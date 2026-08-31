"""FDA NTI: all three criteria, and the three ways to fail.

WHAT THIS TESTS THAT NOTHING ELSE COULD UNTIL NOW

Appendix F step 5 requires all three criteria to hold. While criterion (b) was
unimplementable the conjunction could not be exercised at all: (b) was
permanently `None`, the endpoint was permanently undecided, and every
combination gave the same answer. The AND was written but never executed.

It executes now, and the ways it can be wrong are specific:

    - treating a `None` criterion as a pass
    - conjoining only the criteria that happen to be present
    - returning the scaled criterion's verdict and calling it the endpoint's

All three agree with a correct implementation on the all-pass case and differ
on exactly the three single-failure cases below. So one case is not enough, and
neither is one failing case.

TWO OF THESE LOOK WRONG UNTIL THE PROCEDURE IS TAKEN SERIOUSLY

`scaled_mean_fails` has a TRUE RATIO OF 1.00 and still fails criterion (a).
That is not a broken fixture. Criterion (a) is reference-scaled with sigma_W0
fixed at 0.10, so for a drug whose within-reference CV is 5% the implied limit
on the mean difference is about 95-105% - far tighter than 80-125% - and a
perfectly matched product can fail on sampling variability alone. FDA's NTI
procedure really is that strict for very low-variability drugs, and a package
that quietly widened it would be approving products FDA would not.

`variability_ratio_fails` passes both mean-based criteria and fails anyway,
because criterion (c) asks a question about the PRODUCT rather than the mean:
is the test as reproducible as the reference? A test formulation with twice the
reference's within-subject variability fails that while its mean sits in the
middle of the acceptance range.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from be_stats.nti import assess_nti_endpoint
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    parse_sequence,
    parse_treatment,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads(
    (ROOT / "validation/nti/cases/criterion_combinations.json").read_text("utf-8")
)["cases"]


def observations(name: str) -> list[ReplicateObservation]:
    return [
        ReplicateObservation(
            subject_id=str(row["subject"]),
            sequence=parse_sequence(row["sequence"]),
            period=row["period"],
            treatment=parse_treatment(row["treatment"]),
            endpoint="AUC",
            value=row["value"],
        )
        for row in CASES[name]["observations"]
    ]


def assess(name: str):
    obs = observations(name)
    return assess_nti_endpoint(ReplicateDataset.build(obs), observations=obs)


def criteria(result) -> tuple[bool | None, bool | None, bool | None]:
    return (
        result.scaled_mean_criterion.passes
        if result.scaled_mean_criterion
        else None,
        result.unscaled_abe_criterion.passes,
        result.variability_ratio_criterion.passes
        if result.variability_ratio_criterion
        else None,
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_case_produces_the_criterion_pattern_it_was_built_for(name: str):
    """The fixture's premise, checked before its conclusion.

    A case that no longer produces its intended pattern is not a failing test
    of the conjunction - it is a broken fixture, and the two must not be
    confused. This assertion separates them.
    """
    expected = CASES[name]["criteria"]
    assert criteria(assess(name)) == (
        expected["a_scaled_mean"],
        expected["b_unscaled_abe"],
        expected["c_variability_ratio"],
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("all_pass", True),
        ("scaled_mean_fails", False),
        ("unscaled_abe_fails", False),
        ("variability_ratio_fails", False),
    ],
)
def test_the_endpoint_passes_only_when_all_three_criteria_pass(
    name: str, expected: bool
):
    result = assess(name)
    assert result.decided is True
    assert result.passes is expected


def test_all_three_criteria_are_computed_in_every_case():
    """`decided` must mean all three were computed, not that some were.

    A `None` anywhere makes the endpoint undecided, and an undecided endpoint
    is not a failing one - so a test asserting only `passes is False` would be
    satisfied by an implementation that never computed anything.
    """
    for name in CASES:
        result = assess(name)
        assert None not in criteria(result), name
        assert result.unscaled_abe_criterion.computed is True


def test_criterion_b_uses_the_unscaled_limits_and_not_emas_narrowed_ones():
    """80.00-125.00%, never 90.00-111.11%.

    The single most likely error in this procedure is importing EMA's narrowed
    interval for the same drug class. FDA's NTI has no narrowed interval; the
    narrowing is in criterion (a), which is reference-scaled, and criterion (b)
    is the ordinary one.
    """
    criterion = assess("all_pass").unscaled_abe_criterion
    assert (criterion.lower_limit_percent, criterion.upper_limit_percent) == (
        80.00,
        125.00,
    )


def test_criterion_b_reports_its_interval_now_that_it_is_computed():
    """A computed criterion that still prints NOT COMPUTED is a stale report.

    `explain()` was written when (b) could never be computed and said so
    unconditionally. A validation report repeating that after the criterion
    started deciding endpoints would understate what the package had done.
    """
    lines = " ".join(assess("all_pass").unscaled_abe_criterion.explain())
    assert "NOT COMPUTED" not in lines
    assert "PASS" in lines

    failing = " ".join(assess("unscaled_abe_fails").unscaled_abe_criterion.explain())
    assert "FAIL" in failing


def test_without_the_raw_observations_the_endpoint_withholds():
    """The old behaviour, preserved rather than removed.

    Appendix C is an available-case analysis and `ReplicateDataset` has already
    dropped subjects that Appendix G's sWR could not use. Given only the
    dataset there is no honest way to compute criterion (b), so the endpoint
    stays undecided - which is different from failing, and must not have
    quietly become a pass now that the code path exists.
    """
    result = assess_nti_endpoint(ReplicateDataset.build(observations("all_pass")))

    assert result.unscaled_abe_criterion.computed is False
    assert result.unscaled_abe_criterion.passes is None
    assert result.decided is False
    assert result.passes is None

    # And the same data DOES decide when the observations are supplied, so the
    # withholding is about the missing input and not about the data.
    assert assess("all_pass").decided is True
