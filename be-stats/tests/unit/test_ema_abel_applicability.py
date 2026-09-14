"""EMA ABEL end to end: which acceptance range applies, and what the result may say.

THE DEFECT THIS FILE PINS

`assess_ema_endpoint` widened every Cmax endpoint whose reference CVwR exceeded
30%. EMA 4.1.10 names two further conditions and the engine asked neither:

    "Those HVDP for which a wider difference in Cmax is considered clinically
    irrelevant based on a sound clinical justification can be assessed with a
    widened acceptance range. ... The request for widened interval must be
    prospectively specified in the protocol."

EMA's Q&A (EMA/618604/2008 Rev. 13, question 4) calls the first "a
prerequisite", and applies it to refuse widening for clopidogrel.

WHAT THE ENGINE NOW DOES

    AUC, any CVwR, any basis             80.00-125.00%, decided
    Cmax, CVwR <= 30%, any basis         80.00-125.00%, decided
    Cmax, CVwR > 30%, justified AND
          prespecified                   exp(+/- 0.760 sWR), capped; decided
    Cmax, CVwR > 30%, either explicitly
          NOT justified / NOT prespecified  80.00-125.00%, decided
    Cmax, CVwR > 30%, either NOT STATED  no decision

The conventional range for an explicitly absent basis follows 4.1.8, which sets
80.00-125.00% for Cmax and says widening applies only "in certain cases". An
unstated basis refuses, because the applicable range then depends on a fact
nobody supplied.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
import random
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

from be_stats import ema_hvd
from be_stats import spec as spec_module
from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.evidence import (
    EVIDENCE_MANIFEST,
    EvidenceRecord,
    EvidenceStatus,
    SourceType,
    evidence_for,
)
from be_stats.dossier.evidence_search import (
    EMA_HVD_ABEL_END_TO_END_SEARCH,
    SearchVerdict,
    adopted_sources,
)
from be_stats.dossier.refusals import DIAGNOSTIC_FOR, RefusalCode
from be_stats.dossier.release_gate import (
    REVIEWED_TRANSITIONS,
    Tier1BRelation,
    assess_tier_1b,
    check_capability,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.ema_hvd import (
    METHOD_A_MODEL,
    EmaAcceptanceStrategy,
    EmaResultInconsistent,
    ReferenceVariability,
    _both_criteria,
    assess_ema_endpoint,
    assess_ema_study,
    ema_abel_limits,
)
from be_stats.provenance import Authority, ValidationStatus
from be_stats.regulatory_rounding import TIE_POLICY, round_half_up
from be_stats.replicate import (
    DataError,
    ReplicateObservation,
    UnsupportedDesign,
    parse_sequence,
)
from be_stats.spec import (
    CAPABILITY_VALIDATION,
    EMA_HVD_CONSTANTS,
    FDA_HVD_CONSTANTS,
    VALIDATION,
    Capability,
    DrugClass,
    EmaWideningJustification,
    EmaWideningPrespecification,
    EmaWideningStatus,
    Endpoint,
    Jurisdiction,
    Method,
    NotApplicable,
    SpecificationRequired,
    ema_abel_widening,
    ema_hvd_variability_eligible,
    fda_hvd_method_for,
    resolve_be_spec,
)
from be_stats.study import Treatment

J = EmaWideningJustification.JUSTIFIED
NJ = EmaWideningJustification.NOT_JUSTIFIED
JS = EmaWideningJustification.NOT_STATED
P = EmaWideningPrespecification.PRESPECIFIED
NP = EmaWideningPrespecification.NOT_PRESPECIFIED
PS = EmaWideningPrespecification.NOT_STATED

S = EmaWideningStatus
BASIS = {"clinical_justification": J, "protocol_prespecification": P}

K = EMA_HVD_CONSTANTS["regulatory_constant_k"].value
CAP_LOWER = EMA_HVD_CONSTANTS["cap_lower_percent"].value
CAP_UPPER = EMA_HVD_CONSTANTS["cap_upper_percent"].value
PE = (
    EMA_HVD_CONSTANTS["point_estimate_lower_percent"].value,
    EMA_HVD_CONSTANTS["point_estimate_upper_percent"].value,
)


def swr_for(cv_percent: float) -> float:
    return math.sqrt(math.log1p((cv_percent / 100.0) ** 2))


def study(
    *,
    cv_wr_percent: float,
    ratio: float = 0.95,
    n_per_sequence: int = 30,
    endpoint: str = "Cmax",
    labels: tuple[str, ...] = ("TRTR", "RTRT"),
    seed: int = 7,
) -> list[ReplicateObservation]:
    rng = random.Random(seed)
    sigma = swr_for(cv_wr_percent)
    rows: list[ReplicateObservation] = []
    for label in labels:
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            effect = rng.gauss(0.0, 0.35)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean = effect + (math.log(ratio) if treatment is Treatment.TEST else 0.0)
                rows.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(mean + rng.gauss(0.0, sigma)),
                    )
                )
    return rows


def with_exact_cv(monkeypatch, cv_percent: float) -> None:
    """Make the reference variability EXACTLY this CVwR, on otherwise real data.

    No simulated dataset lands on CVwR = 30.000000%, and a boundary test that
    cannot reach its boundary proves nothing.
    """
    swr = swr_for(cv_percent)
    exact = ReferenceVariability(
        s2_wr=swr * swr,
        swr=swr,
        cv_wr_percent=cv_percent,
        degrees_of_freedom=58,
        n_observations=120,
        n_subjects=60,
    )
    monkeypatch.setattr(ema_hvd, "estimate_reference_variability", lambda _dataset: exact)


# -------------------------------------------------------- the pure rule ---


@pytest.mark.parametrize(
    ("endpoint", "cv", "justification", "prespecification", "expected"),
    [
        # Cmax, CVwR <= 30%: no widening, whatever the basis.
        (Endpoint.CMAX, 25.0, J, P, S.NOT_WIDENED_VARIABILITY),
        (Endpoint.CMAX, 25.0, JS, PS, S.NOT_WIDENED_VARIABILITY),
        (Endpoint.CMAX, 25.0, NJ, NP, S.NOT_WIDENED_VARIABILITY),
        # Cmax, CVwR > 30%: the basis decides.
        (Endpoint.CMAX, 45.0, J, P, S.WIDENED),
        (Endpoint.CMAX, 45.0, JS, P, S.UNDETERMINED_BASIS_NOT_STATED),
        (Endpoint.CMAX, 45.0, J, PS, S.UNDETERMINED_BASIS_NOT_STATED),
        (Endpoint.CMAX, 45.0, JS, PS, S.UNDETERMINED_BASIS_NOT_STATED),
        (Endpoint.CMAX, 45.0, NJ, P, S.NOT_WIDENED_BASIS_ABSENT),
        (Endpoint.CMAX, 45.0, J, NP, S.NOT_WIDENED_BASIS_ABSENT),
        (Endpoint.CMAX, 45.0, NJ, NP, S.NOT_WIDENED_BASIS_ABSENT),
        # An explicit "no" settles the range even when the other is unstated.
        (Endpoint.CMAX, 45.0, NJ, PS, S.NOT_WIDENED_BASIS_ABSENT),
        (Endpoint.CMAX, 45.0, JS, NP, S.NOT_WIDENED_BASIS_ABSENT),
        # AUC: never, at any variability, on any basis.
        (Endpoint.AUC, 45.0, J, P, S.NOT_WIDENED_ENDPOINT),
        (Endpoint.AUC, 500.0, J, P, S.NOT_WIDENED_ENDPOINT),
        (Endpoint.AUC, 45.0, JS, PS, S.NOT_WIDENED_ENDPOINT),
        # OTHER: no rule. CORRECTED - this was NOT_WIDENED_ENDPOINT, which
        # silently treated an unnamed endpoint as if it were AUC.
        (Endpoint.OTHER, 45.0, J, P, S.UNDETERMINED_ENDPOINT_NOT_COVERED),
        (Endpoint.OTHER, 20.0, J, P, S.UNDETERMINED_ENDPOINT_NOT_COVERED),
        (Endpoint.OTHER, None, JS, PS, S.UNDETERMINED_ENDPOINT_NOT_COVERED),
        # Variability not estimable.
        (Endpoint.CMAX, None, J, P, S.UNDETERMINED_VARIABILITY_NOT_ESTIMABLE),
        (Endpoint.AUC, None, J, P, S.NOT_WIDENED_ENDPOINT),
    ],
)
def test_the_widening_rule_matrix(endpoint, cv, justification, prespecification, expected):
    status, reason = ema_abel_widening(
        endpoint=endpoint,
        cv_wr_percent=cv,
        clinical_justification=justification,
        protocol_prespecification=prespecification,
    )
    assert status is expected, reason
    assert reason.strip()


@pytest.mark.parametrize(
    ("cv", "expected"),
    [
        (29.999999, S.NOT_WIDENED_VARIABILITY),
        (30.0, S.NOT_WIDENED_VARIABILITY),
        (30.000001, S.WIDENED),
    ],
)
def test_the_30_percent_boundary_is_strict(cv, expected):
    status, _ = ema_abel_widening(
        endpoint=Endpoint.CMAX,
        cv_wr_percent=cv,
        clinical_justification=J,
        protocol_prespecification=P,
    )
    assert status is expected
    assert ema_hvd_variability_eligible(cv_wr_percent=cv)[0] is (expected is S.WIDENED)


@pytest.mark.parametrize("bad", [True, False, "justified", "JUSTIFIED", None, 1])
def test_the_basis_must_be_typed_and_never_a_flag(bad):
    with pytest.raises(TypeError):
        ema_abel_widening(
            endpoint=Endpoint.CMAX,
            cv_wr_percent=45.0,
            clinical_justification=bad,
            protocol_prespecification=P,
        )
    with pytest.raises(TypeError):
        ema_abel_widening(
            endpoint=Endpoint.CMAX,
            cv_wr_percent=45.0,
            clinical_justification=J,
            protocol_prespecification=bad,
        )


def test_the_assess_entry_point_refuses_a_flag_before_reading_data():
    with pytest.raises(TypeError):
        assess_ema_endpoint(
            study(cv_wr_percent=45.0),
            endpoint=Endpoint.CMAX,
            clinical_justification=True,
            protocol_prespecification=P,
        )


def test_fdas_0294_has_no_place_in_ema_selection():
    """A CVwR above 30% whose sWR is below 0.294 widens under EMA.

    sWR 0.2938 is CVwR 30.05%: EMA widens it, and FDA's switch would not
    select reference scaling. If EMA's rule were ever rewritten on FDA's sWR
    threshold, this study would silently lose its widening.
    """
    swr = 0.2938
    cv = 100.0 * math.sqrt(math.expm1(swr * swr))
    assert cv > 30.0
    assert swr < FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    assert fda_hvd_method_for(swr) is Method.STANDARD_ABE
    status, _ = ema_abel_widening(
        endpoint=Endpoint.CMAX, cv_wr_percent=cv,
        clinical_justification=J, protocol_prespecification=P,
    )
    assert status is S.WIDENED

    for function in (ema_abel_widening, ema_hvd_variability_eligible):
        tree = ast.parse(inspect.getsource(function))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        constants = {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, float)
        }
        assert "FDA_HVD_CONSTANTS" not in names, function
        assert "fda_hvd_method_for" not in names, function
        assert 0.294 not in constants, function


def test_the_ema_module_holds_no_bare_regulatory_literal():
    """30, 0.760, 69.84, 143.19, 80 and 125 are read from EMA_HVD_CONSTANTS."""
    tree = ast.parse(inspect.getsource(ema_hvd))
    forbidden = (30.0, 0.760, 69.84, 143.19, 80.0, 125.0, 0.294)
    offenders = [
        f"{node.value} at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and any(abs(float(node.value) - f) < 1e-12 for f in forbidden)
    ]
    assert not offenders, offenders


# ------------------------------------------------ the regression matrix ---


def test_cmax_low_cv_justified_is_not_widened_and_is_decided():
    result = assess_ema_endpoint(study(cv_wr_percent=15.0), endpoint=Endpoint.CMAX, **BASIS)
    assert result.widening_status is S.NOT_WIDENED_VARIABILITY
    assert result.variability_eligible is False
    assert result.applied_limits == PE
    assert result.limits is None
    # CORRECTED from STANDARD_ABE: Method A ran; only the range is conventional.
    assert result.selected_method is Method.EMA_HVD_ABEL
    assert result.decided and result.passes is not None


def test_cmax_high_cv_justified_and_prespecified_is_widened():
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    assert result.widening_status is S.WIDENED
    assert result.variability_eligible is True
    assert result.selected_method is Method.EMA_HVD_ABEL
    assert result.applied_limits == result.final_scaled_limits
    assert result.applied_limits[0] < PE[0] and result.applied_limits[1] > PE[1]
    assert result.decided


@pytest.mark.parametrize(
    ("justification", "prespecification"), [(JS, P), (J, PS), (JS, PS)]
)
def test_cmax_high_cv_with_an_unstated_basis_issues_no_decision(justification, prespecification):
    result = assess_ema_endpoint(
        study(cv_wr_percent=45.0),
        endpoint=Endpoint.CMAX,
        clinical_justification=justification,
        protocol_prespecification=prespecification,
    )
    assert result.widening_status is S.UNDETERMINED_BASIS_NOT_STATED
    assert result.decided is False
    assert result.passes is None
    assert result.selected_method is None
    assert result.limits is None and result.applied_limits is None
    assert result.treatment_effect is None
    assert result.interval_criterion_passes is None
    assert result.point_estimate_criterion_passes is None
    # Descriptive variability is still reported.
    assert result.cv_wr_percent is not None and result.cv_wr_percent > 30.0
    fatal = [d for d in result.diagnostics if d.severity is Severity.FATAL]
    assert [d.code for d in fatal] == [DiagnosticCode.EMA_ABEL_WIDENING_BASIS_NOT_STATED]


def test_the_default_is_not_stated_and_never_widens():
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX)
    assert result.clinical_justification is JS
    assert result.protocol_prespecification is PS
    assert not result.decided


@pytest.mark.parametrize(("justification", "prespecification"), [(NJ, P), (J, NP), (NJ, NP)])
def test_cmax_high_cv_explicitly_not_justified_is_decided_at_the_conventional_range(
    justification, prespecification
):
    result = assess_ema_endpoint(
        study(cv_wr_percent=45.0),
        endpoint=Endpoint.CMAX,
        clinical_justification=justification,
        protocol_prespecification=prespecification,
    )
    assert result.widening_status is S.NOT_WIDENED_BASIS_ABSENT
    assert result.variability_eligible is True, "variable - and still not widened"
    assert result.limits is None
    assert result.applied_limits == PE
    # CORRECTED from STANDARD_ABE: Method A ran; only the range is conventional.
    assert result.selected_method is Method.EMA_HVD_ABEL
    assert result.decided
    assert any(
        d.code is DiagnosticCode.EMA_ABEL_WIDENING_NOT_PERMITTED
        and d.severity is Severity.ADVISORY
        for d in result.diagnostics
    )


@pytest.mark.parametrize("cv", [45.0, 120.0])
@pytest.mark.parametrize(("justification", "prespecification"), [(J, P), (JS, PS), (NJ, NP)])
def test_auc_is_never_widened(cv, justification, prespecification):
    result = assess_ema_endpoint(
        study(cv_wr_percent=cv, endpoint="AUC"),
        endpoint=Endpoint.AUC,
        clinical_justification=justification,
        protocol_prespecification=prespecification,
    )
    assert result.widening_status is S.NOT_WIDENED_ENDPOINT
    assert result.limits is None
    assert result.raw_scaled_limits is None and result.final_scaled_limits is None
    assert result.applied_limits == PE
    assert result.decided
    assert result.cv_wr_percent > 30.0
    assert "Expanded acceptance interval" not in result.summary()


def test_the_basis_is_never_inferred_from_a_study_that_would_pass():
    """A precise, well-located, highly variable Cmax still gets no decision unstated."""
    rows = study(cv_wr_percent=45.0, ratio=1.0, n_per_sequence=80)
    justified = assess_ema_endpoint(rows, endpoint=Endpoint.CMAX, **BASIS)
    assert justified.passes is True
    unstated = assess_ema_endpoint(rows, endpoint=Endpoint.CMAX)
    assert unstated.decided is False


def test_assess_study_passes_the_basis_to_every_endpoint_and_only_cmax_uses_it():
    results = assess_ema_study(
        {
            Endpoint.CMAX: study(cv_wr_percent=45.0),
            Endpoint.AUC: study(cv_wr_percent=45.0, endpoint="AUC", seed=11),
        },
        **BASIS,
    )
    assert results[Endpoint.CMAX].widening_status is S.WIDENED
    assert results[Endpoint.AUC].widening_status is S.NOT_WIDENED_ENDPOINT
    unstated = assess_ema_study(
        {
            Endpoint.CMAX: study(cv_wr_percent=45.0),
            Endpoint.AUC: study(cv_wr_percent=45.0, endpoint="AUC", seed=11),
        }
    )
    assert not unstated[Endpoint.CMAX].decided
    assert unstated[Endpoint.AUC].decided


# ------------------------------------------- the 30% boundary, end to end ---


@pytest.mark.parametrize(
    ("cv", "widened"), [(29.999999, False), (30.0, False), (30.000001, True)]
)
def test_the_boundary_through_the_whole_assessment(monkeypatch, cv, widened):
    with_exact_cv(monkeypatch, cv)
    result = assess_ema_endpoint(study(cv_wr_percent=30.0), endpoint=Endpoint.CMAX, **BASIS)
    assert result.cv_wr_percent == cv
    assert result.decided
    if widened:
        assert result.widening_status is S.WIDENED
        swr = swr_for(cv)
        assert result.applied_limits == (
            100.0 * math.exp(-K * swr),
            100.0 * math.exp(K * swr),
        )
        # WORTH KNOWING, AND NOT A DEFECT: at CVwR just above 30% the formula
        # gives 80.0030-124.9953%, marginally NARROWER than the conventional
        # range. 4.1.10's table prints that row as 80.00-125.00. The engine
        # applies the formula as stated, and says so rather than clamping.
        assert result.applied_limits[0] == pytest.approx(PE[0], abs=0.005)
        assert result.applied_limits[1] == pytest.approx(PE[1], abs=0.005)
    else:
        assert result.widening_status is S.NOT_WIDENED_VARIABILITY
        assert result.applied_limits == PE


# ---------------------------------------------------- limits and the cap ---


def test_the_limits_are_in_percent_and_converted_once():
    swr = swr_for(40.0)
    limits = ema_abel_limits(swr)
    assert limits.final_lower_percent == pytest.approx(100.0 * math.exp(-K * swr), rel=1e-15)
    assert limits.final_upper_percent == pytest.approx(100.0 * math.exp(K * swr), rel=1e-15)
    assert 50.0 < limits.final_lower_percent < 100.0 < limits.final_upper_percent < 200.0


@pytest.mark.parametrize("cv", [30.5, 35.0, 42.0, 49.0])
def test_moderate_variability_is_uncapped(cv):
    limits = ema_abel_limits(swr_for(cv))
    assert limits.cap_applied is False
    assert CAP_LOWER < limits.final_lower_percent < PE[0]


# CORRECTED. A test here used to PIN a band - CVwR 49.9928% to 49.9989% - where
# only the lower limit was capped, produced by clipping each limit against the
# rounded published pair. EMA's table states no such band. The cap is one rule
# keyed on CVwR, and the tests below hold it to that.


@pytest.mark.parametrize("cv", [49.99, 49.995, 49.9999, 49.99999999])
def test_below_cvwr_50_the_formula_applies_to_both_limits(cv):
    swr = swr_for(cv)
    limits = ema_abel_limits(swr, cv_wr_percent=cv)
    assert limits.cap_applied is False
    assert limits.final_lower_percent == limits.raw_lower_percent == 100.0 * math.exp(-K * swr)
    assert limits.final_upper_percent == limits.raw_upper_percent == 100.0 * math.exp(K * swr)


def test_just_below_50_the_formula_lies_beyond_the_published_pair_and_is_applied():
    """Stated rather than hidden: the table switches at 50, not before."""
    limits = ema_abel_limits(swr_for(49.999), cv_wr_percent=49.999)
    assert limits.cap_applied is False
    assert limits.final_lower_percent < CAP_LOWER
    assert limits.final_upper_percent > CAP_UPPER
    assert CAP_LOWER - limits.final_lower_percent < 0.0033
    assert limits.final_upper_percent - CAP_UPPER < 0.0011


@pytest.mark.parametrize("cv", [50.0, 50.00000001, 50.0001, 60.0, 90.0, 300.0])
def test_at_and_above_cvwr_50_the_limits_are_exactly_the_published_pair(cv):
    limits = ema_abel_limits(swr_for(cv), cv_wr_percent=cv)
    assert limits.cap_applied is True
    assert (limits.final_lower_percent, limits.final_upper_percent) == (CAP_LOWER, CAP_UPPER)


def test_both_limits_change_branch_together_at_one_cvwr():
    for step in range(-80, 81):
        cv = 50.0 + step * 0.00025
        limits = ema_abel_limits(swr_for(cv), cv_wr_percent=cv)
        formula = (limits.raw_lower_percent, limits.raw_upper_percent)
        pair = (CAP_LOWER, CAP_UPPER)
        final = (limits.final_lower_percent, limits.final_upper_percent)
        if cv >= 50.0:
            assert limits.cap_applied and final == pair, cv
        else:
            assert not limits.cap_applied and final == formula, cv


def test_the_cap_decision_uses_the_supplied_cvwr():
    limits = ema_abel_limits(swr_for(50.0), cv_wr_percent=50.0)
    assert limits.cv_wr_percent == 50.0
    assert limits.cap_applied is True


@pytest.mark.parametrize(("cv", "capped"), [(49.99, False), (50.0, True), (60.0, True)])
def test_the_cap_rule_through_the_whole_assessment(monkeypatch, cv, capped):
    with_exact_cv(monkeypatch, cv)
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    assert result.widening_status is S.WIDENED
    assert result.cap_applied is capped
    if capped:
        assert result.applied_limits == (CAP_LOWER, CAP_UPPER)
    else:
        assert result.applied_limits == result.raw_scaled_limits


# ------------------------------------------------- the criteria at the edge ---


def _effect(*, gmr: float, lower: float, upper: float):
    return ema_hvd.TreatmentEffect(
        estimate=math.log(gmr / 100.0),
        standard_error=0.01,
        degrees_of_freedom=40,
        ci_lower=math.log(lower / 100.0),
        ci_upper=math.log(upper / 100.0),
        alpha=0.05,
        n_observations=100,
        n_subjects=25,
    )


def test_a_ci_touching_the_widened_limits_is_contained_and_just_outside_is_not():
    limits = ema_abel_limits(swr_for(40.0))
    lo, hi = limits.final_lower_percent, limits.final_upper_percent
    touching, _, _ = _both_criteria(effect=_effect(gmr=100.0, lower=lo, upper=hi), lower_percent=lo, upper_percent=hi, widened=True)
    assert touching is True
    low_out, _, _ = _both_criteria(effect=_effect(gmr=100.0, lower=lo * (1 - 1e-9), upper=hi), lower_percent=lo, upper_percent=hi, widened=True)
    high_out, _, _ = _both_criteria(effect=_effect(gmr=100.0, lower=lo, upper=hi * (1 + 1e-9)), lower_percent=lo, upper_percent=hi, widened=True)
    assert low_out is False and high_out is False


@pytest.mark.parametrize(
    ("gmr", "ok"), [(80.0, True), (125.0, True), (79.9999, False), (125.0001, False)]
)
def test_the_gmr_constraint_is_inclusive_and_does_not_widen(gmr, ok):
    """Even against the capped limits, the GMR range stays 80.00-125.00%."""
    _, pe_ok, _ = _both_criteria(
        effect=_effect(gmr=gmr, lower=72.0, upper=138.0),
        lower_percent=CAP_LOWER,
        upper_percent=CAP_UPPER,
        widened=True,
    )
    assert pe_ok is ok


def test_the_gmr_is_exposed_separately_from_the_interval_criterion():
    result = assess_ema_endpoint(
        study(cv_wr_percent=45.0, ratio=0.78), endpoint=Endpoint.CMAX, **BASIS
    )
    assert result.point_estimate_limits == PE
    assert result.geometric_mean_ratio < PE[0]
    assert result.point_estimate_criterion_passes is False
    assert result.passes is False
    assert result.interval_criterion_passes is not None


# ------------------------------------------------------------- designs ---


@pytest.mark.parametrize("labels", [("TRTR", "RTRT"), ("TRR", "RTR", "RRT")])
def test_both_accepted_replicate_designs_are_identifiable_and_decide(labels):
    result = assess_ema_endpoint(
        study(cv_wr_percent=40.0, labels=labels, n_per_sequence=16), endpoint=Endpoint.CMAX, **BASIS
    )
    assert result.reference_variability.degrees_of_freedom > 0
    assert result.treatment_effect.degrees_of_freedom > 0
    assert result.decided


def test_a_mixed_or_unrecognised_design_raises_rather_than_approximating():
    rows = study(cv_wr_percent=40.0, labels=("TRR",), n_per_sequence=4) + study(
        cv_wr_percent=40.0, labels=("TRTR",), n_per_sequence=4, seed=9
    )
    with pytest.raises(UnsupportedDesign):
        assess_ema_endpoint(rows, endpoint=Endpoint.CMAX, **BASIS)
    with pytest.raises(DataError):
        parse_sequence("TR")


def test_an_unestimable_reference_variability_leaves_cmax_undetermined_and_auc_decided():
    """Two subjects on a fully replicate design: 4 reference rows, 5 parameters."""
    cmax = assess_ema_endpoint(
        study(cv_wr_percent=40.0, n_per_sequence=1), endpoint=Endpoint.CMAX, **BASIS
    )
    assert cmax.reference_variability is None
    assert cmax.widening_status is S.UNDETERMINED_VARIABILITY_NOT_ESTIMABLE
    assert not cmax.decided and cmax.passes is None
    assert any(
        d.code is DiagnosticCode.EMA_ABEL_QUANTITY_NOT_ESTIMABLE and d.severity is Severity.FATAL
        for d in cmax.diagnostics
    )

    auc = assess_ema_endpoint(
        study(cv_wr_percent=40.0, n_per_sequence=1, endpoint="AUC"), endpoint=Endpoint.AUC, **BASIS
    )
    assert auc.reference_variability is None
    assert auc.widening_status is S.NOT_WIDENED_ENDPOINT
    assert auc.decided


def test_the_design_gate_is_consulted_and_refuses_an_unsupported_classification(monkeypatch):
    """Both designs `identify_design` returns are supported today, so the gate is
    only observable by withdrawing support. If the check were removed, a design
    EMA's table called NOT_IMPLEMENTED would still be analysed."""
    monkeypatch.setitem(
        ema_hvd.EMA_DESIGN_SUPPORT,
        "fully_replicate",
        (ema_hvd.EmaDesignSupport.NOT_IMPLEMENTED, "withdrawn for this test"),
    )
    with pytest.raises(DataError, match="EMA design support"):
        assess_ema_endpoint(study(cv_wr_percent=40.0), endpoint=Endpoint.CMAX, **BASIS)


