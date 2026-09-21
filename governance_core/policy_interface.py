"""The one thing a domain has to implement.

A policy is a pure function from (proposal, context) to a `Decision`. Same
inputs, same policy version, same outcome -- every time, on every machine.
That is the entire contract, and it is what separates this from asking a
model whether something seems acceptable.

Determinism is a real constraint, not a style note. A policy that consults
the clock, a random number, a mutable global, or a network service it does
not control cannot be replayed, and a decision that cannot be replayed
cannot be audited. If a policy needs the time or an account balance, that
belongs in `context` -- passed in, hashed, and recorded -- not read from
inside `evaluate`.

Policies are free to be probabilistic *about the world*. What they may not
be is non-deterministic about their own verdict: a risk model can produce a
score, and the policy then applies a fixed threshold to it. The score can be
uncertain; the comparison must not be.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from governance_core.decision import Decision


@runtime_checkable
class Policy(Protocol):
    """Deterministic evaluation of a proposed action."""

    #: Stable identifier, e.g. "infrastructure.change".
    policy_id: str
    #: Bump on any change to the rules. It is recorded in every decision, so
    #: a replay can tell "the policy changed" from "the answer changed".
    policy_version: str

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        """Return a Decision. Must not mutate its arguments or perform I/O."""
        ...
