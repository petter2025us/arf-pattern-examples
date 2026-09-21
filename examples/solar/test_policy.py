"""Fixture-driven tests for residential solar sales claims.

Structurally identical to every other domain here: same runner, same engine,
same assertions. Only `fixtures.json` and the policy differ. That sameness is
the claim this repository makes, written so it has to stay true.
"""
from pathlib import Path

import pytest

from examples._fixture_runner import load_cases, run_case
from examples.solar.policy import SolarClaimsPolicy

CASES = load_cases(Path(__file__).parent / "fixtures.json")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fixture_reaches_its_stated_outcome(case):
    run_case(SolarClaimsPolicy(), case)


def test_every_fixture_explains_itself():
    """Each case records why it expects what it expects.

    A fixture whose expectation nobody can explain is a test that gets
    "fixed" by editing the expectation the next time it fails.
    """
    for case in CASES:
        assert case.get("because"), case["name"] + " has no stated rationale"
