# Bring your own policy

Adding a domain takes one file. This walks through it, using a change-approval gate as the worked example.

## 1. Decide what your redlines actually are

Before writing code, write the list. The test for whether something belongs here:

> **Would you accept a different answer tomorrow for the same input?**

If no, it is a redline and belongs in a deterministic policy. If yes — "is this tone appropriate", "is this summary good" — it is a graded judgment and a policy gate is the wrong instrument.

Useful shapes for redlines, drawn from the four examples:

| Shape | Example | Why it works deterministically |
|---|---|---|
| Numeric ceiling | APR ≤ 29.99% | A comparison |
| Set membership | Fee not in prohibited set | A lookup |
| Cross-field consistency | Diagnosis must justify procedure | A table |
| Required-input presence | Affordability inputs supplied | An existence check |
| Class override | `delete_snapshot` is always irreversible | A constant, not an inference |

Write down what happens when an input is **missing**, separately from what happens when it is **violated**. They are different outcomes, and conflating them is the most common mistake — see [design-rationale.md](design-rationale.md).

## 2. Write the policy

A policy is any object with `policy_id`, `policy_version`, and `evaluate`. No base class, no registration.

```python
from typing import Any, Mapping

from governance_core.decision import Decision, Outcome, decide


class ChangeApprovalPolicy:
    policy_id = "ops.change_approval"
    policy_version = "1.0.0"

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        def verdict(outcome: Outcome, *reasons: str) -> Decision:
            return decide(
                outcome,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                proposal=proposal,
                context=context,
                reasons=reasons,
            )

        window = proposal.get("maintenance_window")
        if window is None:
            # Missing input -> ESCALATE. It is a question, not a violation.
            return verdict(
                Outcome.ESCALATE,
                "WINDOW_UNKNOWN: no maintenance window was supplied, so the "
                "freeze calendar could not be applied",
            )

        if window in context.get("frozen_windows", ()):
            return verdict(
                Outcome.DENY,
                f"CHANGE_FREEZE: {window} is under a declared freeze",
            )

        return verdict(Outcome.APPROVE)
```

Three rules, and they are the whole contract:

1. **Use `decide()`**, not the `Decision` constructor. It hashes the proposal and context the same way every other policy does, so two logs stay comparable.
2. **No I/O, no clock, no globals.** Anything `evaluate` needs arrives as an argument. A policy that reads the world cannot be replayed, and a decision that cannot be re-derived is not a record.
3. **Read authority from `context`, never from `proposal`.** The proposal is the agent's claim; the context is what your system knows. A proposal asserting its own approval must not receive one.

`DENY` and `ESCALATE` require at least one reason — the `Decision` constructor rejects them otherwise. A refusal nobody can explain is not auditable.

## 3. Wire in whatever produces proposals

Anything with a `generate(feedback)` method, or any callable taking a list of feedback strings. An LLM call, a planner, a form handler:

```python
def generate(feedback: list[str]) -> dict:
    prompt = BASE_PROMPT
    if feedback:
        prompt += "\n\nYour previous proposal was refused:\n" + "\n".join(feedback)
    return json.loads(your_model.complete(prompt))
```

The generator cannot influence the decision. There is no confidence field that buys a lower bar and no flag that marks a proposal pre-approved. That asymmetry is most of what makes the gate worth having.

## 4. Run it

```python
from governance_core import FileAuditLog, GovernanceEngine, govern_with_revision

engine = GovernanceEngine(ChangeApprovalPolicy(), FileAuditLog("audit.jsonl"))

result = govern_with_revision(
    engine,
    generate,
    context={"frozen_windows": ("2026-12-24",)},
    execute=apply_the_change,     # called only on APPROVE
    max_attempts=3,
)

print(result.outcome, result.entry_hash)
```

Use `engine.submit(proposal, context, execute=...)` directly if you do not want a revision loop. Most callers should not: stopping, escalating, or choosing a different action are equally valid responses to a refusal.

`execute` is called **only** on `APPROVE`, and **only** after the decision is durable.

## 5. Verify the trail

```python
assert engine.audit.verify() is True     # whole chain
engine.audit.verify(result.entry_hash)   # up to one entry
```

For `FileAuditLog`, `first_broken_index()` names the first entry that fails, which is what a review needs — *"entry 2 was modified, 0 and 1 are intact"* rather than *"the log is broken"*.

Verify in CI, not just in an incident. A chain nobody checks is a chain nobody notices breaking.

## 6. Test it the way the examples do

Put your cases in `fixtures.json` with the expected outcome **and the reason you expect it**:

```json
{
  "cases": [
    {
      "name": "change during a declared freeze",
      "proposal": {"maintenance_window": "2026-12-24"},
      "context": {"frozen_windows": ["2026-12-24"]},
      "expect": "DENY",
      "because": "the freeze calendar is a hard redline, not a preference"
    }
  ]
}
```

Then reuse the shared runner:

```python
from examples._fixture_runner import load_cases, run_case

CASES = load_cases(Path(__file__).parent / "fixtures.json")

@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_reaches_its_stated_outcome(case):
    run_case(ChangeApprovalPolicy(), case)
```

The `because` field is not decoration. A fixture whose expectation nobody can explain is a test that gets "fixed" by editing the expectation the next time it fails.

## Things that will bite you

**An over-broad rule is not a safe rule.** A redline that also blocks the compliant output trains everyone around it to route past the gate. The solar example documents a live instance: a guarantee detector that would have blocked the exact hedged rewrite it existed to produce.

**A pattern bug fails open.** A regex that matches nothing looks identical to a redline with nothing to catch. The solar example documents that too — a stray `\b` after `100%` silently disabled a branch. Write at least one fixture that your rule must **catch**, not only fixtures it must permit.

**Version your policy.** `policy_version` is recorded in every decision. Bump it on any rule change, or a replay that disagrees cannot distinguish *the policy changed* from *the answer changed*.

**Do not put secrets in `proposal` or `context`.** Both are hashed into the audit entry, and `FileAuditLog` writes them in the clear.
