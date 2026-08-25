"""Average bioequivalence.

THE METHOD, STATED SO IT CAN BE CHECKED RATHER THAN TRUSTED

Everything happens on the natural-log scale, because the multiplicative 80-125%
criterion is symmetric there and is not symmetric on the original scale.

For a 2x2 crossover, define for each subject the half period difference

    d_i = (ln y_i,period2 - ln y_i,period1) / 2

Its expectation is (mu_T - mu_R)/2 + (P2 - P1)/2 in sequence RT, and
(mu_R - mu_T)/2 + (P2 - P1)/2 in sequence TR. The period effect is common to
both and cancels in the difference of the sequence means, leaving

    d_bar(RT) - d_bar(TR)  =  mu_T - mu_R

which is the point estimate. Because each d is half the difference of two
observations on the same subject, var(d) = sigma_W^2 / 2, so the residual mean
square of the ANOVA - the within-subject variance on the log scale - is twice
the pooled variance of the d's.

The interval is the ordinary t interval on that difference, at 90% (two
one-sided tests at 5% each), on n1 + n2 - 2 degrees of freedom. Exponentiating
gives the ratio of geometric means and its interval.

WHY NOT A GENERAL MIXED MODEL

For the balanced and unbalanced 2x2 crossover this closed form is exactly what
PROC GLM produces, and it is auditable by hand on a page. A mixed model becomes
necessary for the replicate designs of Phase 2, and that is where it will be
introduced - not before, because an opaque implementation of a case that has a
transparent one is a validation cost with no benefit.

THE ENGINE DOES NOT DECLARE BIOEQUIVALENCE

`AbeResult.conclusion` reports whether the interval fell inside the acceptance
interval for the profile it was given. That is an arithmetic fact. Whether the
product is bioequivalent is a regulatory conclusion drawn by a qualified person
who also knows what was measured, how the study was run, and what else is in
the dossier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

from be_stats.conversions import log_variance_to_cv_percent
from be_stats.spec import AcceptanceInterval, BeSpec
from be_stats.study import (
    CrossoverStudy,
    DataError,
    ParallelStudy,
    Sequence,
    Treatment,
)


@dataclass(frozen=True, slots=True)
class AbeResult:
    """The outcome of one average-bioequivalence assessment."""

    endpoint: str
    design: str
    regulator: str
    drug_class: str

    #: Ratio of geometric means, test over reference, as a percentage.
    point_estimate: float
    ci_lower: float
    ci_upper: float
    confidence_level: float

    #: Within-subject CV for a crossover; between-subject CV for a parallel
    #: design. The two are not interchangeable and the field name would hide
    #: that, so `cv_kind` says which one this is.
    cv_percent: float
    cv_kind: str

    degrees_of_freedom: int
    n_subjects: int

    acceptance: AcceptanceInterval

    #: True when the whole confidence interval lies inside the acceptance
    #: interval. An arithmetic fact, not a regulatory verdict - see module docs.
    within_acceptance_interval: bool

    #: On the log scale: the estimate and its standard error, kept because a
    #: reviewer reproducing this by hand needs them and rounding the percentages
    #: loses them.
    log_point_estimate: float
    log_standard_error: float

    def summary(self) -> str:
        verdict = (
            "inside the acceptance interval"
            if self.within_acceptance_interval
            else "NOT inside the acceptance interval"
        )
        return (
            f"{self.endpoint}: ratio {self.point_estimate:.2f}% "
            f"({self.confidence_level:.0%} CI {self.ci_lower:.2f}-"
            f"{self.ci_upper:.2f}%), {verdict} "
            f"[{self.acceptance.lower_value:.2f}-{self.acceptance.upper_value:.2f}%, "
            f"{self.acceptance.basis}]"
        )


def _interval(
    log_diff: float,
    standard_error: float,
    df: int,
    spec: BeSpec,
) -> tuple[float, float, float]:
    """The point estimate and confidence limits, as percentages."""
    # Two one-sided tests at `alpha` each => a (1 - 2*alpha) interval. The
    # quantile is 1 - alpha, not 1 - alpha/2: this is the single place the
    # TOST structure enters, and getting it wrong would silently widen or
    # narrow every result the engine produces.
    t_crit = stats.t.ppf(1.0 - spec.alpha, df)
    half_width = t_crit * standard_error
    return (
        100.0 * math.exp(log_diff),
        100.0 * math.exp(log_diff - half_width),
        100.0 * math.exp(log_diff + half_width),
    )


#: The one conversion, imported rather than repeated. See conversions.py for
#: why this is not allowed to be spelled out locally.
_cv_percent_from_log_variance = log_variance_to_cv_percent


def _reject_zero_variance(variance: float, kind: str) -> None:
    """Refuse a degenerate dataset rather than reporting infinite precision.

    Found by the test suite, not by inspection: a study where every subject
    gives the identical pair of values has a residual variance of exactly zero,
    which divided by zero in the TOST p-values and would otherwise have
    produced a confidence interval of zero width.

    A zero-width 90% interval is not a precise result, it is a broken one - and
    in practice it means duplicated rows, over-rounded data, or a placeholder
    that reached the analysis. Reporting it as an emphatic pass would be the
    worst failure this engine could have.
    """
    if variance <= 0.0:
        raise DataError(
            f"The estimated {kind} variance is zero, so every subject "
            "contributed identical values. No confidence interval can be "
            "formed from that, and a zero-width interval would claim a "
            "precision the data do not contain. This normally means duplicated "
            "rows, values rounded until the differences vanished, or "
            "placeholder data - check the dataset rather than the analysis."
        )


def analyse_crossover(study: CrossoverStudy, spec: BeSpec) -> AbeResult:
    """Average bioequivalence from a 2x2 crossover."""
    acceptance = spec.require_interval()

    halves: dict[Sequence, list[float]] = {}
    for sequence in Sequence:
        rows = study.by_sequence(sequence)
        halves[sequence] = [
            (math.log(o.period_2) - math.log(o.period_1)) / 2.0 for o in rows
        ]

    n_rt = len(halves[Sequence.RT])
    n_tr = len(halves[Sequence.TR])
    df = n_rt + n_tr - 2
    if df < 1:
        raise DataError(
            f"{n_rt + n_tr} subjects across two sequences leaves {df} residual "
            "degrees of freedom. At least one is required."
        )

    mean_rt = sum(halves[Sequence.RT]) / n_rt
    mean_tr = sum(halves[Sequence.TR]) / n_tr

    # The period effect is common to both sequences and cancels here.
    log_diff = mean_rt - mean_tr

    ss = sum((d - mean_rt) ** 2 for d in halves[Sequence.RT]) + sum(
        (d - mean_tr) ** 2 for d in halves[Sequence.TR]
    )
    var_d = ss / df
    _reject_zero_variance(var_d, "within-subject")
    standard_error = math.sqrt(var_d * (1.0 / n_rt + 1.0 / n_tr))

    # var(d) = sigma_W^2 / 2, so the within-subject variance is twice it.
    within_subject_log_variance = 2.0 * var_d

    point, lower, upper = _interval(log_diff, standard_error, df, spec)

    return AbeResult(
        endpoint=study.endpoint,
        design="2x2 crossover",
        regulator=str(spec.jurisdiction),
        drug_class=str(spec.drug_class),
        point_estimate=point,
        ci_lower=lower,
        ci_upper=upper,
        confidence_level=spec.confidence_level,
        cv_percent=_cv_percent_from_log_variance(within_subject_log_variance),
        cv_kind="within-subject",
        degrees_of_freedom=df,
        n_subjects=n_rt + n_tr,
        acceptance=acceptance,
        within_acceptance_interval=acceptance.contains(lower, upper),
        log_point_estimate=log_diff,
        log_standard_error=standard_error,
    )


def analyse_parallel(study: ParallelStudy, spec: BeSpec) -> AbeResult:
    """Average bioequivalence from a parallel-group study.

    Uses the pooled-variance t interval, which assumes the two groups share a
    variance. That assumption is worth testing and is often wrong; a Welch
    interval is a deliberate follow-up rather than a silent default, because
    switching between them changes the degrees of freedom and therefore the
    result.
    """
    acceptance = spec.require_interval()

    log_test = [math.log(v) for v in study.test]
    log_reference = [math.log(v) for v in study.reference]
    n_t, n_r = len(log_test), len(log_reference)
    df = n_t + n_r - 2

    mean_t = sum(log_test) / n_t
    mean_r = sum(log_reference) / n_r
    log_diff = mean_t - mean_r

    ss = sum((v - mean_t) ** 2 for v in log_test) + sum(
        (v - mean_r) ** 2 for v in log_reference
    )
    pooled_variance = ss / df
    _reject_zero_variance(pooled_variance, "pooled between-subject")
    standard_error = math.sqrt(pooled_variance * (1.0 / n_t + 1.0 / n_r))

    point, lower, upper = _interval(log_diff, standard_error, df, spec)

    return AbeResult(
        endpoint=study.endpoint,
        design="parallel",
        regulator=str(spec.jurisdiction),
        drug_class=str(spec.drug_class),
        point_estimate=point,
        ci_lower=lower,
        ci_upper=upper,
        confidence_level=spec.confidence_level,
        cv_percent=_cv_percent_from_log_variance(pooled_variance),
        cv_kind="between-subject (pooled)",
        degrees_of_freedom=df,
        n_subjects=n_t + n_r,
        acceptance=acceptance,
        within_acceptance_interval=acceptance.contains(lower, upper),
        log_point_estimate=log_diff,
        log_standard_error=standard_error,
    )


def tost_p_values(result: AbeResult) -> tuple[float, float]:
    """The two one-sided p-values behind the interval.

    Reported because a reviewer may ask for them, and because they are a
    genuine internal check: the interval falls inside the acceptance limits if
    and only if both are below alpha. The test suite asserts that equivalence
    rather than assuming it.
    """
    lower_limit = math.log(result.acceptance.lower_value / 100.0)
    upper_limit = math.log(result.acceptance.upper_value / 100.0)
    df = result.degrees_of_freedom
    se = result.log_standard_error

    t_lower = (result.log_point_estimate - lower_limit) / se
    t_upper = (result.log_point_estimate - upper_limit) / se

    return (
        float(stats.t.sf(t_lower, df)),  # H0: difference <= lower limit
        float(stats.t.cdf(t_upper, df)),  # H0: difference >= upper limit
    )
