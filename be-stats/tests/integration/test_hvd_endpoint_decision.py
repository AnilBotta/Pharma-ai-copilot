"""The whole Appendix G flow, per endpoint.

WHAT THESE TESTS ARE FOR

Not the arithmetic - that is checked component by component in `tests/unit`.
These check the wiring: that the switch reads the right quantity, that each
endpoint decides for itself, that the two subject counts and the two degrees of
freedom stay apart, and that nothing about the answer depends on how the rows
arrived.
"""

from __future__ import annotations

import ast
import inspect
import math
import random
from pathlib import Path

import pytest

from be_stats import hvd
from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.hvd import assess_endpoint, assess_study
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    parse_sequence,
)
from be_stats.spec import Method
from be_stats.study import Treatment

PARTIAL = ("TRR", "RTR", "RRT")
FULLY = ("TRTR", "RTRT")


def synthetic(
    cv_wr: float,
    seed: int,
    *,
    n_per_sequence: int = 8,
    ratio: float = 0.95,
    labels: tuple[str, ...] = PARTIAL,
    endpoint: str = "AUC",
) -> ReplicateDataset:
    sigma = math.sqrt(math.log1p(cv_wr**2))
    rng = random.Random(seed)
    observations = []
    for label in labels:
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject_effect = rng.gauss(0.0, 0.40)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean_log = math.log(1000.0) + subject_effect
                if treatment is Treatment.TEST:
                    mean_log += math.log(ratio)
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(mean_log + rng.gauss(0.0, sigma)),
                    )
                )
    return ReplicateDataset.build(observations)


# --------------------------------------------------------------- switching ---


def test_a_low_variability_endpoint_selects_standard_abe_and_refuses_to_decide():
    """The method is selected. The decision is not made, and that is deliberate.

    Appendix G routes here; Appendix C names the model, and this package cannot
    fit it. An earlier version ran TOST on the Appendix G `ilat` contrast and
    returned a verdict. That verdict came from a different model than FDA
    specifies for this branch, and looked identical to one that did not.
    """
    result = assess_endpoint(synthetic(0.18, 11))

    assert result.swr < 0.294
    assert result.selected_method is Method.STANDARD_ABE

    assert not result.decided
    assert result.passes is None, "not decided is not the same as failing"
    assert result.standard_abe_result is None
    assert result.rsabe_result is None

    refusal = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED
    ]
    assert len(refusal) == 1
    assert refusal[0].severity is Severity.FATAL
    assert "Appendix C" in refusal[0].detail
    assert "required_model" in refusal[0].context


def test_the_refusal_still_returns_the_quantities_it_did_compute():
    """Refusing the decision is not refusing to report.

    sWR, CVwR, the selected method and the treatment contrast are all real and
    all returned. Only the verdict is withheld.
    """
    result = assess_endpoint(synthetic(0.18, 11))

    assert result.swr is not None and result.swr > 0.0
    assert result.cv_wr is not None
    assert result.treatment_contrast is not None
    assert result.treatment_contrast.estimable
    assert result.n_for_swr == 24
    assert result.reference_variance_df == 21


def test_a_high_variability_endpoint_takes_reference_scaling():
    result = assess_endpoint(synthetic(0.45, 22))

    assert result.decided
    assert result.swr >= 0.294
    assert result.selected_method is Method.FDA_HVD_RSABE
    assert result.rsabe_result is not None
    assert result.standard_abe_result is None


def test_the_switch_reads_swr_and_not_a_rounded_cv():
    """CVwR is a display quantity; the rule is stated on sWR.

    A study whose sWR sits just under the threshold has a CVwR near 30%, and
    rounding that for display then switching on it would move the boundary by
    whatever the rounding happened to be.
    """
    from be_stats.spec import fda_hvd_method_for

    for swr, expected in (
        (0.293999, Method.STANDARD_ABE),
        (0.294000, Method.FDA_HVD_RSABE),
        (0.294001, Method.FDA_HVD_RSABE),
        (0.0, Method.STANDARD_ABE),
    ):
        assert fda_hvd_method_for(swr) is expected

    source = Path(inspect.getfile(hvd)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    switch_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "fda_hvd_method_for"
    ]
    assert switch_calls, "the module must route through the frozen rule"
    for call in switch_calls:
        argument = ast.unparse(call.args[0])
        assert "swr" in argument
        assert "cv" not in argument.lower(), (
            f"the switch is applied to {argument}, which mentions CV"
        )


