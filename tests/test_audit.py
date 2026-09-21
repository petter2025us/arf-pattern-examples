"""The audit chain, including the demonstration that makes it worth having.

The headline is `test_modifying_a_past_entry_breaks_the_chain`: write three
decisions, verify (passes), edit the second one on disk, verify (fails). That
is the entire value proposition of hash-chaining, shown rather than asserted,
with nothing but SHA-256 behind it.
"""
from __future__ import annotations

import json

import pytest

from governance_core import (
    GENESIS,
    Decision,
    FileAuditLog,
    InMemoryAuditLog,
    Outcome,
)


def _decision(n: int, outcome: Outcome = Outcome.APPROVE) -> Decision:
    return Decision(
        outcome=outcome,
        policy_id="demo.policy",
        policy_version="1.0.0",
        reasons=() if outcome is Outcome.APPROVE else (f"REASON_{n}",),
        proposal_hash=f"sha256:{n:064d}",
        context_hash=GENESIS,
        timestamp=1_700_000_000.0 + n,
    )


@pytest.fixture(params=["memory", "file"])
def log(request, tmp_path):
    if request.param == "memory":
        return InMemoryAuditLog()
    return FileAuditLog(tmp_path / "audit.jsonl")


def test_an_empty_log_heads_at_genesis(log):
    assert log.head() == GENESIS
    assert log.verify() is True


def test_each_entry_chains_to_the_one_before(log):
    first = log.append(_decision(1))
    second = log.append(_decision(2))
    assert first != second
    assert log.head() == second
    assert log.verify() is True


def test_verifying_a_hash_that_was_never_written_fails(log):
    log.append(_decision(1))
    # Not merely "unknown" -- False. Returning True for an unwritten hash
    # would let a caller "verify" a decision that does not exist, which is
    # worse than having no verification at all.
    assert log.verify("sha256:" + "f" * 64) is False


def test_refusals_are_recorded_too(log):
    entry = log.append(_decision(1, Outcome.DENY))
    assert log.verify(entry) is True
    # A gate that logs only what it permitted has no record of what it
    # stopped, which is usually what a review is looking for.
    assert len(log) == 1


# ---------------------------------------------------------------------------
# The demonstration
# ---------------------------------------------------------------------------

def test_modifying_a_past_entry_breaks_the_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    for n in (1, 2, 3):
        log.append(_decision(n, Outcome.DENY))

    assert log.verify() is True, "the chain must verify before we tamper with it"
    assert log.first_broken_index() is None

    # Edit entry #2 in place, the way someone covering a decision would:
    # flip a DENY to an APPROVE and leave everything else alone.
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    assert record["entry"]["outcome"] == "DENY"
    record["entry"]["outcome"] = "APPROVE"
    lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify() is False
    # And it names *which* entry. "The log is broken" is far less actionable
    # in a review than "entry 1 was modified; entry 0 is intact".
    assert log.first_broken_index() == 1


def test_recomputing_the_edited_entrys_own_hash_is_not_enough(tmp_path):
    """The subtler attempt, and the reason the chain is a chain.

    Someone who edits an entry and also fixes that entry's own hash has
    produced a self-consistent record -- but every later entry still commits
    to the original hash, so the break just moves one row down. Covering it
    up fully means rewriting every subsequent entry.
    """
    from governance_core.audit import chain_hash

    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    for n in (1, 2, 3):
        log.append(_decision(n, Outcome.DENY))

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["entry"]["outcome"] = "APPROVE"
    record["entry_hash"] = chain_hash(record["entry"], record["previous_hash"])
    lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify() is False
    assert log.first_broken_index() == 2  # entry 1 now self-consistent, 2 is not


def test_deleting_an_entry_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = FileAuditLog(path)
    for n in (1, 2, 3):
        log.append(_decision(n, Outcome.DENY))

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # remove the middle decision entirely
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify() is False
    assert log.first_broken_index() == 1


def test_a_file_log_survives_being_reopened(tmp_path):
    path = tmp_path / "audit.jsonl"
    first = FileAuditLog(path)
    first.append(_decision(1))
    head = first.append(_decision(2))

    reopened = FileAuditLog(path)
    assert reopened.head() == head
    assert reopened.verify() is True
    assert reopened.append(_decision(3)) != head
