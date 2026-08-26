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

A ZERO IS REPORTED, AND FLAGGED HARD

A reference variance of exactly zero means every contributing subject's two
reference measurements were identical - in practice duplicated rows,
over-rounded values or placeholder data far more often than a reproducible
product.

An earlier version refused it, returning non-estimable so that no reader could
mistake a zero for a very good study. That was a regulatory rejection rule
invented inside a measurement, and Appendix G contains no such rule: it defines
a quantity, and for those data the quantity is zero. The estimate is now
reported with a `DATA_QUALITY` diagnostic, and the judgement is left to the
places entitled to make it - dataset validation refuses genuine integrity
problems on their own evidence, and the downstream average BE analysis already
refuses its own degenerate variance.

Non-estimable is reserved for cases where the quantity genuinely does not
exist: fewer than one degree of freedom, or a design missing a sequence
Appendix G requires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from be_stats.conversions import log_sd_to_cv
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    VIA_PRIMARY_DOCUMENT,
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

#: Where the sWR expression comes from. Attached to every result so a number
#: printed in a report can name its own definition.
APPENDIX_G: Citation = FDA_STATISTICAL_APPROACHES_APPENDIX_G

#: How that definition was checked. The SAME object `spec.py` uses for the
#: constants, imported rather than restated: this module briefly carried its
#: own string saying the PDF could not be retrieved, which was left behind when
#: the guidance was obtained. Two chains of custody for one formula is one
#: chain too many, and the stale one was the false one.
VERIFIED_BY: str = VIA_PRIMARY_DOCUMENT


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

    `swr` and `cv_wr` are `None` when `estimable` is False, and a real number
    otherwise - including a real 0.0, which is an estimate and not a refusal.
    A zero always arrives with a `ZERO_REFERENCE_VARIANCE` diagnostic at
    `DATA_QUALITY` severity, so a caller can find it without inspecting the
    value.
    """

    design: ReplicateDesign
    endpoint: str

    #: sWR^2 on the log scale, or None when not estimable.
    variance_wr: float | None
    #: sqrt(variance_wr), or None.
    swr: float | None
    #: sqrt(exp(sWR^2) - 1), as a fraction. Multiply by 100 for a percentage.
    cv_wr: float | None

    #: n - m.
    degrees_of_freedom: int
    #: `n` in the formula: subjects that contributed a reference difference.
    n_subjects: int
    #: `m` in the formula. The DESIGN's constant from Appendix G - 3 for the
    #: partial replicate, 2 for the fully replicated design - never the number
    #: of sequences that happened to survive exclusion.
    regulatory_m: int
    #: How many of the design's sequences actually contributed a subject.
    #: Reported beside `regulatory_m` rather than replacing it: when the two
    #: disagree the result is not estimable, and a reader should be able to see
    #: why without reading the diagnostics.
    contributing_sequences: int

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
                f"(n {self.n_subjects} - m {self.regulatory_m})\n"
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

    `m` IS THE DESIGN'S, NOT THE DATA'S - A CORRECTION

    An earlier version of this estimator set `m = len(grouped)`, the number of
    sequences that still held a subject after exclusions, reasoning that an
    empty sequence has no mean, absorbs no degree of freedom, and contributes
    no term - and that SAS would behave the same way on an empty `CLASS` level.

    That reasoning is about arithmetic, and `m` is not an arithmetic question.
    Appendix G names it: "m = 3 for partially replicate design: TRR, RTR, and
    RRT; m = 2 for fully replicate design: TRTR and RTRT". It is a property of
    the design being analysed.

    The consequence of getting this wrong is not a rounding difference. A
    three-sequence study in which one sequence contributes nobody is no longer
    the design Appendix G describes, and quietly analysing it as a two-sequence
    design produces an sWR for a study that was not run - on degrees of freedom
    belonging to a different design. So `m` comes from
    `design.regulatory_sequence_count`, and a missing required sequence makes
    the result non-estimable rather than adjusting the constant to fit.

    This is the same failure as deriving 0.294 from a 30% CV: locally correct
    arithmetic substituted for a figure the regulator specified.
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
        #: From the DESIGN, per Appendix G. Never from what survived exclusion.
        m = self.design.regulatory_sequence_count
        contributing = len(grouped)

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
                    f"sequence(s) {', '.join(missing)} contributed no usable "
                    f"subject, so this is not the {m}-sequence design Appendix "
                    "G specifies. m is the design's constant and will not be "
                    "reduced to fit what is left: doing so would report an sWR "
                    "for a study that was not run, on degrees of freedom "
                    "belonging to a different design",
                    {
                        "missing_sequences": missing,
                        "regulatory_m": m,
                        "sequences_contributing": contributing,
                    },
                )
            )
            return self._not_estimable(dataset, diagnostics, n, m, 0, contributing)

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
                    {"n_subjects": n, "regulatory_m": m, "degrees_of_freedom": df},
                )
            )
            return self._not_estimable(
                dataset, diagnostics, n, m, max(df, 0), contributing
            )

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
            return self._not_estimable(dataset, diagnostics, n, m, df, contributing)

        variance = sum_squares / (2.0 * df)

        # ZERO IS AN ESTIMATE, NOT A REFUSAL - A CORRECTION
        #
        # An earlier version returned non-estimable here, with sWR and CVwR as
        # None, on the reasoning that a zero would eventually be read as a
        # perfectly reproducible product.
        #
        # That was a regulatory rejection rule invented inside a measurement.
        # Appendix G contains no such rule: it defines a quantity, and for data
        # where every subject's two reference observations agree exactly, that
        # quantity is zero. Refusing to report it means this estimator deciding
        # which datasets are allowed to have an answer.
        #
        # So the arithmetic result is preserved and a DATA_QUALITY diagnostic is
        # attached, because an exact zero really is a strong signal of
        # duplicated rows, over-rounded values or placeholder data. What to DO
        # about that belongs elsewhere: a genuine integrity problem is refused
        # at dataset validation on its own evidence, and the downstream average
        # BE analysis already refuses its own degenerate variance
        # (abe._reject_zero_variance). Two independent checks, each on its own
        # grounds, beats one estimator guessing.
        if variance == 0.0:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.ZERO_REFERENCE_VARIANCE,
                    Severity.DATA_QUALITY,
                    None,
                    "the estimated within-reference variance is exactly zero: "
                    "every contributing subject's two reference measurements "
                    "were identical. The estimate is reported because that is "
                    "what the data give, but exact zero is far more often "
                    "duplicated rows, values rounded until the differences "
                    "vanished, or placeholder data than a perfectly "
                    "reproducible product. Check the dataset before using this "
                    "number",
                    {
                        "sum_of_squares": sum_squares,
                        "degrees_of_freedom": df,
                        "n_subjects": n,
                    },
                )
            )

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
            contributing_sequences=contributing,
        )

    # ------------------------------------------------------------ shared ---

    def _not_estimable(
        self,
        dataset: ReplicateDataset,
        diagnostics: list[Diagnostic],
        n: int,
        m: int,
        df: int,
        contributing_sequences: int,
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
            contributing_sequences=contributing_sequences,
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
        contributing_sequences: int,
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
            regulatory_m=m,
            contributing_sequences=contributing_sequences,
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
