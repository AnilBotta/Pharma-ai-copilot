"""FDA NTI: sWT, the variance-ratio interval, and the three criteria.

WHAT IS CHECKED HERE

The arithmetic of each criterion in isolation, with fixtures that pin the
quantity under test and leave the rest inert. The endpoint wiring is in
`tests/integration/test_nti_endpoint.py`.

THE INTERVAL IS THE PART MOST LIKELY TO BE WRONG

Appendix F step 4 names the distribution and the tails:

    [ (sWT/sWR) / sqrt(F_{alpha/2}(v1,v2)),
      (sWT/sWR) / sqrt(F_{1-alpha/2}(v1,v2)) ]

where `F_p(v1, v2)` has probability `p` to its RIGHT. That is an upper-tail
quantile - `scipy.stats.f.isf` - and `f.ppf` is the other one. Swapping them
produces an interval that is still ordered, still positive and roughly the
reciprocal of the right answer, which fails nothing and decides differently.
"""

from __future__ import annotations

import math

import pytest
from scipy import stats

from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.nti import (
    VARIABILITY_ALPHA,
    NtiScaledMeanCriterion,
    NtiUnscaledAbeCriterion,
    NtiVariabilityRatioCriterion,
    WithinTestVarianceResult,
    estimate_test_variance,
    require_fully_replicate,
    variability_ratio_criterion,
)
from be_stats.reference_variance import (
    ReferenceVarianceResult,
    estimate_reference_variance,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    ReplicateSequence,
    parse_sequence,
)
from be_stats.spec import FDA_NTI_CONSTANTS, fda_nti_theta


def fully_replicate(
    ratios_by_sequence: dict[str, list[tuple[float, float]]],
    endpoint: str = "AUC",
) -> ReplicateDataset:
    """Build a TRTR/RTRT study from (test ratio, reference ratio) pairs.

    Period 1 of each pair scales by the ratio and period 2 sits at 100, so a
    subject's test difference is `ln(test_ratio)` and its reference difference
    is `ln(reference_ratio)` exactly.
    """
    observations = []
    for label, pairs in ratios_by_sequence.items():
        sequence = parse_sequence(label)
        for k, (test_ratio, reference_ratio) in enumerate(pairs):
            seen = {"T": 0, "R": 0}
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                key = treatment.value
                first = seen[key] == 0
                seen[key] += 1
                ratio = test_ratio if key == "T" else reference_ratio
                value = 100.0 * ratio if first else 100.0
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


BALANCED = {
    "TRTR": [(1.10, 1.05), (0.92, 1.12), (1.04, 0.94)],
    "RTRT": [(1.08, 0.97), (0.95, 1.09), (1.01, 1.03)],
}


# ------------------------------------------------------------ design gate ---


@pytest.mark.parametrize("labels", [("TRR", "RTR", "RRT")])
def test_a_partial_replicate_is_refused_before_any_arithmetic(labels):
    """III.B: NTI needs a fully replicate design. A partial replicate gives
    each subject ONE test measurement, so criterion c has no numerator."""
    observations = []
    for label in labels:
        sequence = parse_sequence(label)
        for k in range(3):
            for period in range(1, 4):
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period,
                        sequence.expected_treatment(period), "AUC",
                        100.0 + k + period,
                    )
                )
    dataset = ReplicateDataset.build(observations)

    from be_stats.nti import NtiDesignError

    with pytest.raises(NtiDesignError) as exc:
        require_fully_replicate(dataset)
    assert exc.value.code is (
        DiagnosticCode.NTI_REQUIRES_FULLY_REPLICATE_DESIGN
    )
    assert "fully replicate" in str(exc.value)
    assert "no fallback" in str(exc.value)


def test_a_fully_replicate_design_passes_the_gate():
    require_fully_replicate(fully_replicate(BALANCED))


# ------------------------------------------------------------------- sWT ---


def test_test_differences_are_recovered_exactly_from_the_fixture():
    dataset = fully_replicate({"TRTR": [(1.20, 1.05)], "RTRT": [(0.90, 1.02)]})
    from be_stats.replicate import test_differences

    grouped = test_differences(dataset)
    assert grouped[ReplicateSequence.TRTR][0] == pytest.approx(
        math.log(1.20), rel=1e-12
    )
    assert grouped[ReplicateSequence.RTRT][0] == pytest.approx(
        math.log(0.90), rel=1e-12
    )


