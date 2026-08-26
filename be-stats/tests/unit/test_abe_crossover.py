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
    CrossoverObservation,
    CrossoverStudy,
    DataError,
    DrugClass,
    Endpoint,
    Jurisdiction,
    NotImplementedMethod,
    Sequence,
    Treatment,
    analyse_crossover,
    resolve_be_spec,
    tost_p_values,
)

FDA_SPEC = resolve_be_spec(jurisdiction=Jurisdiction.FDA)
EMA_SPEC = resolve_be_spec(jurisdiction=Jurisdiction.EMA)
EMA_NTI_AUC = resolve_be_spec(
    jurisdiction=Jurisdiction.EMA,
    drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
    endpoint=Endpoint.AUC,
)

RT_PAIRS = [(100.0, 105.0), (90.0, 88.0), (110.0, 119.0), (95.0, 99.0)]
TR_PAIRS = [(102.0, 98.0), (115.0, 108.0), (88.0, 91.0), (97.0, 94.0)]


def build(pairs_rt, pairs_tr, endpoint="AUC"):
    obs = [
        CrossoverObservation(f"RT{i}", Sequence.RT, p1, p2)
        for i, (p1, p2) in enumerate(pairs_rt)
    ] + [
        CrossoverObservation(f"TR{i}", Sequence.TR, p1, p2)
        for i, (p1, p2) in enumerate(pairs_tr)
    ]
    return CrossoverStudy(endpoint=endpoint, observations=obs)


BALANCED = build(RT_PAIRS, TR_PAIRS)


def _naive_log_difference(study: CrossoverStudy) -> float:
    """Difference of log treatment means, by a route the estimator never takes."""
    log_t = [math.log(o.value_for(Treatment.TEST)) for o in study.observations]
    log_r = [math.log(o.value_for(Treatment.REFERENCE)) for o in study.observations]
    return sum(log_t) / len(log_t) - sum(log_r) / len(log_r)


def test_balanced_estimate_equals_difference_of_treatment_means():
    """An independent route to the same point estimate.

    For a BALANCED 2x2 the sequence-difference estimator is algebraically equal
    to the plain difference of log treatment means. Computing it the second way
    exercises none of the same code, so agreement is evidence rather than a
    tautology. It holds only when balanced - see the unbalanced test below.
    """
    result = analyse_crossover(BALANCED, FDA_SPEC)
    assert result.log_point_estimate == pytest.approx(
        _naive_log_difference(BALANCED), abs=1e-12
    )


def test_period_effect_does_not_move_the_estimate():
    """The property the crossover design exists for.

    Multiplying every period-2 measurement by a constant is a pure period
    effect. It must leave the treatment estimate untouched; if it does not, the
    design's central advantage has been thrown away somewhere in the code.
    """
    f = 1.37
    shifted = build(
        [(p1, p2 * f) for p1, p2 in RT_PAIRS],
        [(p1, p2 * f) for p1, p2 in TR_PAIRS],
    )
    assert analyse_crossover(shifted, FDA_SPEC).log_point_estimate == pytest.approx(
        analyse_crossover(BALANCED, FDA_SPEC).log_point_estimate, abs=1e-12
    )


def test_naive_estimator_would_have_been_wrong_when_unbalanced():
    """Guards the reason for the implementation, not only its output.

    With unequal sequence sizes AND a period effect the plain difference of
    treatment means is biased while the sequence-difference estimator is not.
    Asserting they genuinely disagree stops anyone later "simplifying" the
    estimator into the naive form and finding every test still passing.
    """
    f = 1.5
    study = build(
        [(100.0, 105.0 * f), (90.0, 88.0 * f), (110.0, 119.0 * f)],
        [(102.0, 98.0 * f)],
    )
    result = analyse_crossover(study, FDA_SPEC)
    assert abs(result.log_point_estimate - _naive_log_difference(study)) > 0.01


def test_scaling_the_test_product_scales_the_ratio():
    k = 1.20
    scaled = build(
        [(p1, p2 * k) for p1, p2 in RT_PAIRS],  # test is period 2 in RT
        [(p1 * k, p2) for p1, p2 in TR_PAIRS],  # test is period 1 in TR
    )
    base = analyse_crossover(BALANCED, FDA_SPEC)
    assert analyse_crossover(scaled, FDA_SPEC).point_estimate == pytest.approx(
        base.point_estimate * k, rel=1e-12
    )


def test_swapping_treatments_inverts_the_ratio():
    swapped = build(
        [(p2, p1) for p1, p2 in RT_PAIRS], [(p2, p1) for p1, p2 in TR_PAIRS]
    )
    base = analyse_crossover(BALANCED, FDA_SPEC)
    other = analyse_crossover(swapped, FDA_SPEC)
    assert other.point_estimate == pytest.approx(1e4 / base.point_estimate, rel=1e-10)
    assert other.ci_lower == pytest.approx(1e4 / base.ci_upper, rel=1e-10)
    assert other.ci_upper == pytest.approx(1e4 / base.ci_lower, rel=1e-10)


