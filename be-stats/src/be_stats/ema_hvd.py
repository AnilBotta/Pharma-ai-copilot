"""EMA average bioequivalence with expanding limits (ABEL).

THE RULE, AND WHERE IT COMES FROM

EMA, *Guideline on the Investigation of Bioequivalence*,
CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010, section 4.1.10.

    Highly variable drug products (HVDP) are those whose intra-subject
    variability for a parameter is larger than 30%. ... Those HVDP for which a
    wider difference in Cmax is considered clinically irrelevant based on a
    sound clinical justification can be assessed with a widened acceptance
    range. ... For the acceptance interval to be widened the bioequivalence
    study must be of a replicate design where it has been demonstrated that the
    within-subject variability for Cmax of the reference compound in the study
    is >30%. ... The request for widened interval must be prospectively
    specified in the protocol. The extent of the widening is defined ... using
    scaled-average-bioequivalence according to [U, L] = exp [+/- k.sWR], where
    ... k is the regulatory constant set to 0.760 ... the acceptance criteria
    for Cmax can be widened to a maximum of 69.84 - 143.19%. ... The geometric
    mean ratio (GMR) should lie within the conventional acceptance range
    80.00-125.00%. The possibility to widen the acceptance criteria based on
    high intra-subject variability does not apply to AUC where the acceptance
    range should remain at 80.00 - 125.00% regardless of variability.

VARIABILITY IS NECESSARY AND NOT SUFFICIENT

An earlier version of this module widened every Cmax endpoint whose CVwR
exceeded 30%. The paragraph above names two more conditions and the engine
asked neither: a sound clinical justification that a wider Cmax difference is
clinically irrelevant for the product, and a widened interval prospectively
specified in the protocol. EMA's own Q&A (EMA/618604/2008 Rev. 13, question 4)
calls the first "a prerequisite" and applies it to refuse widening for
clopidogrel. Neither is a property of the data, so both arrive as typed
product metadata - see `spec.ema_abel_widening` - and an unstated one refuses.

FOUR QUESTIONS, ASKED SEPARATELY

    A  design        is this a replicate design 4.1.10 accepts?
    B  variability   is the reference CVwR strictly greater than 30%?
    C  applicability is the endpoint Cmax, and is widening justified and
                     prespecified for this product?
    D  decision      is the Method A 90% CI inside the applicable limits AND
                     the GMR inside 80.00-125.00%?

Each answer is a field on the result. There is no boolean that collapses them.

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

No Howe approximation, no linearized criterion, no sigma_w0, no NTI logic, and
no 0.294. EMA does not scale a criterion; it scales the LIMITS and then runs an
ordinary confidence-interval test against them. The two procedures share
arithmetic no deeper than "fit a linear model", which lives in `linear_model`.

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

UNITS

Every limit and every criterion is compared in PERCENT. The treatment effect is
estimated on the log scale and converted exactly once, by the `*_percent`
properties of `TreatmentEffect`; the regulatory constants are stored in percent.
Nothing converts a percentage a second time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.linear_model import fit_least_squares
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE_HVD,
    EMA_M13A_IMPLEMENTATION,
    EMA_PKWP_QA,
    VIA_PRIMARY_DOCUMENT,
    ValidationStatus,
)
from be_stats.regulatory_rounding import exact_decimal, round_half_up
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
    EMA_HVD_CONSTANTS,
    BeSpec,
    EmaWideningJustification,
    EmaWideningPrespecification,
    EmaWideningStatus,
    Endpoint,
    Jurisdiction,
    Method,
    NotApplicable,
    ema_abel_widening,
    ema_hvd_variability_eligible,
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


#: The model, named once. Read from here rather than from `TreatmentEffect.model`
#: on the class: with `slots=True` a field default is not a class attribute, and
#: the class-level lookup returns a descriptor rather than this string.
METHOD_A_MODEL = (
    "EMA/618604/2008 Rev. 13 Method A (guideline recommended): "
    "fixed-effects ANOVA, model = sequence + subject(sequence) + period + "
    "formulation"
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
    model: str = METHOD_A_MODEL

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
        cap_cv = EMA_HVD_CONSTANTS["cap_cv_percent"].value
        if self.cap_applied:
            lines.append(
                f"CAP APPLIED: CVwR {self.cv_wr_percent:.4f}% >= {cap_cv:.0f}%, so "
                f"the widened range is the published maximum pair "
                f"{self.cap_lower_percent} - {self.cap_upper_percent}% (4.1.10 "
                "table row '>=50')"
            )
        else:
            lines.append(
                f"cap not reached: CVwR {self.cv_wr_percent:.4f}% < {cap_cv:.0f}%, "
                "so the formula limits apply; the published pair "
                f"{self.cap_lower_percent} - {self.cap_upper_percent}% applies "
                f"from CVwR {cap_cv:.0f}%"
            )
        return lines


def ema_abel_limits(swr: float, *, cv_wr_percent: float | None = None) -> AbelLimits:
    """The widened limits for a given sWR, under 4.1.10's cap.

    THE CAP IS ONE RULE, KEYED ON CVwR

    4.1.10's table ends ">=50 | 69.84 | 143.19", and PKWP's Q&A says the
    widening increases "to a maximum of 50%". So:

        30% < CVwR < 50%    [L, U] = exp(-/+ 0.760 * sWR), the formula
        CVwR >= 50%         [L, U] = 69.84 - 143.19%, the published pair

    The pair is applied AS PUBLISHED, not recomputed from k: the formula at
    CVwR = 50% gives 69.83678 - 143.19102, which `spec.ema_abel_cap_computed()`
    returns for comparison and nothing decides with.

    CORRECTED. An earlier version clipped each limit independently against the
    published pair. Because the pair is not exactly reciprocal (1/0.6984 is
    1.43184, not 1.4319), that turned one rule into two floating-point
    crossings: the lower limit capped from CVwR 49.9928% and the upper from
    49.9989%, with a band in between where only one side was capped. EMA
    states no such band, and independent review rejected it.

    The consequence of the corrected rule is stated rather than hidden: for
    CVwR in [49.9928%, 50%) the formula gives limits up to 0.0032 percentage
    points beyond the published pair, and they are applied, because the table
    switches to the pair at 50 and not before. PowerTOST's scABEL applies the
    same switch.

    `cv_wr_percent` is the CVwR the eligibility decision used. Pass it: the cap
    is a rule about CVwR, and re-deriving CVwR from sWR can land a CVwR of
    exactly 50% at 49.99999999999999%. Omitted, it is derived from sWR.
    """
    if swr <= 0.0:
        raise DataError(
            f"sWR must be positive to form widened limits, got {swr!r}. A zero "
            "within-subject reference variance would give exp(0) = 1, i.e. an "
            "acceptance range of a single point, which is not a rule EMA "
            "states and not one this package will invent."
        )
    k = EMA_HVD_CONSTANTS["regulatory_constant_k"].value
    cap_cv = EMA_HVD_CONSTANTS["cap_cv_percent"].value
    cap_lower = EMA_HVD_CONSTANTS["cap_lower_percent"].value
    cap_upper = EMA_HVD_CONSTANTS["cap_upper_percent"].value

    cv = (
        100.0 * math.sqrt(math.expm1(swr * swr))
        if cv_wr_percent is None
        else float(cv_wr_percent)
    )

    raw_lower = 100.0 * math.exp(-k * swr)
    raw_upper = 100.0 * math.exp(+k * swr)

    # One rule: the published pair from CVwR 50%, the formula below it. Both
    # limits change branch together, at the same CVwR.
    capped = cv >= cap_cv
    return AbelLimits(
        swr=swr,
        cv_wr_percent=cv,
        regulatory_constant_k=k,
        raw_lower_percent=raw_lower,
        raw_upper_percent=raw_upper,
        cap_applied=capped,
        final_lower_percent=cap_lower if capped else raw_lower,
        final_upper_percent=cap_upper if capped else raw_upper,
        cap_lower_percent=cap_lower,
        cap_upper_percent=cap_upper,
    )


# ------------------------------------------------------------- the result ---


class EmaAcceptanceStrategy(StrEnum):
    """Which acceptance range a determined endpoint was compared against.

    NOT a method. Both members are the same regulatory procedure,
    `Method.EMA_HVD_ABEL`, computed with the same Method A model; they differ
    only in the limits the interval is held to. An earlier version encoded this
    difference by reporting the conventional branch as `Method.STANDARD_ABE` -
    the 2x2 crossover and parallel procedure, which nothing in this module runs.
    """

    #: exp(+/- 0.760 sWR) below CVwR 50%, 69.84-143.19% at or above it.
    WIDENED_ABEL_LIMITS = "widened_abel_limits"
    #: 80.00-125.00%, CI bounds rounded to two decimals as 4.1.8 states.
    CONVENTIONAL_LIMITS = "conventional_limits"


class EmaResultInconsistent(ValueError):
    """An EMA result was built asserting something the rule did not produce.

    Raised by `EmaHighlyVariableResult.__post_init__`. The lesson of the FDA
    applicability work applies here unchanged: a contradiction that can be
    constructed will eventually be constructed, and a path-only guarantee
    ("the assess function never builds that") does not survive the next
    refactor. So the contradictions are made impossible to build.
    """


def _conventional_limits() -> tuple[float, float]:
    return (
        EMA_HVD_CONSTANTS["point_estimate_lower_percent"].value,
        EMA_HVD_CONSTANTS["point_estimate_upper_percent"].value,
    )


def _interval_contained(
    *,
    effect: TreatmentEffect,
    lower_percent: float,
    upper_percent: float,
    widened: bool,
) -> bool:
    """THE comparison of a 90% CI with acceptance limits. One definition.

    Both the assessment and `EmaHighlyVariableResult.__post_init__` call this,
    through `_both_criteria`, so the decision and the check on the decision
    cannot use two different rules.

    CONVENTIONAL 80.00-125.00% - ROUNDED, BECAUSE 4.1.8 SAYS SO

    "the lower bound should be >= 80.00% when rounded to two decimal places
    and the upper bound should be <= 125.00% when rounded to two decimal
    places." Applied to AUC, to Cmax with CVwR <= 30%, and to Cmax whose
    widening is explicitly not justified or not prespecified. The bounds are
    rounded in `decimal` under `regulatory_rounding.TIE_POLICY`; the limits
    are compared as the decimals they are. ICH M13A 2.2.4 states the same
    range without a rounding sentence; for a replicate study EMA/531548/2024
    reads the 2010 guideline and M13A in conjunction, and 4.1.8 states one.

    WIDENED LIMITS - UNROUNDED, AND RECORDED AS AN OPEN QUESTION

    4.1.10 gives the widened limits by formula and prints its table to two
    decimals, and does not say whether the CI is rounded before it is compared
    with them. Nothing in 4.1.10, 4.1.8 or the PKWP Q&A settles it. Rather
    than choose silently, the CI is compared UNROUNDED with the limits as
    computed - which grants no bound a rounding margin EMA has not stated -
    and the question is VAL-EMA-ABEL-003.

    `widened` has no default. A caller that does not say which rule applies
    does not get one.
    """
    if widened:
        return (
            effect.ci_lower_percent >= lower_percent
            and effect.ci_upper_percent <= upper_percent
        )
    return (
        round_half_up(effect.ci_lower_percent) >= exact_decimal(lower_percent)
        and round_half_up(effect.ci_upper_percent) <= exact_decimal(upper_percent)
    )


def _both_criteria(
    *,
    effect: TreatmentEffect,
    lower_percent: float,
    upper_percent: float,
    widened: bool,
) -> tuple[bool, bool, bool]:
    """Interval containment, point-estimate constraint, and the conjunction.

    4.1.10 requires both: the 90% confidence interval inside the applicable
    limits, AND the GMR inside 80.00-125.00%. They are computed and reported
    separately so a failure says which one failed. The GMR range is read from
    the constants and never from the limits passed in, so widening the
    interval cannot widen it. The GMR is compared as estimated: 4.1.8's
    rounding sentence is about the confidence interval's bounds.
    """
    pe_lower, pe_upper = _conventional_limits()

    interval_ok = _interval_contained(
        effect=effect,
        lower_percent=lower_percent,
        upper_percent=upper_percent,
        widened=widened,
    )
    pe_ok = (
        pe_lower <= effect.geometric_mean_ratio_percent <= pe_upper
    )
    return interval_ok, pe_ok, (interval_ok and pe_ok)


_JUSTIFICATION_WORDS = {
    EmaWideningJustification.JUSTIFIED: "established",
    EmaWideningJustification.NOT_JUSTIFIED: "explicitly NOT established",
    EmaWideningJustification.NOT_STATED: "NOT STATED",
}

_PRESPECIFICATION_WORDS = {
    EmaWideningPrespecification.PRESPECIFIED: "yes",
    EmaWideningPrespecification.NOT_PRESPECIFIED: "explicitly NO",
    EmaWideningPrespecification.NOT_STATED: "NOT STATED",
}


@dataclass(frozen=True, slots=True)
class EmaHighlyVariableResult:
    """One endpoint, decided or explicitly not - and unable to say otherwise.

    The four questions each have their own fields:

        A  design                       `design` (a supported replicate design,
                                        or the analysis raised before this)
        B  variability                  `reference_variability`,
                                        `variability_eligible`
        C  endpoint and basis           `clinical_justification`,
                                        `protocol_prespecification`,
                                        `widening_status`, `widening_reason`
        D  decision                     `applied_limits`, the two criteria,
                                        `decided`, `passes`

    Everything else - the selected method, the scaled limits, the interval,
    the GMR - is DERIVED from those, so there is no second field to disagree
    with the first. `__post_init__` re-runs the rule and refuses any object
    whose widening status the rule would not give, and any decision whose
    criteria do not follow from its own interval.
    """

    endpoint: Endpoint
    design: ReplicateDesign
    clinical_justification: EmaWideningJustification
    protocol_prespecification: EmaWideningPrespecification
    widening_status: EmaWideningStatus
    widening_reason: str
    reference_variability: ReferenceVariability | None
    variability_eligible: bool | None
    limits: AbelLimits | None
    treatment_effect: TreatmentEffect | None
    applied_limits: tuple[float, float] | None
    interval_criterion_passes: bool | None
    point_estimate_criterion_passes: bool | None
    decided: bool
    passes: bool | None
    diagnostics: tuple[Diagnostic, ...] = ()
    provenance_lines: tuple[str, ...] = ()
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: The method of the `BeSpec` the caller supplied, if one was. Kept so a
    #: decided result can be held to the method the router selected.
    spec_method: Method | None = None

    def __post_init__(self) -> None:
        def refuse(message: str) -> None:
            raise EmaResultInconsistent(f"{self.endpoint}: {message}")

        # METHOD IDENTITY. This engine executes one regulatory procedure,
        # EMA_HVD_ABEL, with one model, Method A. Which acceptance range applied
        # is a separate fact and may not masquerade as a different method.
        if self.spec_method is not None and self.spec_method is not Method.EMA_HVD_ABEL:
            refuse(
                f"built for a spec selecting {self.spec_method}; this engine "
                "implements EMA_HVD_ABEL only"
            )
        if self.treatment_effect is not None and self.treatment_effect.model != METHOD_A_MODEL:
            refuse(
                f"carries a treatment effect from {self.treatment_effect.model!r}; "
                "every EMA highly variable decision is computed with Method A"
            )
        # Spec and result cannot disagree, by construction rather than by a
        # third check: a supplied spec must select EMA_HVD_ABEL (above), and a
        # decided result's method is derived as EMA_HVD_ABEL from `decided`
        # alone. A separate "spec_method is selected_method" guard was removed
        # after mutation testing showed it could never fire while those two
        # hold; `test_the_router_and_the_result_agree_on_the_method_for_every_
        # decided_endpoint` holds the equality itself.

        if not isinstance(self.clinical_justification, EmaWideningJustification):
            refuse("clinical_justification is not an EmaWideningJustification")
        if not isinstance(
            self.protocol_prespecification, EmaWideningPrespecification
        ):
            refuse("protocol_prespecification is not an EmaWideningPrespecification")
        if not isinstance(self.widening_status, EmaWideningStatus):
            refuse("widening_status is not an EmaWideningStatus")

        cv = (
            None
            if self.reference_variability is None
            else self.reference_variability.cv_wr_percent
        )

        # C: the status must be the one the rule gives for these inputs. This
        # single check is what makes "AUC widened", "not justified yet
        # widened" and "CVwR 20% yet widened" impossible to construct.
        expected, _ = ema_abel_widening(
            endpoint=self.endpoint,
            cv_wr_percent=cv,
            clinical_justification=self.clinical_justification,
            protocol_prespecification=self.protocol_prespecification,
        )
        if expected is not self.widening_status:
            refuse(
                f"widening_status {self.widening_status} contradicts the rule, "
                f"which gives {expected} for these inputs"
            )

        # B: the variability answer follows from the estimate, or is absent.
        expected_eligible = (
            None
            if cv is None
            else ema_hvd_variability_eligible(cv_wr_percent=cv)[0]
        )
        if self.variability_eligible is not expected_eligible:
            refuse(
                f"variability_eligible={self.variability_eligible} but the "
                f"estimated CVwR gives {expected_eligible}"
            )

        # Widened limits exist exactly when the range is widened.
        if self.widening_status.widened:
            if self.limits is None:
                refuse("widened, with no widened limits")
            expected_limits = ema_abel_limits(
                self.reference_variability.swr,
                cv_wr_percent=self.reference_variability.cv_wr_percent,
            )
            if self.limits != expected_limits:
                refuse(
                    "widened limits are not the ones 4.1.10 gives for this sWR "
                    "and CVwR: the formula below CVwR 50%, the published pair "
                    "69.84 - 143.19% at or above it"
                )
        elif self.limits is not None:
            refuse(
                f"widened limits carried although the range is "
                f"{self.widening_status}"
            )

        # The limits applied are the ones the status selects, or none.
        # No separate "undetermined" check here: an undetermined range with
        # applied limits is refused below either as a decision on an
        # undetermined range or as a refusal carrying an analysis. A second
        # guard for the same state was removed after mutation testing showed
        # neither could be observed while the other existed.
        if self.applied_limits is not None:
            if self.widening_status.widened:
                selected = (
                    self.limits.final_lower_percent,
                    self.limits.final_upper_percent,
                )
            else:
                selected = _conventional_limits()
            if tuple(self.applied_limits) != selected:
                refuse(
                    f"applied limits {self.applied_limits} are not the "
                    f"{self.widening_status} limits {selected}"
                )

        # D.
        if self.decided:
            if not self.widening_status.determined:
                refuse("decided although the applicable range is undetermined")
            if self.treatment_effect is None:
                refuse("decided with no Method A result")
            if not self.treatment_effect.standard_error > 0.0:
                refuse("decided on a Method A interval with no width")
            if self.applied_limits is None:
                refuse("decided with no applied limits")
            interval_ok, pe_ok, both = _both_criteria(
                effect=self.treatment_effect,
                lower_percent=self.applied_limits[0],
                upper_percent=self.applied_limits[1],
                widened=self.widening_status.widened,
            )
            if (
                self.interval_criterion_passes is not interval_ok
                or self.point_estimate_criterion_passes is not pe_ok
                or self.passes is not both
            ):
                refuse(
                    "the criteria and the verdict do not follow from the "
                    "interval, the GMR and the applied limits"
                )
        else:
            if self.passes is not None:
                refuse("not decided, yet passes is not None")
            if (
                self.interval_criterion_passes is not None
                or self.point_estimate_criterion_passes is not None
            ):
                refuse("not decided, yet a criterion was evaluated")
            if self.applied_limits is not None or self.treatment_effect is not None:
                refuse("not decided, yet carries applied limits or a Method A result")
            if not any(d.severity is Severity.FATAL for d in self.diagnostics):
                refuse("not decided, and no FATAL diagnostic says why")

    # ------------------------------------------------------ derived views ---

    @property
    def swr(self) -> float | None:
        return None if self.reference_variability is None else self.reference_variability.swr

    @property
    def cv_wr_percent(self) -> float | None:
        return (
            None
            if self.reference_variability is None
            else self.reference_variability.cv_wr_percent
        )

    @property
    def scaling_eligible(self) -> bool:
        """True only when the range IS widened - every condition, not variability alone."""
        return self.widening_status.widened

    @property
    def scaling_eligibility_reason(self) -> str:
        return self.widening_reason

    @property
    def selected_method(self) -> Method | None:
        """The regulatory procedure that decided this endpoint, or None.

        CORRECTED. This returned `Method.STANDARD_ABE` for every determined
        branch that was not widened - AUC, Cmax at CVwR <= 30%, Cmax not
        justified or not prespecified. All of those were computed with EMA
        Method A, the replicate ANOVA, and `resolve_be_spec` selects
        EMA_HVD_ABEL for them. STANDARD_ABE is the 2x2 crossover and parallel
        procedure, and the label claimed a model that never ran.

        Now: EMA_HVD_ABEL for every DECIDED result, None for every refusal. It
        reads `decided` and nothing else - not the limits, not the widening
        status - so a change of acceptance range cannot change the method. The
        range is `acceptance_strategy`.
        """
        return Method.EMA_HVD_ABEL if self.decided else None

    @property
    def acceptance_strategy(self) -> EmaAcceptanceStrategy | None:
        """Widened or conventional limits; None where the range is undetermined."""
        if not self.widening_status.determined:
            return None
        if self.widening_status.widened:
            return EmaAcceptanceStrategy.WIDENED_ABEL_LIMITS
        return EmaAcceptanceStrategy.CONVENTIONAL_LIMITS

    @property
    def analysis_model(self) -> str | None:
        """The statistical model actually fitted, or None where none was."""
        return None if self.treatment_effect is None else self.treatment_effect.model

    @property
    def raw_scaled_limits(self) -> tuple[float, float] | None:
        if self.limits is None:
            return None
        return (self.limits.raw_lower_percent, self.limits.raw_upper_percent)

    @property
    def final_scaled_limits(self) -> tuple[float, float] | None:
        if self.limits is None:
            return None
        return (self.limits.final_lower_percent, self.limits.final_upper_percent)

    @property
    def cap_applied(self) -> bool | None:
        return None if self.limits is None else self.limits.cap_applied

    @property
    def confidence_interval(self) -> tuple[float, float] | None:
        if self.treatment_effect is None:
            return None
        return (
            self.treatment_effect.ci_lower_percent,
            self.treatment_effect.ci_upper_percent,
        )

    @property
    def geometric_mean_ratio(self) -> float | None:
        if self.treatment_effect is None:
            return None
        return self.treatment_effect.geometric_mean_ratio_percent

    @property
    def point_estimate_limits(self) -> tuple[float, float]:
        """80.00-125.00%, always. Never the widened limits."""
        return _conventional_limits()

    def provenance(self) -> list[str]:
        return list(self.provenance_lines)

    def summary(self) -> str:
        """One endpoint, top to bottom, in the order a reviewer checks it."""
        lines: list[str] = []
        if not self.decided:
            lines.append("NO ABEL DECISION ISSUED")
        lines.append("Regulator: EMA.")
        lines.append(f"Endpoint: {self.endpoint}.")
        lines.append(
            f"Replicate design: {self.design} - acceptable under 4.1.10 "
            "(3- or 4-period replicate crossover); procedure EMA_HVD_ABEL, "
            "analysed with EMA Method A."
        )
        threshold = EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"].value
        if self.reference_variability is None:
            lines.append(
                f"Reference CVwR: not estimable; EMA ABEL requires >{threshold:.0f}%."
            )
        else:
            lines.append(
                f"Reference CVwR = {self.reference_variability.cv_wr_percent:.2f}% "
                f"(sWR = {self.reference_variability.swr:.6f}); EMA ABEL "
                f"requires >{threshold:.0f}%."
            )
        lines.append(
            "Clinical justification for widening: "
            f"{_JUSTIFICATION_WORDS[self.clinical_justification]}."
        )
        lines.append(
            "Widened interval prospectively specified in the protocol: "
            f"{_PRESPECIFICATION_WORDS[self.protocol_prespecification]}."
        )
        if self.widening_status.widened:
            limits = self.limits
            lines.append(f"k = {limits.regulatory_constant_k:.3f}.")
            cap_cv = EMA_HVD_CONSTANTS["cap_cv_percent"].value
            cap = (
                f"CVwR >= {cap_cv:.0f}%: the published pair applies"
                if limits.cap_applied
                else f"CVwR < {cap_cv:.0f}%: the formula applies"
            )
            lines.append(
                f"Expanded acceptance interval = [{limits.final_lower_percent:.2f}%, "
                f"{limits.final_upper_percent:.2f}%], capped at "
                f"{limits.cap_lower_percent:.2f}-{limits.cap_upper_percent:.2f}% "
                f"from CVwR {cap_cv:.0f}% ({cap})."
            )
        elif self.widening_status.determined:
            low, high = _conventional_limits()
            lines.append(
                f"Acceptance interval = [{low:.2f}%, {high:.2f}%], NOT widened: "
                f"{self.widening_reason}"
            )
        else:
            lines.append(f"Acceptance range UNDETERMINED: {self.widening_reason}")

        if self.treatment_effect is not None:
            effect = self.treatment_effect
            lines.append(
                f"Method A 90% CI = [{effect.ci_lower_percent:.2f}%, "
                f"{effect.ci_upper_percent:.2f}%]."
            )
            low, high = _conventional_limits()
            lines.append(
                f"GMR = {effect.geometric_mean_ratio_percent:.2f}%; required "
                f"inside {low:.2f}-{high:.2f}%."
            )

        lines.append(f"Final decision: {self._decision_sentence()}")
        for diagnostic in self.diagnostics:
            if diagnostic.severity is Severity.FATAL:
                lines.append(str(diagnostic))
        return "\n".join(lines)

    def _decision_sentence(self) -> str:
        if not self.decided:
            reasons = "; ".join(
                d.detail for d in self.diagnostics if d.severity is Severity.FATAL
            )
            return f"NONE - no bioequivalence decision was issued. {reasons}"
        low, high = self.applied_limits
        interval = (
            f"the Method A 90% CI {'lies' if self.interval_criterion_passes else 'does not lie'} "
            f"inside [{low:.2f}%, {high:.2f}%]"
        )
        pe_low, pe_high = _conventional_limits()
        gmr = (
            f"the GMR {'lies' if self.point_estimate_criterion_passes else 'does not lie'} "
            f"inside {pe_low:.2f}-{pe_high:.2f}%"
        )
        comparison = (
            "CI bounds compared unrounded with the widened limits - see "
            "VAL-EMA-ABEL-003"
            if self.widening_status.widened
            else "CI bounds rounded to two decimal places before comparison, "
            "as 4.1.8 states"
        )
        verdict = "PASS" if self.passes else "FAIL"
        return (
            f"{verdict}: {interval}, {gmr} ({comparison})."
            if self.passes
            else f"{verdict} because {interval}, and {gmr} ({comparison})."
        )


# -------------------------------------------------------------- assembly ---


def _require_ema_hvd_spec(spec: BeSpec | None, endpoint: Endpoint) -> None:
    """A supplied spec must be EMA's highly variable route, for this endpoint."""
    if spec is None:
        return
    if spec.jurisdiction is not Jurisdiction.EMA or spec.method is not Method.EMA_HVD_ABEL:
        raise NotApplicable(
            f"assess_ema_endpoint implements EMA 4.1.10 and was given a spec "
            f"for {spec.jurisdiction} {spec.method}. It does not reconcile "
            "another route's spec; resolve the spec for the EMA highly variable "
            "route or use the module that implements the one resolved."
        )
    if spec.endpoint is not endpoint:
        raise NotApplicable(
            f"The spec was resolved for {spec.endpoint} and the analysis was "
            f"asked for {endpoint}. Whether Cmax may be widened is decided per "
            "endpoint, so the two may not differ."
        )


