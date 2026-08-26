"""Appendix G steps 2 and 3, component by component.

WHY THE COMPONENTS ARE TESTED AND NOT ONLY THE ANSWER

Howe's Approximation I is a chain of four intermediates, and every one of them
has a plausible-looking wrong version. `x` can lose its `- SE^2`. `bound_x` can
take the wrong limit, or forget to square. `y` can lose its sign. `bound_y` can
take the chi-square quantile from the wrong tail.

None of those raises. Each produces a number of the right shape and roughly the
right magnitude, and the endpoint decision flips only for studies near the
boundary - which are exactly the studies that matter. So the intermediates are
asserted individually against the guidance's own SAS.
"""

from __future__ import annotations

import math

import pytest
from scipy import stats

from be_stats.hvd import (
    PointEstimateConstraint,
    RsabeResult,
    ScaledCriterion,
    point_estimate_constraint,
    scaled_criterion,
)
from be_stats.spec import FDA_HVD_CONSTANTS, fda_hvd_theta


def make_criterion(
    *,
    estimate: float,
    standard_error: float,
    ci_lower: float,
    ci_upper: float,
    s2wr: float,
    df_d: int,
    upper_confidence_bound: float = 0.0,
) -> ScaledCriterion:
    """A criterion assembled by hand, for testing the pass/fail predicate."""
    theta = fda_hvd_theta()
    return ScaledCriterion(
        x=estimate**2 - standard_error**2,
        bound_x=max(abs(ci_lower), abs(ci_upper)) ** 2,
        y=-theta * s2wr,
        bound_y=-theta * s2wr * df_d / stats.chi2.ppf(0.95, df_d),
        theta=theta,
        sigma_w0=FDA_HVD_CONSTANTS["sigma_w0"].value,
        reference_variance=s2wr,
        reference_variance_df=df_d,
        upper_confidence_bound=upper_confidence_bound,
    )


# ----------------------------------------------------- the chi-square tail ---


def test_the_chi_square_quantile_is_the_inverse_cdf_not_the_upper_tail():
    """SAS's `cinv(0.95, df)` is the 95th percentile. `isf` is the 5th.

    Confusing them does not raise and does not change the sign. For 20 degrees
    of freedom it scales `bound_y` by roughly a factor of three, which moves
    the decision for a band of real studies and nothing else.
    """
    df = 20
    inverse_cdf = stats.chi2.ppf(0.95, df)
    upper_tail = stats.chi2.isf(0.95, df)

    assert inverse_cdf == pytest.approx(31.4104, abs=1e-3)
    assert upper_tail == pytest.approx(10.8508, abs=1e-3)
    assert inverse_cdf > df > upper_tail

    criterion = make_criterion(
        estimate=0.05, standard_error=0.04,
        ci_lower=-0.02, ci_upper=0.12,
        s2wr=0.2, df_d=df,
    )
    expected = -fda_hvd_theta() * 0.2 * df / inverse_cdf
    assert criterion.bound_y == pytest.approx(expected, rel=1e-12)
    assert criterion.bound_y != pytest.approx(
        -fda_hvd_theta() * 0.2 * df / upper_tail, rel=1e-6
    )


def test_bound_y_is_closer_to_zero_than_y_and_that_is_the_conservative_way():
    """A self-check the implementation can be audited against.

    `y` is negative and `df/chisq_0.95(df) < 1`, so `bound_y > y`. It is an
    upper bound on `-theta*sigma_WR^2`, i.e. a LOWER bound on the reference
    variance - less scaling, a harder criterion. If this inverted, the engine
    would be scaling more generously than FDA.
    """
    for df in (3, 10, 21, 60):
        criterion = make_criterion(
            estimate=0.05, standard_error=0.04,
            ci_lower=-0.02, ci_upper=0.12,
            s2wr=0.15, df_d=df,
        )
        assert criterion.y < 0.0
        assert criterion.bound_y > criterion.y
        assert df / stats.chi2.ppf(0.95, df) < 1.0


# ------------------------------------------------- the linearized criterion ---


