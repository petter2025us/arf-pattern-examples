"""The interceptor's guarantees: what runs, what is recorded, and in what order.

The ordering test is the one that matters. It does not observe that both
things happened -- it makes the executor *fail* if the decision was not
already in the log when it was called. An assertion written after the fact
would keep passing if a future edit moved the append below the execute,
because both events would still have occurred.
"""
from __future__ import annotations

import pytest

from governance_core import (
    Decision,
    GovernanceEngine,
    InMemoryAuditLog,
    Outcome,
    StaticProposals,
    decide,
    govern_with_revision,
)


class _FixedPolicy:
    """Returns a scripted outcome per call, so tests drive the engine, not a domain."""

    policy_id = "test.fixed"
    policy_version = "1.0.0"

    def __init__(self, *outcomes: Outcome) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def evaluate(self, proposal, context) -> Decision:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        return decide(
            outcome,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            proposal=proposal,
            context=context,
            reasons=() if outcome is Outcome.APPROVE else (f"REFUSED_{self.calls}",),
        )


def test_the_decision_is_durable_before_the_action_happens():
    """Ordering guard, armed rather than observed."""
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(_FixedPolicy(Outcome.APPROVE), audit)

    def execute(proposal):
        # If the append had not happened yet, the log would be empty here.
        # Raising makes the wrong order impossible to pass, rather than
        # merely visible afterwards.
        if len(audit) == 0:
            raise AssertionError(
                "executed before the decision was recorded: an action with no "
                "durable record is the failure this ordering exists to prevent"
            )
        return "done"

    result = engine.submit({"action": "x"}, {}, execute=execute)
    assert result.executed is True
    assert result.execution_result == "done"
    assert len(audit) == 1


def test_the_ordering_guard_is_armed():
    """Negative control for the test above.

    Calling the executor with an empty log is exactly the shape of the defect
    the previous test rules out. If this does not raise, that test proves
    nothing.
    """
    audit = InMemoryAuditLog()

    def execute(proposal):
        if len(audit) == 0:
            raise AssertionError("executed before the decision was recorded")
        return "done"

    with pytest.raises(AssertionError, match="before the decision was recorded"):
        execute({"action": "x"})


@pytest.mark.parametrize("outcome", [Outcome.DENY, Outcome.ESCALATE])
def test_a_refused_proposal_is_recorded_but_not_executed(outcome):
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(_FixedPolicy(outcome), audit)
    executed = []

    result = engine.submit({"action": "x"}, {}, execute=executed.append)

    assert result.decision.outcome is outcome
    assert result.executed is False
    assert executed == []
    assert len(audit) == 1  # the refusal is the interesting record
    assert audit.verify() is True


def test_approval_without_an_executor_does_not_claim_to_have_executed():
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(_FixedPolicy(Outcome.APPROVE), audit)
    result = engine.submit({"action": "x"}, {})
    assert result.decision.outcome is Outcome.APPROVE
    assert result.executed is False  # permitted is not the same as performed


def test_a_denied_proposal_can_be_revised_and_then_approved():
    audit = InMemoryAuditLog()
    policy = _FixedPolicy(Outcome.DENY, Outcome.APPROVE)
    engine = GovernanceEngine(policy, audit)
    generator = StaticProposals({"draft": 1}, {"draft": 2})
    executed = []

    result = govern_with_revision(
        engine, generator.generate, execute=executed.append, max_attempts=3
    )

    assert result.decision.outcome is Outcome.APPROVE
    assert result.attempts == 2
    assert executed == [{"draft": 2}]
    # Both attempts recorded: the rejected draft is part of the story.
    assert len(audit) == 2
    assert audit.verify() is True
    # The refusal reasons were handed back to the generator.
    assert generator.seen_feedback[1] == ["REFUSED_1"]


def test_exhausting_revisions_escalates_rather_than_denying():
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(_FixedPolicy(Outcome.DENY), audit)
    executed = []

    result = govern_with_revision(
        engine,
        StaticProposals({"draft": 1}).generate,
        execute=executed.append,
        max_attempts=2,
    )

    # "the generator could not produce something admissible" is a different
    # finding from "this action is forbidden", and only the first is usefully
    # handed to a person.
    assert result.decision.outcome is Outcome.ESCALATE
    assert "UNRESOLVED_AFTER_2_ATTEMPTS" in result.decision.reasons[0]
    assert executed == []
    assert len(audit) == 3  # two refusals plus the escalation
    assert audit.verify() is True


def test_an_escalation_stops_revision_immediately():
    """Re-prompting a generator is not the higher authority the policy asked for."""
    audit = InMemoryAuditLog()
    policy = _FixedPolicy(Outcome.ESCALATE, Outcome.APPROVE)
    engine = GovernanceEngine(policy, audit)

    result = govern_with_revision(
        engine, StaticProposals({"draft": 1}, {"draft": 2}).generate, max_attempts=3
    )

    assert result.decision.outcome is Outcome.ESCALATE
    assert result.attempts == 1
    assert policy.calls == 1


def test_a_decision_that_cannot_be_explained_is_rejected_at_construction():
    with pytest.raises(ValueError, match="must carry at least one reason"):
        Decision(outcome=Outcome.DENY, policy_id="p", policy_version="1")
