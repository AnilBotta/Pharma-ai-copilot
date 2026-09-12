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
in the middle of this file are the ones that matter most.

AND THE RISK THE FIRST VERSION MISSED

Independent review found a second defect, of the opposite kind. Having kept the
classification scrupulously out of the routing, the code then let the routing
ignore the classification entirely - and returned `FDA_HVD_RSABE`,
`decided=True` and a pass for a product simultaneously classified
`EXCLUDED_NARROW_THERAPEUTIC_INDEX`. III.C excludes NTI drugs from the
definition and FDA assesses them under Appendix F, so that verdict came from the
wrong appendix.

The fix is a THIRD question, asked before the other two:

    applicability    may the FDA HVD procedure decide this PRODUCT?
    classification   is this a highly variable DRUG?
    method selection which ANALYSIS applies to these data?

Only the third produces a verdict, and it is reached only when the first says
yes. The APPLICABILITY GATE section below holds those tests; the two thresholds
above it are untouched.
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
    ContradictoryProductClass,
    DrugClass,
    Endpoint,
    HvdApplicability,
    HvdClass,
    Jurisdiction,
    Method,
    NtiStatus,
    fda_hvd_applicability,
    fda_hvd_classification,
    fda_hvd_method_for,
    nti_status_from_drug_class,
    reconcile_nti_status,
    resolve_be_spec,
)
from be_stats.study import Treatment

PARTIAL = ("TRR", "RTR", "RRT")

