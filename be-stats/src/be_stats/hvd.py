"""FDA highly variable drugs: which test applies, and what it concludes.

THE WHOLE FLOW, PER PK ENDPOINT

    validated replicate dataset
        -> sWR                        (reference_variance.py, PR #55)
        -> switching rule at 0.294    (spec.fda_hvd_method_for)
        -> STANDARD_ABE or FDA_HVD_RSABE
        -> an endpoint decision with every component visible

THE METHOD IS CHOSEN PER ENDPOINT, NOT PER STUDY

Appendix G step 1 says "determine BE for the individual PK parameter(s)", and
III.C says the analysis is carried out "for both AUC and Cmax". So AUC may take
ordinary average BE while Cmax is reference-scaled, in the same study, from the
same subjects. Classifying a study as highly variable on its worst endpoint and
then scaling everything would give the well-behaved endpoint a wider acceptance
range than it has earned, which is the direction that matters.

`assess_endpoint` therefore takes one endpoint's dataset and knows nothing about
any other.

TWO CRITERIA, BOTH REQUIRED

Appendix G step 3 is explicit that BOTH must hold:

    a. the 95% upper confidence bound for (mu_T - mu_R)^2 - theta*sigma_WR^2
       must be <= 0
    b. the point estimate of the T/R geometric mean ratio must fall within
       [0.8000, 1.2500]

Reducing that to one boolean is how the second one quietly disappears - the
scaled criterion is the elaborate part, and it is easy to treat it as the
answer. `RsabeResult` exposes each separately and computes `passes` from both.

WHAT EACH BRANCH CAN AND CANNOT DECIDE - STATE THIS PRECISELY OR NOT AT ALL

The scaled branch (`sWR >= 0.294`) is complete for both replicate designs.

The unscaled branch (`sWR < 0.294`) is Appendix C's mixed model, and its support
is deliberately UNEVEN. Saying "Appendix C is implemented" would be true of the
fully replicate case and false of the partial replicate one, and a reader
choosing a design on the strength of that sentence would be misled:

    FULLY REPLICATE     decides, given the raw observations. Validated against
                        EMA's published SAS Method C output for the model EMA
                        attributes to FDA, and cross-checked against
                        ReplicateBE.jl. See `appendix_c.py`.

    PARTIAL REPLICATE   REFUSES. `decided = False`, `passes = None`. Not for
                        want of arithmetic - the fit would produce a number -
                        but because PR #61 found no trustworthy oracle for it:
                        ReplicateBE.jl reproduces SAS exactly on the fully
                        replicate design and differs by 2.94 denominator df on
                        the partial replicate one, a design its own validation
                        claim never covered. The correct partial replicate
                        Satterthwaite df is NOT DETERMINED.

    NO RAW OBSERVATIONS Refuses either way. Appendix C is an AVAILABLE CASE
                        analysis and `ReplicateDataset` has already dropped
                        subjects Appendix G's sWR could not use, so they cannot
                        be recovered from it. Pass `observations=`.

In every refusing case the endpoint comes back with its sWR, its selected
method and its treatment contrast, and `decided = False`. It never comes back
with a verdict computed from the reference-scaled construction's intermediate,
which is what an early version of this module did.

WHAT THIS MODULE DOES NOT DO

FDA narrow therapeutic index drugs (Appendix F) and EMA's ABEL are different
procedures and are not here. Each lives in its own module with its own
constants and its own result type, and this one names neither - a test asserts
that the FDA modules do not so much as mention the EMA one, because a
polymorphic "highly variable result" shared between regulators would have to
carry FDA's 0.294 and EMA's separate CV-scale threshold in the same object.
"""

from __future__ import annotations

from dataclasses import dataclass

from be_stats.abe import AbeResult
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.howe import howe_upper_bound
from be_stats.provenance import RegulatoryValue
from be_stats.reference_variance import (
    ReferenceVarianceResult,
    estimate_reference_variance,
)
from be_stats.replicate import ReplicateDataset, ReplicateDesign
from be_stats.replicate_abe import replicate_abe_unavailable
from be_stats.spec import (
    FDA_HVD_CONSTANTS,
    BeSpec,
    DrugClass,
    Endpoint,
    HvdApplicability,
    HvdClass,
    HvdClassification,
    Jurisdiction,
    Method,
    NtiStatus,
    fda_hvd_applicability,
    fda_hvd_classification,
    fda_hvd_method_for,
    fda_hvd_theta,
    reconcile_nti_status,
    resolve_be_spec,
)
from be_stats.treatment_contrast import (
    TreatmentContrastResult,
    estimate_treatment_contrast,
)


