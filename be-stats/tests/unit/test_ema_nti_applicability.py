"""EMA 4.1.9: to whom it applies, which interval, and what it must refuse.

WHAT THESE TESTS ARE FOR

Section 4.1.9 is three sentences and three separate questions, and the failure
mode this file exists to prevent is any two of them collapsing into one:

    the product is an NTID            ->  a clinical decision, case by case,
                                          with NO numerical criteria
    AUC is tightened                  ->  follows from the class alone
    Cmax is tightened                 ->  only where Cmax ITSELF is of
                                          particular importance - a second
                                          product fact

EWP answered the third question in opposite directions for two confirmed NTIDs
in one document, which is the whole reason no default is acceptable:

    ciclosporin   "for which both AUC and Cmax are important for safety and
                  efficacy, a narrowed (90.00-111.11%) acceptance range should
                  be applied for both AUC and Cmax"
    tacrolimus    "[90-111%] for AUC and [80-125%] for Cmax"

Both are EMA/618604/2008 Rev. 13. A package that defaulted either way would be
wrong for a real EMA product.
"""

from __future__ import annotations

import ast
import inspect
import math
import random
import textwrap

import pytest

from be_stats import ema_nti
from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.ema_nti import (
    CROSSOVER_MODEL,
    PARALLEL_MODEL,
    EmaNtiResult,
    EmaNtiResultInconsistent,
    assess_ema_nti_endpoint,
)
from be_stats.regulatory_rounding import round_half_up
from be_stats.spec import (
    CAPABILITY_VALIDATION,
    VALIDATION,
    Capability,
    CmaxClinicalImportance,
    ContradictoryProductClass,
    DrugClass,
    EmaNtiIntervalStatus,
    EmaNtiProductClass,
    Endpoint,
    Jurisdiction,
    Method,
    NotApplicable,
    NotImplementedMethod,
    NtiStatus,
    ProductOverride,
    ValidationStatus,
    ema_nti_interval,
    ema_nti_limits,
    ema_nti_product_class,
    resolve_be_spec,
)
from be_stats.study import CrossoverObservation, CrossoverStudy, ParallelStudy, Sequence

NARROWED = (90.00, 111.11)
CONVENTIONAL = (80.00, 125.00)

NTI = NtiStatus.NARROW_THERAPEUTIC_INDEX
NOT_NTI = NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX
UNSTATED = NtiStatus.NOT_STATED

IMPORTANT = CmaxClinicalImportance.IMPORTANT
NOT_IMPORTANT = CmaxClinicalImportance.NOT_IMPORTANT
IMPORTANCE_UNSTATED = CmaxClinicalImportance.NOT_STATED

#: EMA/618604/2008 Rev. 13, question 5. Both parameters narrowed.
CICLOSPORIN = ProductOverride(
    product="ciclosporin",
    limits={Endpoint.AUC: NARROWED, Endpoint.CMAX: NARROWED},
    citation="EMA/618604/2008 Rev. 13, question 5",
)
#: EMA/618604/2008 Rev. 13, question 4. AUC narrowed, Cmax conventional.
TACROLIMUS = ProductOverride(
    product="tacrolimus",
    limits={Endpoint.AUC: NARROWED, Endpoint.CMAX: CONVENTIONAL},
    citation="EMA/618604/2008 Rev. 13, question 4",
)


def study(endpoint: str = "AUC", *, ratio: float = 1.02, cv: float = 0.05, seed: int = 7):
    """A well-behaved 2x2 crossover, deterministic and comfortably inside."""
    rng = random.Random(seed)
    sigma = math.sqrt(math.log1p(cv**2))
    observations = []
    for k in range(12):
        sequence = Sequence.RT if k % 2 == 0 else Sequence.TR
        subject = math.exp(rng.gauss(0.0, 0.20))
        test = 1000.0 * subject * ratio * math.exp(rng.gauss(0.0, sigma))
        reference = 1000.0 * subject * math.exp(rng.gauss(0.0, sigma))
        first, second = (
            (reference, test) if sequence is Sequence.RT else (test, reference)
        )
        observations.append(
            CrossoverObservation(
                subject=f"S{k:02d}", sequence=sequence, period_1=first, period_2=second
            )
        )
    return CrossoverStudy(endpoint=endpoint, observations=observations)


def parallel_study(endpoint: str = "AUC"):
    rng = random.Random(11)
    return ParallelStudy(
        endpoint=endpoint,
        test=[1000.0 * math.exp(rng.gauss(0.0, 0.1)) for _ in range(20)],
        reference=[1000.0 * math.exp(rng.gauss(0.0, 0.1)) for _ in range(20)],
    )