#: A product confirmed NOT to be a narrow therapeutic index drug.
#:
#: Spelled out at every call site that needs a verdict, because since the
#: applicability gate an unstated status refuses to decide. The alias exists so
#: that the declaration is short enough to be read rather than skimmed - not so
#: that it can be forgotten.
NON_NTI = NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX

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

    A confirmed non-NTI product, because the applicability gate would otherwise
    refuse to select a method at all - and that refusal is the subject of its
    own tests, not of this one.
    """
    below = assess_endpoint(dataset_with_exact_swr(0.2939), nti_status=NON_NTI)
    on = assess_endpoint(dataset_with_exact_swr(0.294), nti_status=NON_NTI)
    above = assess_endpoint(dataset_with_exact_swr(0.294001), nti_status=NON_NTI)

    assert below.selected_method is Method.STANDARD_ABE
    assert on.selected_method is Method.FDA_HVD_RSABE
    assert above.selected_method is Method.FDA_HVD_RSABE


def test_an_unstated_nti_status_refuses_the_verdict_and_says_why():
    """THE CORRECTION. This test previously asserted the opposite.

    It read: the advisory says what is missing, and the analysis is untouched -
    and it asserted `selected_method is FDA_HVD_RSABE` with a populated
    `rsabe_result` for a product whose NTI status nobody had stated.

    Independent review of PR #82 found that wrong, and it was wrong at the
    regulation rather than in the code. III.C's definition excludes NTI drugs
    and FDA assesses them under Appendix F, so a verdict issued without knowing
    the product's class may be a verdict from the wrong appendix. The severity
    is now FATAL, which in this package means the analysis produced no estimate
    of the thing asked for - and that is now literally true of the decision.
    """
    result = assess_endpoint(dataset_with_exact_swr(0.45))

    refusals = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.FDA_HVD_APPLICABILITY_REQUIRES_NTI_STATUS
    ]
    assert len(refusals) == 1
    assert refusals[0].severity is Severity.FATAL

    assert result.applicability is HvdApplicability.UNDETERMINED_NTI_NOT_STATED
    assert result.hvd_classification.hvd_class is HvdClass.NOT_CLASSIFIED
    assert result.selected_method is None
    assert result.rsabe_applicable is None
    assert result.rsabe_result is None
    assert result.decided is False
    assert result.passes is None

    # The descriptive quantities survive, because they describe the reference's
    # variability and assert nothing about bioequivalence.
    assert result.swr == pytest.approx(0.45, abs=1e-12)
    assert result.cv_wr_percent > 30.0
    assert result.reference_variance.estimable


def test_a_low_cv_does_not_license_a_method_when_nti_is_unknown():
    """Review section 3, which is the subtle half of the blocker.

    "Not highly variable" and "therefore ordinary average BE applies" are
    different claims, and they come apart exactly when the NTI status is
    unknown: an unknown product with CVwR of 10% could still be an NTI drug,
    which FDA assesses under Appendix F with narrower criteria - not under the
    conventional 80.00-125.00 limits.

    So the classification is allowed to stand (the HVD conjunction has already
    failed on variability alone) while the regulatory method is not inferred
    from it.
    """
    result = assess_endpoint(dataset_with_exact_swr(0.10))

    # The logical classification stands.
    assert result.hvd_classification.hvd_class is HvdClass.NOT_HIGHLY_VARIABLE
    assert result.hvd_classification.is_highly_variable is False

    # The regulatory method does not follow from it.
    assert result.applicability is HvdApplicability.UNDETERMINED_NTI_NOT_STATED
    assert result.selected_method is None
    assert result.decided is False
    assert result.passes is None
    assert [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.FDA_HVD_APPLICABILITY_REQUIRES_NTI_STATUS
    ]


@pytest.mark.parametrize(
    "nti_status",
    [
        NtiStatus.NOT_STATED,
        NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX,
        NtiStatus.NARROW_THERAPEUTIC_INDEX,
    ],
)
def test_the_nti_status_changes_the_decision_and_never_the_estimates(nti_status):
    """THE STRUCTURAL GUARANTEE, rewritten around the right invariant.

    It used to assert that the NTI status changed the classification "and
    nothing else", comparing whole results including `decided` and `passes`.
    That invariant WAS the blocker: it held only because the verdict ignored the
    product's regulatory class.

    The correct invariant is narrower and still worth locking down. The NTI
    status must not move a single ESTIMATE - the sWR, the CVwR, the degrees of
    freedom, the subject count all describe the data and cannot depend on a
    product property. What it does move is whether those estimates support a
    regulatory decision at all.
    """
    dataset = dataset_with_exact_swr(0.45)
    reference = assess_endpoint(dataset, nti_status=NON_NTI)
    result = assess_endpoint(dataset, nti_status=nti_status)

    # The measurements are identical, whatever the product turns out to be.
    assert result.swr == reference.swr
    assert result.cv_wr == reference.cv_wr
    assert result.swr2 == reference.swr2
    assert result.n_for_swr == reference.n_for_swr
    assert result.reference_variance_df == reference.reference_variance_df

    # The decision is gated on applicability, and only the confirmed non-NTI
    # product gets one.
    if nti_status is NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX:
        assert result.applicability.permits_verdict
        assert result.decided is True
        assert result.passes is not None
        assert result.selected_method is Method.FDA_HVD_RSABE
    else:
        assert not result.applicability.permits_verdict
        assert result.decided is False
        assert result.passes is None
        assert result.selected_method is None
        assert result.rsabe_applicable is None


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


def test_a_non_estimable_dataset_refuses_for_a_confirmed_non_nti_product_too():
    """The estimability branch, which the gate now short-circuits for refusals.

    A refused product returns before the `variance.estimable` check, so without
    this the branch would only ever be reached by the unstated case and a defect
    in it could hide behind the gate.
    """
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
    result = assess_endpoint(dataset, nti_status=NON_NTI)

    assert result.applicability is HvdApplicability.APPLICABLE
    assert not result.reference_variance.estimable
    assert result.swr is None
    assert result.selected_method is None
    assert result.decided is False
    assert result.passes is None
    assert result.hvd_classification.hvd_class is HvdClass.NOT_CLASSIFIED


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
    result = assess_endpoint(dataset_with_exact_swr(0.45), nti_status=NON_NTI)

    assert result.passes == (result.rsabe_passes and result.point_estimate_passes)
    assert result.rsabe_result.passes == result.passes


def test_swr2_is_delegated_rather_than_stored_twice():
    """A second copy of a number is a second number that can be wrong."""
    result = assess_endpoint(dataset_with_exact_swr(0.45), nti_status=NON_NTI)
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


# =========================================================================== #
# THE APPLICABILITY GATE
#
# Added after independent review of PR #82, which found that the first version
# of this work could return, on one object:
#
#     hvd_classification = EXCLUDED_NARROW_THERAPEUTIC_INDEX
#     selected_method    = FDA_HVD_RSABE
#     decided            = True
#     passes             = True
#
# - a bioequivalence verdict from FDA's highly variable procedure for a product
# FDA assesses under Appendix F. Each field was individually correct and the
# object as a whole asserted something false.
#
# The classification and the switch are UNCHANGED. What is new is a gate in
# front of the verdict, and these are its tests.
# =========================================================================== #


# ------------------------------------------ the gate, on the rule itself ---


@pytest.mark.parametrize(
    "nti_status,expected,permits",
    [
        (NtiStatus.NOT_NARROW_THERAPEUTIC_INDEX, HvdApplicability.APPLICABLE, True),
        (
            NtiStatus.NARROW_THERAPEUTIC_INDEX,
            HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX,
            False,
        ),
        (
            NtiStatus.NOT_STATED,
            HvdApplicability.UNDETERMINED_NTI_NOT_STATED,
            False,
        ),
    ],
)
def test_applicability_depends_only_on_the_product(nti_status, expected, permits):
    """Three inputs, three outcomes, and exactly one permits a verdict."""
    applicability = fda_hvd_applicability(nti_status)
    assert applicability is expected
    assert applicability.permits_verdict is permits


def test_applicability_is_not_a_function_of_the_data():
    """It takes no dataset, no sWR and no CVwR - asserted on the signature.

    A variable NTI drug is no more eligible for Appendix G than a reproducible
    one, so applicability must not be computable from the data. If a future
    change threads a measurement in here, the gate has become something else.
    """
    parameters = list(inspect.signature(fda_hvd_applicability).parameters)
    assert parameters == ["nti_status"]


# ------------------------------------------------ explicit NTI: refused ---


@pytest.mark.parametrize("swr", [0.20, 0.2937, 0.40])
def test_an_nti_product_gets_no_verdict_at_any_variability(swr):
    """Review section 6. Below the switch, in the window, and above it.

    All three refused, and for the same reason: the product belongs to a
    different appendix. The sWR at which it was refused is irrelevant, which is
    exactly why all three are here.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(swr),
        nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX,
    )

    assert result.applicability is (
        HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX
    )
    assert result.decided is False
    assert result.passes is None
    assert result.selected_method is None
    assert result.rsabe_applicable is None
    assert result.rsabe_result is None
    assert result.appendix_c_result is None
    assert result.standard_abe_result is None

    refusals = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.FDA_HVD_NOT_APPLICABLE_NTI
    ]
    assert len(refusals) == 1
    assert refusals[0].severity is Severity.FATAL
    assert "Appendix F" in refusals[0].context["required_procedure"]


