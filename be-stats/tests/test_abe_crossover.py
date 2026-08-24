"""Correctness properties of the 2x2 crossover estimator.

WHAT THESE TESTS ARE, AND WHAT THEY ARE NOT

Every assertion here is either an algebraic identity or an invariance that must
hold for the estimator to be the estimator it claims to be. None of them
compares against a number this engine produced, and none of them encodes a
figure recalled from a textbook.

That distinction is the reason `validation/` exists separately. These tests can
show the code computes what the module documentation says it computes. They
cannot show that what the documentation says is what a regulator expects - only
a reference dataset with an independently published answer can do that, and
that is a validation activity with a statistician's signature on it.
"""

from __future__ import annotations

import math

import pytest

from be_stats import (
    EMA,
    FDA,
    CrossoverObservation,
    CrossoverStudy,
    DrugClass,
    NotApplicable,
    Sequence,
    analyse_crossover,
    tost_p_values,
)


def build(pairs_rt, pairs_tr, endpoint="AUC"):
    """A study from (period_1, period_2) pairs for each sequence."""
    obs = [
        CrossoverObservation(f"RT{i}", Sequence.RT, p1, p2)
        for i, (p1, p2) in enumerate(pairs_rt)
    ] + [
        CrossoverObservation(f"TR{i}", Sequence.TR, p1, p2)
        for i, (p1, p2) in enumerate(pairs_tr)
    ]
    return CrossoverStudy(endpoint=endpoint, observations=obs)


# A small balanced study reused across tests. The numbers are arbitrary; no
# assertion below depends on their particular values.
BALANCED = build(
    pairs_rt=[(100.0, 105.0), (90.0, 88.0), (110.0, 119.0), (95.0, 99.0)],
    pairs_tr=[(102.0, 98.0), (115.0, 108.0), (88.0, 91.0), (97.0, 94.0)],
)


def test_balanced_estimate_equals_difference_of_treatment_means():
    """An independent route to the same point estimate.

    For a BALANCED 2x2 the sequence-difference estimator is algebraically equal
    to the plain difference of log treatment means. Computing it the second way
    exercises none of the same code, so agreement is real evidence rather than
    a tautology.

    It is only true when balanced - which is exactly why the estimator is not
    written the plain way. See the unbalanced test below.
    """
    result = analyse_crossover(BALANCED, FDA)

    from be_stats.study import Treatment

    log_t = [
        math.log(o.value_for(Treatment.TEST)) for o in BALANCED.observations
    ]
    log_r = [
        math.log(o.value_for(Treatment.REFERENCE)) for o in BALANCED.observations
    ]
    naive = sum(log_t) / len(log_t) - sum(log_r) / len(log_r)

    assert result.log_point_estimate == pytest.approx(naive, abs=1e-12)


def test_period_effect_does_not_move_the_estimate():
    """The property the crossover design exists for.

    Multiplying every period-2 measurement by a constant is a pure period
    effect. It must leave the treatment estimate untouched; if it does not, the
    design's central advantage has been thrown away somewhere in the code.
    """
    factor = 1.37
    shifted = build(
        pairs_rt=[(p1, p2 * factor) for p1, p2 in
                  [(100.0, 105.0), (90.0, 88.0), (110.0, 119.0), (95.0, 99.0)]],
        pairs_tr=[(p1, p2 * factor) for p1, p2 in
                  [(102.0, 98.0), (115.0, 108.0), (88.0, 91.0), (97.0, 94.0)]],
    )
    base = analyse_crossover(BALANCED, FDA)
    moved = analyse_crossover(shifted, FDA)

    assert moved.log_point_estimate == pytest.approx(
        base.log_point_estimate, abs=1e-12
    )


def test_naive_estimator_would_have_been_wrong_when_unbalanced():
    """Guards the reason for the implementation, not only its output.

    With unequal sequence sizes AND a period effect, the plain difference of
    treatment means is biased while the sequence-difference estimator is not.
    This test asserts the two genuinely disagree there - so that nobody later
    "simplifies" the estimator into the naive form and finds every test still
    passing.
    """
    factor = 1.5  # a large period effect, to make the bias unmistakable
    rt = [(100.0, 105.0 * factor), (90.0, 88.0 * factor), (110.0, 119.0 * factor)]
    tr = [(102.0, 98.0 * factor)]
    study = build(pairs_rt=rt, pairs_tr=tr)

    result = analyse_crossover(study, FDA)

    from be_stats.study import Treatment

    log_t = [math.log(o.value_for(Treatment.TEST)) for o in study.observations]
    log_r = [math.log(o.value_for(Treatment.REFERENCE)) for o in study.observations]
    naive = sum(log_t) / len(log_t) - sum(log_r) / len(log_r)

    assert abs(result.log_point_estimate - naive) > 0.01


