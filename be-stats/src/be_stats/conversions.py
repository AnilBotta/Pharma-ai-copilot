"""The canonical conversions between a CV and a log-scale standard deviation.

ONE DEFINITION, USED EVERYWHERE

On the log scale

    CV_w = sqrt(exp(s_w^2) - 1)        and        s_w = sqrt(ln(1 + CV_w^2))

so a 30% coefficient of variation does **not** mean s_wR = 0.30. It means

    s_wR = sqrt(ln(1 + 0.30^2)) = 0.293560...

which is where FDA's 0.294 switching value comes from - it is that quantity,
rounded for publication.

WHY THIS MATTERS ENOUGH TO HAVE ITS OWN MODULE

The two numbers differ in the fourth decimal, and the difference is not
cosmetic: a study whose reference variability falls between 0.293560 and 0.294
switches to reference scaling under one reading and stays on conventional
average BE under the other. Those are different tests with different acceptance
criteria.

So the threshold is *derived* here from the CV it represents, and never written
as a literal anywhere in the package. A test asserts that no module reintroduces
`0.294` as a bare constant.
"""

from __future__ import annotations

import math

#: FDA's definition of a highly variable drug: within-subject variability in
#: the BE measure of 30% or greater, and not an NTI drug.
HVD_CV_THRESHOLD = 0.30


def cv_to_log_sd(cv: float) -> float:
    """Coefficient of variation (as a fraction) to log-scale standard deviation."""
    if cv <= 0.0:
        raise ValueError(f"CV must be positive, got {cv}.")
    return math.sqrt(math.log1p(cv * cv))


def log_sd_to_cv(sd: float) -> float:
    """Log-scale standard deviation to coefficient of variation (as a fraction)."""
    if sd < 0.0:
        raise ValueError(f"A standard deviation cannot be negative, got {sd}.")
    return math.sqrt(math.expm1(sd * sd))


def cv_percent_to_log_variance(cv_percent: float) -> float:
    """Convenience for the many call sites that carry CV as a percentage."""
    return cv_to_log_sd(cv_percent / 100.0) ** 2


def log_variance_to_cv_percent(variance: float) -> float:
    if variance < 0.0:
        raise ValueError(f"A variance cannot be negative, got {variance}.")
    return 100.0 * log_sd_to_cv(math.sqrt(variance))


#: The reference-variability value at which FDA switches to reference scaling,
#: DERIVED from the CV it represents rather than transcribed as 0.294.
HVD_SWR_THRESHOLD = cv_to_log_sd(HVD_CV_THRESHOLD)
