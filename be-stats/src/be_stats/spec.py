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

from dataclasses import dataclass, field
from enum import StrEnum

from be_stats.conversions import HVD_CV_THRESHOLD, HVD_SWR_THRESHOLD
from be_stats.provenance import (
    DERIVED_INTERNALLY,
    EMA_BIOEQUIVALENCE,
    FDA_STATISTICAL_APPROACHES,
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
#: Both runnable methods are IMPLEMENTED_UNVALIDATED rather than VALIDATED:
#: they reproduce an independent implementation (tier 3) but no tier-1
#: regulator worked example has been reproduced yet. See validation/README.md.
VALIDATION: dict[Method, ValidationStatus] = {
    Method.STANDARD_ABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    Method.EMA_NTI_NARROW_ABE: ValidationStatus.IMPLEMENTED_UNVALIDATED,
    Method.FDA_NTI_RSABE: ValidationStatus.NOT_IMPLEMENTED,
    Method.FDA_HVD_RSABE: ValidationStatus.NOT_IMPLEMENTED,
    Method.EMA_HVD_ABEL: ValidationStatus.NOT_IMPLEMENTED,
}

IMPLEMENTED: frozenset[Method] = frozenset(
    m for m, s in VALIDATION.items() if s is not ValidationStatus.NOT_IMPLEMENTED
)


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
                constants={
                    "sigma_w0": RegulatoryValue(
                        0.10,
                        FDA_STATISTICAL_APPROACHES,
                        VerificationStatus.VERIFIED,
                        "NTI reference-scaling constant.",
                    ),
                    "delta": RegulatoryValue(
                        1.0 / 0.9,
                        FDA_STATISTICAL_APPROACHES,
                        VerificationStatus.VERIFIED,
                        "Stated as 1/0.9.",
                    ),
                    "variance_ratio_upper_limit": RegulatoryValue(
                        2.5,
                        FDA_STATISTICAL_APPROACHES,
                        VerificationStatus.VERIFIED,
                        "Upper limit on the 90% CI of sigma_WT / sigma_WR.",
                    ),
                },
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
                constants={
                    "sigma_w0": RegulatoryValue(
                        0.25,
                        FDA_STATISTICAL_APPROACHES,
                        VerificationStatus.VERIFIED,
                        "HVD reference-scaling constant.",
                    ),
                    "hvd_cv_threshold": RegulatoryValue(
                        HVD_CV_THRESHOLD,
                        FDA_STATISTICAL_APPROACHES,
                        VerificationStatus.VERIFIED,
                        "Within-subject variability of 30% or greater defines "
                        "a highly variable drug.",
                    ),
                    # DERIVED, not transcribed. The commonly quoted 0.294 is
                    # this quantity rounded; the two differ in the fourth
                    # decimal and disagree for a real range of studies, so the
                    # package computes it and records that it did.
                    "swr_switching_threshold": RegulatoryValue(
                        HVD_SWR_THRESHOLD,
                        DERIVED_INTERNALLY,
                        VerificationStatus.DERIVED,
                        "cv_to_log_sd(0.30). Published as 0.294; whether the "
                        "rounded figure or the 30% CV is normative is an open "
                        "question for Phase 2A.",
                    ),
                },
                notes=(
                    "FDA switches to reference-scaled ABE above the reference "
                    "variability threshold and additionally constrains the "
                    "point estimate to 80.00-125.00. Below it, conventional "
                    "ABE applies for that endpoint. Phase 2A."
                ),
            )
        return spec(
            method=Method.EMA_HVD_ABEL,
            acceptance=None,
            required_design="replicated crossover",
            notes=(
                "EMA uses average BE with expanding limits (ABEL), which is a "
                "different procedure from FDA's RSABE and not a relabelling "
                "of it. Phase 2C."
            ),
        )

    raise NotApplicable(f"Unhandled drug class: {cls}")