def test_the_endpoint_decision_fits_method_a_and_nothing_from_fda():
    """Structural. The model identity is regulator-specific.

    The decision must reach its contrast through `estimate_treatment_effect`,
    and the module may import none of FDA's replicate models: not Appendix C's
    mixed model, not Appendix G's within-subject contrast.
    """
    tree = ast.parse(inspect.getsource(ema_hvd))
    imported = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for forbidden in ("be_stats.appendix_c", "be_stats.replicate_abe", "be_stats.treatment_contrast",
                      "be_stats.hvd", "be_stats.nti", "be_stats.abe", "appendix_c", "replicate_abe",
                      "treatment_contrast"):
        assert forbidden not in imported, forbidden

    assess = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "assess_ema_endpoint"
    )
    called = {
        n.func.id for n in ast.walk(assess) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "estimate_treatment_effect" in called
    assert "estimate_reference_variability" in called


def test_a_mislabelled_endpoint_is_refused():
    with pytest.raises(DataError, match="mislabelled"):
        assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="AUC"), endpoint=Endpoint.CMAX, **BASIS)


# ----------------------------------------------------- unconstructible states ---


@pytest.fixture
def widened():
    return assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)


@pytest.fixture
def conventional():
    return assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="AUC"), endpoint=Endpoint.AUC, **BASIS)


