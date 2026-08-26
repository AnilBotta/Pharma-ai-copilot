"""Within-subject reference variability, and nothing that decides anything.

WHAT THIS MODULE ANSWERS

Given a validated replicate dataset: what is sWR, what is CVwR, on how many
degrees of freedom, from which subjects - and is it estimable at all?

WHAT IT REFUSES TO ANSWER

Whether the study is bioequivalent. Whether reference scaling applies. The
verified regulatory switching value sWR = 0.294 lives in `spec.py` and is not
imported here, deliberately: a module that both estimates a quantity and
applies the regulator's threshold to it is one refactor away from a result
object carrying a pass. Measuring and deciding are separated so the measurement
can be checked before anything depends on it.

ONE FORMULA, TWO DESIGNS - AND A CORRECTION

An earlier version of this module declined to estimate sWR for the fully
replicated design. The reasoning was that FDA analyses the partial replicate
through PROC GLM and the fully replicated design through PROC MIXED, so the
two must need different estimators, and substituting the closed form would be
our arithmetic standing in for the regulator's method.

**That inference was wrong, and reading Appendix G settled it.** The guidance
gives the sWR calculation ONCE, for both designs, and distinguishes them only
by the sequence count:

    sWR^2 = SUM_i SUM_j (Dij - Dbar_i.)^2 / (2(n - m))

    "I = number of sequences m used in the study
     [m = 3 for partially replicate design: TRR, RTR, and RRT;
      m = 2 for fully replicate design: TRTR and RTRT]"

The GLM/MIXED distinction is real and applies to the *other* intermediate - the
treatment contrast `ilat`, where a four-period design needs a mixed model with
Satterthwaite degrees of freedom. It is not about sWR. Both SAS examples reach
sWR the same way: the partial one takes `s2wr = ms/2` from a one-way ANOVA of
`dlat` on sequence, and the fully replicated one takes `s2wr = estimate/2` from
the residual covariance parameter of the same `dlat = seq` model. Those are the
same quantity, and both equal the closed form above.

So both estimators are implemented, and the class split is retained because the
sequence count differs and because the analyses genuinely diverge at the next
step - which belongs to the release that computes the contrast, not this one.

DEGENERACY IS NOT PRECISION

A reference variance of zero means every subject's two reference measurements
were identical. That is duplicated rows or over-rounded data, never a study
with perfect reproducibility. It returns a non-estimable result with sWR and
CVwR as `None` rather than 0.0, so no downstream reader can mistake it for a
very good study.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from be_stats.conversions import log_sd_to_cv
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    VIA_STATISTICAL_REVIEW,
    Citation,
    ValidationStatus,
    VerificationStatus,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateSequence,
    reference_differences,
)

#: Where the partial-replicate expression comes from. Attached to every result
#: so a number printed in a report can name its own definition.
APPENDIX_G: Citation = FDA_STATISTICAL_APPROACHES_APPENDIX_G

#: How that definition was checked. This tooling could not retrieve the FDA
#: guidance PDF, so the formula and its terms were supplied at statistical
#: review against the primary source, with the section reference above. A
#: figure read from the document and one relayed by a qualified reviewer are
#: both VERIFIED, and an auditor is entitled to know which.
VERIFIED_BY: str = "statistical review against primary FDA source"


class NotEstimable(Exception):
    """The quantity does not exist for these data, or not from this release.

    Distinct from a `DataError`: the data passed validation, and there is still
    no number to report. Two situations reach it, and the `code` tells them
    apart - `ESTIMATOR_NOT_IMPLEMENTED` means the engine is unfinished,
    everything else means the data cannot support the estimate.

    Degeneracy and insufficient degrees of freedom do NOT raise: they return a
    result carrying `estimable = False` and the diagnostics, because a report
    wants to print why rather than catch something.
    """

    def __init__(
        self,
        message: str,
        code: DiagnosticCode = DiagnosticCode.ESTIMATOR_NOT_IMPLEMENTED,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReferenceVarianceResult:
    """What was estimated, from whom, and whether it means anything.

    `swr` and `cv_wr` are `None` when `estimable` is False. They are not zero.
    A zero would be read by something, eventually, as a very precise study.
    """

    design: ReplicateDesign
    endpoint: str

    #: sWR^2 on the log scale, or None when not estimable.
    variance_wr: float | None
    #: sqrt(variance_wr), or None.
    swr: float | None
    #: sqrt(exp(sWR^2) - 1), as a fraction. Multiply by 100 for a percentage.
    cv_wr: float | None

    #: n - m: subjects contributing, less one per contributing sequence.
    degrees_of_freedom: int
    #: `n` in the formula: subjects that contributed a reference difference.
    n_subjects: int
    #: `m` in the formula, counted as sequences that actually contributed.
    n_sequences: int

    estimable: bool
    diagnostics: tuple[Diagnostic, ...] = ()

    #: Accounting that must add up, and is asserted to.
    subjects_received: int = 0
    subjects_used: int = 0
    subjects_excluded: int = 0
    exclusion_reasons: dict[DiagnosticCode, int] = field(default_factory=dict)

    #: Which estimator ran, named on the result rather than inferred from the
    #: design, so a future third estimator cannot be mistaken for this one.
    estimator: str = ""
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED

    @property
    def cv_wr_percent(self) -> float | None:
        return None if self.cv_wr is None else 100.0 * self.cv_wr

    def provenance(self) -> list[str]:
        """One line per statistical definition this result rests on."""
        return [
            f"sWR^2 = SUM_i SUM_j (Dij - Dbar_i)^2 / (2(n - m)), with "
            f"Dij = Rij1 - Rij2 on the log scale — {APPENDIX_G} "
            f"[{VerificationStatus.VERIFIED}, via {VERIFIED_BY}]",
            "CVwR = sqrt(exp(sWR^2) - 1) — be_stats.conversions.log_sd_to_cv, "
            "the package's single canonical conversion",
            f"estimator: {self.estimator} [{self.validation_status}]",
        ]

    def summary(self) -> str:
        """What a reader needs, ending where this module's authority ends."""
        head = (
            f"{self.design} / {self.endpoint}\n"
            f"Subjects received: {self.subjects_received}\n"
            f"Subjects contributing to sWR: {self.subjects_used}\n"
        )
        if self.estimable:
            body = (
                f"\nsWR^2 = {self.variance_wr:.6f}\n"
                f"sWR    = {self.swr:.6f}\n"
                f"CVwR   = {self.cv_wr_percent:.2f}%\n"
                f"\nReference degrees of freedom = {self.degrees_of_freedom} "
                f"(n {self.n_subjects} - m {self.n_sequences})\n"
            )
        else:
            body = (
                "\nsWR is NOT ESTIMABLE from these data. "
                "No value is reported, because a zero would be read as "
                "precision.\n"
            )
        if self.diagnostics:
            lines = "\n".join(f"  {d}" for d in self.diagnostics)
            body += f"\nDiagnostics:\n{lines}\n"
        return head + body + (
            "\nRegulatory BE decision: NOT COMPUTED IN THIS MODULE.\n"
            "Method selection (sWR >= 0.294) and the RSABE criterion are a "
            "separate release."
        )


