"""EMA average bioequivalence with expanding limits (ABEL).

THE RULE, AND WHERE IT COMES FROM

EMA, *Guideline on the Investigation of Bioequivalence*,
CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010, section 4.1.10.

    Highly variable drug products (HVDP) are those whose intra-subject
    variability for a parameter is larger than 30%. ... For the acceptance
    interval to be widened the bioequivalence study must be of a replicate
    design where it has been demonstrated that the within-subject variability
    for Cmax of the reference compound in the study is >30%. ... The extent of
    the widening is defined ... using scaled-average-bioequivalence according
    to [U, L] = exp [+/- k.sWR], where ... k is the regulatory constant set to
    0.760 ... the acceptance criteria for Cmax can be widened to a maximum of
    69.84 - 143.19%. ... The geometric mean ratio (GMR) should lie within the
    conventional acceptance range 80.00-125.00%. The possibility to widen the
    acceptance criteria based on high intra-subject variability does not apply
    to AUC where the acceptance range should remain at 80.00 - 125.00%
    regardless of variability.

WHY A 2010 DOCUMENT IS STILL THE RULE

ICH M13A came into effect on 25 January 2025 and superseded parts of that
guideline — but only the parts about non-replicate designs. EMA/531548/2024
says so directly: the 2010 guideline "pertaining to specific topics not
addressed in ICH M13A will continue to apply", and names "BE studies with
highly variable drugs (replicate design)" among them. Highly variable drugs are
a Tier 3 topic for the future M13C, which does not exist yet. So the applicable
stack, in precedence order, is:

    1. ICH M13A                     study design and non-replicate analysis
    2. CPMP/EWP/QWP/1401/98 Rev. 1  4.1.10, the ABEL rule itself
    3. EMA/618604/2008 Rev. 13      the Q&A, which says HOW to analyse it
    4. product-specific guidance    outranks the general rule where it exists

HOW THE ANALYSIS IS DONE, WHICH THE GUIDELINE DOES NOT SAY

4.1.10 gives the limits but not the model. The Q&A does. It compares three
models on two worked data sets and recommends the first:

    Method A (guideline recommended)
        proc glm; class formulation subject period sequence;
        model logDATA = sequence subject(sequence) period formulation;

All terms fixed. One variance component. No random effects, no REML, no
iteration. That is why EMA's replicate analysis can be implemented faithfully
here while FDA's Appendix C cannot — see `be_stats.replicate_abe`, which
records Appendix C's five-parameter mixed model and refuses to approximate it.

    THERE IS NO FDA MATERIAL IN THIS MODULE.

No Howe approximation, no linearized criterion, no sigma_w0, no NTI logic. EMA
does not scale a criterion; it scales the LIMITS and then runs an ordinary
confidence-interval test against them. The two procedures share arithmetic no
deeper than "fit a linear model", which lives in `linear_model`.

WITHIN-SUBJECT VARIABILITY OF THE REFERENCE

The Q&A again, section 3.4: "the preferred way to get an unbiased estimate of
sigma^2_wr is using the data from the reference product only", fitted as

    data var; set replicate; if formulation='R';
    proc glm; class subject period sequence;
    model logDATA = sequence subject(sequence) period;

with CV(%) = 100 * sqrt(exp(s^2_wR) - 1). This is NOT FDA Appendix G's
sum-of-squared-differences estimator, and the provenance recorded here cites
EMA rather than Appendix G even where the two happen to agree numerically.

WHICH SUBJECTS ARE INCLUDED

All of them, including subjects missing periods. That is not a liberty: EMA's
own Data set I contains eight subjects with incomplete data, and reproducing
EMA's published result for it requires keeping them. `ReplicateDataset` drops
such subjects, correctly, because FDA's sWR needs both reference replicates —
so this module does not use `ReplicateDataset`. It shares the row-level
validation (`validate_subject_rows`) and applies its own inclusion rule.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.linear_model import LeastSquaresFit, fit_least_squares
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE_HVD,
    EMA_M13A_IMPLEMENTATION,
    EMA_PKWP_QA,
    VIA_PRIMARY_DOCUMENT,
    ValidationStatus,
)
from be_stats.replicate import (
    DataError,
    ReplicateDesign,
    ReplicateObservation,
    ReplicateSequence,
    Treatment,
    identify_design,
    validate_subject_rows,
)
from be_stats.spec import (
    EMA_ABEL_SCALABLE_ENDPOINTS,
    EMA_HVD_CONSTANTS,
    Endpoint,
    Method,
    ema_hvd_scaling_eligible,
)

#: One-sided level. EMA asks for a 90% confidence interval, which is the
#: two-sided interval at alpha = 0.05 each side.
ALPHA = 0.05


# ------------------------------------------------------- design support ---


class EmaDesignSupport:
    """What EMA permits, as an explicit classification rather than a silence."""

    SUPPORTED = "supported"
    NOT_APPLICABLE = "not_applicable"
    NOT_IMPLEMENTED = "not_implemented"


#: Every design this package can describe, classified for EMA with a reason.
#:
#: 4.1.10: "It is acceptable to apply either a 3-period or a 4-period crossover
#: scheme in the replicate design study." Both of the replicate designs already
#: modelled here are therefore supported; everything else is classified rather
#: than left to fall through.
EMA_DESIGN_SUPPORT: dict[str, tuple[str, str]] = {
    "fully_replicate": (
        EmaDesignSupport.SUPPORTED,
        "4-period replicate crossover (TRTR/RTRT). 4.1.10 accepts a 3- or "
        "4-period replicate scheme, and EMA's own Data set I is of this form.",
    ),
    "partial_replicate": (
        EmaDesignSupport.SUPPORTED,
        "3-period replicate crossover (TRR/RTR/RRT). Accepted by 4.1.10 and "
        "by Q&A 19, which discusses exactly this scheme for demonstrating "
        "within-subject variability for Cmax. EMA's Data set II is of this "
        "form.",
    ),
    "2x2_crossover": (
        EmaDesignSupport.NOT_APPLICABLE,
        "A conventional two-period crossover measures the reference once per "
        "subject, so there is no within-subject reference variability to "
        "estimate and no basis on which 4.1.10 permits widening. This is not "
        "a gap in the implementation: the design cannot support the method.",
    ),
    "parallel": (
        EmaDesignSupport.NOT_APPLICABLE,
        "A parallel-group study has no within-subject replication at all. "
        "4.1.10 requires a replicate design.",
    ),
    "2x2x3_replicate_tr_rt_r": (
        EmaDesignSupport.NOT_IMPLEMENTED,
        "The two-sequence three-period replicate (TRT/RTR) is a replicate "
        "design and is not refused by 4.1.10, but Q&A 19 recommends against "
        "it - only half the subjects give two reference measurements, so a "
        "study of ~24 is needed for 12 usable ones. It is not modelled by "
        "`ReplicateSequence` and is not implemented here.",
    ),
}


def ema_design_support(design: str) -> tuple[str, str]:
    """Classification and reason for a design name. Unknown names refuse."""
    if design not in EMA_DESIGN_SUPPORT:
        raise DataError(
            f"{design!r} is not a design this package classifies for EMA. "
            f"Known: {', '.join(sorted(EMA_DESIGN_SUPPORT))}."
        )
    return EMA_DESIGN_SUPPORT[design]


# --------------------------------------------------------- the dataset ---


@dataclass(frozen=True, slots=True)
class EmaObservation:
    """One usable measurement, with the period retained.

    `SubjectRecord` keeps log values grouped by treatment and drops the period,
    which is everything FDA's sWR needs. Method A needs a period effect, and
    with subjects missing periods the period cannot be recovered from the
    sequence afterwards. So EMA keeps its own row.
    """

    subject_id: str
    sequence: ReplicateSequence
    period: int
    treatment: Treatment
    log_value: float


@dataclass(frozen=True, slots=True)
class EmaReplicateDataset:
    """Validated rows for an EMA replicate analysis.

    Deliberately NOT `ReplicateDataset`. See the module docstring: the two
    differ in which subjects they keep, and that difference is regulatory
    rather than cosmetic.
    """

    endpoint: str
    design: ReplicateDesign
    observations: tuple[EmaObservation, ...]
    diagnostics: tuple[Diagnostic, ...]
    subjects_received: tuple[str, ...]

    @property
    def subjects(self) -> tuple[str, ...]:
        seen: list[str] = []
        for o in self.observations:
            if o.subject_id not in seen:
                seen.append(o.subject_id)
        return tuple(seen)

    @property
    def periods(self) -> tuple[int, ...]:
        return tuple(sorted({o.period for o in self.observations}))

    def reference_only(self) -> tuple[EmaObservation, ...]:
        return tuple(
            o for o in self.observations if o.treatment is Treatment.REFERENCE
        )

    @classmethod
    def build(cls, observations: list[ReplicateObservation]) -> EmaReplicateDataset:
        if not observations:
            raise DataError("No observations were supplied.")

        endpoints = {o.endpoint for o in observations}
        if len(endpoints) != 1:
            raise DataError(
                f"Observations span {len(endpoints)} endpoints "
                f"({', '.join(sorted(endpoints))}). One endpoint per dataset."
            )
        endpoint = endpoints.pop()
        design = identify_design({o.sequence for o in observations})

        subjects_received: list[str] = []
        grouped: dict[str, list[ReplicateObservation]] = {}
        for obs in observations:
            if obs.subject_id not in grouped:
                grouped[obs.subject_id] = []
                subjects_received.append(obs.subject_id)
            grouped[obs.subject_id].append(obs)

        kept: list[EmaObservation] = []
        diagnostics: list[Diagnostic] = []
        for subject_id in subjects_received:
            validated = validate_subject_rows(
                subject_id, grouped[subject_id], diagnostics
            )
            if validated is None:
                continue
            sequence, by_period = validated

            # EMA's inclusion rule, and the one place it differs from FDA's.
            # A subject short of a period still carries information about the
            # period and subject effects, and Method A uses it. Recorded as an
            # advisory so an incomplete study is never silent.
            missing = [
                p for p in range(1, sequence.periods + 1) if p not in by_period
            ]
            if missing:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.MISSING_PERIOD,
                        Severity.ADVISORY,
                        subject_id,
                        "missing measurement at period "
                        + ", ".join(str(p) for p in missing)
                        + "; retained, because EMA's Method A is an ANOVA over "
                        "the observations present and its own worked data set "
                        "includes such subjects",
                        {"missing_periods": missing},
                    )
                )
            for period in sorted(by_period):
                row = by_period[period]
                kept.append(
                    EmaObservation(
                        subject_id=subject_id,
                        sequence=sequence,
                        period=period,
                        treatment=row.treatment,
                        log_value=row.log_value,
                    )
                )

        if not kept:
            raise DataError(
                "No subject survived validation, so there is nothing to "
                "estimate. Diagnostics: "
                + "; ".join(str(d) for d in diagnostics)
            )

        return cls(
            endpoint=endpoint,
            design=design,
            observations=tuple(kept),
            diagnostics=tuple(diagnostics),
            subjects_received=tuple(subjects_received),
        )


# ------------------------------------------------------------- the model ---


def _design_matrix(
    rows: tuple[EmaObservation, ...], *, with_formulation: bool
) -> tuple[list[list[float]], list[float], int]:
    """Reference-cell coding of Method A.

    Columns: intercept, subject indicators (first omitted), period indicators
    (first omitted), and - when asked for - a single test indicator whose
    coefficient IS mu_T - mu_R on the log scale.

    `sequence` is absent because it is aliased with subject: every subject sits
    in one sequence, so the subject indicators already span it. SAS absorbs the
    same redundancy. Its absence changes no fitted value and no degree of
    freedom, and `test_method_a_matches_a_model_that_names_sequence` proves it.
    """
    subjects = sorted({r.subject_id for r in rows})
    periods = sorted({r.period for r in rows})

    matrix: list[list[float]] = []
    for r in rows:
        row = [1.0]
        row.extend(1.0 if r.subject_id == s else 0.0 for s in subjects[1:])
        row.extend(1.0 if r.period == p else 0.0 for p in periods[1:])
        if with_formulation:
            row.append(1.0 if r.treatment is Treatment.TEST else 0.0)
        matrix.append(row)

    response = [r.log_value for r in rows]
    formulation_index = len(matrix[0]) - 1 if with_formulation else -1
    return matrix, response, formulation_index


@dataclass(frozen=True, slots=True)
class ReferenceVariability:
    """CVwR from the reference measurements alone, EMA's preferred estimator."""

    s2_wr: float
    swr: float
    cv_wr_percent: float
    degrees_of_freedom: int
    n_observations: int
    n_subjects: int
    estimator: str = (
        "EMA/618604/2008 Rev. 13 section 3.4: fixed-effects ANOVA on the "
        "REFERENCE observations only, model = sequence + subject(sequence) + "
        "period; s2_wR is the residual mean square"
    )

    def provenance(self) -> list[str]:
        return [
            f"CVwR estimated by {self.estimator} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]",
            "CV(%) = 100 * sqrt(exp(s2_wR) - 1) — EMA 4.1.10 footnote",
            f"residual degrees of freedom: {self.degrees_of_freedom}",
        ]


