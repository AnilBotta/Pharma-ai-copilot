"""FDA narrow therapeutic index drugs: three criteria, all required.

THE ONE THING TO GET RIGHT ABOUT THIS PROCEDURE

FDA NTI is **not** a narrowed acceptance interval. There is no 90.00-111.11%
anywhere in it - that is EMA's approach to the same drug class, and letting it
leak in here would replace three criteria with one.

FDA requires a fully replicate crossover study and, per Appendix F step 5, all
three of:

    a. the 95% upper confidence bound for (mu_T - mu_R)^2 - theta*sigma_WR^2
       must be <= 0                          [reference-scaled, sigma_W0 = 0.10]
    b. the regular UNSCALED limits of 80.00-125.00% must be passed
    c. the upper limit of the 90% equal-tails confidence interval for
       sigma_WT / sigma_WR must be <= 2.500

Criterion (b) is the one most likely to be misread as narrowed, and criterion
(c) has no counterpart in any other procedure here: it asks whether the test
product is as reproducible as the reference, which for a drug where small
concentration differences matter is a question about the product rather than
about the mean.

WHAT IS AND IS NOT DECIDED

Criteria (a) and (c) are computed. Criterion (b) is NOT: the unscaled analysis
of a fully replicate study is FDA's Appendix C mixed model, which this package
cannot fit and has no way to verify - see `replicate_abe.py`. So the overall
NTI decision is `NOT DECIDED`, and it stays that way however comfortably the
other two pass.

Two of three criteria do not make a verdict. An endpoint that met (a) and (c)
and was never tested against (b) is not bioequivalent under this procedure; it
is untested under it.

THE DESIGN GATE COMES FIRST

III.B: "For NTI drugs, a fully replicate crossover design should be used." A
2x2 crossover, a partial replicate or a parallel study does not reach any of
the arithmetic below - it is refused, by design rather than by running out of
data. A partial replicate in particular gives each subject ONE test
measurement, so criterion (c) has no numerator at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.howe import HoweUpperBound, howe_upper_bound
from be_stats.provenance import (
    FDA_STATISTICAL_APPROACHES_APPENDIX_F,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5,
    FDA_STATISTICAL_APPROACHES_III_B,
    VIA_PRIMARY_DOCUMENT,
)
from be_stats.reference_variance import (
    ReferenceVarianceResult,
    estimate_reference_variance,
    sum_of_squared_deviations,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    test_differences,
)
from be_stats.replicate_abe import replicate_abe_unavailable
from be_stats.spec import FDA_NTI_CONSTANTS, fda_nti_theta
from be_stats.study import DataError
from be_stats.treatment_contrast import (
    TreatmentContrastResult,
    estimate_treatment_contrast,
)

#: Appendix F step 4: "here, alpha = 0.1", for the variability comparison.
VARIABILITY_ALPHA = 0.10


class NtiDesignError(DataError):
    """The design is not one FDA accepts for a narrow therapeutic index drug."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = DiagnosticCode.NTI_REQUIRES_FULLY_REPLICATE_DESIGN


def require_fully_replicate(dataset: ReplicateDataset) -> None:
    """The gate, before any arithmetic. III.B, and it is not negotiable here.

    Falling back to ordinary average BE for an NTI drug on a 2x2 study would
    be the single most consequential substitution this package could make: the
    procedure FDA specifies has three criteria and this one would have one.
    """
    if dataset.design is not ReplicateDesign.FULLY_REPLICATE:
        raise NtiDesignError(
            f"FDA requires a fully replicate crossover design (TRTR / RTRT) "
            f"for a narrow therapeutic index drug; this study is "
            f"{dataset.design}. Section III.B: 'For NTI drugs, a fully "
            "replicate crossover design should be used.' There is no fallback "
            "to ordinary average BE - the NTI procedure has three criteria, "
            "one of which compares within-subject test and reference "
            "variability and therefore needs two test measurements per "
            "subject, which this design does not provide."
        )


# ------------------------------------------------- within-test variability ---