def _applicability_explanation(applicability: HvdApplicability) -> str:
    """One sentence per applicability outcome, shared by summary and provenance.

    One function rather than two strings: the wording is the deliverable here,
    and two copies would drift until the summary and the provenance disagreed
    about whether a decision had been issued.
    """
    if applicability is HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX:
        return (
            "FDA HVD procedure not applicable: the product is identified as "
            "narrow therapeutic index. Use the FDA NTI procedure."
        )
    if applicability is HvdApplicability.UNDETERMINED_NTI_NOT_STATED:
        return (
            "FDA HVD applicability cannot be determined because NTI status was "
            "not specified. Variability estimates are descriptive only; no "
            "regulatory BE decision was issued."
        )
    return "FDA HVD procedure applies: the product is confirmed not to be a narrow therapeutic index drug."


class NotDecidable(Exception):
    """The endpoint cannot be decided, and the result says why.

    Raised only where returning a result would mean inventing a component.
    Everything a diagnostic can express is expressed as a diagnostic instead.
    """


# ------------------------------------------------------- the two criteria ---


@dataclass(frozen=True, slots=True)
class ScaledCriterion:
    """Appendix G step 3a, with Howe's Approximation I left visible.

    Every intermediate FDA names is a field here. A reviewer reproducing this
    from the guidance works through `x`, `bound_x`, `y`, `bound_y` in that
    order, and a result that showed only the final bound would force them to
    re-derive the chain to find a disagreement.
    """

    #: x = estimate^2 - stderr^2
    x: float
    #: bound_x = max(|CI lower|, |CI upper|)^2, from the 90% log-scale interval
    bound_x: float
    #: y = -theta * sWR^2
    y: float
    #: bound_y = y * df_D / chisq_{0.95}(df_D)
    bound_y: float

    theta: float
    sigma_w0: float
    #: sWR^2 as it entered the criterion.
    reference_variance: float
    #: The degrees of freedom of the REFERENCE VARIANCE, which is what scales
    #: `y`. Not the contrast's - Appendix G uses them for different pieces.
    reference_variance_df: int

    #: The 95% upper confidence bound for (mu_T - mu_R)^2 - theta*sigma_WR^2.
    upper_confidence_bound: float

    @property
    def passes(self) -> bool:
        """FDA: the bound "must be <= 0". The boundary passes."""
        return self.upper_confidence_bound <= 0.0

    def explain(self) -> list[str]:
        return [
            f"x = estimate^2 - SE^2 = {self.x:.8f}",
            f"bound_x = max(|CI|)^2 = {self.bound_x:.8f}",
            f"theta = [ln(1.25)/{self.sigma_w0}]^2 = {self.theta:.8f}",
            f"y = -theta * sWR^2 = {self.y:.8f}",
            f"bound_y = y * {self.reference_variance_df} / "
            f"chisq_0.95({self.reference_variance_df}) = {self.bound_y:.8f}",
            f"critbound = (x+y) + sqrt((bound_x-x)^2 + (bound_y-y)^2) = "
            f"{self.upper_confidence_bound:.8f}",
            f"criterion A: {self.upper_confidence_bound:.8f} <= 0 -> "
            f"{'PASS' if self.passes else 'FAIL'}",
        ]


@dataclass(frozen=True, slots=True)
class PointEstimateConstraint:
    """Appendix G step 3b. The criterion that gets forgotten.

    Reference scaling widens the acceptance region as reference variability
    grows, without limit. This is the stop on it: however variable the
    reference, the observed T/R ratio must still sit within 80.00-125.00%.
    """

    geometric_mean_ratio: float
    lower_limit: float
    upper_limit: float

    @property
    def passes(self) -> bool:
        """FDA: "must fall within [0.8000, 1.2500]". Both boundaries pass."""
        return self.lower_limit <= self.geometric_mean_ratio <= self.upper_limit

    def explain(self) -> list[str]:
        return [
            f"criterion B: {self.lower_limit:.4f} <= "
            f"{self.geometric_mean_ratio:.6f} <= {self.upper_limit:.4f} -> "
            f"{'PASS' if self.passes else 'FAIL'}"
        ]


@dataclass(frozen=True, slots=True)
class RsabeResult:
    """Both criteria, and the conjunction of them. Never one boolean."""

    scaled_criterion: ScaledCriterion
    point_estimate_constraint: PointEstimateConstraint

    reference_variance: ReferenceVarianceResult
    treatment_contrast: TreatmentContrastResult

    @property
    def passes(self) -> bool:
        return (
            self.scaled_criterion.passes
            and self.point_estimate_constraint.passes
        )

    def explain(self) -> list[str]:
        lines = self.scaled_criterion.explain()
        lines += self.point_estimate_constraint.explain()
        lines.append(
            "both criteria are required: "
            f"A {'PASS' if self.scaled_criterion.passes else 'FAIL'} and "
            f"B {'PASS' if self.point_estimate_constraint.passes else 'FAIL'} "
            f"-> {'PASS' if self.passes else 'FAIL'}"
        )
        return lines


