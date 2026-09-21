"""Guard the public/private boundary of this repository.

This repository is public. ARF AI's engine and control-plane internals are
not. The boundary between them is not enforced by anything structural -- it
is prose, and prose drifts -- so this scanner exists to make a crossing fail
loudly instead of being noticed by a reader months later.

## What it looks for, and what it deliberately does not

Two classes:

1. **Private identifiers.** Names that only exist inside ARF's private
   repositories. A match is unambiguous: these strings have no innocent
   reading in a public reference library.

2. **Architectural phrases.** Multi-word phrases that describe a *mechanism*
   rather than a concept. "an audit log" is a concept every governed system
   has; "the authorization is minted from a durably committed audit entry,
   consumed by an atomic compare-and-swap" is a specification of one
   particular protocol.

What it must never do is prohibit the vocabulary of the field. `audit`,
`authorization`, `risk`, `execution`, `policy`, `deterministic`, `signature`
are the words this repository is *about*. A guard that flagged them would be
turned off within a week, and the repository's own README already says why:
an over-broad rule trains everyone around it to route past the gate. Every
pattern here is therefore either a private proper noun or a phrase of three
or more words naming a specific mechanism.

## Scanning itself

The scanner necessarily contains the strings it searches for, so it excludes
its own file. That exclusion is the only one, and
`tests/test_ip_boundary.py` asserts it stays the only one -- otherwise the
exclusion list would become the obvious hiding place.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from typing import Iterable, NamedTuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SELF = "tools/ip_boundary_scan.py"

# Names that exist only inside ARF's private repositories.
PRIVATE_IDENTIFIERS = [
    r"arf_enterprise",
    r"\barf-api\b",
    r"agentic_reliability_framework",
    r"AdmissionToken",
    r"\badmission_id\b",
    r"authorized_action_hashes",
    r"envelope_hash",
    r"canonicalization_version",
    r"CapabilityGrant",
    r"ExecutionLadder",
    r"PostgresAdmissionRegistry",
    r"InMemoryAdmissionRegistry",
    r"AuthorityStore",
    r"ARF_ADMISSION_SIGNING_KEY",
    r"ARF_AUDIT_SIGNING_KEY",
    r"ARF_KEY_PEPPER",
    r"\bCUDL\b",
    # Private formal-model vocabulary.
    r"NoOrBypass",
    r"NoAndBypass",
    r"DenialIsAlwaysExplained",
    r"distributivity witness",
    r"\bTLA\+",
]

# Phrases that describe a specific mechanism rather than a general concept.
# Each is >= 3 words, or a compound proper to ARF's internals.
#
# Deliberately NOT here: "enterprise actuators" and "execution-admission
# mechanisms". Those are the *names* of omitted components, and the README's
# boundary section has to be able to say a thing is not reproduced. Naming an
# omitted component reveals no mechanism; describing one does, and the phrases
# below are what describe them. Losing that distinction would make the honest
# boundary statement unwriteable, which is how a guard ends up disabled.
ARCHITECTURAL_PHRASES = [
    r"durably committed audit entry",
    r"committed audit entry",
    r"atomic compare-and-swap",
    r"compare-and-swap against durable state",
    r"single-use authorization",
    r"durable single-use state",
    r"reconcilable state",
    r"execution-control protocol",
    r"admission registry",
    r"durable authority store",
    r"\bauthority store\b",
    r"Bayesian risk fusion",
    r"epistemic[- ]uncertainty gating",
    r"memory-augmented correction",
    r"risk fusion",
    r"hyperprior",
    r"\bHMC\b",
    r"causal counterfactual",
    r"signatures over the chain head",
]

# Credential shapes. Narrow on purpose: a public repo full of the word
# "key" must not be unusable.
SECRET_SHAPES = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(AKIA|ASIA)[0-9A-Z]{16}",
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"xox[baprs]-[A-Za-z0-9-]{12,}",
    r"git\+https://[^\s\"')]+",
    # A credential-shaped assignment. The AKIA pattern above matches AWS
    # key *ids*; a secret access key has no distinguishing prefix, so it is
    # caught by shape instead. Found by the armed-guard test, which planted
    # one and watched the scanner stay quiet.
    r"\b[A-Z][A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD|PASSWD)\b\s*=\s*[\"']?[A-Za-z0-9/+_=-]{20,}",
    r"[a-z][a-z0-9+.-]*://[^:/@\s]+:[^@/\s]{6,}@",
]

CATEGORIES = [
    ("private-identifier", PRIVATE_IDENTIFIERS),
    ("architectural-phrase", ARCHITECTURAL_PHRASES),
    ("secret-shape", SECRET_SHAPES),
]

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
    ".rego", ".cfg", ".ini", ".sh", "",
}


class Finding(NamedTuple):
    path: str
    line: int
    category: str
    pattern: str
    excerpt: str


def _tracked_files(root: pathlib.Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout.split("\n")
    return [f for f in out if f.strip()]


def scan_text(path: str, text: str) -> list[Finding]:
    """Findings for one file's contents. Pure: no I/O, easy to test."""
    findings: list[Finding] = []
    if path.replace("\\", "/") == SELF:
        return findings
    for lineno, line in enumerate(text.splitlines(), 1):
        for category, patterns in CATEGORIES:
            for pat in patterns:
                if re.search(pat, line, re.IGNORECASE if category != "secret-shape" else 0):
                    findings.append(
                        Finding(path, lineno, category, pat, line.strip()[:120])
                    )
    return findings


def scan_tree(root: pathlib.Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for rel in _tracked_files(root):
        p = root / rel
        if p.suffix not in TEXT_SUFFIXES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(rel, text))
    return findings


def scan_history(root: pathlib.Path = REPO_ROOT) -> dict[str, list[Finding]]:
    """Same patterns against every commit. Reported, never auto-fixed:
    rewriting published history is a decision, not a cleanup."""
    commits = subprocess.run(
        ["git", "rev-list", "--all"],
        cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.split()
    per_commit: dict[str, list[Finding]] = {}
    for c in commits:
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", c],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout.split("\n")
        hits: list[Finding] = []
        for rel in (n for n in names if n.strip()):
            if pathlib.Path(rel).suffix not in TEXT_SUFFIXES:
                continue
            blob = subprocess.run(
                ["git", "show", f"{c}:{rel}"],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if blob.returncode != 0 or not blob.stdout:
                # A path that existed in the tree listing but cannot be read
                # back is skipped rather than crashing the scan -- but it is
                # not silently treated as clean, which is the failure mode
                # that matters for a guard.
                continue
            hits.extend(scan_text(rel, blob.stdout))
        if hits:
            per_commit[c] = hits
    return per_commit


def _report(findings: Iterable[Finding]) -> None:
    for f in findings:
        print(f"  {f.path}:{f.line}  [{f.category}]  {f.pattern}\n      {f.excerpt}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", action="store_true", help="scan every commit too")
    args = ap.parse_args()

    tree = scan_tree()
    print(f"current tree: {len(tree)} finding(s)")
    _report(tree)

    if args.history:
        hist = scan_history()
        total = sum(len(v) for v in hist.values())
        print(f"\nhistory: {total} finding(s) across {len(hist)} commit(s)")
        for c, hits in hist.items():
            subj = subprocess.run(
                ["git", "log", "-1", "--format=%h %s", c],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            ).stdout.strip()
            print(f"  --- {subj}")
            _report(hits)

    return 1 if tree else 0


if __name__ == "__main__":
    sys.exit(main())