def test_an_auc_result_cannot_carry_widened_limits_or_a_widened_status(widened, conventional):
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(conventional, widening_status=S.WIDENED)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(conventional, limits=widened.limits)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, endpoint=Endpoint.AUC)


def test_widening_cannot_be_asserted_when_the_basis_is_absent(widened):
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, clinical_justification=NJ)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, protocol_prespecification=PS)


def test_widening_cannot_be_asserted_for_ineligible_variability(widened):
    low = ReferenceVariability(
        s2_wr=swr_for(20.0) ** 2, swr=swr_for(20.0), cv_wr_percent=20.0,
        degrees_of_freedom=58, n_observations=120, n_subjects=60,
    )
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, reference_variability=low)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, variability_eligible=False)


def test_a_decision_needs_method_a_and_consistent_criteria(widened):
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, treatment_effect=None)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, passes=not widened.passes)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, point_estimate_criterion_passes=not widened.point_estimate_criterion_passes)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(widened, applied_limits=PE)


def test_an_unstated_basis_cannot_be_decided_or_carry_an_analysis():
    refused = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX)
    decided = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(refused, decided=True, passes=True)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(refused, applied_limits=decided.applied_limits)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(refused, treatment_effect=decided.treatment_effect)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(refused, passes=False)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(refused, diagnostics=())