def estimate_reference_variability(
    dataset: EmaReplicateDataset,
) -> ReferenceVariability:
    """EMA's CVwR. Reference data only, by the Q&A's stated model."""
    rows = dataset.reference_only()
    if not rows:
        raise DataError(
            "No reference measurements, so there is no within-subject "
            "reference variability to estimate."
        )
    matrix, response, _ = _design_matrix(rows, with_formulation=False)
    fit = fit_least_squares(matrix, response)
    return ReferenceVariability(
        s2_wr=fit.mean_square_error,
        swr=fit.residual_standard_deviation,
        cv_wr_percent=100.0 * math.sqrt(math.expm1(fit.mean_square_error)),
        degrees_of_freedom=fit.degrees_of_freedom,
        n_observations=fit.n_observations,
        n_subjects=len({r.subject_id for r in rows}),
    )


@dataclass(frozen=True, slots=True)
class TreatmentEffect:
    """mu_T - mu_R and its 90% interval, from Method A."""

    estimate: float
    standard_error: float
    degrees_of_freedom: int
    ci_lower: float
    ci_upper: float
    alpha: float
    n_observations: int
    n_subjects: int
    model: str = (
        "EMA/618604/2008 Rev. 13 Method A (guideline recommended): "
        "fixed-effects ANOVA, model = sequence + subject(sequence) + period + "
        "formulation"
    )

    @property
    def geometric_mean_ratio_percent(self) -> float:
        return 100.0 * math.exp(self.estimate)

    @property
    def ci_lower_percent(self) -> float:
        return 100.0 * math.exp(self.ci_lower)

    @property
    def ci_upper_percent(self) -> float:
        return 100.0 * math.exp(self.ci_upper)


