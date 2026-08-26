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
    FDA_STATISTICAL_APPROACHES,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F,
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    FDA_STATISTICAL_APPROACHES_III_C,
    VIA_STATISTICAL_REVIEW,
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
    Method.FDA_NTI_RSABE: ValidationStatus.NOT_IMPLEMENTED,
    Method.FDA_HVD_RSABE: ValidationStatus.NOT_IMPLEMENTED,
    Method.EMA_HVD_ABEL: ValidationStatus.NOT_IMPLEMENTED,
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

FDA_HVD_CONSTANTS: dict[str, RegulatoryValue] = {
    "classification_cv": RegulatoryValue(
        0.30,
        FDA_STATISTICAL_APPROACHES_III_C,
        VerificationStatus.VERIFIED,
        "Defines WHICH DRUGS are highly variable: within-subject variability "
        "of 30% or greater, and not an NTI drug. Not the analysis switch.",
        VIA_STATISTICAL_REVIEW,
    ),
    "swr_switching_threshold": RegulatoryValue(
        0.294,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "Selects WHICH ANALYSIS applies, from the estimated sWR. Below it, "
        "ordinary ABE; at or above it, reference-scaled ABE. Numerically near "
        "sqrt(ln(1+0.30^2)) = 0.293560 but NOT that quantity - this is the "
        "regulator's stated criterion and must not be recomputed.",
        VIA_STATISTICAL_REVIEW,
    ),
    "sigma_w0": RegulatoryValue(
        0.25,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "Reference-scaling constant for highly variable drugs.",
        VIA_STATISTICAL_REVIEW,
    ),
    "point_estimate_lower": RegulatoryValue(
        0.8000,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "The scaled criterion alone is not sufficient: the T/R point estimate "
        "must also fall within 0.8000-1.2500.",
        VIA_STATISTICAL_REVIEW,
    ),
    "point_estimate_upper": RegulatoryValue(
        1.2500,
        FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        VerificationStatus.VERIFIED,
        "",
        VIA_STATISTICAL_REVIEW,
    ),
}


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
    """
    if swr < 0.0:
        raise ValueError(f"sWR cannot be negative, got {swr}.")
    threshold = FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    return Method.FDA_HVD_RSABE if swr >= threshold else Method.STANDARD_ABE


FDA_NTI_CONSTANTS: dict[str, RegulatoryValue] = {
    "sigma_w0": RegulatoryValue(
        0.10,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "NTI reference-scaling constant.",
        VIA_STATISTICAL_REVIEW,
    ),
    "delta": RegulatoryValue(
        1.0 / 0.9,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "Stated as 1/0.9.",
        VIA_STATISTICAL_REVIEW,
    ),
    "variance_ratio_upper_limit": RegulatoryValue(
        2.5,
        FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        VerificationStatus.VERIFIED,
        "Upper limit on the 90% CI of sigma_WT / sigma_WR.",
        VIA_STATISTICAL_REVIEW,
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
            required_design="replicated crossover",
            notes=(
                "EMA uses average BE with expanding limits (ABEL), which is a "
                "different procedure from FDA's RSABE and not a relabelling "
                "of it. Phase 2C."
            ),
        )

    raise NotApplicable(f"Unhandled drug class: {cls}")