# --------------------------------------------------- the product-class gate ---


@pytest.mark.parametrize(
    "status,expected",
    [
        (NTI, EmaNtiProductClass.CONFIRMED_NARROW_THERAPEUTIC_INDEX),
        (NOT_NTI, EmaNtiProductClass.NOT_NARROW_THERAPEUTIC_INDEX),
        (UNSTATED, EmaNtiProductClass.UNDETERMINED_NOT_STATED),
    ],
)
def test_the_product_class_is_read_and_never_derived(status, expected):
    assert ema_nti_product_class(status)[0] is expected


def test_an_unstated_class_gets_no_verdict_whatever_the_data_look_like():
    """4.1.9: 'it is not possible to define a set of criteria to categorise
    drugs as narrow therapeutic index drugs'. So there is nothing to infer from,
    and a tight interval on a low-variability study infers nothing either."""
    result = assess_ema_nti_endpoint(
        study(cv=0.02), endpoint=Endpoint.AUC, nti_status=UNSTATED
    )
    assert not result.decided
    assert result.passes is None
    assert result.selected_method is None
    assert result.applied_limits is None
    assert result.treatment is None
    codes = [d.code for d in result.diagnostics]
    assert codes == [DiagnosticCode.EMA_NTI_PRODUCT_CLASS_NOT_STATED]
    assert result.diagnostics[0].severity is Severity.FATAL


def test_a_product_stated_not_to_be_nti_gets_no_ema_nti_verdict():
    """Not a conventional one either. The conventional interval may well be
    right for the product; it reaches it through 4.1.8 and the standard route,
    which is a different method."""
    result = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=NOT_NTI
    )
    assert not result.decided
    assert result.applied_limits is None
    assert result.selected_method is None
    assert [d.code for d in result.diagnostics] == [
        DiagnosticCode.EMA_NTI_NOT_APPLICABLE
    ]


@pytest.mark.parametrize("drug_class", [DrugClass.STANDARD, DrugClass.HIGHLY_VARIABLE])
def test_a_non_nti_class_denies_the_narrowed_interval(drug_class):
    """A standard or highly variable product does not collect 4.1.9's interval.

    Both routes are closed: the class those specs carry is an assertion of
    non-NTI, and asserting it directly gets no verdict either.
    """
    from be_stats.spec import nti_status_from_drug_class

    assert nti_status_from_drug_class(drug_class) is NOT_NTI

    result = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=NOT_NTI
    )
    assert result.applied_limits is None
    assert result.selected_method is None


def test_two_sources_that_disagree_about_the_class_refuse_rather_than_choose():
    """PR #83's rule, reused: `reconcile_nti_status` raises rather than
    preferring the spec or the metadata."""
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    with pytest.raises(ContradictoryProductClass):
        assess_ema_nti_endpoint(
            study(), endpoint=Endpoint.AUC, spec=spec, nti_status=NOT_NTI
        )


def test_a_routed_nti_spec_is_an_explicit_classification():
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    result = assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, spec=spec)
    assert result.product_class is EmaNtiProductClass.CONFIRMED_NARROW_THERAPEUTIC_INDEX
    assert result.applied_limits == NARROWED
    assert result.decided


def test_the_class_is_not_inferred_from_variability_or_monitoring():
    """Two inputs that look like evidence of a narrow therapeutic index and are
    not: a very low within-subject CV, and a product whose Cmax is declared
    important for drug level monitoring. Neither classifies the drug."""
    low_cv = assess_ema_nti_endpoint(
        study("Cmax", cv=0.01), endpoint=Endpoint.CMAX, nti_status=UNSTATED
    )
    monitored = assess_ema_nti_endpoint(
        study("Cmax"),
        endpoint=Endpoint.CMAX,
        nti_status=UNSTATED,
        cmax_importance=IMPORTANT,
    )
    for result in (low_cv, monitored):
        assert not result.decided
        assert [d.code for d in result.diagnostics] == [
            DiagnosticCode.EMA_NTI_PRODUCT_CLASS_NOT_STATED
        ]


# ------------------------------------------------------ the decision table ---