def estimate_treatment_effect(dataset: EmaReplicateDataset) -> TreatmentEffect:
    """Method A, over every observation the dataset kept."""
    rows = dataset.observations
    if not any(r.treatment is Treatment.TEST for r in rows):
        raise DataError(
            "No test measurements, so there is no treatment contrast to "
            "estimate."
        )
    matrix, response, index = _design_matrix(rows, with_formulation=True)
    fit = fit_least_squares(matrix, response)
    weights = [0.0] * len(fit.coefficients)
    weights[index] = 1.0
    estimate, se, lower, upper = fit.confidence_interval(weights, alpha=ALPHA)
    return TreatmentEffect(
        estimate=estimate,
        standard_error=se,
        degrees_of_freedom=fit.degrees_of_freedom,
        ci_lower=lower,
        ci_upper=upper,
        alpha=ALPHA,
        n_observations=fit.n_observations,
        n_subjects=len({r.subject_id for r in rows}),
    )


# -------------------------------------------------------- the ABEL limits ---


@dataclass(frozen=True, slots=True)
class AbelLimits:
    """The widened acceptance range, with the cap shown rather than hidden."""

    swr: float
    cv_wr_percent: float
    regulatory_constant_k: float
    #: exp(+/- k * sWR), before any cap. Always reported, even when capped:
    #: a cap that silently replaces a number is a cap nobody can check.
    raw_lower_percent: float
    raw_upper_percent: float
    cap_applied: bool
    final_lower_percent: float
    final_upper_percent: float
    cap_lower_percent: float
    cap_upper_percent: float

    def provenance(self) -> list[str]:
        lines = [
            f"[U, L] = exp[+/- k.sWR] with k = {self.regulatory_constant_k} — "
            f"EMA 4.1.10 [verified, via {VIA_PRIMARY_DOCUMENT}]",
            f"sWR = {self.swr!r} (CVwR {self.cv_wr_percent:.4f}%)",
            f"unconstrained limits {self.raw_lower_percent:.4f} - "
            f"{self.raw_upper_percent:.4f}%",
        ]
        if self.cap_applied:
            lines.append(
                f"CAP APPLIED: 4.1.10 permits widening 'to a maximum of "
                f"{self.cap_lower_percent} - {self.cap_upper_percent}%', and "
                "the unconstrained limits fall outside it"
            )
        else:
            lines.append(
                f"cap not reached ({self.cap_lower_percent} - "
                f"{self.cap_upper_percent}%)"
            )
        return lines


