# arf-pattern-examples

A public reference implementation of the deterministic governance pattern used by [ARF AI](https://www.arf-ai.com/): **agents propose actions, policies deterministically decide whether those actions may proceed, and every decision produces a verifiable audit record.**

> **This repository is independent reference code.** It does not contain ARF AI's proprietary decision engine, authority system, execution admission protocol, or enterprise actuators. It demonstrates the *pattern*, not the product — see [What this is not](#what-this-is-not).

```
agent proposes an action
        │
        ▼
  deterministic policy          ← same inputs, same version, same answer
        │
   APPROVE / DENY / ESCALATE
        │
        ▼
  audit append (durable)        ← BEFORE anything happens
        │
        ▼
      execute                   ← only on APPROVE
```

The core claim is that this pipeline does not change between domains. Only the redlines do. Four worked examples run through the identical engine and the identical test runner:

| Domain | The proposed action | What the redlines are about |
|---|---|---|
| **[infrastructure](examples/infrastructure/)** | "Delete this production volume" | Reversibility, blast radius, environment, approval |
| [solar](examples/solar/) | "Send this proposal to this customer" | Claims that are unsubstantiable *for this customer* |
| [healthcare](examples/healthcare/) | "Approve this prior authorization" | Eligibility rules that must not be a model's judgment call |
| [lending](examples/lending/) | "Extend this offer at these terms" | Rate ceilings, prohibited fees, affordability |

Start with **infrastructure**. It is the clearest case, because the action is unambiguously consequential: either the volume is deleted or it is not, with no interpretive middle ground about whether an output was "appropriate".

## Why deterministic

Some decisions must never be delegated to a model's judgment. Not because models are bad at judgment, but because a judgment that varies between two identical requests cannot be audited, cannot be appealed, and cannot be shown to a regulator as a rule.

A deterministic policy is a function: same proposal, same context, same policy version, same answer — every time. That property is what makes a decision reviewable six months later.

Policies may be *probabilistic about the world*. A risk model can produce a score; the policy then applies a fixed threshold to it. The score can be uncertain. The comparison must not be.

## The three outcomes

`APPROVE`, `DENY`, `ESCALATE` — ARF's vocabulary, used here for the same reason it exists there.

`ESCALATE` is not a softer `DENY`. It means the policy established that it is **not the right authority** to decide: an input is missing, or the action is above the bar this policy may clear alone. Collapsing it into `DENY` destroys the distinction between *this is forbidden* and *this needs a person*, and that distinction is the whole of what a reviewer needs in order to act.

The examples lean on it deliberately:

- Infrastructure: reversibility could not be established → `ESCALATE`. **Not knowing whether an action can be undone is not evidence that it can.**
- Healthcare: clinical documentation missing → `ESCALATE`, never `DENY`. A filing gap is an unanswered question, not an ineligible request. Denying there refuses care for paperwork.
- Lending: affordability inputs absent → `ESCALATE`. An unassessed offer is neither safe nor refused.

## Ordering: record, then act

```
evaluate → Decision → AuditLog.append() → execute()
```

Not *execute, then log if it worked*. Every crash, timeout and process kill between the action and the log produces an action nobody has a record of — and those are precisely the moments a record matters. Writing first means the worst case is a record of an action that did not happen, which is a discrepancy you can find and resolve. The other order produces an action nobody can find at all.

**This is an educational simplification.** ARF's real execution-control protocol is considerably stronger: the authorization to execute is minted only from a durably committed audit entry, it is single-use, its consumption is an atomic compare-and-swap against durable state, and an execution whose outcome is unknown lands in a reconcilable state rather than being retried. None of that is reproduced here. What is reproduced is the ordering principle, which is portable, and which most systems get wrong in the cheap direction.

## An unreachable authority is not a permissive one

When the governing policy lives in an external engine — OPA, Cedar, a policy service — the interesting question is not the happy path. It is what happens when that engine is unreachable.

The tempting answer is to keep a local mirror of the rules and evaluate against it so the system stays available. `governance_core/external_policy.py` refuses to do that, and the refusal is the point:

- Unreachable authority → **`ESCALATE`** (default) or **`DENY`** (strict).
- `on_unavailable=APPROVE` is **rejected by the constructor**. There is no configuration that turns a policy-engine outage into a permission, because a flag that can do that will eventually be set.
- No local evaluator is consulted. Not as a fallback, not "just this once".

A local mirror holds the rules as of the last sync; the authoritative engine holds the rules as they are. They differ exactly when it matters — after a policy was tightened and before the mirror caught up. Falling back answers a question nobody asked (*what would the old rules have said?*) and returns it as though it were the answer to *what do the rules say?*. An outage in the policy engine silently becomes an outage in enforcement.

`tests/test_fail_closed.py` proves the local evaluator is never consulted, using a spy — because the substitution would be **invisible in the outcome** and is only visible in the call record. A paired control wires the "helpful" fallback up deliberately and shows the spy catches it, so the main test's silence is evidence rather than an absence.

> This repository's own earlier version had exactly this defect: an OPA client that fell back to a local Python evaluator when the sidecar was unreachable, with `fail_closed=True` as opt-in. The default was fail-open. It is documented here rather than quietly removed, because it is the most copyable mistake in the whole pattern.

A local Python policy is still perfectly usable — as *the* policy, chosen explicitly, for development and for every example in this repository. What it may never be is a hidden understudy that walks on when the real one is unavailable.

## The audit trail, demonstrated

Each entry contains the hash of the entry before it. Changing any past entry changes its hash, which breaks every hash after it.

`tests/test_audit.py` shows this rather than asserting it:

1. Write three decisions → `verify()` passes
2. Edit entry #2 on disk, flipping a `DENY` to an `APPROVE` → `verify()` **fails**, and `first_broken_index()` returns `1`
3. Also fix that entry's own hash → still fails, at index `2`. The break moves down; covering it up fully means rewriting every subsequent entry.

`SHA-256` and nothing else. No proprietary machinery, no key management.

**Scope:** hash-chaining is *integrity*, not *authenticity*. It detects modification; it does not prove authorship, because anyone who can rewrite an entry can recompute the rest of the chain. Real non-repudiation needs signatures over the chain head and a key the writer cannot reach. ARF does that privately; this repository stops at the portable concept on purpose.

## Run it

```bash
pip install -e ".[dev]"
python -m pytest -q
```

Everything runs offline. No API key, no model call, no network, no OPA binary — a reference implementation you cannot execute is a blog post.

## Layout

```
governance_core/
  decision.py         Outcome, Decision, canonical hashing
  policy_interface.py The Policy protocol — the one thing a domain implements
  audit.py            Hash-chained log: InMemoryAuditLog, FileAuditLog
  engine.py           The interceptor, and the optional revision loop
  external_policy.py  Delegation to an authoritative engine, fail-closed
  llm_adapter.py      Where a proposal generator plugs in

examples/<domain>/
  policy.py           The redlines
  fixtures.json       Proposals, expected outcomes, and why
  test_policy.py      Identical in every domain

docs/
  bring-your-own-policy.md   Adding your own domain
  design-rationale.md        Why the pattern is shaped this way
```

`examples/solar/policy.rego` expresses the same solar redlines in Rego, to show the pattern does not depend on a policy language. The Python policy is what the tests run.

## Two bugs worth keeping

Both are in the repository because a pattern library that hides its own near-misses reads as marketing.

**An over-broad redline is not "safely strict."** The first guarantee detector flagged any mention of a dollar sign or "30%". That would have blocked the exact hedged rewrite the policy exists to produce — *"you may qualify for up to a 30% Federal ITC, depending on your personal tax liability"* mentions a percentage and guarantees nothing. Fixed by matching phrases that assert certainty rather than any adjacent number. An over-broad rule trains everyone around it to route past the gate.

**A pattern bug fails open, and silence is the dangerous direction.** The full-bill-elimination regex ended in `\b` — but `100%` ends in a non-word character, so there is no word boundary there and the branch never matched anything. The test suite caught it on the first run. In a deployment without that fixture, it would have looked like a working redline while permitting every claim it was written to stop.

## What this is not

- **Not ARF AI's engine.** No Bayesian risk fusion, no epistemic-uncertainty gating, no authority system, no execution admission protocol, no enterprise actuators. Those are proprietary and none of them are here.
- **Not a risk scorer.** This is a deterministic gate, appropriate for hard redlines. Probabilistic risk estimation is a different job.
- **Not compliance.** The healthcare and lending examples use invented codes, thresholds and fee names. They are illustrative policy examples, **not legal, medical, clinical, underwriting, financial or regulatory advice**, and nothing here establishes compliance with anything.
- **Not production software.** It is a reference implementation with tests, not a system running against real decisions.

## License

Apache-2.0. See [LICENSE](LICENSE).