# ---------------------------------------------------------- the criterion ---


def scaled_criterion(
    *,
    contrast: TreatmentContrastResult,
    reference_variance: ReferenceVarianceResult,
) -> ScaledCriterion:
    """Appendix G step 2, following the guidance's own SAS line by line.

        x        = estimate**2 - stderr**2
        bound_x  = (max(|LowerCL|, |UpperCL|))**2
        theta    = ((log(1.25))/0.25)**2
        y        = -theta*s2wr
        bound_y  = y*dfd/cinv(0.95, dfd)
        critbound = (x+y) + sqrt(((bound_x-x)**2) + ((bound_y-y)**2))

    THE CHI-SQUARE DIRECTION, PINNED

    `cinv(0.95, dfd)` is the 95th PERCENTILE of the chi-square distribution -
    SAS's inverse CDF, not an upper-tail quantile. It is easy to reach for
    `chi2.isf(0.95, df)` instead, which is the 5th percentile, and the mistake
    is nearly invisible: it produces a `bound_y` that is still negative and
    still ordered sensibly, but roughly `chisq_95/chisq_05` times too far from
    zero, which for 20 df is a factor of about 3.

    The direction is self-checkable, and a test checks it. `y` is negative, and
    `df/chisq_95(df) < 1`, so `bound_y` is CLOSER TO ZERO than `y`: it is an
    upper bound on `-theta*sigma_WR^2`, which is a LOWER bound on
    `sigma_WR^2` - the conservative direction, since a smaller reference
    variance means less scaling and a harder criterion.

    The degrees of freedom here are the REFERENCE VARIANCE's, not the
    contrast's. The two models are fitted on different subject sets whenever a
    subject is missing its test measurement.
    """
    if not contrast.estimable:
        raise NotDecidable("The treatment contrast is not estimable.")
    if not reference_variance.estimable or reference_variance.variance_wr is None:
        raise NotDecidable("sWR is not estimable.")

    # The arithmetic lives in `howe.py`, shared with the narrow-therapeutic-
    # index procedure. Shared on evidence rather than resemblance: the two
    # appendices' SAS were compared line by line and differ only in `theta`,
    # which each supplies from its own verified constants. This wrapper knows
    # the highly-variable constants and cites Appendix G; it does not pass a
    # mode flag to a generic routine.
    bound = howe_upper_bound(
        estimate=contrast.estimate,
        standard_error=contrast.standard_error,
        ci_lower=contrast.ci_lower,
        ci_upper=contrast.ci_upper,
        reference_variance=reference_variance.variance_wr,
        reference_variance_df=reference_variance.degrees_of_freedom,
        theta=fda_hvd_theta(),
    )

    return ScaledCriterion(
        x=bound.x,
        bound_x=bound.bound_x,
        y=bound.y,
        bound_y=bound.bound_y,
        theta=bound.theta,
        sigma_w0=FDA_HVD_CONSTANTS["sigma_w0"].value,
        reference_variance=bound.reference_variance,
        reference_variance_df=bound.reference_variance_df,
        upper_confidence_bound=bound.upper_confidence_bound,
    )


def point_estimate_constraint(
    contrast: TreatmentContrastResult,
) -> PointEstimateConstraint:
    """Appendix G step 3b, against the verified constants."""
    return PointEstimateConstraint(
        geometric_mean_ratio=contrast.point_estimate,
        lower_limit=FDA_HVD_CONSTANTS["point_estimate_lower"].value,
        upper_limit=FDA_HVD_CONSTANTS["point_estimate_upper"].value,
    )


# ------------------------------------------------------ endpoint decision ---


