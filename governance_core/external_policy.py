"""Delegating to an authoritative external policy engine, without failing open.

When the policy that governs a decision lives somewhere else -- OPA, Cedar, a
policy service -- the interesting question is not the happy path. It is what
happens when that engine cannot be reached.

The tempting answer is to keep a local mirror of the rules and evaluate
against it when the authoritative engine is down, so the system stays
available. **This module refuses to do that**, and the refusal is the whole
point of the file.

## Why a local fallback is silent authority substitution

A local mirror is a copy of the rules as they were when someone last synced
it. The authoritative engine is the rules as they are. Those differ exactly
when it matters most: after a policy was tightened and before the mirror
caught up. Falling back means answering a question nobody asked -- "what
would the old rules have said?" -- and returning it as though it were the
answer to "what do the rules say?".

It also fails in the dangerous direction. An outage in the policy engine
becomes an outage in *enforcement*, and nothing in the response says so. The
decision looks identical to one the authoritative engine made.

This is the same shape as any system quietly substituting an in-memory
stand-in for an unreachable dependency: the thing that cannot be reached is
replaced by something that can, and the substitution is invisible in the
output. A missing authority is not a permissive authority.

## What this does instead

Unreachable authoritative engine -> `ESCALATE` by default, or `DENY` in
strict mode. Both are honest: the system is saying it could not establish
whether the action is permitted, and is declining to guess.

A local Python policy remains perfectly usable -- as *the* policy, chosen
explicitly at construction, for development and for the examples in this
repository. What it may never be is a hidden understudy that walks on when
the real one is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Protocol, runtime_checkable

from governance_core.decision import Decision, Outcome, decide

logger = logging.getLogger("governance_core.external")


class AuthoritativePolicyUnavailable(RuntimeError):
    """The external engine could not be reached, or gave an unusable answer."""


@runtime_checkable
class ExternalPolicyClient(Protocol):
    """Transport to an authoritative policy engine.

    Implementations raise `AuthoritativePolicyUnavailable` (or any exception)
    when the engine cannot be reached. They must not invent a verdict.
    """

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Return the engine's raw result: at minimum `{"outcome": ...}`."""
        ...


class ExternalPolicy:
    """A `Policy` backed by an authoritative external engine. Fails closed.

    `on_unavailable` chooses between the two honest answers:

    - `ESCALATE` (default) -- "I could not establish whether this is
      permitted." Right when a human can pick the decision up, which is the
      usual case for a governance gate.
    - `DENY` -- right when there is no one to escalate to and the action must
      simply not happen unattended.

    `APPROVE` is not accepted, and the constructor rejects it. There is no
    configuration of this class that turns a policy-engine outage into a
    permission, because a flag that can do that will eventually be set.
    """

    def __init__(
        self,
        client: ExternalPolicyClient,
        *,
        policy_id: str,
        policy_version: str,
        on_unavailable: Outcome = Outcome.ESCALATE,
    ) -> None:
        if on_unavailable is Outcome.APPROVE:
            raise ValueError(
                "on_unavailable=APPROVE would turn a policy-engine outage into "
                "a permission. An unreachable authority is not a permissive "
                "one; choose ESCALATE or DENY."
            )
        self._client = client
        self.policy_id = policy_id
        self.policy_version = policy_version
        self._on_unavailable = on_unavailable

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        try:
            raw = self._client.evaluate(proposal, context)
            outcome = Outcome(str(raw["outcome"]))
            reasons = tuple(str(r) for r in (raw.get("reasons") or ()))
        except Exception as exc:  # noqa: BLE001 - any transport or shape failure
            # Deliberately broad. A malformed response is as much "I did not
            # get an answer" as a refused connection, and distinguishing them
            # here would only create a branch where one of them falls through.
            logger.error(
                "authoritative policy %s unavailable: %s; answering %s rather "
                "than substituting another evaluator",
                self.policy_id,
                exc,
                self._on_unavailable.value,
            )
            return decide(
                self._on_unavailable,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                proposal=proposal,
                context=context,
                reasons=(
                    f"AUTHORITATIVE_POLICY_UNAVAILABLE: {self.policy_id} "
                    f"v{self.policy_version} could not be evaluated ({exc}). "
                    "No local evaluator was consulted: a mirror answers what "
                    "the rules used to say, not what they say.",
                ),
            )

        if outcome is not Outcome.APPROVE and not reasons:
            # The engine refused without saying why. Treat that as an
            # unusable answer rather than passing an unexplainable refusal
            # downstream -- `Decision` would reject it anyway, and a crash
            # here would read as a bug in this module.
            reasons = (
                f"UNEXPLAINED_REFUSAL: {self.policy_id} returned "
                f"{outcome.value} with no reasons",
            )

        return decide(
            outcome,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            proposal=proposal,
            context=context,
            reasons=reasons,
        )
