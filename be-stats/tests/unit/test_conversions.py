"""The CV / log-SD conversion, and the constant it is not allowed to become.

This is the smallest module in the package and the one most likely to be
quietly duplicated, because writing `math.sqrt(math.log1p(cv**2))` inline is
easier than importing it. These tests make the duplication fail.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from be_stats.conversions import (
    HVD_CV_THRESHOLD,
    HVD_SWR_THRESHOLD,
    cv_to_log_sd,
    log_sd_to_cv,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "be_stats"


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
    # And the gap is larger than the rounding it is often confused with.
    assert abs(cv_to_log_sd(0.30) - 0.294) > 1e-4


def test_the_hvd_threshold_is_derived_from_the_cv():
    assert HVD_CV_THRESHOLD == 0.30
    assert HVD_SWR_THRESHOLD == cv_to_log_sd(HVD_CV_THRESHOLD)


def test_the_rounded_threshold_is_not_a_numeric_literal_in_the_source():
    """Guards the derivation against being "simplified" back to a constant.

    A study whose reference variability falls between 0.293560 and 0.294
    switches methods one way under the derived value and the other way under
    the rounded one. Whichever turns out to be normative, the codebase must not
    contain both.

    Checked by walking the AST for numeric constants rather than by searching
    the text. The first version of this test searched for the string and failed
    on a docstring in `conversions.py` that explains where 0.294 comes from -
    which is documentation doing its job. Prose may name the number; code may
    not contain it.
    """
    import ast

    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, float)
                and abs(node.value - 0.294) < 1e-12
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "0.294 appears as a numeric literal rather than being derived through "
        "cv_to_log_sd(0.30): " + ", ".join(offenders)
    )


def test_the_derived_and_rounded_values_genuinely_differ():
    """The premise of the test above, stated so it cannot rot.

    If these two ever became equal the guard would be pointless, and somebody
    should know.
    """
    assert HVD_SWR_THRESHOLD != pytest.approx(0.294, abs=1e-6)


def test_monotonic():
    sds = [cv_to_log_sd(cv) for cv in (0.05, 0.10, 0.20, 0.40, 0.80)]
    assert sds == sorted(sds)


def test_non_positive_cv_is_refused():
    for bad in (0.0, -0.1):
        with pytest.raises(ValueError, match="must be positive"):
            cv_to_log_sd(bad)


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
