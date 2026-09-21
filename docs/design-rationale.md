# Design rationale

Why the pattern is shaped this way. This document argues for the structure; it does not compare products.

## Probabilistic proposal generation is not deterministic authorization

The two are often collapsed, and the collapse is the source of most of the confusion about "AI governance".

A model generating a proposal is doing something inherently probabilistic. It samples. Two identical prompts can produce two different outputs, and that is not a defect — it is what the technique is.

Authorization is the opposite kind of thing. "May this action proceed?" must produce the same answer for the same inputs, because the answer has to survive three things a sampled answer cannot:

- **Appeal.** Someone will ask why their request was refused. "The model judged it inappropriate" is not an answer anyone can act on, and it is not an answer that can be shown to be wrong.
- **Review.** A regulator, an auditor, or an incident responder reads decisions after the fact. They need to re-derive the decision, not re-run a sampler and hope.
- **Consistency.** Two identical requests receiving different answers is a fairness problem in lending, a safety problem in healthcare, and an outage in infrastructure.

So the split is not "deterministic good, probabilistic bad". It is that the two belong at different points in the pipeline. **Propose probabilistically. Authorize deterministically.**

A policy may still *consume* probabilistic input — a risk model's score, a confidence estimate, an anomaly signal. What it may not do is let its own verdict vary. A fixed threshold applied to an uncertain score is deterministic; the uncertainty lives in the score, and the score is recorded.

## Why the gate is not "LLM-as-judge"

Asking a second model whether the first model's output is acceptable inherits every property that made the first output unsuitable for authorization: it samples, it cannot be replayed, and it has no stable version you can point at six months later.

It also fails in a particular way that matters. A judge model is persuadable by the same text it is judging. A deterministic policy reading `proposal["apr_percent"] > 29.99` is not.

This is not an argument that model-based evaluation is useless. It is an argument about which decisions it may make. Model evaluation is reasonable for graded, subjective qualities where being approximately right is the goal. Hard redlines are not that. **The test for whether something belongs in a deterministic policy: would you accept a different answer tomorrow for the same input?** If no, it is a redline.

## Why `ESCALATE` is a first-class outcome

A two-valued gate forces every "I don't know" into one of two lies.

Folded into `APPROVE`, a missing input becomes a silent assumption of safety — the failure mode where a broken lookup *widens* autonomy, and an outage in a read path becomes an authorization bypass.

Folded into `DENY`, a missing input becomes a refusal the requester cannot fix and cannot appeal, because nothing was actually wrong with their request. In healthcare that is care refused for paperwork. In lending it is a denial recorded against someone for a field the system failed to populate.

Three outcomes let the gate say the true thing: *this is forbidden*, *this is permitted*, or *I am not the right authority to decide this*.

The infrastructure example leans hardest on it. Reversibility that could not be *established* gates as if the action were permanent — the safe direction under uncertainty — but is recorded as "undetermined", not as "irreversible". "We could not tell" and "we knew it was permanent" are different findings, and only one of them is a bug in the system that looked.

## Why the record comes before the action

Writing the decision after the action seems harmless, and is the default almost everywhere, because in the happy path the two orders are indistinguishable.

They differ exactly when it matters. Between `execute()` and `log()` there is a window containing every crash, timeout, deploy, OOM kill and network partition. An action that lands in that window happened and left no trace. Nobody can find it, because the only system that knew about it is the one that died.

Reverse the order and the worst case inverts: a record of an action that did not happen. That is a discrepancy — findable by reconciling records against reality, and resolvable. A discrepancy you can find beats a silence you cannot.

This repository implements the ordering and stops there. The stronger property — that the authorization to act is *derived* from the committed record, so acting without a record is structurally impossible rather than merely discouraged — needs durable single-use state and is not reproduced here.

## Why the policy interface is so small

`evaluate(proposal, context) -> Decision`. That is all.

Everything a policy needs comes in as an argument, which makes the policy a pure function and therefore replayable. A policy that reads the clock, a global, or a network service cannot be re-run to check its own past decisions, and a decision that cannot be re-derived is an assertion rather than a record.

This is why `context` exists as a separate argument rather than being folded into the proposal. The two have different trust properties:

- **`proposal`** is what the agent asked for. Untrusted. Every field is a claim to be checked.
- **`context`** is what the *system* knows. Approvals, coverage status, change windows, current state.

The infrastructure example makes the distinction concrete: a proposal carrying `"approved": true` is ignored, because approval is read from `context`. An agent asserting its own authority is the one input a gate must never take at face value, and keeping the two in separate arguments makes that hard to get wrong by accident.

## Why the revision loop is optional

Handing a refusal back to the generator and asking for another attempt is useful, and it is *one possible response* to `DENY` — not the point.

The point is that the policy decides whether a proposal is executable. What a caller does with a refusal is the caller's business: stop, revise, route to a person, or choose a different action entirely. Building the retry into the gate would make the gate look like a negotiation, and it is not one.

The loop that exists here ends in `ESCALATE` rather than `DENY` when attempts run out, because "the generator could not produce something admissible" is a different finding from "this action is forbidden", and only the first one is usefully handed to a person.
