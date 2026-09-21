# A public conformance property

This document states one property of this repository's reference
infrastructure policy in a form a third party can check independently.

It exists so that someone who wants to test a claim about this code has an
exact claim to test, rather than an impression formed from reading prose.

## P1 — reference infrastructure blast-radius ceiling

> For the reference policy `infrastructure.change` v1.0.0, for every proposal
> in which `environment == "production"` and `blast_radius` is an integer
> strictly greater than `5`, `evaluate()` must **not** return `APPROVE`.

Source of every term:

| term | where it is defined |
|---|---|
| the policy | [`examples/infrastructure/policy.py`](../examples/infrastructure/policy.py) |
| the ceiling `5` | `BLAST_RADIUS_CEILING["production"]` in that file |
| the outcomes | `Outcome` in [`governance_core/decision.py`](../governance_core/decision.py) |
| the predicate | `exceeds_production_ceiling` in [`examples/infrastructure/conformance.py`](../examples/infrastructure/conformance.py) |

Nothing in P1 depends on anything private. Every term resolves to a line of
public source in this repository.

## What P1 is, and what it is not

**It is a property of this example policy.** It is derivable line by line
from public source, and it is checked by
[`examples/infrastructure/test_conformance.py`](../examples/infrastructure/test_conformance.py).

**It is not an ARF AI invariant.** It is not a product invariant, not an
execution-control invariant, not a risk-engine property, and not a claim
about how any deployed system behaves. The policy here is an illustrative
reference policy and `5` is a number chosen for a worked example. Nobody
should read P1 as describing a rule any product enforces.

## Three points of exactness

**"must not return APPROVE", not "must return DENY".** The evaluator has
branches that run before the ceiling is compared: a proposal whose
reversibility cannot be established escalates, and an irreversible production
change is denied for a different reason. "Must return `DENY`" would therefore
be **false**, and a false property is worse than none. What holds across
every proposal satisfying the antecedent is the exact, weaker claim.

**"strictly greater".** At exactly `5` the change is within budget and the
ceiling branch does not fire. Off-by-one at a threshold is the usual way a
numerical property gets misread, so both sides of the boundary are exercised
explicitly rather than left to the reader.

**Only `production`.** P1 says nothing about `staging` or `dev`, which have
their own, looser ceilings. Separately — and this is the one place P1's
wording could mislead — the *policy* applies the production ceiling to any
environment string it does not recognise, so that a typo cannot buy more
authority than it should. That is a property of the policy, not part of P1.

## Re-implementing the predicate

`exceeds_production_ceiling` is pure, total, and imports nothing from the
engine. Re-implementing it needs no dependency on this repository:

```
exceeds(environment, blast_radius) :=
    environment == "production" and blast_radius > 5
```

Generating cases that P1 ranges over needs only that predicate. Checking the
consequent needs the policy's `evaluate()`, which is a pure function of
`(proposal, context)` and performs no I/O.

## Scope

This document describes one property of one example policy. The other
example domains have their own thresholds and are not covered by it, and
this repository makes no claim that P1 is the most interesting property it
has — only that it is exactly stated, publicly derivable, and tested at its
boundary.
