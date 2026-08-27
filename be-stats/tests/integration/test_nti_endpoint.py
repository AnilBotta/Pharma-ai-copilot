"""FDA NTI at the endpoint: three criteria, and what happens when one is absent.

THE CONJUNCTION IS THE POINT

Three booleans give eight combinations and only one of them passes. All eight
are enumerated below rather than sampled, because the failure mode is a
criterion quietly dropping out of the conjunction - and a dropped criterion
shows up in exactly one row.

There is also a ninth case, which is the one this release actually produces:
a criterion that was never computed. It must give `None`, not `False`. An
endpoint never tested against the unscaled limits is untested under this
procedure, and reporting that as a failure would be as wrong as reporting it as
a pass.
"""

from __future__ import annotations

import ast
import inspect
import math
import random
from pathlib import Path

import pytest

from be_stats import nti
from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.howe import HoweUpperBound
from be_stats.nti import (
    FdaNtiResult,
    NtiDesignError,
    NtiScaledMeanCriterion,
    NtiUnscaledAbeCriterion,
    NtiVariabilityRatioCriterion,
    WithinTestVarianceResult,
    assess_nti_endpoint,
    assess_nti_study,
)
from be_stats.reference_variance import ReferenceVarianceResult
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateObservation,
    parse_sequence,
)
from be_stats.spec import fda_nti_theta
from be_stats.study import Treatment

FULLY = ("TRTR", "RTRT")


def synthetic(
    cv_wr: float,
    cv_wt: float,
    seed: int,
    *,
    n_per_sequence: int = 12,
    ratio: float = 0.97,
    labels: tuple[str, ...] = FULLY,
    endpoint: str = "AUC",
) -> ReplicateDataset:
    sigma_r = math.sqrt(math.log1p(cv_wr**2))
    sigma_t = math.sqrt(math.log1p(cv_wt**2))
    rng = random.Random(seed)
    observations = []
    for label in labels:
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject_effect = rng.gauss(0.0, 0.30)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                is_test = treatment is Treatment.TEST
                mean_log = math.log(1000.0) + subject_effect
                if is_test:
                    mean_log += math.log(ratio)
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(
                            mean_log
                            + rng.gauss(0.0, sigma_t if is_test else sigma_r)
                        ),
                    )
                )
    return ReplicateDataset.build(observations)


# ------------------------------------------------------------ design gate ---


def test_the_design_gate_runs_before_any_arithmetic():
    """A partial replicate never reaches a criterion.

    Checked structurally as well as behaviourally: `assess_nti_endpoint` must
    call the gate before it calls anything that estimates.
    """
    partial = synthetic(0.12, 0.13, 5, n_per_sequence=4, labels=("TRR", "RTR", "RRT"))
    with pytest.raises(NtiDesignError):
        assess_nti_endpoint(partial)

    source = Path(inspect.getfile(nti)).read_text(encoding="utf-8")
    function = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "assess_nti_endpoint"
    )
    calls = [
        n.func.id
        for n in ast.walk(function)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls[0] == "require_fully_replicate", (
        f"the gate must be the first call; got {calls[:3]}"
    )


def test_a_two_by_two_crossover_cannot_reach_nti_at_all():
    """There is no replicate dataset for it to arrive as, and that is the
    point: the NTI path starts from a fully replicate structure."""
    from be_stats.replicate import UnsupportedDesign

    with pytest.raises(UnsupportedDesign):
        parse_sequence("TR")


# --------------------------------------------- the eight combinations ---


def _criteria(a: bool, b: bool, c: bool) -> FdaNtiResult:
    """A result assembled by hand, with all three criteria computed.

    `decided=True` is forced here so the conjunction itself is what is under
    test. `assess_nti_endpoint` never produces this state in this release -
    criterion b is structurally unavailable - which is exactly why the
    conjunction needs testing separately from the pipeline.
    """
    scaled = NtiScaledMeanCriterion(
        bound=HoweUpperBound(
            x=0.001, bound_x=0.01, y=-0.02, bound_y=-0.013,
            theta=fda_nti_theta(), reference_variance=0.018,
            reference_variance_df=22,
            upper_confidence_bound=-0.01 if a else 0.01,
        ),
        sigma_w0=0.10, delta=1.0 / 0.9,
        estimate=0.03, standard_error=0.02, ci_lower=-0.01, ci_upper=0.07,
    )
    unscaled = NtiUnscaledAbeCriterion(
        lower_limit_percent=80.0,
        upper_limit_percent=125.0,
        computed=True,
        reason="fixture",
        ci_lower_percent=92.0 if b else 74.0,
        ci_upper_percent=118.0 if b else 118.0,
    )
    ratio = NtiVariabilityRatioCriterion(
        swt=0.2, swr=0.15, ratio=1.33, df_test=22, df_reference=22,
        ci_lower=0.9, ci_upper=2.0 if c else 3.1, limit=2.5,
    )
    return FdaNtiResult(
        endpoint="AUC",
        design=ReplicateDesign.FULLY_REPLICATE,
        scaled_mean_criterion=scaled,
        unscaled_abe_criterion=unscaled,
        variability_ratio_criterion=ratio,
        reference_variance=None,  # type: ignore[arg-type]
        test_variance=None,  # type: ignore[arg-type]
        treatment_contrast=None,
        decided=True,
    )


@pytest.mark.parametrize(
    "a,b,c,overall",
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, True, True, False),
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, False),
    ],
)
def test_all_eight_combinations_of_the_three_criteria(a, b, c, overall):
    result = _criteria(a, b, c)
    assert result.scaled_mean_criterion.passes is a
    assert result.unscaled_abe_criterion.passes is b
    assert result.variability_ratio_criterion.passes is c
    assert result.passes is overall