@dataclass(frozen=True, slots=True)
class WithinTestVarianceResult:
    """sWT, by the same estimator sWR uses, applied to the test replicates.

    A NOTE ON WHERE THIS FORMULA COMES FROM

    Appendix F step 1 gives the closed form for sWR only. It names `sWT` in
    step 4 - "the estimate of sigma_WT with v1 as the degree of freedom" - and
    does not restate how to compute it.

    What is implemented is the same estimator applied to the subject's two TEST
    observations: `DTij = Tij1 - Tij2`, deviations about the sequence means,
    divided by `2(n - m)`. That is the symmetric reading, and it is what
    Appendix C's `REPEATED / GRP=TRT SUB=SUBJ` residual structure produces -
    treatment-specific within-subject variances from the same model.

    It is an interpretation nonetheless, and it is recorded as one rather than
    presented as transcription.
    """

    variance_wt: float | None
    swt: float | None
    degrees_of_freedom: int
    n_subjects: int
    regulatory_m: int
    estimable: bool
    diagnostics: tuple[Diagnostic, ...] = ()

    def provenance(self) -> list[str]:
        return [
            "sWT^2 = SUM_i SUM_j (DTij - DTbar_i.)^2 / (2(n - m)), with "
            "DTij = Tij1 - Tij2 on the log scale — the Appendix F step 1 "
            "estimator applied to the test replicates. Appendix F states the "
            "closed form for sWR only and names sWT without restating it; "
            "this is the symmetric reading, consistent with Appendix C's "
            "treatment-specific residual variances "
            f"— {FDA_STATISTICAL_APPROACHES_APPENDIX_F} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}; sWT by symmetry]",
        ]


def estimate_test_variance(dataset: ReplicateDataset) -> WithinTestVarianceResult:
    """sWT for a fully replicate dataset."""
    require_fully_replicate(dataset)

    diagnostics: list[Diagnostic] = []
    grouped = test_differences(dataset)
    m = dataset.design.regulatory_sequence_count
    n = sum(len(v) for v in grouped.values())

    missing = [
        s.value
        for s in sorted(dataset.design.sequences, key=lambda s: s.value)
        if s not in grouped
    ]
    if missing:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS,
                Severity.FATAL,
                None,
                f"sequence(s) {', '.join(missing)} contributed no test "
                f"difference, so this is not the {m}-sequence design Appendix "
                "F specifies",
                {"missing_sequences": missing, "regulatory_m": m},
            )
        )
        return WithinTestVarianceResult(None, None, 0, n, m, False, tuple(diagnostics))

    if n == 0:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.MISSING_TEST_REPLICATE,
                Severity.FATAL,
                None,
                "no subject contributed two test measurements, so sWT has no "
                "estimate and the variability comparison has no numerator",
                {},
            )
        )
        return WithinTestVarianceResult(None, None, 0, n, m, False, tuple(diagnostics))

    df = n - m
    if df < 1:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.INSUFFICIENT_TEST_DF,
                Severity.FATAL,
                None,
                f"{n} subject(s) with a test difference across {m} sequences "
                f"leaves {df} degrees of freedom; at least 1 is needed",
                {"n_subjects": n, "regulatory_m": m, "degrees_of_freedom": df},
            )
        )
        return WithinTestVarianceResult(None, None, max(df, 0), n, m, False, tuple(diagnostics))

    variance = sum_of_squared_deviations(grouped) / (2.0 * df)
    if variance == 0.0:
        # Same treatment as the reference variance: an estimate, flagged hard.
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.ZERO_REFERENCE_VARIANCE,
                Severity.DATA_QUALITY,
                None,
                "the estimated within-TEST variance is exactly zero: every "
                "subject's two test measurements were identical. Reported "
                "because that is what the data give, and far more often "
                "duplicated or over-rounded values than a perfectly "
                "reproducible product",
                {"n_subjects": n, "degrees_of_freedom": df, "quantity": "sWT"},
            )
        )

    return WithinTestVarianceResult(
        variance_wt=variance,
        swt=math.sqrt(variance),
        degrees_of_freedom=df,
        n_subjects=n,
        regulatory_m=m,
        estimable=True,
        diagnostics=tuple(diagnostics),
    )


# ----------------------------------------------------- the three criteria ---