DECISION_TABLE = [
    ("NTI / AUC", NTI, Endpoint.AUC, IMPORTANCE_UNSTATED, NARROWED),
    ("NTI / AUC / importance stated", NTI, Endpoint.AUC, IMPORTANT, NARROWED),
    ("NTI / AUC / not important", NTI, Endpoint.AUC, NOT_IMPORTANT, NARROWED),
    ("NTI / Cmax important", NTI, Endpoint.CMAX, IMPORTANT, NARROWED),
    ("NTI / Cmax not important", NTI, Endpoint.CMAX, NOT_IMPORTANT, CONVENTIONAL),
    ("NTI / Cmax unstated", NTI, Endpoint.CMAX, IMPORTANCE_UNSTATED, None),
    ("NTI / other", NTI, Endpoint.OTHER, IMPORTANT, None),
    ("not NTI / AUC", NOT_NTI, Endpoint.AUC, IMPORTANCE_UNSTATED, None),
    ("not NTI / Cmax important", NOT_NTI, Endpoint.CMAX, IMPORTANT, None),
    ("unstated class / AUC", UNSTATED, Endpoint.AUC, IMPORTANCE_UNSTATED, None),
    ("unstated class / Cmax", UNSTATED, Endpoint.CMAX, IMPORTANT, None),
]


@pytest.mark.parametrize(
    "label,status,endpoint,importance,expected", DECISION_TABLE,
    ids=[row[0] for row in DECISION_TABLE],
)
def test_the_decision_table(label, status, endpoint, importance, expected):
    result = assess_ema_nti_endpoint(
        study("Cmax" if endpoint is Endpoint.CMAX else "AUC"),
        endpoint=endpoint,
        nti_status=status,
        cmax_importance=importance,
    )
    assert result.applied_limits == expected, label
    assert result.decided is (expected is not None), label
    if expected is None:
        assert result.passes is None
        assert result.selected_method is None
        assert any(d.severity is Severity.FATAL for d in result.diagnostics)
    else:
        assert result.passes in (True, False)
        assert result.selected_method is Method.EMA_NTI_NARROW_ABE


def test_the_auc_interval_does_not_move_with_the_cmax_fact():
    """4.1.9 tightens AUC on the class alone. A Cmax judgement that could move
    the AUC interval would be one product question answered with another's."""
    limits = {
        importance: assess_ema_nti_endpoint(
            study(), endpoint=Endpoint.AUC, nti_status=NTI, cmax_importance=importance
        ).applied_limits
        for importance in CmaxClinicalImportance
    }
    assert set(limits.values()) == {NARROWED}


def test_an_endpoint_the_guideline_does_not_address_is_refused():
    result = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.OTHER, nti_status=NTI
    )
    assert not result.decided
    assert result.applied_limits is None
    assert [d.code for d in result.diagnostics] == [
        DiagnosticCode.EMA_NTI_ENDPOINT_NOT_COVERED
    ]


def test_aucs_rule_is_not_borrowed_for_another_endpoint():
    """The refusal above must not be an accident of ordering: OTHER is refused
    even when the general rule for AUC would have narrowed."""
    status, _ = ema_nti_interval(
        endpoint=Endpoint.OTHER,
        product_class=EmaNtiProductClass.CONFIRMED_NARROW_THERAPEUTIC_INDEX,
        cmax_importance=IMPORTANT,
    )
    assert status is EmaNtiIntervalStatus.UNDETERMINED_ENDPOINT_NOT_COVERED
    assert ema_nti_limits(status) is None


# ------------------------------------------- product-specific guidance ---
#
# The two EWP answers, expressed through the same engine and the same rule,
# with the difference carried entirely by the product fact.


def test_the_two_published_products_get_their_published_intervals():
    ciclosporin = {
        endpoint: assess_ema_nti_endpoint(
            study("Cmax" if endpoint is Endpoint.CMAX else "AUC"),
            endpoint=endpoint,
            nti_status=NTI,
            cmax_importance=IMPORTANT,
        ).applied_limits
        for endpoint in (Endpoint.AUC, Endpoint.CMAX)
    }
    tacrolimus = {
        endpoint: assess_ema_nti_endpoint(
            study("Cmax" if endpoint is Endpoint.CMAX else "AUC"),
            endpoint=endpoint,
            nti_status=NTI,
            cmax_importance=NOT_IMPORTANT,
        ).applied_limits
        for endpoint in (Endpoint.AUC, Endpoint.CMAX)
    }
    assert ciclosporin == {Endpoint.AUC: NARROWED, Endpoint.CMAX: NARROWED}
    assert tacrolimus == {Endpoint.AUC: NARROWED, Endpoint.CMAX: CONVENTIONAL}
    assert ciclosporin != tacrolimus, "a universal Cmax constant would be wrong for one"


