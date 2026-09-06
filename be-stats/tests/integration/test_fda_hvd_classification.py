"""Classifying the DRUG, and never routing the ANALYSIS with it.

WHAT THIS FILE EXISTS BECAUSE OF

`FDA_HVD_CLASSIFICATION_CV` - FDA's 30 percent definition of a highly variable
drug - was recorded in `spec.py` with a citation to III.C, indexed in the
constants register, asserted by three tests to be a different number from the
switching threshold, and CONSUMED BY NOTHING. The constants register said so in
its own machinery: `consumed_by=()`.

So the package could state the definition and could not apply it. Every report
it produced named the analysis that ran and never said whether the drug was
highly variable, which is the first question a reader asks.

THE TWO RULES, AND THE WINDOW WHERE THEY DISAGREE

    III.C definition   CVwR >= 30%, AND not an NTI drug     -> the DRUG
    III.C / App. G     sWR  >= 0.294                        -> the ANALYSIS

CVwR >= 30% is exactly sWR >= sqrt(ln(1 + 0.30^2)) = 0.293560..., so every
study whose estimated sWR lands in [0.293560, 0.294) is a highly variable drug
analysed by ordinary average BE. The window is four ten-thousandths wide and it
is not empty, and `test_the_two_rules_disagree_on_a_real_dataset` builds a
dataset inside it.

The other direction cannot happen, and that asymmetry is asserted rather than
assumed: the CV-to-sWR map is monotone, so an sWR at or above 0.294 always
carries a CVwR above 30%.

THE SHAPE OF THE RISK

Not that the classification is computed wrongly. That it is computed at all and
then quietly consulted for routing, which would move FDA's stated 0.294 to a
derived 0.293560 for exactly the studies in that window. The structural tests
at the end of this file are the ones that matter most.
"""

from __future__ import annotations

import ast
import inspect
import math

import pytest

from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.hvd import assess_endpoint, assess_study
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    parse_sequence,
)
from be_stats.spec import (
    FDA_HVD_CONSTANTS,
    Capability,
    HvdClass,
    Method,
    NtiStatus,
    fda_hvd_classification,
    fda_hvd_method_for,
)
from be_stats.study import Treatment

PARTIAL = ("TRR", "RTR", "RRT")

#: sWR at which CVwR is exactly 30 percent. FDA's classification boundary
#: expressed on the other scale - NOT the switching threshold, which is 0.294.
SWR_AT_CV_30 = math.sqrt(math.log1p(0.30**2))


def dataset_with_exact_swr(
    swr: float, *, endpoint: str = "Cmax"
) -> ReplicateDataset:
    """A partial replicate dataset whose sWR is `swr` to machine precision.

    Boundary tests need the boundary, not a draw near it. Appendix G's

        sWR^2 = SUM_i SUM_j (Dij - Dbar_i.)^2 / (2(n - m))

    collapses to exactly `swr` for a construction chosen to make it: two
    subjects per sequence whose reference differences are +swr and -swr. Each
    sequence mean is then zero, each sequence contributes 2*swr^2, and with
    m = 3 sequences and n = 6 subjects the denominator 2(n - m) = 6 cancels the
    numerator 6*swr^2.

    Randomly generated data cannot do this. A test that draws until it lands
    near 0.294 is testing the draw, and the cases that matter here are decided
    in the fourth decimal place.
    """
    observations: list[ReplicateObservation] = []
    for label in PARTIAL:
        sequence = parse_sequence(label)
        for k, half in enumerate((+0.5, -0.5)):
            reference_period = 0
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                log_value = math.log(1000.0)
                if treatment is Treatment.REFERENCE:
                    # The subject's two reference measurements differ by
                    # `2 * half * swr` on the log scale, so Dij = +/- swr.
                    log_value += half * swr if reference_period == 0 else -half * swr
                    reference_period += 1
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(log_value),
                    )
                )
    return ReplicateDataset.build(observations)


