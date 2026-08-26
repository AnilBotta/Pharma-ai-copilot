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

ONLY ONE OF THE TWO BRANCHES DECIDES

The scaled branch is complete. The unscaled branch is not, and it refuses.

Appendix G step 1a routes an endpoint with `sWR < 0.294` to the two one-sided
tests procedure without naming a model. Appendix C names one: a mixed model on
the subject-period observations, with a period term, an unstructured
subject-by-formulation covariance and treatment-specific residual variances,
which this package cannot fit and has nothing to check a from-scratch fit
against. See `replicate_abe.py`.

So an endpoint below the threshold comes back with its sWR, its selected
method, its treatment contrast - and `decided = False`. It does not come back
with a bioequivalence verdict computed from the reference-scaled construction's
intermediate, which is what an earlier version of this module did.

WHAT THIS MODULE DOES NOT DO

FDA narrow therapeutic index drugs (Appendix F) and EMA's ABEL are different
procedures and are not here. The constants for NTI exist in `spec.py` and are
consumed by nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy import stats

from be_stats.abe import AbeResult
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    VIA_PRIMARY_DOCUMENT,
    RegulatoryValue,
    ValidationStatus,
)
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
    Jurisdiction,
    Method,
    fda_hvd_method_for,
    fda_hvd_theta,
    resolve_be_spec,
)
from be_stats.treatment_contrast import (
    TreatmentContrastResult,
    estimate_treatment_contrast,
)

#: Appendix G step 2 asks for a 95% upper confidence bound. Stated once.
UPPER_BOUND_CONFIDENCE = 0.95


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

    x = contrast.estimate**2 - contrast.standard_error**2
    bound_x = max(abs(contrast.ci_lower), abs(contrast.ci_upper)) ** 2

    theta = fda_hvd_theta()
    sigma_w0 = FDA_HVD_CONSTANTS["sigma_w0"].value
    s2wr = reference_variance.variance_wr
    df_d = reference_variance.degrees_of_freedom

    y = -theta * s2wr
    # stats.chi2.ppf is the inverse CDF, which is what SAS's cinv is.
    bound_y = y * df_d / stats.chi2.ppf(UPPER_BOUND_CONFIDENCE, df_d)

    critbound = (x + y) + math.sqrt((bound_x - x) ** 2 + (bound_y - y) ** 2)

    return ScaledCriterion(
        x=x,
        bound_x=bound_x,
        y=y,
        bound_y=bound_y,
        theta=theta,
        sigma_w0=sigma_w0,
        reference_variance=s2wr,
        reference_variance_df=df_d,
        upper_confidence_bound=critbound,
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

    standard_abe_result: AbeResult | None = None
    rsabe_result: RsabeResult | None = None

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
        if self.standard_abe_result is not None:
            return self.standard_abe_result.within_acceptance_interval
        return None

    def provenance(self) -> list[str]:
        lines = [
            f"switching rule: {self.switching_threshold.explain()}",
            f"observed sWR = {self.swr}, threshold "
            f"{self.switching_threshold.value} -> {self.selected_method}",
        ]
        lines += self.reference_variance.provenance()
        if self.treatment_contrast is not None:
            lines += self.treatment_contrast.provenance()
        return lines

    def summary(self) -> str:
        head = (
            f"{self.endpoint} ({self.design})\n"
            f"  sWR = {self.swr if self.swr is None else f'{self.swr:.6f}'}, "
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


def assess_endpoint(
    dataset: ReplicateDataset,
    *,
    spec: BeSpec | None = None,
) -> FdaHvdResult:
    """The whole Appendix G flow for one PK endpoint.

    Estimates sWR, applies FDA's switching rule to it, and runs whichever
    procedure that selects. Every component is returned; nothing is collapsed
    to a verdict on the way.
    """
    threshold = FDA_HVD_CONSTANTS["swr_switching_threshold"]
    variance = estimate_reference_variance(dataset)
    diagnostics = list(variance.diagnostics)

    if not variance.estimable or variance.swr is None:
        return FdaHvdResult(
            endpoint=dataset.endpoint,
            design=dataset.design,
            swr=None,
            cv_wr=None,
            switching_threshold=threshold,
            selected_method=None,
            reference_variance=variance,
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
        # The contrast IS still computed and returned - it is a real quantity a
        # reviewer may want - but it does not become a decision.
        diagnostics.append(replicate_abe_unavailable(dataset))
        return FdaHvdResult(
            **common, decided=False, diagnostics=tuple(diagnostics)
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
) -> dict[str, FdaHvdResult]:
    """Every endpoint decided on its own sWR.

    A thin loop, and the reason it is a loop rather than a study-level
    classification: FDA determines the method "for the individual PK
    parameter". AUC and Cmax from the same subjects may take different
    procedures, and the endpoint with the lower reference variability must not
    inherit a scaled acceptance range from the one with more.
    """
    return {
        endpoint: assess_endpoint(dataset, spec=spec)
        for endpoint, dataset in datasets.items()
    }
