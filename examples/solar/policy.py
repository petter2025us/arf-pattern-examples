"""Residential solar sales claims -- the original example, ported.

The proposed action is "send this proposal to this customer". The redlines
are claims that are false or unsubstantiable for *this* customer, which is
why the policy reads the customer record and not just the text.

Two rules carry the weight:

**Guaranteed tax-credit language to a customer with no tax liability.** The
federal ITC is a credit against tax owed, not a rebate. Promising it as
guaranteed cash to a zero-liability household is a real compliance problem,
and the LLM has no way to know the household's liability from the prompt.

**"Eliminate 100% of your bill" under avoided-cost export pricing** with no
battery. Under NEM 3.0, exported solar is bought back at a fraction of
retail, so a no-battery system generally cannot support a 100%-offset claim.

## A real bug this caught, kept because it is instructive

The first version of the guarantee detector flagged any mention of a dollar
sign or "30%". That is wrong, and wrong in the most damaging direction: it
would have blocked the exact hedged rewrite the policy exists to produce.

    "you may qualify for up to a 30% Federal ITC, depending on your
     personal tax liability"

legitimately mentions a percentage and is not a guarantee. The fix was to
match phrases that assert certainty -- `guarantee`, `you will receive`,
`will get back` -- rather than any adjacent number. Both cases are pinned by
tests so it cannot silently regress.

The general lesson outlives solar: an over-broad redline is not "safely
strict". It trains everyone around it to route past the gate.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from governance_core.decision import Decision, Outcome, decide

POLICY_ID = "solar.sales_claims"
POLICY_VERSION = "2.0.0"

MIN_PRICE_PER_WATT = 2.60
MAX_PRICE_PER_WATT = 5.20
MAX_DEALER_FEE_PERCENT = 25.0

#: Territories on avoided-cost export pricing, where a no-battery system
#: cannot generally support a full-offset claim.
AVOIDED_COST_UTILITIES = frozenset({"PG&E", "SCE", "SDG&E"})

# Certainty, not arithmetic. See the module docstring -- this narrowness is
# the whole fix, and widening it back to "any number" re-breaks the hedged
# rewrite the policy is supposed to produce.
_GUARANTEE_RE = re.compile(
    r"\b(guarantee[ds]?|you will receive|will get back|guaranteed refund)\b",
    re.IGNORECASE,
)
# No trailing \b. The first draft had one, and it silently disabled the
# branch that matters most: `100%` ends in a non-word character, so there is
# no word boundary after it, and `eliminate 100% of your bill` never matched
# at all. The test suite caught it on the first run -- but a regex that
# matches nothing fails *open*, so in a deployment without that fixture this
# would have looked like a working redline while permitting every claim it
# was written to stop. Worth keeping as a comment: the dangerous direction
# for a pattern bug is silence, not noise.
_FULL_ELIMINATION_RE = re.compile(
    r"\b(eliminat\w*\s+(100%|all|your entire)|zero\s+electric(ity)?\s+bill|"
    r"no more electric(ity)?\s+bill|100%\s+of your bill)",
    re.IGNORECASE,
)


class SolarClaimsPolicy:
    """Deterministic gate for a customer-facing solar proposal."""

    policy_id = POLICY_ID
    policy_version = POLICY_VERSION

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        reasons: list[str] = []
        pricing = proposal.get("pricing") or {}
        customer = proposal.get("customer") or {}
        design = proposal.get("system_design") or {}
        claims = proposal.get("claims") or []

        price_per_watt = pricing.get("price_per_watt")
        if price_per_watt is None:
            reasons.append(
                "PRICE_MISSING: price per watt was not supplied, so neither "
                "the floor nor the ceiling can be applied"
            )
        else:
            if price_per_watt > MAX_PRICE_PER_WATT:
                reasons.append(
                    f"PRICE_CEILING_EXCEEDED: ${price_per_watt:.2f}/W is above the "
                    f"${MAX_PRICE_PER_WATT:.2f}/W ceiling"
                )
            if price_per_watt < MIN_PRICE_PER_WATT:
                reasons.append(
                    f"PRICE_FLOOR_BREACHED: ${price_per_watt:.2f}/W is below the "
                    f"${MIN_PRICE_PER_WATT:.2f}/W floor, which cannot cover install cost"
                )

        dealer_fee = pricing.get("dealer_fee_percent")
        if dealer_fee is not None and dealer_fee > MAX_DEALER_FEE_PERCENT:
            reasons.append(
                f"DEALER_FEE_EXCEEDED: {dealer_fee:.1f}% is above the "
                f"{MAX_DEALER_FEE_PERCENT:.1f}% cap"
            )

        tax_liability = customer.get("estimated_tax_liability")
        for claim in claims:
            text = str(claim.get("text", ""))

            if _GUARANTEE_RE.search(text) and "tax" in text.lower():
                if tax_liability is None:
                    reasons.append(
                        "TAX_LIABILITY_UNKNOWN: a guaranteed tax-credit claim was "
                        "made and the customer's liability is unknown"
                    )
                elif tax_liability <= 0:
                    reasons.append(
                        "TAX_GUARANTEE_TO_ZERO_LIABILITY: the ITC offsets tax owed; "
                        "this household owes none, so the credit is not the cash "
                        "this claim promises"
                    )

            if _FULL_ELIMINATION_RE.search(text):
                utility = customer.get("utility_provider")
                if utility in AVOIDED_COST_UTILITIES and not design.get(
                    "has_battery_storage"
                ):
                    reasons.append(
                        f"FULL_OFFSET_UNSUPPORTABLE: a 100%-offset claim in {utility} "
                        "territory with no battery; exports are bought at "
                        "avoided cost, well below retail"
                    )

        def verdict(outcome: Outcome, *extra: str) -> Decision:
            return decide(
                outcome,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                proposal=proposal,
                context=context,
                reasons=tuple(reasons) + extra,
            )

        if not reasons:
            return verdict(Outcome.APPROVE)

        # A missing input is a question for a human; a violated redline is a
        # refusal. Keeping them apart means "we could not check" never reads
        # as "we checked and it was fine", and never as "this is forbidden".
        unknowns = [r for r in reasons if "_UNKNOWN" in r or "_MISSING" in r]
        if len(unknowns) == len(reasons):
            return verdict(Outcome.ESCALATE)
        return verdict(Outcome.DENY)