def _not_estimable(quantity: str, exc: Exception, *, fatal: bool) -> Diagnostic:
    return Diagnostic(
        DiagnosticCode.EMA_ABEL_QUANTITY_NOT_ESTIMABLE,
        Severity.FATAL if fatal else Severity.ADVISORY,
        None,
        f"{quantity} could not be estimated: {exc}",
        {"quantity": quantity},
    )


def assess_ema_endpoint(
    observations: list[ReplicateObservation],
    *,
    endpoint: Endpoint,
    clinical_justification: EmaWideningJustification = EmaWideningJustification.NOT_STATED,
    protocol_prespecification: EmaWideningPrespecification = (
        EmaWideningPrespecification.NOT_STATED
    ),
    spec: BeSpec | None = None,
) -> EmaHighlyVariableResult:
    """The EMA highly-variable decision for one endpoint.

        A  validated replicate dataset, on a design 4.1.10 accepts
        B  CVwR from the reference data only
        C  the rule: endpoint, then variability, then the basis for widening
                                 |
          widened  ------  conventional 80.00-125.00%  ------  undetermined
              \\                    |                              |
        D  Method A 90% CI inside the applied limits          no decision:
           AND GMR inside 80.00-125.00%                       CVwR reported,
                                                              nothing else

    Both determined branches run Method A for the contrast; they differ only in
    the limits the interval is compared against. That is what ABEL is: EMA
    moves the limits, it does not change the test.

    The basis for widening defaults to NOT_STATED and is never inferred. A
    highly variable Cmax endpoint analysed without it receives no decision - on
    purpose, because the alternative is to assume a clinical judgement nobody
    made.

    CALLER-SELECTED, NOT ROUTED

    This function executes EMA's highly variable procedure; it does not decide
    that the procedure applies. `resolve_be_spec` is the router, and a `spec`
    passed here must be the EMA highly variable route for the same endpoint -
    an EMA NTI spec, an FDA spec or a standard-class spec raises
    `NotApplicable`. With `spec=None` the caller has chosen the method itself,
    and nothing here can tell that the product is not, say, an NTI drug. The
    basis for widening narrows that risk - a wider Cmax difference is not
    clinically irrelevant for an NTI drug - and does not remove it.
    """
    endpoint = Endpoint(endpoint)
    _require_ema_hvd_spec(spec, endpoint)
    # Refuse a bool or a string before any data is read.
    ema_abel_widening(
        endpoint=endpoint,
        cv_wr_percent=None,
        clinical_justification=clinical_justification,
        protocol_prespecification=protocol_prespecification,
    )

    dataset = EmaReplicateDataset.build(observations)
    known_endpoints = {e.value for e in Endpoint}
    if dataset.endpoint in known_endpoints and dataset.endpoint != endpoint.value:
        raise DataError(
            f"The observations are labelled {dataset.endpoint!r} and the "
            f"analysis was asked for {endpoint}. Widening is decided per "
            "endpoint, so a mislabelled AUC must not be analysed as Cmax."
        )

    # A: the design.
    support, design_reason = ema_design_support(str(dataset.design))
    if support is not EmaDesignSupport.SUPPORTED:
        raise DataError(
            f"EMA design support for {dataset.design} is {support}: {design_reason}"
        )

    diagnostics = list(dataset.diagnostics)
    widenable_endpoint = not ema_abel_widening(
        endpoint=endpoint,
        cv_wr_percent=None,
        clinical_justification=clinical_justification,
        protocol_prespecification=protocol_prespecification,
    )[0] is EmaWideningStatus.NOT_WIDENED_ENDPOINT

    # B: reference variability. Its failure decides nothing for AUC, whose
    # range does not depend on it, and leaves Cmax undetermined.
    variability: ReferenceVariability | None
    try:
        variability = estimate_reference_variability(dataset)
    except (DataError, ValueError) as exc:
        variability = None
        diagnostics.append(
            _not_estimable("reference variability", exc, fatal=widenable_endpoint)
        )

    variability_eligible = (
        None
        if variability is None
        else ema_hvd_variability_eligible(cv_wr_percent=variability.cv_wr_percent)[0]
    )

    # C: which range applies.
    status, reason = ema_abel_widening(
        endpoint=endpoint,
        cv_wr_percent=None if variability is None else variability.cv_wr_percent,
        clinical_justification=clinical_justification,
        protocol_prespecification=protocol_prespecification,
    )

    provenance = [
        f"EMA {EMA_BIOEQUIVALENCE_HVD.section} "
        f"({EMA_BIOEQUIVALENCE_HVD.document_version})",
        f"precedence: {EMA_M13A_IMPLEMENTATION.document_version} — ICH M13A "
        "does not address highly variable drugs on a replicate design, so "
        "4.1.10 continues to apply",
        f"design: {dataset.design} — {design_reason}",
        f"analysis model: {METHOD_A_MODEL} ({EMA_PKWP_QA.document_version})",
        *([] if variability is None else variability.provenance()),
        f"clinical justification: {clinical_justification}; protocol "
        f"prespecification: {protocol_prespecification}",
        f"acceptance range: {status} — {reason}",
    ]

    if status is EmaWideningStatus.UNDETERMINED_BASIS_NOT_STATED:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.EMA_ABEL_WIDENING_BASIS_NOT_STATED,
                Severity.FATAL,
                None,
                reason,
                {
                    "clinical_justification": str(clinical_justification),
                    "protocol_prespecification": str(protocol_prespecification),
                },
            )
        )
    elif status is EmaWideningStatus.NOT_WIDENED_BASIS_ABSENT:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.EMA_ABEL_WIDENING_NOT_PERMITTED,
                Severity.ADVISORY,
                None,
                reason,
                {
                    "clinical_justification": str(clinical_justification),
                    "protocol_prespecification": str(protocol_prespecification),
                },
            )
        )
    elif status is EmaWideningStatus.UNDETERMINED_ENDPOINT_NOT_COVERED:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.EMA_HVD_ENDPOINT_NOT_COVERED,
                Severity.FATAL,
                None,
                reason,
                {"endpoint": str(endpoint)},
            )
        )

    def refused() -> EmaHighlyVariableResult:
        return EmaHighlyVariableResult(
            endpoint=endpoint,
            design=dataset.design,
            clinical_justification=clinical_justification,
            protocol_prespecification=protocol_prespecification,
            widening_status=status,
            widening_reason=reason,
            reference_variability=variability,
            variability_eligible=variability_eligible,
            limits=limits,
            treatment_effect=None,
            applied_limits=None,
            interval_criterion_passes=None,
            point_estimate_criterion_passes=None,
            decided=False,
            passes=None,
            diagnostics=tuple(diagnostics),
            provenance_lines=tuple(provenance),
            spec_method=None if spec is None else spec.method,
        )

    limits = (
        ema_abel_limits(variability.swr, cv_wr_percent=variability.cv_wr_percent)
        if status.widened
        else None
    )
    if limits is not None:
        provenance.extend(limits.provenance())

    if not status.determined:
        return refused()

    # D: Method A, then the two criteria.
    try:
        effect = estimate_treatment_effect(dataset)
        if not effect.standard_error > 0.0:
            raise ValueError(
                "the Method A residual variance is zero, so the 90% interval "
                "has no width and cannot be compared with any limit"
            )
    except (DataError, ValueError) as exc:
        diagnostics.append(_not_estimable("Method A treatment effect", exc, fatal=True))
        return refused()

    applied = (
        (limits.final_lower_percent, limits.final_upper_percent)
        if limits is not None
        else _conventional_limits()
    )
    if limits is None:
        provenance.append(
            f"conventional acceptance range {applied[0]:.2f} - {applied[1]:.2f}% "
            "applied, no widening"
        )
    interval_ok, pe_ok, passes = _both_criteria(
        effect=effect,
        lower_percent=applied[0],
        upper_percent=applied[1],
        widened=status.widened,
    )

    return EmaHighlyVariableResult(
        endpoint=endpoint,
        design=dataset.design,
        clinical_justification=clinical_justification,
        protocol_prespecification=protocol_prespecification,
        widening_status=status,
        widening_reason=reason,
        reference_variability=variability,
        variability_eligible=variability_eligible,
        limits=limits,
        treatment_effect=effect,
        applied_limits=applied,
        interval_criterion_passes=interval_ok,
        point_estimate_criterion_passes=pe_ok,
        decided=True,
        passes=passes,
        diagnostics=tuple(diagnostics),
        provenance_lines=tuple(provenance),
        spec_method=None if spec is None else spec.method,
    )