@dataclass(frozen=True, slots=True)
class NtiScaledMeanCriterion:
    """Appendix F steps 2 and 5a."""

    bound: HoweUpperBound
    sigma_w0: float
    delta: float
    estimate: float
    standard_error: float
    ci_lower: float
    ci_upper: float

    @property
    def x(self) -> float:
        return self.bound.x

    @property
    def bound_x(self) -> float:
        return self.bound.bound_x

    @property
    def y(self) -> float:
        return self.bound.y

    @property
    def bound_y(self) -> float:
        return self.bound.bound_y

    @property
    def theta(self) -> float:
        return self.bound.theta

    @property
    def upper_confidence_bound(self) -> float:
        return self.bound.upper_confidence_bound

    @property
    def passes(self) -> bool:
        """"must be <= 0". The boundary passes."""
        return self.upper_confidence_bound <= 0.0

    def explain(self) -> list[str]:
        lines = self.bound.explain(
            theta_basis=f"[ln(Delta)/sigma_W0]^2, Delta=1/0.9, "
            f"sigma_W0={self.sigma_w0}"
        )
        lines.append(
            f"criterion a: {self.upper_confidence_bound:.8f} <= 0 -> "
            f"{'PASS' if self.passes else 'FAIL'}"
        )
        return lines


@dataclass(frozen=True, slots=True)
class NtiUnscaledAbeCriterion:
    """Appendix F step 5b: the ordinary 80.00-125.00% limits must ALSO pass.

    NOT COMPUTED, and the interval is not the narrowed one.

    Two mistakes are possible here and this class exists to prevent both. The
    first is applying EMA's 90.00-111.11% narrowed interval, which is a
    different regulator's approach to the same drug class; the limits carried
    here are FDA's verified 80.00 and 125.00. The second is testing them
    against a convenient interval rather than the one FDA specifies.

    The unscaled average BE analysis of a fully replicate study is Appendix C's
    mixed model. Appendix F's own SAS produces a 90% interval from its `ilat`
    model - the one `bound_x` is built from - and it would be easy to reach for
    that. It is a different model: no period term, one residual variance, no
    subject-by-formulation covariance. So this criterion is not computed, and
    the overall decision is withheld.
    """

    lower_limit_percent: float
    upper_limit_percent: float
    computed: bool = False
    reason: str = ""
    #: Populated only when `computed` is True, which is never in this release.
    ci_lower_percent: float | None = None
    ci_upper_percent: float | None = None

    @property
    def passes(self) -> bool | None:
        """`None` while not computed. Never `False`, which would read as failure.

        The containment test is written out rather than left as a `TODO`, so
        that implementing Appendix C is a matter of supplying the interval and
        not of also deciding what to do with it - and so that the limits being
        used are visible now.
        """
        if not self.computed:
            return None
        if self.ci_lower_percent is None or self.ci_upper_percent is None:
            return None
        return (
            self.ci_lower_percent >= self.lower_limit_percent
            and self.ci_upper_percent <= self.upper_limit_percent
        )

    def explain(self) -> list[str]:
        return [
            f"criterion b: unscaled {self.lower_limit_percent:.2f}-"
            f"{self.upper_limit_percent:.2f}% — NOT COMPUTED",
            f"    {self.reason}",
        ]


@dataclass(frozen=True, slots=True)
class NtiVariabilityRatioCriterion:
    """Appendix F steps 4 and 5c: is the test as reproducible as the reference?

    The interval is F-based and equal-tailed, exactly as the guidance gives it:

        [ (sWT/sWR) / sqrt(F_{alpha/2}(v1, v2)),
          (sWT/sWR) / sqrt(F_{1-alpha/2}(v1, v2)) ]

    where `F_p(v1, v2)` has probability `p` to its RIGHT - an upper-tail
    quantile, which is `scipy.stats.f.isf(p, v1, v2)`, not `f.ppf`. Since
    `isf(0.05) > isf(0.95)`, dividing by the square roots puts the smaller
    limit first, which is the arithmetic check that the tails are the right way
    round.

    `v1` belongs to sWT and `v2` to sWR. They are separate arguments because
    the two variances are estimated from different subject sets whenever a
    subject is missing one of its four measurements.

    No normal approximation, no Wald interval on log variance, no bootstrap:
    the guidance names the distribution.
    """

    swt: float | None
    swr: float | None
    ratio: float | None
    df_test: int
    df_reference: int
    ci_lower: float | None
    ci_upper: float | None
    limit: float
    alpha: float = VARIABILITY_ALPHA
    estimable: bool = True
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def passes(self) -> bool | None:
        """`None` when the ratio does not exist. Never `False` by default."""
        if not self.estimable or self.ci_upper is None:
            return None
        return self.ci_upper <= self.limit

    def explain(self) -> list[str]:
        if not self.estimable:
            return [
                "criterion c: sigma_WT / sigma_WR — NOT ESTIMABLE",
                *[f"    {d}" for d in self.diagnostics],
            ]
        return [
            f"sWT = {self.swt:.6f} (df {self.df_test}), "
            f"sWR = {self.swr:.6f} (df {self.df_reference})",
            f"ratio = {self.ratio:.6f}, "
            f"{1 - self.alpha:.0%} equal-tails CI "
            f"[{self.ci_lower:.6f}, {self.ci_upper:.6f}]",
            f"criterion c: {self.ci_upper:.6f} <= {self.limit:.4f} -> "
            f"{'PASS' if self.passes else 'FAIL'}",
        ]


