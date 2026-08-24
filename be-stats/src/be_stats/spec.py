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

SOURCES

Constants and thresholds below were supplied with citations during statistical
review. Each carries its origin in `basis`. Nothing here was recalled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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


#: Methods this version can actually run. Everything else resolves to a spec
#: that refuses when an estimator is asked to use it.
IMPLEMENTED: frozenset[Method] = frozenset(
    {Method.STANDARD_ABE, Method.EMA_NTI_NARROW_ABE}
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


@dataclass(frozen=True, slots=True)
class AcceptanceInterval:
    lower: float
    upper: float
    basis: str

    def contains(self, ci_lower: float, ci_upper: float) -> bool:
        return ci_lower >= self.lower and ci_upper <= self.upper


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


_STANDARD = (80.00, 125.00)
_EMA_NARROWED = (90.00, 111.11)


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

    #: Smallest number of evaluable subjects the regulator will accept,
    #: independent of what the power calculation says. `None` where this
    #: package has not confirmed a figure for the jurisdiction.
    regulatory_minimum_n: int | None = None
    regulatory_minimum_basis: str = ""

    #: Constants the method needs. Empty for standard ABE; carried for the
    #: reference-scaled methods so Phase 2 inherits verified values rather than
    #: rediscovering them.
    constants: dict[str, float] = field(default_factory=dict)

    notes: str = ""

    @property
    def confidence_level(self) -> float:
        return 1.0 - 2.0 * self.alpha

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

    def require_interval(self) -> AcceptanceInterval:
        self.require_implemented()
        if self.acceptance is None:
            raise NotApplicable(
                f"{self.method} does not decide by a fixed acceptance interval."
            )
        return self.acceptance


# ------------------------------------------------------------- minimums ---
# FDA: not fewer than 12 evaluable subjects in a PK BE study, and at least 24
# for a highly variable drug product. Supplied with citation at statistical
# review. EMA's minimum is deliberately left unset - see validation/README.md;
# an unconfirmed number here would be indistinguishable from a confirmed one.

_FDA_MIN_STANDARD = 12
_FDA_MIN_HVD = 24


def _fda_minimum(drug_class: DrugClass) -> tuple[int, str]:
    if drug_class is DrugClass.HIGHLY_VARIABLE:
        return _FDA_MIN_HVD, "FDA: at least 24 subjects for a highly variable drug product"
    return _FDA_MIN_STANDARD, "FDA: not fewer than 12 evaluable subjects in a PK BE study"


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

    minimum_n: int | None
    minimum_basis: str
    if jur is Jurisdiction.FDA:
        minimum_n, minimum_basis = _fda_minimum(cls)
    else:
        minimum_n, minimum_basis = (
            None,
            "EMA minimum not confirmed in this version - see validation/README.md",
        )

    def spec(**kwargs) -> BeSpec:
        return BeSpec(
            jurisdiction=jur,
            drug_class=cls,
            endpoint=end,
            alpha=alpha,
            regulatory_minimum_n=minimum_n,
            regulatory_minimum_basis=minimum_basis,
            **kwargs,
        )

    # A product-specific interval outranks every jurisdiction default below,
    # but only for the methods that are decided by an interval at all.
    override = None
    if product is not None and end in product.limits:
        lo, hi = product.limits[end]
        override = AcceptanceInterval(
            lo, hi, f"product-specific guidance for {product.product}"
                    f"{' - ' + product.citation if product.citation else ''}"
        )

    if cls is DrugClass.STANDARD:
        lo, hi = _STANDARD
        return spec(
            method=Method.STANDARD_ABE,
            acceptance=override or AcceptanceInterval(
                lo, hi, f"{jur} standard interval"
            ),
        )

    if cls is DrugClass.NARROW_THERAPEUTIC_INDEX:
        if jur is Jurisdiction.FDA:
            return spec(
                method=Method.FDA_NTI_RSABE,
                acceptance=None,
                required_design="fully replicated crossover",
                constants={
                    # Supplied at statistical review with FDA citations.
                    "sigma_w0": 0.10,
                    "delta": 1.0 / 0.9,
                    "variance_ratio_upper_limit": 2.5,
                },
                notes=(
                    "FDA requires reference-scaled BE, an additional unscaled "
                    "80.00-125.00 criterion, and a comparison of test and "
                    "reference within-subject variability. Phase 2B."
                ),
            )

        # EMA.
        if override is not None:
            return spec(method=Method.EMA_NTI_NARROW_ABE, acceptance=override)

        if end is Endpoint.AUC:
            lo, hi = _EMA_NARROWED
            return spec(
                method=Method.EMA_NTI_NARROW_ABE,
                acceptance=AcceptanceInterval(
                    lo, hi, "EMA: narrowed interval for AUC of an NTI drug"
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
                    "sigma_w0": 0.25,
                    "swr_switching_threshold": 0.294,
                    "point_estimate_lower": 80.00,
                    "point_estimate_upper": 125.00,
                },
                notes=(
                    "FDA switches to reference-scaled ABE at sWR >= 0.294 and "
                    "additionally constrains the point estimate to "
                    "80.00-125.00. Below the threshold, conventional ABE "
                    "applies for that endpoint. Phase 2A."
                ),
            )
        return spec(
            method=Method.EMA_HVD_ABEL,
            acceptance=None,
            required_design="replicated crossover",
            notes=(
                "EMA uses average BE with expanding limits (ABEL), which is a "
                "different procedure from FDA's RSABE and not a relabelling "
                "of it. Phase 2."
            ),
        )

    raise NotApplicable(f"Unhandled drug class: {cls}")