@dataclass(frozen=True, slots=True)
class FdaHvdResult:
    """One PK endpoint, decided by whichever method its own sWR selected.

    Exactly one of `standard_abe_result` and `rsabe_result` is populated. The
    other is `None` rather than a zeroed structure: a field that exists but
    means nothing is a field something will eventually read.
    """

    endpoint: str
    design: ReplicateDesign

    swr: float | None
    cv_wr: float | None
    switching_threshold: RegulatoryValue
    selected_method: Method | None

    reference_variance: ReferenceVarianceResult
    treatment_contrast: TreatmentContrastResult | None = None

    #: III.C's classification of the DRUG, reported and never routed by.
    #:
    #: These are the two things most often conflated - the classification and
    #: the selected method - so they are both on this result, and a reader who
    #: can see both at once can see that they answer different questions and
    #: occasionally disagree. `rsabe_applicable` is derived from the method,
    #: never from this.
    #:
    #: `None` means the classification was not requested, which is different
    #: from a classification of NOT_CLASSIFIED - that one was requested and
    #: came back undetermined.
    hvd_classification: HvdClassification | None = None

    #: Whether FDA's HVD procedure may decide this PRODUCT at all, settled
    #: before any observation is read. Only `APPLICABLE` permits a verdict, and
    #: `__post_init__` enforces that rather than leaving it to callers.
    applicability: HvdApplicability = HvdApplicability.APPLICABLE

    standard_abe_result: AbeResult | None = None
    rsabe_result: RsabeResult | None = None
    #: The unscaled branch, when it decided. Appendix C's mixed model, for a
    #: fully replicate design. Separate from `standard_abe_result`, which is
    #: Phase 1's 2x2 crossover TOST and is a different model on a different
    #: design - collapsing the two would lose exactly the distinction
    #: `replicate_abe.py` spent four PRs defending.
    appendix_c_result: object | None = None

    decided: bool = True
    diagnostics: tuple[Diagnostic, ...] = ()

    #: n for sWR and n for the contrast are reported separately because they
    #: can legitimately differ - a subject missing its test measurement has no
    #: contrast and may still have both reference replicates.
    n_for_swr: int = 0
    n_for_treatment_contrast: int = 0

    #: Kept apart because Appendix G uses them for different pieces of the
    #: upper-bound construction.
    reference_variance_df: int = 0
    treatment_contrast_df: float = 0.0

    def __post_init__(self) -> None:
        """The contradictory state made UNCONSTRUCTIBLE, not merely untested.

        Independent review of the first version of this PR found that it could
        return, on one object:

            hvd_classification = EXCLUDED_NARROW_THERAPEUTIC_INDEX
            selected_method    = FDA_HVD_RSABE
            decided            = True
            passes             = True

        - a bioequivalence verdict from FDA's highly variable procedure for a
        product FDA assesses under Appendix F. Every individual field was
        computed correctly and the object as a whole asserted something false.

        A test would have caught the paths the test happened to cover. This
        raises in the constructor, so no path can produce it: a refused
        applicability cannot carry a method, a branch result or a decision, and
        a decision cannot exist without an applicability that permits one.

        Raising from a frozen dataclass's `__post_init__` is the only place this
        can live and still be unavoidable. Every return in this module goes
        through it.
        """
        if self.applicability.permits_verdict:
            return

        if self.decided:
            raise NotDecidable(
                f"a decided result was constructed with applicability "
                f"{self.applicability}. FDA's highly variable procedure does "
                "not apply to this product, so there is no verdict for it to "
                "report."
            )
        for field, value in (
            ("selected_method", self.selected_method),
            ("rsabe_result", self.rsabe_result),
            ("appendix_c_result", self.appendix_c_result),
            ("standard_abe_result", self.standard_abe_result),
        ):
            if value is not None:
                raise NotDecidable(
                    f"applicability is {self.applicability} and {field} is "
                    f"{value!r}. A product the procedure does not apply to "
                    "must not be carrying the analysis it would have received; "
                    "that is the dual state that made a contradictory result "
                    "possible."
                )

    @property
    def rsabe_applicable(self) -> bool | None:
        """Did FDA's switch select reference scaling? `None` before it ran.

        Read from `selected_method`, which was set by `fda_hvd_method_for` from
        the estimated sWR. NOT from `hvd_classification`: a drug classified
        highly variable whose study came out at sWR 0.2937 is analysed by
        ordinary average BE, and this property must say so.
        """
        if self.selected_method is None:
            return None
        return self.selected_method is Method.FDA_HVD_RSABE

    @property
    def swr2(self) -> float | None:
        """sWR^2 as it entered the criterion. Delegated, never stored twice."""
        return self.reference_variance.variance_wr

    @property
    def cv_wr_percent(self) -> float | None:
        return None if self.cv_wr is None else 100.0 * self.cv_wr

    @property
    def rsabe_criterion(self) -> float | None:
        """The 95% upper confidence bound, or None if RSABE did not run."""
        if self.rsabe_result is None:
            return None
        return self.rsabe_result.scaled_criterion.upper_confidence_bound

    @property
    def rsabe_limit(self) -> float | None:
        """What that bound must not exceed. Appendix G step 3a: zero.

        A named property rather than a literal at the comparison site, so the
        report can print the criterion and its limit side by side without
        either being re-typed.
        """
        return None if self.rsabe_result is None else 0.0

    @property
    def rsabe_passes(self) -> bool | None:
        if self.rsabe_result is None:
            return None
        return self.rsabe_result.scaled_criterion.passes

    @property
    def gmr(self) -> float | None:
        """The T/R geometric mean ratio the point-estimate constraint tests."""
        if self.treatment_contrast is None:
            return None
        return self.treatment_contrast.point_estimate

    @property
    def point_estimate_passes(self) -> bool | None:
        """Criterion B alone. Separate from `passes`, which is the conjunction.

        Exposed at this level because a caller reading only `passes` cannot
        tell which of the two criteria failed, and criterion B failing means
        something different about the product than criterion A failing.
        """
        if self.rsabe_result is None:
            return None
        return self.rsabe_result.point_estimate_constraint.passes

    @property
    def passes(self) -> bool | None:
        """Whether the endpoint met its criteria. `None` when not decided.

        Deliberately not a bare `bool`: an undecidable endpoint returning
        `False` would be indistinguishable from a failing one.
        """
        if not self.decided:
            return None
        if self.rsabe_result is not None:
            return self.rsabe_result.passes
        if self.appendix_c_result is not None:
            return self.appendix_c_result.passes
        if self.standard_abe_result is not None:
            return self.standard_abe_result.within_acceptance_interval
        return None

    def provenance(self) -> list[str]:
        lines: list[str] = []
        if not self.applicability.permits_verdict:
            # FIRST, and on its own. A reader who stops after one line must
            # come away knowing no decision was issued - which is the opposite
            # of what they would conclude from a classification line followed
            # by a switching-rule line.
            lines.append(_applicability_explanation(self.applicability))
        if self.hvd_classification is not None:
            lines += self.hvd_classification.explain()
        if not self.applicability.permits_verdict:
            lines.append(
                "the variability figures below are DESCRIPTIVE ONLY. No "
                "bioequivalence decision was issued and no analysis method was "
                "selected, because FDA's highly variable procedure was not "
                "established to apply to this product."
            )
            lines += self.reference_variance.provenance()
            return lines
        lines += [
            f"switching rule: {self.switching_threshold.explain()}",
            f"observed sWR = {self.swr}, threshold "
            f"{self.switching_threshold.value} -> {self.selected_method}",
        ]
        # Said explicitly, because the two lines above and the classification
        # lines above THEM sit next to each other and the reader's instinct is
        # to join them with "therefore".
        if self.hvd_classification is not None:
            lines.append(
                "the classification above did not select this method: FDA "
                "selects the analysis from the estimated sWR on the sWR scale, "
                "and the classification describes the drug on the CV scale."
            )
        lines += self.reference_variance.provenance()
        if self.treatment_contrast is not None:
            lines += self.treatment_contrast.provenance()
        return lines

    def summary(self) -> str:
        if not self.applicability.permits_verdict:
            # The refusal, the reason, and the descriptive figures. No method
            # line and no criteria block, because there are none.
            cv = (
                None
                if self.hvd_classification is None
                else self.hvd_classification.cv_wr_percent
            )
            body = (
                f"{self.endpoint} ({self.design})\n"
                f"  NO BE DECISION ISSUED - {self.applicability}\n"
                f"  {_applicability_explanation(self.applicability)}\n"
                f"  descriptive only: sWR = "
                f"{'n/a' if self.swr is None else f'{self.swr:.6f}'}, "
                f"CVwR = {'n/a' if cv is None else f'{cv:.2f}%'}, "
                f"n = {self.n_for_swr}, df = {self.reference_variance_df}\n"
            )
            if self.hvd_classification is not None:
                body += (
                    f"  drug classification (III.C, CV scale): "
                    f"{self.hvd_classification.hvd_class}\n"
                )
            if self.diagnostics:
                body += "  diagnostics:\n" + "\n".join(
                    f"    {d}" for d in self.diagnostics
                )
            return body

        classification = ""
        if self.hvd_classification is not None:
            cv = self.hvd_classification.cv_wr_percent
            classification = (
                f"  drug classification (III.C, CV scale): "
                f"{self.hvd_classification.hvd_class}"
                f"{'' if cv is None else f' at CVwR {cv:.2f}%'}\n"
            )
        head = (
            f"{self.endpoint} ({self.design})\n"
            + classification
            + f"  sWR = {self.swr if self.swr is None else f'{self.swr:.6f}'}, "
            f"threshold {self.switching_threshold.value} -> "
            f"{self.selected_method}\n"
            f"  n for sWR = {self.n_for_swr}, "
            f"n for contrast = {self.n_for_treatment_contrast}\n"
            f"  reference variance df = {self.reference_variance_df}, "
            f"contrast df = {self.treatment_contrast_df}\n"
        )
        if self.rsabe_result is not None:
            body = "\n".join(f"  {line}" for line in self.rsabe_result.explain())
        elif self.standard_abe_result is not None:
            body = f"  {self.standard_abe_result.summary()}"
        else:
            body = "  NOT DECIDED"
        if self.diagnostics:
            body += "\n  diagnostics:\n" + "\n".join(
                f"    {d}" for d in self.diagnostics
            )
        return head + body