def test_zero_swr_routes_to_standard_abe():
    """sWR = 0 is below the threshold, so ordinary average BE applies.

    Whether that analysis can then run is its own question, answered on its own
    evidence - here the contrast has real variability, so it can.
    """
    observations = []
    for label in PARTIAL:
        sequence = parse_sequence(label)
        for k, ratio in enumerate((0.94, 0.99, 1.03)):
            for period in range(1, 4):
                treatment = sequence.expected_treatment(period)
                # Both references identical -> sWR = 0. Test values vary.
                value = 100.0 * ratio if treatment is Treatment.TEST else 100.0
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC", value
                    )
                )
    result = assess_endpoint(ReplicateDataset.build(observations))

    assert result.swr == 0.0
    assert result.selected_method is Method.STANDARD_ABE
    assert any(
        d.code is DiagnosticCode.ZERO_REFERENCE_VARIANCE for d in result.diagnostics
    )
    # Routed correctly, and then refused for the branch's own reason.
    assert not result.decided
    assert any(
        d.code is DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED
        for d in result.diagnostics
    )


# ------------------------------------------------------- per-endpoint choice ---


def test_auc_and_cmax_choose_different_methods_in_the_same_study():
    """FDA determines the method "for the individual PK parameter".

    Classifying the study on its worst endpoint and scaling everything would
    hand the well-behaved endpoint a wider acceptance region than it earned.
    """
    results = assess_study(
        {
            "AUC": synthetic(0.18, 11, endpoint="AUC"),
            "Cmax": synthetic(0.45, 22, endpoint="Cmax"),
        }
    )

    assert results["AUC"].swr < 0.294
    assert results["Cmax"].swr >= 0.294
    assert results["AUC"].selected_method is Method.STANDARD_ABE
    assert results["Cmax"].selected_method is Method.FDA_HVD_RSABE

    # The scaled endpoint decides; the unscaled one selects its method and
    # then refuses, because Appendix C is not implemented.
    assert results["Cmax"].decided
    assert results["Cmax"].rsabe_result is not None
    assert results["Cmax"].standard_abe_result is None

    assert not results["AUC"].decided
    assert results["AUC"].standard_abe_result is None
    assert results["AUC"].rsabe_result is None
    assert results["AUC"].passes is None


def test_the_endpoint_travels_with_its_own_result():
    results = assess_study(
        {
            "AUC": synthetic(0.18, 11, endpoint="AUC"),
            "Cmax": synthetic(0.45, 22, endpoint="Cmax"),
        }
    )
    assert results["AUC"].endpoint == "AUC"
    assert results["Cmax"].endpoint == "Cmax"


# --------------------------------- two subject counts, two degrees of freedom ---


def test_the_two_subject_counts_can_differ_and_both_are_reported():
    """A subject missing its test measurement has no contrast, and may still
    have both reference replicates. That is a legitimate study, and the result
    must not report one number for both."""
    observations = []
    for label in PARTIAL:
        sequence = parse_sequence(label)
        for k in range(6):
            for period in range(1, 4):
                treatment = sequence.expected_treatment(period)
                if label == "TRR" and k == 0 and treatment is Treatment.TEST:
                    continue
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC",
                        100.0 + 3 * k + period * (2 if treatment is Treatment.TEST else 1),
                    )
                )
    result = assess_endpoint(ReplicateDataset.build(observations))

    assert result.n_for_swr == 18, "the subject still has both references"
    assert result.n_for_treatment_contrast == 17
    assert result.n_for_swr != result.n_for_treatment_contrast

    # The same condition fires twice with the same code and different
    # severities, which is the documented behaviour: it changed nothing for
    # sWR and removed the subject from the contrast. `model` in the context
    # says which entry is which.
    entries = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.MISSING_TEST_OBSERVATION
    ]
    severities = {d.severity for d in entries}
    assert severities == {Severity.ADVISORY, Severity.EXCLUSION}

    contrast_entry = next(
        d for d in entries if d.context.get("model") == "treatment_contrast"
    )
    assert contrast_entry.severity is Severity.EXCLUSION
    assert contrast_entry.subject == "TRR-0"