def test_a_complete_conventional_decision_cannot_be_relabelled_undetermined():
    """The hardest forgery: every analysis field present and self-consistent.

    Take a real decision against 80.00-125.00% for a product explicitly not
    justified, and relabel the basis as unstated. The criteria still follow
    from the interval; only the claim that a range was applicable is false.
    """
    decided = assess_ema_endpoint(
        study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX,
        clinical_justification=NJ, protocol_prespecification=P,
    )
    refused = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(
            decided,
            clinical_justification=JS,
            protocol_prespecification=PS,
            widening_status=S.UNDETERMINED_BASIS_NOT_STATED,
            diagnostics=refused.diagnostics,
        )


def test_selected_method_is_derived_not_stored():
    names = {f.name for f in dataclasses.fields(ema_hvd.EmaHighlyVariableResult)}
    assert "selected_method" not in names
    assert "scaling_eligible" not in names
    assert "raw_scaled_limits" not in names


# ------------------------------------------------------------ explainability ---


def test_an_eligible_result_reads_top_to_bottom(widened):
    lines = widened.summary().splitlines()
    expected_prefixes = [
        "Regulator: EMA.",
        "Endpoint: Cmax.",
        "Replicate design: fully_replicate - acceptable",
        "Reference CVwR = ",
        "Clinical justification for widening: established.",
        "Widened interval prospectively specified in the protocol: yes.",
        "k = 0.760.",
        "Expanded acceptance interval = [",
        "Method A 90% CI = [",
        "GMR = ",
        "Final decision: ",
    ]
    assert len(lines) >= len(expected_prefixes)
    for line, prefix in zip(lines, expected_prefixes, strict=False):
        assert line.startswith(prefix), (prefix, line)
    assert "requires >30%" in lines[3]
    assert "capped at 69.84-143.19%" in lines[7]
    assert "required inside 80.00-125.00%" in lines[9]
    assert lines[10].startswith(f"Final decision: {'PASS' if widened.passes else 'FAIL'}")
    assert "compared unrounded with the widened limits" in lines[10]
    assert "VAL-EMA-ABEL-003" in lines[10]