def test_the_criterion_follows_the_sas_line_by_line():
    """An independent restatement of the six SAS lines, not a call into them."""
    from be_stats.reference_variance import ReferenceVarianceResult
    from be_stats.replicate import ReplicateDesign
    from be_stats.treatment_contrast import TreatmentContrastResult

    estimate, se = 0.09, 0.05
    ci_lower, ci_upper = 0.005, 0.175
    s2wr, df_d = 0.18, 21

    contrast = TreatmentContrastResult(
        design=ReplicateDesign.PARTIAL_REPLICATE,
        endpoint="AUC",
        estimate=estimate,
        standard_error=se,
        degrees_of_freedom=21.0,
        degrees_of_freedom_basis="fixture",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        alpha=0.10,
        point_estimate=math.exp(estimate),
        n_subjects=24,
        n_by_sequence={},
        sequence_weights={},
        mean_square_error=0.0,
    )
    variance = ReferenceVarianceResult(
        design=ReplicateDesign.PARTIAL_REPLICATE,
        endpoint="AUC",
        variance_wr=s2wr,
        swr=math.sqrt(s2wr),
        cv_wr=0.0,
        degrees_of_freedom=df_d,
        n_subjects=24,
        regulatory_m=3,
        contributing_sequences=3,
        estimable=True,
    )

    got = scaled_criterion(contrast=contrast, reference_variance=variance)

    # Written out longhand from the guidance.
    theta = (math.log(1.25) / 0.25) ** 2
    x = estimate**2 - se**2
    boundx = (max(abs(ci_lower), abs(ci_upper))) ** 2
    y = -theta * s2wr
    boundy = y * df_d / stats.chi2.ppf(0.95, df_d)
    critbound = (x + y) + math.sqrt((boundx - x) ** 2 + (boundy - y) ** 2)

    assert got.x == pytest.approx(x, rel=1e-14)
    assert got.bound_x == pytest.approx(boundx, rel=1e-14)
    assert got.theta == pytest.approx(theta, rel=1e-14)
    assert got.y == pytest.approx(y, rel=1e-14)
    assert got.bound_y == pytest.approx(boundy, rel=1e-14)
    assert got.upper_confidence_bound == pytest.approx(critbound, rel=1e-14)


def test_x_subtracts_the_squared_standard_error():
    """`x = estimate^2 - stderr^2`, not `estimate^2`.

    Dropping the correction biases the criterion upward - toward failing - by
    the sampling variance of the estimate, which is largest in the small
    studies where it matters most.
    """
    criterion = make_criterion(
        estimate=0.10, standard_error=0.06,
        ci_lower=0.0, ci_upper=0.2, s2wr=0.1, df_d=20,
    )
    assert criterion.x == pytest.approx(0.10**2 - 0.06**2, rel=1e-14)
    assert criterion.x != pytest.approx(0.10**2, rel=1e-6)


def test_bound_x_takes_the_larger_absolute_limit_and_squares_it():
    """`max(|LowerCL|, |UpperCL|)^2`. An interval straddling zero is the case
    that separates "larger absolute" from "upper"."""
    straddling = make_criterion(
        estimate=0.0, standard_error=0.05,
        ci_lower=-0.30, ci_upper=0.10, s2wr=0.1, df_d=20,
    )
    assert straddling.bound_x == pytest.approx(0.30**2, rel=1e-14)
    assert straddling.bound_x != pytest.approx(0.10**2, rel=1e-6)


def test_theta_and_sigma_w0_come_from_the_spec_layer():
    """Not re-declared here. The criterion inherits their provenance."""
    criterion = make_criterion(
        estimate=0.05, standard_error=0.04,
        ci_lower=-0.02, ci_upper=0.12, s2wr=0.2, df_d=20,
    )
    assert criterion.sigma_w0 == FDA_HVD_CONSTANTS["sigma_w0"].value == 0.25
    assert criterion.theta == fda_hvd_theta()
    assert criterion.theta == pytest.approx((math.log(1.25) / 0.25) ** 2, rel=1e-15)


# ------------------------------------------------------ criterion A boundary ---