def test_an_nti_product_still_reports_its_variability_descriptively():
    """Refusing the verdict is not refusing to measure.

    sWR and CVwR describe the reference's own variability and carry no
    comparison between products, so they are reported. What is NOT reported is
    a treatment contrast: a point estimate of T against R is the shape of an
    answer, and this is not a product this procedure may answer for.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(0.40),
        nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX,
    )

    assert result.swr == pytest.approx(0.40, abs=1e-12)
    assert result.cv_wr_percent > 30.0
    assert result.reference_variance.estimable
    assert result.reference_variance_df == 3

    assert result.treatment_contrast is None
    assert result.gmr is None
    assert result.point_estimate_passes is None
    assert result.n_for_treatment_contrast == 0


def test_the_nti_classification_and_the_refusal_agree_with_each_other():
    """The two halves of the same fact, on the same object.

    The classification says the drug is excluded by class; the applicability
    says the procedure does not apply. A result showing one without the other
    would be the contradiction in a quieter form.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(0.40),
        nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX,
    )

    assert result.hvd_classification.hvd_class is (
        HvdClass.EXCLUDED_NARROW_THERAPEUTIC_INDEX
    )
    assert result.hvd_classification.is_highly_variable is False
    assert result.applicability is (
        HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX
    )


# ----------------------------------------- unstated NTI: also refused ---


@pytest.mark.parametrize(
    "swr,expected_class",
    [
        (0.10, HvdClass.NOT_HIGHLY_VARIABLE),
        (0.2937, HvdClass.NOT_CLASSIFIED),
        (0.40, HvdClass.NOT_CLASSIFIED),
    ],
)
def test_an_unstated_status_refuses_at_every_variability(swr, expected_class):
    """Review section 6's third block, including its section 3 subtlety.

    Below 30% the classification is still allowed to say "not highly variable" -
    the HVD conjunction has failed on variability alone. Above it the
    classification is undetermined. In all three cases there is no verdict,
    because "not highly variable" does not establish that ordinary average BE
    is the applicable regulatory method for a product that might be NTI.
    """
    result = assess_endpoint(dataset_with_exact_swr(swr))

    assert result.hvd_classification.hvd_class is expected_class
    assert result.applicability is HvdApplicability.UNDETERMINED_NTI_NOT_STATED
    assert result.decided is False
    assert result.passes is None
    assert result.selected_method is None
    assert result.rsabe_applicable is None