def test_only_one_of_eight_combinations_passes():
    """Stated as a property, so a criterion dropping out of the conjunction
    would show up as more than one passing row."""
    passing = [
        (a, b, c)
        for a in (True, False)
        for b in (True, False)
        for c in (True, False)
        if _criteria(a, b, c).passes
    ]
    assert passing == [(True, True, True)]


@pytest.mark.parametrize("missing", ["a", "b", "c"])
def test_one_missing_criterion_yields_not_decided_not_failure(missing):
    """Missing is neither pass nor fail."""
    result = _criteria(True, True, True)
    if missing == "a":
        result = FdaNtiResult(
            **{**_as_kwargs(result), "scaled_mean_criterion": None}
        )
    elif missing == "b":
        result = FdaNtiResult(
            **{
                **_as_kwargs(result),
                "unscaled_abe_criterion": NtiUnscaledAbeCriterion(
                    80.0, 125.0, computed=False, reason="not implemented"
                ),
            }
        )
    else:
        result = FdaNtiResult(
            **{**_as_kwargs(result), "variability_ratio_criterion": None}
        )

    assert result.passes is None
    assert result.passes is not False


def _as_kwargs(result: FdaNtiResult) -> dict:
    import dataclasses

    return {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}


def test_an_unavailable_variability_ratio_blocks_the_verdict():
    """The zero-sWR case, end to end through the conjunction."""
    result = _criteria(True, True, True)
    blocked = FdaNtiResult(
        **{
            **_as_kwargs(result),
            "variability_ratio_criterion": NtiVariabilityRatioCriterion(
                swt=0.2, swr=0.0, ratio=None, df_test=22, df_reference=22,
                ci_lower=None, ci_upper=None, limit=2.5, estimable=False,
            ),
        }
    )
    assert blocked.variability_ratio_criterion.passes is None
    assert blocked.passes is None


# ------------------------------------------- the pipeline, as it stands ---


def test_a_real_endpoint_computes_two_criteria_and_withholds_the_verdict():
    result = assess_nti_endpoint(synthetic(0.12, 0.13, 5))

    assert result.scaled_mean_criterion is not None
    assert result.scaled_mean_criterion.passes in (True, False)
    assert result.variability_ratio_criterion is not None
    assert result.variability_ratio_criterion.passes in (True, False)

    assert result.unscaled_abe_criterion.computed is False
    assert result.unscaled_abe_criterion.passes is None

    assert result.decided is False
    assert result.passes is None

    assert any(
        d.code is DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED
        for d in result.diagnostics
    )


def test_two_of_three_never_becomes_a_verdict():
    """The specific thing the release must not do.

    Both computable criteria passing comfortably still gives NOT DECIDED.
    """
    result = assess_nti_endpoint(synthetic(0.10, 0.11, 3))
    assert result.scaled_mean_criterion.passes is True
    assert result.variability_ratio_criterion.passes is True
    assert result.passes is None
    assert "NOT DECIDED" in result.summary()