def _hvd_spec() -> BeSpec:
    """The unscaled 80.00-125.00% interval, for the standard branch.

    Resolved through `resolve_be_spec` with the STANDARD drug class rather than
    HIGHLY_VARIABLE: below the threshold FDA applies the ordinary average BE
    procedure, and asking for the highly-variable spec would return a method
    that refuses. The interval carries its own provenance either way.
    """
    return resolve_be_spec(
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.STANDARD,
        endpoint=Endpoint.OTHER,
    )


def _applicability_refusal(
    applicability: HvdApplicability, classification: HvdClassification
) -> Diagnostic:
    """Why no verdict was issued, in words that name the next step.

    FATAL, not advisory. The analysis did not produce a regulatory decision,
    which is what this package's FATAL severity means; an ADVISORY here would
    say "recorded, changed nothing" about the one condition that changed
    everything. The first version of this PR attached exactly that advisory.
    """
    if applicability is HvdApplicability.NOT_APPLICABLE_NARROW_THERAPEUTIC_INDEX:
        return Diagnostic(
            DiagnosticCode.FDA_HVD_NOT_APPLICABLE_NTI,
            Severity.FATAL,
            None,
            "FDA HVD procedure not applicable: the product is identified as "
            "narrow therapeutic index. Use the FDA NTI procedure. III.C "
            "defines a highly variable drug as one with within-subject "
            "variability of 30 percent or greater AND that is not considered "
            "an NTI drug, and FDA assesses NTI drugs under Appendix F - a "
            "reference-scaled criterion on sigma_W0 = 0.10, plus the unscaled "
            "80.00-125.00 limits, plus a bound on the ratio of within-subject "
            "variances. Reference variability is reported below as a "
            "descriptive quantity and no bioequivalence decision was issued",
            {
                "applicability": str(applicability),
                "hvd_classification": str(classification.hvd_class),
                "required_procedure": "FDA Appendix F (narrow therapeutic index)",
                "cv_wr_percent": classification.cv_wr_percent,
            },
        )
    return Diagnostic(
        DiagnosticCode.FDA_HVD_APPLICABILITY_REQUIRES_NTI_STATUS,
        Severity.FATAL,
        None,
        "FDA HVD applicability cannot be determined because NTI status was not "
        "specified. Variability estimates are descriptive only; no regulatory "
        "BE decision was issued. III.C's definition has two conjuncts and the "
        "second - that the drug is not a narrow therapeutic index drug - is a "
        "property of the product that no dataset carries. An unstated status "
        "is not an assertion of non-NTI, and assuming one would decide this "
        "endpoint from Appendix G whenever the assumption was wrong. Supply "
        "nti_status, or a spec whose drug_class states the product's class",
        {
            "applicability": str(applicability),
            "hvd_classification": str(classification.hvd_class),
            "cv_wr_percent": classification.cv_wr_percent,
            "meets_variability_criterion": (
                classification.meets_variability_criterion
            ),
        },
    )