def test_the_unstated_refusal_is_not_silent():
    """It names the missing input and what to supply."""
    result = assess_endpoint(dataset_with_exact_swr(0.40))
    refusal = next(
        d for d in result.diagnostics
        if d.code is DiagnosticCode.FDA_HVD_APPLICABILITY_REQUIRES_NTI_STATUS
    )
    assert refusal.severity is Severity.FATAL
    assert "not an assertion of non-NTI" in refusal.detail
    assert "nti_status" in refusal.detail


# ------------------------------- confirmed non-NTI: nothing changed ---


@pytest.mark.parametrize(
    "swr,expected_class,expected_method",
    [
        (0.10, HvdClass.NOT_HIGHLY_VARIABLE, Method.STANDARD_ABE),
        (0.2937, HvdClass.HIGHLY_VARIABLE, Method.STANDARD_ABE),
        (0.294, HvdClass.HIGHLY_VARIABLE, Method.FDA_HVD_RSABE),
        (0.40, HvdClass.HIGHLY_VARIABLE, Method.FDA_HVD_RSABE),
    ],
)
def test_a_confirmed_non_nti_product_flows_exactly_as_before(
    swr, expected_class, expected_method
):
    """Review section 6's first block, and the regression guard for the fix.

    The row at 0.2937 is the disagreement window: a highly variable drug taking
    ordinary average BE. The gate must not have collapsed it - which it would
    have, had applicability been made a function of the classification.
    """
    result = assess_endpoint(dataset_with_exact_swr(swr), nti_status=NON_NTI)

    assert result.applicability is HvdApplicability.APPLICABLE
    assert result.applicability.permits_verdict
    assert result.hvd_classification.hvd_class is expected_class
    assert result.selected_method is expected_method
    assert result.rsabe_applicable is (expected_method is Method.FDA_HVD_RSABE)


def test_the_gate_moves_no_number_for_a_confirmed_non_nti_product():
    """The fix is a gate, not a change to the arithmetic.

    Every quantity the RSABE criterion reports is checked against the values a
    pre-gate assessment produced for the same dataset. They are recomputed here
    from the criterion's own components rather than hard-coded, so this fails if
    the gate ever perturbs the arithmetic it stands in front of.
    """
    result = assess_endpoint(dataset_with_exact_swr(0.45), nti_status=NON_NTI)
    rsabe = result.rsabe_result

    assert rsabe is not None
    assert result.rsabe_criterion == (
        rsabe.scaled_criterion.upper_confidence_bound
    )
    assert result.rsabe_limit == 0.0
    assert result.rsabe_passes == rsabe.scaled_criterion.passes
    assert result.gmr == result.treatment_contrast.point_estimate
    assert result.point_estimate_passes == (
        rsabe.point_estimate_constraint.passes
    )
    assert result.passes == (
        result.rsabe_passes and result.point_estimate_passes
    )
    assert result.swr2 == pytest.approx(0.45**2, abs=1e-12)


# --------------------------------------- the spec as a source of truth ---


def _spec_for(drug_class: DrugClass):
    return resolve_be_spec(
        jurisdiction=Jurisdiction.FDA,
        drug_class=drug_class,
        endpoint=Endpoint.CMAX if drug_class is DrugClass.HIGHLY_VARIABLE else Endpoint.AUC,
    )


def test_the_drug_class_nti_claim_invariant_holds_through_the_resolver():
    """Review section 5 asked for this invariant to be PROVEN, not assumed.

    The claim being relied on is that a spec resolved as HIGHLY_VARIABLE
    establishes non-NTI. It rests on two things, both asserted here rather than
    described: `DrugClass` members are distinct, so one field cannot hold both;
    and `resolve_be_spec` routes them to different methods, so the resolver
    treats them as disjoint regulatory paths.
    """
    assert DrugClass.HIGHLY_VARIABLE is not DrugClass.NARROW_THERAPEUTIC_INDEX

    hvd = _spec_for(DrugClass.HIGHLY_VARIABLE)
    nti = _spec_for(DrugClass.NARROW_THERAPEUTIC_INDEX)
    assert hvd.method is Method.FDA_HVD_RSABE
    assert nti.method is Method.FDA_NTI_RSABE

    assert nti_status_from_drug_class(DrugClass.HIGHLY_VARIABLE) is NON_NTI
    assert nti_status_from_drug_class(DrugClass.STANDARD) is NON_NTI
    assert nti_status_from_drug_class(DrugClass.NARROW_THERAPEUTIC_INDEX) is (
        NtiStatus.NARROW_THERAPEUTIC_INDEX
    )

    # Every member states its claim. A drug class added without one must raise
    # rather than inherit a neighbour's.
    for member in DrugClass:
        assert nti_status_from_drug_class(member) in (
            NON_NTI,
            NtiStatus.NARROW_THERAPEUTIC_INDEX,
        ), member


