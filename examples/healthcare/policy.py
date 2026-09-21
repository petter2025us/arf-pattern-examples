"""Prior-authorization decisions -- an illustrative policy example.

**Not medical, clinical, legal, or regulatory advice.** The codes, rules and
thresholds below are invented for demonstration. No real plan's criteria are
reproduced, and nothing here establishes compliance with anything. It is
included because prior authorization has the shape the pattern suits: a
consequential decision, hard eligibility rules that must not be delegated to
a model's judgment, and a genuine need to explain any refusal afterwards.

The proposed action is "approve this authorization", not "write some text".

The rule worth noticing is the third one. Missing clinical documentation is
ESCALATE, never DENY. A denial says the request is ineligible; an escalation
says nobody has yet established whether it is. Collapsing the second into
the first denies care for a filing gap, which is both wrong and the kind of
wrong that is invisible in aggregate statistics.
"""
from __future__ import annotations

from typing import Any, Mapping

from governance_core.decision import Decision, Outcome, decide

POLICY_ID = "healthcare.prior_auth"
POLICY_VERSION = "1.0.0"

#: Invented for the example: procedure -> diagnoses that can justify it.
PROCEDURE_DIAGNOSIS_RULES: dict[str, frozenset[str]] = {
    "PROC-MRI-LUMBAR": frozenset({"DX-LBP-CHRONIC", "DX-RADICULOPATHY"}),
    "PROC-SLEEP-STUDY": frozenset({"DX-OSA-SUSPECTED", "DX-HYPERSOMNIA"}),
    "PROC-KNEE-ARTHRO": frozenset({"DX-MENISCAL-TEAR"}),
}

REQUIRED_DOCUMENTATION: dict[str, tuple[str, ...]] = {
    "PROC-MRI-LUMBAR": ("conservative_therapy_weeks",),
    "PROC-KNEE-ARTHRO": ("imaging_report",),
}


class PriorAuthorizationPolicy:
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

        procedure = str(proposal.get("procedure_code", ""))
        diagnosis = proposal.get("diagnosis_code")
        member = proposal.get("member") or {}

        if procedure not in PROCEDURE_DIAGNOSIS_RULES:
            return verdict(
                Outcome.ESCALATE,
                f"PROCEDURE_NOT_IN_RULESET: {procedure or '<missing>'} has no "
                "deterministic criteria here; an unknown procedure is not an "
                "approvable one, and it is not a denial either",
            )

        if not member.get("coverage_active", False):
            return verdict(
                Outcome.DENY,
                "COVERAGE_INACTIVE: the member's coverage is not active for the "
                "requested service date",
            )

        if diagnosis is None:
            return verdict(
                Outcome.ESCALATE,
                "DIAGNOSIS_MISSING: no diagnosis was supplied, so the "
                "procedure-diagnosis rule cannot be applied",
            )

        allowed = PROCEDURE_DIAGNOSIS_RULES[procedure]
        if diagnosis not in allowed:
            return verdict(
                Outcome.DENY,
                f"DIAGNOSIS_DOES_NOT_SUPPORT_PROCEDURE: {diagnosis} is not among "
                f"{sorted(allowed)} for {procedure}",
            )

        missing = [
            field
            for field in REQUIRED_DOCUMENTATION.get(procedure, ())
            if (proposal.get("documentation") or {}).get(field) in (None, "")
        ]
        if missing:
            return verdict(
                Outcome.ESCALATE,
                f"DOCUMENTATION_INCOMPLETE: missing {', '.join(missing)}; this is "
                "an unanswered question, not an ineligible request",
            )

        return verdict(Outcome.APPROVE)