def test_tost_agrees_with_the_confidence_interval():
    """The two formulations of the same decision must never disagree.

    TOST at alpha, and a (1-2*alpha) interval inside the limits, are one test
    written two ways. Asserting it catches the classic error of using
    t(1-alpha/2) where t(1-alpha) belongs, which would silently change every
    verdict the engine ever produced.
    """
    clearly_fails = build(
        [(100.0, 158.0), (95.0, 154.0), (110.0, 171.0), (88.0, 143.0)],
        [(159.0, 101.0), (150.0, 94.0), (172.0, 109.0), (140.0, 89.0)],
    )
    for study in (BALANCED, clearly_fails):
        result = analyse_crossover(study, FDA_SPEC)
        p_lower, p_upper = tost_p_values(result)
        both = p_lower < FDA_SPEC.alpha and p_upper < FDA_SPEC.alpha
        assert both is result.within_acceptance_interval

    # Confirm the failing case really did exercise the other branch, so this
    # cannot quietly degrade into checking one side twice.
    assert not analyse_crossover(clearly_fails, FDA_SPEC).within_acceptance_interval


def test_zero_variance_is_refused_rather_than_reported_as_certainty():
    """Found by the suite, not by inspection.

    Identical values for every subject give a residual variance of exactly
    zero. That raised ZeroDivisionError inside the p-values, and would
    otherwise have produced a zero-width 90% interval - an emphatic pass
    claiming a precision the data do not contain.
    """
    degenerate = build([(100.0, 160.0)] * 4, [(160.0, 100.0)] * 4)
    with pytest.raises(DataError, match="variance is zero"):
        analyse_crossover(degenerate, FDA_SPEC)


def test_near_zero_variance_still_produces_a_finite_interval():
    """The counterpart: only exact degeneracy is refused.

    Near-degenerate data is legitimate - it means a very precise study - and
    must still analyse. Refusing it too would be a different failure.
    """
    almost = build(
        [(100.0, 160.0), (100.0, 160.0001), (100.0, 159.9999), (100.0, 160.0002)],
        [(160.0, 100.0), (160.0001, 100.0), (159.9999, 100.0), (160.0002, 100.0)],
    )
    result = analyse_crossover(almost, FDA_SPEC)
    assert math.isfinite(result.ci_lower) and math.isfinite(result.ci_upper)
    assert result.ci_lower < result.point_estimate < result.ci_upper


def test_confidence_interval_brackets_the_point_estimate():
    result = analyse_crossover(BALANCED, FDA_SPEC)
    assert result.ci_lower < result.point_estimate < result.ci_upper
    assert result.n_subjects == 8
    assert result.degrees_of_freedom == 6


def test_ema_nti_auc_uses_the_narrowed_interval():
    result = analyse_crossover(BALANCED, EMA_NTI_AUC)
    assert (result.acceptance.lower_value, result.acceptance.upper_value) == (90.00, 111.11)


def test_estimator_refuses_a_spec_whose_method_it_cannot_run():
    """The gate is on the spec, so no estimator can forget to check."""
    fda_nti = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
    )
    with pytest.raises(NotImplementedMethod, match="fully replicated"):
        analyse_crossover(BALANCED, fda_nti)

    # The highly-variable method is implemented now, and a 2x2 crossover still
    # cannot be analysed under it - for a different and better reason. Its
    # acceptance region moves with the reference variability, so there is no
    # fixed interval for a confidence interval to sit inside.
    from be_stats.spec import NotApplicable

    fda_hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    with pytest.raises(NotApplicable, match="fixed acceptance interval"):
        analyse_crossover(BALANCED, fda_hvd)


def test_standard_interval_is_identical_across_jurisdictions():
    fda = analyse_crossover(BALANCED, FDA_SPEC)
    ema = analyse_crossover(BALANCED, EMA_SPEC)
    assert fda.point_estimate == pytest.approx(ema.point_estimate)
    assert (fda.acceptance.lower_value, fda.acceptance.upper_value) == (80.00, 125.00)
    assert (ema.acceptance.lower_value, ema.acceptance.upper_value) == (80.00, 125.00)


def test_result_records_which_jurisdiction_produced_it():
    """A result that does not say whose rules it used is not reportable."""
    assert analyse_crossover(BALANCED, FDA_SPEC).regulator == "FDA"
    assert analyse_crossover(BALANCED, EMA_SPEC).regulator == "EMA"