def variability_ratio_criterion(
    *,
    test_variance: WithinTestVarianceResult,
    reference_variance: ReferenceVarianceResult,
    alpha: float = VARIABILITY_ALPHA,
) -> NtiVariabilityRatioCriterion:
    """Appendix F step 4, with the zero-reference case handled explicitly."""
    limit = FDA_NTI_CONSTANTS["variance_ratio_upper_limit"].value
    diagnostics: list[Diagnostic] = []

    def unavailable() -> NtiVariabilityRatioCriterion:
        return NtiVariabilityRatioCriterion(
            swt=test_variance.swt,
            swr=reference_variance.swr,
            ratio=None,
            df_test=test_variance.degrees_of_freedom,
            df_reference=reference_variance.degrees_of_freedom,
            ci_lower=None,
            ci_upper=None,
            limit=limit,
            alpha=alpha,
            estimable=False,
            diagnostics=tuple(diagnostics),
        )

    if not test_variance.estimable or test_variance.swt is None:
        diagnostics.extend(test_variance.diagnostics)
        return unavailable()
    if not reference_variance.estimable or reference_variance.swr is None:
        return unavailable()

    if reference_variance.swr == 0.0:
        # sWR = 0 is a legitimate estimate - the previous release established
        # that, and refusing to report it would be inventing a rule. But this
        # criterion divides by it, and the quotient does not exist. Infinity is
        # not a regulatory result, and "the ratio is enormous, so it fails" is
        # a decision the guidance does not authorise.
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.REFERENCE_SD_ZERO_VARIANCE_RATIO_UNDEFINED,
                Severity.FATAL,
                None,
                "sWR is exactly zero, so sigma_WT / sigma_WR has no value. The "
                "variance estimate itself is legitimate and is reported; the "
                "ratio is not defined and is not reported as infinite, as very "
                "large, or as a failure. Appendix F states no handling rule for "
                "this case, so the criterion is unavailable and the endpoint is "
                "not decided",
                {"swt": test_variance.swt, "swr": 0.0},
            )
        )
        return unavailable()

    ratio = test_variance.swt / reference_variance.swr
    v1 = test_variance.degrees_of_freedom
    v2 = reference_variance.degrees_of_freedom

    # `isf(p, v1, v2)` is the value with probability p to its RIGHT, which is
    # how the guidance defines F_p. `ppf` would be the other tail.
    f_lower_tail = stats.f.isf(alpha / 2.0, v1, v2)
    f_upper_tail = stats.f.isf(1.0 - alpha / 2.0, v1, v2)

    return NtiVariabilityRatioCriterion(
        swt=test_variance.swt,
        swr=reference_variance.swr,
        ratio=ratio,
        df_test=v1,
        df_reference=v2,
        ci_lower=ratio / math.sqrt(f_lower_tail),
        ci_upper=ratio / math.sqrt(f_upper_tail),
        limit=limit,
        alpha=alpha,
        estimable=True,
        diagnostics=tuple(diagnostics),
    )