def test_a_conventional_result_says_its_bounds_were_rounded():
    result = assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="AUC"), endpoint=Endpoint.AUC, **BASIS)
    (final,) = [line for line in result.summary().splitlines() if line.startswith("Final decision: ")]
    assert "rounded to two decimal places before comparison, as 4.1.8 states" in final


def test_a_refused_result_leads_with_no_decision_and_prints_no_limits():
    refused = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX)
    text = refused.summary()
    assert text.splitlines()[0] == "NO ABEL DECISION ISSUED"
    assert "Clinical justification for widening: NOT STATED." in text
    assert "Expanded acceptance interval" not in text
    assert "Method A 90% CI" not in text
    assert "Acceptance range UNDETERMINED" in text
    assert "Final decision: NONE" in text


def test_a_not_justified_result_says_the_range_was_not_widened():
    result = assess_ema_endpoint(
        study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX,
        clinical_justification=NJ, protocol_prespecification=P,
    )
    text = result.summary()
    assert "Clinical justification for widening: explicitly NOT established." in text
    assert "Acceptance interval = [80.00%, 125.00%], NOT widened" in text
    assert "Expanded acceptance interval" not in text


# ------------------------------------------------------------- routing ---


def test_every_hvd_and_nti_route_goes_to_its_own_regulators_method():
    cases = {
        (Jurisdiction.FDA, DrugClass.HIGHLY_VARIABLE, Endpoint.CMAX): Method.FDA_HVD_RSABE,
        (Jurisdiction.EMA, DrugClass.HIGHLY_VARIABLE, Endpoint.CMAX): Method.EMA_HVD_ABEL,
        (Jurisdiction.FDA, DrugClass.NARROW_THERAPEUTIC_INDEX, Endpoint.AUC): Method.FDA_NTI_RSABE,
        (Jurisdiction.EMA, DrugClass.NARROW_THERAPEUTIC_INDEX, Endpoint.AUC): Method.EMA_NTI_NARROW_ABE,
    }
    for (jurisdiction, drug_class, endpoint), method in cases.items():
        spec = resolve_be_spec(jurisdiction=jurisdiction, drug_class=drug_class, endpoint=endpoint)
        assert spec.method is method
    ema = resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=Endpoint.CMAX)
    assert ema.constants is EMA_HVD_CONSTANTS
    assert "clinical justification" in ema.notes
    assert "prospectively specified" in ema.notes


def test_the_ema_engine_accepts_only_the_ema_hvd_spec_for_the_same_endpoint():
    rows = study(cv_wr_percent=45.0)
    good = resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=Endpoint.CMAX)
    assert assess_ema_endpoint(rows, endpoint=Endpoint.CMAX, spec=good, **BASIS).decided

    for other in (
        resolve_be_spec(jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=Endpoint.CMAX),
        resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.STANDARD, endpoint=Endpoint.CMAX),
        resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=Endpoint.AUC),
    ):
        with pytest.raises(NotApplicable):
            assess_ema_endpoint(rows, endpoint=Endpoint.CMAX, spec=other, **BASIS)


# ------------------------------------------------ refusal vocabulary and gate ---


def test_the_refusal_code_corresponds_to_the_fatal_diagnostic():
    assert (
        DIAGNOSTIC_FOR[RefusalCode.EMA_ABEL_WIDENING_BASIS_REQUIRED]
        is DiagnosticCode.EMA_ABEL_WIDENING_BASIS_NOT_STATED
    )
    for capability_id in ("EMA_HVD_ABEL", "EMA_HVD_ENDPOINT_DECISION", "EMA_ABEL_WIDENING_BASIS_GATE"):
        assert RefusalCode.EMA_ABEL_WIDENING_BASIS_REQUIRED in CAPABILITY_MATRIX[capability_id].refusal_conditions


# -------------------------------------------------------------- governance ---


EMA_HVD_CAPABILITIES = (
    "EMA_HVD_ABEL",
    "EMA_HVD_DESIGN_GATE",
    "EMA_HVD_VARIABILITY_ELIGIBILITY",
    "EMA_HVD_REFERENCE_VARIABILITY",
    "EMA_REPLICATE_METHOD_A",
    "EMA_ABEL_LIMIT_CALCULATION",
    "EMA_ABEL_PE_CONSTRAINT",
    "EMA_HVD_ENDPOINT_DECISION",
    "EMA_ABEL_WIDENING_BASIS_GATE",
)


def test_no_status_moved():
    assert VALIDATION[Method.EMA_HVD_ABEL] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    expected = {
        Capability.EMA_HVD_DESIGN_GATE: ValidationStatus.IMPLEMENTED,
        Capability.EMA_HVD_VARIABILITY_ELIGIBILITY: ValidationStatus.IMPLEMENTED,
        Capability.EMA_HVD_REFERENCE_VARIABILITY: ValidationStatus.VALIDATED,
        Capability.EMA_REPLICATE_METHOD_A: ValidationStatus.VALIDATED,
        Capability.EMA_ABEL_LIMIT_CALCULATION: ValidationStatus.VALIDATED,
        Capability.EMA_ABEL_PE_CONSTRAINT: ValidationStatus.IMPLEMENTED_UNVALIDATED,
        Capability.EMA_HVD_ENDPOINT_DECISION: ValidationStatus.IMPLEMENTED_UNVALIDATED,
        Capability.EMA_ABEL_WIDENING_BASIS_GATE: ValidationStatus.IMPLEMENTED,
    }
    for capability, status in expected.items():
        assert CAPABILITY_VALIDATION[capability] is status, capability
        assert CAPABILITY_MATRIX[capability.name].validation_status is status
    assert CAPABILITY_MATRIX["EMA_HVD_ABEL"].validation_status is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert REVIEWED_TRANSITIONS == frozenset(
        {"EMA_HVD_REFERENCE_VARIABILITY", "EMA_REPLICATE_METHOD_A", "EMA_ABEL_LIMIT_CALCULATION"}
    )
    assert CAPABILITY_VALIDATION[Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL] is ValidationStatus.NOT_IMPLEMENTED


def test_the_three_validated_components_still_hold_qualifying_ema_evidence():
    for capability_id in ("EMA_HVD_REFERENCE_VARIABILITY", "EMA_REPLICATE_METHOD_A", "EMA_ABEL_LIMIT_CALCULATION"):
        assessments = assess_tier_1b(capability_id)
        assert assessments and all(a.relation is Tier1BRelation.QUALIFYING for a in assessments)
        assert check_capability(capability_id, reviewed_transitions=REVIEWED_TRANSITIONS).passed


