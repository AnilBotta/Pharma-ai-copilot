"""mu_T - mu_R, and the weighting that decides it.

THE FIXTURES PIN Iij EXACTLY

Every subject below has both reference observations equal to 100, so

    Iij = ln(T) - (ln(100) + ln(100))/2 = ln(T/100)

and a fixture can name the contrast it wants by naming a ratio. That isolates
the contrast from the reference variance completely - which is the point, since
the two are estimated from different subject sets and must be checkable apart.

It also means these datasets have sWR = 0. That is deliberate and harmless:
nothing here calls the variance estimator.
"""

from __future__ import annotations

import math

import pytest

from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    ReplicateSequence,
    parse_sequence,
)
from be_stats.treatment_contrast import (
    CONTRAST_ALPHA,
    FullyReplicateTreatmentContrastEstimator,
    PartialReplicateTreatmentContrastEstimator,
    estimate_treatment_contrast,
    satterthwaite_df,
    subject_weighted_mean,
)


def dataset_from_ratios(
    ratios_by_sequence: dict[str, list[float]], endpoint: str = "AUC"
) -> ReplicateDataset:
    """Build a study where subject j of sequence i has `Iij = ln(ratio)`."""
    observations = []
    for label, ratios in ratios_by_sequence.items():
        sequence = parse_sequence(label)
        for k, ratio in enumerate(ratios):
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                value = 100.0 * ratio if treatment.value == "T" else 100.0
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=value,
                    )
                )
    return ReplicateDataset.build(observations)


BALANCED = {"TRR": [1.00, 1.10], "RTR": [0.90, 0.95], "RRT": [1.05, 1.20]}


# ------------------------------------------------------------------- Iij ---


def test_iij_is_recovered_exactly_from_the_fixture():
    """Guards the fixture itself: if this drifts, every expectation below is
    measuring something other than what its comment claims."""
    dataset = dataset_from_ratios({"TRR": [1.10], "RTR": [0.90], "RRT": [1.25]})
    from be_stats.replicate import treatment_contrasts

    grouped = treatment_contrasts(dataset)
    assert grouped[ReplicateSequence.TRR][0] == pytest.approx(math.log(1.10), rel=1e-12)
    assert grouped[ReplicateSequence.RTR][0] == pytest.approx(math.log(0.90), rel=1e-12)
    assert grouped[ReplicateSequence.RRT][0] == pytest.approx(math.log(1.25), rel=1e-12)


# ------------------------------------------------- equal sequence weights ---
#
# THE UNBALANCED CASE, CALCULATED BY HAND
#
#   TRR   3 subjects   ratios 1.00, 1.10, 1.20
#   RTR   2 subjects   ratios 0.90, 0.95
#   RRT   1 subject    ratio  1.30
#
#   Ibar_1 = (ln1.00 + ln1.10 + ln1.20)/3
#   Ibar_2 = (ln0.90 + ln0.95)/2
#   Ibar_3 =  ln1.30
#
#   FDA estimate       = (Ibar_1 + Ibar_2 + Ibar_3)/3       <- equal SEQUENCE weight
#   naive subject mean = (sum of all six)/6                 <- NOT this
#
#   df  = n - m = 6 - 3 = 3
#   MSE = [ SUM(TRR deviations^2) + SUM(RTR deviations^2) + 0 ] / 3
#   SE  = sqrt( MSE * (1/9)(1/3 + 1/2 + 1/1) )

UNBALANCED = {"TRR": [1.00, 1.10, 1.20], "RTR": [0.90, 0.95], "RRT": [1.30]}


def _hand_calculated_unbalanced() -> dict[str, float]:
    trr = [math.log(r) for r in (1.00, 1.10, 1.20)]
    rtr = [math.log(r) for r in (0.90, 0.95)]
    rrt = [math.log(1.30)]

    mean_trr = sum(trr) / 3
    mean_rtr = sum(rtr) / 2
    mean_rrt = rrt[0]

    estimate = (mean_trr + mean_rtr + mean_rrt) / 3

    ss = sum((v - mean_trr) ** 2 for v in trr)
    ss += sum((v - mean_rtr) ** 2 for v in rtr)
    ss += 0.0  # a single-subject sequence contributes no deviation
    df = 6 - 3
    mse = ss / df
    se = math.sqrt(mse * (1.0 / 9.0) * (1.0 / 3.0 + 1.0 / 2.0 + 1.0 / 1.0))

    return {
        "estimate": estimate,
        "mse": mse,
        "se": se,
        "df": df,
        "subject_mean": (sum(trr) + sum(rtr) + sum(rrt)) / 6,
    }


