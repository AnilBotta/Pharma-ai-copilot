"""FDA and EMA must not be able to reach each other.

WHY THIS FILE EXISTS

FDA RSABE and EMA ABEL are both called "reference scaling" and they are not the
same method. They differ in what triggers scaling, on which SCALE the trigger is
expressed, what gets scaled, which endpoints qualify, whether there is a cap,
and how the criteria combine. Two of their constants happen to be numerically
equal today — the point-estimate range is 80.00-125.00% for both — and one pair
is *nearly* equal, which is worse: EMA's CVwR > 30% is sWR > 0.293560 while FDA
states sWR >= 0.294.

Numeric coincidence between two regulators is not a shared rule. It is two
regulators who currently agree. These tests make the separation structural, so
that changing one cannot move the other.
"""

from __future__ import annotations

import math

import pytest

from be_stats import spec
from be_stats.spec import (
    EMA_ABEL_SCALABLE_ENDPOINTS,
    EMA_HVD_CONSTANTS,
    FDA_HVD_CONSTANTS,
    FDA_NTI_CONSTANTS,
    Endpoint,
    ema_hvd_scaling_eligible,
    fda_hvd_method_for,
)


def test_the_constant_tables_are_distinct_objects():
    """No shared mutable dictionary, and no generic SCALED_BE_CONSTANTS."""
    assert EMA_HVD_CONSTANTS is not FDA_HVD_CONSTANTS
    assert EMA_HVD_CONSTANTS is not FDA_NTI_CONSTANTS
    assert not set(EMA_HVD_CONSTANTS) & {"sigma_w0", "swr_switching_threshold"}
    assert not hasattr(spec, "SCALED_BE_CONSTANTS")
    assert not hasattr(spec, "HVD_CONSTANTS")

    # And no RegulatoryValue object is shared between the two tables, even
    # where the numbers agree.
    fda_values = {id(v) for v in FDA_HVD_CONSTANTS.values()}
    ema_values = {id(v) for v in EMA_HVD_CONSTANTS.values()}
    assert not fda_values & ema_values


def test_mutating_an_ema_constant_cannot_change_an_fda_decision(monkeypatch):
    """Point 17, made operational rather than asserted.

    The FDA switch is read at 0.294. If the two tables were aliased — or if a
    helper resolved through a shared registry — moving EMA's threshold would
    move FDA's answer. It must not.
    """
    swr = 0.2945
    before = fda_hvd_method_for(swr)

    monkeypatch.setitem(
        EMA_HVD_CONSTANTS,
        "cv_wr_scaling_threshold_percent",
        type(EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"])(
            99.0,
            EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"].citation,
            EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"].verification,
        ),
    )
    assert fda_hvd_method_for(swr) is before

    # And the EMA side really did move, so the test is not vacuous.
    eligible, _ = ema_hvd_scaling_eligible(
        cv_wr_percent=50.0, endpoint=Endpoint.CMAX
    )
    assert eligible is False


def test_mutating_an_fda_constant_cannot_change_an_ema_decision(monkeypatch):
    eligible_before, _ = ema_hvd_scaling_eligible(
        cv_wr_percent=31.0, endpoint=Endpoint.CMAX
    )
    assert eligible_before is True

    monkeypatch.setitem(
        FDA_HVD_CONSTANTS,
        "swr_switching_threshold",
        type(FDA_HVD_CONSTANTS["swr_switching_threshold"])(
            0.99,
            FDA_HVD_CONSTANTS["swr_switching_threshold"].citation,
            FDA_HVD_CONSTANTS["swr_switching_threshold"].verification,
        ),
    )
    eligible_after, _ = ema_hvd_scaling_eligible(
        cv_wr_percent=31.0, endpoint=Endpoint.CMAX
    )
    assert eligible_after is True