def scaled_mean_criterion(
    *,
    contrast: TreatmentContrastResult,
    reference_variance: ReferenceVarianceResult,
) -> NtiScaledMeanCriterion:
    """Appendix F step 2, through the shared Howe helper.

    The helper is shared because Appendix F's and Appendix G's SAS were
    compared line by line and differ only in `theta` - see `howe.py`. This
    wrapper supplies FDA's NTI constants and cites Appendix F; it does not pass
    a mode flag to a generic routine.
    """
    if not contrast.estimable:
        raise DataError("The treatment contrast is not estimable.")
    if not reference_variance.estimable or reference_variance.variance_wr is None:
        raise DataError("sWR is not estimable.")

    bound = howe_upper_bound(
        estimate=contrast.estimate,
        standard_error=contrast.standard_error,
        ci_lower=contrast.ci_lower,
        ci_upper=contrast.ci_upper,
        reference_variance=reference_variance.variance_wr,
        reference_variance_df=reference_variance.degrees_of_freedom,
        theta=fda_nti_theta(),
    )
    return NtiScaledMeanCriterion(
        bound=bound,
        sigma_w0=FDA_NTI_CONSTANTS["sigma_w0"].value,
        delta=FDA_NTI_CONSTANTS["delta"].value,
        estimate=contrast.estimate,
        standard_error=contrast.standard_error,
        ci_lower=contrast.ci_lower,
        ci_upper=contrast.ci_upper,
    )


# ------------------------------------------------------- endpoint result ---


@dataclass(frozen=True, slots=True)
class FdaNtiResult:
    """One PK endpoint under FDA's NTI procedure. Three criteria, all required."""

    endpoint: str
    design: ReplicateDesign

    scaled_mean_criterion: NtiScaledMeanCriterion | None
    unscaled_abe_criterion: NtiUnscaledAbeCriterion
    variability_ratio_criterion: NtiVariabilityRatioCriterion | None

    reference_variance: ReferenceVarianceResult
    test_variance: WithinTestVarianceResult
    treatment_contrast: TreatmentContrastResult | None

    decided: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()

    #: Reported separately because the three quantities come from three subject
    #: sets that can legitimately differ.
    n_for_swr: int = 0
    n_for_swt: int = 0
    n_for_treatment_contrast: int = 0
    reference_variance_df: int = 0
    test_variance_df: int = 0
    treatment_contrast_df: float = 0.0

    @property
    def passes(self) -> bool | None:
        """All three, or nothing.

        `None` whenever any required criterion was not computed. Missing is not
        failure and it is not a pass: an endpoint never tested against the
        unscaled limits is untested, not bioequivalent and not inequivalent.
        """
        if not self.decided:
            return None
        criteria = (
            self.scaled_mean_criterion.passes
            if self.scaled_mean_criterion
            else None,
            self.unscaled_abe_criterion.passes,
            self.variability_ratio_criterion.passes
            if self.variability_ratio_criterion
            else None,
        )
        if any(c is None for c in criteria):
            return None
        return all(criteria)

    def provenance(self) -> list[str]:
        """Every basis this NTI decision rests on, cited to Appendix F.

        WHY sWR IS NOT CITED TO APPENDIX G HERE

        The sWR estimator is shared with the highly-variable procedure, and its
        own `provenance()` cites Appendix G - correctly, for that procedure.
        But an NTI decision does not rest on Appendix G. Appendix F step 1
        states the same closed form, in the same words, restricted to `m = 2`,
        and that is the authority for this result.

        Reusing an implementation is not the same as inheriting its citation.
        Delegating here would have put Appendix G in the provenance of a
        narrow-therapeutic-index decision, which a test now prevents.
        """
        lines = [
            f"design gate: fully replicate required — "
            f"{FDA_STATISTICAL_APPROACHES_III_B} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]",
            f"criteria a, b, c — {FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]",
            "sWR^2 = SUM_i SUM_j (Dij - Dbar_i.)^2 / (2(n - m)), m = 2, with "
            "Dij = Rij1 - Rij2 on the log scale "
            f"— {FDA_STATISTICAL_APPROACHES_APPENDIX_F} step 1 "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]. The estimator is shared "
            "with the highly variable procedure, whose own citation is "
            "Appendix G; the authority for THIS result is Appendix F, which "
            "states the same form.",
            "CVwR = sqrt(exp(sWR^2) - 1) — be_stats.conversions.log_sd_to_cv, "
            "the package's single canonical conversion",
        ]
        lines += self.test_variance.provenance()
        if self.treatment_contrast is not None:
            lines += [
                line.replace("Appendix G (highly variable drugs)", "Appendix F")
                for line in self.treatment_contrast.provenance()
            ]
        lines.append(
            "the 95% upper bound uses Howe's Approximation I, shared with the "
            "highly variable procedure because the two appendices' SAS differ "
            f"only in theta — {FDA_STATISTICAL_APPROACHES_APPENDIX_F} step 2 "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]"
        )
        return lines

    def summary(self) -> str:
        head = (
            f"{self.endpoint} ({self.design}) — FDA narrow therapeutic index\n"
            f"  n for sWR = {self.n_for_swr} (df {self.reference_variance_df}), "
            f"n for sWT = {self.n_for_swt} (df {self.test_variance_df}), "
            f"n for contrast = {self.n_for_treatment_contrast} "
            f"(df {self.treatment_contrast_df})\n"
        )
        lines: list[str] = []
        if self.scaled_mean_criterion is not None:
            lines += self.scaled_mean_criterion.explain()
        else:
            lines.append("criterion a: NOT COMPUTED")
        lines += self.unscaled_abe_criterion.explain()
        if self.variability_ratio_criterion is not None:
            lines += self.variability_ratio_criterion.explain()
        else:
            lines.append("criterion c: NOT COMPUTED")

        verdict = {True: "PASS", False: "FAIL", None: "NOT DECIDED"}[self.passes]
        lines.append(f"all three criteria are required -> {verdict}")

        body = "\n".join(f"  {line}" for line in lines)
        if self.diagnostics:
            body += "\n  diagnostics:\n" + "\n".join(
                f"    {d}" for d in self.diagnostics
            )
        return head + body


