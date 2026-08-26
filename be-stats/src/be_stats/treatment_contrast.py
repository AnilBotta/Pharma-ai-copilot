"""The treatment contrast: mu_T - mu_R, weighted the way FDA weights it.

THE ONE THING MOST LIKELY TO BE GOT WRONG HERE

FDA's SAS estimates the contrast as an equally weighted average of the SEQUENCE
means, not as an average over subjects:

    estimate 'average' intercept 1 seq 0.3333333333 0.3333333333 0.3333333333;

With equal group sizes those coincide. With unequal ones they do not, and the
difference is not small - a study with 12 subjects in TRR and 4 in RRT weights
each RRT subject three times as heavily under FDA's estimator as a subject
average would. Dropouts make sequences unequal in almost every real study, so
this is the ordinary case rather than a corner.

`test_unbalanced_sequences` exists to prove the engine did not take the naive
subject mean, by computing both and asserting the engine matched the right one.

WHY SEQUENCE AND NOT SUBJECT

The subject-level intermediate `Iij` still carries the period and sequence
structure of the design. Averaging the sequence means gives each sequence -
and so each arrangement of periods - the same influence on the answer, which is
what makes the period effects cancel. A subject-weighted mean lets whichever
sequence retained the most subjects pull the estimate toward its own period
pattern.

THIS IS THE APPENDIX G INTERMEDIATE, NOT AN AVERAGE-BE ANALYSIS

`Iij` exists to build the reference-scaled criterion: FDA forms `x` and
`bound_x` from exactly this contrast, at exactly this alpha. That is what it is
for and where it is right.

It is NOT FDA's unscaled average BE analysis for a replicate study. That is
Appendix C, a different model on different data - subject-period observations,
a period term, an unstructured subject-by-formulation covariance, and separate
residual variances for T and R. See `replicate_abe.py`. The two must not be
made to serve one another simply because both end in a T-R contrast.

TWO DESIGNS, TWO ESTIMATORS - AND THIS TIME IT IS NOT THE SAME FORMULA

Appendix G gives one sWR equation for both designs. It does NOT do the same for
the contrast: the partial replicate is fitted with `PROC GLM` and the fully
replicated design with `PROC MIXED ... ddfm=satterth`. That the variance
estimator is shared is not a reason to share this one, so the two are separate
classes and the degrees of freedom are derived separately.

For the fully replicated case the Satterthwaite degrees of freedom are computed
rather than assumed - see `satterthwaite_df`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy import stats

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    VIA_PRIMARY_DOCUMENT,
    ValidationStatus,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateSequence,
    treatment_contrasts,
)

#: FDA's `estimate ... / cl alpha=0.1` gives a two-sided 90% interval, which is
#: the two-one-sided-tests interval at 5% each. Stated once.
CONTRAST_ALPHA = 0.10


def satterthwaite_df(components: list[tuple[float, float, int]]) -> float:
    """Satterthwaite degrees of freedom for a linear combination of variances.

        df = 2 (SUM g_i s_i^2)^2 / SUM ( g_i^2 * 2 s_i^4 / v_i )

    where each component is `(g_i, s_i^2, v_i)`: its coefficient, its estimate
    and its own degrees of freedom.

    WHY THIS IS COMPUTED AND NOT HARD-CODED

    FDA asks for `ddfm=satterth` on the fully replicated design. Its model
    there - `model ilat = seq`, with no RANDOM and no REPEATED statement - has a
    single residual variance component, and for a single component the formula
    collapses:

        df = 2 (g s^2)^2 / ( g^2 * 2 s^4 / v ) = v

    exactly, for any coefficient. So the Satterthwaite result IS the residual
    degrees of freedom here - not an approximation of them, and not a
    substitution for them.

    Writing it as the general formula rather than returning `n - 2` matters for
    two reasons. It is checkable: a test asserts the collapse rather than
    asserting a number. And if a future model gains a second variance
    component, this function keeps working while a hard-coded `n - 2` would
    silently be wrong.

    THE SCOPE OF THAT CLAIM, STATED NARROWLY

    "Satterthwaite reduces to the residual degrees of freedom" is true of
    **Appendix G's `ilat = seq` model and nothing else in this guidance.** It
    holds because that model has one variance component.

    It is emphatically NOT true of Appendix C, whose model carries five: an
    unstructured 2x2 subject-by-formulation covariance and two
    treatment-specific residual variances. Its Satterthwaite degrees of freedom
    must come from that model's own covariance-parameter estimates and their
    asymptotic covariance. Reusing `n - 2` there would be wrong, and wrong in a
    way that produces a plausible interval.
    """
    if not components:
        raise ValueError("Satterthwaite degrees of freedom need a component.")
    numerator = math.fsum(g * s2 for g, s2, _ in components)
    if numerator == 0.0:
        raise ValueError(
            "The estimated variance of the contrast is zero, so Satterthwaite "
            "degrees of freedom are undefined."
        )
    denominator = math.fsum(
        (g**2) * 2.0 * (s2**2) / v for g, s2, v in components if v > 0
    )
    if denominator <= 0.0:
        raise ValueError(
            "No component carries degrees of freedom; Satterthwaite is undefined."
        )
    return 2.0 * (numerator**2) / denominator


@dataclass(frozen=True, slots=True)
class TreatmentContrastResult:
    """mu_T - mu_R on the log scale, with everything needed to check it."""

    design: ReplicateDesign
    endpoint: str

    #: mu_T - mu_R on the log scale: the equally weighted mean of the sequence
    #: means of `Iij`.
    estimate: float
    standard_error: float
    #: Residual for the partial replicate; Satterthwaite for the fully
    #: replicated design, which here equals the residual - see
    #: `satterthwaite_df`. Float because Satterthwaite need not be an integer.
    degrees_of_freedom: float
    #: How that number was arrived at, so a reader need not infer it.
    degrees_of_freedom_basis: str

    #: The 90% interval on the LOG scale. Appendix G squares the larger
    #: absolute limit to form `boundx`, so the log-scale limits - not the
    #: percentages - are the load-bearing ones.
    ci_lower: float
    ci_upper: float
    alpha: float

    #: exp(estimate): the T/R geometric mean ratio, as a fraction.
    point_estimate: float

    #: Subjects contributing an `Iij`. NOT necessarily the number contributing
    #: to sWR - a subject missing its test measurement has no contrast and may
    #: still have both reference replicates.
    n_subjects: int
    n_by_sequence: dict[ReplicateSequence, int]
    #: The weight each sequence mean received. Equal by construction, and
    #: reported so an unbalanced study can be checked at a glance.
    sequence_weights: dict[ReplicateSequence, float]
    #: Residual mean square of the one-way model on `Iij`.
    mean_square_error: float

    estimable: bool = True
    diagnostics: tuple[Diagnostic, ...] = ()
    estimator: str = ""
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED

    @property
    def point_estimate_percent(self) -> float:
        return 100.0 * self.point_estimate

    @property
    def ci_lower_percent(self) -> float:
        return 100.0 * math.exp(self.ci_lower)

    @property
    def ci_upper_percent(self) -> float:
        return 100.0 * math.exp(self.ci_upper)

    def provenance(self) -> list[str]:
        return [
            f"mu_T - mu_R estimated as the equally weighted mean of the "
            f"{len(self.sequence_weights)} sequence means of "
            f"Iij — {FDA_STATISTICAL_APPROACHES_APPENDIX_G} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]",
            f"degrees of freedom: {self.degrees_of_freedom_basis}",
            f"interval: two-sided {1 - self.alpha:.0%} on the log scale "
            f"(FDA's `estimate ... / cl alpha={self.alpha}`)",
        ]


class _TreatmentContrastEstimator:
    """One-way model on `Iij`, with equal weight on every sequence mean."""

    design: ReplicateDesign
    name: str
    df_basis: str

    def estimate(
        self,
        dataset: ReplicateDataset,
        *,
        alpha: float = CONTRAST_ALPHA,
    ) -> TreatmentContrastResult:
        if dataset.design is not self.design:
            raise ValueError(
                f"{self.name} was handed a {dataset.design} dataset. The "
                "contrast estimators are not interchangeable: FDA fits the "
                "partial replicate with PROC GLM and the fully replicated "
                "design with PROC MIXED."
            )

        diagnostics: list[Diagnostic] = []
        grouped = treatment_contrasts(dataset)

        # A subject with no test measurement contributes nothing here. In the
        # variance estimator that was ADVISORY, because sWR needs only the
        # reference replicates. It is an EXCLUSION now, and recording it under
        # the same code at a different severity is deliberate: the condition is
        # identical, the consequence is not.
        with_contrast = {
            r.subject_id for r in dataset.records if r.has_test and r.log_reference
        }
        for record in dataset.records:
            if record.subject_id not in with_contrast:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.MISSING_TEST_OBSERVATION,
                        Severity.EXCLUSION,
                        record.subject_id,
                        "no test measurement, so no Iij exists; excluded from "
                        "the treatment contrast while still contributing to "
                        "sWR if both reference replicates are present",
                        # `model` disambiguates this from the dataset-level
                        # diagnostic carrying the same code at ADVISORY. The
                        # condition is identical and the consequence is not,
                        # which is exactly what a code is allowed to do - but a
                        # reader should not have to infer which entry is which.
                        {
                            "sequence": record.sequence.value,
                            "model": "treatment_contrast",
                        },
                    )
                )

        m = self.design.regulatory_sequence_count
        missing = [
            s.value
            for s in sorted(self.design.sequences, key=lambda s: s.value)
            if s not in grouped
        ]
        if missing:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS,
                    Severity.FATAL,
                    None,
                    f"sequence(s) {', '.join(missing)} contributed no Iij. The "
                    f"contrast is the equally weighted mean of {m} sequence "
                    "means, and a mean that does not exist cannot be given a "
                    "weight",
                    {"missing_sequences": missing, "regulatory_m": m},
                )
            )
            return self._not_estimable(dataset, diagnostics, grouped, m, alpha)

        n_by_sequence = {s: len(v) for s, v in grouped.items()}
        n = sum(n_by_sequence.values())
        df = n - m
        if df < 1:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.INSUFFICIENT_CONTRAST_DF,
                    Severity.FATAL,
                    None,
                    f"{n} subject(s) with a contrast across {m} sequences "
                    f"leaves {df} residual degrees of freedom; at least 1 is "
                    "needed to estimate the standard error",
                    {"n_subjects": n, "regulatory_m": m, "degrees_of_freedom": df},
                )
            )
            return self._not_estimable(dataset, diagnostics, grouped, m, alpha)

        # THE EQUAL WEIGHTS. Not a subject mean - see the module docstring.
        weight = 1.0 / m
        sequence_means = {
            s: math.fsum(values) / len(values) for s, values in grouped.items()
        }
        estimate = math.fsum(weight * mean for mean in sequence_means.values())

        deviations: list[float] = []
        for sequence, values in grouped.items():
            mean = sequence_means[sequence]
            deviations.extend((v - mean) ** 2 for v in values)
        mse = math.fsum(deviations) / df

        # Var(SUM w_i Ibar_i) = MSE * SUM w_i^2 / n_i, the sequence means being
        # independent.
        variance = mse * math.fsum(
            (weight**2) / n_by_sequence[s] for s in grouped
        )
        standard_error = math.sqrt(variance)

        contrast_df = self._degrees_of_freedom(variance, mse, df)

        if mse == 0.0:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.ZERO_CONTRAST_VARIANCE,
                    Severity.DATA_QUALITY,
                    None,
                    "the residual variance of Iij is exactly zero, so the "
                    "confidence interval has zero width. That is what the data "
                    "give, and it far more often means duplicated or "
                    "over-rounded values than a study with no residual "
                    "variability. Check the dataset before using this interval",
                    {"n_subjects": n, "degrees_of_freedom": df},
                )
            )

        t_crit = stats.t.ppf(1.0 - alpha / 2.0, contrast_df)
        half_width = t_crit * standard_error

        return TreatmentContrastResult(
            design=dataset.design,
            endpoint=dataset.endpoint,
            estimate=estimate,
            standard_error=standard_error,
            degrees_of_freedom=contrast_df,
            degrees_of_freedom_basis=self.df_basis,
            ci_lower=estimate - half_width,
            ci_upper=estimate + half_width,
            alpha=alpha,
            point_estimate=math.exp(estimate),
            n_subjects=n,
            n_by_sequence=n_by_sequence,
            sequence_weights={s: weight for s in grouped},
            mean_square_error=mse,
            estimable=True,
            diagnostics=tuple(diagnostics),
            estimator=self.name,
        )

    def _degrees_of_freedom(
        self, variance: float, mse: float, residual_df: int
    ) -> float:
        return float(residual_df)

    def _not_estimable(
        self,
        dataset: ReplicateDataset,
        diagnostics: list[Diagnostic],
        grouped: dict,
        m: int,
        alpha: float,
    ) -> TreatmentContrastResult:
        n_by_sequence = {s: len(v) for s, v in grouped.items()}
        return TreatmentContrastResult(
            design=dataset.design,
            endpoint=dataset.endpoint,
            estimate=float("nan"),
            standard_error=float("nan"),
            degrees_of_freedom=0.0,
            degrees_of_freedom_basis=self.df_basis,
            ci_lower=float("nan"),
            ci_upper=float("nan"),
            alpha=alpha,
            point_estimate=float("nan"),
            n_subjects=sum(n_by_sequence.values()),
            n_by_sequence=n_by_sequence,
            sequence_weights={},
            mean_square_error=float("nan"),
            estimable=False,
            diagnostics=tuple(diagnostics),
            estimator=self.name,
        )


class PartialReplicateTreatmentContrastEstimator(_TreatmentContrastEstimator):
    """TRR / RTR / RRT, fitted as FDA's `PROC GLM ... model ilat = seq`.

    `Iij = Tij - (Rij1 + Rij2)/2`, three sequence means, weights 1/3 each, and
    the residual degrees of freedom of the one-way model.
    """

    design = ReplicateDesign.PARTIAL_REPLICATE
    name = "partial-replicate treatment contrast (FDA Appendix G, PROC GLM)"
    df_basis = "residual degrees of freedom of the one-way model on Iij, n - 3"


class FullyReplicateTreatmentContrastEstimator(_TreatmentContrastEstimator):
    """TRTR / RTRT, fitted as FDA's `PROC MIXED ... ddfm=satterth`.

    `Iij` is the mean of the subject's two test observations minus the mean of
    its two reference observations, matching FDA's
    `ilat = 0.5*(lat1t+lat2t-lat1r-lat2r)`. Two sequence means, weights 0.5.

    The degrees of freedom are computed through `satterthwaite_df`, not
    borrowed from the partial-replicate estimator. FDA's model here carries a
    single residual variance component, so the Satterthwaite value equals the
    residual degrees of freedom exactly - a derivation, checked by a test,
    rather than an assumption.
    """

    design = ReplicateDesign.FULLY_REPLICATE
    name = "fully-replicate treatment contrast (FDA Appendix G, PROC MIXED)"
    df_basis = (
        "Satterthwaite on a single residual variance component, which collapses "
        "to the residual degrees of freedom n - 2"
    )

    def _degrees_of_freedom(
        self, variance: float, mse: float, residual_df: int
    ) -> float:
        if mse == 0.0:
            # Satterthwaite is undefined on a zero variance. Fall back to the
            # residual degrees of freedom and say so rather than raising: the
            # zero is already flagged DATA_QUALITY by the caller.
            return float(residual_df)
        coefficient = variance / mse
        return satterthwaite_df([(coefficient, mse, residual_df)])


_ESTIMATORS: dict[ReplicateDesign, _TreatmentContrastEstimator] = {
    ReplicateDesign.PARTIAL_REPLICATE: PartialReplicateTreatmentContrastEstimator(),
    ReplicateDesign.FULLY_REPLICATE: FullyReplicateTreatmentContrastEstimator(),
}


def contrast_estimator_for(design: ReplicateDesign) -> _TreatmentContrastEstimator:
    return _ESTIMATORS[design]


def estimate_treatment_contrast(
    dataset: ReplicateDataset, *, alpha: float = CONTRAST_ALPHA
) -> TreatmentContrastResult:
    """mu_T - mu_R for this dataset, by the estimator its design uses."""
    return contrast_estimator_for(dataset.design).estimate(dataset, alpha=alpha)


def subject_weighted_mean(dataset: ReplicateDataset) -> float:
    """The naive average over all subjects. NOT FDA's estimator.

    Present only so tests can assert the engine did not produce it, and so a
    reader can see the size of the difference on their own data. Nothing in the
    package calls this.
    """
    values = [v for group in treatment_contrasts(dataset).values() for v in group]
    if not values:
        raise ValueError("No subject has a treatment contrast.")
    return math.fsum(values) / len(values)