def test_the_three_subject_counts_and_degrees_of_freedom_are_separate():
    result = assess_nti_endpoint(synthetic(0.12, 0.13, 5))
    assert result.n_for_swr == 24
    assert result.n_for_swt == 24
    assert result.n_for_treatment_contrast == 24
    assert result.reference_variance_df == 22
    assert result.test_variance_df == 22
    assert result.treatment_contrast_df == 22.0


def test_a_subject_missing_one_test_period_moves_only_the_test_count():
    """sWT needs both test measurements; sWR needs neither."""
    # TRTR period 3 is that subject's SECOND test measurement. Its two
    # reference measurements (periods 2 and 4) are untouched.
    observations = [
        o
        for o in _rows(0.12, 0.13, 5)
        if not (o.subject_id == "TRTR-0" and o.period == 3)
    ]
    result = assess_nti_endpoint(ReplicateDataset.build(observations))

    assert result.n_for_swr == 24, "both reference replicates survive"
    assert result.n_for_swt == 23
    assert result.test_variance_df == 21
    assert result.reference_variance_df == 22


def _rows(cv_wr: float, cv_wt: float, seed: int) -> list[ReplicateObservation]:
    sigma_r = math.sqrt(math.log1p(cv_wr**2))
    sigma_t = math.sqrt(math.log1p(cv_wt**2))
    rng = random.Random(seed)
    observations = []
    for label in FULLY:
        sequence = parse_sequence(label)
        for k in range(12):
            subject_effect = rng.gauss(0.0, 0.30)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                is_test = treatment is Treatment.TEST
                mean_log = math.log(1000.0) + subject_effect
                if is_test:
                    mean_log += math.log(0.97)
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC",
                        math.exp(
                            mean_log
                            + rng.gauss(0.0, sigma_t if is_test else sigma_r)
                        ),
                    )
                )
    return observations


# ------------------------------------------------- endpoint independence ---


def test_auc_and_cmax_are_assessed_independently():
    """One endpoint's outcome must not enter the other's arithmetic."""
    results = assess_nti_study(
        {
            "AUC": synthetic(0.10, 0.11, 3, endpoint="AUC"),
            "Cmax": synthetic(0.10, 0.40, 9, endpoint="Cmax"),
        }
    )

    assert results["AUC"].endpoint == "AUC"
    assert results["Cmax"].endpoint == "Cmax"
    assert results["AUC"].variability_ratio_criterion.passes is True
    assert results["Cmax"].variability_ratio_criterion.passes is False

    # Assessed alone, each endpoint gives exactly the same numbers.
    alone_auc = assess_nti_endpoint(synthetic(0.10, 0.11, 3, endpoint="AUC"))
    alone_cmax = assess_nti_endpoint(synthetic(0.10, 0.40, 9, endpoint="Cmax"))
    for combined, alone in (
        (results["AUC"], alone_auc),
        (results["Cmax"], alone_cmax),
    ):
        assert combined.reference_variance.swr == alone.reference_variance.swr
        assert combined.test_variance.swt == alone.test_variance.swt
        assert (
            combined.variability_ratio_criterion.ci_upper
            == alone.variability_ratio_criterion.ci_upper
        )


# --------------------------------------------------------------- shared ---


def test_the_howe_helper_is_shared_and_theta_is_not():
    """One implementation of the bound, two sets of constants."""
    source = Path(inspect.getfile(nti)).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "howe_upper_bound" in imported
    assert "fda_nti_theta" in imported
    assert "fda_hvd_theta" not in imported, (
        "the NTI module must not reach for the highly-variable theta"
    )

    from be_stats import hvd

    hvd_source = Path(inspect.getfile(hvd)).read_text(encoding="utf-8")
    hvd_imported = {
        alias.name
        for node in ast.walk(ast.parse(hvd_source))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "howe_upper_bound" in hvd_imported
    assert "fda_nti_theta" not in hvd_imported


def test_neither_module_declares_the_others_constants():
    """No bare literals for sigma_w0 or the limits in either module."""
    from be_stats import hvd

    for module, forbidden in (
        (nti, (0.25, 0.294)),
        (hvd, (0.10, 2.5)),
    ):
        source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
        offenders = [
            f"{node.value} at line {node.lineno}"
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, float)
            and any(abs(node.value - f) < 1e-12 for f in forbidden)
        ]
        assert not offenders, (
            f"{module.__name__} declares the other procedure's constants: "
            + ", ".join(offenders)
        )