def test_scaling_the_test_product_scales_the_ratio():
    """A known multiplicative effect must come back out."""
    k = 1.20
    scaled = build(
        # In RT the test is period 2; in TR it is period 1.
        pairs_rt=[(p1, p2 * k) for p1, p2 in
                  [(100.0, 105.0), (90.0, 88.0), (110.0, 119.0), (95.0, 99.0)]],
        pairs_tr=[(p1 * k, p2) for p1, p2 in
                  [(102.0, 98.0), (115.0, 108.0), (88.0, 91.0), (97.0, 94.0)]],
    )
    base = analyse_crossover(BALANCED, FDA)
    result = analyse_crossover(scaled, FDA)

    assert result.point_estimate == pytest.approx(base.point_estimate * k, rel=1e-12)


def test_swapping_treatments_inverts_the_ratio():
    """T/R and R/T must be reciprocals, and the CI must invert with them."""
    swapped = build(
        pairs_rt=[(p2, p1) for p1, p2 in
                  [(100.0, 105.0), (90.0, 88.0), (110.0, 119.0), (95.0, 99.0)]],
        pairs_tr=[(p2, p1) for p1, p2 in
                  [(102.0, 98.0), (115.0, 108.0), (88.0, 91.0), (97.0, 94.0)]],
    )
    base = analyse_crossover(BALANCED, FDA)
    other = analyse_crossover(swapped, FDA)

    assert other.point_estimate == pytest.approx(1e4 / base.point_estimate, rel=1e-10)
    assert other.ci_lower == pytest.approx(1e4 / base.ci_upper, rel=1e-10)
    assert other.ci_upper == pytest.approx(1e4 / base.ci_lower, rel=1e-10)


def test_tost_agrees_with_the_confidence_interval():
    """The two formulations of the same decision must never disagree.

    TOST at alpha and a (1-2*alpha) interval inside the limits are the same
    test written two ways. Asserting it catches the classic error of using
    t(1-alpha/2) where t(1-alpha) belongs, which would silently change every
    verdict the engine ever produced.
    """
    # A study that clearly passes, and one that clearly fails - the identity
    # has to hold on both sides of the decision, not only where it is easy.
    clearly_fails = build(
        pairs_rt=[(100.0, 158.0), (95.0, 154.0), (110.0, 171.0), (88.0, 143.0)],
        pairs_tr=[(159.0, 101.0), (150.0, 94.0), (172.0, 109.0), (140.0, 89.0)],
    )
    for study in (BALANCED, clearly_fails):
        result = analyse_crossover(study, FDA)
        p_lower, p_upper = tost_p_values(result)
        both_significant = p_lower < FDA.alpha and p_upper < FDA.alpha
        assert both_significant is result.within_acceptance_interval

    # Confirm the second study really did exercise the failing branch, so this
    # test cannot quietly degrade into checking one case twice.
    assert not analyse_crossover(clearly_fails, FDA).within_acceptance_interval


def test_zero_variance_is_refused_rather_than_reported_as_certainty():
    """Found by the suite, not by inspection.

    Identical values for every subject give a residual variance of exactly
    zero. That used to raise ZeroDivisionError inside the p-values and would
    have produced a zero-width confidence interval - an emphatic pass claiming
    a precision the data do not contain.
    """
    from be_stats import DataError

    degenerate = build([(100.0, 160.0)] * 4, [(160.0, 100.0)] * 4)
    with pytest.raises(DataError, match="variance is zero"):
        analyse_crossover(degenerate, FDA)


def test_confidence_interval_brackets_the_point_estimate():
    result = analyse_crossover(BALANCED, FDA)
    assert result.ci_lower < result.point_estimate < result.ci_upper


def test_degrees_of_freedom_and_n():
    result = analyse_crossover(BALANCED, FDA)
    assert result.n_subjects == 8
    assert result.degrees_of_freedom == 6


def test_ema_narrows_the_interval_for_nti_and_fda_refuses():
    """The FDA/EMA divergence, asserted rather than described."""
    ema = analyse_crossover(BALANCED, EMA, DrugClass.NARROW_THERAPEUTIC_INDEX)
    assert (ema.acceptance.lower, ema.acceptance.upper) == (90.00, 111.11)

    with pytest.raises(NotApplicable, match="reference-scaled"):
        analyse_crossover(BALANCED, FDA, DrugClass.NARROW_THERAPEUTIC_INDEX)


def test_highly_variable_is_refused_by_both_rather_than_approximated():
    for profile in (FDA, EMA):
        with pytest.raises(NotApplicable):
            analyse_crossover(BALANCED, profile, DrugClass.HIGHLY_VARIABLE)


def test_standard_interval_is_the_same_for_both_regulators():
    fda = analyse_crossover(BALANCED, FDA)
    ema = analyse_crossover(BALANCED, EMA)
    assert fda.point_estimate == pytest.approx(ema.point_estimate)
    assert (fda.acceptance.lower, fda.acceptance.upper) == (80.00, 125.00)
    assert (ema.acceptance.lower, ema.acceptance.upper) == (80.00, 125.00)


def test_result_records_which_profile_produced_it():
    """A result that does not say whose rules it used is not reportable."""
    assert analyse_crossover(BALANCED, FDA).regulator == "FDA"
    assert analyse_crossover(BALANCED, EMA).regulator == "EMA"