@pytest.mark.parametrize(
    "override,expected",
    [(CICLOSPORIN, NARROWED), (TACROLIMUS, CONVENTIONAL)],
    ids=["ciclosporin", "tacrolimus"],
)
def test_product_specific_guidance_supplies_the_cmax_answer(override, expected):
    """A document EMA published is an answer to 4.1.9's Cmax question, so it
    settles an importance the caller did not state."""
    result = assess_ema_nti_endpoint(
        study("Cmax"),
        endpoint=Endpoint.CMAX,
        nti_status=NTI,
        cmax_importance=IMPORTANCE_UNSTATED,
        product=override,
    )
    assert result.applied_limits == expected
    assert result.decided
    assert override.product in result.interval_source


def test_product_specific_guidance_cannot_classify_the_product():
    """It settles WHICH numbers apply within 4.1.9, not whether 4.1.9 applies.
    Limits supplied for a drug nobody classified decide nothing."""
    for status in (UNSTATED, NOT_NTI):
        result = assess_ema_nti_endpoint(
            study("Cmax"),
            endpoint=Endpoint.CMAX,
            nti_status=status,
            product=CICLOSPORIN,
        )
        assert not result.decided
        assert result.applied_limits is None


def test_supplied_limits_that_contradict_the_stated_importance_are_refused():
    result = assess_ema_nti_endpoint(
        study("Cmax"),
        endpoint=Endpoint.CMAX,
        nti_status=NTI,
        cmax_importance=IMPORTANT,
        product=TACROLIMUS,
    )
    assert not result.decided
    assert result.applied_limits is None
    assert [d.code for d in result.diagnostics] == [
        DiagnosticCode.EMA_NTI_PRODUCT_LIMITS_CONFLICT
    ]


def test_a_third_interval_from_a_product_document_is_not_a_contradiction():
    """Product-specific guidance outranks the general rule; a pair that is
    neither canonical is what that provision is for."""
    other = ProductOverride(
        product="example", limits={Endpoint.CMAX: (85.00, 117.65)}, citation="example"
    )
    result = assess_ema_nti_endpoint(
        study("Cmax"),
        endpoint=Endpoint.CMAX,
        nti_status=NTI,
        cmax_importance=IMPORTANT,
        product=other,
    )
    assert result.applied_limits == (85.00, 117.65)
    assert result.decided


def test_product_guidance_settles_an_endpoint_the_guideline_does_not_address():
    other = ProductOverride(
        product="example", limits={Endpoint.OTHER: NARROWED}, citation="example"
    )
    result = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.OTHER, nti_status=NTI, product=other
    )
    assert result.decided
    assert result.applied_limits == NARROWED


def test_guidance_for_another_endpoint_does_not_reach_this_one():
    result = assess_ema_nti_endpoint(
        study("Cmax"),
        endpoint=Endpoint.CMAX,
        nti_status=NTI,
        product=ProductOverride(
            product="example", limits={Endpoint.AUC: NARROWED}, citation="example"
        ),
    )
    assert not result.decided
    assert [d.code for d in result.diagnostics] == [
        DiagnosticCode.EMA_NTI_CMAX_IMPORTANCE_NOT_STATED
    ]


# ------------------------------------------------------------- the limits ---


def test_the_narrowed_limits_are_the_published_pair():
    """90.00 and 111.11 as EMA prints them. NOT 1/0.9."""
    assert ema_nti_limits(EmaNtiIntervalStatus.NARROWED) == (90.00, 111.11)
    assert ema_nti_limits(EmaNtiIntervalStatus.NARROWED)[1] != pytest.approx(
        100.0 / 0.9, abs=1e-9
    )
    assert ema_nti_limits(EmaNtiIntervalStatus.CONVENTIONAL) == (80.00, 125.00)
    for status in EmaNtiIntervalStatus:
        if not status.determined:
            assert ema_nti_limits(status) is None


def test_the_reciprocal_is_not_the_regulatory_upper_limit():
    """100/0.9 = 111.111..., which is not what EMA published.

    The two agree to within the rounding, which is exactly why the difference
    has to be asserted on the CONSTANT rather than on a decision: a bound at
    111.12% is outside the interval EMA states and inside a reciprocal nobody
    stated, and only the first is the rule.
    """
    _, upper = ema_nti_limits(EmaNtiIntervalStatus.NARROWED)
    assert upper == 111.11
    assert upper != 100.0 / 0.9
    assert not ema_nti._interval_contained(
        ci_lower_percent=95.0, ci_upper_percent=111.12, lower=90.00, upper=upper
    )