def test_the_two_degrees_of_freedom_are_separate_fields():
    """Appendix G uses them for different pieces of the upper bound.

    `bound_y` scales by the REFERENCE VARIANCE's degrees of freedom; the
    interval that forms `bound_x` uses the CONTRAST's. One generic `df` would
    make them the same number by construction.
    """
    observations = []
    for label in PARTIAL:
        sequence = parse_sequence(label)
        for k in range(6):
            for period in range(1, 4):
                treatment = sequence.expected_treatment(period)
                if label == "RRT" and k == 0 and treatment is Treatment.TEST:
                    continue
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC",
                        100.0 + 4 * k + period * (3 if treatment is Treatment.TEST else 1),
                    )
                )
    result = assess_endpoint(ReplicateDataset.build(observations))

    assert result.reference_variance_df == 18 - 3
    assert result.treatment_contrast_df == 17 - 3
    assert result.reference_variance_df != result.treatment_contrast_df

    if result.rsabe_result is not None:
        assert (
            result.rsabe_result.scaled_criterion.reference_variance_df
            == result.reference_variance_df
        )


def test_the_scaled_criterion_scales_by_the_reference_variance_df():
    result = assess_endpoint(synthetic(0.45, 22))
    assert result.rsabe_result is not None
    criterion = result.rsabe_result.scaled_criterion
    assert criterion.reference_variance_df == result.reference_variance_df
    assert criterion.reference_variance == result.reference_variance.variance_wr


# --------------------------------------------------- the standard branch ---


def test_no_module_forms_its_own_tost_interval():
    """One implementation of the interval, in `abe.abe_from_log_contrast`.

    Checked structurally: neither the decision module nor the contrast module
    may contain a Student-t quantile beyond the contrast's own interval, and
    `hvd.py` must contain none at all. Two implementations of one procedure is
    how a fourth-decimal disagreement lives for a year.

    `abe_from_log_contrast` is deliberately kept even though the unscaled
    branch currently refuses: Appendix C, when implemented, must produce a
    contrast, an SE and degrees of freedom and then hand them to it rather than
    forming an interval of its own.
    """
    source = Path(inspect.getfile(hvd)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    t_uses = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "stats"
        and node.attr == "t"
    ]
    assert not t_uses, f"hvd.py forms its own t interval: {t_uses}"

    from be_stats import abe

    # A t QUANTILE is what forms an interval. `stats.t.sf` and `stats.t.cdf`
    # are tail probabilities and belong to `tost_p_values`, which reports the
    # two one-sided p-values and decides nothing - so the check is on `ppf`.
    abe_source = Path(inspect.getfile(abe)).read_text(encoding="utf-8")
    quantile_sites = [
        node.lineno
        for node in ast.walk(ast.parse(abe_source))
        if isinstance(node, ast.Attribute)
        and node.attr == "ppf"
        and ast.unparse(node).startswith("stats.t.")
    ]
    assert len(quantile_sites) == 1, (
        f"abe.py forms a t interval at lines {quantile_sites}; there must be "
        "exactly one such place in the package"
    )


