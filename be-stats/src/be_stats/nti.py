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

All three criteria are now computed, and the endpoint gets a verdict. Criterion
(b) - the unscaled analysis of a fully replicate study - is FDA's Appendix C
mixed model, which arrived in `appendix_c.py`. NTI already requires a fully
replicate design, which is exactly the design Appendix C is implemented and
checked for, so the two scopes coincide and nothing here relies on the partial
replicate case that Appendix C refuses.

`decided` is a CONDITION over the three criteria, not a constant. It was
hard-coded `False` while criterion (b) was missing; it is now false whenever
ANY criterion could not be computed - criterion (c) has no numerator when a
subject contributes a single test measurement, and criterion (b) withholds if
the design or the data will not support a fit.

Two of three criteria do not make a verdict. An endpoint that met (a) and (c)
and was never tested against (b) is not bioequivalent under this procedure; it
is untested under it - and that remains true now that the usual path computes
all three.

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
    Citation,
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
from be_stats.spec import (
    FDA_NTI_CONSTANTS,
    BeSpec,
    Jurisdiction,
    Method,
    NotApplicable,
    NtiApplicability,
    NtiStatus,
    fda_nti_applicability,
    fda_nti_theta,
    reconcile_nti_status,
)
from be_stats.study import DataError
from be_stats.treatment_contrast import (
    TreatmentContrastResult,
    estimate_treatment_contrast,
)

