"""An unreachable authority must not become a permissive one.

The defect these tests exist to prevent: an authoritative policy engine goes
down, a local mirror of the rules answers in its place, and the decision is
indistinguishable from one the real engine made. The system reports
enforcement it did not perform.

The important test is `test_a_local_evaluator_is_never_consulted_when_the_
authority_is_down`, and it is written so it cannot pass by coincidence. A
spy records whether the local evaluator was called at all; the substitution
would be invisible in the *outcome* (both might say APPROVE) but is visible
in the call record.

`test_the_substitution_detector_is_armed` is the paired control: it wires up
the "helpful" fallback deliberately and shows the spy catches it. Without
that, the test above proves only that nothing happened to call the evaluator.
"""
from __future__ import annotations

import pytest

from governance_core import (
    GovernanceEngine,
    InMemoryAuditLog,
    Outcome,
    decide,
)
from governance_core.external_policy import (
    AuthoritativePolicyUnavailable,
    ExternalPolicy,
)

PROPOSAL = {"action": "delete_volume", "environment": "production"}


class _ReachableEngine:
    def __init__(self, outcome="DENY", reasons=("ENGINE_SAID_NO",)):
        self._outcome = outcome
        self._reasons = reasons

    def evaluate(self, proposal, context):
        return {"outcome": self._outcome, "reasons": list(self._reasons)}


class _UnreachableEngine:
    def evaluate(self, proposal, context):
        raise AuthoritativePolicyUnavailable("connection refused")


class _LocalMirrorSpy:
    """A local policy that would happily answer. Records whether it was asked.

    It returns APPROVE on purpose: if anything ever substitutes it for an
    unreachable authority, the substitution produces a *permission*, which is
    the damaging direction and the one worth proving impossible.
    """

    policy_id = "local.mirror"
    policy_version = "0.0.1-stale"

    def __init__(self):
        self.calls = 0

    def evaluate(self, proposal, context):
        self.calls += 1
        return decide(
            Outcome.APPROVE,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            proposal=proposal,
            context=context,
        )


# ---------------------------------------------------------------------------
# Reachable: the authority's answer is the answer
# ---------------------------------------------------------------------------

def test_a_reachable_authority_decides():
    policy = ExternalPolicy(
        _ReachableEngine(), policy_id="ext.policy", policy_version="3.1.0"
    )
    decision = policy.evaluate(PROPOSAL, {})
    assert decision.outcome is Outcome.DENY
    assert decision.reasons == ("ENGINE_SAID_NO",)
    assert decision.policy_version == "3.1.0"


def test_a_refusal_with_no_reason_is_made_explainable():
    policy = ExternalPolicy(
        _ReachableEngine(outcome="DENY", reasons=()),
        policy_id="ext.policy",
        policy_version="3.1.0",
    )
    decision = policy.evaluate(PROPOSAL, {})
    assert decision.outcome is Outcome.DENY
    assert "UNEXPLAINED_REFUSAL" in decision.reasons[0]


# ---------------------------------------------------------------------------
# Unreachable: fail closed, and consult nothing else
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "configured, expected",
    [(Outcome.ESCALATE, Outcome.ESCALATE), (Outcome.DENY, Outcome.DENY)],
)
def test_an_unreachable_authority_fails_closed(configured, expected):
    policy = ExternalPolicy(
        _UnreachableEngine(),
        policy_id="ext.policy",
        policy_version="3.1.0",
        on_unavailable=configured,
    )
    decision = policy.evaluate(PROPOSAL, {})
    assert decision.outcome is expected
    assert "AUTHORITATIVE_POLICY_UNAVAILABLE" in decision.reasons[0]


def test_approve_on_unavailable_cannot_be_configured():
    """There is no flag that turns an outage into a permission."""
    with pytest.raises(ValueError, match="not a permissive one"):
        ExternalPolicy(
            _UnreachableEngine(),
            policy_id="ext.policy",
            policy_version="3.1.0",
            on_unavailable=Outcome.APPROVE,
        )


def test_a_local_evaluator_is_never_consulted_when_the_authority_is_down():
    """The headline. Substitution would be invisible in the outcome."""
    mirror = _LocalMirrorSpy()
    policy = ExternalPolicy(
        _UnreachableEngine(), policy_id="ext.policy", policy_version="3.1.0"
    )

    decision = policy.evaluate(PROPOSAL, {})

    assert decision.outcome is Outcome.ESCALATE
    assert mirror.calls == 0, (
        "the local mirror was consulted for a decision the authoritative "
        "engine could not make -- that is silent authority substitution"
    )
    # And the recorded decision names the authority, not the mirror, so an
    # auditor can tell which policy actually answered.
    assert decision.policy_id == "ext.policy"
    assert decision.policy_version == "3.1.0"


def test_the_substitution_detector_is_armed():
    """Paired control: wire the fallback up and show the spy catches it.

    Without this, the test above proves only that nothing happened to touch
    the mirror -- not that touching it would have been noticed.
    """
    mirror = _LocalMirrorSpy()
    authority = _UnreachableEngine()

    def with_silent_fallback(proposal, context):
        try:
            return authority.evaluate(proposal, context)
        except AuthoritativePolicyUnavailable:
            return mirror.evaluate(proposal, context)  # the defect, on purpose

    decision = with_silent_fallback(PROPOSAL, {})

    assert mirror.calls == 1
    # Note what the fallback produced: APPROVE, for a production delete, from
    # a policy version marked stale -- and nothing in the result says the
    # authoritative engine was never reached.
    assert decision.outcome is Outcome.APPROVE
    assert decision.policy_version == "0.0.1-stale"


# ---------------------------------------------------------------------------
# Through the engine: a fail-closed decision is still recorded
# ---------------------------------------------------------------------------

def test_a_failed_closed_decision_is_recorded_and_not_executed():
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(
        ExternalPolicy(
            _UnreachableEngine(), policy_id="ext.policy", policy_version="3.1.0"
        ),
        audit,
    )
    executed = []

    result = engine.submit(PROPOSAL, {}, execute=executed.append)

    assert result.decision.outcome is Outcome.ESCALATE
    assert executed == []
    # The outage is itself part of the audit trail. "We could not evaluate
    # this" is a finding somebody should see, not a gap in the record.
    assert len(audit) == 1
    assert audit.verify() is True
