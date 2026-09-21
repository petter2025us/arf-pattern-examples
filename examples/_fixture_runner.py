"""One runner, three domains.

Every domain's `test_policy.py` calls this with its own policy and its own
fixtures. That is the claim the repository is making, made executable: the
pipeline does not change between a lending offer and an infrastructure
change. Only the redlines do.

The runner drives the real `GovernanceEngine`, not the policy in isolation,
so each domain test also exercises decision -> audit append -> execute and
leaves a verifiable chain behind.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governance_core import GovernanceEngine, InMemoryAuditLog, Outcome
from governance_core.policy_interface import Policy


def load_cases(fixtures_path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))
    return data["cases"]


def run_case(policy: Policy, case: dict[str, Any]) -> None:
    """Assert one fixture reaches its stated outcome, through the full engine."""
    audit = InMemoryAuditLog()
    engine = GovernanceEngine(policy, audit)
    executed: list[Any] = []

    result = engine.submit(
        case["proposal"], case.get("context", {}), execute=executed.append
    )

    expected = Outcome(case["expect"])
    assert result.decision.outcome is expected, (
        f"{case['name']}: expected {expected.value}, got "
        f"{result.decision.outcome.value} -- {'; '.join(result.decision.reasons)}"
    )

    # The action happens only on APPROVE. Asserted for every case in every
    # domain, because "denied but executed anyway" is the failure the whole
    # pattern exists to prevent and it should be impossible to regress quietly.
    assert executed == ([case["proposal"]] if expected is Outcome.APPROVE else [])

    # One decision in, one entry out, chain intact -- including for refusals.
    # A gate that only records what it permitted has no record of what it
    # stopped, which is usually the part a review is looking for.
    assert len(audit) == 1
    assert audit.verify() is True

    if expected is not Outcome.APPROVE:
        assert result.decision.reasons, f"{case['name']}: refusal with no reason"
