"""The IP-boundary guard, and proof that it is armed.

A scanner that reports nothing is indistinguishable from a scanner that
cannot report anything. `test_the_guard_is_armed` is what separates the two:
it feeds the scanner material it must reject and fails if the scanner stays
quiet. Without it, `test_the_repository_is_clean` proves only that nothing
happened to trip a guard that might be broken.

## Why the planted material is assembled rather than written out

This file is tracked, and `scan_tree()` reads tracked files. Written
literally, the fixtures below would make the repository fail its own scan --
and the tempting fix, exempting this file, would create a second hole beside
the scanner's own. Exemptions are where things get parked.

So every fixture is assembled at import time from fragments split across the
join, and no private identifier or architectural phrase exists as a literal
string anywhere in the repository. The scanner keeps exactly one exclusion,
its own pattern table, and `test_the_scanner_excludes_only_itself` pins that.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

from ip_boundary_scan import SELF, scan_text, scan_tree  # noqa: E402


def _p(*parts: str) -> str:
    """Join fragments into planted material.

    Each call is split at a point that breaks every pattern it is meant to
    trip, so the literal never appears on a line of this file.
    """
    return "".join(parts)


# Must be caught. Written as fragments; see the module docstring.
MUST_BE_CAUGHT = [
    _p("from arf_", "enterprise.executor import EnterpriseExecutor"),
    _p("registry.consume(admission", "_id)"),
    _p("the Admission", "Token is bound to the envelope", "_hash"),
    _p("import agentic_", "reliability_framework"),
    _p("the authorization is minted from a durably committed ", "audit entry"),
    _p("consumption is an atomic compare", "-and-swap against durable state"),
    _p("an outcome that is unknown lands in a reconcilable ", "state"),
    _p("per-process state instead of a durable authority ", "store"),
    _p("Bayesian risk ", "fusion with epistemic", "-uncertainty gating"),
    _p("the CU", "DL threshold governs escalation"),
    _p("NoOr", "Bypass holds for every reachable state"),
    _p("see the TL", "A+ specification for the distributivity ", "witness"),
    _p("AWS_SECRET_ACCESS_KEY=", "wJalrXUtnFEMIKB7MDENGbPxRfiCYEXAMPLEKEY123"),
    _p("pip install git", "+https://github.com/example/private-thing.git"),
]

# Must NOT be caught. This half keeps the guard usable: it is the vocabulary
# the repository is written in, and a guard that rejected it would be
# switched off rather than obeyed.
MUST_BE_ALLOWED = [
    "Every decision produces an audit record.",
    "The policy returns APPROVE, DENY or ESCALATE.",
    "Authorization is deterministic: same inputs, same answer.",
    "Risk estimation is a different job from a deterministic gate.",
    "Execution happens only after the decision is durable.",
    "A signature can establish authenticity; a hash chain cannot.",
    "The engine appends to the audit log before it executes.",
    "This repository does not reproduce ARF AI's proprietary risk engine,",
    "its authority and execution-admission mechanisms, or enterprise actuators.",
]


def test_the_repository_is_clean():
    findings = scan_tree()
    assert findings == [], "\n".join(
        f"{f.path}:{f.line} [{f.category}] {f.pattern}" for f in findings
    )


def test_the_guard_is_armed():
    """Paired control. Each planted line must produce at least one finding."""
    missed = [
        line for line in MUST_BE_CAUGHT if not scan_text("planted.md", line)
    ]
    assert missed == [], (
        "the guard did not catch material it must reject; it would report a "
        f"clean repository while these were present: {missed}"
    )


def test_the_guard_is_not_over_broad():
    tripped = [
        (line, [f.pattern for f in scan_text("ok.md", line)])
        for line in MUST_BE_ALLOWED
        if scan_text("ok.md", line)
    ]
    assert tripped == [], (
        "the guard rejected ordinary governance vocabulary. An over-broad rule "
        f"trains everyone around it to route past the gate: {tripped}"
    )


def test_a_planted_file_on_disk_is_caught(tmp_path):
    """End to end through a real file, not only the pure function."""
    planted = tmp_path / "leak.md"
    planted.write_text(
        "# notes\n\n" + MUST_BE_CAUGHT[4] + "\n", encoding="utf-8"
    )
    findings = scan_text("leak.md", planted.read_text(encoding="utf-8"))
    assert findings, "a file containing private architecture was reported clean"
    assert findings[0].line == 3


def test_the_scanner_excludes_only_itself():
    """The exclusion list is the obvious hiding place, so it is pinned.

    The scanner cannot scan its own pattern table without matching every
    pattern in it. That one exemption is necessary; a second one would not
    be, and would be the natural place to park something.
    """
    assert SELF == "tools/ip_boundary_scan.py"
    assert scan_text(SELF, MUST_BE_CAUGHT[0]) == []
    assert scan_text("anything/else.py", MUST_BE_CAUGHT[0])


def test_no_fixture_leaks_into_the_tracked_tree():
    """The assembly trick must actually work.

    If a fragment split stopped breaking its pattern, this file would become
    the leak, and `test_the_repository_is_clean` would be the only thing
    standing between that and a push. This says so directly.
    """
    here = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert scan_text("tests/test_ip_boundary.py", here) == []