def test_swt_uses_the_same_estimator_as_swr():
    """One formula. sWT is Appendix F step 1 applied to the test replicates.

    Asserted by swapping the roles: a study whose TEST differences equal
    another study's REFERENCE differences must give the same number from the
    two estimators.
    """
    pairs = [(1.10, 1.30), (0.92, 0.88), (1.04, 1.15), (0.97, 1.02)]
    as_test = fully_replicate(
        {"TRTR": [(t, 1.0) for t, _ in pairs[:2]],
         "RTRT": [(t, 1.0) for t, _ in pairs[2:]]}
    )
    as_reference = fully_replicate(
        {"TRTR": [(1.0, t) for t, _ in pairs[:2]],
         "RTRT": [(1.0, t) for t, _ in pairs[2:]]}
    )

    swt = estimate_test_variance(as_test)
    swr = estimate_reference_variance(as_reference)

    assert swt.estimable and swr.estimable
    assert swt.variance_wt == pytest.approx(swr.variance_wr, rel=1e-15)
    assert swt.degrees_of_freedom == swr.degrees_of_freedom


def test_swt_uses_the_designs_m_of_two():
    result = estimate_test_variance(fully_replicate(BALANCED))
    assert result.estimable
    assert result.n_subjects == 6
    assert result.regulatory_m == 2
    assert result.degrees_of_freedom == 4


def test_swt_is_hand_reproducible():
    """Two subjects per sequence, so each sequence's deviation sum is
    `(d1 - d2)^2 / 2` - a different route than the estimator's mean."""
    ratios = {
        "TRTR": [(1.10, 1.0), (1.30, 1.0)],
        "RTRT": [(0.90, 1.0), (1.20, 1.0)],
    }
    result = estimate_test_variance(fully_replicate(ratios))

    pairs = [(1.10, 1.30), (0.90, 1.20)]
    ss = sum((math.log(a) - math.log(b)) ** 2 / 2.0 for a, b in pairs)
    expected = ss / (2.0 * (4 - 2))

    assert result.variance_wt == pytest.approx(expected, rel=1e-12)
    assert result.swt == pytest.approx(math.sqrt(expected), rel=1e-12)


def test_swt_refuses_a_missing_sequence():
    result = estimate_test_variance(
        fully_replicate({"TRTR": [(1.1, 1.0), (1.2, 1.0)]})
    )
    assert not result.estimable
    assert any(
        d.code is DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS
        for d in result.diagnostics
    )


def test_swt_is_not_pooled_with_swr():
    """The two variances must move independently.

    Changing only the reference measurements must leave sWT untouched. An
    estimator that pooled them would drift.
    """
    a = estimate_test_variance(fully_replicate(BALANCED))
    moved = {
        label: [(t, r * 3.0) for t, r in pairs]
        for label, pairs in BALANCED.items()
    }
    b = estimate_test_variance(fully_replicate(moved))
    assert a.variance_wt == b.variance_wt


# ------------------------------------------- criterion c: the F interval ---


def _variances(swt: float, swr: float, df_t: int, df_r: int):
    test = WithinTestVarianceResult(
        variance_wt=swt**2, swt=swt, degrees_of_freedom=df_t,
        n_subjects=df_t + 2, regulatory_m=2, estimable=True,
    )
    from be_stats.replicate import ReplicateDesign

    reference = ReferenceVarianceResult(
        design=ReplicateDesign.FULLY_REPLICATE,
        endpoint="AUC",
        variance_wr=swr**2,
        swr=swr,
        cv_wr=0.0,
        degrees_of_freedom=df_r,
        n_subjects=df_r + 2,
        regulatory_m=2,
        contributing_sequences=2,
        estimable=True,
    )
    return test, reference