def test_phase_one_routes_through_the_shared_core_too():
    """The abstraction is live, not speculative.

    `analyse_crossover` and `analyse_parallel` build their own contrasts and
    then call the same function the replicate branch will. If either grew its
    own interval again, the count above would rise.
    """
    from be_stats import abe

    source = Path(inspect.getfile(abe)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for name in ("analyse_crossover", "analyse_parallel"):
        function = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        calls = {
            n.func.id
            for n in ast.walk(function)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "abe_from_log_contrast" in calls, name


def test_the_unscaled_branch_is_not_implemented_rather_than_experimental():
    """A status field does not travel with a number.

    Marking this EXPERIMENTAL while returning a bioequivalence verdict put the
    caveat somewhere the verdict would not carry it. The branch refuses now,
    and the status says so.
    """
    from be_stats import CAPABILITY_VALIDATION, Capability, ValidationStatus

    assert (
        CAPABILITY_VALIDATION[Capability.FDA_HVD_UNSCALED_BRANCH]
        is ValidationStatus.NOT_IMPLEMENTED
    )
    assert ValidationStatus.EXPERIMENTAL not in CAPABILITY_VALIDATION.values()


def test_the_summary_says_the_endpoint_was_not_decided():
    result = assess_endpoint(synthetic(0.18, 11))
    text = result.summary()
    assert "sWR" in text
    assert "0.294" in text
    assert "standard_abe" in text
    assert "NOT DECIDED" in text
    assert "REPLICATE_ABE_MODEL_NOT_IMPLEMENTED" in text


# ---------------------------------------- the two analyses must stay distinct ---


def test_appendix_g_and_appendix_c_operate_on_different_data():
    """The regression that stops a future refactor merging them.

    Both eventually produce a T-R contrast, which makes them look
    interchangeable. They are not: Appendix G's intermediate is built from
    `Iij`/`Dij` - within-subject combinations that absorb period - while
    Appendix C is fitted on the subject-period observations with SEQ, PER and
    TRT as fixed effects.

    Structural rather than numerical, because the numerical difference is
    exactly the thing that would not be noticed.
    """
    from be_stats import replicate_abe, treatment_contrast

    contrast_source = Path(inspect.getfile(treatment_contrast)).read_text(
        encoding="utf-8"
    )
    contrast_tree = ast.parse(contrast_source)
    contrast_imports = {
        alias.name
        for node in ast.walk(contrast_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "treatment_contrasts" in contrast_imports, (
        "the Appendix G estimator works from Iij"
    )

    model = replicate_abe.APPENDIX_C_MODEL
    assert model.operates_on == "subject-period log observations"
    assert "Iij" not in model.operates_on and "Dij" not in model.operates_on
    assert set(model.fixed_effects) == {"sequence", "period", "treatment"}
    assert "period" in model.fixed_effects, (
        "Appendix G's Iij absorbs period within a subject; Appendix C estimates it"
    )
    assert model.n_covariance_parameters == 5


def test_the_appendix_c_specification_is_recorded_even_though_it_does_not_run():
    from be_stats import replicate_abe
    from be_stats.provenance import ValidationStatus

    assert replicate_abe.VALIDATION_STATUS is ValidationStatus.NOT_IMPLEMENTED

    explained = " ".join(replicate_abe.APPENDIX_C_MODEL.explain())
    for fragment in ("sequence", "period", "treatment", "FA0(2)", "GRP=TRT",
                     "Satterthwaite", "Appendix C", "May 2026"):
        assert fragment in explained


def test_calling_the_appendix_c_analysis_raises_with_the_model_it_needs():
    from be_stats.replicate_abe import analyse_replicate_abe
    from be_stats.spec import NotImplementedMethod

    with pytest.raises(NotImplementedMethod) as exc:
        analyse_replicate_abe(synthetic(0.18, 11))
    message = str(exc.value)
    assert "Appendix C" in message
    assert "FA0(2)" in message
    assert "Satterthwaite" in message


def test_the_satterthwaite_collapse_is_not_claimed_for_appendix_c():
    """The scoping the review asked for, asserted where it will be read.

    "Satterthwaite reduces to the residual df" is true of Appendix G's
    single-component `ilat = seq` model. Appendix C has five components and its
    degrees of freedom must come from that model.
    """
    from be_stats import treatment_contrast

    doc = treatment_contrast.satterthwaite_df.__doc__ or ""
    assert "NOT true of Appendix C" in doc
    assert "five" in doc or "5" in doc


# ------------------------------------------------------------- provenance ---


def test_the_constants_are_not_duplicated_in_this_module():
    """`sigma_w0`, `theta` and the point-estimate limits are consumed from the
    spec layer, so the calculation inherits their citations."""
    source = Path(inspect.getfile(hvd)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = (0.25, 0.294, 0.8000, 1.2500)
    offenders = [
        f"{node.value} at line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and any(abs(node.value - f) < 1e-12 for f in forbidden)
    ]
    assert not offenders, (
        "regulatory constants re-declared as bare literals: " + ", ".join(offenders)
    )


def test_the_result_can_explain_where_its_numbers_came_from():
    result = assess_endpoint(synthetic(0.45, 22))
    text = " ".join(result.provenance())
    assert "Appendix G" in text
    assert "May 2026" in text
    assert "primary document" in text


def test_rsabe_is_implemented_but_not_validated():
    from be_stats import VALIDATION, ValidationStatus

    assert VALIDATION[Method.FDA_HVD_RSABE] is (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.NOT_IMPLEMENTED
    # EMA ABEL is implemented as of the EMA release and is still not VALIDATED.
    # It has tier-1B evidence, which FDA HVD does not — EMA published two
    # worked data sets and both reproduce — but the cap reading remains open
    # (VAL-EMA-ABEL-002), so the method-level status stays unvalidated.
    assert VALIDATION[Method.EMA_HVD_ABEL] is (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    for status in VALIDATION.values():
        assert status is not ValidationStatus.VALIDATED


# ------------------------------------------------------------- invariance ---


def _decision(observations) -> tuple:
    result = assess_endpoint(ReplicateDataset.build(observations))
    criterion = result.rsabe_result.scaled_criterion if result.rsabe_result else None
    return (
        result.selected_method,
        result.swr,
        result.treatment_contrast.estimate,
        result.treatment_contrast.standard_error,
        result.treatment_contrast.degrees_of_freedom,
        result.reference_variance_df,
        None if criterion is None else criterion.upper_confidence_bound,
        result.passes,
    )


@pytest.mark.parametrize("cv,seed", [(0.18, 11), (0.45, 22)])
def test_shuffling_rows_does_not_change_the_regulatory_result(cv, seed):
    """Carried forward from the previous release, and asserted EXACTLY.

    No tolerance is needed or granted: every quantity here is a closed form
    over `math.fsum`, so permutation cannot move a bit. A tolerance would be
    the place a real order-dependence could hide.
    """
    observations = list(synthetic(cv, seed).records) and _rows(cv, seed)
    baseline = _decision(observations)

    rng = random.Random(4242)
    for _ in range(15):
        shuffled = observations[:]
        rng.shuffle(shuffled)
        assert _decision(shuffled) == baseline


def _rows(cv: float, seed: int) -> list[ReplicateObservation]:
    sigma = math.sqrt(math.log1p(cv**2))
    rng = random.Random(seed)
    observations = []
    for label in PARTIAL:
        sequence = parse_sequence(label)
        for k in range(8):
            subject_effect = rng.gauss(0.0, 0.40)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean_log = math.log(1000.0) + subject_effect
                if treatment is Treatment.TEST:
                    mean_log += math.log(0.95)
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, "AUC",
                        math.exp(mean_log + rng.gauss(0.0, sigma)),
                    )
                )
    return observations


def test_renaming_subjects_does_not_change_the_regulatory_result():
    observations = _rows(0.45, 22)
    baseline = _decision(observations)
    renamed = [
        ReplicateObservation(
            f"ANON-{abs(hash(o.subject_id)) % 99991}",
            o.sequence, o.period, o.treatment, o.endpoint, o.value,
        )
        for o in observations
    ]
    assert _decision(renamed) == baseline


def test_reordering_sequence_groups_does_not_change_the_regulatory_result():
    observations = _rows(0.45, 22)
    baseline = _decision(observations)
    order = {"RRT": 0, "TRR": 1, "RTR": 2}
    regrouped = sorted(
        observations, key=lambda o: (order[o.sequence.value], o.subject_id, o.period)
    )
    assert _decision(regrouped) == baseline


def test_reversing_period_order_does_not_change_the_regulatory_result():
    observations = _rows(0.45, 22)
    assert _decision(list(reversed(observations))) == _decision(observations)


# ------------------------------------------------------------- refusals ---


def test_an_undecidable_endpoint_says_so_rather_than_failing():
    """`passes` is None, not False. A study that could not be assessed is not
    a study that failed."""
    observations = []
    for label in ("TRR", "RTR"):
        sequence = parse_sequence(label)
        for k in range(4):
            for period in range(1, 4):
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period,
                        sequence.expected_treatment(period), "AUC",
                        100.0 + k + period,
                    )
                )
    result = assess_endpoint(ReplicateDataset.build(observations))

    assert not result.decided
    assert result.passes is None
    assert result.selected_method is None
    assert result.swr is None
    assert any(
        d.code is DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS
        for d in result.diagnostics
    )


def test_a_fully_replicate_study_is_decided_too():
    result = assess_endpoint(synthetic(0.45, 33, n_per_sequence=12, labels=FULLY))
    assert result.decided
    assert result.selected_method is Method.FDA_HVD_RSABE
    assert result.reference_variance_df == 24 - 2
    assert result.treatment_contrast_df == pytest.approx(24 - 2, rel=1e-12)
