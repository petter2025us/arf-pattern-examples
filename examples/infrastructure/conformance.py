"""A public, independently checkable property of this reference policy.

This module exists so that a third party can state and re-check one property
of `examples/infrastructure/policy.py` **without importing this repository**
and without knowing anything about any product's internals.

## The property

> **P1 (reference infrastructure blast-radius ceiling).**
> For the reference policy `infrastructure.change` v1.0.0, for every proposal
> in which `environment == "production"` and `blast_radius` is an integer
> strictly greater than `PRODUCTION_BLAST_RADIUS_CEILING`, `evaluate()` must
> **not** return `APPROVE`.

Three things about how that is worded, because each of them is load-bearing:

**"must not return APPROVE", not "must return DENY".** The evaluator has
earlier branches. A proposal whose reversibility cannot be established
escalates before the ceiling is ever compared, and an irreversible production
change is denied for a different reason. Stating the property as "must return
DENY" would be *false*, and a property that is false is worse than no property
at all. What holds for every such proposal is the weaker, exact claim: the
answer is never APPROVE.

**"reference policy", not "invariant".** This is a property of the example
policy in this repository, derivable line by line from its public source. It
is not a claim about how any product behaves, not a product invariant, and
not a rule anyone else is obliged to adopt. The threshold below is an
illustrative number chosen for a worked example.

**"strictly greater".** At exactly the ceiling the proposal is within budget
and the branch does not fire. Off-by-one at a threshold is the most common
way a numerical property is misread, so the boundary is exercised explicitly
in `test_conformance.py` rather than left to the reader.

## Re-implementing this elsewhere

`exceeds_production_ceiling` is pure, total, and depends on nothing in this
package. Re-implementing it is three lines in any language:

    exceeds(environment, blast_radius) :=
        environment == "production" and blast_radius > 5

The value `5` is `PRODUCTION_BLAST_RADIUS_CEILING`, read from
`policy.BLAST_RADIUS_CEILING` below rather than duplicated, so this module
cannot drift from the policy it describes.
"""
from __future__ import annotations

from examples.infrastructure.policy import BLAST_RADIUS_CEILING

#: The ceiling P1 is stated against. Sourced from the policy, never copied:
#: a hand-copied constant is a second source of truth and would let this
#: module keep asserting a threshold the policy no longer uses.
PRODUCTION_BLAST_RADIUS_CEILING: int = BLAST_RADIUS_CEILING["production"]

PROPERTY_ID = "P1"
PROPERTY_STATEMENT = (
    "For reference policy infrastructure.change v1.0.0, a proposal with "
    "environment == 'production' and blast_radius > "
    f"{PRODUCTION_BLAST_RADIUS_CEILING} must not evaluate to APPROVE."
)


def exceeds_production_ceiling(environment: str, blast_radius: int) -> bool:
    """True when P1's antecedent holds for this (environment, blast_radius).

    Pure and total. Imports nothing from the engine, touches no I/O, and is
    the only thing a third party needs in order to generate cases that P1
    ranges over.
    """
    return environment == "production" and int(blast_radius) > PRODUCTION_BLAST_RADIUS_CEILING
