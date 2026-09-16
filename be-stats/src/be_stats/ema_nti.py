"""EMA's narrow therapeutic index procedure: 4.1.9, and nothing borrowed.

WHAT THIS MODULE IMPLEMENTS

One regulatory procedure. For a product a clinician has classified as a narrow
therapeutic index drug, EMA tightens the acceptance interval - AUC always, Cmax
where Cmax is itself of particular importance for safety, efficacy or drug
level monitoring - and changes nothing else about the analysis. The model, the
90% confidence interval and the containment test are the ones any EMA
bioequivalence study uses. EMA moves the limits. It does not change the test.

THE THREE QUESTIONS, KEPT APART

    A  is the product an NTID?              `NtiStatus`, from the product's
                                            regulatory file, cross-checked
                                            against the routed spec
    B  which interval does this endpoint    `ema_nti_interval`: AUC always;
       get?                                 Cmax on `CmaxClinicalImportance`;
                                            nothing else addressed
    C  does the interval contain the CI?    one comparison, two decimal places

A is not derived from B and neither is derived from the data. EMA states in
terms that "it is not possible to define a set of criteria to categorise drugs
as narrow therapeutic index drugs (NTIDs) and it must be decided case by case
... based on clinical considerations", so there is no rule this engine could
implement that would answer A from a dataset, and it does not try.

WHY THERE IS NO "DEFAULT" FOR CMAX

EWP answered B oppositely for two NTIDs in one document. Ciclosporin: "for
which both AUC and Cmax are important for safety and efficacy, a narrowed
(90.00-111.11%) acceptance range should be applied for both AUC and Cmax".
Tacrolimus: "the bioequivalence acceptance criteria for tacrolimus should be
[90-111%] for AUC and [80-125%] for Cmax". Both are EMA/618604/2008 Rev. 13.
A default in either direction is a wrong answer for a real EMA product, so an
unstated importance yields no verdict rather than the more convenient one.

WHAT THIS MODULE IS NOT

It is not FDA's NTI procedure. Appendix F uses a fully replicate design, a
reference-scaled criterion, an unscaled criterion and a comparison of test and
reference within-subject variability, all three of which must hold. Nothing
here computes sigma_W0, Delta, theta or a variability ratio, and no FDA NTI
result can be built from an EMA NTI one. `test_ema_nti_applicability.py`
asserts that structurally, over this module's syntax tree, rather than by
searching its text - this docstring mentions sigma_W0 while saying it is
absent, and a text search cannot tell a disclaimer from a use.

It is not EMA's highly variable procedure either. 4.1.10 widens Cmax on
observed variability; 4.1.9 tightens on a clinical classification. A drug
cannot be routed to both - FDA's III.C excludes NTI drugs from the highly
variable class, and EMA's two sections address different products - and this
module shares no state with `ema_hvd`.

THE REGULATORY STACK, AS OF THIS RELEASE

ICH M13A came into effect on 25 January 2025, "formally superseding applicable
parts of" CPMP/EWP/QWP/1401/98 Rev. 1. It covers non-replicate study design and
data analysis, and it does NOT cover narrow therapeutic index drugs: EMA/531548
/2024 lists "drugs with narrow therapeutic index" among the Tier 3 topics
deferred to the future ICH M13C, and states that "the requirements of both ICH
M13A and the existing EMA Guideline read in conjunction may be applicable" to
them. So both documents are live here, each for what it covers:

    ICH M13A 2.2.3.2    the analysis model for a non-replicate crossover
    ICH M13A 2.2.4      the conventional 80.00-125.00% range
    EMA 4.1.8           the two-decimal comparison
    EMA 4.1.9           the tightened 90.00-111.11% range, and when it applies
    EMA PKWP Q&A        the per-product answers, themselves now to be read in
                        conjunction with M13A pending EMA's review

Neither "the 2010 guideline governs everything" nor "M13A superseded EMA NTI"
is true, and the provenance lines on every result say which document each part
of the decision came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from be_stats.abe import AbeResult, analyse_crossover, analyse_parallel
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE,
    Citation,
    RegulatoryValue,
    VerificationStatus,
)
from be_stats.regulatory_rounding import exact_decimal, round_half_up
from be_stats.spec import (
    AcceptanceInterval,
    BeSpec,
    CmaxClinicalImportance,
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
    nti_status_from_drug_class,
    reconcile_nti_status,
)
from be_stats.study import CrossoverStudy, DataError, ParallelStudy

#: The model each supported design is analysed with, named on the result.
#:
#: ICH M13A 2.2.3.2: "Randomised, non-replicate, crossover design studies
#: should be analysed using an appropriate parametric method, e.g., general
#: linear model (GLM) or mixed model", with "a summary of the testing of
#: sequence, subject within sequence, period, and formulation effects". The 2x2
#: closed form in `abe.analyse_crossover` is exactly what PROC GLM gives for
#: that model - see that module's header for the derivation - so the model is
#: named here by what it IS rather than by the function that computes it.
CROSSOVER_MODEL = (
    "ICH M13A 2.2.3.2 general linear model on log-transformed data, "
    "model = sequence + subject(sequence) + period + formulation"
)
#: M13A 2.2.3.4: "The statistical analysis for randomised, parallel design
#: studies should reflect independent samples."
PARALLEL_MODEL = (
    "ICH M13A 2.2.3.4 two independent samples on log-transformed data, "
    "pooled-variance t interval"
)

_MODELS: dict[str, str] = {
    "2x2 crossover": CROSSOVER_MODEL,
    "parallel": PARALLEL_MODEL,
}


class EmaNtiResultInconsistent(ValueError):
    """A result was built that the rule would not give.

    Raised by `EmaNtiResult.__post_init__`. The contradictions 4.1.9 makes
    impossible are made impossible to CONSTRUCT rather than merely never
    constructed, because a path-only guarantee does not survive a refactor.
    """


def _interval_contained(
    *, ci_lower_percent: float, ci_upper_percent: float, lower: float, upper: float
) -> bool:
    """THE comparison of a 90% CI with 4.1.9's limits. One definition.

    TWO DECIMAL PLACES, FOR BOTH INTERVALS

    4.1.8: "To be inside the acceptance interval the lower bound should be >=
    80.00% when rounded to two decimal places and the upper bound should be <=
    125.00% when rounded to two decimal places." 4.1.9 replaces WHICH interval
    applies - "the acceptance interval for AUC should be tightened to
    90.00-111.11%" - and says nothing about what containment means, because
    4.1.8 has already said it. Both of 4.1.9's limits are published to exactly
    two decimals, in the same document and the same style as 4.1.8's, and the
    PKWP Q&A repeats "(90.00-111.11%)" for ciclosporin. So the same comparison
    applies to both, through the same helper PR #85 introduced - there is one
    rounding implementation in this package and this is a caller of it.

    This differs from the WIDENED limits of 4.1.10, which are compared
    unrounded (VAL-EMA-ABEL-003), and the difference is a fact about the
    numbers rather than a preference: a widened limit is computed per study
    from exp(+/- k.sWR) and has no published two-decimal form to round against.
    4.1.9's limits are published constants.

    4.1.8's sentence names 80.00 and 125.00 and does not restate itself under
    4.1.9. That residual is VAL-EMA-NTI-001, recorded rather than resolved.
    """
    return (
        round_half_up(ci_lower_percent) >= exact_decimal(lower)
        and round_half_up(ci_upper_percent) <= exact_decimal(upper)
    )


@dataclass(frozen=True, slots=True)
class EmaNtiResult:
    """One endpoint under EMA 4.1.9, decided or explicitly not.

    Each question keeps its own field, and the answer to one is never readable
    as the answer to another:

        product     `nti_status`, `spec_drug_class`, `product_class`
        endpoint    `endpoint`
        Cmax fact   `cmax_importance`
        source      `product_override`, `interval_source`
        interval    `interval_status`, `applied_limits`
        design      `design`, `analysis_model`
        statistics  `treatment`
        verdict     `decided`, `passes`

    `__post_init__` re-runs the rule and refuses any object whose class,
    interval or verdict the rule would not give.
    """

    endpoint: Endpoint
    nti_status: NtiStatus
    spec_drug_class: DrugClass | None
    product_class: EmaNtiProductClass
    product_class_reason: str
    cmax_importance: CmaxClinicalImportance
    interval_status: EmaNtiIntervalStatus
    interval_reason: str
    #: The product-specific guidance supplied, if any. Present on the result
    #: because "which document set these limits" is part of the verdict.
    product_override: ProductOverride | None
    #: Where `applied_limits` came from: the general guideline or a named
    #: product-specific document.
    interval_source: str | None
    design: str | None
    analysis_model: str | None
    applied_limits: tuple[float, float] | None
    treatment: AbeResult | None
    decided: bool
    passes: bool | None
    diagnostics: tuple[Diagnostic, ...] = ()
    provenance_lines: tuple[str, ...] = ()
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: The method of the `BeSpec` the caller supplied, if one was.
    spec_method: Method | None = None

    def __post_init__(self) -> None:
        def refuse(message: str) -> None:
            raise EmaNtiResultInconsistent(f"{self.endpoint}: {message}")

        # METHOD IDENTITY. This engine executes one regulatory procedure. Which
        # interval applied is a separate fact and may not masquerade as a
        # different method: a confirmed NTID whose Cmax takes 80.00-125.00% was
        # still decided under 4.1.9, and is not STANDARD_ABE.
        if self.spec_method is not None and self.spec_method is not Method.EMA_NTI_NARROW_ABE:
            refuse(
                f"built for a spec selecting {self.spec_method}; this engine "
                "implements EMA_NTI_NARROW_ABE only"
            )

        for name, value, kind in (
            ("nti_status", self.nti_status, NtiStatus),
            ("product_class", self.product_class, EmaNtiProductClass),
            ("cmax_importance", self.cmax_importance, CmaxClinicalImportance),
            ("interval_status", self.interval_status, EmaNtiIntervalStatus),
        ):
            if not isinstance(value, kind):
                refuse(f"{name} is not a {kind.__name__}")

        # A: the class must be the one the reconciled status gives, and the
        # routed spec may not contradict it. `reconcile_nti_status` has already
        # raised on a disagreement by the time any result exists; this holds
        # the same equality on the object, so no result can be BUILT carrying a
        # spec class its own NTI status denies.
        if (
            self.spec_drug_class is not None
            and nti_status_from_drug_class(self.spec_drug_class) is not self.nti_status
        ):
            refuse(
                f"carries spec drug_class={self.spec_drug_class}, which asserts "
                f"{nti_status_from_drug_class(self.spec_drug_class)}, beside "
                f"nti_status={self.nti_status}"
            )
        expected_class, _ = ema_nti_product_class(self.nti_status)
        if expected_class is not self.product_class:
            refuse(
                f"product_class {self.product_class} contradicts "
                f"nti_status={self.nti_status}, which gives {expected_class}"
            )

        # B: the interval status must be the one the rule gives. This single
        # check makes "not an NTID yet narrowed", "Cmax importance unstated yet
        # decided" and "AUC narrowed by a Cmax fact" impossible to construct.
        expected_status, _ = ema_nti_interval(
            endpoint=self.endpoint,
            product_class=self.product_class,
            cmax_importance=self.cmax_importance,
        )
        if expected_status is not self.interval_status:
            refuse(
                f"interval_status {self.interval_status} contradicts the rule, "
                f"which gives {expected_status} for these inputs"
            )

        # THE PRODUCT CLASS IS NOT NEGOTIABLE BY A DOCUMENT
        #
        # Product-specific guidance can settle WHICH numbers apply within
        # 4.1.9. It cannot settle whether 4.1.9 applies: that is the clinical
        # classification, and a product-specific interval supplied for a drug
        # nobody classified would be this method deciding a study it has no
        # basis to decide. So an unconfirmed class refuses whatever else was
        # supplied.
        if not self.product_class.confirmed:
            if self.applied_limits is not None:
                refuse(
                    f"product class is {self.product_class}, yet limits were applied"
                )
            if self.decided or self.passes is not None:
                refuse(
                    f"product class is {self.product_class}, yet a verdict was issued"
                )
            if not any(d.severity is Severity.FATAL for d in self.diagnostics):
                refuse("declined to decide without a FATAL diagnostic saying why")
            return

        general = ema_nti_limits(self.interval_status)
        override = _override_limits(self.product_override, self.endpoint)

        # No limits is a refusal - the endpoint's rule was undetermined and no
        # document supplied one, or the two supplied ones contradicted - and a
        # refusal decides nothing and says why.
        if self.applied_limits is None:
            if self.decided or self.passes is not None or self.treatment is not None:
                refuse("no limits were applied, yet a verdict was issued")
            if self.interval_source is not None:
                refuse("no limits were applied, yet a source was recorded")
            if general is not None and override is None:
                refuse(
                    f"the rule gives {general} for these inputs, yet no limits "
                    "were applied and no product-specific guidance was supplied"
                )
            if not any(d.severity is Severity.FATAL for d in self.diagnostics):
                refuse("declined to apply either interval without saying why")
            return

        if override is None:
            if general is None:
                refuse(
                    f"applied {self.applied_limits} where the rule selects no "
                    "interval and no product-specific guidance was supplied"
                )
            if self.applied_limits != general:
                refuse(
                    f"applied {self.applied_limits} where the general rule gives "
                    f"{general} and no product-specific guidance was supplied"
                )
        else:
            if self.applied_limits != override:
                refuse(
                    f"applied {self.applied_limits} where the product-specific "
                    f"guidance supplied gives {override}"
                )
            if general is not None and _contradicts(override, self.interval_status):
                refuse(
                    f"applied the product-specific {override} beside a stated "
                    f"clinical importance that selects {general}"
                )
        if self.interval_source is None:
            refuse("limits were applied with no source recorded")

        if not self.decided:
            if self.passes is not None or self.treatment is not None:
                refuse("not decided, yet carrying a verdict or a contrast")
            if not any(d.severity is Severity.FATAL for d in self.diagnostics):
                refuse("declined to decide without a FATAL diagnostic saying why")
            return

        # C: a decision needs the contrast it was made from, a model it was
        # computed with, and a verdict that follows from its own interval.
        if self.treatment is None:
            refuse("decided with no treatment contrast")
        if self.analysis_model not in _MODELS.values():
            refuse(
                f"decided with model {self.analysis_model!r}, which is not one "
                "this module analyses with"
            )
        if self.design is None or _MODELS.get(self.design) != self.analysis_model:
            refuse(
                f"design {self.design!r} and model {self.analysis_model!r} do "
                "not correspond"
            )
        lower, upper = self.applied_limits
        expected_passes = _interval_contained(
            ci_lower_percent=self.treatment.ci_lower,
            ci_upper_percent=self.treatment.ci_upper,
            lower=lower,
            upper=upper,
        )
        if self.passes is not expected_passes:
            refuse(
                f"passes={self.passes} but the 90% CI "
                f"{self.treatment.ci_lower:.6f}-{self.treatment.ci_upper:.6f}% "
                f"against {lower}-{upper}% gives {expected_passes}"
            )

    @property
    def selected_method(self) -> Method | None:
        """EMA_NTI_NARROW_ABE for every decided result, None for a refusal.

        Reads `decided` and nothing else. Not the applied limits: a confirmed
        NTID whose Cmax is explicitly not of particular importance is decided
        against 80.00-125.00% and is STILL an EMA 4.1.9 decision. Deriving the
        method from the interval is the defect PR #85 corrected on the highly
        variable path, and it is the same defect here.
        """
        return Method.EMA_NTI_NARROW_ABE if self.decided else None

    @property
    def narrowed(self) -> bool | None:
        """Did 4.1.9 tighten this endpoint? None when no interval was selected."""
        if not self.interval_status.determined:
            return None
        return self.applied_limits == ema_nti_limits(EmaNtiIntervalStatus.NARROWED)

    def explain(self) -> list[str]:
        """The verdict as a person would have to write it out."""
        lines = [
            "Regulator: EMA",
            f"Product class: {self.product_class} ({self.product_class_reason})",
            f"Endpoint: {self.endpoint}",
        ]
        if self.endpoint is Endpoint.CMAX:
            lines.append(f"Cmax importance: {self.cmax_importance}")
        if self.applied_limits is None:
            lines.append("Applicable interval: NOT SELECTED")
            lines.append(f"Reason: {self.interval_reason}")
        else:
            lower, upper = self.applied_limits
            lines.append(f"Applicable interval: {lower:.2f}-{upper:.2f}%")
            lines.append(f"Regulatory basis: {self.interval_source}")
        if self.design is not None:
            lines.append(f"Study design: {self.design}")
        if self.analysis_model is not None:
            lines.append(f"Analysis model: {self.analysis_model}")
        if self.treatment is not None:
            lines.append(
                f"Point estimate: {self.treatment.point_estimate:.2f}%"
            )
            lines.append(
                f"90% CI: {self.treatment.ci_lower:.2f}-"
                f"{self.treatment.ci_upper:.2f}%"
            )
        if not self.decided:
            lines.append("NO EMA NTI DECISION ISSUED")
            lines.append(f"Reason: {self.interval_reason}")
        else:
            lines.append(f"Final decision: {'PASS' if self.passes else 'FAIL'}")
        lines.append(f"Method: {self.selected_method}")
        lines.append(f"Validation status: {self.validation_status}")
        return lines


def _override_limits(
    product: ProductOverride | None, endpoint: Endpoint
) -> tuple[float, float] | None:
    if product is None or endpoint not in product.limits:
        return None
    lower, upper = product.limits[endpoint]
    return (float(lower), float(upper))


def _acceptance(
    limits: tuple[float, float], *, source: str, product: ProductOverride | None
) -> AcceptanceInterval:
    """An `AcceptanceInterval` carrying where its numbers came from.

    A product-specific interval is UNVERIFIED on purpose: the engine has not
    read the document the caller is citing. The general rule's is VERIFIED,
    from the guideline section this module implements.
    """
    if product is None:
        citation = EMA_BIOEQUIVALENCE
        verification = VerificationStatus.VERIFIED
    else:
        citation = Citation(
            authority="EMA",
            document=f"product-specific guidance for {product.product}",
            document_version=product.citation or "as supplied",
        )
        verification = VerificationStatus.UNVERIFIED
    lower, upper = limits
    return AcceptanceInterval(
        lower=RegulatoryValue(lower, citation, verification),
        upper=RegulatoryValue(upper, citation, verification),
        basis=source,
    )


def _require_ema_nti_spec(spec: BeSpec | None, endpoint: Endpoint) -> None:
    """A supplied spec must be EMA's NTI route, for this endpoint."""
    if spec is None:
        return
    if (
        spec.jurisdiction is not Jurisdiction.EMA
        or spec.method is not Method.EMA_NTI_NARROW_ABE
    ):
        raise NotApplicable(
            f"assess_ema_nti_endpoint implements EMA 4.1.9 and was given a spec "
            f"for {spec.jurisdiction} {spec.method}. It does not reconcile "
            "another route's spec; resolve the spec for the EMA narrow "
            "therapeutic index route or use the module that implements the one "
            "resolved."
        )
    if spec.endpoint is not endpoint:
        raise NotApplicable(
            f"The spec was resolved for {spec.endpoint} and the analysis was "
            f"asked for {endpoint}. Whether Cmax is tightened is decided per "
            "endpoint, so the two may not differ."
        )