#: Appendix F step 4: "here, alpha = 0.1", for the variability comparison.
#:
#: READ FROM THE VERIFIED CONSTANT, NOT DECLARED HERE. This was a bare module
#: literal, and the only alpha in the NTI procedure without a citation. The
#: name is kept because callers and tests import it; the value lives in
#: `spec.FDA_NTI_CONSTANTS` with the rest of Appendix F's numbers.
VARIABILITY_ALPHA = FDA_NTI_CONSTANTS["variability_ci_alpha"].value


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

    The interval is NOT the narrowed one.

    Two mistakes are possible here and this class exists to prevent both. The
    first is applying EMA's 90.00-111.11% narrowed interval, which is a
    different regulator's approach to the same drug class; the limits carried
    here are FDA's verified 80.00 and 125.00. The second is testing them
    against a convenient interval rather than the one FDA specifies.

    THE INTERVAL COMES FROM APPENDIX C, AND FROM NOTHING NEARER TO HAND.

    The unscaled average BE analysis of a fully replicate study is Appendix C's
    mixed model. Appendix F's own SAS produces a 90% interval from its `ilat`
    model - the one `bound_x` is built from - and it would be easy to reach for
    that, since it is already computed a few lines away. It is a DIFFERENT
    model: no period term, one residual variance, no subject-by-formulation
    covariance. PR #61 measured what that substitution costs on a neighbouring
    model, where a correct Satterthwaite df on the wrong covariance structure
    came out 1.8 times too small.

    So this criterion consumes `appendix_c.analyse_replicate_abe_full` and
    nothing else, and `computed` stays False whenever that refuses.
    """

    lower_limit_percent: float
    upper_limit_percent: float
    computed: bool = False
    reason: str = ""
    #: Populated only when `computed` is True.
    ci_lower_percent: float | None = None
    ci_upper_percent: float | None = None
    #: The unscaled geometric mean ratio, from the same Appendix C fit. Shown
    #: beside the interval so a reviewer can see where the point estimate
    #: sits; criterion (b) itself tests the interval, not the ratio.
    geometric_mean_ratio_percent: float | None = None

    @property
    def passes(self) -> bool | None:
        """`None` when not computed. Never `False`, which would read as failure.

        Inclusive at both ends, matching `appendix_c.within_acceptance_range`:
        FDA requires the interval to be WITHIN 80 to 125 percent, and an
        interval touching a limit is within it.
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
        window = (
            f"unscaled {self.lower_limit_percent:.2f}-"
            f"{self.upper_limit_percent:.2f}%"
        )
        if not self.computed:
            return [f"criterion b: {window} — NOT COMPUTED", f"    {self.reason}"]
        return [
            f"criterion b: {window}: "
            f"{self.ci_lower_percent:.2f}-{self.ci_upper_percent:.2f}% -> "
            f"{'PASS' if self.passes else 'FAIL'}",
            f"    90% CI = [{self.ci_lower_percent:.2f}%, "
            f"{self.ci_upper_percent:.2f}%]; required inside {window}"
            + (
                ""
                if self.geometric_mean_ratio_percent is None
                else f"; GMR = {self.geometric_mean_ratio_percent:.2f}%"
            ),
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


class NtiNotDecidable(Exception):
    """A result was built that asserts something Appendix F did not decide.

    Raised from `FdaNtiResult.__post_init__`. The contradictory states are made
    UNCONSTRUCTIBLE rather than merely untested - the principle PR #82 applied
    to the highly variable result, applied here to the result it did not reach.
    """


def _applicability_explanation(applicability: NtiApplicability) -> str:
    """One sentence per applicability outcome, shared by summary and provenance.

    One function rather than two strings, so the summary and the provenance
    cannot drift into disagreeing about whether a decision was issued.
    """
    if applicability is NtiApplicability.NOT_APPLICABLE_NOT_NTI:
        return (
            "FDA NTI procedure not applicable: the product is identified as "
            "not narrow therapeutic index. No BE decision was issued under "
            "Appendix F."
        )
    if applicability is NtiApplicability.UNDETERMINED_NTI_NOT_STATED:
        return (
            "FDA NTI applicability cannot be determined because NTI status was "
            "not specified. Variability estimates are descriptive only; no "
            "regulatory BE decision was issued."
        )
    return "Product class: NTI — FDA Appendix F applicable."


#: Appendix F step 5's own lettering. Used for reporting only.
CRITERION_LABELS: tuple[str, str, str] = ("a", "b", "c")


@dataclass(frozen=True, slots=True)
class FdaNtiResult:
    """One PK endpoint under FDA's NTI procedure. Three criteria, all required.

    FOUR THINGS, IN THE ORDER A REVIEWER NEEDS THEM

        applicability  may Appendix F decide this PRODUCT at all?
        design         is the study the fully replicate crossover III.B requires?
        criteria       a, b and c, each reported on its own
        decision       PASS only if all three passed; NOT DECIDED if any is
                       missing, which is neither a pass nor a failure

    WHAT CANNOT BE BUILT

    `__post_init__` refuses two families of contradictory object:

      - a refused applicability carrying a decision, a criterion, a test
        variance or a treatment contrast. A product Appendix F does not apply
        to must not carry the analysis it would have received.
      - `decided=True` while any of the three criteria is absent or could not
        be evaluated. Two of three criteria are not a verdict.

    `selected_method` is DERIVED from the applicability rather than stored, so
    "not applicable, yet the NTI method was selected" has no field to live in.
    """

    endpoint: str
    design: ReplicateDesign
    reference_variance: ReferenceVarianceResult

    applicability: NtiApplicability = NtiApplicability.APPLICABLE

    scaled_mean_criterion: NtiScaledMeanCriterion | None = None
    unscaled_abe_criterion: NtiUnscaledAbeCriterion | None = None
    variability_ratio_criterion: NtiVariabilityRatioCriterion | None = None

    test_variance: WithinTestVarianceResult | None = None
    treatment_contrast: TreatmentContrastResult | None = None

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

    def __post_init__(self) -> None:
        if not self.applicability.permits_verdict:
            if self.decided:
                raise NtiNotDecidable(
                    f"a decided result was constructed with applicability "
                    f"{self.applicability}. Appendix F does not apply to this "
                    "product, so there is no verdict for it to report."
                )
            for field_name in (
                "scaled_mean_criterion",
                "unscaled_abe_criterion",
                "variability_ratio_criterion",
                "test_variance",
                "treatment_contrast",
            ):
                value = getattr(self, field_name)
                if value is not None:
                    raise NtiNotDecidable(
                        f"applicability is {self.applicability} and "
                        f"{field_name} is populated. A product the NTI "
                        "procedure does not apply to must not carry the "
                        "analysis it would have received."
                    )
            return

        if self.decided:
            unavailable = [
                label
                for label, outcome in self._criterion_outcomes()
                if outcome is None
            ]
            if unavailable:
                raise NtiNotDecidable(
                    f"decided=True with criterion {', '.join(unavailable)} "
                    "unavailable. Appendix F step 5 requires all three "
                    "conditions for each PK parameter tested; an endpoint with "
                    "a criterion missing is untested under this procedure, not "
                    "decided."
                )

    # --------------------------------------------------------- criteria ---

    def _criterion_outcomes(self) -> tuple[tuple[str, bool | None], ...]:
        """(label, passes) for a, b and c. `None` for absent or unevaluable."""
        return (
            (
                "a",
                None
                if self.scaled_mean_criterion is None
                else self.scaled_mean_criterion.passes,
            ),
            (
                "b",
                None
                if self.unscaled_abe_criterion is None
                else self.unscaled_abe_criterion.passes,
            ),
            (
                "c",
                None
                if self.variability_ratio_criterion is None
                else self.variability_ratio_criterion.passes,
            ),
        )

    @property
    def criterion_a_passes(self) -> bool | None:
        return self._criterion_outcomes()[0][1]

    @property
    def criterion_b_passes(self) -> bool | None:
        return self._criterion_outcomes()[1][1]

    @property
    def criterion_c_passes(self) -> bool | None:
        return self._criterion_outcomes()[2][1]

    @property
    def failed_criteria(self) -> tuple[str, ...]:
        """Which of a, b and c were evaluated and FAILED."""
        return tuple(
            label for label, outcome in self._criterion_outcomes()
            if outcome is False
        )

    @property
    def unavailable_criteria(self) -> tuple[str, ...]:
        """Which of a, b and c could not be evaluated. Not failures."""
        return tuple(
            label for label, outcome in self._criterion_outcomes()
            if outcome is None
        )

    @property
    def passes(self) -> bool | None:
        """All three, or nothing.

        `None` whenever the endpoint is not decided. The constructor guarantees
        that a decided endpoint has all three criteria evaluated, so the
        conjunction below never sees a `None`; the check is kept because a
        conjunction that silently treated a missing criterion as `True` is the
        specific failure this procedure is most exposed to.
        """
        if not self.decided:
            return None
        outcomes = [outcome for _, outcome in self._criterion_outcomes()]
        if any(outcome is None for outcome in outcomes):
            return None
        return all(outcomes)

    # --------------------------------------------------- classification ---

    @property
    def selected_method(self) -> Method | None:
        """Derived, never stored: there is no field for a contradiction to use."""
        if not self.applicability.permits_verdict:
            return None
        return Method.FDA_NTI_RSABE

    @property
    def design_valid(self) -> bool | None:
        """`None` when the design question was never asked.

        For a product Appendix F does not apply to, the design gate does not
        run - III.B's requirement is a requirement OF the NTI procedure - so
        reporting the design as valid or invalid would answer a question the
        procedure did not put.
        """
        if not self.applicability.permits_verdict:
            return None
        return self.design is ReplicateDesign.FULLY_REPLICATE

    @property
    def regulatory_basis(self) -> tuple[Citation, ...]:
        """The sections this result rests on, as citation objects."""
        return (
            FDA_STATISTICAL_APPROACHES_III_B,
            FDA_STATISTICAL_APPROACHES_APPENDIX_F,
            FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5,
        )

    # --------------------------------------------------- explainability ---

    def _final_decision_sentence(self) -> str:
        if self.passes is True:
            return "Final decision: PASS only because criteria a, b and c all passed."
        if self.passes is False:
            return (
                f"Final decision: FAIL because criterion "
                f"{', '.join(self.failed_criteria)} failed; Appendix F step 5 "
                "requires all three."
            )
        if self.unavailable_criteria:
            return (
                f"Final decision: NOT DECIDED - criterion "
                f"{', '.join(self.unavailable_criteria)} could not be "
                "evaluated. Missing is neither a pass nor a failure."
            )
        return "Final decision: NOT DECIDED - no verdict was assembled."

    def provenance(self) -> list[str]:
        """Every basis this NTI result rests on, cited to Appendix F.

        WHY sWR IS NOT CITED TO APPENDIX G HERE

        The sWR estimator is shared with the highly-variable procedure, and its
        own `provenance()` cites Appendix G - correctly, for that procedure.
        But an NTI decision does not rest on Appendix G. Appendix F step 1
        states the same closed form, in the same words, restricted to `m = 2`,
        and that is the authority for this result.

        Reusing an implementation is not the same as inheriting its citation.
        Delegating here would have put Appendix G in the provenance of a
        narrow-therapeutic-index decision, which a test now prevents.

        A REFUSED RESULT LEADS WITH THE REFUSAL

        A reader who stops after one line must come away knowing no decision
        was issued, so that line comes first and no criterion line follows.
        """
        applicability_rule = (
            "applicability rule: Appendix F decides only a product confirmed "
            "to be narrow therapeutic index, and membership of that class is "
            "declared, never inferred from the design or the variability — "
            f"{FDA_STATISTICAL_APPROACHES_III_B} "
            f"[verified, via {VIA_PRIMARY_DOCUMENT}]"
        )
        if not self.applicability.permits_verdict:
            return [
                _applicability_explanation(self.applicability),
                applicability_rule,
                "the variability figures on this result are DESCRIPTIVE ONLY: "
                "no criterion was computed, no analysis method was selected "
                "and no bioequivalence decision was issued.",
            ]

        lines = [
            _applicability_explanation(self.applicability),
            applicability_rule,
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
        if self.test_variance is not None:
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
        lines.append(
            "criterion b is 'the unscaled average BE procedure' of Appendix F "
            "step 3, which names the procedure and not a model; for a fully "
            "replicate study it is computed through Appendix C's mixed model, "
            "the guidance's own analysis for replicate average BE. An "
            "interpretation of step 3, recorded as one."
        )
        return lines

    def summary(self) -> str:
        if not self.applicability.permits_verdict:
            swr = None if self.reference_variance is None else self.reference_variance.swr
            body = (
                f"{self.endpoint} ({self.design}) — FDA narrow therapeutic index\n"
                f"  NO BE DECISION ISSUED - {self.applicability}\n"
                f"  {_applicability_explanation(self.applicability)}\n"
                f"  descriptive only: sWR = "
                f"{'n/a' if swr is None else f'{swr:.6f}'}, "
                f"n = {self.n_for_swr}, df = {self.reference_variance_df}\n"
            )
            if self.diagnostics:
                body += "  diagnostics:\n" + "\n".join(
                    f"    {d}" for d in self.diagnostics
                )
            return body

        head = (
            f"{self.endpoint} ({self.design}) — FDA narrow therapeutic index\n"
            f"  {_applicability_explanation(self.applicability)}\n"
            f"  Design: fully replicate (TRTR / RTRT) — acceptable under III.B.\n"
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
        if self.unscaled_abe_criterion is not None:
            lines += self.unscaled_abe_criterion.explain()
        else:
            lines.append("criterion b: NOT COMPUTED")
        if self.variability_ratio_criterion is not None:
            lines += self.variability_ratio_criterion.explain()
        else:
            lines.append("criterion c: NOT COMPUTED")

        verdict = {True: "PASS", False: "FAIL", None: "NOT DECIDED"}[self.passes]
        lines.append(f"all three criteria are required -> {verdict}")
        lines.append(self._final_decision_sentence())

        body = "\n".join(f"  {line}" for line in lines)
        if self.diagnostics:
            body += "\n  diagnostics:\n" + "\n".join(
                f"    {d}" for d in self.diagnostics
            )
        return head + body


# ------------------------------------------------- the applicability gate ---


def _require_fda_spec(spec: BeSpec | None) -> None:
    """A spec resolved for another jurisdiction is refused, not reconciled.

    Another jurisdiction's narrow therapeutic index procedure narrows the
    acceptance interval where FDA adds two criteria, so a spec carrying it
    describes a different procedure. Reconciling its drug class with the NTI
    status would answer the wrong question correctly.
    """
    if spec is None or spec.jurisdiction is Jurisdiction.FDA:
        return
    raise NotApplicable(
        f"the supplied spec is for {spec.jurisdiction}, resolving to "
        f"{spec.method}. FDA Appendix F is not a parameterisation of another "
        "jurisdiction's narrow therapeutic index rule, so this spec is refused "
        "here rather than reconciled."
    )


def _applicability_refusal(applicability: NtiApplicability) -> Diagnostic:
    """Why no verdict was issued, in words that name what would change it.

    FATAL: in this package FATAL means the analysis did not produce the thing
    asked for, and that is literally true of the decision.
    """
    if applicability is NtiApplicability.NOT_APPLICABLE_NOT_NTI:
        return Diagnostic(
            DiagnosticCode.FDA_NTI_NOT_APPLICABLE_NOT_NTI,
            Severity.FATAL,
            None,
            "FDA NTI procedure not applicable: the product is identified as "
            "not narrow therapeutic index. Appendix F - sigma_W0 = 0.10, the "
            "unscaled 80.00-125.00% limits and the within-subject variability "
            "comparison - is FDA's procedure for NTI drugs (III.B), and a "
            "product outside that class is assessed under the procedure its "
            "own class requires. Reference variability is reported as a "
            "descriptive quantity and no bioequivalence decision was issued",
            {
                "applicability": str(applicability),
                "required_procedure": (
                    "the procedure for the product's declared class, not "
                    "Appendix F"
                ),
            },
        )
    return Diagnostic(
        DiagnosticCode.FDA_NTI_APPLICABILITY_REQUIRES_NTI_STATUS,
        Severity.FATAL,
        None,
        "FDA NTI applicability cannot be determined because NTI status was not "
        "specified. Variability estimates are descriptive only; no regulatory "
        "BE decision was issued. Membership of the NTI class is a regulatory "
        "property of the product - III.B defines it by the clinical "
        "consequence of small differences in dose or concentration - and is "
        "not inferred from a fully replicate design or a low within-subject "
        "variability, both of which are common among products that are not "
        "NTI. Supply nti_status, or a spec whose drug_class states the "
        "product's class",
        {"applicability": str(applicability)},
    )


def _refused_result(
    dataset: ReplicateDataset, applicability: NtiApplicability
) -> FdaNtiResult:
    """Descriptive reference variability, the refusal, and nothing decisional.

    sWR describes the reference's own reproducibility and asserts nothing about
    bioequivalence, so it is reported. sWT is not: its estimator requires the
    fully replicate design, and the design gate is part of the procedure that
    does not apply. No treatment contrast is estimated either - a point estimate
    of T against R is the shape of an answer.
    """
    variance = estimate_reference_variance(dataset)
    diagnostics = list(variance.diagnostics)
    diagnostics.append(_applicability_refusal(applicability))
    return FdaNtiResult(
        endpoint=dataset.endpoint,
        design=dataset.design,
        reference_variance=variance,
        applicability=applicability,
        decided=False,
        diagnostics=tuple(diagnostics),
        n_for_swr=variance.n_subjects,
        reference_variance_df=variance.degrees_of_freedom,
    )


def assess_nti_endpoint(
    dataset: ReplicateDataset,
    *,
    spec: BeSpec | None = None,
    observations: list | None = None,
    nti_status: NtiStatus = NtiStatus.NOT_STATED,
) -> FdaNtiResult:
    """FDA's NTI procedure for one PK endpoint.

    THE ORDER, AND WHY IT IS THIS ORDER

        1. the spec's jurisdiction          raises NotApplicable if not FDA
        2. ONE answer about the product     raises ContradictoryProductClass
        3. applicability                    refuses unless confirmed NTI
        4. the design gate                  raises NtiDesignError unless fully
                                            replicate
        5. the three criteria               each reported on its own
        6. the decision                     only when all three were evaluated

    Steps 2 and 3 are new, and they close a defect: this function used to take
    no product-class input at all, so a STANDARD or HIGHLY_VARIABLE product on a
    fully replicate design received an Appendix F verdict. The applicability
    gate runs before the design gate because the design requirement is a
    requirement OF the NTI procedure - for a product that procedure does not
    apply to, the design is not the question.

    ALL THREE CRITERIA CAN BE COMPUTED - GIVEN THE RAW OBSERVATIONS.

    Criterion (b) is the ordinary unscaled 80.00-125.00% test, and for a fully
    replicate study that means Appendix C's mixed model. `observations` is
    needed for the same reason it is needed in `hvd.py`: Appendix C is an
    AVAILABLE CASE analysis and `ReplicateDataset` has already dropped subjects
    that the sWR estimator could not use. Without the raw rows, criterion (b)
    stays uncomputed and the endpoint stays undecided.

    NTI's design gate is what makes this clean: it already requires a fully
    replicate design, which is precisely the scope Appendix C is implemented
    and checked for. There is no partial replicate case to refuse here.
    """
    _require_fda_spec(spec)
    resolved_nti = reconcile_nti_status(spec=spec, nti_status=nti_status)
    applicability = fda_nti_applicability(resolved_nti)
    if not applicability.permits_verdict:
        return _refused_result(dataset, applicability)

    require_fully_replicate(dataset)

    variance = estimate_reference_variance(dataset)
    test_variance = estimate_test_variance(dataset)
    diagnostics = list(variance.diagnostics)
    diagnostics += [
        d for d in test_variance.diagnostics if d not in variance.diagnostics
    ]

    contrast = estimate_treatment_contrast(dataset)
    diagnostics += [d for d in contrast.diagnostics if d not in diagnostics]

    lower = FDA_NTI_CONSTANTS["unscaled_lower_percent"].value
    upper = FDA_NTI_CONSTANTS["unscaled_upper_percent"].value
    if observations is None:
        unscaled = NtiUnscaledAbeCriterion(
            lower_limit_percent=lower,
            upper_limit_percent=upper,
            computed=False,
            reason=(
                "criterion b is Appendix C's mixed model, which is an AVAILABLE "
                "CASE analysis and needs the raw observations. The dataset has "
                "already dropped subjects the sWR estimator could not use, so "
                "they cannot be recovered from it. Pass `observations=` to "
                "compute this criterion"
            ),
        )
        diagnostics.append(replicate_abe_unavailable(dataset))
    else:
        from be_stats.appendix_c import analyse_replicate_abe_full

        appendix_c = analyse_replicate_abe_full(observations)
        diagnostics += [
            d for d in appendix_c.diagnostics if d not in diagnostics
        ]
        if appendix_c.decided:
            unscaled = NtiUnscaledAbeCriterion(
                lower_limit_percent=lower,
                upper_limit_percent=upper,
                computed=True,
                reason=(
                    "computed from FDA Appendix C's mixed model on the "
                    "subject-period observations, with Satterthwaite "
                    "denominator degrees of freedom"
                ),
                ci_lower_percent=appendix_c.ci_lower_percent,
                ci_upper_percent=appendix_c.ci_upper_percent,
                geometric_mean_ratio_percent=(
                    appendix_c.geometric_mean_ratio_percent
                ),
            )
        else:
            unscaled = NtiUnscaledAbeCriterion(
                lower_limit_percent=lower,
                upper_limit_percent=upper,
                computed=False,
                reason=(
                    "Appendix C declined to decide for this dataset; see the "
                    "diagnostics"
                ),
            )

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
        reference_variance=variance,
        applicability=applicability,
        scaled_mean_criterion=scaled,
        unscaled_abe_criterion=unscaled,
        variability_ratio_criterion=ratio,
        test_variance=test_variance,
        treatment_contrast=contrast if contrast.estimable else None,
        # DECIDED ONLY WHEN ALL THREE CRITERIA WERE EVALUATED - and the
        # constructor now refuses anything else, so this condition cannot be
        # loosened without a construction error saying which criterion is gone.
        decided=(
            scaled is not None
            and unscaled.passes is not None
            and ratio.passes is not None
        ),
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
    *,
    spec: BeSpec | None = None,
    observations: dict[str, list] | None = None,
    nti_status: NtiStatus = NtiStatus.NOT_STATED,
) -> dict[str, FdaNtiResult]:
    """Every endpoint assessed on its own data.

    A loop, and deliberately nothing more: AUC and Cmax are evaluated
    separately, and one endpoint's outcome must not enter the other's
    arithmetic.

    A CORRECTION: THIS COULD NEVER DECIDE

    It used to call `assess_nti_endpoint(dataset)` with no observations, so
    criterion (b) - Appendix C, which needs the raw rows - was never computed
    and every endpoint of every study came back NOT DECIDED. Observations are
    now accepted per endpoint, keyed like `datasets`.

    The product's class applies to every endpoint at once, so `spec` and
    `nti_status` are passed through unchanged; applicability is therefore the
    same for AUC and Cmax.
    """
    observations = observations or {}
    return {
        endpoint: assess_nti_endpoint(
            dataset,
            spec=spec,
            observations=observations.get(endpoint),
            nti_status=nti_status,
        )
        for endpoint, dataset in datasets.items()
    }
