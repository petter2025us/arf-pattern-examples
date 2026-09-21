"""Tamper-evident decision log.

Every entry carries the hash of the entry before it, so the log is a chain.
Changing any past entry changes its hash, which breaks every hash after it --
you cannot quietly edit history without rewriting all of it, and the head
hash is the single value that attests to the whole chain.

That property is the reason deterministic governance is worth anything. A
gate whose decisions are not durably recorded is a gate whose decisions
cannot be reviewed, and an unreviewable gate is indistinguishable from no
gate at the moment somebody asks what happened.

`tests/test_audit.py` demonstrates this concretely: write three decisions,
verify (passes), modify the second entry on disk, verify (fails, and names
the entry that broke). That demonstration needs no cryptography beyond
SHA-256 and no proprietary machinery of any kind.

**Scope.** This is hash-chaining only -- integrity, not authenticity. It
detects modification; it does not prove authorship, because anyone who can
rewrite an entry can recompute the rest of the chain. Establishing authorship as well as
integrity requires signatures, which this file does not implement. How any
particular product does that is out of scope; this file deliberately
stops at the portable concept, because the portable concept is the part
worth teaching.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator, Protocol, runtime_checkable

from governance_core.decision import Decision, canonical_json, digest

#: The hash a chain starts from. Fixed rather than random so an empty log
#: has a well-defined head and two empty logs are comparable.
GENESIS = "sha256:" + "0" * 64


def chain_hash(entry: dict[str, Any], previous_hash: str) -> str:
    """`SHA256(canonical(entry) + previous_hash)`.

    The previous hash is *inside* the hashed material, which is what links
    the entries. Hashing the entry alone and storing the parent beside it
    would record the order without enforcing it -- you could reorder entries
    and every individual hash would still check out.
    """
    return digest({"entry": entry, "previous_hash": previous_hash})


@runtime_checkable
class AuditLog(Protocol):
    """Append-only decision log."""

    def append(self, decision: Decision) -> str:
        """Append a decision. Returns the new entry's hash."""
        ...

    def verify(self, entry_hash: str | None = None) -> bool:
        """Recompute the chain. With `entry_hash`, verify up to that entry."""
        ...

    def head(self) -> str:
        """Hash of the most recent entry, or GENESIS when empty."""
        ...


def _verify_records(records: list[dict[str, Any]], entry_hash: str | None) -> bool:
    previous = GENESIS
    seen = False
    for record in records:
        expected = chain_hash(record["entry"], previous)
        if record.get("entry_hash") != expected:
            return False
        if record.get("previous_hash") != previous:
            return False
        previous = expected
        if entry_hash is not None and expected == entry_hash:
            seen = True
            break
    if entry_hash is not None and not seen:
        # An unknown hash is not a valid chain position. Returning True here
        # would let a caller "verify" an entry that was never written.
        return False
    return True


class InMemoryAuditLog:
    """For tests and demos. Loses everything when the process exits.

    Named so that is obvious. A durable-looking name on an ephemeral store is
    how a deployment ends up believing it has records it does not have.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def append(self, decision: Decision) -> str:
        entry = decision.to_entry()
        with self._lock:
            previous = self._records[-1]["entry_hash"] if self._records else GENESIS
            entry_hash = chain_hash(entry, previous)
            self._records.append(
                {"entry": entry, "previous_hash": previous, "entry_hash": entry_hash}
            )
        return entry_hash

    def verify(self, entry_hash: str | None = None) -> bool:
        with self._lock:
            return _verify_records(list(self._records), entry_hash)

    def head(self) -> str:
        with self._lock:
            return self._records[-1]["entry_hash"] if self._records else GENESIS

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(list(self._records))


class FileAuditLog:
    """Append-only JSONL on disk. One JSON object per line, one per decision.

    JSONL because it is append-only by construction: writing a decision never
    rewrites an earlier byte, so a crash mid-write can truncate the tail but
    cannot corrupt history. A single JSON array would have to be rewritten
    whole on every append, which is exactly the operation an append-only log
    exists to avoid.

    Durability here is `flush` + `fsync` on each append. That is the honest
    minimum for "the record exists before the action does"; a real deployment
    would put this behind storage with its own retention and access controls.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _records(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def append(self, decision: Decision) -> str:
        entry = decision.to_entry()
        with self._lock:
            records = self._records()
            previous = records[-1]["entry_hash"] if records else GENESIS
            entry_hash = chain_hash(entry, previous)
            record = {
                "entry": entry,
                "previous_hash": previous,
                "entry_hash": entry_hash,
            }
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(canonical_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return entry_hash

    def verify(self, entry_hash: str | None = None) -> bool:
        with self._lock:
            try:
                records = self._records()
            except json.JSONDecodeError:
                # A line that will not parse is itself tampering evidence.
                return False
            return _verify_records(records, entry_hash)

    def head(self) -> str:
        with self._lock:
            records = self._records()
            return records[-1]["entry_hash"] if records else GENESIS

    def first_broken_index(self) -> int | None:
        """Index of the first entry that fails, or None if the chain holds.

        Useful in a review: "the log is broken" is far less actionable than
        "entry 2 was modified, entries 0 and 1 are intact".
        """
        with self._lock:
            try:
                records = self._records()
            except json.JSONDecodeError:
                return 0
            previous = GENESIS
            for index, record in enumerate(records):
                expected = chain_hash(record["entry"], previous)
                if (
                    record.get("entry_hash") != expected
                    or record.get("previous_hash") != previous
                ):
                    return index
                previous = expected
            return None

    def __len__(self) -> int:
        return len(self._records())
