"""The CV / log-SD conversion, and nothing about regulation.

This is the smallest module in the package and the one most likely to be
quietly duplicated, because writing `math.sqrt(math.log1p(cv**2))` inline is
easier than importing it. These tests make the duplication fail.

WHAT USED TO BE HERE, AND WHY IT IS GONE

An earlier version of this file contained an AST-level test that failed the
build if `0.294` appeared anywhere in `src/` as a numeric literal, on the
reasoning that FDA's switching threshold was `cv_to_log_sd(0.30) = 0.293560`
rounded, and so ought to be derived rather than stored.

That guard has been deleted, because the reasoning behind it was wrong. FDA's
`0.294` is not a rounded display of this module's arithmetic - it is the
regulator's own criterion, applied to an *estimate* of sWR. A test forbidding
the regulator's number from appearing in the code was, in effect, a test
requiring the package to substitute its own. The regulatory facts are now
asserted in `tests/integration/test_fda_hvd_thresholds.py`, against
`RegulatoryValue`s that carry their citations.

What remains here is arithmetic, which is all this module ever contained.
"""

from __future__ import annotations

import math

import pytest

from be_stats.conversions import cv_to_log_sd, log_sd_to_cv


def test_round_trip():
    for cv in (0.05, 0.10, 0.20, 0.30, 0.50, 1.00, 2.50):
        assert log_sd_to_cv(cv_to_log_sd(cv)) == pytest.approx(cv, rel=1e-12)


def test_a_thirty_percent_cv_is_not_a_log_sd_of_thirty_percent():
    """The confusion this module exists to prevent.

    They are close enough to look interchangeable and far enough apart to
    change a switching decision.
    """
    assert cv_to_log_sd(0.30) == pytest.approx(0.293560, abs=5e-7)
    assert cv_to_log_sd(0.30) != 0.30


def test_the_conversion_of_thirty_percent_is_not_fdas_threshold():
    """The numerical fact, stated without the conclusion once drawn from it.

    `cv_to_log_sd(0.30)` and FDA's 0.294 differ by roughly 4.4e-4. That is a
    real difference - a study whose estimated sWR falls between them switches
    method one way under one number and the other way under the other - and it
    is *not* evidence that either is a rounding of the other. Which of the two
    governs is a regulatory question, answered in `spec.py`, not here.
    """
    assert abs(cv_to_log_sd(0.30) - 0.294) == pytest.approx(4.4e-4, abs=1e-5)


def test_monotonic():
    sds = [cv_to_log_sd(cv) for cv in (0.05, 0.10, 0.20, 0.40, 0.80)]
    assert sds == sorted(sds)


def test_non_positive_cv_is_refused():
    for bad in (0.0, -0.1):
        with pytest.raises(ValueError, match="must be positive"):
            cv_to_log_sd(bad)


def test_negative_sd_is_refused():
    with pytest.raises(ValueError, match="cannot be negative"):
        log_sd_to_cv(-0.1)


def test_small_cv_approaches_the_log_sd():
    """A sanity anchor: for small variability the two nearly coincide, which is
    exactly why the confusion is easy to make and hard to notice."""
    assert cv_to_log_sd(0.01) == pytest.approx(0.01, rel=1e-4)
    assert cv_to_log_sd(0.50) != pytest.approx(0.50, rel=1e-2)


def test_conversion_matches_its_own_definition():
    """Independent restatement of the formula, not a call to the function."""
    for cv in (0.15, 0.35, 0.60):
        assert cv_to_log_sd(cv) == pytest.approx(
            math.sqrt(math.log(1.0 + cv * cv)), rel=1e-15
        )


def test_the_module_exports_no_regulatory_constant():
    """Provenance is not optional, so a bare float may not live here.

    A regulatory number in this module would be a float without a citation,
    indistinguishable from a remembered one. Anything regulatory belongs in
    `spec.py` as a `RegulatoryValue`.
    """
    import be_stats.conversions as conversions

    public = [n for n in vars(conversions) if not n.startswith("_")]
    assert not [n for n in public if n.isupper()], (
        "conversions.py must export functions only; a constant here would be a "
        "regulatory value without provenance"
    )