def test_the_construction_really_does_hit_the_target_swr():
    """The helper above is load-bearing, so it is checked before it is used.

    If this drifts, every boundary assertion in this file becomes a test of a
    nearby value rather than of the boundary, and would still pass.
    """
    for target in (0.10, SWR_AT_CV_30, 0.294, 0.45):
        result = assess_endpoint(dataset_with_exact_swr(target))
        assert result.swr == pytest.approx(target, abs=1e-12), target
        assert result.n_for_swr == 6
        assert result.reference_variance_df == 3


# ------------------------------------------- the classification boundary ---


@pytest.mark.parametrize(
    "cv_wr_percent,expected",
    [
        (29.99, HvdClass.NOT_HIGHLY_VARIABLE),
        (29.999999, HvdClass.NOT_HIGHLY_VARIABLE),
        (30.0, HvdClass.HIGHLY_VARIABLE),
        (30.000001, HvdClass.HIGHLY_VARIABLE),
        (30.01, HvdClass.HIGHLY_VARIABLE),
        (45.0, HvdClass.HIGHLY_VARIABLE),
    ],
)
def test_thirty_percent_or_greater_puts_the_boundary_inside(
    cv_wr_percent, expected
):
    """III.C: "30 percent or greater". The boundary case IS highly variable."""
    classification = fda_hvd_classification(
        cv_wr_percent=cv_wr_percent,
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    assert classification.hvd_class is expected


def test_fda_includes_the_boundary_where_ema_excludes_it():
    """Same number, two regulators, opposite inequalities. Not a duplicate.

    EMA 4.1.10 widens only when CVwR is STRICTLY greater than 30%. FDA III.C
    classifies at 30% or greater. A drug at exactly 30.00% is highly variable
    to FDA and not eligible for widening under EMA, and a shared "the 30% rule"
    would have to be wrong for one of them.
    """
    from be_stats.spec import Endpoint, ema_hvd_scaling_eligible

    fda = fda_hvd_classification(
        cv_wr_percent=30.0,
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    ema_eligible, _ = ema_hvd_scaling_eligible(
        cv_wr_percent=30.0, endpoint=Endpoint.CMAX
    )

    assert fda.hvd_class is HvdClass.HIGHLY_VARIABLE
    assert ema_eligible is False


def test_the_threshold_comes_from_the_verified_constant_not_a_literal():
    classification = fda_hvd_classification(
        cv_wr_percent=42.0,
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    assert classification.threshold_percent == pytest.approx(
        100.0 * FDA_HVD_CONSTANTS["classification_cv"].value
    )
    assert classification.basis is FDA_HVD_CONSTANTS["classification_cv"]
    assert classification.basis.citation.section == "III.C"


# ------------------------------------------------- the second conjunct ---


def test_an_nti_drug_is_not_highly_variable_however_variable_it_is():
    """III.C: "and that are not considered NTI drugs". Both conjuncts, or none.

    Dropping the exclusion would classify every variable NTI drug as highly
    variable, and an NTI drug is assessed under Appendix F - a different
    procedure with a different scaling constant and two extra criteria.
    """
    classification = fda_hvd_classification(
        cv_wr_percent=60.0, nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX
    )
    assert classification.hvd_class is HvdClass.EXCLUDED_NARROW_THERAPEUTIC_INDEX
    assert classification.is_highly_variable is False
    # The variability criterion still passed, and still says so. The drug is
    # excluded by CLASS, not because it was found to be reproducible.
    assert classification.meets_variability_criterion is True


def test_an_unstated_nti_status_leaves_the_drug_unclassified():
    """Not assumed non-NTI, on the `StudyRole` precedent.

    The convenient default is "not NTI", which classifies the drug as highly
    variable and is the more confident answer. It is also a regulatory
    assertion about a product, made silently, by a package that was handed
    numbers and no product information.
    """
    classification = fda_hvd_classification(cv_wr_percent=45.0)

    assert classification.nti_status is NtiStatus.NOT_STATED
    assert classification.hvd_class is HvdClass.NOT_CLASSIFIED
    assert classification.is_highly_variable is None, (
        "None, not False - undetermined and 'shown not to be' are different "
        "claims, exactly as with an undecided endpoint's `passes`"
    )


def test_a_low_cv_is_classified_without_the_nti_status():
    """The conjunction already fails, so the missing conjunct cannot save it.

    Refusing to classify here would report NOT_CLASSIFIED for a drug III.C
    plainly does not cover, and would make the unstated-NTI case look far more
    common than it is.
    """
    classification = fda_hvd_classification(cv_wr_percent=12.0)

    assert classification.nti_status is NtiStatus.NOT_STATED
    assert classification.hvd_class is HvdClass.NOT_HIGHLY_VARIABLE
    assert classification.is_highly_variable is False


def test_no_cvwr_means_no_classification():
    classification = fda_hvd_classification(
        cv_wr_percent=None,
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    assert classification.hvd_class is HvdClass.NOT_CLASSIFIED
    assert classification.meets_variability_criterion is None
    assert classification.is_highly_variable is None


# ------------------------------------ the two rules, and their disagreement ---


def test_the_two_rules_disagree_on_a_real_dataset():
    """THE PRIMARY TEST IN THIS FILE.

    A dataset whose CVwR is 30.0042% - so the drug IS highly variable under
    III.C - and whose sWR is 0.2936, BELOW FDA's 0.294. The analysis is
    ordinary average BE.

    "Highly variable, therefore reference-scaled" is false here, and this is
    the study that makes it false. Anyone who wires the classification into the
    switch turns this dataset's verdict into a different one.

    Deliberately 0.2936 rather than the window's own edge at 0.293560: see
    `test_the_exact_boundary_is_not_reachable_from_data` for why a dataset
    cannot be placed on a float boundary to the last bit, and why this package
    does not add a tolerance to compensate.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(0.2936),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert result.cv_wr_percent > 30.0
    assert result.hvd_classification.hvd_class is HvdClass.HIGHLY_VARIABLE

    assert result.swr < FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    assert result.selected_method is Method.STANDARD_ABE
    assert result.rsabe_applicable is False
    assert result.rsabe_result is None


def test_the_exact_boundary_is_not_reachable_from_data():
    """A finding, recorded rather than smoothed over.

    `log_sd_to_cv(cv_to_log_sd(0.30))` is exactly 0.30 - the package's own
    conversions round-trip to the bit. A DATASET cannot: the reference
    differences are carried as PK values, so they pass through `exp` on the way
    in and `log` on the way out, and the recovered sWR differs from the
    intended one in the last two or three bits.

    A study engineered to sit exactly on 30.00% therefore lands a few parts in
    1e14 either side of it, and here it lands below and is classified NOT
    highly variable.

    THE PACKAGE DOES NOT COMPENSATE, AND THAT IS THE POINT.

    Adding an epsilon to the comparison would be this package choosing a
    tolerance FDA did not state, at the exact place where the choice decides
    the answer. The comparison stays as III.C writes it, the effect is written
    down here, and any real study reports a CVwR whose distance from 30% is
    many orders of magnitude larger than this.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(SWR_AT_CV_30),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert result.cv_wr_percent == pytest.approx(30.0, abs=1e-9)
    assert result.cv_wr_percent != 30.0
    assert result.cv_wr_percent < 30.0
    assert result.hvd_classification.hvd_class is HvdClass.NOT_HIGHLY_VARIABLE

    # The conversions themselves are exact, so this is a property of carrying
    # data through PK values and not of the threshold comparison.
    from be_stats.conversions import cv_to_log_sd, log_sd_to_cv

    assert log_sd_to_cv(cv_to_log_sd(0.30)) == 0.30

    # And the analysis is unaffected either way - both sides of this boundary
    # are far below 0.294.
    assert result.selected_method is Method.STANDARD_ABE


@pytest.mark.parametrize("swr", [0.2936, 0.2939, 0.29399999])
def test_every_study_in_the_window_is_highly_variable_and_unscaled(swr):
    """The window [0.293560, 0.294), swept rather than sampled at one point."""
    assert SWR_AT_CV_30 < swr < 0.294

    result = assess_endpoint(
        dataset_with_exact_swr(swr),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert result.hvd_classification.hvd_class is HvdClass.HIGHLY_VARIABLE
    assert result.cv_wr_percent > 30.0
    assert result.selected_method is Method.STANDARD_ABE
    assert result.rsabe_applicable is False


@pytest.mark.parametrize("swr", [0.294, 0.294001, 0.35, 0.60])
def test_at_and_above_the_switch_both_rules_agree(swr):
    """Above 0.294 the two coincide, and the agreement is a fact not a rule.

    Asserted so that a reader can see the disagreement is confined to the
    window: everywhere else the classification and the switch give the same
    impression, which is precisely why the window is easy to miss.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(swr),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert result.selected_method is Method.FDA_HVD_RSABE
    assert result.rsabe_applicable is True
    assert result.hvd_classification.hvd_class is HvdClass.HIGHLY_VARIABLE


def test_the_reverse_disagreement_is_impossible_and_that_is_asserted():
    """No study is reference-scaled while its drug is not highly variable.

    The CV-to-sWR map is monotone increasing, so sWR >= 0.294 implies
    CVwR > 30%. Worth asserting rather than reasoning about: if either
    conversion ever changed, this would fail and the two rules would have
    become independent in a way nobody intended.
    """
    from be_stats.conversions import log_sd_to_cv

    for step in range(0, 400):
        swr = 0.294 + step * 0.001
        assert fda_hvd_method_for(swr) is Method.FDA_HVD_RSABE
        assert 100.0 * log_sd_to_cv(swr) > 30.0


# ------------------------------------------------------ end-to-end wiring ---


def test_the_switch_boundary_holds_end_to_end_on_data():
    """0.2939 / 0.294 exactly / 0.294001, through the whole assessment.

    The existing boundary tests call `fda_hvd_method_for` with a float. These
    run real datasets through `assess_endpoint`, because a switch applied to
    the right number in the wrong place would pass the first and fail these.
    """
    below = assess_endpoint(dataset_with_exact_swr(0.2939))
    on = assess_endpoint(dataset_with_exact_swr(0.294))
    above = assess_endpoint(dataset_with_exact_swr(0.294001))

    assert below.selected_method is Method.STANDARD_ABE
    assert on.selected_method is Method.FDA_HVD_RSABE
    assert above.selected_method is Method.FDA_HVD_RSABE


def test_an_unstated_nti_status_is_reported_and_changes_no_number():
    """The advisory says what is missing, and the analysis is untouched.

    ADVISORY severity, which this package defines as "recorded, changed
    nothing". That is the exact claim being made, and the next test proves it
    rather than trusting the label.
    """
    result = assess_endpoint(dataset_with_exact_swr(0.45))

    advisories = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.NTI_STATUS_NOT_STATED
    ]
    assert len(advisories) == 1
    assert advisories[0].severity is Severity.ADVISORY
    assert result.hvd_classification.hvd_class is HvdClass.NOT_CLASSIFIED
    assert result.selected_method is Method.FDA_HVD_RSABE
    assert result.rsabe_result is not None


def test_no_advisory_when_the_drug_is_not_variable_enough_to_need_one():
    """The advisory is about an incomplete classification, not a missing field.

    Below 30% the classification is complete without the NTI status, so
    demanding one would be noise on every low-variability study.
    """
    result = assess_endpoint(dataset_with_exact_swr(0.10))

    assert result.hvd_classification.hvd_class is HvdClass.NOT_HIGHLY_VARIABLE
    assert not [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.NTI_STATUS_NOT_STATED
    ]


@pytest.mark.parametrize(
    "nti_status",
    [
        NtiStatus.NOT_STATED,
        NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
        NtiStatus.NARROW_THERAPEUTIC_INDEX,
    ],
)
def test_the_nti_status_changes_the_classification_and_nothing_else(nti_status):
    """THE STRUCTURAL GUARANTEE, checked by comparing whole results.

    Every statistical quantity on the result is compared across all three NTI
    statuses. If any of them ever became sensitive to the classification -
    through the switch, through a branch, through a diagnostic that gated
    something - one of these equalities breaks.
    """
    dataset = dataset_with_exact_swr(0.45)
    reference = assess_endpoint(dataset)
    result = assess_endpoint(dataset, nti_status=nti_status)

    assert result.swr == reference.swr
    assert result.cv_wr == reference.cv_wr
    assert result.selected_method is reference.selected_method
    assert result.rsabe_applicable == reference.rsabe_applicable
    assert result.decided == reference.decided
    assert result.passes == reference.passes
    assert result.rsabe_criterion == reference.rsabe_criterion
    assert result.rsabe_passes == reference.rsabe_passes
    assert result.gmr == reference.gmr
    assert result.point_estimate_passes == reference.point_estimate_passes


def test_the_classification_survives_a_dataset_that_cannot_be_estimated():
    """sWR not estimable: no classification, no method, no invented verdict."""
    sequence = parse_sequence("TRR")
    dataset = ReplicateDataset.build(
        [
            ReplicateObservation(
                subject_id="only-one",
                sequence=sequence,
                period=period,
                treatment=sequence.expected_treatment(period),
                endpoint="Cmax",
                value=1000.0,
            )
            for period in range(1, sequence.periods + 1)
        ]
    )
    result = assess_endpoint(dataset, nti_status=NtiStatus.NOT_STATED)

    assert not result.decided
    assert result.passes is None
    assert result.selected_method is None
    assert result.rsabe_applicable is None
    assert result.hvd_classification.hvd_class is HvdClass.NOT_CLASSIFIED
    assert result.hvd_classification.meets_variability_criterion is None


def test_each_endpoint_classifies_on_its_own_variability():
    """One product, one NTI status, two endpoints, two classifications.

    The NTI status is a property of the drug and applies to both. CVwR is a
    property of the endpoint's data and does not, so AUC may be ordinary while
    Cmax is highly variable - the same per-endpoint logic Appendix G applies to
    the method, for the same reason.
    """
    results = assess_study(
        {
            "AUC": dataset_with_exact_swr(0.10, endpoint="AUC"),
            "Cmax": dataset_with_exact_swr(0.50, endpoint="Cmax"),
        },
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert results["AUC"].hvd_classification.hvd_class is (
        HvdClass.NOT_HIGHLY_VARIABLE
    )
    assert results["Cmax"].hvd_classification.hvd_class is (
        HvdClass.HIGHLY_VARIABLE
    )


# ---------------------------------------------------------- the schema ---


def test_the_result_reports_every_component_of_the_decision():
    """§8's audit trail: each piece separately, and the conjunction last."""
    result = assess_endpoint(
        dataset_with_exact_swr(0.45),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )

    assert result.swr2 == pytest.approx(0.45**2, abs=1e-12)
    assert result.swr == pytest.approx(0.45, abs=1e-12)
    assert result.cv_wr_percent > 30.0
    assert result.hvd_classification.hvd_class is HvdClass.HIGHLY_VARIABLE
    assert result.switching_threshold.value == 0.294
    assert result.rsabe_applicable is True
    assert result.rsabe_criterion is not None
    assert result.rsabe_limit == 0.0
    assert result.rsabe_passes is not None
    assert result.gmr is not None
    assert result.point_estimate_passes is not None
    assert result.decided is True
    assert result.passes is not None


def test_the_conjunction_is_not_read_off_either_criterion_alone():
    """`passes` is A and B. Both are separately visible, and both are needed."""
    result = assess_endpoint(dataset_with_exact_swr(0.45))

    assert result.passes == (result.rsabe_passes and result.point_estimate_passes)
    assert result.rsabe_result.passes == result.passes


def test_swr2_is_delegated_rather_than_stored_twice():
    """A second copy of a number is a second number that can be wrong."""
    result = assess_endpoint(dataset_with_exact_swr(0.45))
    assert result.swr2 is result.reference_variance.variance_wr


# ------------------------------------------------------------ structural ---


def test_the_classification_is_not_wired_into_the_switch():
    """The mistake this whole file guards against, asserted on the AST.

    A behavioural test cannot catch this reliably: a switch that consulted the
    classification would still return the right answer everywhere except the
    four-ten-thousandth window, and a test suite that happened not to exercise
    the window would pass.
    """
    from be_stats import spec

    tree = ast.parse(inspect.getsource(spec.fda_hvd_method_for))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "fda_hvd_classification" not in called, (
        "fda_hvd_method_for consults the classification. The classification is "
        "on the CV scale; routing by it moves FDA's stated 0.294 to the "
        "derived 0.293560 for every study in between."
    )
    assert "classification_cv" not in inspect.getsource(spec.fda_hvd_method_for)


def test_the_classification_does_not_read_the_switching_threshold():
    """And the converse, which would be the same error from the other side."""
    from be_stats import spec

    source = inspect.getsource(spec.fda_hvd_classification)
    assert "swr_switching_threshold" not in source
    assert "0.294" not in source.split('"""')[2], (
        "0.294 appears in the classification's code rather than only in its "
        "docstring, where it is discussed"
    )


def test_the_classification_constant_is_consumed_and_only_by_the_classifier():
    """The register now says what the code does, and it did not before.

    `consumed_by` was an empty tuple: the constant was cited, indexed, tested
    for distinctness and applied to nothing. What must NOT appear here is
    `FDA_HVD_METHOD_SELECTION`.
    """
    from be_stats.dossier.constants import constant

    record = constant("FDA_HVD_CLASSIFICATION_CV")
    assert record.consumed_by == ("FDA_HVD_CLASSIFICATION",)
    assert "FDA_HVD_METHOD_SELECTION" not in record.consumed_by
    assert "FDA_HVD_RSABE" not in record.consumed_by

    switch = constant("FDA_HVD_SWR_SWITCH")
    assert "FDA_HVD_CLASSIFICATION" not in switch.consumed_by


def test_the_capability_is_registered_and_not_promoted():
    """§10: implementation completion does not move a validation status."""
    from be_stats.dossier.capabilities import capability

    from be_stats.provenance import ValidationStatus
    from be_stats.spec import CAPABILITY_VALIDATION

    status = CAPABILITY_VALIDATION[Capability.FDA_HVD_CLASSIFICATION]
    assert status is not ValidationStatus.VALIDATED
    assert status is ValidationStatus.IMPLEMENTED

    record = capability("FDA_HVD_CLASSIFICATION")
    assert record.jurisdiction is not None
    assert record.decision_supported is False, (
        "classifying a drug is not deciding a study"
    )
    assert record.regulatory_source.section == "III.C"


# --------------------------------------------------------- explainability ---


def test_the_explanation_never_joins_the_two_rules_with_therefore():
    """§15: the wording is the deliverable, so the wording is tested.

    "HVD because CV >30 therefore RSABE" is the sentence this package must
    never produce. The classification's own lines talk about the drug and do
    not mention sWR, 0.294 or the analysis at all.
    """
    classification = fda_hvd_classification(
        cv_wr_percent=45.0,
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    text = " ".join(classification.explain()).lower()

    assert "0.294" not in text
    assert "reference-scaled" not in text
    assert "rsabe" not in text
    assert "therefore" not in text
    assert "classifies the drug" in text
    assert "30 percent or greater" in text


def test_the_provenance_says_the_classification_selected_nothing():
    """Two adjacent blocks a reader will otherwise join with an arrow."""
    result = assess_endpoint(
        dataset_with_exact_swr(0.45),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    lines = result.provenance()
    joined = " ".join(lines)

    assert "classification: highly_variable" in joined
    assert "the classification above did not select this method" in joined
    assert any("switching rule" in line for line in lines)


def test_the_summary_shows_the_classification_beside_the_method():
    result = assess_endpoint(
        dataset_with_exact_swr(SWR_AT_CV_30),
        nti_status=NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
    )
    summary = result.summary()

    # The disagreement, visible in one glance at the summary.
    assert "highly_variable" in summary
    assert "standard_abe" in summary


def test_an_unclassified_drug_says_why_in_its_own_explanation():
    classification = fda_hvd_classification(cv_wr_percent=45.0)
    text = " ".join(classification.explain())

    assert "not classified" in text
    assert "does not affect which analysis was run" in text