def test_validated_components_do_not_validate_the_method(monkeypatch):
    """Claim VALIDATED for the method with a reviewed transition: the gate refuses."""
    patched = dict(VALIDATION)
    patched[Method.EMA_HVD_ABEL] = ValidationStatus.VALIDATED
    monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)

    result = check_capability("EMA_HVD_ABEL", reviewed_transitions=frozenset({"EMA_HVD_ABEL"}))

    assert not result.passed
    assert any("without tier-1B evidence" in v for v in result.violations)
    assert not [r for r in evidence_for("EMA_HVD_ABEL") if r.tier is EvidenceTier.TIER_1B]


def test_cross_authority_tier_1b_cannot_qualify_the_ema_method(monkeypatch):
    patched = dict(VALIDATION)
    patched[Method.EMA_HVD_ABEL] = ValidationStatus.VALIDATED
    monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)

    def record(authority):
        return EvidenceRecord(
            evidence_id=f"TEST-SYNTHETIC-{authority}",
            capabilities=("EMA_HVD_ABEL",),
            tier=EvidenceTier.TIER_1B,
            source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
            source_authority="test fixture",
            evidence_authority=authority,
            scenario="-", dataset="-", software_environment="-",
            expected="-", observed="-", tolerance="-",
            status=EvidenceStatus.PASSED,
            established_by="tests/unit/test_ema_abel_applicability.py",
        )

    monkeypatch.setattr(
        "be_stats.dossier.evidence.EVIDENCE_MANIFEST", (*EVIDENCE_MANIFEST, record(Authority.FDA))
    )
    result = check_capability("EMA_HVD_ABEL", reviewed_transitions=frozenset({"EMA_HVD_ABEL"}))
    assert not result.passed
    assert any("none is from the governing authority EMA" in v for v in result.violations)

    monkeypatch.setattr(
        "be_stats.dossier.evidence.EVIDENCE_MANIFEST", (*EVIDENCE_MANIFEST, record(Authority.EMA))
    )
    control = check_capability("EMA_HVD_ABEL", reviewed_transitions=frozenset({"EMA_HVD_ABEL"}))
    assert not any("tier-1B" in v for v in control.violations), control.violations


def test_no_capability_is_labelled_tier_1b_without_a_tier_1b_record():
    """The label is a claim about the row. EMA_HVD_ABEL carried TIER_1B with none.

    A row may hold tier-1B evidence that does not QUALIFY it - FDA's Appendix C
    rows hold EMA's - and the label then describes that evidence honestly. What
    it may not do is describe evidence the row does not hold at all.
    """
    for capability_id, record in CAPABILITY_MATRIX.items():
        if record.evidence_tier is EvidenceTier.TIER_1B:
            held = [r for r in evidence_for(capability_id) if r.tier is EvidenceTier.TIER_1B]
            assert held, f"{capability_id} is labelled TIER_1B and holds no tier-1B record"
    assert CAPABILITY_MATRIX["EMA_HVD_ABEL"].evidence_tier is EvidenceTier.TIER_1A


def test_the_method_holds_no_tier_1b_and_powertost_stays_tier_3():
    records = evidence_for("EMA_HVD_ABEL")
    assert not [r for r in records if r.tier is EvidenceTier.TIER_1B]
    (powertost,) = [r for r in records if r.evidence_id == "POWERTOST-CROSS-CHECK"]
    assert powertost.tier is EvidenceTier.TIER_3
    assert powertost.evidence_authority is None


def test_every_ema_hvd_capability_is_governed_by_ema():
    for capability_id in EMA_HVD_CAPABILITIES:
        record = CAPABILITY_MATRIX[capability_id]
        assert record.governing_authority is Authority.EMA, capability_id
        assert record.validation_status is not None


def test_the_widening_basis_evidence_record_is_tier_1a_and_emas():
    (record,) = [r for r in EVIDENCE_MANIFEST if r.evidence_id == "EMA-ABEL-WIDENING-BASIS-001"]
    assert record.tier is EvidenceTier.TIER_1A
    assert record.evidence_authority is Authority.EMA
    assert record.established_by == "tests/unit/test_ema_abel_applicability.py"


# ------------------------------------------------ the end-to-end tier-1B search ---


def test_the_end_to_end_search_is_recorded_and_adopts_nothing():
    assert EMA_HVD_ABEL_END_TO_END_SEARCH, "an empty search passes vacuously"
    assert not adopted_sources(search=EMA_HVD_ABEL_END_TO_END_SEARCH)
    for source in EMA_HVD_ABEL_END_TO_END_SEARCH:
        assert source.authority == "EMA"
        assert source.document_version.strip() and source.sections_read.strip()
        assert source.url.startswith("https://www.ema.europa.eu/")
        if source.verdict is SearchVerdict.NUMBERS_OUT_OF_SCOPE:
            assert source.rejected_because.strip()
    documents = " ".join(s.document for s in EMA_HVD_ABEL_END_TO_END_SEARCH)
    assert "CPMP/EWP/QWP/1401/98 Rev. 1" in documents
    assert "EMA/618604/2008" in documents


def test_the_qa_data_sets_are_not_stitched_into_an_end_to_end_case():
    (qa,) = [s for s in EMA_HVD_ABEL_END_TO_END_SEARCH if "618604" in s.document]
    assert qa.verdict is SearchVerdict.NUMBERS_OUT_OF_SCOPE
    assert "Stitching" in qa.rejected_because


# --------------------------------------------------------- FDA is untouched ---


def test_fda_hvd_and_nti_rules_are_unchanged():
    assert FDA_HVD_CONSTANTS["swr_switching_threshold"].value == 0.294
    assert fda_hvd_method_for(0.294) is Method.FDA_HVD_RSABE
    assert fda_hvd_method_for(0.293999) is Method.STANDARD_ABE
    assert VALIDATION[Method.FDA_HVD_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert not hasattr(spec_module, "SCALED_BE_CONSTANTS")


# ------------------------------------------------- 4.1.8's two-decimal rule ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (79.994, "79.99"),
        (79.996, "80.00"),
        (80.0, "80.00"),
        (125.004, "125.00"),
        (125.006, "125.01"),
        (125.0, "125.00"),
    ],
)
def test_round_half_up_away_from_any_tie(value, expected):
    assert round_half_up(value) == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(79.995, "80.00"), (125.005, "125.01"), (0.125, "0.13"), (2.675, "2.68")],
)
def test_the_documented_tie_policy_is_half_up_and_not_binary_round(value, expected):
    """EMA states no tie convention; this is the documented one, tested as policy.

    Every value here is one Python's binary `round` gets the other way:
    `round(2.675, 2)` is 2.67 because 2.675 is stored as 2.67499999...
    """
    assert round_half_up(value) == Decimal(expected)
    assert "ROUND_HALF_UP" in TIE_POLICY


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_rounding_refuses_a_non_finite_value(bad):
    with pytest.raises(ValueError):
        round_half_up(bad)


def test_the_rounding_helper_never_uses_binary_round_or_formatting():
    from be_stats import regulatory_rounding

    tree = ast.parse(inspect.getsource(regulatory_rounding))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "round" not in names
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)] or all(
        "cannot round" in ast.unparse(n) or "places must" in ast.unparse(n)
        for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)
    )


def _patch_effect(monkeypatch, *, lower: float, upper: float, gmr: float = 100.0):
    effect = _effect(gmr=gmr, lower=lower, upper=upper)
    monkeypatch.setattr(ema_hvd, "estimate_treatment_effect", lambda _dataset: effect)
    return effect