def test_the_result_cites_appendix_f_and_not_appendix_g():
    """A shared implementation must not drag Appendix G into an NTI citation.

    The sWR estimator is shared with the highly-variable procedure and its own
    `provenance()` cites Appendix G - correctly, there. Appendix F step 1
    states the same closed form, and that is the authority for an NTI result,
    so `FdaNtiResult.provenance()` does not delegate.

    The check is on the CITATION form, `Appendix G (highly variable drugs)`,
    not on the words. The provenance legitimately explains in prose that the
    estimator is shared and where its own citation points - documentation doing
    its job. Phase 1 learned that distinction the hard way, when a
    text-searching guard failed on its own explanatory comment.
    """
    result = assess_nti_endpoint(synthetic(0.12, 0.13, 5))
    text = " ".join(result.provenance())

    assert "Appendix F" in text
    assert "III.B" in text
    assert "May 2026" in text
    assert "primary document" in text

    citation_form = "Appendix G (highly variable drugs)"
    assert citation_form not in text, (
        "an NTI decision is cited to Appendix G"
    )
    # And the shared estimator's own record still says Appendix G, which is
    # right for what that object is.
    assert citation_form in " ".join(result.reference_variance.provenance())


def test_the_nti_method_stays_not_implemented_while_a_criterion_is_missing():
    from be_stats import VALIDATION, Method, ValidationStatus
    from be_stats import CAPABILITY_VALIDATION, Capability

    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.NOT_IMPLEMENTED
    assert (
        CAPABILITY_VALIDATION[Capability.FDA_NTI_UNSCALED_ABE]
        is ValidationStatus.NOT_IMPLEMENTED
    )
    assert (
        CAPABILITY_VALIDATION[Capability.FDA_NTI_DESIGN_VALIDATION]
        is ValidationStatus.IMPLEMENTED
    )
    for status in VALIDATION.values():
        assert status is not ValidationStatus.VALIDATED


def test_ema_abel_did_not_arrive_through_the_nti_module():
    """ABEL is implemented now, and NOT by anything in here.

    This guard used to assert ABEL was absent. It is present as of the EMA
    release, so the useful thing to pin is what has not changed: FDA's NTI
    route and EMA's highly-variable route remain separate procedures in
    separate modules, and implementing one did not generalise into the other.
    """
    from be_stats import VALIDATION, Method, ValidationStatus
    from be_stats import ema_hvd, nti

    assert VALIDATION[Method.EMA_HVD_ABEL] is (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.NOT_IMPLEMENTED

    assert not hasattr(nti, "assess_ema_endpoint")
    assert not hasattr(ema_hvd, "assess_nti_endpoint")

    # The EMA module states its own exclusion. Asserted on the PROSE only:
    # whether the CODE reaches FDA logic is checked in
    # tests/integration/test_regulator_separation.py, because a docstring that
    # says "no sigma_w0" contains the string "sigma_w0" and a text search
    # cannot tell a disclaimer from a use.
    assert "no NTI logic" in ema_hvd.__doc__


# ------------------------------------------------------------- invariance ---


def _quantities(observations) -> tuple:
    result = assess_nti_endpoint(ReplicateDataset.build(observations))
    return (
        result.reference_variance.swr,
        result.test_variance.swt,
        result.scaled_mean_criterion.upper_confidence_bound,
        result.variability_ratio_criterion.ci_lower,
        result.variability_ratio_criterion.ci_upper,
        result.variability_ratio_criterion.passes,
        result.scaled_mean_criterion.passes,
        result.passes,
    )


def test_shuffling_rows_does_not_change_any_nti_quantity():
    observations = _rows(0.12, 0.13, 5)
    baseline = _quantities(observations)

    rng = random.Random(31337)
    for _ in range(12):
        shuffled = observations[:]
        rng.shuffle(shuffled)
        assert _quantities(shuffled) == baseline


def test_renaming_subjects_does_not_change_any_nti_quantity():
    observations = _rows(0.12, 0.13, 5)
    baseline = _quantities(observations)
    renamed = [
        ReplicateObservation(
            f"ANON-{abs(hash(o.subject_id)) % 99991}",
            o.sequence, o.period, o.treatment, o.endpoint, o.value,
        )
        for o in observations
    ]
    assert _quantities(renamed) == baseline


def test_reversing_period_order_does_not_change_any_nti_quantity():
    observations = _rows(0.12, 0.13, 5)
    assert _quantities(list(reversed(observations))) == _quantities(observations)