def test_a_highly_variable_spec_establishes_non_nti_on_its_own():
    """So the product class need not be stated twice.

    A caller who has already resolved a HIGHLY_VARIABLE spec has declared the
    product's class; demanding `nti_status` as well would be duplicated state
    with two chances to disagree.
    """
    result = assess_endpoint(
        dataset_with_exact_swr(0.45), spec=_spec_for(DrugClass.HIGHLY_VARIABLE)
    )

    assert result.applicability is HvdApplicability.APPLICABLE
    assert result.decided is True
    assert result.selected_method is Method.FDA_HVD_RSABE


def test_an_nti_spec_refuses_through_the_same_gate():
    result = assess_endpoint(
        dataset_with_exact_swr(0.45),
        spec=_spec_for(DrugClass.NARROW_THERAPEUTIC_INDEX),
    )

    assert result.applicability is (
        HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX
    )
    assert result.decided is False
    assert result.selected_method is None


@pytest.mark.parametrize(
    "drug_class,nti_status",
    [
        (DrugClass.HIGHLY_VARIABLE, NtiStatus.NARROW_THERAPEUTIC_INDEX),
        (DrugClass.STANDARD, NtiStatus.NARROW_THERAPEUTIC_INDEX),
        (DrugClass.NARROW_THERAPEUTIC_INDEX, NON_NTI),
    ],
)
def test_a_contradictory_spec_and_status_fail_closed(drug_class, nti_status):
    """Review section 5: if both are supplied and disagree, fail closed.

    Not resolved by precedence. Two incompatible statements about one product's
    regulatory class cannot both be true, and preferring either is the engine
    deciding which of its inputs to believe about a property it cannot observe.
    """
    with pytest.raises(ContradictoryProductClass) as raised:
        assess_endpoint(
            dataset_with_exact_swr(0.45),
            spec=_spec_for(drug_class),
            nti_status=nti_status,
        )

    message = str(raised.value)
    assert str(drug_class) in message
    assert str(nti_status) in message
    assert "will not choose between them" in message


@pytest.mark.parametrize(
    "drug_class,nti_status",
    [
        (DrugClass.HIGHLY_VARIABLE, NON_NTI),
        (DrugClass.NARROW_THERAPEUTIC_INDEX, NtiStatus.NARROW_THERAPEUTIC_INDEX),
        (DrugClass.HIGHLY_VARIABLE, NtiStatus.NOT_STATED),
    ],
)
def test_agreeing_or_absent_inputs_reconcile_without_complaint(
    drug_class, nti_status
):
    """Failing closed must not mean failing on agreement."""
    resolved = reconcile_nti_status(
        spec=_spec_for(drug_class), nti_status=nti_status
    )
    assert resolved is nti_status_from_drug_class(drug_class)


def test_no_spec_leaves_the_status_exactly_as_given():
    for status in NtiStatus:
        assert reconcile_nti_status(spec=None, nti_status=status) is status


# ------------------------------------------------- result coherence ---


def test_a_contradictory_result_cannot_be_CONSTRUCTED():
    """THE PRIMARY GUARD, and it is a constructor check rather than a test.

    This is the exact object independent review found reachable. Building it
    directly - bypassing `assess_endpoint` entirely - must still fail, because
    a guard that lives in one function protects only that function.
    """
    from be_stats.hvd import FdaHvdResult, NotDecidable
    from be_stats.reference_variance import estimate_reference_variance

    variance = estimate_reference_variance(dataset_with_exact_swr(0.45))
    refused = HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX

    def build(**overrides):
        fields = dict(
            endpoint="Cmax",
            design=variance.design,
            swr=variance.swr,
            cv_wr=variance.cv_wr,
            switching_threshold=FDA_HVD_CONSTANTS["swr_switching_threshold"],
            selected_method=None,
            reference_variance=variance,
            applicability=refused,
            decided=False,
        )
        fields.update(overrides)
        return FdaHvdResult(**fields)

    # The refusing result itself is constructible.
    assert build().passes is None

    # Decided, while the procedure does not apply.
    with pytest.raises(NotDecidable, match="does not apply"):
        build(decided=True)

    # Carrying the method it would have received.
    with pytest.raises(NotDecidable, match="dual state"):
        build(selected_method=Method.FDA_HVD_RSABE)