def assess_nti_endpoint(dataset: ReplicateDataset) -> FdaNtiResult:
    """FDA's NTI procedure for one PK endpoint.

    Raises `NtiDesignError` before any arithmetic if the design is not fully
    replicate. Otherwise computes what can be computed and withholds the
    verdict, because criterion b needs Appendix C.
    """
    require_fully_replicate(dataset)

    variance = estimate_reference_variance(dataset)
    test_variance = estimate_test_variance(dataset)
    diagnostics = list(variance.diagnostics)
    diagnostics += [
        d for d in test_variance.diagnostics if d not in variance.diagnostics
    ]

    contrast = estimate_treatment_contrast(dataset)
    diagnostics += [d for d in contrast.diagnostics if d not in diagnostics]

    unscaled = NtiUnscaledAbeCriterion(
        lower_limit_percent=FDA_NTI_CONSTANTS["unscaled_lower_percent"].value,
        upper_limit_percent=FDA_NTI_CONSTANTS["unscaled_upper_percent"].value,
        computed=False,
        reason=(
            "the unscaled average BE analysis of a fully replicate study is "
            "FDA Appendix C's mixed model, which is not implemented — see "
            "replicate_abe.py. Appendix F's own ilat interval is a different "
            "model and is not substituted"
        ),
    )
    diagnostics.append(replicate_abe_unavailable(dataset))

    scaled = None
    if contrast.estimable and variance.estimable:
        scaled = scaled_mean_criterion(
            contrast=contrast, reference_variance=variance
        )

    ratio = variability_ratio_criterion(
        test_variance=test_variance, reference_variance=variance
    )
    diagnostics += [d for d in ratio.diagnostics if d not in diagnostics]

    return FdaNtiResult(
        endpoint=dataset.endpoint,
        design=dataset.design,
        scaled_mean_criterion=scaled,
        unscaled_abe_criterion=unscaled,
        variability_ratio_criterion=ratio,
        reference_variance=variance,
        test_variance=test_variance,
        treatment_contrast=contrast if contrast.estimable else None,
        # Criterion b is structurally unavailable, so the endpoint is never
        # decided in this release. Stated as a constant rather than computed,
        # so that implementing Appendix C is a deliberate change here.
        decided=False,
        diagnostics=tuple(diagnostics),
        n_for_swr=variance.n_subjects,
        n_for_swt=test_variance.n_subjects,
        n_for_treatment_contrast=contrast.n_subjects,
        reference_variance_df=variance.degrees_of_freedom,
        test_variance_df=test_variance.degrees_of_freedom,
        treatment_contrast_df=contrast.degrees_of_freedom,
    )


def assess_nti_study(
    datasets: dict[str, ReplicateDataset],
) -> dict[str, FdaNtiResult]:
    """Every endpoint assessed on its own data.

    A loop, and deliberately nothing more: AUC and Cmax are evaluated
    separately, and one endpoint's outcome must not enter the other's
    arithmetic. Combining them into a study-level statement is a later,
    separate decision.
    """
    return {
        endpoint: assess_nti_endpoint(dataset)
        for endpoint, dataset in datasets.items()
    }
