"""Consumer lending offers -- an illustrative policy example.

**Not legal, financial, underwriting, or regulatory advice.** The ceilings,
fee names and thresholds are invented for demonstration. Nothing here
reproduces any lender's criteria or establishes compliance with anything.

The proposed action is "extend this offer at these terms". Lending earns its
place in this repository because two of its redlines are unusually crisp --
a rate ceiling is a number comparison, and a prohibited fee is a set
membership test -- while the third, affordability, is exactly the kind of
judgment that should escalate rather than resolve itself.
"""
from __future__ import annotations

from typing import Any, Mapping

from governance_core.decision import Decision, Outcome, decide

POLICY_ID = "lending.offer"
POLICY_VERSION = "1.0.0"

APR_CEILING_PERCENT = 29.99
MAX_DEBT_TO_INCOME = 0.43
PROHIBITED_FEES = frozenset({"prepayment_penalty", "mandatory_arbitration_fee"})


class LendingOfferPolicy:
    policy_id = POLICY_ID
    policy_version = POLICY_VERSION

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        def verdict(outcome: Outcome, *reasons: str) -> Decision:
            return decide(
                outcome,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                proposal=proposal,
                context=context,
                reasons=reasons,
            )

        apr = proposal.get("apr_percent")
        if apr is None:
            return verdict(
                Outcome.ESCALATE, "APR_MISSING: no rate was supplied to check"
            )
        if float(apr) > APR_CEILING_PERCENT:
            return verdict(
                Outcome.DENY,
                f"APR_CEILING_EXCEEDED: {apr}% is above the configured "
                f"{APR_CEILING_PERCENT}% ceiling",
            )

        offered = {str(f) for f in (proposal.get("fees") or [])}
        prohibited = sorted(offered & PROHIBITED_FEES)
        if prohibited:
            return verdict(
                Outcome.DENY,
                f"PROHIBITED_FEE: {', '.join(prohibited)} may not appear in an offer",
            )

        dti = proposal.get("debt_to_income")
        if dti is None:
            return verdict(
                Outcome.ESCALATE,
                "AFFORDABILITY_INPUTS_MISSING: debt-to-income was not supplied, so "
                "affordability was never assessed -- an unassessed offer is not a "
                "safe one, and it is not a refusal either",
            )
        if float(dti) > MAX_DEBT_TO_INCOME:
            return verdict(
                Outcome.ESCALATE,
                f"DEBT_TO_INCOME_ABOVE_THRESHOLD: {dti:.2f} exceeds "
                f"{MAX_DEBT_TO_INCOME:.2f}; a human decides whether compensating "
                "factors justify it",
            )

        return verdict(Outcome.APPROVE)
