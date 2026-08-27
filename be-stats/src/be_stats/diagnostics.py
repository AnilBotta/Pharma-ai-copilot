"""Why a subject did not contribute, said in a form a machine can act on.

A DROPPED SUBJECT IS A FINDING, NOT AN IMPLEMENTATION DETAIL

Complete-case deletion is the quiet failure mode of every replicate analysis.
Twenty-four subjects go in, twenty-two reach the variance estimator, and the
report says twenty-four. Nobody lies; the number is simply never asked for.

So exclusion is a first-class output here. Every subject that does not reach
the estimator produces a `Diagnostic` naming itself and the reason, and the
result carries `subjects_received`, `subjects_used` and `subjects_excluded`
side by side so the three cannot disagree.

CODES, NOT SENTENCES

A free-text reason cannot be counted, filtered, translated, or asserted on. It
also drifts: the same condition acquires three wordings across two releases and
a report that groups by message silently splits them. So the reason is a
`DiagnosticCode`, and the prose is a rendering of it. User-facing text can be
generated from the code later without touching the statistics.

SEVERITY IS ABOUT CONSEQUENCE, NOT TONE

`ADVISORY` changed nothing. `EXCLUSION` removed one subject from the estimate.
`FATAL` stopped the analysis. A reader scanning for what actually happened to
their study should not have to interpret adjectives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DiagnosticCode(StrEnum):
    """The vocabulary. Adding a member is a deliberate act; reusing one is not.

    Two rules keep this useful. A code names a *condition*, never a severity -
    the same condition can exclude a subject in one design and stop the
    analysis in another. And a code is never repurposed: if the meaning changes
    it becomes a new member, because reports and audit trails outlive releases.
    """

    # ------------------------------------------------ structural integrity ---
    #: The same subject has two rows for one period. Which is the real one is
    #: not this package's decision to make.
    DUPLICATE_SUBJECT_PERIOD = "DUPLICATE_SUBJECT_PERIOD"
    #: The treatment on the row is not the treatment the declared sequence
    #: assigns to that period. The file disagrees with itself.
    SEQUENCE_TREATMENT_MISMATCH = "SEQUENCE_TREATMENT_MISMATCH"
    #: A period number outside the range the sequence defines - period 4 of a
    #: three-period design, or period 0.
    PERIOD_OUT_OF_RANGE = "PERIOD_OUT_OF_RANGE"
    #: A subject has no row at all for one of the design's periods.
    MISSING_PERIOD = "MISSING_PERIOD"
    #: A treatment label that is neither T nor R.
    UNKNOWN_TREATMENT = "UNKNOWN_TREATMENT"
    #: A sequence label the supported designs do not contain.
    UNKNOWN_SEQUENCE = "UNKNOWN_SEQUENCE"

    # ---------------------------------------------------- completeness ---
    #: The subject is missing one of its two reference measurements, so no
    #: within-subject reference difference exists for it.
    MISSING_REFERENCE_REPLICATE = "MISSING_REFERENCE_REPLICATE"
    #: The subject has its references but no test measurement. It can still
    #: contribute to sWR; it cannot contribute to the treatment contrast.
    MISSING_TEST_OBSERVATION = "MISSING_TEST_OBSERVATION"

    # --------------------------------------------------------- values ---
    #: Zero or negative PK value. There is no logarithm, and substituting a
    #: small number invents data.
    NON_POSITIVE_PK_VALUE = "NON_POSITIVE_PK_VALUE"

    # -------------------------------------------------------- estimation ---
    #: Fewer residual degrees of freedom than the estimator needs.
    INSUFFICIENT_REFERENCE_DF = "INSUFFICIENT_REFERENCE_DF"
    #: The estimated reference variance is exactly zero. A legitimate
    #: arithmetic result, and a strong signal that the reference observations
    #: are duplicated, over-rounded or otherwise suspect. It does NOT make the
    #: estimate non-estimable: Appendix G contains no such rule, and inventing
    #: one here would put a regulatory rejection inside a measurement.
    ZERO_REFERENCE_VARIANCE = "ZERO_REFERENCE_VARIANCE"
    #: A sequence the FDA design requires contributed no usable subject. The
    #: study is then not the design Appendix G specifies, and `m` may not be
    #: quietly reduced to fit what is left.
    REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS = (
        "REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS"
    )
    #: Fewer residual degrees of freedom than the treatment contrast needs.
    #: Distinct from INSUFFICIENT_REFERENCE_DF: the two models are fitted on
    #: different subject sets and can fail independently.
    INSUFFICIENT_CONTRAST_DF = "INSUFFICIENT_CONTRAST_DF"
    #: The residual variance of Iij is exactly zero, so the interval has zero
    #: width. Reported, not refused - the same reasoning as
    #: ZERO_REFERENCE_VARIANCE.
    ZERO_CONTRAST_VARIANCE = "ZERO_CONTRAST_VARIANCE"
    #: The model could not be fitted - a singular covariance structure, or a
    #: negative variance component that is not attributable to rounding.
    SINGULAR_MODEL = "SINGULAR_MODEL"

    # ------------------------------------------------------------ design ---
    #: The sequences present do not form one of the supported FDA designs.
    UNSUPPORTED_REPLICATE_DESIGN = "UNSUPPORTED_REPLICATE_DESIGN"
    #: The design is supported and its estimator is not written yet. Distinct
    #: from UNSUPPORTED: the data are fine, the engine is not finished.
    ESTIMATOR_NOT_IMPLEMENTED = "ESTIMATOR_NOT_IMPLEMENTED"
    #: The endpoint routed to ordinary average BE, and FDA's Appendix C mixed
    #: model for replicate crossover studies is not implemented. The endpoint
    #: is NOT decided - deliberately, rather than being decided by a different
    #: model that would look the same.
    REPLICATE_ABE_MODEL_NOT_IMPLEMENTED = "REPLICATE_ABE_MODEL_NOT_IMPLEMENTED"

    # ------------------------------------ narrow therapeutic index drugs ---
    #: An NTI drug was submitted on a design FDA does not accept for it. NTI
    #: requires a fully replicate crossover; nothing else reaches the criteria.
    NTI_REQUIRES_FULLY_REPLICATE_DESIGN = "NTI_REQUIRES_FULLY_REPLICATE_DESIGN"
    #: sWR is exactly zero, so sigma_WT / sigma_WR has no value. Not infinity,
    #: and not a pass.
    REFERENCE_SD_ZERO_VARIANCE_RATIO_UNDEFINED = (
        "REFERENCE_SD_ZERO_VARIANCE_RATIO_UNDEFINED"
    )
    #: No subject contributed two test measurements, so sWT cannot be
    #: estimated and the variability comparison has no numerator.
    MISSING_TEST_REPLICATE = "MISSING_TEST_REPLICATE"
    #: Fewer than one degree of freedom for the within-test variance.
    INSUFFICIENT_TEST_DF = "INSUFFICIENT_TEST_DF"


class Severity(StrEnum):
    """What the condition actually did to the analysis."""

    #: Recorded, changed nothing.
    ADVISORY = "advisory"
    #: The number is arithmetically sound and the DATA behind it are suspect.
    #: Nothing was excluded and nothing was refused - this is the engine saying
    #: "I computed what you asked; look at your dataset before using it".
    #: Separate from ADVISORY because a reader scanning for problems must not
    #: have to weigh adjectives, and separate from FATAL because refusing here
    #: would be a rule the guidance does not contain.
    DATA_QUALITY = "data_quality"
    #: One subject did not reach the estimator.
    EXCLUSION = "exclusion"
    #: The analysis did not produce an estimate.
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One recorded finding, attributable to a subject where there is one."""

    code: DiagnosticCode
    severity: Severity
    #: The subject this concerns, or None for a study-level finding.
    subject: str | None = None
    #: Human-readable elaboration. Never the primary carrier of meaning - the
    #: code is. Safe to change wording without breaking a caller.
    detail: str = ""
    #: Structured particulars: period numbers, observed and expected values.
    #: Keeps specifics out of the prose so they stay machine-readable.
    context: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        who = f"subject {self.subject}: " if self.subject else ""
        return f"[{self.severity}] {self.code} — {who}{self.detail}".rstrip(" —")


def counts_by_code(diagnostics: list[Diagnostic]) -> dict[DiagnosticCode, int]:
    """How many times each condition fired.

    The shape a report wants: "3 subjects excluded, all
    MISSING_REFERENCE_REPLICATE" is a different study from "3 excluded for
    three different reasons", and free text cannot tell you which you have.
    """
    counts: dict[DiagnosticCode, int] = {}
    for d in diagnostics:
        counts[d.code] = counts.get(d.code, 0) + 1
    return counts


def subjects_with(
    diagnostics: list[Diagnostic], severity: Severity
) -> list[str]:
    """Distinct subjects touched by diagnostics of this severity, in order."""
    seen: list[str] = []
    for d in diagnostics:
        if d.severity is severity and d.subject is not None and d.subject not in seen:
            seen.append(d.subject)
    return seen