#: Every branch that issues a decision against 80.00-125.00%.
CONVENTIONAL_BRANCHES = {
    "AUC": {
        "rows": {"cv_wr_percent": 45.0, "endpoint": "AUC"},
        "endpoint": Endpoint.AUC,
        "basis": BASIS,
    },
    "Cmax, CVwR <= 30%": {
        "rows": {"cv_wr_percent": 15.0},
        "endpoint": Endpoint.CMAX,
        "basis": BASIS,
    },
    "Cmax, not justified": {
        "rows": {"cv_wr_percent": 45.0},
        "endpoint": Endpoint.CMAX,
        "basis": {"clinical_justification": NJ, "protocol_prespecification": P},
    },
    "Cmax, not prespecified": {
        "rows": {"cv_wr_percent": 45.0},
        "endpoint": Endpoint.CMAX,
        "basis": {"clinical_justification": J, "protocol_prespecification": NP},
    },
}


@pytest.mark.parametrize("branch", sorted(CONVENTIONAL_BRANCHES))
@pytest.mark.parametrize(
    ("lower", "upper", "passes"),
    [
        (79.994, 110.0, False),   # 79.99
        (79.996, 110.0, True),    # 80.00
        (80.0, 110.0, True),
        (90.0, 125.004, True),    # 125.00
        (90.0, 125.006, False),   # 125.01
        (90.0, 125.0, True),
        (80.0, 125.0, True),      # both clean boundaries
    ],
)
def test_every_conventional_branch_rounds_the_ci_as_4_1_8_states(monkeypatch, branch, lower, upper, passes):
    config = CONVENTIONAL_BRANCHES[branch]
    _patch_effect(monkeypatch, lower=lower, upper=upper)
    result = assess_ema_endpoint(study(**config["rows"]), endpoint=config["endpoint"], **config["basis"])
    assert result.widening_status.determined and not result.widening_status.widened
    assert result.applied_limits == PE
    assert result.decided
    assert result.interval_criterion_passes is passes
    assert result.passes is passes


def test_against_widened_limits_the_ci_is_compared_unrounded(monkeypatch):
    """69.836 rounds to 69.84, the published lower limit. Unrounded, it is outside."""
    with_exact_cv(monkeypatch, 60.0)
    _patch_effect(monkeypatch, lower=69.836, upper=120.0)
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    assert result.widening_status is S.WIDENED
    assert result.applied_limits == (CAP_LOWER, CAP_UPPER)
    assert round_half_up(result.confidence_interval[0]) == Decimal("69.84")
    assert result.interval_criterion_passes is False
    assert result.passes is False


def test_the_criteria_function_demands_an_explicit_rule():
    with pytest.raises(TypeError):
        _both_criteria(effect=_effect(gmr=100.0, lower=90.0, upper=110.0), lower_percent=80.0, upper_percent=125.0)


def test_one_function_compares_the_ci_with_limits_and_both_paths_use_it():
    """No second comparison anywhere, so the pipeline and the invariant agree."""
    tree = ast.parse(inspect.getsource(ema_hvd))
    compares = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(n, ast.Attribute) and n.attr in {"ci_lower_percent", "ci_upper_percent"}
            for n in ast.walk(node)
        )
    ]
    containing = next(
        f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "_interval_contained"
    )
    inside = {id(n) for n in ast.walk(containing)}
    assert compares and all(id(node) in inside for node in compares)

    def calls_in(name):
        function = next(
            f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == name
        )
        return {
            n.func.id for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }

    assert "_both_criteria" in calls_in("assess_ema_endpoint")
    assert "_both_criteria" in calls_in("__post_init__")


def test_a_conventional_verdict_must_follow_the_rounded_comparison(monkeypatch):
    effect_fail = _effect(gmr=100.0, lower=79.994, upper=110.0)
    _patch_effect(monkeypatch, lower=79.996, upper=110.0)
    passing = assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="AUC"), endpoint=Endpoint.AUC, **BASIS)
    assert passing.passes is True

    # A decided result whose rounded CI actually fails.
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(passing, treatment_effect=effect_fail)
    # A failed result whose rounded CI actually passes.
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(passing, interval_criterion_passes=False, passes=False)


def _consistent_replace(result, limits):
    applied = (limits.final_lower_percent, limits.final_upper_percent)
    interval_ok, pe_ok, both = _both_criteria(
        effect=result.treatment_effect, lower_percent=applied[0], upper_percent=applied[1], widened=True
    )
    return dataclasses.replace(
        result, limits=limits, applied_limits=applied,
        interval_criterion_passes=interval_ok, point_estimate_criterion_passes=pe_ok, passes=both,
    )


def test_a_pre_50_result_cannot_carry_the_published_pair(monkeypatch):
    with_exact_cv(monkeypatch, 45.0)
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    forged = dataclasses.replace(
        result.limits, cap_applied=True, final_lower_percent=CAP_LOWER, final_upper_percent=CAP_UPPER
    )
    with pytest.raises(EmaResultInconsistent):
        _consistent_replace(result, forged)


def test_a_50_plus_result_cannot_carry_formula_limits(monkeypatch):
    with_exact_cv(monkeypatch, 60.0)
    result = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX, **BASIS)
    forged = dataclasses.replace(
        result.limits,
        cap_applied=False,
        final_lower_percent=result.limits.raw_lower_percent,
        final_upper_percent=result.limits.raw_upper_percent,
    )
    with pytest.raises(EmaResultInconsistent):
        _consistent_replace(result, forged)


# ------------------------------------------------------------ Endpoint.OTHER ---


@pytest.mark.parametrize("cv", [15.0, 45.0])
@pytest.mark.parametrize(("justification", "prespecification"), [(J, P), (JS, PS), (NJ, NP)])
def test_endpoint_other_gets_no_decision_and_is_not_treated_as_auc(cv, justification, prespecification):
    result = assess_ema_endpoint(
        study(cv_wr_percent=cv, endpoint="other"),
        endpoint=Endpoint.OTHER,
        clinical_justification=justification,
        protocol_prespecification=prespecification,
    )
    assert result.widening_status is S.UNDETERMINED_ENDPOINT_NOT_COVERED
    assert result.decided is False and result.passes is None
    assert result.applied_limits is None and result.limits is None
    assert result.selected_method is None
    assert any(
        d.code is DiagnosticCode.EMA_HVD_ENDPOINT_NOT_COVERED and d.severity is Severity.FATAL
        for d in result.diagnostics
    )
    text = result.summary()
    assert text.splitlines()[0] == "NO ABEL DECISION ISSUED"
    assert "80.00%, 125.00%" not in text


def test_an_auc_verdict_cannot_be_relabelled_as_endpoint_other(conventional):
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(conventional, endpoint=Endpoint.OTHER)


def test_the_endpoint_refusal_is_in_the_refusal_vocabulary():
    assert (
        DIAGNOSTIC_FOR[RefusalCode.EMA_HVD_ENDPOINT_RULE_REQUIRED]
        is DiagnosticCode.EMA_HVD_ENDPOINT_NOT_COVERED
    )
    for capability_id in ("EMA_HVD_ABEL", "EMA_HVD_ENDPOINT_DECISION"):
        assert RefusalCode.EMA_HVD_ENDPOINT_RULE_REQUIRED in CAPABILITY_MATRIX[capability_id].refusal_conditions


# ---------------------------------------------- product class and routing ---


def test_no_nti_or_other_route_can_reach_the_abel_engine():
    rows_auc = study(cv_wr_percent=45.0, endpoint="AUC")
    for spec in (
        resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX, endpoint=Endpoint.AUC),
        resolve_be_spec(jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX, endpoint=Endpoint.AUC),
        resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.STANDARD, endpoint=Endpoint.AUC),
    ):
        with pytest.raises(NotApplicable):
            assess_ema_endpoint(rows_auc, endpoint=Endpoint.AUC, spec=spec, **BASIS)
    with pytest.raises(SpecificationRequired):
        resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX, endpoint=Endpoint.CMAX)