# --------------------------------------------------------------- partial ---


class _ReferenceVarianceEstimator:
    """FDA Appendix G step 1, shared by both replicate designs.

        sWR^2 = SUM_i SUM_j (Dij - Dbar_i.)^2 / (2(n - m))

    with `Dij = Rij1 - Rij2` on the log scale, `m` the number of sequences and
    `n` the total number of subjects used in the study.

    The two subclasses differ only in which design they accept and therefore in
    what `m` can be. They are separate types rather than a parameter because a
    caller handing a `TRTR` dataset to the partial-replicate estimator has made
    a mistake worth failing on, and because the analyses diverge at the next
    step - the treatment contrast, which is a later release.

    THE TWO IN THE DENOMINATOR IS NOT A DEGREES-OF-FREEDOM TERM

    Worth stating because it is the most common way to get this formula wrong
    by a factor of two. `Dij` is a difference of two measurements, so its
    variance is 2 sigma_WR^2. The sum of squared deviations about the sequence
    means therefore estimates `2 sigma_WR^2 x (n - m)`, and dividing by
    `2(n - m)` recovers sigma_WR^2. The chi-square degrees of freedom of the
    estimate are `n - m`, NOT `2(n - m)` - which is what this result reports.

    `m` IS COUNTED, NOT ASSUMED

    The guidance defines `m` as "number of sequences used in the study" and
    then brackets the usual values - 3 for the partial replicate, 2 for the
    fully replicated design. Where every subject in a sequence has been
    excluded, that sequence was not used: its mean does not exist, it absorbs
    no degree of freedom, and the sum has no term from it. Counting it anyway
    would understate the degrees of freedom and inflate the variance.

    This also matches how the guidance's own SAS reaches the same number. Both
    examples fit `dlat = seq` and take the error term from it, and neither
    `PROC GLM` nor `PROC MIXED` spends a degree of freedom on a `CLASS` level
    with no observations. A shortfall against the design's expected sequence
    count is recorded as a diagnostic rather than absorbed silently.
    """

    #: Set by the subclasses.
    design: ReplicateDesign
    name: str
    validation_status = ValidationStatus.IMPLEMENTED_UNVALIDATED

    def estimate(self, dataset: ReplicateDataset) -> ReferenceVarianceResult:
        if dataset.design is not self.design:
            raise ValueError(
                f"{self.name} was handed a {dataset.design} dataset. The "
                "estimators are not interchangeable; dispatch through "
                "estimate_reference_variance()."
            )

        diagnostics = list(dataset.diagnostics)
        grouped = reference_differences(dataset)

        n = sum(len(v) for v in grouped.values())
        m = len(grouped)

        for sequence in sorted(self.design.sequences, key=lambda s: s.value):
            if sequence not in grouped:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.SEQUENCE_CONTRIBUTED_NO_SUBJECTS,
                        Severity.ADVISORY,
                        None,
                        f"sequence {sequence.value} contributed no subject, so "
                        "the estimate rests on fewer sequences than the design "
                        "defines; m is counted, not assumed",
                        {"sequence": sequence.value},
                    )
                )

        df = n - m
        if df < 1:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.INSUFFICIENT_REFERENCE_DF,
                    Severity.FATAL,
                    None,
                    f"{n} contributing subject(s) across {m} sequence(s) leaves "
                    f"{df} degrees of freedom; at least 1 is needed. Each "
                    "sequence spends one degree of freedom on its own mean",
                    {"n_subjects": n, "n_sequences": m, "degrees_of_freedom": df},
                )
            )
            return self._not_estimable(dataset, diagnostics, n, m, max(df, 0))

        # `math.fsum`, not `sum`, and this is not fastidiousness.
        #
        # Floating-point addition is not associative, so `sum` over the same
        # values in a different order can differ in the last bit. The values
        # here arrive in whatever order the input file had, which means a
        # study re-exported with a different sort order would produce an sWR
        # differing by roughly 1e-16 - invisible, reproducible by nobody, and
        # exactly the kind of thing that surfaces years later as "your tool
        # gave two answers for one dataset".
        #
        # `fsum` returns the correctly-rounded sum of the exact total, so every
        # permutation gives a bit-identical result. The invariance tests in
        # tests/integration/test_replicate_designs.py assert equality, not
        # approximate equality, and they found this.
        deviations: list[float] = []
        for differences in grouped.values():
            mean = math.fsum(differences) / len(differences)
            deviations.extend((d - mean) ** 2 for d in differences)
        sum_squares = math.fsum(deviations)

        # A sum of squares over a positive denominator cannot be negative, in
        # exact arithmetic or in floating point. There is therefore no
        # clamping rule here and no numerical tolerance to document - the only
        # way to reach this branch is a defect in the code above, and a silent
        # correction would hide it.
        if sum_squares < 0.0:  # pragma: no cover - unreachable by construction
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.SINGULAR_MODEL,
                    Severity.FATAL,
                    None,
                    f"negative sum of squares ({sum_squares}); this is not a "
                    "data condition, it is a defect in the estimator",
                    {"sum_of_squares": sum_squares},
                )
            )
            return self._not_estimable(dataset, diagnostics, n, m, df)

        variance = sum_squares / (2.0 * df)

        # Matches the degeneracy rule the rest of the engine already applies:
        # exact zero is refused, near-zero still estimates. See
        # abe._reject_zero_variance and validation/README.md - the tolerance is
        # the engine's established one, not a new number invented here.
        if variance <= 0.0:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.DEGENERATE_REFERENCE_VARIANCE,
                    Severity.FATAL,
                    None,
                    "the estimated within-reference variance is zero: every "
                    "contributing subject's two reference measurements were "
                    "identical. That is duplicated rows, over-rounded values or "
                    "placeholder data - not a perfectly reproducible product. "
                    "No sWR is reported, because a zero would be read as "
                    "certainty",
                    {"sum_of_squares": sum_squares, "degrees_of_freedom": df},
                )
            )
            return self._not_estimable(dataset, diagnostics, n, m, df)

        swr = math.sqrt(variance)
        return self._result(
            dataset,
            diagnostics,
            variance_wr=variance,
            swr=swr,
            cv_wr=log_sd_to_cv(swr),
            n=n,
            m=m,
            df=df,
            estimable=True,
        )

    # ------------------------------------------------------------ shared ---

    def _not_estimable(
        self,
        dataset: ReplicateDataset,
        diagnostics: list[Diagnostic],
        n: int,
        m: int,
        df: int,
    ) -> ReferenceVarianceResult:
        return self._result(
            dataset,
            diagnostics,
            variance_wr=None,
            swr=None,
            cv_wr=None,
            n=n,
            m=m,
            df=df,
            estimable=False,
        )

    def _result(
        self,
        dataset: ReplicateDataset,
        diagnostics: list[Diagnostic],
        *,
        variance_wr: float | None,
        swr: float | None,
        cv_wr: float | None,
        n: int,
        m: int,
        df: int,
        estimable: bool,
    ) -> ReferenceVarianceResult:
        from be_stats.diagnostics import counts_by_code

        excluded = len(dataset.subjects_excluded)
        received = len(dataset.subjects_received)
        exclusions = [d for d in diagnostics if d.severity is Severity.EXCLUSION]
        return ReferenceVarianceResult(
            design=dataset.design,
            endpoint=dataset.endpoint,
            variance_wr=variance_wr,
            swr=swr,
            cv_wr=cv_wr,
            degrees_of_freedom=df,
            n_subjects=n,
            n_sequences=m,
            estimable=estimable,
            diagnostics=tuple(diagnostics),
            subjects_received=received,
            subjects_used=n,
            subjects_excluded=excluded,
            exclusion_reasons=counts_by_code(exclusions),
            estimator=self.name,
            validation_status=self.validation_status,
        )