def _fatal(code: DiagnosticCode, detail: str, context: dict) -> Diagnostic:
    return Diagnostic(code, Severity.FATAL, None, detail, context)


def _refusal(
    *,
    endpoint: Endpoint,
    nti_status: NtiStatus,
    spec_drug_class: DrugClass | None,
    product_class: EmaNtiProductClass,
    product_class_reason: str,
    cmax_importance: CmaxClinicalImportance,
    interval_status: EmaNtiIntervalStatus,
    interval_reason: str,
    product: ProductOverride | None,
    diagnostics: list[Diagnostic],
    spec_method: Method | None,
    provenance: tuple[str, ...],
    design: str | None = None,
    applied_limits: tuple[float, float] | None = None,
    interval_source: str | None = None,
    analysis_model: str | None = None,
) -> EmaNtiResult:
    return EmaNtiResult(
        endpoint=endpoint,
        nti_status=nti_status,
        spec_drug_class=spec_drug_class,
        product_class=product_class,
        product_class_reason=product_class_reason,
        cmax_importance=cmax_importance,
        interval_status=interval_status,
        interval_reason=interval_reason,
        product_override=product,
        interval_source=interval_source,
        design=design,
        analysis_model=analysis_model,
        applied_limits=applied_limits,
        treatment=None,
        decided=False,
        passes=None,
        diagnostics=tuple(diagnostics),
        provenance_lines=provenance,
        spec_method=spec_method,
    )