def test_nothing_in_the_package_routes_to_the_abel_engine_automatically():
    """The engine is caller-selected. No module but its own calls it."""
    package = Path(ema_hvd.__file__).parent
    offenders = []
    for path in package.rglob("*.py"):
        if path.name in {"ema_hvd.py", "__init__.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "id", None) or getattr(node, "attr", None)
            if name in {"assess_ema_endpoint", "assess_ema_study"}:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
    assert "CALLER-SELECTED, NOT ROUTED" in (assess_ema_endpoint.__doc__ or "")


# ------------------------------------------------------- method identity ---
#
# The acceptance range and the method are different facts. Every decided
# branch below runs the same Method A model under the same regulatory procedure,
# EMA_HVD_ABEL, and only the limits differ. A result used to call four of these
# branches Method.STANDARD_ABE - the 2x2 and parallel procedure, which never ran.


#: (study kwargs, endpoint, basis, widening status, acceptance strategy)
DECIDED_BRANCHES = {
    "Cmax, CVwR <= 30%": (
        {"cv_wr_percent": 15.0}, Endpoint.CMAX, BASIS,
        S.NOT_WIDENED_VARIABILITY, EmaAcceptanceStrategy.CONVENTIONAL_LIMITS,
    ),
    "Cmax, CVwR > 30%, justified and prespecified": (
        {"cv_wr_percent": 45.0}, Endpoint.CMAX, BASIS,
        S.WIDENED, EmaAcceptanceStrategy.WIDENED_ABEL_LIMITS,
    ),
    "Cmax, CVwR > 30%, not justified": (
        {"cv_wr_percent": 45.0}, Endpoint.CMAX,
        {"clinical_justification": NJ, "protocol_prespecification": P},
        S.NOT_WIDENED_BASIS_ABSENT, EmaAcceptanceStrategy.CONVENTIONAL_LIMITS,
    ),
    "Cmax, CVwR > 30%, not prespecified": (
        {"cv_wr_percent": 45.0}, Endpoint.CMAX,
        {"clinical_justification": J, "protocol_prespecification": NP},
        S.NOT_WIDENED_BASIS_ABSENT, EmaAcceptanceStrategy.CONVENTIONAL_LIMITS,
    ),
    "AUC": (
        {"cv_wr_percent": 45.0, "endpoint": "AUC"}, Endpoint.AUC, BASIS,
        S.NOT_WIDENED_ENDPOINT, EmaAcceptanceStrategy.CONVENTIONAL_LIMITS,
    ),
}


@pytest.mark.parametrize("branch", sorted(DECIDED_BRANCHES))
def test_method_identity_does_not_change_when_the_limits_do(branch):
    rows, endpoint, basis, status, strategy = DECIDED_BRANCHES[branch]
    result = assess_ema_endpoint(study(**rows), endpoint=endpoint, **basis)

    # The statistical model actually fitted.
    assert result.analysis_model == METHOD_A_MODEL
    assert result.treatment_effect.model == METHOD_A_MODEL
    assert "sequence + subject(sequence) + period + formulation" in result.analysis_model
    # The regulatory procedure.
    assert result.selected_method is Method.EMA_HVD_ABEL
    assert result.selected_method is not Method.STANDARD_ABE
    # The acceptance range, separately.
    assert result.widening_status is status
    assert result.acceptance_strategy is strategy
    if strategy is EmaAcceptanceStrategy.WIDENED_ABEL_LIMITS:
        assert result.applied_limits == result.final_scaled_limits
    else:
        assert result.applied_limits == PE
        assert result.limits is None
    # Decision semantics.
    assert result.decided is True
    assert isinstance(result.passes, bool)


def test_refusals_carry_no_method_and_no_strategy():
    unstated = assess_ema_endpoint(study(cv_wr_percent=45.0), endpoint=Endpoint.CMAX)
    other = assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="other"), endpoint=Endpoint.OTHER, **BASIS)
    for refused in (unstated, other):
        assert refused.selected_method is None
        assert refused.acceptance_strategy is None
        assert refused.analysis_model is None


def test_the_router_and_the_result_agree_on_the_method_for_every_decided_endpoint():
    for endpoint, rows in ((Endpoint.CMAX, study(cv_wr_percent=15.0)), (Endpoint.AUC, study(cv_wr_percent=45.0, endpoint="AUC"))):
        spec = resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=endpoint)
        assert spec.method is Method.EMA_HVD_ABEL
        result = assess_ema_endpoint(rows, endpoint=endpoint, spec=spec, **BASIS)
        assert result.decided
        assert result.acceptance_strategy is EmaAcceptanceStrategy.CONVENTIONAL_LIMITS
        assert result.spec_method is spec.method is result.selected_method


def test_a_supplied_ema_hvd_spec_can_never_yield_a_different_method():
    spec = resolve_be_spec(jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE, endpoint=Endpoint.AUC)
    result = assess_ema_endpoint(study(cv_wr_percent=45.0, endpoint="AUC"), endpoint=Endpoint.AUC, spec=spec, **BASIS)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(result, spec_method=Method.STANDARD_ABE)
    with pytest.raises(EmaResultInconsistent):
        dataclasses.replace(result, spec_method=Method.EMA_NTI_NARROW_ABE)


def test_a_result_cannot_claim_a_model_other_than_method_a(conventional):
    for model in ("Phase-1 2x2 TOST", "FDA Appendix C mixed model", "FDA Appendix G contrast"):
        forged = dataclasses.replace(conventional.treatment_effect, model=model)
        with pytest.raises(EmaResultInconsistent):
            dataclasses.replace(conventional, treatment_effect=forged)


def test_method_identity_reads_the_decision_and_nothing_else():
    """Structural: the property cannot be computed from limits or widening status."""
    source = textwrap.dedent(inspect.getsource(ema_hvd.EmaHighlyVariableResult.selected_method.fget))
    tree = ast.parse(source)
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "decided" in attributes
    for forbidden in ("applied_limits", "limits", "widening_status", "acceptance_strategy", "STANDARD_ABE"):
        assert forbidden not in attributes, forbidden
    assert "STANDARD_ABE" not in {n.attr for n in ast.walk(ast.parse(inspect.getsource(ema_hvd))) if isinstance(n, ast.Attribute)}


def test_capability_endpoint_scope_matches_what_the_engine_decides_and_widens():
    decided = {
        e for e in Endpoint
        if ema_abel_widening(endpoint=e, cv_wr_percent=20.0, clinical_justification=J, protocol_prespecification=P)[0].determined
    }
    widened = {
        e for e in Endpoint
        if ema_abel_widening(endpoint=e, cv_wr_percent=45.0, clinical_justification=J, protocol_prespecification=P)[0].widened
    }
    assert decided == {Endpoint.AUC, Endpoint.CMAX}
    assert widened == {Endpoint.CMAX}
    for capability_id in ("EMA_HVD_ABEL", "EMA_HVD_ENDPOINT_DECISION", "EMA_HVD_DESIGN_GATE"):
        assert set(CAPABILITY_MATRIX[capability_id].endpoints) == decided, capability_id
    for capability_id in ("EMA_ABEL_LIMIT_CALCULATION", "EMA_ABEL_WIDENING_BASIS_GATE", "EMA_HVD_VARIABILITY_ELIGIBILITY"):
        assert set(CAPABILITY_MATRIX[capability_id].endpoints) == widened, capability_id
    from be_stats.dossier.routing import route_for

    route = route_for(Jurisdiction.EMA, DrugClass.HIGHLY_VARIABLE, Endpoint.AUC)
    assert route.method is Method.EMA_HVD_ABEL
    assert decided <= set(route.endpoints)