# ----------------------------------------------------------------- fully ---


class PartialReplicateReferenceVarianceEstimator(_ReferenceVarianceEstimator):
    """TRR / RTR / RRT, where the guidance's `m` is 3.

    FDA's SAS example for this design fits `PROC GLM ... model dlat=seq` and
    takes `s2wr = ms / 2` - the error mean square of a one-way analysis of the
    reference differences on sequence, halved. That is the closed form in the
    base class, since `ms = SS / (n - m)`.
    """

    design = ReplicateDesign.PARTIAL_REPLICATE
    name = "partial-replicate within-reference variance (FDA Appendix G)"


class FullyReplicateReferenceVarianceEstimator(_ReferenceVarianceEstimator):
    """TRTR / RTRT, where the guidance's `m` is 2.

    Implemented in 0.3.0 after the guidance was obtained and read. The previous
    release declined here, on the reasoning that FDA's use of `PROC MIXED` for
    fully replicated studies implied a different variance estimator. It does
    not: Appendix G gives the sWR calculation once for both designs, and the
    mixed model applies to the treatment contrast rather than to sWR.

    FDA's SAS example for this design takes `s2wr = estimate / 2` from the
    residual covariance parameter of `PROC MIXED ... model dlat=seq` - the same
    quantity the partial example takes from `PROC GLM`, and the same as the
    closed form.

    Caution carried forward: `Dij` here is still `Rij1 - Rij2`, the difference
    of the subject's TWO reference measurements. The two TEST measurements this
    design also collects play no part in sWR. They enter `Iij`, which is the
    mean of the test observations minus the mean of the reference ones, and
    which nothing in this release consumes.
    """

    design = ReplicateDesign.FULLY_REPLICATE
    name = "fully-replicate within-reference variance (FDA Appendix G)"