_PROVENANCE: tuple[str, ...] = (
    "EMA Guideline on the Investigation of Bioequivalence, "
    "CPMP/EWP/QWP/1401/98 Rev. 1, section 4.1.9: the acceptance interval for "
    "AUC is tightened to 90.00-111.11% for a narrow therapeutic index drug, "
    "and the same interval applies to Cmax where Cmax is of particular "
    "importance for safety, efficacy or drug level monitoring.",
    "The same section: no set of criteria can categorise a drug as an NTID, "
    "and the classification is made case by case on clinical considerations. "
    "This engine therefore takes it as stated product metadata and derives it "
    "from nothing.",
    "EMA guideline section 4.1.8: a bound is inside the acceptance interval "
    "when it is within the limits after rounding to two decimal places.",
    "ICH M13A section 2.2.3.2 (crossover) and 2.2.3.4 (parallel): the "
    "analysis model for a non-replicate study.",
    "EMA/531548/2024, adopted by CHMP 17 February 2025: after 25 January 2025 "
    "ICH M13A applies to what it covers, and the EMA guideline continues to "
    "apply to topics M13A does not address. Narrow therapeutic index drugs "
    "are named there as a topic whose requirements are read in conjunction, "
    "and are deferred to the future ICH M13C.",
)


def assess_ema_nti_endpoint(
    study: CrossoverStudy | ParallelStudy,
    *,
    endpoint: Endpoint,
    nti_status: NtiStatus = NtiStatus.NOT_STATED,
    cmax_importance: CmaxClinicalImportance = CmaxClinicalImportance.NOT_STATED,
    product: ProductOverride | None = None,
    spec: BeSpec | None = None,
    alpha: float = 0.05,
) -> EmaNtiResult:
    """The EMA narrow therapeutic index decision for one endpoint.

        A  product class    stated, and cross-checked against the routed spec
        B  interval         AUC tightened; Cmax on its own stated importance;
                            product-specific guidance replaces either
        C  decision         the 90% CI inside the applied limits, both bounds
                            compared after rounding to two decimal places

    Both determined branches run the same model and the same comparison. They
    differ only in the limits, which is what 4.1.9 is.

    Every product fact defaults to NOT_STATED and none is ever inferred. A
    confirmed NTID's Cmax analysed without its clinical importance receives no
    decision, on purpose: EMA published both answers for real products and
    choosing one here would be choosing wrong for the other.

    CALLER-SELECTED, NOT ROUTED

    This function executes 4.1.9; it does not decide that 4.1.9 applies.
    `resolve_be_spec` is the router, and a `spec` passed here must be the EMA
    NTI route for the same endpoint - an EMA highly variable spec, an FDA spec
    or a standard-class spec raises `NotApplicable`.

    DESIGNS

    A 2x2 crossover and a parallel-group study, which are the non-replicate
    designs M13A 2.2.3 gives a model for. A replicate design raises
    `NotImplementedMethod` rather than being analysed: EMA's narrowed interval
    says nothing about how to fit a replicate model, FDA's Appendix C model is
    a different regulator's specification for a different procedure, and
    borrowing it would be inventing EMA's analysis.
    """
    endpoint = Endpoint(endpoint)
    _require_ema_nti_spec(spec, endpoint)
    spec_drug_class = None if spec is None else spec.drug_class
    spec_method = None if spec is None else spec.method

    # ONE answer about the product. A spec and product metadata that disagree
    # raise `ContradictoryProductClass` here rather than being resolved by
    # precedence - the rule PR #83 established, reused rather than restated.
    nti_status = reconcile_nti_status(spec=spec, nti_status=nti_status)
    product_class, class_reason = ema_nti_product_class(nti_status)
    interval_status, interval_reason = ema_nti_interval(
        endpoint=endpoint,
        product_class=product_class,
        cmax_importance=cmax_importance,
    )

    def refuse(code: DiagnosticCode, context: dict) -> EmaNtiResult:
        return _refusal(
            endpoint=endpoint,
            nti_status=nti_status,
            spec_drug_class=spec_drug_class,
            product_class=product_class,
            product_class_reason=class_reason,
            cmax_importance=cmax_importance,
            interval_status=interval_status,
            interval_reason=interval_reason,
            product=product,
            diagnostics=[_fatal(code, interval_reason, context)],
            spec_method=spec_method,
            provenance=_PROVENANCE,
        )

    if interval_status is EmaNtiIntervalStatus.UNDETERMINED_CLASS_NOT_DETERMINED:
        return refuse(
            DiagnosticCode.EMA_NTI_PRODUCT_CLASS_NOT_STATED,
            {
                "nti_status": str(nti_status),
                "spec_drug_class": None if spec_drug_class is None else str(spec_drug_class),
                "product_class_reason": class_reason,
            },
        )
    if interval_status is EmaNtiIntervalStatus.NOT_APPLICABLE_NOT_NTI:
        return refuse(
            DiagnosticCode.EMA_NTI_NOT_APPLICABLE,
            {"nti_status": str(nti_status)},
        )
    # The class holds. Which numbers apply is now the general rule's answer,
    # replaced by product-specific guidance where the caller supplied it for
    # THIS endpoint.
    #
    # A document can settle an endpoint the general rule leaves open - EMA's
    # own tacrolimus answer is exactly that, a per-product Cmax decision the
    # guideline delegates - so an override is consulted before the endpoint
    # refusals below, and the refusals stand only when nothing supplied one.
    general = ema_nti_limits(interval_status)
    override = _override_limits(product, endpoint)

    if general is None and override is None:
        if interval_status is EmaNtiIntervalStatus.UNDETERMINED_CMAX_IMPORTANCE_NOT_STATED:
            return refuse(
                DiagnosticCode.EMA_NTI_CMAX_IMPORTANCE_NOT_STATED,
                {"cmax_importance": str(cmax_importance)},
            )
        return refuse(
            DiagnosticCode.EMA_NTI_ENDPOINT_NOT_COVERED,
            {"endpoint": str(endpoint)},
        )

    if override is not None and general is not None and _contradicts(override, interval_status):
        return _refusal(
            endpoint=endpoint,
            nti_status=nti_status,
            spec_drug_class=spec_drug_class,
            product_class=product_class,
            product_class_reason=class_reason,
            cmax_importance=cmax_importance,
            interval_status=interval_status,
            interval_reason=interval_reason,
            product=product,
            diagnostics=[
                _fatal(
                    DiagnosticCode.EMA_NTI_PRODUCT_LIMITS_CONFLICT,
                    f"the product-specific guidance for {product.product} gives "
                    f"{override[0]:.2f}-{override[1]:.2f}% and the stated "
                    f"clinical importance of Cmax selects {general[0]:.2f}-"
                    f"{general[1]:.2f}%. Two sources, two answers, and 4.1.9 "
                    "gives no rule for choosing between them.",
                    {
                        "product": product.product,
                        "product_limits": list(override),
                        "rule_limits": list(general),
                    },
                )
            ],
            spec_method=spec_method,
            provenance=_PROVENANCE,
        )

    applied = general if override is None else override
    source = (
        f"EMA guideline 4.1.9 ({'tightened' if interval_status.narrowed else 'conventional'})"
        if override is None
        else f"product-specific guidance for {product.product}"
    )
    acceptance = _acceptance(applied, source=source, product=None if override is None else product)

    design, run = _analysis_for(study)
    analysis_spec = BeSpec(
        method=Method.EMA_NTI_NARROW_ABE,
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=endpoint,
        alpha=alpha,
        acceptance=acceptance,
        required_design="2x2 crossover or parallel",
    )

    try:
        treatment = run(study, analysis_spec)
    except DataError as exc:
        return _refusal(
            endpoint=endpoint,
            nti_status=nti_status,
            spec_drug_class=spec_drug_class,
            product_class=product_class,
            product_class_reason=class_reason,
            cmax_importance=cmax_importance,
            interval_status=interval_status,
            interval_reason=interval_reason,
            product=product,
            diagnostics=[
                _fatal(
                    DiagnosticCode.EMA_NTI_QUANTITY_NOT_ESTIMABLE,
                    f"the treatment contrast could not be estimated: {exc}",
                    {"quantity": "treatment contrast"},
                )
            ],
            spec_method=spec_method,
            provenance=_PROVENANCE,
            design=design,
            applied_limits=applied,
            interval_source=source,
            analysis_model=_MODELS[design],
        )

    passes = _interval_contained(
        ci_lower_percent=treatment.ci_lower,
        ci_upper_percent=treatment.ci_upper,
        lower=applied[0],
        upper=applied[1],
    )

    return EmaNtiResult(
        endpoint=endpoint,
        nti_status=nti_status,
        spec_drug_class=spec_drug_class,
        product_class=product_class,
        product_class_reason=class_reason,
        cmax_importance=cmax_importance,
        interval_status=interval_status,
        interval_reason=interval_reason,
        product_override=product,
        interval_source=source,
        design=design,
        analysis_model=_MODELS[design],
        applied_limits=applied,
        treatment=treatment,
        decided=True,
        passes=passes,
        provenance_lines=_PROVENANCE,
        spec_method=spec_method,
    )


