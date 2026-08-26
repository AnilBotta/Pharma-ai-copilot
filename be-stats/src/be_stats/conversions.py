"""The canonical conversions between a CV and a log-scale standard deviation.

PURE MATHEMATICS. NO REGULATORY RULE LIVES HERE.

On the log scale

    CV_w = sqrt(exp(s_w^2) - 1)        and        s_w = sqrt(ln(1 + CV_w^2))

so a 30% coefficient of variation does **not** equal a log-scale standard
deviation of 0.30. It gives

    sqrt(ln(1 + 0.30^2)) = 0.293560...

A CORRECTION WORTH RECORDING

An earlier version of this module exported that 0.293560 as the FDA switching
threshold, on the reasoning that FDA's published 0.294 was the same quantity
rounded, and that the package should therefore prefer the exact derivation. The
arithmetic was right and the conclusion was wrong.

FDA's guidance defines two *different* things that happen to be numerically
adjacent:

    classification    a highly variable drug has within-subject %CV >= 30%
    method selection  estimated sWR < 0.294  -> ordinary ABE
                      estimated sWR >= 0.294 -> reference-scaled ABE

0.294 is not a rounded display of the first. It is the normative rule for the
second, written by the regulator, and applied to an *estimate* of sWR rather
than to an assumed CV. "Correcting" it to 0.293560 would have replaced FDA's
criterion with the package's own - which is precisely the failure this codebase
is organised to avoid, arrived at from the opposite direction.

Both values now live in `spec.py` as separate `RegulatoryValue`s with separate
citations. This module keeps only the conversion, for the places where a caller
genuinely needs to move between the two scales.
"""

from __future__ import annotations

import math


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
