"""Power, sample size, and the input checks that run before either.

As in the crossover suite: these are invariances and internal consistencies,
not comparisons against remembered numbers. Agreement with an independent
implementation is a validation activity and lives in `validation/`.
"""

from __future__ import annotations

import pytest

from be_stats import (
    EMA,
    FDA,
    CrossoverObservation,
    CrossoverStudy,
    DataError,
    ParallelStudy,
    Sequence,
    analyse_parallel,
    power_abe,
    sample_size_abe,
)

# ----------------------------------------------------------------- power ---


def test_power_increases_with_sample_size():
    powers = [
        power_abe(cv_percent=25.0, n_total=n, profile=FDA).power
        for n in (8, 16, 24, 32, 48)
    ]
    assert powers == sorted(powers)
    assert powers[0] < powers[-1]


def test_power_decreases_as_variability_rises():
    powers = [
        power_abe(cv_percent=cv, n_total=32, profile=FDA).power
        for cv in (10.0, 20.0, 30.0, 40.0)
    ]
    assert powers == sorted(powers, reverse=True)


def test_power_is_a_probability():
    for n in (4, 6, 12, 60, 200):
        for cv in (5.0, 25.0, 60.0):
            p = power_abe(cv_percent=cv, n_total=n, profile=FDA).power
            assert 0.0 <= p <= 1.0


def test_power_is_highest_when_the_true_ratio_is_one():
    """Planning at exact equality flatters the study - assert it, so that the
    0.95 default is understood as deliberate rather than arbitrary."""
    at_one = power_abe(
        cv_percent=25.0, n_total=24, profile=FDA, expected_ratio=1.00
    ).power
    at_095 = power_abe(
        cv_percent=25.0, n_total=24, profile=FDA, expected_ratio=0.95
    ).power
    at_090 = power_abe(
        cv_percent=25.0, n_total=24, profile=FDA, expected_ratio=0.90
    ).power
    assert at_one > at_095 > at_090


def test_parallel_needs_more_subjects_than_crossover():
    """A between-subject comparison throws away the pairing, so it must cost
    more. If this ever inverts, the standard errors have been swapped."""
    crossover = sample_size_abe(cv_percent=25.0, profile=FDA, design="2x2").n_total
    parallel = sample_size_abe(
        cv_percent=25.0, profile=FDA, design="parallel"
    ).n_total
    assert parallel > crossover


def test_ema_nti_narrowing_costs_subjects():
    """The EMA/FDA divergence has a price, and the tool should show it."""
    from be_stats import DrugClass

    standard = sample_size_abe(cv_percent=15.0, profile=EMA).n_total
    nti = sample_size_abe(
        cv_percent=15.0,
        profile=EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
    ).n_total
    assert nti > standard


# ----------------------------------------------------------- sample size ---


def test_sample_size_is_the_smallest_that_reaches_target():
    """Both halves matter: the answer must reach the target, and the step below
    it must not - otherwise the search is returning something larger than
    necessary and every study costs more than it needs to."""
    target = 0.80
    result = sample_size_abe(cv_percent=25.0, profile=FDA, target_power=target)

    assert result.achieved_power >= target
    assert result.n_total % 2 == 0

    below = power_abe(
        cv_percent=25.0, n_total=result.n_total - 2, profile=FDA
    ).power
    assert below < target


def test_sample_size_rises_with_variability():
    sizes = [
        sample_size_abe(cv_percent=cv, profile=FDA).n_total
        for cv in (10.0, 20.0, 30.0)
    ]
    assert sizes == sorted(sizes)


def test_higher_target_power_needs_more_subjects():
    at_80 = sample_size_abe(cv_percent=25.0, profile=FDA, target_power=0.80).n_total
    at_90 = sample_size_abe(cv_percent=25.0, profile=FDA, target_power=0.90).n_total
    assert at_90 > at_80


def test_infeasible_request_raises_rather_than_looping():
    """The realistic infeasible case is a ratio sitting on the boundary.

    An earlier version of this test used an enormous CV and asserted it could
    not be powered. That premise was wrong - the search reaches 99% power well
    inside the cap, because subjects buy their way out of variability. What
    subjects cannot buy is a true ratio parked on the acceptance limit: power
    there cannot exceed alpha however large the study, so the search must give
    up and say so.
    """
    with pytest.raises(ValueError, match="infeasible"):
        sample_size_abe(
            cv_percent=25.0,
            profile=FDA,
            target_power=0.80,
            expected_ratio=0.80,
        )


def test_a_very_large_cv_is_merely_expensive_not_infeasible():
    """The counterpart to the test above, so the distinction is recorded."""
    result = sample_size_abe(cv_percent=100.0, profile=FDA, target_power=0.80)
    assert result.achieved_power >= 0.80
    assert result.n_total > 100


def test_method_is_named_on_every_result():
    """A sample size whose method cannot be traced cannot be defended."""
    assert "non-central t" in sample_size_abe(cv_percent=20.0, profile=FDA).method
    assert "non-central t" in power_abe(
        cv_percent=20.0, n_total=24, profile=FDA
    ).method


# ------------------------------------------------------------ input data ---


def test_non_positive_measurement_is_refused():
    with pytest.raises(DataError, match="logarithm"):
        CrossoverObservation("S1", Sequence.RT, 100.0, 0.0)
    with pytest.raises(DataError, match="logarithm"):
        CrossoverObservation("S1", Sequence.RT, -5.0, 100.0)


def test_a_single_sequence_is_refused():
    """With one sequence the treatment effect is completely confounded with
    the period effect. Producing a number here would be worse than failing."""
    obs = [
        CrossoverObservation(f"S{i}", Sequence.RT, 100.0, 105.0) for i in range(6)
    ]
    with pytest.raises(DataError, match="confounded"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_duplicate_subject_is_refused():
    obs = [
        CrossoverObservation("S1", Sequence.RT, 100.0, 105.0),
        CrossoverObservation("S1", Sequence.TR, 100.0, 105.0),
        CrossoverObservation("S2", Sequence.TR, 100.0, 105.0),
    ]
    with pytest.raises(DataError, match="more than once"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_too_few_subjects_is_refused():
    obs = [
        CrossoverObservation("S1", Sequence.RT, 100.0, 105.0),
        CrossoverObservation("S2", Sequence.TR, 100.0, 105.0),
    ]
    with pytest.raises(DataError, match="too few"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_parallel_group_needs_two_subjects():
    with pytest.raises(DataError, match="at least 2|At least 2"):
        ParallelStudy(endpoint="AUC", test=[100.0], reference=[100.0, 101.0])


# --------------------------------------------------------------- parallel ---


def test_parallel_analysis_runs_and_reports_between_subject_cv():
    study = ParallelStudy(
        endpoint="AUC",
        test=[100.0, 110.0, 95.0, 105.0, 98.0, 102.0],
        reference=[99.0, 108.0, 97.0, 103.0, 101.0, 100.0],
    )
    result = analyse_parallel(study, FDA)
    assert result.design == "parallel"
    assert result.cv_kind.startswith("between-subject")
    assert result.degrees_of_freedom == 10
    assert result.ci_lower < result.point_estimate < result.ci_upper
