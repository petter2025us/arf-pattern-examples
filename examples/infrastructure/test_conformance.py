"""P1 exercised at and around the threshold, and across the space it ranges over.

`test_policy.py` checks hand-written fixtures: specific proposals with stated
expectations. This file checks a *property* instead -- one claim quantified
over many proposals -- which is a different kind of evidence and fails in a
different way. A fixture catches the case somebody thought of; a property
catches the case nobody did.

The boundary cases matter most. A ceiling comparison has exactly one place it
can be wrong, and both `>=` and `>` look equally plausible while reading.
"""
from __future__ import annotations

import itertools

import pytest

from examples.infrastructure.conformance import (
    PRODUCTION_BLAST_RADIUS_CEILING as CEILING,
    exceeds_production_ceiling,
)
from examples.infrastructure.policy import REVERSIBLE, InfrastructureChangePolicy
from governance_core import Outcome

POLICY = InfrastructureChangePolicy()


def _evaluate(environment, blast_radius, **overrides):
    proposal = {
        "action": "resize_cluster",
        "environment": environment,
        "blast_radius": blast_radius,
        "reversibility": REVERSIBLE,
    }
    proposal.update(overrides)
    context = {"approvals": 2, "change_window_open": True}
    return POLICY.evaluate(proposal, context)


# --------------------------------------------------------------------------
# The threshold itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize("blast_radius", range(0, CEILING + 1))
def test_at_or_below_the_ceiling_the_ceiling_branch_does_not_fire(blast_radius):
    """Up to and including the ceiling, P1's antecedent is false."""
    assert exceeds_production_ceiling("production", blast_radius) is False
    decision = _evaluate("production", blast_radius)
    assert "BLAST_RADIUS_EXCEEDED" not in " ".join(decision.reasons)


@pytest.mark.parametrize(
    "blast_radius",
    [CEILING + 1, CEILING + 2, CEILING * 2, 100, 10_000, 1_000_000],
)
def test_above_the_ceiling_never_approves(blast_radius):
    """P1, stated directly."""
    assert exceeds_production_ceiling("production", blast_radius) is True
    assert _evaluate("production", blast_radius).outcome is not Outcome.APPROVE


def test_the_boundary_is_strictly_greater_not_greater_or_equal(blast_radius=CEILING):
    """The single off-by-one this property can have.

    At exactly the ceiling the change is within budget. If the comparison
    were `>=`, this would deny and the repository would be quietly stricter
    than it documents.
    """
    assert exceeds_production_ceiling("production", blast_radius) is False
    assert _evaluate("production", blast_radius).outcome is Outcome.APPROVE
    assert exceeds_production_ceiling("production", blast_radius + 1) is True


# --------------------------------------------------------------------------
# P1 across the space, including the branches that pre-empt the ceiling
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "blast_radius,reversibility,approvals",
    list(itertools.product(
        [CEILING + 1, CEILING + 7, 250],
        ["REVERSIBLE", "COMPENSABLE", "IRREVERSIBLE", None],
        [0, 1, 2],
    )),
)
def test_p1_holds_whatever_else_the_proposal_says(
    blast_radius, reversibility, approvals
):
    """Once the antecedent holds, no other field rescues an APPROVE.

    This is why P1 says "must not APPROVE" rather than "must DENY": with
    reversibility unknown the evaluator escalates before it ever compares the
    ceiling, and with IRREVERSIBLE it denies for a different reason. All three
    outcomes are acceptable here; APPROVE is not.
    """
    assert exceeds_production_ceiling("production", blast_radius) is True
    proposal = {"action": "resize_cluster", "environment": "production",
                "blast_radius": blast_radius}
    if reversibility is not None:
        proposal["reversibility"] = reversibility
    decision = POLICY.evaluate(proposal, {"approvals": approvals})
    assert decision.outcome is not Outcome.APPROVE
    assert decision.reasons, "a non-APPROVE decision must explain itself"


def test_non_production_environments_are_outside_the_property(tmp_path=None):
    """P1 says nothing about staging or dev, and must not be read as doing so.

    A reader who assumed the ceiling were global would conclude this
    repository denies a 50-resource staging change. It does not.
    """
    assert exceeds_production_ceiling("staging", CEILING + 1) is False
    assert _evaluate("staging", CEILING + 1).outcome is Outcome.APPROVE


def test_an_unknown_environment_is_treated_as_production(tmp_path=None):
    """The strictest ceiling is the default, so a typo cannot buy authority.

    Stated here because it is the one place P1's wording could mislead: the
    property is about `environment == "production"`, while the *policy* also
    applies the production ceiling to anything it does not recognise.
    """
    assert _evaluate("prodcution", CEILING + 1).outcome is not Outcome.APPROVE