def assess_ema_study(
    observations_by_endpoint: dict[Endpoint, list[ReplicateObservation]],
    *,
    clinical_justification: EmaWideningJustification = EmaWideningJustification.NOT_STATED,
    protocol_prespecification: EmaWideningPrespecification = (
        EmaWideningPrespecification.NOT_STATED
    ),
) -> dict[Endpoint, EmaHighlyVariableResult]:
    """Every endpoint, decided independently.

    AUC and Cmax do NOT share a scaling decision. Under 4.1.10 Cmax may be
    widened and AUC may not, so the same study can route one endpoint to ABEL
    and the other to the conventional range. Each endpoint is assessed on its
    own data and its own eligibility; the basis for widening is product
    metadata and is passed to each, where only Cmax consults it.
    """
    return {
        endpoint: assess_ema_endpoint(
            rows,
            endpoint=endpoint,
            clinical_justification=clinical_justification,
            protocol_prespecification=protocol_prespecification,
        )
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
    "EmaAcceptanceStrategy",
    "EmaResultInconsistent",
    "METHOD_A_MODEL",
    "ReferenceVariability",
    "TreatmentEffect",
    "assess_ema_endpoint",
    "assess_ema_study",
    "ema_abel_limits",
    "ema_design_support",
    "estimate_reference_variability",
    "estimate_treatment_effect",
]
