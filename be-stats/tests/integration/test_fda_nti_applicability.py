"""FDA NTI end to end: the product class gates the verdict, and nothing else may.

WHAT THIS FILE EXISTS BECAUSE OF

PR #82 found that FDA's highly variable procedure issued verdicts for products
nobody had said were not NTI. Auditing the NTI procedure for the same defect
found it from the other side, and worse: `assess_nti_endpoint` took no
product-class input AT ALL. A STANDARD or HIGHLY_VARIABLE product on a fully
replicate design received an Appendix F verdict - sigma_W0 = 0.10, the
variability comparison against 2.500 - that FDA applies to nothing but NTI
drugs. The same audit found that `assess_nti_study` could never decide anything,
and that a result could be BUILT asserting `decided=True` with a criterion
missing.

THE ORDER THE ENGINE NOW FOLLOWS

    spec jurisdiction   another jurisdiction's spec is refused, not reconciled
    product class       spec and nti_status reconciled; disagreement raises
    applicability       Appendix F decides only a product CONFIRMED NTI
    design              III.B: fully replicate, or NtiDesignError
    criteria            a, b, c - each reported on its own
    decision            all three evaluated and all three passed

Applicability is asked before the design because the design requirement is a
requirement OF the NTI procedure. For a product that procedure does not apply
to, the design is not the question - and a partial replicate study of a
non-NTI product is refused as "not applicable", never as "wrong design".
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
import random
from pathlib import Path

import pytest

from be_stats import hvd, nti
from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.dossier.constants import (
    ConstantKind,
    constant,
    unpinned_normative_constants,
)
from be_stats.howe import HoweUpperBound
from be_stats.nti import (
    VARIABILITY_ALPHA,
    FdaNtiResult,
    NtiDesignError,
    NtiNotDecidable,
    NtiScaledMeanCriterion,
    NtiUnscaledAbeCriterion,
    NtiVariabilityRatioCriterion,
    WithinTestVarianceResult,
    assess_nti_endpoint,
    assess_nti_study,
)
from be_stats.provenance import VerificationStatus
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateObservation,
    parse_sequence,
)
from be_stats.spec import (
    FDA_NTI_CONSTANTS,
    ContradictoryProductClass,
    DrugClass,
    Endpoint,
    HvdApplicability,
    Jurisdiction,
    Method,
    NotApplicable,
    NtiApplicability,
    NtiStatus,
    fda_hvd_applicability,
    fda_nti_applicability,
    fda_nti_theta,
    resolve_be_spec,
)
from be_stats.study import Treatment

FULLY = ("TRTR", "RTRT")
PARTIAL = ("TRR", "RTR", "RRT")
NTI = NtiStatus.NARROW_THERAPEUTIC_INDEX
NON_NTI = NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX


def rows(
    cv_wr: float,
    cv_wt: float,
    seed: int,
    *,
    labels: tuple[str, ...] = FULLY,
    n_per_sequence: int = 12,
    ratio: float = 0.97,
    endpoint: str = "AUC",
) -> list[ReplicateObservation]:
    """Deterministic subject-period observations. Seeded, never drawn at random."""
    sigma_r = math.sqrt(math.log1p(cv_wr**2))
    sigma_t = math.sqrt(math.log1p(cv_wt**2))
    rng = random.Random(seed)
    out: list[ReplicateObservation] = []
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
                out.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period, treatment, endpoint,
                        math.exp(
                            mean_log
                            + rng.gauss(0.0, sigma_t if is_test else sigma_r)
                        ),
                    )
                )
    return out


def dataset(observations: list[ReplicateObservation]) -> ReplicateDataset:
    return ReplicateDataset.build(observations)


def fda_spec(drug_class: DrugClass):
    endpoint = (
        Endpoint.CMAX if drug_class is DrugClass.HIGHLY_VARIABLE else Endpoint.AUC
    )
    return resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=drug_class, endpoint=endpoint
    )


@pytest.fixture(scope="module")
def decided() -> FdaNtiResult:
    """A confirmed NTI product, fully replicate, raw rows supplied: all three."""
    observations = rows(0.10, 0.11, 3)
    return assess_nti_endpoint(
        dataset(observations), observations=observations, nti_status=NTI
    )


# ============================================================ the rule ===


@pytest.mark.parametrize(
    "status,expected,permits",
    [
        (NTI, NtiApplicability.APPLICABLE, True),
        (NON_NTI, NtiApplicability.NOT_APPLICABLE_NOT_NTI, False),
        (NtiStatus.NOT_STATED, NtiApplicability.UNDETERMINED_NTI_NOT_STATED, False),
    ],
)
def test_applicability_is_decided_by_the_declared_class_alone(status, expected, permits):
    applicability = fda_nti_applicability(status)
    assert applicability is expected
    assert applicability.permits_verdict is permits


def test_applicability_takes_no_data():
    """On the signature: nothing measured can reach the gate."""
    assert list(inspect.signature(fda_nti_applicability).parameters) == ["nti_status"]


def test_the_two_fda_scaled_procedures_admit_disjoint_products():
    """No declared status lets both Appendix F and Appendix G decide.

    And an unstated status lets neither - the shared reconciliation fails
    closed in both directions.
    """
    for status in NtiStatus:
        nti_permits = fda_nti_applicability(status).permits_verdict
        hvd_permits = fda_hvd_applicability(status).permits_verdict
        assert not (nti_permits and hvd_permits), status
    assert not fda_nti_applicability(NtiStatus.NOT_STATED).permits_verdict
    assert not fda_hvd_applicability(NtiStatus.NOT_STATED).permits_verdict


def test_every_applicability_member_is_accounted_for():
    assert set(NtiApplicability) == {
        NtiApplicability.APPLICABLE,
        NtiApplicability.NOT_APPLICABLE_NOT_NTI,
        NtiApplicability.UNDETERMINED_NTI_NOT_STATED,
    }
    assert [a for a in NtiApplicability if a.permits_verdict] == [
        NtiApplicability.APPLICABLE
    ]


# ================================================ confirmed NTI: decided ===


def test_a_confirmed_nti_product_gets_all_three_criteria_and_a_verdict(decided):
    assert decided.applicability is NtiApplicability.APPLICABLE
    assert decided.selected_method is Method.FDA_NTI_RSABE
    assert decided.design_valid is True
    assert decided.decided is True

    for label in ("a", "b", "c"):
        assert getattr(decided, f"criterion_{label}_passes") is not None, label
    assert decided.unavailable_criteria == ()
    assert decided.passes is (
        decided.criterion_a_passes
        and decided.criterion_b_passes
        and decided.criterion_c_passes
    )
    refusal_codes = {
        DiagnosticCode.FDA_NTI_NOT_APPLICABLE_NOT_NTI,
        DiagnosticCode.FDA_NTI_APPLICABILITY_REQUIRES_NTI_STATUS,
    }
    assert not [d for d in decided.diagnostics if d.code in refusal_codes]


def test_criterion_b_shows_its_interval_and_its_ratio(decided):
    """Review section 6: the 90% CI, the GMR, the limits and the outcome."""
    b = decided.unscaled_abe_criterion
    assert b.computed
    assert b.ci_lower_percent is not None and b.ci_upper_percent is not None
    assert b.geometric_mean_ratio_percent is not None
    assert b.ci_lower_percent <= b.geometric_mean_ratio_percent <= b.ci_upper_percent
    assert (b.lower_limit_percent, b.upper_limit_percent) == (80.00, 125.00)
    assert b.passes in (True, False)


# ============================================ not NTI, or not stated: refused ===


@pytest.mark.parametrize("labels", [FULLY, PARTIAL], ids=["fully", "partial"])
@pytest.mark.parametrize(
    "status,expected,code",
    [
        (
            NON_NTI,
            NtiApplicability.NOT_APPLICABLE_NOT_NTI,
            DiagnosticCode.FDA_NTI_NOT_APPLICABLE_NOT_NTI,
        ),
        (
            NtiStatus.NOT_STATED,
            NtiApplicability.UNDETERMINED_NTI_NOT_STATED,
            DiagnosticCode.FDA_NTI_APPLICABILITY_REQUIRES_NTI_STATUS,
        ),
    ],
    ids=["not-nti", "not-stated"],
)
def test_a_product_not_confirmed_nti_gets_no_appendix_f_verdict(
    status, expected, code, labels
):
    """Whatever the design, and with the raw rows supplied.

    A partial replicate here is refused as NOT APPLICABLE, not as the wrong
    design: the design requirement belongs to a procedure that does not apply.
    """
    observations = rows(0.12, 0.13, 5, labels=labels)
    result = assess_nti_endpoint(
        dataset(observations), observations=observations, nti_status=status
    )

    assert result.applicability is expected
    assert result.decided is False
    assert result.passes is None
    assert result.selected_method is None
    assert result.design_valid is None
    for field in (
        "scaled_mean_criterion",
        "unscaled_abe_criterion",
        "variability_ratio_criterion",
        "test_variance",
        "treatment_contrast",
    ):
        assert getattr(result, field) is None, field
    assert result.failed_criteria == ()

    refusals = [d for d in result.diagnostics if d.code is code]
    assert len(refusals) == 1
    assert refusals[0].severity is Severity.FATAL

    # Descriptive, and only descriptive.
    assert result.reference_variance.estimable
    assert result.reference_variance.swr > 0.0
    assert result.n_for_swr > 0


def test_the_class_is_not_inferred_from_a_study_that_looks_like_an_nti_study():
    """A fully replicate design and a 5% CVwR - still not evidence of NTI."""
    observations = rows(0.05, 0.05, 7)
    result = assess_nti_endpoint(dataset(observations), observations=observations)

    assert result.applicability is NtiApplicability.UNDETERMINED_NTI_NOT_STATED
    assert result.decided is False
    assert result.passes is None


def test_an_nti_product_on_a_partial_replicate_is_a_specification_failure():
    """Refused by raising, and never downgraded to another method."""
    partial = dataset(rows(0.12, 0.13, 5, labels=PARTIAL, n_per_sequence=4))
    with pytest.raises(NtiDesignError):
        assess_nti_endpoint(partial, nti_status=NTI)


def test_the_unstated_default_is_on_the_signature():
    parameters = inspect.signature(assess_nti_endpoint).parameters
    assert parameters["nti_status"].default is NtiStatus.NOT_STATED
    assert parameters["spec"].default is None
    assert parameters["observations"].default is None


# ================================================ the spec, reconciled ===


def test_an_nti_spec_establishes_the_class_on_its_own():
    result = assess_nti_endpoint(
        dataset(rows(0.10, 0.11, 3)), spec=fda_spec(DrugClass.NARROW_THERAPEUTIC_INDEX)
    )
    assert result.applicability is NtiApplicability.APPLICABLE
    assert result.selected_method is Method.FDA_NTI_RSABE
    # Without the raw rows criterion b is not computed: applicable, undecided.
    assert result.scaled_mean_criterion is not None
    assert result.variability_ratio_criterion is not None
    assert result.decided is False


@pytest.mark.parametrize("drug_class", [DrugClass.STANDARD, DrugClass.HIGHLY_VARIABLE])
def test_a_standard_or_hvd_spec_refuses_through_the_gate(drug_class):
    result = assess_nti_endpoint(dataset(rows(0.10, 0.11, 3)), spec=fda_spec(drug_class))
    assert result.applicability is NtiApplicability.NOT_APPLICABLE_NOT_NTI
    assert result.decided is False
    assert result.selected_method is None


@pytest.mark.parametrize(
    "drug_class,status",
    [
        (DrugClass.NARROW_THERAPEUTIC_INDEX, NON_NTI),
        (DrugClass.STANDARD, NTI),
        (DrugClass.HIGHLY_VARIABLE, NTI),
    ],
)
def test_a_contradictory_spec_and_status_fail_closed(drug_class, status):
    with pytest.raises(ContradictoryProductClass) as raised:
        assess_nti_endpoint(
            dataset(rows(0.10, 0.11, 3)), spec=fda_spec(drug_class), nti_status=status
        )
    message = str(raised.value)
    assert str(drug_class) in message
    assert str(status) in message


@pytest.mark.parametrize(
    "drug_class,status,expected",
    [
        (DrugClass.NARROW_THERAPEUTIC_INDEX, NTI, NtiApplicability.APPLICABLE),
        (DrugClass.STANDARD, NON_NTI, NtiApplicability.NOT_APPLICABLE_NOT_NTI),
    ],
)
def test_agreeing_inputs_reconcile_without_complaint(drug_class, status, expected):
    result = assess_nti_endpoint(
        dataset(rows(0.10, 0.11, 3)), spec=fda_spec(drug_class), nti_status=status
    )
    assert result.applicability is expected


def test_the_contradiction_is_raised_before_the_design_gate():
    """A partial replicate with contradictory inputs: the contradiction wins.

    The class question is settled before the data are examined at all, so the
    error names the actual problem rather than a design nobody should be asking
    about yet.
    """
    partial = dataset(rows(0.12, 0.13, 5, labels=PARTIAL, n_per_sequence=4))
    with pytest.raises(ContradictoryProductClass):
        assess_nti_endpoint(
            partial,
            spec=fda_spec(DrugClass.NARROW_THERAPEUTIC_INDEX),
            nti_status=NON_NTI,
        )


def test_a_spec_for_another_jurisdiction_is_refused_not_reconciled():
    other = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    with pytest.raises(NotApplicable):
        assess_nti_endpoint(dataset(rows(0.10, 0.11, 3)), spec=other, nti_status=NTI)


# ================================================ unconstructible states ===


def _scaled(bound: float) -> NtiScaledMeanCriterion:
    return NtiScaledMeanCriterion(
        bound=HoweUpperBound(
            x=0.001, bound_x=0.01, y=-0.02, bound_y=-0.013,
            theta=fda_nti_theta(), reference_variance=0.018,
            reference_variance_df=22, upper_confidence_bound=bound,
        ),
        sigma_w0=0.10, delta=1.0 / 0.9,
        estimate=0.03, standard_error=0.02, ci_lower=-0.01, ci_upper=0.07,
    )


def _unscaled(lower: float, upper: float, computed: bool = True) -> NtiUnscaledAbeCriterion:
    return NtiUnscaledAbeCriterion(
        lower_limit_percent=80.0,
        upper_limit_percent=125.0,
        computed=computed,
        reason="fixture",
        ci_lower_percent=lower if computed else None,
        ci_upper_percent=upper if computed else None,
        geometric_mean_ratio_percent=((lower * upper) ** 0.5) if computed else None,
    )


def _ratio(ci_upper: float | None, ratio: float = 1.2) -> NtiVariabilityRatioCriterion:
    return NtiVariabilityRatioCriterion(
        swt=0.12, swr=0.10, ratio=ratio if ci_upper is not None else None,
        df_test=22, df_reference=22,
        ci_lower=0.9 if ci_upper is not None else None, ci_upper=ci_upper,
        limit=2.5, estimable=ci_upper is not None,
    )


def _built(*, a=True, b=True, c=True, decided=True, **overrides) -> FdaNtiResult:
    fields = dict(
        endpoint="AUC",
        design=ReplicateDesign.FULLY_REPLICATE,
        reference_variance=None,
        scaled_mean_criterion=_scaled(-0.01 if a else 0.01),
        unscaled_abe_criterion=_unscaled(92.0 if b else 74.0, 118.0),
        variability_ratio_criterion=_ratio(2.0 if c else 3.1),
        decided=decided,
    )
    fields.update(overrides)
    return FdaNtiResult(**fields)


@pytest.mark.parametrize(
    "applicability",
    [NtiApplicability.NOT_APPLICABLE_NOT_NTI, NtiApplicability.UNDETERMINED_NTI_NOT_STATED],
)
def test_a_refused_result_cannot_be_decided(applicability):
    with pytest.raises(NtiNotDecidable, match="does not apply"):
        FdaNtiResult(
            endpoint="AUC",
            design=ReplicateDesign.FULLY_REPLICATE,
            reference_variance=None,
            applicability=applicability,
            decided=True,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("scaled_mean_criterion", _scaled(-0.01)),
        ("unscaled_abe_criterion", _unscaled(92.0, 118.0)),
        ("variability_ratio_criterion", _ratio(2.0)),
        ("test_variance", WithinTestVarianceResult(0.0144, 0.12, 22, 24, 2, True)),
        ("treatment_contrast", object()),
    ],
)
def test_a_refused_result_cannot_carry_the_analysis_it_would_have_received(field, value):
    with pytest.raises(NtiNotDecidable, match=field):
        FdaNtiResult(
            endpoint="AUC",
            design=ReplicateDesign.FULLY_REPLICATE,
            reference_variance=None,
            applicability=NtiApplicability.NOT_APPLICABLE_NOT_NTI,
            decided=False,
            **{field: value},
        )


@pytest.mark.parametrize(
    "missing,overrides",
    [
        ("a", {"scaled_mean_criterion": None}),
        ("b", {"unscaled_abe_criterion": None}),
        ("c", {"variability_ratio_criterion": None}),
        ("b", {"unscaled_abe_criterion": _unscaled(0.0, 0.0, computed=False)}),
        ("c", {"variability_ratio_criterion": _ratio(None)}),
    ],
    ids=["a-absent", "b-absent", "c-absent", "b-uncomputed", "c-unestimable"],
)
def test_decided_cannot_be_true_with_a_criterion_missing(missing, overrides):
    with pytest.raises(NtiNotDecidable, match=f"criterion {missing}"):
        _built(**overrides)

    undecided = _built(decided=False, **overrides)
    assert undecided.passes is None
    assert missing in undecided.unavailable_criteria


def test_selected_method_is_derived_and_has_no_field_to_contradict():
    names = {f.name for f in dataclasses.fields(FdaNtiResult)}
    assert "selected_method" not in names
    assert _built().selected_method is Method.FDA_NTI_RSABE
    refused = FdaNtiResult(
        endpoint="AUC",
        design=ReplicateDesign.FULLY_REPLICATE,
        reference_variance=None,
        applicability=NtiApplicability.UNDETERMINED_NTI_NOT_STATED,
    )
    assert refused.selected_method is None


# ============================================== the three-way conjunction ===


@pytest.mark.parametrize("a", [True, False])
@pytest.mark.parametrize("b", [True, False])
@pytest.mark.parametrize("c", [True, False])
def test_the_verdict_is_the_conjunction_and_names_what_failed(a, b, c):
    result = _built(a=a, b=b, c=c)
    assert result.passes is (a and b and c)
    assert result.failed_criteria == tuple(
        label for label, ok in (("a", a), ("b", b), ("c", c)) if not ok
    )


# ======================================================== exact boundaries ===


@pytest.mark.parametrize("bound,expected", [(-1e-12, True), (0.0, True), (1e-12, False)])
def test_criterion_a_boundary(bound, expected):
    assert _scaled(bound).passes is expected


@pytest.mark.parametrize(
    "lower,upper,expected",
    [
        (80.0, 110.0, True),
        (79.999999, 110.0, False),
        (90.0, 125.0, True),
        (90.0, 125.000001, False),
        (80.0, 125.0, True),
    ],
)
def test_criterion_b_boundary(lower, upper, expected):
    assert _unscaled(lower, upper).passes is expected


@pytest.mark.parametrize(
    "ci_upper,expected", [(2.499999, True), (2.5, True), (2.500001, False)]
)
def test_criterion_c_boundary(ci_upper, expected):
    assert _ratio(ci_upper).passes is expected


def test_criterion_c_tests_the_confidence_limit_not_the_point_ratio():
    """A comfortable ratio with an upper limit over 2.500 fails."""
    criterion = _ratio(2.6, ratio=1.1)
    assert criterion.ratio < criterion.limit
    assert criterion.passes is False


def test_all_three_exactly_on_their_boundaries_pass():
    result = _built(
        scaled_mean_criterion=_scaled(0.0),
        unscaled_abe_criterion=_unscaled(80.0, 125.0),
        variability_ratio_criterion=_ratio(2.5),
    )
    assert result.passes is True


# ================================================== constants and literals ===


def test_the_normative_constants_are_the_ones_appendix_f_states():
    assert FDA_NTI_CONSTANTS["sigma_w0"].value == 0.10
    assert FDA_NTI_CONSTANTS["delta"].value == 1.0 / 0.9
    assert FDA_NTI_CONSTANTS["delta"].value != 1.11111
    assert fda_nti_theta() == (math.log(1.0 / 0.9) / 0.10) ** 2
    assert FDA_NTI_CONSTANTS["variance_ratio_upper_limit"].value == 2.5
    assert FDA_NTI_CONSTANTS["unscaled_lower_percent"].value == 80.00
    assert FDA_NTI_CONSTANTS["unscaled_upper_percent"].value == 125.00

    for name, value in FDA_NTI_CONSTANTS.items():
        assert value.citation.authority == "FDA", name
        assert value.citation.document_version == "final, May 2026", name
        assert value.verification is VerificationStatus.VERIFIED, name


def test_the_variability_alpha_is_a_cited_constant_and_not_a_literal():
    alpha = FDA_NTI_CONSTANTS["variability_ci_alpha"]
    assert alpha.value == 0.10
    assert VARIABILITY_ALPHA == alpha.value
    assert "steps 4-5" in alpha.citation.section

    record = constant("FDA_NTI_VARIABILITY_CI_ALPHA")
    assert record.kind is ConstantKind.NORMATIVE
    assert "FDA_NTI_VARIABILITY_RATIO" in record.consumed_by
    assert record not in unpinned_normative_constants()


def test_nti_module_declares_no_regulatory_number_as_a_literal():
    """Section 12: every Appendix F number is read from the constants.

    Checked on the AST, so a docstring that MENTIONS 2.500 or 1.11111 is fine
    and a float literal that USES one is not.
    """
    forbidden = (0.10, 2.5, 1.0 / 0.9, 1.11111, 0.9, 0.8, 1.25, 80.0, 125.0, 0.95, 0.05)
    source = Path(inspect.getfile(nti)).read_text(encoding="utf-8")
    offenders = [
        f"{node.value!r} at line {node.lineno}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and any(abs(node.value - f) < 1e-9 for f in forbidden)
    ]
    assert not offenders, ", ".join(offenders)


# ======================================================== the study level ===


def test_the_study_passes_observations_through_per_endpoint():
    """A CORRECTION: `assess_nti_study` used to decide nothing, ever."""
    auc_rows = rows(0.10, 0.11, 3, endpoint="AUC")
    cmax_rows = rows(0.10, 0.11, 9, endpoint="Cmax")
    results = assess_nti_study(
        {"AUC": dataset(auc_rows), "Cmax": dataset(cmax_rows)},
        observations={"AUC": auc_rows},
        nti_status=NTI,
    )

    assert results["AUC"].unscaled_abe_criterion.computed is True
    assert results["AUC"].decided is True
    assert results["Cmax"].unscaled_abe_criterion.computed is False
    assert results["Cmax"].decided is False


def test_applicability_is_the_same_for_every_endpoint_of_one_product():
    results = assess_nti_study(
        {
            "AUC": dataset(rows(0.10, 0.11, 3, endpoint="AUC")),
            "Cmax": dataset(rows(0.10, 0.40, 9, endpoint="Cmax")),
        },
        nti_status=NON_NTI,
    )
    for endpoint, result in results.items():
        assert result.applicability is NtiApplicability.NOT_APPLICABLE_NOT_NTI, endpoint
        assert result.passes is None, endpoint


# ========================================================= explainability ===


def test_a_decided_result_reads_top_to_bottom(decided):
    summary = decided.summary()
    for fragment in (
        "Product class: NTI — FDA Appendix F applicable.",
        "Design: fully replicate (TRTR / RTRT) — acceptable under III.B.",
        "criterion a:",
        "criterion b:",
        "90% CI = [",
        "criterion c:",
        "Final decision:",
    ):
        assert fragment in summary, fragment
    # In that order.
    positions = [summary.index(f) for f in ("Product class", "Design:", "criterion a:", "criterion b:", "criterion c:", "Final decision:")]
    assert positions == sorted(positions)


def test_the_final_sentence_names_the_failing_criterion():
    assert "FAIL because criterion b failed" in _built(b=False).summary()
    assert "PASS only because criteria a, b and c all passed." in _built().summary()
    undecided = _built(
        decided=False, unscaled_abe_criterion=_unscaled(0.0, 0.0, computed=False)
    )
    assert "NOT DECIDED - criterion b could not be evaluated" in undecided.summary()


@pytest.mark.parametrize("status", [NON_NTI, NtiStatus.NOT_STATED])
def test_a_refusal_leads_with_the_refusal_and_shows_no_criterion(status):
    result = assess_nti_endpoint(dataset(rows(0.10, 0.11, 3)), nti_status=status)
    lines = result.provenance()
    summary = result.summary()

    assert lines[0].startswith(("FDA NTI procedure not applicable", "FDA NTI applicability cannot be determined"))
    assert "DESCRIPTIVE ONLY" in " ".join(lines)
    assert "NO BE DECISION ISSUED" in summary
    assert "criterion a" not in summary
    assert "Final decision" not in summary


def test_a_decided_result_cites_appendix_f_and_never_appendix_g(decided):
    text = " ".join(decided.provenance())
    assert "applicability rule" in text
    assert "Appendix F" in text
    assert "Appendix G (highly variable drugs)" not in text
    assert {c.section for c in decided.regulatory_basis} >= {
        "III.B (statistical method for narrow therapeutic index drugs)"
    }


# ============================================== PR #82 is not regressed ===


def test_the_hvd_gate_still_refuses_an_nti_product_and_admits_a_non_nti_one():
    """The reconciliation is shared, so the HVD behaviour is pinned here too."""
    partial = dataset(rows(0.45, 0.45, 11, labels=PARTIAL, n_per_sequence=8))
    assert (
        hvd.assess_endpoint(partial, nti_status=NTI).applicability
        is HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX
    )
    assert (
        hvd.assess_endpoint(partial, nti_status=NON_NTI).applicability
        is HvdApplicability.APPLICABLE
    )
    assert (
        hvd.assess_endpoint(partial).applicability
        is HvdApplicability.UNDETERMINED_NTI_NOT_STATED
    )