def test_the_interval_uses_upper_tail_f_quantiles():
    """`F_p(v1,v2)` has probability p to its RIGHT: `f.isf`, not `f.ppf`."""
    test, reference = _variances(0.15, 0.12, df_t=22, df_r=20)
    got = variability_ratio_criterion(
        test_variance=test, reference_variance=reference
    )

    ratio = 0.15 / 0.12
    expected_lower = ratio / math.sqrt(stats.f.isf(0.05, 22, 20))
    expected_upper = ratio / math.sqrt(stats.f.isf(0.95, 22, 20))

    assert got.ratio == pytest.approx(ratio, rel=1e-14)
    assert got.ci_lower == pytest.approx(expected_lower, rel=1e-14)
    assert got.ci_upper == pytest.approx(expected_upper, rel=1e-14)

    # The wrong tail is still ordered and still positive, which is why it
    # would not be noticed.
    wrong_upper = ratio / math.sqrt(stats.f.ppf(0.95, 22, 20))
    assert got.ci_upper != pytest.approx(wrong_upper, rel=1e-6)


def test_the_interval_brackets_the_ratio_and_is_ordered():
    for df_t, df_r in ((5, 5), (22, 20), (20, 22), (60, 12)):
        test, reference = _variances(0.15, 0.12, df_t, df_r)
        got = variability_ratio_criterion(
            test_variance=test, reference_variance=reference
        )
        assert got.ci_lower < got.ratio < got.ci_upper


def test_the_degrees_of_freedom_are_not_interchangeable():
    """v1 belongs to sWT, v2 to sWR. Swapping them changes the interval.

    They can differ for a real reason: a subject missing one of its four
    measurements contributes to one variance and not the other.
    """
    test_a, reference_a = _variances(0.15, 0.12, df_t=30, df_r=8)
    test_b, reference_b = _variances(0.15, 0.12, df_t=8, df_r=30)

    a = variability_ratio_criterion(
        test_variance=test_a, reference_variance=reference_a
    )
    b = variability_ratio_criterion(
        test_variance=test_b, reference_variance=reference_b
    )
    assert a.ratio == b.ratio
    assert a.ci_upper != pytest.approx(b.ci_upper, rel=1e-6)


def test_alpha_is_ten_percent_for_an_equal_tails_ninety_percent_interval():
    assert VARIABILITY_ALPHA == 0.10
    test, reference = _variances(0.15, 0.12, 22, 20)
    got = variability_ratio_criterion(
        test_variance=test, reference_variance=reference
    )
    assert got.alpha == 0.10


@pytest.mark.parametrize(
    "ci_upper,expected",
    [(2.499999, True), (2.500000, True), (2.500001, False), (1.0, True), (3.0, False)],
)
def test_criterion_c_boundary_is_closed_at_two_point_five(ci_upper, expected):
    criterion = NtiVariabilityRatioCriterion(
        swt=0.2, swr=0.1, ratio=2.0, df_test=20, df_reference=20,
        ci_lower=1.0, ci_upper=ci_upper,
        limit=FDA_NTI_CONSTANTS["variance_ratio_upper_limit"].value,
    )
    assert criterion.limit == 2.5
    assert criterion.passes is expected


def test_a_zero_reference_sd_makes_the_ratio_undefined_not_infinite():
    """The case the previous release created.

    sWR = 0 is a legitimate variance estimate and is reported as one. It is
    also a denominator here, and the quotient does not exist. Infinity is not a
    regulatory result, and "very large, therefore fails" is a decision the
    guidance does not authorise.
    """
    test, reference = _variances(0.15, 0.0, 22, 20)
    got = variability_ratio_criterion(
        test_variance=test, reference_variance=reference
    )

    assert not got.estimable
    assert got.ratio is None
    assert got.ci_upper is None
    assert got.passes is None, "not estimable is not a failure"

    codes = {d.code for d in got.diagnostics}
    assert DiagnosticCode.REFERENCE_SD_ZERO_VARIANCE_RATIO_UNDEFINED in codes
    assert any(d.severity is Severity.FATAL for d in got.diagnostics)


def test_an_unestimable_test_variance_also_yields_no_criterion():
    from be_stats.replicate import ReplicateDesign

    test = WithinTestVarianceResult(None, None, 0, 0, 2, False, ())
    reference = ReferenceVarianceResult(
        design=ReplicateDesign.FULLY_REPLICATE, endpoint="AUC",
        variance_wr=0.01, swr=0.1, cv_wr=0.1, degrees_of_freedom=20,
        n_subjects=22, regulatory_m=2, contributing_sequences=2, estimable=True,
    )
    got = variability_ratio_criterion(
        test_variance=test, reference_variance=reference
    )
    assert not got.estimable
    assert got.passes is None