def _contradicts(
    override: tuple[float, float], status: EmaNtiIntervalStatus
) -> bool:
    """Do supplied limits say the opposite of the stated clinical importance?

    Only when the supplied pair is EXACTLY the other canonical interval. A
    product-specific document giving some third pair is not a contradiction -
    it is product-specific guidance, which is what it is for, and 4.1.9 expects
    it to outrank the general rule.
    """
    narrowed = ema_nti_limits(EmaNtiIntervalStatus.NARROWED)
    conventional = ema_nti_limits(EmaNtiIntervalStatus.CONVENTIONAL)
    if status.narrowed:
        return override == conventional
    return override == narrowed


def _analysis_for(study: CrossoverStudy | ParallelStudy):
    """Which design this is, and the function that analyses it.

    A replicate dataset is refused here rather than coerced. EMA's 4.1.9 states
    an interval and no replicate model; FDA's Appendix C model is another
    regulator's specification written for another procedure; and EMA's Method A
    belongs to 4.1.10's widening, whose applicability rule is a different one.
    """
    if isinstance(study, CrossoverStudy):
        return "2x2 crossover", analyse_crossover
    if isinstance(study, ParallelStudy):
        return "parallel", analyse_parallel
    raise NotImplementedMethod(
        f"EMA's narrow therapeutic index procedure is implemented for a 2x2 "
        f"crossover and a parallel-group study, and was given {type(study).__name__}. "
        "A replicate design is not analysed here: 4.1.9 tightens the interval "
        "and states no replicate model, and neither FDA's Appendix C model nor "
        "EMA's Method A was written for this procedure. Substituting one would "
        "be inventing EMA's analysis rather than implementing it."
    )


__all__ = [
    "CROSSOVER_MODEL",
    "PARALLEL_MODEL",
    "EmaNtiResult",
    "EmaNtiResultInconsistent",
    "assess_ema_nti_endpoint",
]