BOUNDARY_CASES = [
    # (label, ci_lower, ci_upper, limits, expected)
    ("narrowed, exactly on both", 90.00, 111.11, NARROWED, True),
    ("narrowed, just inside", 90.01, 111.10, NARROWED, True),
    ("narrowed, lower just outside", 89.99, 111.00, NARROWED, False),
    ("narrowed, upper just outside", 90.10, 111.12, NARROWED, False),
    # 4.1.8's rounding, applied to the tightened interval: VAL-EMA-NTI-001.
    ("narrowed, lower rounds up onto 90.00", 89.995, 111.00, NARROWED, True),
    ("narrowed, lower rounds below 90.00", 89.9949, 111.00, NARROWED, False),
    ("narrowed, upper rounds down onto 111.11", 95.00, 111.1149, NARROWED, True),
    ("narrowed, upper rounds above 111.11", 95.00, 111.115, NARROWED, False),
    ("conventional, exactly on both", 80.00, 125.00, CONVENTIONAL, True),
    ("conventional, lower just outside", 79.99, 120.00, CONVENTIONAL, False),
    ("conventional, upper just outside", 85.00, 125.01, CONVENTIONAL, False),
    ("conventional, lower rounds up onto 80.00", 79.995, 120.00, CONVENTIONAL, True),
    ("conventional, upper rounds down onto 125.00", 85.00, 125.0049, CONVENTIONAL, True),
]


@pytest.mark.parametrize(
    "label,lower,upper,limits,expected", BOUNDARY_CASES,
    ids=[row[0] for row in BOUNDARY_CASES],
)
def test_the_boundary_behaviour(label, lower, upper, limits, expected):
    assert (
        ema_nti._interval_contained(
            ci_lower_percent=lower, ci_upper_percent=upper,
            lower=limits[0], upper=limits[1],
        )
        is expected
    ), label


def test_the_comparison_uses_the_one_rounding_helper():
    """Not a second implementation, and not a formatted string. The package has
    exactly one rounding helper and this module is a caller of it."""
    source = inspect.getsource(ema_nti)
    assert "from be_stats.regulatory_rounding import" in source
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "round_half_up" in called
    assert "round" not in called, "binary round() is not the regulatory rule"
    assert round_half_up(89.995) == round_half_up(89.995)


def test_the_verdict_a_result_carries_is_the_one_its_own_interval_gives():
    for importance, limits in ((IMPORTANT, NARROWED), (NOT_IMPORTANT, CONVENTIONAL)):
        result = assess_ema_nti_endpoint(
            study("Cmax"),
            endpoint=Endpoint.CMAX,
            nti_status=NTI,
            cmax_importance=importance,
        )
        assert result.applied_limits == limits
        assert result.passes is ema_nti._interval_contained(
            ci_lower_percent=result.treatment.ci_lower,
            ci_upper_percent=result.treatment.ci_upper,
            lower=limits[0],
            upper=limits[1],
        )


def test_a_study_outside_the_narrowed_interval_but_inside_the_conventional_one():
    """The case the whole section exists for: the same data, the same model,
    two answers, because the interval moved."""
    wide = study("Cmax", ratio=1.12, cv=0.10, seed=3)
    narrowed = assess_ema_nti_endpoint(
        wide, endpoint=Endpoint.CMAX, nti_status=NTI, cmax_importance=IMPORTANT
    )
    conventional = assess_ema_nti_endpoint(
        wide, endpoint=Endpoint.CMAX, nti_status=NTI, cmax_importance=NOT_IMPORTANT
    )
    assert narrowed.treatment.ci_lower == conventional.treatment.ci_lower
    assert narrowed.treatment.ci_upper == conventional.treatment.ci_upper
    assert narrowed.passes is False
    assert conventional.passes is True
    assert narrowed.selected_method is conventional.selected_method


# ------------------------------------------------ designs and the model ---


def test_the_supported_designs_run_and_name_their_model():
    crossover = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=NTI
    )
    parallel = assess_ema_nti_endpoint(
        parallel_study(), endpoint=Endpoint.AUC, nti_status=NTI
    )
    assert crossover.design == "2x2 crossover"
    assert crossover.analysis_model == CROSSOVER_MODEL
    assert parallel.design == "parallel"
    assert parallel.analysis_model == PARALLEL_MODEL
    assert crossover.applied_limits == parallel.applied_limits == NARROWED


def test_the_crossover_model_is_the_one_m13a_asks_for():
    """M13A 2.2.3.2 asks for a GLM with 'sequence, subject within sequence,
    period, and formulation' effects. The model is named on the result rather
    than left to be inferred from which function was called."""
    for term in ("sequence", "subject(sequence)", "period", "formulation"):
        assert term in CROSSOVER_MODEL
    assert "M13A" in CROSSOVER_MODEL
    assert "M13A" in PARALLEL_MODEL