def ema_abel_limits(swr: float) -> AbelLimits:
    """The widened limits for a given sWR, capped as 4.1.10 states.

    THE CAP IS THE REGULATOR'S STATED PAIR, NOT A RECOMPUTED ONE

    4.1.10 says widening is permitted "to a maximum of 69.84 - 143.19%". Those
    are the numbers applied. `spec.ema_abel_cap_computed()` gives what the
    formula would produce at CVwR = 50% (69.83678..., 143.19101...), which
    rounds to the stated pair; a test asserts they agree to the two decimals
    the guideline publishes, and the stated pair is what decides.

    The cap is applied to each limit independently rather than by capping sWR
    first, because the guideline states it as a limit pair. The two agree
    wherever the pair is exactly the formula's value at the cap, and stating
    which one is normative is the point of keeping both.
    """
    if swr <= 0.0:
        raise DataError(
            f"sWR must be positive to form widened limits, got {swr!r}. A zero "
            "within-subject reference variance would give exp(0) = 1, i.e. an "
            "acceptance range of a single point, which is not a rule EMA "
            "states and not one this package will invent."
        )
    k = EMA_HVD_CONSTANTS["regulatory_constant_k"].value
    cap_lower = EMA_HVD_CONSTANTS["cap_lower_percent"].value
    cap_upper = EMA_HVD_CONSTANTS["cap_upper_percent"].value

    raw_lower = 100.0 * math.exp(-k * swr)
    raw_upper = 100.0 * math.exp(+k * swr)

    capped = raw_lower < cap_lower or raw_upper > cap_upper
    return AbelLimits(
        swr=swr,
        cv_wr_percent=100.0 * math.sqrt(math.expm1(swr * swr)),
        regulatory_constant_k=k,
        raw_lower_percent=raw_lower,
        raw_upper_percent=raw_upper,
        cap_applied=capped,
        final_lower_percent=max(raw_lower, cap_lower),
        final_upper_percent=min(raw_upper, cap_upper),
        cap_lower_percent=cap_lower,
        cap_upper_percent=cap_upper,
    )


