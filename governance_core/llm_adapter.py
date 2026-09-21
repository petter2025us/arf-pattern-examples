"""Where the probabilistic part plugs in.

A proposal generator is anything that produces a candidate action: an LLM, a
planner, a rules-based recommender, a human filling in a form. The pattern
does not care, and that is deliberate -- the gate's job is to be correct
about the proposals it receives, not to know where they came from.

Note what this interface does *not* have: any way to influence the decision.
A generator cannot pass a confidence score that buys it a lower bar, or a
flag that marks a proposal pre-approved. Anything a generator asserts about
itself is an input to be checked, never a permission. That asymmetry is most
of what makes the gate worth having.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class ProposalGenerator(Protocol):
    """Produces a candidate action, optionally informed by prior refusals."""

    def generate(self, feedback: Sequence[str]) -> Mapping[str, Any]:
        """Return a proposal. `feedback` holds the reasons a previous
        proposal was denied, empty on the first attempt."""
        ...


class StaticProposals:
    """A scripted generator: hands back a fixed sequence of proposals.

    Used by the examples and tests so a full run is reproducible without a
    model, a network, or an API key. Every example in this repository runs
    offline for that reason -- a reference implementation you cannot execute
    is a blog post.
    """

    def __init__(self, *proposals: Mapping[str, Any]) -> None:
        if not proposals:
            raise ValueError("StaticProposals needs at least one proposal")
        self._proposals = list(proposals)
        self.seen_feedback: list[list[str]] = []

    def generate(self, feedback: Sequence[str]) -> Mapping[str, Any]:
        self.seen_feedback.append(list(feedback))
        index = min(len(self.seen_feedback) - 1, len(self._proposals) - 1)
        return self._proposals[index]