def test_unbalanced_sequences_use_equal_sequence_weights_not_subject_weights():
    """The single most consequential thing in this module.

    FDA's `estimate 'average' intercept 1 seq 0.3333 0.3333 0.3333` averages
    the three SEQUENCE means. With 3, 2 and 1 subjects the naive subject mean
    is a different number, and dropouts make sequences unequal in almost every
    real study.
    """
    hand = _hand_calculated_unbalanced()
    result = estimate_treatment_contrast(dataset_from_ratios(UNBALANCED))

    assert result.estimable
    assert result.estimate == pytest.approx(hand["estimate"], rel=1e-12)

    # And explicitly NOT the naive mean, which the engine also exposes so the
    # difference can be seen rather than argued about.
    naive = subject_weighted_mean(dataset_from_ratios(UNBALANCED))
    assert naive == pytest.approx(hand["subject_mean"], rel=1e-12)
    assert result.estimate != pytest.approx(naive, rel=1e-6)


def test_the_unbalanced_standard_error_and_df_are_hand_reproducible():
    hand = _hand_calculated_unbalanced()
    result = estimate_treatment_contrast(dataset_from_ratios(UNBALANCED))

    assert result.mean_square_error == pytest.approx(hand["mse"], rel=1e-12)
    assert result.standard_error == pytest.approx(hand["se"], rel=1e-12)
    assert result.degrees_of_freedom == hand["df"]
    assert result.n_by_sequence == {
        ReplicateSequence.TRR: 3,
        ReplicateSequence.RTR: 2,
        ReplicateSequence.RRT: 1,
    }
    assert set(result.sequence_weights.values()) == {1.0 / 3.0}


def test_balanced_sequences_make_the_two_weightings_agree():
    """The reason the mistake survives testing on tidy data.

    With equal group sizes the equal-sequence-weight mean IS the subject mean,
    so a wrong implementation passes every balanced fixture.
    """
    dataset = dataset_from_ratios(BALANCED)
    result = estimate_treatment_contrast(dataset)
    assert result.estimate == pytest.approx(subject_weighted_mean(dataset), rel=1e-12)


def test_the_point_estimate_is_the_exponentiated_contrast():
    result = estimate_treatment_contrast(dataset_from_ratios(BALANCED))
    assert result.point_estimate == pytest.approx(math.exp(result.estimate), rel=1e-15)
    assert result.point_estimate_percent == pytest.approx(
        100.0 * result.point_estimate, rel=1e-15
    )


def test_the_interval_is_two_sided_ninety_percent_on_the_log_scale():
    """FDA writes `estimate ... / cl alpha=0.1`, which is a 90% interval."""
    from scipy import stats

    result = estimate_treatment_contrast(dataset_from_ratios(UNBALANCED))
    assert result.alpha == CONTRAST_ALPHA == 0.10

    t_crit = stats.t.ppf(0.95, result.degrees_of_freedom)
    half = t_crit * result.standard_error
    assert result.ci_lower == pytest.approx(result.estimate - half, rel=1e-12)
    assert result.ci_upper == pytest.approx(result.estimate + half, rel=1e-12)


# ------------------------------------------------------- Satterthwaite df ---


def test_satterthwaite_collapses_to_the_residual_df_for_one_component():
    """Why the fully replicate estimator may use `n - 2` - as a derivation.

    FDA asks for `ddfm=satterth` on a model with no RANDOM and no REPEATED
    statement, so there is a single residual variance component. For one
    component the formula is exactly the component's own degrees of freedom,
    for ANY coefficient.
    """
    for coefficient in (0.1, 1.0, 7.5):
        for residual_df in (2, 5, 22, 97):
            assert satterthwaite_df(
                [(coefficient, 0.037, residual_df)]
            ) == pytest.approx(float(residual_df), rel=1e-12)


def test_the_general_formula_agrees_with_the_exact_collapse():
    """Verifies the identity the single-component shortcut relies on.

    `satterthwaite_df` returns `v` directly for one component, because
    evaluating `2t^2 / (2t^2 / v)` in floating point yields 20.999999999999996
    and a report should not print that. The shortcut is legitimate only if the
    general expression really does reproduce `v`, so here it is evaluated
    longhand and compared.
    """
    for g in (0.0417, 1.0, 7.5):
        for s2 in (1e-6, 0.0371, 12.5):
            for v in (2, 21, 22, 97):
                numerator = g * s2
                denominator = (g**2) * 2.0 * (s2**2) / v
                general = 2.0 * (numerator**2) / denominator
                assert general == pytest.approx(float(v), rel=1e-12)
                assert satterthwaite_df([(g, s2, v)]) == float(v)


def test_satterthwaite_is_between_the_component_dfs_for_two_components():
    """The general behaviour, so the collapse above is not a coincidence of
    the implementation returning its last argument."""
    df = satterthwaite_df([(1.0, 0.02, 10), (1.0, 0.02, 40)])
    assert 10 < df < 40