# ------------------------------------------------------------- the result ---


@dataclass(frozen=True, slots=True)
class EmaHighlyVariableResult:
    """One endpoint, decided or explicitly not.

    Every criterion is exposed on its own. There is no single opaque boolean
    that a caller could read without also seeing which of the two conditions
    produced it.
    """

    endpoint: Endpoint
    design: ReplicateDesign

    swr: float | None
    cv_wr_percent: float | None

    scaling_eligible: bool
    scaling_eligibility_reason: str
    selected_method: Method

    raw_scaled_limits: tuple[float, float] | None
    final_scaled_limits: tuple[float, float] | None
    cap_applied: bool | None

    applied_limits: tuple[float, float] | None
    confidence_interval: tuple[float, float] | None
    geometric_mean_ratio: float | None

    interval_criterion_passes: bool | None
    point_estimate_criterion_passes: bool | None

    decided: bool
    passes: bool | None

    diagnostics: tuple[Diagnostic, ...] = ()
    provenance_lines: tuple[str, ...] = ()
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED
    reference_variability: ReferenceVariability | None = None
    treatment_effect: TreatmentEffect | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def provenance(self) -> list[str]:
        return list(self.provenance_lines)


def _both_criteria(
    *,
    effect: TreatmentEffect,
    lower_percent: float,
    upper_percent: float,
) -> tuple[bool, bool, bool]:
    """Interval containment, point-estimate constraint, and the conjunction.

    4.1.10 requires both: the 90% confidence interval inside the applicable
    limits, AND the GMR inside 80.00-125.00%. They are computed and reported
    separately so a failure says which one failed.
    """
    pe_lower = EMA_HVD_CONSTANTS["point_estimate_lower_percent"].value
    pe_upper = EMA_HVD_CONSTANTS["point_estimate_upper_percent"].value

    interval_ok = (
        effect.ci_lower_percent >= lower_percent
        and effect.ci_upper_percent <= upper_percent
    )
    pe_ok = (
        pe_lower <= effect.geometric_mean_ratio_percent <= pe_upper
    )
    return interval_ok, pe_ok, (interval_ok and pe_ok)


