"""Power and sample size for average bioequivalence.

THE METHOD IS NAMED, NOT IMPLIED

Power for TOST has no elementary closed form. Three approaches are in common
use, and they do not agree to the last subject:

  * the exact method, via Owen's Q function;
  * the non-central t approximation;
  * a shifted-normal approximation.

This module implements the **non-central t approximation** and says so in the
result. Naming the method matters more than the small differences between them:
a sample size that cannot be traced to a stated method cannot be defended, and
two tools that disagree by one subject are usually two different methods rather
than one bug. The exact Owen's Q method is a deliberate follow-up.

WHAT THE APPROXIMATION IS

Under the alternative, the two one-sided statistics are non-central t variates
with non-centralities

    ncp_lower = (theta - theta_lower) / se
    ncp_upper = (theta - theta_upper) / se

and power is approximated by

    P(T_upper <= -t_crit) - P(T_lower <= t_crit)

clamped at zero. The approximation neglects the dependence between the two
statistics; it is accurate for the sample sizes and variabilities of ordinary
bioequivalence work, and is conservative to a degree that shrinks as n grows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

from be_stats.profiles import DrugClass, RegulatoryProfile

#: The method this module implements, carried into every result it returns.
METHOD = "non-central t approximation"

#: Sample sizes are searched, not solved. This caps the search so a request
#: that cannot be satisfied fails loudly rather than looping.
_MAX_N = 10_000


@dataclass(frozen=True, slots=True)
class PowerResult:
    power: float
    method: str = METHOD


@dataclass(frozen=True, slots=True)
class SampleSizeResult:
    """The smallest total sample size reaching the target power."""

    n_total: int
    #: Per sequence for a crossover, per group for a parallel design. Equal
    #: allocation is assumed; unequal allocation is a separate calculation.
    n_per_group: int
    achieved_power: float
    target_power: float
    design: str
    method: str = METHOD


def _standard_error(design: str, cv_percent: float, n_total: int) -> float:
    """Standard error of the log ratio, for a given total sample size.

    For a 2x2 crossover with n/2 per sequence the standard error of the
    treatment difference is sqrt(sigma_W^2/2 * (2/(n/2))) = sigma_W * sqrt(2/n).
    For two parallel groups of n/2 it is sigma * sqrt(4/n).
    """
    log_variance = math.log1p((cv_percent / 100.0) ** 2)
    sigma = math.sqrt(log_variance)
    if design == "2x2":
        return sigma * math.sqrt(2.0 / n_total)
    if design == "parallel":
        return sigma * math.sqrt(4.0 / n_total)
    raise ValueError(f"Unknown design: {design!r}. Expected '2x2' or 'parallel'.")


def _degrees_of_freedom(design: str, n_total: int) -> int:
    if design == "2x2":
        return n_total - 2
    if design == "parallel":
        return n_total - 2
    raise ValueError(f"Unknown design: {design!r}.")


def power_abe(
    *,
    cv_percent: float,
    n_total: int,
    profile: RegulatoryProfile,
    design: str = "2x2",
    expected_ratio: float = 0.95,
    drug_class: DrugClass = DrugClass.STANDARD,
) -> PowerResult:
    """Power of the TOST procedure at a given sample size.

    `expected_ratio` is the true test/reference ratio being planned against, as
    a fraction. It defaults to 0.95 rather than 1.0 deliberately: planning at
    exact equality assumes the formulations are identical, which is the one
    assumption a bioequivalence study exists to question, and it produces
    sample sizes that are too small whenever it is untrue.
    """
    if not 0.0 < expected_ratio:
        raise ValueError("expected_ratio must be positive.")
    if cv_percent <= 0.0:
        raise ValueError("cv_percent must be positive.")

    acceptance = profile.acceptance_interval(drug_class)
    theta_lower = math.log(acceptance.lower / 100.0)
    theta_upper = math.log(acceptance.upper / 100.0)
    theta = math.log(expected_ratio)

    df = _degrees_of_freedom(design, n_total)
    if df < 1:
        return PowerResult(power=0.0)

    se = _standard_error(design, cv_percent, n_total)
    t_crit = stats.t.ppf(1.0 - profile.alpha, df)

    ncp_lower = (theta - theta_lower) / se
    ncp_upper = (theta - theta_upper) / se

    power = float(
        stats.nct.cdf(-t_crit, df, ncp_upper) - stats.nct.cdf(t_crit, df, ncp_lower)
    )
    # The approximation can return a very small negative number when power is
    # effectively zero. Clamping is honest here; anything below zero is not a
    # probability and reporting it would be worse than rounding it.
    return PowerResult(power=max(0.0, min(1.0, power)))


def sample_size_abe(
    *,
    cv_percent: float,
    profile: RegulatoryProfile,
    design: str = "2x2",
    target_power: float = 0.80,
    expected_ratio: float = 0.95,
    drug_class: DrugClass = DrugClass.STANDARD,
) -> SampleSizeResult:
    """The smallest even total sample size reaching `target_power`.

    Searched upward rather than solved, because the power function is a step
    function of n through the degrees of freedom and a closed-form inversion
    would have to be rounded back onto the steps anyway.

    Only even totals are considered: both designs here allocate equally to two
    groups, and an odd total cannot do that.
    """
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must be between 0 and 1.")

    n = 4
    while n <= _MAX_N:
        achieved = power_abe(
            cv_percent=cv_percent,
            n_total=n,
            profile=profile,
            design=design,
            expected_ratio=expected_ratio,
            drug_class=drug_class,
        ).power
        if achieved >= target_power:
            return SampleSizeResult(
                n_total=n,
                n_per_group=n // 2,
                achieved_power=achieved,
                target_power=target_power,
                design=design,
            )
        n += 2

    raise ValueError(
        f"No sample size up to {_MAX_N} reaches {target_power:.0%} power at "
        f"CV {cv_percent}% with an expected ratio of {expected_ratio}. That "
        "combination is usually a sign the study is infeasible as designed "
        "rather than that it needs more subjects."
    )