def test_satterthwaite_refuses_a_zero_variance():
    with pytest.raises(ValueError, match="zero"):
        satterthwaite_df([(1.0, 0.0, 10)])


def test_the_fully_replicate_estimator_reports_satterthwaite_df():
    ratios = {"TRTR": [1.00, 1.10, 1.05, 0.98], "RTRT": [0.92, 1.02]}
    result = estimate_treatment_contrast(dataset_from_ratios(ratios))

    assert result.estimable
    assert result.n_subjects == 6
    # n - m with m = 2, reached through the Satterthwaite formula.
    assert result.degrees_of_freedom == pytest.approx(4.0, rel=1e-12)
    assert "Satterthwaite" in result.degrees_of_freedom_basis
    assert set(result.sequence_weights.values()) == {0.5}


def test_the_fully_replicate_iij_is_the_mean_of_two_ts_less_the_mean_of_two_rs():
    """FDA: `ilat = 0.5*(lat1t + lat2t - lat1r - lat2r)`."""
    sequence = parse_sequence("TRTR")
    values = {1: 120.0, 2: 100.0, 3: 130.0, 4: 110.0}
    observations = [
        ReplicateObservation(
            "S", sequence, p, sequence.expected_treatment(p), "AUC", v
        )
        for p, v in values.items()
    ]
    record = ReplicateDataset.build(
        observations
        + [
            ReplicateObservation(
                "T", parse_sequence("RTRT"), p,
                parse_sequence("RTRT").expected_treatment(p), "AUC", 100.0,
            )
            for p in range(1, 5)
        ]
    ).records[0]

    expected = 0.5 * (
        math.log(120.0) + math.log(130.0) - math.log(100.0) - math.log(110.0)
    )
    assert record.treatment_contrast() == pytest.approx(expected, rel=1e-15)


# -------------------------------------------------------------- refusals ---


def test_the_estimators_refuse_each_others_designs():
    partial = dataset_from_ratios(BALANCED)
    fully = dataset_from_ratios({"TRTR": [1.0, 1.1], "RTRT": [0.9, 1.0]})

    with pytest.raises(ValueError, match="not interchangeable"):
        FullyReplicateTreatmentContrastEstimator().estimate(partial)
    with pytest.raises(ValueError, match="not interchangeable"):
        PartialReplicateTreatmentContrastEstimator().estimate(fully)


def test_a_missing_sequence_makes_the_contrast_non_estimable():
    """A mean that does not exist cannot be given a weight of one third."""
    result = estimate_treatment_contrast(
        dataset_from_ratios({"TRR": [1.0, 1.1], "RTR": [0.9, 1.0]})
    )
    assert not result.estimable
    assert any(
        d.code is DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS
        for d in result.diagnostics
    )


def test_too_few_subjects_leaves_no_residual_degrees_of_freedom():
    result = estimate_treatment_contrast(
        dataset_from_ratios({"TRR": [1.0], "RTR": [0.9], "RRT": [1.1]})
    )
    assert not result.estimable
    assert any(
        d.code is DiagnosticCode.INSUFFICIENT_CONTRAST_DF
        for d in result.diagnostics
    )


def test_a_subject_without_a_test_measurement_is_excluded_from_the_contrast():
    """The severity change from the previous release, asserted.

    sWR needs only the reference replicates, so this was ADVISORY there. The
    contrast cannot be formed without a test observation, so it is an
    EXCLUSION here - same code, different consequence.
    """
    observations = []
    for label, ratios in BALANCED.items():
        sequence = parse_sequence(label)
        for k, ratio in enumerate(ratios):
            for period in range(1, 4):
                treatment = sequence.expected_treatment(period)
                if label == "TRR" and k == 0 and treatment.value == "T":
                    continue  # this subject never took the test product
                value = 100.0 * ratio if treatment.value == "T" else 100.0
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC", value
                    )
                )
    result = estimate_treatment_contrast(ReplicateDataset.build(observations))

    assert result.estimable
    assert result.n_subjects == 5, "six subjects, five with a contrast"
    excluded = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.MISSING_TEST_OBSERVATION
    ]
    assert len(excluded) == 1
    assert excluded[0].severity is Severity.EXCLUSION
    assert excluded[0].subject == "TRR-0"


def test_zero_contrast_variance_is_reported_and_flagged():
    """Same principle as the reference variance: report, flag, do not refuse."""
    result = estimate_treatment_contrast(
        dataset_from_ratios({"TRR": [1.1, 1.1], "RTR": [1.1, 1.1], "RRT": [1.1, 1.1]})
    )
    assert result.estimable
    assert result.mean_square_error == 0.0
    assert result.standard_error == 0.0
    flagged = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.ZERO_CONTRAST_VARIANCE
    ]
    assert len(flagged) == 1
    assert flagged[0].severity is Severity.DATA_QUALITY
