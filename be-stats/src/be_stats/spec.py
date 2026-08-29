"""Resolving *which test applies* before computing anything.

THE ORDER MATTERS

An earlier version of this package asked a regulatory profile for an acceptance
interval and then did arithmetic. That is the wrong shape, because for several
combinations the regulator does not change the interval - it changes the test.
FDA does not narrow limits for a narrow therapeutic index drug; it requires a
fully replicated design, reference-scaled BE, an additional unscaled criterion,
and a comparison of within-subject variances. Handing back an interval there
would answer a question nobody asked.

So the engine resolves a `BeSpec` first. The spec names the method, says which
design it requires, and carries the constants that method needs. Only a spec
whose method is implemented can be handed to an estimator; the rest refuse by
construction rather than by a check somebody might forget.

METHODS ARE JURISDICTION-SPECIFIC, ALWAYS

There is deliberately no generic "highly variable" method. FDA uses
reference-scaled average BE; EMA uses average BE with expanding limits. They are
different procedures with different constants and different decision rules, and
a shared abstraction over them would exist only to be wrong in one of the two.

EVERY NUMBER SAYS WHERE IT CAME FROM

Constants are `RegulatoryValue`, not float: a value plus the document, the
section, the document version, and whether anybody has checked it. `explain()`
answers "why 0.90" with something better than "because this file says so".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from be_stats.provenance import (
    EMA_BIOEQUIVALENCE,
    EMA_BIOEQUIVALENCE_HVD,
    FDA_STATISTICAL_APPROACHES,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F,
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    FDA_STATISTICAL_APPROACHES_III_A,
    FDA_STATISTICAL_APPROACHES_III_C,
    VIA_PRIMARY_DOCUMENT,
    Citation,
    RegulatoryValue,
    ValidationStatus,
    VerificationStatus,
)


class Jurisdiction(StrEnum):
    FDA = "FDA"
    EMA = "EMA"


class Endpoint(StrEnum):
    """The measure being compared.

    Present because EMA's narrowed interval for NTI drugs applies to AUC by
    default but to Cmax only when Cmax is itself important for safety or
    efficacy - a per-endpoint, per-product decision. A jurisdiction-and-class
    profile without an endpoint cannot express that.
    """

    AUC = "AUC"
    CMAX = "Cmax"
    OTHER = "other"


class DrugClass(StrEnum):
    STANDARD = "standard"
    NARROW_THERAPEUTIC_INDEX = "narrow_therapeutic_index"
    HIGHLY_VARIABLE = "highly_variable"


class Method(StrEnum):
    """The procedure, not merely the limits."""

    STANDARD_ABE = "standard_abe"
    EMA_NTI_NARROW_ABE = "ema_nti_narrow_abe"
    FDA_NTI_RSABE = "fda_nti_rsabe"
    FDA_HVD_RSABE = "fda_hvd_rsabe"
    EMA_HVD_ABEL = "ema_hvd_abel"


#: How far each method has got. `IMPLEMENTED` is derived from this rather than
#: maintained beside it, so the two cannot disagree.
#:
#: Both runnable methods are IMPLEMENTED_UNVALIDATED rather than VALIDATED.
#: The evidence stands at:
#:
#:     tier 1A  FDA regulatory ALGORITHM      VERIFIED - attested at review
#:                                            with section references
#:     tier 1B  FDA numeric worked DATASET    PENDING - the guidance body has
#:                                            not been obtainable
#:     tier 3   independent numeric check     PASSED - two PowerTOST cases
#:
#: VALIDATED requires 1B. An attested algorithm is not a reproduced result, and
#: only the second licenses a filing. See validation/README.md.
VALIDATION: dict[Method, ValidationStatus] = {
    Method.STANDARD_ABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    Method.EMA_NTI_NARROW_ABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    #: All three Appendix F criteria are computable as of the Appendix C
    #: release - (b) was the one that was structurally missing. The method
    #: therefore leaves NOT_IMPLEMENTED, and stops at
    #: IMPLEMENTED_UNVALIDATED: its validation ladder has to be re-run against
    #: the assembled procedure, not inherited from the three parts.
    Method.FDA_NTI_RSABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    #: Implemented in the highly-variable release. IMPLEMENTED_UNVALIDATED and
    #: not VALIDATED: tier 1A conformance to Appendix G is established, tier 1B
    #: is not, and this package's policy is that an attested algorithm is not a
    #: reproduced result.
    Method.FDA_HVD_RSABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    #: EMA ABEL. IMPLEMENTED_UNVALIDATED at the METHOD level even though three
    #: of its capabilities are VALIDATED on tier-1B evidence — the first in
    #: this package to reach that bar.
    #:
    #: A method status is the status of the whole procedure, and the whole
    #: procedure is more than its parts: no EMA publication carries one
    #: end-to-end highly variable Cmax example running CVwR > 30% -> widened
    #: limits -> Method A 90% CI -> GMR constraint -> a stated verdict.
    #: Validated components assembled by unvalidated wiring is precisely the
    #: failure this ladder exists to make visible, so the method stays below
    #: its parts rather than inheriting their best status.
    #:
    #: See `CAPABILITY_VALIDATION` for the per-capability picture.
    Method.EMA_HVD_ABEL: ValidationStatus.IMPLEMENTED_UNVALIDATED,
}

#: NOTE: this frozenset and `ValidationStatus.IMPLEMENTED` are unrelated. This
#: one answers "can this method be run at all"; that one is a status meaning
#: "implemented, with no external numeric claim to validate".
IMPLEMENTED: frozenset[Method] = frozenset(
    m for m, s in VALIDATION.items() if s is not ValidationStatus.NOT_IMPLEMENTED
)


class Capability(StrEnum):
    """Things the engine can do that are not methods.

    A `Method` decides bioequivalence. These do not - they validate a dataset,
    or estimate a quantity that a method will later use. They are tracked
    separately rather than added to `Method` for one reason: everything in
    `Method` is a candidate answer to "which test applies", and putting a data
    validator in that enum would make it possible for a routing function to
    return one.

    The separation matters most right now, because this release estimates sWR
    without being allowed to decide anything with it.
    """

    #: Recognise a replicate design, validate its structure, construct the
    #: reference replicates.
    FDA_HVD_REPLICATE_DATA_VALIDATION = "fda_hvd_replicate_data_validation"
    #: Estimate the within-subject reference variance and CVwR from a
    #: validated replicate dataset.
    FDA_HVD_REFERENCE_VARIANCE = "fda_hvd_reference_variance"
    #: Estimate mu_T - mu_R as the equally weighted mean of the sequence means
    #: of Iij, with the design's own degrees of freedom.
    FDA_HVD_TREATMENT_CONTRAST = "fda_hvd_treatment_contrast"
    #: Apply the switching rule at sWR = 0.294 to one endpoint.
    FDA_HVD_METHOD_SELECTION = "fda_hvd_method_selection"
    #: Ordinary average BE for a replicate design, per FDA Appendix C. Tracked
    #: separately from `Method.STANDARD_ABE`, which covers the 2x2 crossover
    #: and parallel designs Phase 1 implements.
    FDA_HVD_UNSCALED_BRANCH = "fda_hvd_unscaled_branch"
    #: Appendix C itself: the mixed model, independent of which caller needs it.
    #:
    #: SPLIT BY DESIGN, and the split is load-bearing rather than tidy.
    #:
    #: PR #61 established a trustworthy oracle for the fully replicate design
    #: and NOT for the partial replicate one: ReplicateBE.jl reproduces EMA's
    #: published SAS Method C output exactly on 2x2x4 and differs by 2.94
    #: denominator degrees of freedom on 2x3x3. A single
    #: `FDA_REPLICATE_STANDARD_ABE` status would have to say one thing about
    #: two situations that differ, and whichever it said would be wrong about
    #: the other - a report reading VALIDATED would imply partial replicate
    #: support that does not exist.
    FDA_REPLICATE_STANDARD_ABE_FULL = "fda_replicate_standard_abe_full"
    FDA_REPLICATE_STANDARD_ABE_PARTIAL = "fda_replicate_standard_abe_partial"

    # ------------------------------------ narrow therapeutic index drugs ---
    #: Enforce that an NTI drug is on a fully replicate design before any
    #: arithmetic runs.
    FDA_NTI_DESIGN_VALIDATION = "fda_nti_design_validation"
    #: Appendix F steps 2 and 5a: the reference-scaled mean criterion.
    FDA_NTI_REFERENCE_SCALED_CRITERION = "fda_nti_reference_scaled_criterion"
    #: Appendix F steps 4 and 5c: the 90% equal-tails F interval for
    #: sigma_WT / sigma_WR against 2.500.
    FDA_NTI_VARIABILITY_RATIO = "fda_nti_variability_ratio"
    #: Appendix F step 5b: the ordinary UNSCALED 80.00-125.00% limits, which
    #: for a fully replicate study means Appendix C's model.
    FDA_NTI_UNSCALED_ABE = "fda_nti_unscaled_abe"

    # ------------------------------ EMA highly variable drugs (ABEL) ---
    #: Which replicate designs 4.1.10 permits, classified with a reason.
    EMA_HVD_DESIGN_GATE = "ema_hvd_design_gate"
    #: CVwR > 30%, strictly, on the CV scale, and Cmax only.
    EMA_HVD_VARIABILITY_ELIGIBILITY = "ema_hvd_variability_eligibility"
    #: CVwR from the reference measurements alone, by the model
    #: EMA/618604/2008 Rev. 13 section 3.4 specifies.
    EMA_HVD_REFERENCE_VARIABILITY = "ema_hvd_reference_variability"
    #: Method A: the all-fixed-effects ANOVA the Q&A calls "guideline
    #: recommended", giving mu_T - mu_R and its 90% interval.
    EMA_REPLICATE_METHOD_A = "ema_replicate_method_a"
    #: exp(+/- k.sWR) with the cap 4.1.10 states.
    EMA_ABEL_LIMIT_CALCULATION = "ema_abel_limit_calculation"
    #: The GMR within 80.00-125.00%, required in addition to the interval.
    EMA_ABEL_PE_CONSTRAINT = "ema_abel_pe_constraint"
    #: The two criteria combined into one endpoint verdict.
    EMA_HVD_ENDPOINT_DECISION = "ema_hvd_endpoint_decision"


#: Capabilities carry their own statuses, on the same ladder.
#:
#: Data validation is `IMPLEMENTED` rather than `IMPLEMENTED_UNVALIDATED`
#: because it produces no number for a regulator to disagree with: it either
#: enforces the design definitions or it does not, and the tests decide that.
#: Reference variance is `IMPLEMENTED_UNVALIDATED` because it produces sWR,
#: and no regulator-published worked dataset has been reproduced.
CAPABILITY_VALIDATION: dict[Capability, ValidationStatus] = {
    Capability.FDA_HVD_REPLICATE_DATA_VALIDATION: ValidationStatus.IMPLEMENTED,
    Capability.FDA_HVD_REFERENCE_VARIANCE: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    Capability.FDA_HVD_TREATMENT_CONTRAST: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    #: Structural: the switch either applies 0.294 to the estimated sWR or it
    #: does not, and the tier-1A cases decide that.
    Capability.FDA_HVD_METHOD_SELECTION: ValidationStatus.IMPLEMENTED,
    #: NOT_IMPLEMENTED, and not an open question.
    #:
    #: Appendix G step 1a routes sWR < 0.294 to the two one-sided tests
    #: procedure without naming a model. Appendix C names one, and it is not
    #: the Appendix G intermediate: a mixed model on subject-period
    #: observations with a PERIOD term, an unstructured subject-by-formulation
    #: covariance and treatment-specific residual variances.
    #:
    #: An earlier version ran TOST on the `ilat` contrast and called this
    #: EXPERIMENTAL. A status field does not travel with a number, and the
    #: number was a bioequivalence verdict from a different model.
    #:
    #: IMPLEMENTED FOR FULLY REPLICATE DESIGNS as of the Appendix C release.
    #: A partial replicate study below the switch still refuses, and so does a
    #: fully replicate one whose raw observations were not supplied - Appendix
    #: C is available-case and cannot be run from the reduced dataset. The
    #: status is the weaker of the two situations it covers, deliberately: a
    #: caller reading IMPLEMENTED here must not infer that every HVD study
    #: below the switch gets a verdict.
    Capability.FDA_HVD_UNSCALED_BRANCH: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    #: Appendix C for the FULLY REPLICATE design. Implemented, and validated
    #: against two independent kinds of evidence:
    #:
    #:   EMA/618604/2008 Rev. 13 Data set I, SAS 9.1 Method C - a regulator's
    #:   published result for FDA's model. Note the authority precisely: the
    #:   MODEL is FDA's, the NUMBERS are EMA-published. Stronger than a
    #:   peer-reviewed dataset, weaker than an FDA-published example of FDA's
    #:   own model, and never described as the latter.
    #:
    #:   ReplicateBE.jl 1.0.15 on Julia 1.10.5 - an independent implementation
    #:   oracle, verified in PR #61 to reproduce that same SAS output.
    Capability.FDA_REPLICATE_STANDARD_ABE_FULL: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    #: Appendix C for the PARTIAL REPLICATE design. NOT_IMPLEMENTED, and the
    #: reason is evidentiary rather than arithmetical: the same code would
    #: produce a number and there is nothing to check it against. The correct
    #: partial replicate Satterthwaite df remains NOT DETERMINED. See
    #: validation/findings/VAL-FDA-APPENDIX-C-002.md.
    Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL: (
        ValidationStatus.NOT_IMPLEMENTED
    ),
    # ------------------------------------ narrow therapeutic index drugs ---
    #: Structural: the design gate either enforces III.B or it does not.
    Capability.FDA_NTI_DESIGN_VALIDATION: ValidationStatus.IMPLEMENTED,
    Capability.FDA_NTI_REFERENCE_SCALED_CRITERION: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    Capability.FDA_NTI_VARIABILITY_RATIO: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    #: Criterion (b), now computed. NTI's design gate already requires a fully
    #: replicate design, which is exactly the scope Appendix C is validated
    #: for - so unlike the HVD branch there is no partial replicate case to
    #: refuse, and all three NTI criteria are available given the raw
    #: observations.
    Capability.FDA_NTI_UNSCALED_ABE: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    # ------------------------------ EMA highly variable drugs (ABEL) ---
    #
    # THE FIRST `VALIDATED` ENTRIES IN THIS TABLE, AND WHY THEY EARN IT
    #
    # Everything above is IMPLEMENTED_UNVALIDATED at best, because FDA has
    # published no worked dataset and the package's policy is that an attested
    # algorithm is not a reproduced result. EMA has published one — two, in
    # fact, plus a table — so three EMA capabilities clear the bar that no FDA
    # capability can currently clear.
    #
    # The evidence is TIER 1B: a regulator's own numbers, reproduced. Not tier
    # 3, which is an independent implementation agreeing, and not tier 1A,
    # which is an algorithm attested against prose.
    #: Structural: the gate either permits the designs 4.1.10 permits or it
    #: does not. No number for a regulator to disagree with.
    Capability.EMA_HVD_DESIGN_GATE: ValidationStatus.IMPLEMENTED,
    #: Structural: a strict comparison against 30 on the CV scale.
    Capability.EMA_HVD_VARIABILITY_ELIGIBILITY: ValidationStatus.IMPLEMENTED,
    #: VALIDATED — tier 1B. EMA/618604/2008 Rev. 13 section 3.4 publishes the
    #: reference within-subject CV for both annexed data sets under the Model
    #: A/B column: 47.0% and 11.2%. This package's estimator, run on the raw
    #: data from the same annex, gives 46.96% and 11.17% — agreement to the
    #: one decimal EMA printed. See tests/validation/test_ema_tier1b.py.
    Capability.EMA_HVD_REFERENCE_VARIABILITY: ValidationStatus.VALIDATED,
    #: VALIDATED — tier 1B. The same Q&A publishes Method A's point estimate
    #: and 90% confidence interval for both data sets: 115.66 (107.11, 124.89)
    #: and 102.26 (97.32, 107.46). Both reproduce to the two decimals printed,
    #: INCLUDING the unbalanced four-period set whose eight incomplete subjects
    #: must be retained for the published result to come out.
    Capability.EMA_REPLICATE_METHOD_A: ValidationStatus.VALIDATED,
    #: VALIDATED — tier 1B. Section 4.1.10 prints its own table of widened
    #: limits at CVwR 30, 35, 40, 45 and >=50 percent. All five rows reproduce
    #: to the two decimals published, and the stated cap 69.84 - 143.19% is
    #: applied as stated.
    #:
    #: VAL-EMA-ABEL-002 does not qualify this. It is RESOLVED: PowerTOST keeps
    #: the unrounded formula where EMA states a rounded pair, which is a
    #: documented divergence between an oracle and a regulator and not an open
    #: question about the rule. be-stats follows the regulator, and the tier-1B
    #: table is what confirms that reading.
    Capability.EMA_ABEL_LIMIT_CALCULATION: ValidationStatus.VALIDATED,
    #: A containment test on a number produced elsewhere. No regulator-published
    #: example exercises the constraint on its own, so it stays unvalidated even
    #: though the limits either side of it are validated.
    Capability.EMA_ABEL_PE_CONSTRAINT: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
    #: DELIBERATELY NOT VALIDATED, and the reason is worth stating.
    #:
    #: Every PART of the endpoint decision now has tier-1B evidence, and the
    #: whole does not. No EMA publication carries one end-to-end highly
    #: variable Cmax example running CVwR > 30% -> widened limits -> Method A
    #: 90% CI -> GMR within 80-125% -> a stated PASS or FAIL. Validating the
    #: components does not validate the wiring between them, and this is
    #: exactly the place where a package could assemble correct pieces into a
    #: wrong verdict.
    Capability.EMA_HVD_ENDPOINT_DECISION: (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    ),
}


def validation_report() -> list[str]:
    """Every method and capability with its status, for a release note or log.

    One function so the two tables are always shown together; reading either
    alone gives a misleading picture of what the engine can be trusted with.
    """
    lines = ["methods:"]
    lines += [f"  {m} — {s}" for m, s in VALIDATION.items()]
    lines += ["capabilities:"]
    lines += [f"  {c} — {s}" for c, s in CAPABILITY_VALIDATION.items()]
    return lines


class NotApplicable(Exception):
    """This combination is not assessed the way the caller assumed."""


class NotImplementedMethod(Exception):
    """The correct method is known, and this version does not implement it.

    Distinct from `NotApplicable` on purpose: this is "we know what you need
    and cannot do it yet", not "you have asked for something incoherent". A
    caller can act on the difference.
    """


class SpecificationRequired(Exception):
    """The regulator leaves this to product-specific guidance.

    Raised rather than defaulted. Both possible answers are defensible for some
    products, so choosing one silently would be choosing wrong for the others.
    """


class NotValidated(Exception):
    """The method runs, but has not been shown to agree with the regulator."""


@dataclass(frozen=True, slots=True)
class AcceptanceInterval:
    lower: RegulatoryValue
    upper: RegulatoryValue
    basis: str

    def contains(self, ci_lower: float, ci_upper: float) -> bool:
        return ci_lower >= self.lower.value and ci_upper <= self.upper.value

    @property
    def lower_value(self) -> float:
        return self.lower.value

    @property
    def upper_value(self) -> float:
        return self.upper.value

    def explain(self) -> list[str]:
        return [self.lower.explain(), self.upper.explain()]


@dataclass(frozen=True, slots=True)
class ProductOverride:
    """Product-specific guidance, which outranks the jurisdiction default.

    EMA narrows AUC to 90.00-111.11 for NTI drugs, and whether Cmax is narrowed
    too is product-specific: ciclosporin narrows both, colchicine narrows AUC
    and leaves Cmax at 80.00-125.00. A jurisdiction rule alone cannot be right
    for both, so the product rule wins when one is supplied.
    """

    product: str
    #: Endpoint -> (lower, upper) in percent.
    limits: dict[Endpoint, tuple[float, float]] = field(default_factory=dict)
    citation: str = ""


def _interval(
    lower: float, upper: float, citation: Citation, basis: str, verification
) -> AcceptanceInterval:
    return AcceptanceInterval(
        lower=RegulatoryValue(lower, citation, verification),
        upper=RegulatoryValue(upper, citation, verification),
        basis=basis,
    )


#: The conventional interval. Shared by both regulators for the standard case,
#: and long enough established that it is treated as verified.
_ICH_M13A_LIKE = Citation(
    authority="ICH / FDA / EMA",
    document="Conventional bioequivalence acceptance interval",
    document_version="current",
)


# ------------------------------------------- FDA highly variable drugs ---
#
# TWO ADJACENT NUMBERS THAT MEAN DIFFERENT THINGS
#
# FDA defines a highly variable drug by within-subject variability of 30% or
# greater. Separately, once a replicate study has been run, it selects the
# analysis by the ESTIMATED within-reference standard deviation:
#
#     sWR <  0.294  ->  ordinary ABE / TOST
#     sWR >= 0.294  ->  reference-scaled ABE, plus a point-estimate constraint
#
# It is tempting to notice that sqrt(ln(1 + 0.30^2)) = 0.293560 and conclude
# that 0.294 is that value rounded, and that an engine should therefore prefer
# the exact derivation. An earlier version of this package did exactly that.
# It was wrong: 0.294 is the regulator's rule, applied to an estimate, and
# replacing it with a self-computed 0.293560 substitutes the package's
# arithmetic for FDA's criterion. Both are kept, separately, because they
# answer different questions.
#
# NOW READ FROM THE PRIMARY DOCUMENT
#
# These were VERIFIED by relay until the guidance itself was obtained. Both
# statements survive, in the guidance's own words:
#
#   III.C     "Highly variable drugs are drugs for which within subject
#             variability (%CV) in BE measures 30 percent or greater and that
#             are not considered NTI drugs."
#
#   III.C     "If the estimated within-subject standard deviation of the
#             reference is < 0.294, the average BE two one-sided test procedure
#             should be used ... Otherwise, the reference-scaled average BE
#             procedure should be used ... together with a point estimate
#             constraint ... bounded by 80.00 percent to 125.00 percent."
#
#   App. G    "a. If sWR < 0.294, use the two one-sided tests procedure ...
#              b. If sWR >= 0.294, use the reference-scaled procedure"
#
# Both places put the boundary case ON the scaled side, which is what
# `fda_hvd_method_for` implements.

FDA_HVD_CONSTANTS: dict[str, RegulatoryValue] = {
    "classification_cv": RegulatoryValue(
        0.30,
        FDA_STATISTICAL_APPROACHES_III_C,
        VerificationStatus.VERIFIED,
        "Defines WHICH DRUGS are highly variable: within-subject variability "
        "(%CV) of 30 percent or greater, and not an NTI drug. Not the "
        "analysis switch.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "swr_switching_threshold": RegulatoryValue(
        0.294,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "Selects WHICH ANALYSIS applies, from the estimated sWR. Below it, "
        "ordinary ABE; at or above it, reference-scaled ABE. Numerically near "
        "sqrt(ln(1+0.30^2)) = 0.293560 but NOT that quantity - this is the "
        "regulator's stated criterion and must not be recomputed. Stated in "
        "both III.C and Appendix G step 1, which agree on the boundary.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "sigma_w0": RegulatoryValue(
        0.25,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "Reference-scaling constant for highly variable drugs; Appendix G "
        "step 2 gives it as 'sigma_W0 = 0.25 (regulatory constant)'.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "point_estimate_lower": RegulatoryValue(
        0.8000,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "The scaled criterion alone is not sufficient: Appendix G step 3b "
        "requires the T/R geometric mean ratio to fall within [0.8000, "
        "1.2500].",
        VIA_PRIMARY_DOCUMENT,
    ),
    "point_estimate_upper": RegulatoryValue(
        1.2500,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "",
        VIA_PRIMARY_DOCUMENT,
    ),
}


# --------------------------------------- EMA highly variable drugs ---
#
# A SEPARATE DICTIONARY, ON PURPOSE, AND NOT A REGULATOR FLAG
#
# FDA's RSABE and EMA's ABEL are not one method with two parameter sets. They
# differ in what triggers scaling, on which SCALE that trigger is expressed,
# what the scaled quantity is, which endpoints may use it, whether there is a
# cap, and how the criteria combine. Sharing a constants table between them
# would make each of those differences a conditional rather than a fact, and a
# conditional is something that can be got wrong once and then be wrong
# everywhere.
#
# THE TRIGGER IS ON THE CV SCALE, AND IT IS STRICT
#
# EMA 4.1.10: widening requires "that the within-subject variability for Cmax
# of the reference compound in the study is >30%". That is CVwR, as a
# percentage, strictly greater than 30.
#
# It is NOT sWR >= 0.294, and it must not be turned into one. On the sWR scale
# EMA's boundary is sqrt(ln(1 + 0.30^2)) = 0.293560..., which is a DIFFERENT
# NUMBER from FDA's stated 0.294 — the two regulators' thresholds disagree in
# the fourth decimal, and studies exist between them. See
# validation/findings/VAL-FDA-HVD-002.md, which records that difference from
# the other side.
#
# So EMA's threshold is stored as 30 percent on the CV scale, compared on the
# CV scale, and never converted for the purposes of the decision.
EMA_HVD_CONSTANTS: dict[str, RegulatoryValue] = {
    "cv_wr_scaling_threshold_percent": RegulatoryValue(
        30.0,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "Widening requires CVwR > 30 percent, STRICTLY greater. 4.1.10: 'the "
        "bioequivalence study must be of a replicate design where it has been "
        "demonstrated that the within-subject variability for Cmax of the "
        "reference compound in the study is >30%'. Compared on the CV scale; "
        "do not convert to an sWR boundary.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "regulatory_constant_k": RegulatoryValue(
        0.760,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "4.1.10: '[U, L] = exp [+/- k.sWR] ... k is the regulatory constant "
        "set to 0.760'. Stated to three decimals by the regulator and stored "
        "as stated.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "cap_cv_percent": RegulatoryValue(
        50.0,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "The variability at which widening stops. The guideline's own table "
        "ends at '>=50' and the Q&A says the widening increases 'to a maximum "
        "of 50%'.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "cap_lower_percent": RegulatoryValue(
        69.84,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "4.1.10: 'the acceptance criteria for Cmax can be widened to a maximum "
        "of 69.84 - 143.19%'. STATED by the regulator, not recomputed. "
        "exp(-0.760*sqrt(ln(1.25))) = 69.83678..., which rounds to it - see "
        "`ema_abel_cap_computed` for that value, kept separate.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "cap_upper_percent": RegulatoryValue(
        143.19,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "As above; exp(+0.760*sqrt(ln(1.25))) = 143.19101... rounds to it. "
        "Note the stated pair is not exactly reciprocal (1/0.6984 = 1.43184), "
        "because each was rounded independently.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "point_estimate_lower_percent": RegulatoryValue(
        80.00,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "4.1.10: 'The geometric mean ratio (GMR) should lie within the "
        "conventional acceptance range 80.00-125.00%.' Required IN ADDITION to "
        "the confidence interval falling inside the widened limits. "
        "Numerically equal to FDA's constraint and stored separately, because "
        "two regulators agreeing today is not the same as one rule.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "point_estimate_upper_percent": RegulatoryValue(
        125.00,
        EMA_BIOEQUIVALENCE_HVD,
        VerificationStatus.VERIFIED,
        "",
        VIA_PRIMARY_DOCUMENT,
    ),
}

#: Which endpoints EMA permits reference scaling for. Cmax, and only Cmax.
#:
#: 4.1.10, final paragraph: "The possibility to widen the acceptance criteria
#: based on high intra-subject variability does not apply to AUC where the
#: acceptance range should remain at 80.00 - 125.00% regardless of
#: variability."
#:
#: A frozenset rather than a boolean on the endpoint, so that adding an
#: endpoint is an edit to a regulatory table with a citation attached, not a
#: condition somebody relaxes in passing.
EMA_ABEL_SCALABLE_ENDPOINTS: frozenset[Endpoint] = frozenset({Endpoint.CMAX})


def ema_abel_cap_computed() -> tuple[float, float]:
    """The cap as the formula would give it, NOT as the regulator states it.

    Exists to be compared against the stated 69.84 - 143.19, never to be used
    in place of it. `ema_abel_limits` applies the stated pair; this function is
    the check that the two agree to the precision the guideline publishes.

    The FDA NTI release established the pattern: when a regulator states a
    number and also gives a formula that nearly reproduces it, keep both and
    say which one decides.
    """
    k = EMA_HVD_CONSTANTS["regulatory_constant_k"].value
    cap_cv = EMA_HVD_CONSTANTS["cap_cv_percent"].value / 100.0
    swr = math.sqrt(math.log1p(cap_cv**2))
    return 100.0 * math.exp(-k * swr), 100.0 * math.exp(k * swr)


def ema_hvd_scaling_eligible(
    *, cv_wr_percent: float, endpoint: Endpoint
) -> tuple[bool, str]:
    """Does EMA permit reference scaling here? Returns (eligible, reason).

    Two conditions, both required, and each reported separately because a study
    that fails on the endpoint is a different situation from one that fails on
    variability.
    """
    if endpoint not in EMA_ABEL_SCALABLE_ENDPOINTS:
        permitted = ", ".join(sorted(str(e) for e in EMA_ABEL_SCALABLE_ENDPOINTS))
        return False, (
            f"EMA does not permit reference scaling for {endpoint}. Section "
            f"4.1.10 restricts widening to {permitted}: 'The possibility to "
            "widen the acceptance criteria based on high intra-subject "
            "variability does not apply to AUC where the acceptance range "
            "should remain at 80.00 - 125.00% regardless of variability.'"
        )

    threshold = EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"].value
    if not cv_wr_percent > threshold:
        return False, (
            f"CVwR is {cv_wr_percent:.4f}%, which is not greater than the "
            f"{threshold:.0f}% EMA requires. The comparison is strict and is "
            "made on the CV scale, as 4.1.10 states it."
        )
    return True, (
        f"CVwR {cv_wr_percent:.4f}% exceeds {threshold:.0f}% and {endpoint} is "
        "scalable under 4.1.10."
    )


# ------------------------------- the OTHER rule that uses 0.294 ---
#
# Reading the guidance end to end turned up a second threshold at 0.294, in
# section III.A, for in vitro permeation testing of topical products. It is NOT
# the highly-variable rule and it does not share its boundary:
#
#   III.A     "the reference-scaled average BE approach is used for the
#             endpoint only if it has a sWR > 0.294. The regular average BE
#             approach ... is used for the endpoint with sWR <= 0.294."
#
#   App. G    sWR >= 0.294 -> reference-scaled
#
# Same number, opposite treatment of the boundary, different products. A study
# whose estimated sWR is exactly 0.294 is scaled under one and unscaled under
# the other.
#
# Recorded, and deliberately NOT wired into anything. The package does not do
# in vitro permeation testing, and the point of writing it down is that
# `fda_hvd_method_for` must never be reused for one - which is the same
# scoping lesson the M13A minimums taught, arriving from a third direction.

FDA_IVPT_NOTE: RegulatoryValue = RegulatoryValue(
    0.294,
    FDA_STATISTICAL_APPROACHES_III_A,
    VerificationStatus.VERIFIED,
    "IN VITRO PERMEATION TESTING ONLY, and NOT interchangeable with the "
    "highly-variable rule: here scaling applies when sWR > 0.294 (strictly), "
    "with sWR <= 0.294 unscaled. Appendix G puts the boundary case on the "
    "other side. Not consumed by any code path.",
    VIA_PRIMARY_DOCUMENT,
)


def fda_hvd_theta() -> float:
    """FDA's scaled bioequivalence limit, theta = [ln(1.25) / sigma_w0]^2.

    Computed rather than stored because it is defined by a formula in the
    guidance, not given as a number - so the formula is the thing to preserve.
    Its inputs are the verified constants above.
    """
    sigma_w0 = FDA_HVD_CONSTANTS["sigma_w0"].value
    return (math.log(1.25) / sigma_w0) ** 2


def fda_hvd_method_for(swr: float) -> Method:
    """Which analysis FDA's Appendix G selects for an estimated sWR.

    The decision rule, frozen and testable, with nothing yet consuming it -
    Phase 2A implements the analyses themselves. Boundary handling follows the
    guidance's inequality exactly: 0.294 itself selects reference scaling.

    APPLIES TO HIGHLY VARIABLE DRUGS AND NOTHING ELSE. Section III.A of the
    same guidance uses 0.294 with a STRICT inequality for in vitro permeation
    testing, so this function is wrong for that context by exactly one
    boundary case. See `FDA_IVPT_NOTE`.
    """
    if swr < 0.0:
        raise ValueError(f"sWR cannot be negative, got {swr}.")
    threshold = FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    return Method.FDA_HVD_RSABE if swr >= threshold else Method.STANDARD_ABE


# FDA NTI: THREE CRITERIA, ALL OF WHICH MUST HOLD
#
# Appendix F step 5 lists them, and reducing the procedure to "narrower limits"
# would drop two of the three:
#
#   a.  95% upper confidence bound for (mu_T - mu_R)^2 - theta*sigma_WR^2 <= 0
#   b.  the regular unscaled limits of 80.00-125.00% must ALSO be passed
#   c.  the upper limit of the 90% equal-tails CI for sigma_WT / sigma_WR must
#       be <= 2.500
#
# And III.B requires a FULLY REPLICATE crossover design for an NTI drug, which
# is why this method cannot be offered for a 2x2 study at any acceptance limit.
FDA_NTI_CONSTANTS: dict[str, RegulatoryValue] = {
    "sigma_w0": RegulatoryValue(
        0.10,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "NTI reference-scaling constant; Appendix F step 2 gives "
        "'sigma_W0 = 0.10 (regulatory constant)'.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "delta": RegulatoryValue(
        1.0 / 0.9,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "THE NORMATIVE CONSTANT, stated in Appendix F's prose as 1/0.9 "
        "(approximately 1.11111), and used as theta = [ln(delta)/sigma_W0]^2. "
        "The exact ratio is kept: the prose states the constant and the SAS "
        "example displays it to five places. See FDA_NTI_SAS_EXAMPLE_DELTA.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "variance_ratio_upper_limit": RegulatoryValue(
        2.5,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "Appendix F step 5c: the upper limit of the 90% EQUAL-TAILS confidence "
        "interval for sigma_WT / sigma_WR must be less than or equal to 2.500. "
        "The interval is an F-based one at alpha = 0.1, not a normal "
        "approximation.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "unscaled_lower_percent": RegulatoryValue(
        80.00,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "Appendix F step 5b: the regular unscaled limits must ALSO be passed. "
        "FDA does not narrow the interval for an NTI drug - it adds criteria.",
        VIA_PRIMARY_DOCUMENT,
    ),
    "unscaled_upper_percent": RegulatoryValue(
        125.00,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "",
        VIA_PRIMARY_DOCUMENT,
    ),
}


@dataclass(frozen=True, slots=True)
class BeSpec:
    """Everything decided before a single observation is read."""

    method: Method
    jurisdiction: Jurisdiction
    drug_class: DrugClass
    endpoint: Endpoint

    #: Two one-sided tests at this level, so a (1 - 2*alpha) interval.
    alpha: float = 0.05

    #: Present only for methods whose decision *is* an interval. `None` for the
    #: reference-scaled methods, where an interval would misdescribe the test.
    acceptance: AcceptanceInterval | None = None

    required_design: str = "2x2 crossover or parallel"

    #: Constants the method needs, each with its own provenance. Empty for
    #: standard ABE; carried for the reference-scaled methods so Phase 2
    #: inherits verified values rather than rediscovering them.
    constants: dict[str, RegulatoryValue] = field(default_factory=dict)

    notes: str = ""

    @property
    def confidence_level(self) -> float:
        return 1.0 - 2.0 * self.alpha

    @property
    def validation_status(self) -> ValidationStatus:
        return VALIDATION[self.method]

    @property
    def is_implemented(self) -> bool:
        return self.method in IMPLEMENTED

    def require_implemented(self) -> None:
        """Gate every estimator entry point."""
        if self.is_implemented:
            return
        raise NotImplementedMethod(
            f"{self.jurisdiction} assesses a {self.drug_class} drug on "
            f"{self.endpoint} using {self.method}, which requires a "
            f"{self.required_design}. This version does not implement it. "
            f"{self.notes} Substituting the standard 80.00-125.00 interval "
            "would be a different test, not a conservative one."
        )

    def require_validated(self) -> None:
        """Opt-in gate for a caller that must not use unvalidated arithmetic.

        Not called by the estimators. A production integration calls it; a
        development one deliberately does not, and the difference is explicit
        at the call site rather than buried in a flag.
        """
        if self.validation_status is not ValidationStatus.VALIDATED:
            raise NotValidated(
                f"{self.method} is {self.validation_status}. It has not been "
                "shown to reproduce a regulator-published worked example, so "
                "its output must not support a submission. See "
                "validation/README.md."
            )

    def require_interval(self) -> AcceptanceInterval:
        self.require_implemented()
        if self.acceptance is None:
            raise NotApplicable(
                f"{self.method} does not decide by a fixed acceptance interval."
            )
        return self.acceptance

    def provenance(self) -> list[str]:
        """Every number this spec would use, and where each came from."""
        lines: list[str] = []
        if self.acceptance is not None:
            lines.extend(self.acceptance.explain())
        lines.extend(f"{name}: {rv.explain()}" for name, rv in self.constants.items())
        return lines

    def unverified_values(self) -> list[str]:
        """Names of any constant not yet checked against its primary source."""
        names: list[str] = []
        if self.acceptance is not None:
            for label, rv in (("lower", self.acceptance.lower), ("upper", self.acceptance.upper)):
                if rv.verification is VerificationStatus.UNVERIFIED:
                    names.append(label)
        names.extend(
            name
            for name, rv in self.constants.items()
            if rv.verification is VerificationStatus.UNVERIFIED
        )
        return names


# ------------------------- the Appendix F example-code literal ---
#
# A PRECISION DISCREPANCY, NOT A CONTRADICTION
#
# Appendix F states the constant in prose as `Delta = 1/0.9
# (approximately=1.11111)`, and its SAS example then writes
# `theta=((log(1.11111))/0.1)**2` - the five-decimal approximation the prose
# itself offers, not a second rule.
#
# This is worth being careful about in both directions. It is NOT the guidance
# contradicting itself, and it says nothing about the algorithm, which is
# identical either way. It is an example printing a constant to five decimal
# places, which is what example code does. Calling it a contradiction would
# misrepresent the document.
#
# It is also not nothing: carried through theta it is a relative difference of
# about 1.9e-05, and criterion (a) has a boundary, so there exist studies the
# two would decide differently. `test_the_production_decision_uses_the_prose_
# constant` exhibits one.
#
# So the normative constant is the prose ratio, the example literal is kept
# beside it as an implementation reference, and neither is rounded into the
# other.

#: The literal that appears in Appendix F's SAS. NOT a regulatory constant, and
#: deliberately outside `FDA_NTI_CONSTANTS` so it can never be iterated as one.
#: Kept so the comparison is reproducible from the package rather than from
#: somebody's memory of the PDF.
FDA_NTI_SAS_EXAMPLE_DELTA: RegulatoryValue = RegulatoryValue(
    1.11111,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F,
    VerificationStatus.VERIFIED,
    "IMPLEMENTATION REFERENCE, NOT THE REGULATORY CONSTANT. This is the "
    "five-decimal approximation written in Appendix F's SAS example; the "
    "normative value is the prose ratio Delta = 1/0.9. Verified as appearing "
    "in the document, which is a claim about the example code and not about "
    "the rule. Consumed by nothing in the decision path.",
    VIA_PRIMARY_DOCUMENT,
)


def fda_nti_theta() -> float:
    """FDA's NTI scaled limit, theta = [ln(Delta) / sigma_W0]^2.

    THE ONE THE ENGINE DECIDES WITH.

    Computed from the verified regulatory constants: `Delta = 1/0.9` as stated
    in Appendix F's prose, and `sigma_W0 = 0.10`.

    See `fda_nti_theta_sas_example` for the value Appendix F's example code
    would give, and the comment above it for why they differ and why the prose
    constant governs.
    """
    delta = FDA_NTI_CONSTANTS["delta"].value
    sigma_w0 = FDA_NTI_CONSTANTS["sigma_w0"].value
    return (math.log(delta) / sigma_w0) ** 2


def fda_nti_theta_sas_example() -> float:
    """Theta as Appendix F's SAS example would compute it. NOT the rule.

    Provided so the difference can be measured from the package rather than
    re-derived by hand, and so a test can assert that no decision path calls
    this. Nothing in `nti.py` does, and a structural test enforces it.
    """
    sigma_w0 = FDA_NTI_CONSTANTS["sigma_w0"].value
    return (math.log(FDA_NTI_SAS_EXAMPLE_DELTA.value) / sigma_w0) ** 2


def resolve_be_spec(
    *,
    jurisdiction: Jurisdiction | str,
    drug_class: DrugClass | str = DrugClass.STANDARD,
    endpoint: Endpoint | str = Endpoint.AUC,
    product: ProductOverride | None = None,
    alpha: float = 0.05,
) -> BeSpec:
    """Decide which test applies, before any data is touched."""
    jur = Jurisdiction(jurisdiction)
    cls = DrugClass(drug_class)
    end = Endpoint(endpoint)

    def spec(**kwargs) -> BeSpec:
        return BeSpec(
            jurisdiction=jur,
            drug_class=cls,
            endpoint=end,
            alpha=alpha,
            **kwargs,
        )

    override = None
    if product is not None and end in product.limits:
        lo, hi = product.limits[end]
        override = _interval(
            lo,
            hi,
            Citation(
                authority=str(jur),
                document=f"product-specific guidance for {product.product}",
                document_version=product.citation or "as supplied",
            ),
            f"product-specific guidance for {product.product}",
            VerificationStatus.UNVERIFIED,
        )

    if cls is DrugClass.STANDARD:
        return spec(
            method=Method.STANDARD_ABE,
            acceptance=override
            or _interval(
                80.00,
                125.00,
                _ICH_M13A_LIKE,
                f"{jur} standard interval",
                VerificationStatus.VERIFIED,
            ),
        )

    if cls is DrugClass.NARROW_THERAPEUTIC_INDEX:
        if jur is Jurisdiction.FDA:
            return spec(
                method=Method.FDA_NTI_RSABE,
                acceptance=None,
                required_design="fully replicated crossover",
                constants=FDA_NTI_CONSTANTS,
                notes=(
                    "FDA requires reference-scaled BE, an additional unscaled "
                    "80.00-125.00 criterion, and a comparison of test and "
                    "reference within-subject variability. Phase 2B."
                ),
            )

        if override is not None:
            return spec(method=Method.EMA_NTI_NARROW_ABE, acceptance=override)

        if end is Endpoint.AUC:
            return spec(
                method=Method.EMA_NTI_NARROW_ABE,
                acceptance=_interval(
                    90.00,
                    111.11,
                    EMA_BIOEQUIVALENCE,
                    "EMA: narrowed interval for AUC of an NTI drug",
                    VerificationStatus.VERIFIED,
                ),
            )

        if end is Endpoint.CMAX:
            raise SpecificationRequired(
                "EMA narrows Cmax for an NTI drug only when Cmax is itself "
                "important for safety, efficacy or therapeutic drug "
                "monitoring, and that is decided per product: ciclosporin "
                "narrows both AUC and Cmax, colchicine narrows AUC and leaves "
                "Cmax at 80.00-125.00. Supply a ProductOverride giving the "
                "Cmax limits from the applicable product-specific guidance. "
                "Neither default is safe to assume."
            )

        raise SpecificationRequired(
            f"EMA NTI limits for endpoint {end} are not defined by the general "
            "guideline. Supply a ProductOverride."
        )

    if cls is DrugClass.HIGHLY_VARIABLE:
        if jur is Jurisdiction.FDA:
            return spec(
                method=Method.FDA_HVD_RSABE,
                acceptance=None,
                required_design="partially or fully replicated crossover",
                constants=FDA_HVD_CONSTANTS,
                notes=(
                    "FDA switches to reference-scaled ABE at an ESTIMATED sWR "
                    "of 0.294 or above, and additionally constrains the point "
                    "estimate to 0.8000-1.2500. Below the threshold, "
                    "conventional ABE applies for that endpoint. Phase 2A."
                ),
            )
        return spec(
            method=Method.EMA_HVD_ABEL,
            acceptance=None,
            required_design="3-period or 4-period replicate crossover",
            constants=EMA_HVD_CONSTANTS,
            notes=(
                "EMA widens the acceptance LIMITS and then applies an ordinary "
                "interval test: [U, L] = exp[+/- 0.760 * sWR], capped at "
                "69.84-143.19%, with the GMR additionally required to fall "
                "within 80.00-125.00%. That is a different procedure from "
                "FDA's RSABE, which scales a CRITERION, and not a relabelling "
                "of it. Widening applies to Cmax ONLY, and only where CVwR "
                "exceeds 30 percent - strictly, on the CV scale. Section "
                "4.1.10; ICH M13A does not address replicate designs, so the "
                "2010 guideline continues to apply (EMA/531548/2024)."
            ),
        )

    raise NotApplicable(f"Unhandled drug class: {cls}")