def test_a_replicate_design_is_refused_rather_than_borrowed():
    """4.1.9 states an interval and no replicate model. FDA's Appendix C model
    is another regulator's specification for another procedure, and EMA's
    Method A belongs to 4.1.10."""
    from be_stats.replicate import ReplicateObservation, parse_sequence

    rows = [
        ReplicateObservation(
            "S1", parse_sequence("TRR"), period, parse_sequence("TRR").expected_treatment(period),
            "AUC", 100.0,
        )
        for period in (1, 2, 3)
    ]
    with pytest.raises(NotImplementedMethod, match="replicate"):
        assess_ema_nti_endpoint(rows, endpoint=Endpoint.AUC, nti_status=NTI)


def test_no_appendix_c_or_method_a_model_can_reach_this_module():
    """Structurally, over the syntax tree. A text search would match this
    file's own prose and the module's docstring, which says the models are
    absent while naming them."""
    tree = ast.parse(inspect.getsource(ema_nti))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "be_stats.appendix_c" not in imported
    assert "be_stats.replicate_abe" not in imported
    assert "be_stats.ema_hvd" not in imported
    assert "be_stats.nti" not in imported
    assert "be_stats.hvd" not in imported


# ---------------------------------------------- EMA NTI is not FDA NTI ---


def test_no_fda_appendix_f_quantity_enters_this_module():
    """FDA assesses an NTI drug with a scaled criterion, an unscaled criterion
    and a variability comparison, all three of which must hold. EMA moves the
    limits. Checked over the syntax tree, on names actually referenced."""
    tree = ast.parse(inspect.getsource(ema_nti))
    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in (
        "fda_nti_theta",
        "fda_nti_theta_sas_example",
        "sigma_w0",
        "scaled_mean_criterion",
        "variability_ratio_criterion",
        "assess_nti_endpoint",
        "howe_upper_bound",
    ):
        assert forbidden not in referenced, forbidden


def test_the_two_nti_methods_are_separate_members_with_separate_statuses():
    assert Method.EMA_NTI_NARROW_ABE is not Method.FDA_NTI_RSABE
    assert VALIDATION[Method.EMA_NTI_NARROW_ABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    result = assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, nti_status=NTI)
    assert result.selected_method is not Method.FDA_NTI_RSABE


def test_another_routes_spec_is_refused_rather_than_reconciled():
    for jurisdiction, drug_class in (
        (Jurisdiction.FDA, DrugClass.NARROW_THERAPEUTIC_INDEX),
        (Jurisdiction.EMA, DrugClass.HIGHLY_VARIABLE),
        (Jurisdiction.EMA, DrugClass.STANDARD),
    ):
        spec = resolve_be_spec(
            jurisdiction=jurisdiction, drug_class=drug_class, endpoint=Endpoint.AUC
        )
        with pytest.raises(NotApplicable):
            assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, spec=spec)


def test_a_spec_for_another_endpoint_is_refused():
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    with pytest.raises(NotApplicable, match="per endpoint"):
        assess_ema_nti_endpoint(study("Cmax"), endpoint=Endpoint.CMAX, spec=spec)


# ------------------------------------------------------ method identity ---


def test_the_method_is_the_procedure_and_not_the_width_of_the_interval():
    """The defect PR #85 corrected on the highly variable path. A confirmed NTI
    drug whose Cmax takes 80.00-125.00% was still decided under 4.1.9."""
    conventional = assess_ema_nti_endpoint(
        study("Cmax"), endpoint=Endpoint.CMAX, nti_status=NTI,
        cmax_importance=NOT_IMPORTANT,
    )
    assert conventional.applied_limits == CONVENTIONAL
    assert conventional.selected_method is Method.EMA_NTI_NARROW_ABE
    assert conventional.selected_method is not Method.STANDARD_ABE