def assess_endpoint(
    dataset: ReplicateDataset,
    *,
    spec: BeSpec | None = None,
    observations: list | None = None,
    nti_status: NtiStatus = NtiStatus.NOT_STATED,
) -> FdaHvdResult:
    """The whole Appendix G flow for one PK endpoint.

    Estimates sWR, applies FDA's switching rule to it, and runs whichever
    procedure that selects. Every component is returned; nothing is collapsed
    to a verdict on the way.

    WHY `observations` EXISTS, AND WHY THE DATASET IS NOT ENOUGH

    Below the switch, FDA routes to Appendix C - and Appendix C is an AVAILABLE
    CASE analysis that uses all observed data, while `ReplicateDataset` has
    already excluded any subject missing a reference replicate because that is
    what Appendix G's sWR requires. Those excluded subjects are gone and cannot
    be recovered from the dataset, so the raw rows have to be supplied
    separately for the unscaled branch to be answerable at all.

    Two inclusion rules, one study, and the difference is regulatory rather
    than cosmetic - which PR #60 established for EMA and PR #61 confirmed here
    from FDA section III.

    Omitting `observations` is legitimate: the scaled branch does not need
    them, and the unscaled branch then refuses with a diagnostic saying what is
    missing rather than guessing.

    `nti_status` GATES THE VERDICT - A CORRECTION

    An earlier version of this function documented, in this docstring, that
    `nti_status` "REACHES THE CLASSIFICATION AND NOTHING ELSE" and that leaving
    it unset "changes no number, no branch and no verdict". That was accurate
    about the code and wrong about the regulation, and independent review caught
    it.

    III.C defines a highly variable drug as one whose within-subject variability
    is 30 percent or greater AND that is not considered an NTI drug, and FDA
    assesses NTI drugs under Appendix F: a different procedure, a different
    scaling constant, two additional criteria. A function that returns
    `FDA_HVD_RSABE`, `decided=True` and a pass for a product known to be NTI has
    answered from the wrong appendix, and the old code could do exactly that
    while simultaneously reporting the classification
    `EXCLUDED_NARROW_THERAPEUTIC_INDEX` on the same object.

    So applicability is now a GATE, evaluated before the switch and independent
    of the data:

        NOT_NARROW_THERAPEUTIC_INDEX  the flow below runs unchanged. Not one
                                      number moves.
        NARROW_THERAPEUTIC_INDEX      no verdict. sWR and CVwR are reported as
                                      descriptive quantities; the product
                                      belongs to the NTI procedure.
        NOT_STATED                    no verdict. Applicability is undetermined,
                                      and an unstated NTI status is not an
                                      assertion of non-NTI.

    WHAT THE GATE DOES NOT DO

    It does not route by CVwR, it does not touch the 0.294 switch, and it does
    not collapse the classification into the decision. For a confirmed non-NTI
    product the disagreement window is intact: CVwR at or above 30 percent with
    sWR below 0.294 is a highly variable drug taking ordinary average BE.

    It also does not call the NTI engine. `nti.py` owns that procedure, and a
    cross-call from here would put two regulatory methods in one module.
    """
    threshold = FDA_HVD_CONSTANTS["swr_switching_threshold"]

    # ONE answer about the product, from both places that can carry one, or a
    # refusal. Before any estimation: a contradiction about the product's
    # regulatory class is not something to discover after computing a verdict.
    resolved_nti = reconcile_nti_status(spec=spec, nti_status=nti_status)
    applicability = fda_hvd_applicability(resolved_nti)

    variance = estimate_reference_variance(dataset)
    diagnostics = list(variance.diagnostics)

    # III.C's definition, evaluated on the CV scale from the SAME estimate the
    # switch will read on the sWR scale. Computed BEFORE the switch and passed
    # to neither it nor any branch below: it is an output, not an input.
    classification = fda_hvd_classification(
        cv_wr_percent=variance.cv_wr_percent, nti_status=resolved_nti
    )

    if not applicability.permits_verdict:
        # THE GATE. Descriptive quantities are reported; nothing decisional is.
        #
        # No treatment contrast is estimated here, deliberately. sWR and CVwR
        # describe the reference's variability and carry no comparison; a point
        # estimate of T against R is the shape of an answer, and this product is
        # not one this procedure may answer for.
        diagnostics.append(_applicability_refusal(applicability, classification))
        return FdaHvdResult(
            endpoint=dataset.endpoint,
            design=dataset.design,
            swr=variance.swr,
            cv_wr=variance.cv_wr,
            switching_threshold=threshold,
            selected_method=None,
            reference_variance=variance,
            hvd_classification=classification,
            applicability=applicability,
            decided=False,
            diagnostics=tuple(diagnostics),
            n_for_swr=variance.n_subjects,
            reference_variance_df=variance.degrees_of_freedom,
        )

    if not variance.estimable or variance.swr is None:
        return FdaHvdResult(
            endpoint=dataset.endpoint,
            design=dataset.design,
            swr=None,
            cv_wr=None,
            switching_threshold=threshold,
            selected_method=None,
            reference_variance=variance,
            hvd_classification=classification,
            applicability=applicability,
            decided=False,
            diagnostics=tuple(diagnostics),
            n_for_swr=variance.n_subjects,
            reference_variance_df=variance.degrees_of_freedom,
        )

    # THE SWITCH. Applied to the estimated sWR itself - never to a displayed or
    # rounded CVwR, which would move the boundary by whatever the display
    # rounding happened to be.
    method = fda_hvd_method_for(variance.swr)

    contrast = estimate_treatment_contrast(dataset)
    diagnostics += [
        d for d in contrast.diagnostics if d not in variance.diagnostics
    ]

    common = dict(
        endpoint=dataset.endpoint,
        design=dataset.design,
        swr=variance.swr,
        cv_wr=variance.cv_wr,
        switching_threshold=threshold,
        selected_method=method,
        reference_variance=variance,
        treatment_contrast=contrast,
        hvd_classification=classification,
        applicability=applicability,
        n_for_swr=variance.n_subjects,
        n_for_treatment_contrast=contrast.n_subjects,
        reference_variance_df=variance.degrees_of_freedom,
        treatment_contrast_df=contrast.degrees_of_freedom,
    )

    if not contrast.estimable:
        return FdaHvdResult(
            **common, decided=False, diagnostics=tuple(diagnostics)
        )

    if method is Method.STANDARD_ABE:
        # THE UNSCALED BRANCH REFUSES, AND HERE IS WHY.
        #
        # Appendix G step 1a routes here, saying to use the two one-sided tests
        # procedure. It does not name a model, and Appendix C does: a mixed
        # model on the subject-period observations with fixed effects for
        # sequence, PERIOD and treatment, an unstructured subject-by-formulation
        # covariance, treatment-specific residual variances, and Satterthwaite
        # degrees of freedom from all five covariance parameters.
        #
        # An earlier version of this module ran TOST on the Appendix G `ilat`
        # contrast instead and marked the capability EXPERIMENTAL. That was the
        # wrong trade: a status field does not travel with a number, and the
        # number was a bioequivalence verdict computed from a different model.
        # `replicate_abe.py` records the model that has to be fitted and why it
        # is not fitted here.
        #
        # THE UNSCALED BRANCH NOW DECIDES - FOR FULLY REPLICATE DESIGNS.
        #
        # The paragraph above is the history and it is kept because it is the
        # reason this took four PRs. Appendix C is implemented as of the
        # full-replicate release, so a fully replicate study below the switch
        # gets a real verdict from the model FDA actually specifies rather than
        # a refusal.
        #
        # THREE WAYS THIS STILL DOES NOT DECIDE, ALL OF THEM DELIBERATE:
        #
        #   no `observations`  Appendix C is available-case and needs the raw
        #                      rows; `dataset` has already dropped subjects
        #                      that Appendix G excluded.
        #   partial replicate  no trustworthy oracle exists for its
        #                      Satterthwaite df - VAL-FDA-APPENDIX-C-002.
        #   the fit refuses    a degenerate covariance for this contrast.
        #
        # In every one of them `decided` stays False and `passes` stays None.
        from be_stats.appendix_c import (
            SUPPORTED_DESIGNS,
            analyse_replicate_abe_full,
        )

        if observations is None:
            diagnostics.append(replicate_abe_unavailable(dataset))
            return FdaHvdResult(
                **common, decided=False, diagnostics=tuple(diagnostics)
            )

        appendix_c = analyse_replicate_abe_full(observations)
        diagnostics.extend(appendix_c.diagnostics)
        if not appendix_c.decided:
            return FdaHvdResult(
                **common, decided=False, diagnostics=tuple(diagnostics)
            )

        _ = SUPPORTED_DESIGNS
        return FdaHvdResult(
            **common,
            appendix_c_result=appendix_c,
            decided=True,
            diagnostics=tuple(diagnostics),
        )

    rsabe = RsabeResult(
        scaled_criterion=scaled_criterion(
            contrast=contrast, reference_variance=variance
        ),
        point_estimate_constraint=point_estimate_constraint(contrast),
        reference_variance=variance,
        treatment_contrast=contrast,
    )
    return FdaHvdResult(
        **common, rsabe_result=rsabe, diagnostics=tuple(diagnostics)
    )