def test_the_undetermined_case_is_guarded_the_same_way():
    """Both refusing members, not just the NTI one.

    The unstated case is the one a future change is most likely to soften,
    because it looks like a missing argument rather than a regulatory fact.
    """
    from be_stats.hvd import FdaHvdResult, NotDecidable
    from be_stats.reference_variance import estimate_reference_variance

    variance = estimate_reference_variance(dataset_with_exact_swr(0.45))

    with pytest.raises(NotDecidable):
        FdaHvdResult(
            endpoint="Cmax",
            design=variance.design,
            swr=variance.swr,
            cv_wr=variance.cv_wr,
            switching_threshold=FDA_HVD_CONSTANTS["swr_switching_threshold"],
            selected_method=None,
            reference_variance=variance,
            applicability=HvdApplicability.UNDETERMINED_NTI_NOT_STATED,
            decided=True,
        )


def test_every_applicability_member_is_covered_by_these_tests():
    """A fourth member added later must be classified, not defaulted.

    `permits_verdict` is a whitelist of one, so a new member is refusing by
    default - which is the safe direction - but it would arrive with no tests
    and no diagnostic wording. This fails until somebody writes them.
    """
    assert set(HvdApplicability) == {
        HvdApplicability.APPLICABLE,
        HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX,
        HvdApplicability.UNDETERMINED_NTI_NOT_STATED,
    }
    assert [a for a in HvdApplicability if a.permits_verdict] == [
        HvdApplicability.APPLICABLE
    ]


def test_applicability_is_the_same_for_every_endpoint_of_one_product():
    """It is a product property, so it cannot vary by endpoint.

    The classification legitimately does vary - each endpoint has its own CVwR -
    and this is the thing that must not.
    """
    results = assess_study(
        {
            "AUC": dataset_with_exact_swr(0.10, endpoint="AUC"),
            "Cmax": dataset_with_exact_swr(0.50, endpoint="Cmax"),
        },
        nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX,
    )

    for endpoint, result in results.items():
        assert result.applicability is (
            HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX
        ), endpoint
        assert result.decided is False, endpoint
        assert result.passes is None, endpoint


# ------------------------------------------ gate explainability (section 8) ---


def test_the_nti_refusal_explains_itself_and_names_the_right_procedure():
    result = assess_endpoint(
        dataset_with_exact_swr(0.40),
        nti_status=NtiStatus.NARROW_THERAPEUTIC_INDEX,
    )
    lines = result.provenance()
    joined = " ".join(lines)

    assert lines[0] == (
        "FDA HVD procedure not applicable: the product is identified as "
        "narrow therapeutic index. Use the FDA NTI procedure."
    ), "the refusal must be the FIRST line, not a footnote after a method line"
    assert "DESCRIPTIVE ONLY" in joined
    assert "No bioequivalence decision was issued" in joined

    # And no switching-rule line, because no method was selected.
    assert not any("switching rule" in line for line in lines)


def test_the_unstated_refusal_explains_itself():
    result = assess_endpoint(dataset_with_exact_swr(0.40))
    lines = result.provenance()

    assert lines[0] == (
        "FDA HVD applicability cannot be determined because NTI status was not "
        "specified. Variability estimates are descriptive only; no regulatory "
        "BE decision was issued."
    )
    assert not any("switching rule" in line for line in lines)


def test_a_refusing_summary_never_shows_a_pass_or_a_method():
    for status in (
        NtiStatus.NARROW_THERAPEUTIC_INDEX,
        NtiStatus.NOT_STATED,
    ):
        summary = assess_endpoint(
            dataset_with_exact_swr(0.40), nti_status=status
        ).summary()

        assert "NO BE DECISION ISSUED" in summary
        assert "descriptive only" in summary
        assert "fda_hvd_rsabe" not in summary
        assert "PASS" not in summary
        assert "criterion A" not in summary


def test_the_confirmed_non_nti_explanation_is_unchanged():
    """Section 8: retain the existing classification/switch explanation."""
    result = assess_endpoint(dataset_with_exact_swr(0.40), nti_status=NON_NTI)
    joined = " ".join(result.provenance())

    assert "classification: highly_variable" in joined
    assert "the classification above did not select this method" in joined
    assert "switching rule" in joined
    assert "DESCRIPTIVE ONLY" not in joined