def test_the_two_triggers_are_different_numbers_and_disagree_for_real_studies():
    """The gap between EMA's derived boundary and FDA's stated one."""
    ema_as_swr = math.sqrt(math.log1p(0.30**2))
    fda = FDA_HVD_CONSTANTS["swr_switching_threshold"].value

    assert ema_as_swr < fda
    assert fda - ema_as_swr == pytest.approx(0.00043962, abs=1e-8)

    # A study in between: EMA scales it, FDA does not.
    swr = 0.2938
    assert 100.0 * math.sqrt(math.expm1(swr**2)) > 30.0
    assert swr < fda


def test_the_endpoint_rules_are_not_shared():
    """EMA restricts scaling to Cmax; FDA has no such endpoint restriction.

    If either grew a shared "scalable endpoints" table, one regulator's rule
    would start governing the other's.
    """
    assert EMA_ABEL_SCALABLE_ENDPOINTS == frozenset({Endpoint.CMAX})
    assert not hasattr(spec, "SCALABLE_ENDPOINTS")

    # FDA's HVD path takes no endpoint argument at all, which is the structural
    # form of "FDA does not restrict by endpoint here".
    import inspect

    assert "endpoint" not in inspect.signature(fda_hvd_method_for).parameters


def test_the_ema_module_imports_nothing_from_the_fda_decision_modules():
    """No Howe, no linearized criterion, no sigma_w0, no NTI.

    EMA scales the LIMITS and then runs an ordinary interval test. FDA scales a
    CRITERION. Sharing code between them would be sharing a method.
    """
    source = (
        __import__("pathlib").Path(spec.__file__).parent / "ema_hvd.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "from be_stats.howe",
        "from be_stats.hvd",
        "from be_stats.nti",
        "from be_stats.reference_variance",
        "from be_stats.treatment_contrast",
        "howe_upper_bound",
        "scaled_criterion",
        "fda_hvd",
        "FDA_HVD_CONSTANTS",
        "FDA_NTI_CONSTANTS",
    ):
        assert forbidden not in source, (
            f"ema_hvd.py refers to {forbidden!r}; EMA must not reach FDA logic"
        )


def test_the_fda_modules_do_not_reach_back_into_ema():
    from pathlib import Path

    package = Path(spec.__file__).parent
    for name in ("hvd.py", "nti.py", "reference_variance.py", "howe.py"):
        source = (package / name).read_text(encoding="utf-8")
        assert "ema_hvd" not in source, name
        assert "EMA_HVD_CONSTANTS" not in source, name


def test_the_shared_helper_is_low_level_and_knows_no_regulator():
    """`linear_model` is the one thing both sides may legitimately share.

    It is allowed to exist because it is arithmetic — a design matrix and a
    least-squares solve — and it stays allowed only while it knows nothing
    about bioequivalence.
    """
    from pathlib import Path

    source = (Path(spec.__file__).parent / "linear_model.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("EMA_HVD_CONSTANTS", "FDA_HVD_CONSTANTS", "Endpoint"):
        assert forbidden not in source

    # It may mention the regulators in prose explaining WHY it is neutral; it
    # may not import from either.
    assert "from be_stats.spec import" not in source
    assert "from be_stats.ema_hvd import" not in source
    assert "from be_stats.hvd import" not in source


def test_the_point_estimate_ranges_agree_today_and_are_still_stored_twice():
    """Numerically equal, structurally separate. That is the whole point."""
    assert EMA_HVD_CONSTANTS["point_estimate_lower_percent"].value == 80.00
    assert FDA_HVD_CONSTANTS["point_estimate_lower"].value == 0.8000
    assert (
        EMA_HVD_CONSTANTS["point_estimate_lower_percent"].citation
        is not FDA_HVD_CONSTANTS["point_estimate_lower"].citation
    )
    assert (
        EMA_HVD_CONSTANTS["point_estimate_lower_percent"].citation.authority
        == "EMA"
    )
    assert (
        FDA_HVD_CONSTANTS["point_estimate_lower"].citation.authority == "FDA"
    )