def assess_study(
    datasets: dict[str, ReplicateDataset],
    *,
    spec: BeSpec | None = None,
    nti_status: NtiStatus = NtiStatus.NOT_STATED,
) -> dict[str, FdaHvdResult]:
    """Every endpoint decided on its own sWR.

    A thin loop, and the reason it is a loop rather than a study-level
    classification: FDA determines the method "for the individual PK
    parameter". AUC and Cmax from the same subjects may take different
    procedures, and the endpoint with the lower reference variability must not
    inherit a scaled acceptance range from the one with more.

    `nti_status` is a property of the PRODUCT, so it is the one thing here that
    legitimately applies to every endpoint at once. Each endpoint still
    classifies on its OWN CVwR, so a study may well report AUC as not highly
    variable and Cmax as highly variable - which is the same per-endpoint logic
    the method selection follows, for the same reason.

    APPLICABILITY, BY CONTRAST, IS THE SAME FOR EVERY ENDPOINT

    It depends only on the product's NTI status, so an NTI product's AUC and
    Cmax are both refused, and an unstated status refuses both. There is no
    endpoint for which the wrong appendix becomes the right one.
    """
    return {
        endpoint: assess_endpoint(dataset, spec=spec, nti_status=nti_status)
        for endpoint, dataset in datasets.items()
    }