_ESTIMATORS = {
    ReplicateDesign.PARTIAL_REPLICATE: PartialReplicateReferenceVarianceEstimator(),
    ReplicateDesign.FULLY_REPLICATE: FullyReplicateReferenceVarianceEstimator(),
}


def estimator_for(design: ReplicateDesign):
    """The estimator that belongs to this design. No fallback."""
    try:
        return _ESTIMATORS[design]
    except KeyError:  # pragma: no cover - the enum is exhaustive
        raise NotEstimable(f"No estimator is registered for {design}.") from None


def estimate_reference_variance(
    dataset: ReplicateDataset,
) -> ReferenceVarianceResult:
    """sWR for a validated replicate dataset, by the estimator its design uses.

    Dispatch is by design, and there is deliberately no default: a design
    without a registered estimator raises rather than borrowing one.
    """
    return estimator_for(dataset.design).estimate(dataset)


def sequence_mean_differences(
    dataset: ReplicateDataset,
) -> dict[ReplicateSequence, float]:
    """`Dbar_i.` per sequence - the intermediate a hand check needs.

    Exposed so an independent calculation can be compared term by term rather
    than only at the final variance, where an error of the right magnitude in
    the wrong place is invisible.
    """
    return {
        sequence: math.fsum(values) / len(values)
        for sequence, values in reference_differences(dataset).items()
    }
