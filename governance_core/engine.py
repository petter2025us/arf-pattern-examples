"""The interceptor: propose -> decide -> record -> execute.

The ordering is the design, and it is the one thing to copy if you copy
nothing else:

    evaluate
       |
    Decision
       |
    AuditLog.append()      <- durable BEFORE anything happens
       |
    execute()

Not `execute, then log if it worked`. If the record is written after the
action, then every crash, timeout, and process kill in between produces an
action nobody has a record of -- and those are exactly the moments a record
matters most. Writing first means the worst case is a record of an action
that did not happen, which is a discrepancy you can find and resolve. The
other order produces an action nobody can find at all.

**This is an educational simplification.** ARF AI's production implementation
contains additional private controls that are intentionally not reproduced
here, and this file should not be read as a description of them. What *is*
reproduced is the ordering principle, which is portable, independently
useful, and which most systems get wrong in the cheap direction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from governance_core.audit import AuditLog
from governance_core.decision import Decision, Outcome
from governance_core.policy_interface import Policy

logger = logging.getLogger("governance_core")

#: Called with the approved proposal. Whatever actually does the thing:
#: sends the email, calls the cloud API, writes the authorization.
Executor = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class GovernanceResult:
    decision: Decision
    entry_hash: str
    executed: bool
    execution_result: Any = None
    attempts: int = 1

    @property
    def outcome(self) -> Outcome:
        return self.decision.outcome


class GovernanceEngine:
    """Wraps a policy and an audit log around a proposed action."""

    def __init__(self, policy: Policy, audit_log: AuditLog) -> None:
        self._policy = policy
        self._audit = audit_log

    @property
    def audit(self) -> AuditLog:
        """The log this engine writes to. Exposed so a caller can verify
        the chain, and so helpers need not reach into a private field."""
        return self._audit

    def submit(
        self,
        proposal: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        execute: Executor | None = None,
    ) -> GovernanceResult:
        """Evaluate one proposal, record the decision, then execute if approved."""
        context = dict(context or {})
        decision = self._policy.evaluate(proposal, context)

        # Durable first. Everything below depends on this having happened.
        entry_hash = self._audit.append(decision)

        if decision.outcome is not Outcome.APPROVE:
            logger.info(
                "%s: %s (%s)",
                decision.outcome.value,
                "; ".join(decision.reasons),
                decision.policy_id,
            )
            return GovernanceResult(decision, entry_hash, executed=False)

        if execute is None:
            # Approved, nothing wired up to act on it. Distinct from having
            # executed -- `executed=False` says so rather than implying the
            # action happened because it was permitted to.
            return GovernanceResult(decision, entry_hash, executed=False)

        return GovernanceResult(
            decision, entry_hash, executed=True, execution_result=execute(proposal)
        )


def govern_with_revision(
    engine: GovernanceEngine,
    generate: Callable[[Sequence[str]], Mapping[str, Any]],
    context: Mapping[str, Any] | None = None,
    execute: Executor | None = None,
    max_attempts: int = 2,
) -> GovernanceResult:
    """Let a generator revise a DENIED proposal, bounded, then escalate.

    Retrying is *one* possible response to DENY, not the point of the
    pattern, and it is optional on purpose. The centrepiece is that the
    policy decides whether a proposal is executable; asking the generator to
    try again is just what a caller may choose to do with a refusal. Other
    callers stop, or route to a human, or pick a different action entirely.

    An attempt that exhausts its budget ends as ESCALATE rather than DENY:
    "the generator could not produce something admissible" is a different
    finding from "this action is forbidden", and only the first one is
    usefully handed to a person.

    Every attempt is separately evaluated and separately recorded. The log
    shows the rejected drafts, which is usually the interesting part of a
    review -- what the system tried to do and was stopped from doing.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    feedback: list[str] = []
    last: GovernanceResult | None = None

    for attempt in range(1, max_attempts + 1):
        proposal = generate(feedback)
        result = engine.submit(proposal, context, execute=execute)
        last = result

        if result.decision.outcome is Outcome.APPROVE:
            return GovernanceResult(
                result.decision,
                result.entry_hash,
                result.executed,
                result.execution_result,
                attempts=attempt,
            )
        if result.decision.outcome is Outcome.ESCALATE:
            # The policy asked for a higher authority. Re-prompting a
            # generator is not that authority, so revision stops here.
            return GovernanceResult(
                result.decision, result.entry_hash, False, None, attempts=attempt
            )
        feedback = list(result.decision.reasons)

    assert last is not None
    escalation = Decision(
        outcome=Outcome.ESCALATE,
        policy_id=last.decision.policy_id,
        policy_version=last.decision.policy_version,
        reasons=(
            f"UNRESOLVED_AFTER_{max_attempts}_ATTEMPTS: last refusal was "
            + "; ".join(last.decision.reasons),
        ),
        proposal_hash=last.decision.proposal_hash,
        context_hash=last.decision.context_hash,
    )
    entry_hash = engine.audit.append(escalation)
    return GovernanceResult(escalation, entry_hash, False, None, attempts=max_attempts)