@pytest.mark.parametrize(
    "bound,expected",
    [(1e-12, False), (0.0, True), (-1e-12, True), (-0.05, True), (0.05, False)],
)
def test_criterion_a_passes_at_and_below_zero(bound, expected):
    """FDA: the upper bound "must be <= 0". The boundary passes."""
    criterion = make_criterion(
        estimate=0.05, standard_error=0.04,
        ci_lower=-0.02, ci_upper=0.12, s2wr=0.2, df_d=20,
        upper_confidence_bound=bound,
    )
    assert criterion.passes is expected


# ------------------------------------------------------ criterion B boundary ---


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (0.799999, False),
        (0.800000, True),
        (0.800001, True),
        (1.000000, True),
        (1.249999, True),
        (1.250000, True),
        (1.250001, False),
    ],
)
def test_criterion_b_includes_both_boundaries(ratio, expected):
    """FDA: "must fall within [0.8000, 1.2500]" - a closed interval."""
    constraint = PointEstimateConstraint(
        geometric_mean_ratio=ratio,
        lower_limit=FDA_HVD_CONSTANTS["point_estimate_lower"].value,
        upper_limit=FDA_HVD_CONSTANTS["point_estimate_upper"].value,
    )
    assert constraint.passes is expected


def test_the_constraint_reads_its_limits_from_the_verified_constants():
    from be_stats.replicate import ReplicateDesign
    from be_stats.treatment_contrast import TreatmentContrastResult

    contrast = TreatmentContrastResult(
        design=ReplicateDesign.PARTIAL_REPLICATE,
        endpoint="AUC",
        estimate=math.log(0.9),
        standard_error=0.05,
        degrees_of_freedom=20.0,
        degrees_of_freedom_basis="fixture",
        ci_lower=-0.2,
        ci_upper=0.0,
        alpha=0.10,
        point_estimate=0.9,
        n_subjects=24,
        n_by_sequence={},
        sequence_weights={},
        mean_square_error=0.0,
    )
    constraint = point_estimate_constraint(contrast)
    assert constraint.lower_limit == 0.8000
    assert constraint.upper_limit == 1.2500
    assert constraint.geometric_mean_ratio == 0.9
    assert constraint.passes


# ------------------------------------------------ the two criteria together ---


def _rsabe(scaled_passes: bool, pe_passes: bool) -> RsabeResult:
    criterion = make_criterion(
        estimate=0.05, standard_error=0.04,
        ci_lower=-0.02, ci_upper=0.12, s2wr=0.2, df_d=20,
        upper_confidence_bound=-0.01 if scaled_passes else 0.01,
    )
    constraint = PointEstimateConstraint(
        geometric_mean_ratio=1.00 if pe_passes else 1.40,
        lower_limit=0.8000,
        upper_limit=1.2500,
    )
    return RsabeResult(
        scaled_criterion=criterion,
        point_estimate_constraint=constraint,
        reference_variance=None,  # type: ignore[arg-type]
        treatment_contrast=None,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "scaled,pe,overall",
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ],
)
def test_all_four_combinations_of_the_two_criteria(scaled, pe, overall):
    """The point-estimate constraint must not vanish because the scaled
    statistic passed. Reference scaling widens the acceptance region without
    limit as reference variability grows; criterion B is the stop on it."""
    result = _rsabe(scaled, pe)
    assert result.scaled_criterion.passes is scaled
    assert result.point_estimate_constraint.passes is pe
    assert result.passes is overall


def test_a_wide_ratio_fails_however_variable_the_reference():
    """The failure criterion B exists to catch.

    A hugely variable reference makes `y` very negative, so criterion A passes
    comfortably. The observed ratio is still 1.40, and the endpoint still
    fails.
    """
    result = _rsabe(scaled_passes=True, pe_passes=False)
    assert result.scaled_criterion.passes
    assert not result.passes
    assert "B FAIL" in " ".join(result.explain())


def test_explain_shows_every_component():
    text = " ".join(_rsabe(True, True).explain())
    for fragment in ("x =", "bound_x", "theta", "y =", "bound_y", "critbound",
                     "criterion A", "criterion B", "both criteria are required"):
        assert fragment in text