# -------------------------------------------------- criterion a and theta ---


def test_theta_comes_from_the_exact_ratio_not_the_rounded_decimal():
    """Appendix F's prose gives `Delta = 1/0.9`; its SAS writes `1.11111`.

    The two disagree in theta by about 1.9e-05 relative. The calculation
    consumes the exact ratio, and this test records both the choice and the
    size of what was chosen against.
    """
    assert FDA_NTI_CONSTANTS["delta"].value == 1.0 / 0.9
    assert FDA_NTI_CONSTANTS["sigma_w0"].value == 0.10

    exact = fda_nti_theta()
    assert exact == pytest.approx((math.log(1.0 / 0.9) / 0.10) ** 2, rel=1e-15)

    rounded = (math.log(1.11111) / 0.10) ** 2
    assert exact != pytest.approx(rounded, rel=1e-9)
    assert abs(exact - rounded) / exact == pytest.approx(1.9e-05, rel=0.1)


def test_nti_theta_is_not_the_hvd_theta():
    """Different sigma_w0, different Delta, different number. A shared Howe
    helper must never imply a shared theta."""
    from be_stats.spec import fda_hvd_theta

    assert fda_nti_theta() != pytest.approx(fda_hvd_theta(), rel=1e-3)
    assert fda_nti_theta() == pytest.approx(1.1100838, abs=1e-6)
    assert fda_hvd_theta() == pytest.approx(0.7966887, abs=1e-6)


@pytest.mark.parametrize(
    "bound,expected",
    [(1e-12, False), (0.0, True), (-1e-12, True), (-0.05, True), (0.05, False)],
)
def test_criterion_a_boundary_is_closed_at_zero(bound, expected):
    from be_stats.howe import HoweUpperBound

    criterion = NtiScaledMeanCriterion(
        bound=HoweUpperBound(
            x=0.001, bound_x=0.01, y=-0.02, bound_y=-0.013,
            theta=fda_nti_theta(), reference_variance=0.018,
            reference_variance_df=22, upper_confidence_bound=bound,
        ),
        sigma_w0=0.10, delta=1.0 / 0.9,
        estimate=0.03, standard_error=0.02, ci_lower=-0.01, ci_upper=0.07,
    )
    assert criterion.passes is expected


# ------------------------------------------------- criterion b, withheld ---


def test_criterion_b_uses_fda_limits_and_never_the_ema_narrowed_ones():
    """The single most important thing not to get wrong about FDA NTI.

    90.00-111.11% is EMA's narrowed interval for the same drug class. FDA does
    not narrow - it adds criteria, and its unscaled limits stay 80.00-125.00%.
    """
    criterion = NtiUnscaledAbeCriterion(
        lower_limit_percent=FDA_NTI_CONSTANTS["unscaled_lower_percent"].value,
        upper_limit_percent=FDA_NTI_CONSTANTS["unscaled_upper_percent"].value,
        reason="fixture",
    )
    assert criterion.lower_limit_percent == 80.00
    assert criterion.upper_limit_percent == 125.00
    assert criterion.lower_limit_percent != 90.00
    assert criterion.upper_limit_percent != pytest.approx(111.11, abs=0.01)


def test_criterion_b_is_none_while_uncomputed_never_false():
    criterion = NtiUnscaledAbeCriterion(80.0, 125.0, computed=False, reason="x")
    assert criterion.passes is None
    assert criterion.passes is not False


def test_the_containment_test_is_written_out_for_when_it_is_computed():
    """So that implementing Appendix C is a matter of supplying the interval,
    not of also deciding what to do with it."""
    inside = NtiUnscaledAbeCriterion(
        80.0, 125.0, computed=True, reason="",
        ci_lower_percent=92.0, ci_upper_percent=118.0,
    )
    below = NtiUnscaledAbeCriterion(
        80.0, 125.0, computed=True, reason="",
        ci_lower_percent=79.99, ci_upper_percent=118.0,
    )
    boundary = NtiUnscaledAbeCriterion(
        80.0, 125.0, computed=True, reason="",
        ci_lower_percent=80.0, ci_upper_percent=125.0,
    )
    assert inside.passes is True
    assert below.passes is False
    assert boundary.passes is True, "FDA's interval includes its boundaries"