def assess_ema_endpoint(
    observations: list[ReplicateObservation],
    *,
    endpoint: Endpoint,
) -> EmaHighlyVariableResult:
    """The EMA highly-variable decision for one endpoint.

        validated replicate dataset
                -> estimate CVwR from the reference data
                -> is this endpoint scalable at all?
                -> is CVwR > 30%?
              no /                          \\ yes
        ordinary EMA ABE            widened limits, capped
        at 80.00-125.00%            plus the GMR constraint

    Both branches run Method A for the contrast; they differ only in the limits
    the interval is compared against. That is what ABEL is: EMA moves the
    limits, it does not change the test.
    """
    dataset = EmaReplicateDataset.build(observations)
    support, reason = ema_design_support(str(dataset.design))
    if support is not EmaDesignSupport.SUPPORTED:
        raise DataError(
            f"EMA design support for {dataset.design} is {support}: {reason}"
        )

    variability = estimate_reference_variability(dataset)
    effect = estimate_treatment_effect(dataset)

    eligible, eligibility_reason = ema_hvd_scaling_eligible(
        cv_wr_percent=variability.cv_wr_percent, endpoint=endpoint
    )

    provenance = [
        f"EMA {EMA_BIOEQUIVALENCE_HVD.section} "
        f"({EMA_BIOEQUIVALENCE_HVD.document_version})",
        f"precedence: {EMA_M13A_IMPLEMENTATION.document_version} — ICH M13A "
        "does not address highly variable drugs on a replicate design, so "
        "4.1.10 continues to apply",
        f"analysis model: {effect.model} ({EMA_PKWP_QA.document_version})",
        *variability.provenance(),
        f"scaling eligibility: {eligibility_reason}",
    ]

    if eligible:
        limits = ema_abel_limits(variability.swr)
        applied = (limits.final_lower_percent, limits.final_upper_percent)
        provenance.extend(limits.provenance())
        raw = (limits.raw_lower_percent, limits.raw_upper_percent)
        final = applied
        cap_applied: bool | None = limits.cap_applied
        method = Method.EMA_HVD_ABEL
    else:
        pe_lower = EMA_HVD_CONSTANTS["point_estimate_lower_percent"].value
        pe_upper = EMA_HVD_CONSTANTS["point_estimate_upper_percent"].value
        applied = (pe_lower, pe_upper)
        raw = final = None
        cap_applied = None
        method = Method.STANDARD_ABE
        provenance.append(
            f"conventional acceptance range {pe_lower:.2f} - {pe_upper:.2f}% "
            "applied, no widening"
        )

    interval_ok, pe_ok, passes = _both_criteria(
        effect=effect, lower_percent=applied[0], upper_percent=applied[1]
    )

    return EmaHighlyVariableResult(
        endpoint=endpoint,
        design=dataset.design,
        swr=variability.swr,
        cv_wr_percent=variability.cv_wr_percent,
        scaling_eligible=eligible,
        scaling_eligibility_reason=eligibility_reason,
        selected_method=method,
        raw_scaled_limits=raw,
        final_scaled_limits=final,
        cap_applied=cap_applied,
        applied_limits=applied,
        confidence_interval=(effect.ci_lower_percent, effect.ci_upper_percent),
        geometric_mean_ratio=effect.geometric_mean_ratio_percent,
        interval_criterion_passes=interval_ok,
        point_estimate_criterion_passes=pe_ok,
        decided=True,
        passes=passes,
        diagnostics=dataset.diagnostics,
        provenance_lines=tuple(provenance),
        reference_variability=variability,
        treatment_effect=effect,
    )


def assess_ema_study(
    observations_by_endpoint: dict[Endpoint, list[ReplicateObservation]],
) -> dict[Endpoint, EmaHighlyVariableResult]:
    """Every endpoint, decided independently.

    AUC and Cmax do NOT share a scaling decision. Under 4.1.10 Cmax may be
    widened and AUC may not, so the same study can route one endpoint to ABEL
    and the other to the conventional range. Each endpoint is assessed on its
    own data and its own eligibility; nothing is carried across.
    """
    return {
        endpoint: assess_ema_endpoint(rows, endpoint=endpoint)
        for endpoint, rows in observations_by_endpoint.items()
    }


__all__ = [
    "ALPHA",
    "AbelLimits",
    "EMA_DESIGN_SUPPORT",
    "EmaDesignSupport",
    "EmaHighlyVariableResult",
    "EmaObservation",
    "EmaReplicateDataset",
    "ReferenceVariability",
    "TreatmentEffect",
    "assess_ema_endpoint",
    "assess_ema_study",
    "ema_abel_limits",
    "ema_design_support",
    "estimate_reference_variability",
    "estimate_treatment_effect",
]
