"""What a deterministic policy returns.

The vocabulary is `APPROVE` / `DENY` / `ESCALATE` rather than allow/block,
because the thing being decided is whether a *proposed action* may proceed --
not whether a piece of text is acceptable. That distinction is the whole
point of the pattern: an agent proposes a consequential action, and a
deterministic policy decides whether it executes.

A `Decision` carries the evidence needed to explain and reproduce itself.
An outcome on its own is not auditable: six months later, "DENY" tells a
reviewer nothing, while "DENY, policy `solar.claims` v3, because
TAX_GUARANTEE_TO_ZERO_LIABILITY, on this exact proposal" tells them
everything. The hashes are what make a replay checkable -- feed the same
proposal and context to the same policy version and you must get the same
outcome.

This is a public reference implementation of a pattern. It is deliberately
NOT a miniature copy of ARF's internal decision record, which carries fields
this has no business reproducing.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class Outcome(str, Enum):
    """The three things a deterministic gate can conclude.

    `ESCALATE` is not a softer `DENY`. It means the policy established that
    it is *not the right authority* to decide -- the inputs needed are
    missing, or the action is above the bar this policy is allowed to clear
    on its own. Collapsing it into DENY loses the distinction between "this
    is forbidden" and "this needs someone else", which is precisely the
    distinction a human reviewer needs in order to act.
    """

    APPROVE = "APPROVE"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


def canonical_json(value: Any) -> str:
    """Stable bytes for a structure, so hashes are reproducible.

    `sort_keys` plus tight separators means two structurally identical
    payloads hash identically regardless of key order or the whitespace
    whatever produced them happened to emit. Without this, a hash chain
    verifies only against the exact serializer that wrote it.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Decision:
    """A deterministic policy's verdict, with the evidence to re-check it."""

    outcome: Outcome
    policy_id: str
    policy_version: str
    reasons: tuple[str, ...] = ()
    proposal_hash: str = ""
    context_hash: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        # A DENY or ESCALATE with no reason is unusable by the person who has
        # to act on it, and unreviewable by an auditor. APPROVE may be silent.
        if self.outcome is not Outcome.APPROVE and not self.reasons:
            raise ValueError(
                f"{self.outcome.value} must carry at least one reason: an "
                "outcome a reviewer cannot explain is not auditable."
            )

    @property
    def approved(self) -> bool:
        return self.outcome is Outcome.APPROVE

    def to_entry(self) -> dict[str, Any]:
        """The audit-log shape. Ordering is irrelevant -- `canonical_json`
        sorts -- but the field set is what gets hashed, so it is explicit."""
        return {
            "outcome": self.outcome.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
            "proposal_hash": self.proposal_hash,
            "context_hash": self.context_hash,
            "timestamp": self.timestamp,
        }


def decide(
    outcome: Outcome,
    *,
    policy_id: str,
    policy_version: str,
    proposal: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
    reasons: Sequence[str] = (),
) -> Decision:
    """Build a `Decision`, hashing the inputs it was made from.

    Policies call this rather than constructing `Decision` directly, so every
    policy in every domain hashes its inputs the same way. A per-policy
    hashing convention would make two logs incomparable.
    """
    return Decision(
        outcome=outcome,
        policy_id=policy_id,
        policy_version=policy_version,
        reasons=tuple(reasons),
        proposal_hash=digest(proposal),
        context_hash=digest(context or {}),
    )