def test_selected_method_reads_decided_and_nothing_else():
    """Structurally. The property must not consult the applied limits, the
    interval status or the product class - deriving the method from the
    interval is the defect, and a docstring saying so is not a guarantee."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(EmaNtiResult.selected_method.fget)))
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert read == {"decided"}


def test_a_refusal_carries_no_method():
    result = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=UNSTATED
    )
    assert result.selected_method is None


def test_the_router_and_the_result_agree_on_the_method():
    for endpoint, importance in (
        (Endpoint.AUC, IMPORTANCE_UNSTATED),
        (Endpoint.CMAX, IMPORTANT),
    ):
        spec = resolve_be_spec(
            jurisdiction=Jurisdiction.EMA,
            drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
            endpoint=endpoint,
            product=CICLOSPORIN if endpoint is Endpoint.CMAX else None,
        )
        result = assess_ema_nti_endpoint(
            study("Cmax" if endpoint is Endpoint.CMAX else "AUC"),
            endpoint=endpoint,
            spec=spec,
            cmax_importance=importance,
        )
        assert spec.method is Method.EMA_NTI_NARROW_ABE
        assert result.selected_method is spec.method


# ------------------------------------------------------ result invariants ---


def _decided() -> EmaNtiResult:
    return assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, nti_status=NTI)


def _replace(result: EmaNtiResult, **changes) -> EmaNtiResult:
    import dataclasses

    return dataclasses.replace(result, **changes)


def test_a_non_nti_product_cannot_carry_a_narrowed_result():
    with pytest.raises(EmaNtiResultInconsistent):
        _replace(
            _decided(),
            nti_status=NOT_NTI,
            product_class=EmaNtiProductClass.NOT_NARROW_THERAPEUTIC_INDEX,
            interval_status=EmaNtiIntervalStatus.NOT_APPLICABLE_NOT_NTI,
        )


def test_an_unstated_class_cannot_carry_a_decision():
    with pytest.raises(EmaNtiResultInconsistent):
        _replace(
            _decided(),
            nti_status=UNSTATED,
            product_class=EmaNtiProductClass.UNDETERMINED_NOT_STATED,
            interval_status=EmaNtiIntervalStatus.UNDETERMINED_CLASS_NOT_DETERMINED,
        )


def test_a_product_class_that_contradicts_its_own_status_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="contradicts"):
        _replace(_decided(), product_class=EmaNtiProductClass.NOT_NARROW_THERAPEUTIC_INDEX)


def test_a_spec_class_that_contradicts_the_status_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="drug_class"):
        _replace(_decided(), spec_drug_class=DrugClass.HIGHLY_VARIABLE)


def test_an_unstated_cmax_importance_cannot_carry_either_verdict():
    cmax = assess_ema_nti_endpoint(
        study("Cmax"), endpoint=Endpoint.CMAX, nti_status=NTI, cmax_importance=IMPORTANT
    )
    with pytest.raises(EmaNtiResultInconsistent, match="contradicts the rule"):
        _replace(cmax, cmax_importance=IMPORTANCE_UNSTATED)


def test_an_interval_status_the_rule_would_not_give_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="contradicts the rule"):
        _replace(_decided(), interval_status=EmaNtiIntervalStatus.CONVENTIONAL)


def test_limits_that_are_not_the_selected_interval_are_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="general rule"):
        _replace(_decided(), applied_limits=CONVENTIONAL)


def test_a_decision_without_a_contrast_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="no treatment contrast"):
        _replace(_decided(), treatment=None)


def test_a_verdict_that_its_own_interval_denies_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="passes="):
        _replace(_decided(), passes=not _decided().passes)


def test_an_undecided_result_cannot_carry_a_verdict():
    refusal = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=UNSTATED
    )
    with pytest.raises(EmaNtiResultInconsistent):
        _replace(refusal, passes=True)


def test_a_refusal_without_a_fatal_diagnostic_is_refused():
    refusal = assess_ema_nti_endpoint(
        study(), endpoint=Endpoint.AUC, nti_status=UNSTATED
    )
    with pytest.raises(EmaNtiResultInconsistent, match="FATAL"):
        _replace(refusal, diagnostics=())


def test_a_result_built_for_another_methods_spec_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="EMA_NTI_NARROW_ABE only"):
        _replace(_decided(), spec_method=Method.FDA_NTI_RSABE)
    with pytest.raises(EmaNtiResultInconsistent, match="EMA_NTI_NARROW_ABE only"):
        _replace(_decided(), spec_method=Method.EMA_HVD_ABEL)


def test_a_model_this_module_does_not_analyse_with_is_refused():
    with pytest.raises(EmaNtiResultInconsistent, match="model"):
        _replace(_decided(), analysis_model="EMA Method A")
    with pytest.raises(EmaNtiResultInconsistent, match="do not correspond"):
        _replace(_decided(), design="parallel")


def test_a_bare_flag_is_refused_where_a_stated_fact_is_required():
    for bad in (True, False, "important", 1):
        with pytest.raises(TypeError):
            ema_nti_interval(
                endpoint=Endpoint.CMAX,
                product_class=EmaNtiProductClass.CONFIRMED_NARROW_THERAPEUTIC_INDEX,
                cmax_importance=bad,
            )
        with pytest.raises(TypeError):
            ema_nti_product_class(bad)


# ------------------------------------------------------- explainability ---


def test_the_explanation_names_every_fact_the_verdict_rests_on():
    result = assess_ema_nti_endpoint(
        study("Cmax"), endpoint=Endpoint.CMAX, nti_status=NTI, cmax_importance=IMPORTANT
    )
    text = "\n".join(result.explain())
    assert "Regulator: EMA" in text
    assert "confirmed_narrow_therapeutic_index" in text
    assert "Endpoint: Cmax" in text
    assert "Cmax importance: important" in text
    assert "90.00-111.11%" in text
    assert "M13A" in text
    assert "90% CI:" in text
    assert "Final decision:" in text
    assert "ema_nti_narrow_abe" in text


def test_an_unstated_cmax_importance_explains_what_was_missing():
    result = assess_ema_nti_endpoint(
        study("Cmax"), endpoint=Endpoint.CMAX, nti_status=NTI
    )
    text = "\n".join(result.explain())
    assert "NO EMA NTI DECISION ISSUED" in text
    assert "particular importance" in text
    assert "Applicable interval: NOT SELECTED" in text


def test_the_provenance_names_both_live_documents():
    result = assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, nti_status=NTI)
    text = "\n".join(result.provenance_lines)
    assert "4.1.9" in text
    assert "4.1.8" in text
    assert "M13A" in text
    assert "EMA/531548/2024" in text
    assert "case by case" in text


# --------------------------------------------------------- governance ---


def test_the_method_and_its_capabilities_keep_their_statuses():
    assert VALIDATION[Method.EMA_NTI_NARROW_ABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert (
        CAPABILITY_VALIDATION[Capability.EMA_NTI_ENDPOINT_DECISION]
        is ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    for gate in (
        Capability.EMA_NTI_PRODUCT_CLASS_GATE,
        Capability.EMA_NTI_CMAX_IMPORTANCE_GATE,
    ):
        assert CAPABILITY_VALIDATION[gate] is ValidationStatus.IMPLEMENTED


def test_a_result_reports_its_own_unvalidated_status():
    result = assess_ema_nti_endpoint(study(), endpoint=Endpoint.AUC, nti_status=NTI)
    assert result.validation_status is ValidationStatus.IMPLEMENTED_UNVALIDATED


def test_the_capability_endpoint_scope_matches_what_the_rule_decides():
    from be_stats.dossier.capabilities import CAPABILITY_MATRIX

    decided = {
        endpoint
        for endpoint in Endpoint
        if ema_nti_interval(
            endpoint=endpoint,
            product_class=EmaNtiProductClass.CONFIRMED_NARROW_THERAPEUTIC_INDEX,
            cmax_importance=IMPORTANT,
        )[0].determined
    }
    for capability_id in ("EMA_NTI_NARROW_ABE", "EMA_NTI_ENDPOINT_DECISION"):
        assert set(CAPABILITY_MATRIX[capability_id].endpoints) == decided, capability_id
    assert set(CAPABILITY_MATRIX["EMA_NTI_CMAX_IMPORTANCE_GATE"].endpoints) == {
        Endpoint.CMAX
    }


def test_the_capability_rows_claim_only_the_designs_that_run():
    from be_stats.dossier.capabilities import CAPABILITY_MATRIX
    from be_stats.minimums import DesignFamily

    for capability_id in (
        "EMA_NTI_NARROW_ABE",
        "EMA_NTI_ENDPOINT_DECISION",
        "EMA_NTI_PRODUCT_CLASS_GATE",
        "EMA_NTI_CMAX_IMPORTANCE_GATE",
    ):
        row = CAPABILITY_MATRIX[capability_id]
        assert set(row.design_requirement) == {
            DesignFamily.CROSSOVER,
            DesignFamily.PARALLEL,
        }, capability_id
        assert DesignFamily.REPLICATE not in row.design_requirement


def test_the_open_finding_is_recorded_and_still_open():
    from be_stats.dossier.findings import FINDINGS, FindingStatus

    finding = FINDINGS["VAL-EMA-NTI-001"]
    assert finding.status is FindingStatus.OPEN
    assert "EMA_NTI_NARROW_ABE" in finding.affected_capabilities


def test_the_tier_1b_search_adopted_nothing():
    from be_stats.dossier.evidence_search import (
        EMA_NTI_TIER_1B_SEARCH,
        SearchVerdict,
        adopted_sources,
    )

    assert EMA_NTI_TIER_1B_SEARCH
    assert list(adopted_sources(EMA_NTI_TIER_1B_SEARCH)) == []
    qa = next(
        s for s in EMA_NTI_TIER_1B_SEARCH if "Pharmacokinetics Working Party" in s.document
    )
    assert qa.verdict is SearchVerdict.NUMBERS_OUT_OF_SCOPE
    assert "Limits, not results" in qa.rejected_because
