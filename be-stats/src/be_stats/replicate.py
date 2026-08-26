"""Replicate designs: what the data must be before anything is estimated.

THE FILE MUST AGREE WITH ITSELF

A replicate bioequivalence dataset carries the same fact twice. The sequence
label says what the subject was meant to receive in each period, and the
treatment column says what the row records. When those disagree, one of them is
wrong, and no arithmetic downstream can tell you which.

So the sequence and the period *define* the expected treatment, and a row that
contradicts them is rejected. Nothing here infers structure from row order:
not the sequence, not the period, and above all not which reference
measurement is R1 and which is R2. Sorting a CSV differently must not change a
variance.

WHY THE DESIGNS ARE ENUMERATED AND NOT PARSED

It is tempting to accept any string of Ts and Rs and work out the rest. That
would accept `TRT`, `TRRR`, and `RRTR` - structures FDA's appendix does not
describe, whose estimators are not the ones implemented here, and for which a
plausible number is worse than a refusal. The supported designs are listed, and
anything else raises `UnsupportedDesign` by name.

WHAT THIS MODULE DELIBERATELY DOES NOT DO

It does not decide bioequivalence, and it does not decide *which test* decides
bioequivalence. It produces the quantities an FDA highly-variable analysis is
built from - the reference differences, the treatment contrasts - and stops.
The switching rule at sWR = 0.294 exists in `spec.py` and is not consulted
here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.study import DataError, Treatment


class ReplicateSequence(StrEnum):
    """The supported sequences, named by their period order.

    The name IS the specification: `TRR` means period 1 test, period 2
    reference, period 3 reference. `expected_treatment` reads it directly
    rather than consulting a table that could drift from the name.
    """

    TRR = "TRR"
    RTR = "RTR"
    RRT = "RRT"
    TRTR = "TRTR"
    RTRT = "RTRT"

    @property
    def periods(self) -> int:
        return len(self.value)

    def expected_treatment(self, period: int) -> Treatment:
        """What this sequence assigns to this period.

        The single source of truth for design validation, reference-pair
        construction and period completeness.
        """
        if not 1 <= period <= self.periods:
            raise ValueError(
                f"Sequence {self.value} has {self.periods} periods; period "
                f"{period} is outside it."
            )
        return Treatment(self.value[period - 1])

    def reference_periods(self) -> tuple[int, ...]:
        """The periods carrying reference, in ascending period order.

        This ordering defines R1 and R2. It comes from the design, never from
        the order rows happen to appear in a file - which is the whole reason
        this method exists rather than a `sorted()` at the call site.
        """
        return tuple(
            p for p in range(1, self.periods + 1)
            if self.expected_treatment(p) is Treatment.REFERENCE
        )

    def test_periods(self) -> tuple[int, ...]:
        return tuple(
            p for p in range(1, self.periods + 1)
            if self.expected_treatment(p) is Treatment.TEST
        )


class ReplicateDesign(StrEnum):
    """Two designs, two estimators, one architectural boundary.

    FDA's appendix analyses these differently - the partial replicate through
    the general linear model example, the fully replicated through a mixed
    model. Collapsing them because both give each subject two reference
    measurements would make the partial-replicate formula stand in for a model
    it is not, which is the class of substitution this package exists to
    refuse.
    """

    PARTIAL_REPLICATE = "partial_replicate"
    FULLY_REPLICATE = "fully_replicate"

    @property
    def sequences(self) -> frozenset[ReplicateSequence]:
        return _DESIGN_SEQUENCES[self]

    @property
    def regulatory_sequence_count(self) -> int:
        """`m` in the FDA variance formula. A property of the DESIGN.

        Appendix G names it outright - "m = 3 for partially replicate design:
        TRR, RTR, and RRT; m = 2 for fully replicate design: TRTR and RTRT" -
        so it is not the number of sequence buckets that still hold subjects
        after exclusions.

        The distinction has teeth. If one sequence of a three-sequence design
        contributes nobody, counting `m = 2` would produce an sWR from a design
        FDA does not describe, on degrees of freedom that belong to a different
        study. The estimator refuses instead; see
        `REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS`.
        """
        return len(self.sequences)


_DESIGN_SEQUENCES: dict[ReplicateDesign, frozenset[ReplicateSequence]] = {
    ReplicateDesign.PARTIAL_REPLICATE: frozenset(
        {ReplicateSequence.TRR, ReplicateSequence.RTR, ReplicateSequence.RRT}
    ),
    ReplicateDesign.FULLY_REPLICATE: frozenset(
        {ReplicateSequence.TRTR, ReplicateSequence.RTRT}
    ),
}


class UnsupportedDesign(DataError):
    """The sequences present are not one of the designs this version supports.

    A subclass of `DataError` because it is a statement about the data, and a
    named type because a caller should be able to distinguish "this study is
    shaped in a way we do not handle" from "this study has a bad row".

    Carries a `code` for the same reason exclusions do: a caller that groups
    failures should not have to match on prose.
    """

    def __init__(
        self,
        message: str,
        code: DiagnosticCode = DiagnosticCode.UNSUPPORTED_REPLICATE_DESIGN,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReplicateObservation:
    """One measurement: one subject, one period, one treatment, one endpoint.

    `value` is the original positive PK quantity - a concentration, an AUC, a
    Cmax. It is never a logarithm. The engine takes the logarithm itself,
    exactly once, so a caller cannot pass a pre-logged value through the same
    field and have it silently treated as raw. A pre-logged Cmax is usually a
    small positive number and would pass every validation here while producing
    a variance an order of magnitude wrong.
    """

    subject_id: str
    sequence: ReplicateSequence
    period: int
    treatment: Treatment
    endpoint: str
    value: float

    @property
    def log_value(self) -> float:
        return math.log(self.value)


@dataclass(frozen=True, slots=True)
class SubjectRecord:
    """One subject's usable measurements, arranged by the design.

    Reference values are in ascending PERIOD order, so `reference_values[0]` is
    R1 and `reference_values[1]` is R2 by definition of the sequence rather
    than by accident of input order.
    """

    subject_id: str
    sequence: ReplicateSequence
    #: Log-scale test values, in ascending period order.
    log_test: tuple[float, ...]
    #: Log-scale reference values, in ascending period order.
    log_reference: tuple[float, ...]

    @property
    def has_reference_pair(self) -> bool:
        return len(self.log_reference) >= 2

    @property
    def has_test(self) -> bool:
        return len(self.log_test) >= 1

    def reference_difference(self) -> float:
        """`Dij = Rij1 - Rij2` on the log scale, per FDA Appendix G.

        R1 minus R2 in period order. The sign convention matters only in that
        it must be consistent: the estimator squares deviations from a sequence
        mean, so a systematically flipped sign would leave sWR unchanged - but
        a sign that flips *per subject*, which is what row-order dependence
        produces, would not.
        """
        if not self.has_reference_pair:
            raise DataError(
                f"Subject {self.subject_id} has {len(self.log_reference)} "
                "reference measurement(s); a within-subject reference "
                "difference needs two."
            )
        return self.log_reference[0] - self.log_reference[1]

    def treatment_contrast(self) -> float:
        """`Iij = Tij - (Rij1 + Rij2)/2`, generalised to the mean of each.

        For the partial replicate this is exactly the appendix's expression,
        since there is one test measurement. For a fully replicated design it
        is the mean test minus the mean reference, which is the same contrast
        with the same interpretation.

        Computed here because PR #56 needs it; nothing in this release consumes
        it, and it is exposed so it can be checked before it is relied on.
        """
        if not self.has_test:
            raise DataError(
                f"Subject {self.subject_id} has no test measurement, so no "
                "treatment contrast exists for it."
            )
        if not self.log_reference:
            raise DataError(
                f"Subject {self.subject_id} has no reference measurement."
            )
        # `fsum` for the same reason the estimator uses it: a quantity that
        # depends on summation order is a quantity two runs can disagree about.
        mean_t = math.fsum(self.log_test) / len(self.log_test)
        mean_r = math.fsum(self.log_reference) / len(self.log_reference)
        return mean_t - mean_r


def identify_design(
    sequences: set[ReplicateSequence] | frozenset[ReplicateSequence],
) -> ReplicateDesign:
    """Which supported design these sequences belong to.

    Requires every sequence present to belong to one design. A file mixing
    `TRR` with `TRTR` is not a design with five sequences; it is two studies in
    one file, or a labelling error.
    """
    if not sequences:
        raise UnsupportedDesign(
            "No sequences present, so there is no design to identify."
        )
    for design, members in _DESIGN_SEQUENCES.items():
        if set(sequences) <= set(members):
            return design
    present = ", ".join(sorted(s.value for s in sequences))
    raise UnsupportedDesign(
        f"The sequences present ({present}) do not form a supported design. "
        "This version supports the partial replicate (TRR / RTR / RRT) and the "
        "fully replicated design (TRTR / RTRT), and refuses anything else "
        "rather than guessing an estimator for it."
    )


def parse_sequence(label: str) -> ReplicateSequence:
    """A sequence label, or a refusal that names what is supported.

    Separate from `ReplicateSequence(label)` so the error explains itself: a
    bare `ValueError: 'TRT' is not a valid ReplicateSequence` tells a user
    nothing about which designs exist.
    """
    try:
        return ReplicateSequence(label)
    except ValueError:
        pass

    supported = ", ".join(s.value for s in ReplicateSequence)

    # A sequence can be a perfectly real replicate design and still be useless
    # for THIS quantity, and saying only "unsupported" would send someone
    # looking for a bug in their file. The guidance's own TRR/RTT design is the
    # case in point: RTT replicates the TEST, so a subject in that sequence has
    # one reference observation and no within-reference difference at all.
    if label.count("R") < 2 and set(label) <= {"T", "R"} and label:
        raise UnsupportedDesign(
            f"{label!r} contains {label.count('R')} reference period(s). sWR is "
            "estimated from the difference between a subject's TWO reference "
            "observations, so a sequence that replicates the test rather than "
            "the reference contributes nothing to it - this is a statement "
            "about the design, not about your data. FDA's own TRR/RTT design "
            "(Appendix A) is of this kind: it is a replicate design, and it is "
            "not one of the reference-scaled designs. Reference-scaled "
            f"designs: {supported}.",
            DiagnosticCode.UNSUPPORTED_REPLICATE_DESIGN,
        ) from None

    raise UnsupportedDesign(
        f"{label!r} is not a supported replicate sequence. Supported: "
        f"{supported}. Sequences outside this list are refused rather than "
        "parsed, because their estimators are not the ones implemented here.",
        DiagnosticCode.UNKNOWN_SEQUENCE,
    ) from None


def parse_treatment(label: str) -> Treatment:
    """A treatment label, or a refusal.

    The ingestion boundary. `Treatment` is a closed enum, so a bad label
    already fails - but with `ValueError: 'X' is not a valid Treatment`, which
    tells a user reading a rejected CSV nothing. This raises the package's own
    error type with the package's own diagnostic code.
    """
    try:
        return Treatment(label)
    except ValueError:
        error = DataError(
            f"{label!r} is not a treatment. A replicate bioequivalence dataset "
            "has exactly two: T (test) and R (reference). A third label means "
            "the column holds something else - a formulation code, or a "
            "period - and mapping it here would be a guess."
        )
        error.code = DiagnosticCode.UNKNOWN_TREATMENT  # type: ignore[attr-defined]
        raise error from None


@dataclass(frozen=True, slots=True)
class ReplicateDataset:
    """A validated replicate dataset, and the record of what was dropped.

    Construct with `ReplicateDataset.build(...)`, which performs the
    validation and returns a dataset whose `records` are exactly the subjects
    that survived it. `diagnostics` explains every subject that did not.

    STUDY-LEVEL FAILURES RAISE; SUBJECT-LEVEL FAILURES EXCLUDE

    An unsupported design, a file spanning two endpoints, or a study with no
    usable subject left is a statement about the whole dataset, and continuing
    would produce an estimate of something nobody asked for. A bad row for one
    subject is a statement about that subject: it is excluded, loudly, and the
    other twenty-three are analysed.

    Neither path repairs anything.
    """

    endpoint: str
    design: ReplicateDesign
    records: tuple[SubjectRecord, ...]
    diagnostics: tuple[Diagnostic, ...]
    #: Every subject id seen in the input, including excluded ones.
    subjects_received: tuple[str, ...]

    @property
    def subjects_excluded(self) -> tuple[str, ...]:
        used = {r.subject_id for r in self.records}
        return tuple(s for s in self.subjects_received if s not in used)

    def by_sequence(self, sequence: ReplicateSequence) -> list[SubjectRecord]:
        return [r for r in self.records if r.sequence is sequence]

    def sequences_present(self) -> tuple[ReplicateSequence, ...]:
        """Design sequences that actually contributed a surviving subject.

        Not the same as the design's sequence list. A sequence whose every
        subject was excluded contributes no deviations and no degrees of
        freedom, and the variance estimator must count what is there rather
        than what was planned.
        """
        present = {r.sequence for r in self.records}
        return tuple(
            s for s in ReplicateSequence if s in present and s in self.design.sequences
        )

    # ------------------------------------------------------------ build ---

    @classmethod
    def build(
        cls, observations: list[ReplicateObservation]
    ) -> ReplicateDataset:
        if not observations:
            raise DataError("No observations were supplied.")

        endpoints = {o.endpoint for o in observations}
        if len(endpoints) != 1:
            raise DataError(
                f"Observations span {len(endpoints)} endpoints "
                f"({', '.join(sorted(endpoints))}). One endpoint per dataset: "
                "a variance computed across AUC and Cmax together is not a "
                "quantity anything can use."
            )
        endpoint = endpoints.pop()

        design = identify_design({o.sequence for o in observations})

        # Order of first appearance, so the report lists subjects the way the
        # file did. Membership is a set; the ORDER is never load-bearing.
        subjects_received: list[str] = []
        grouped: dict[str, list[ReplicateObservation]] = {}
        for obs in observations:
            if obs.subject_id not in grouped:
                grouped[obs.subject_id] = []
                subjects_received.append(obs.subject_id)
            grouped[obs.subject_id].append(obs)

        records: list[SubjectRecord] = []
        diagnostics: list[Diagnostic] = []
        for subject_id in subjects_received:
            record = _validate_subject(
                subject_id, grouped[subject_id], diagnostics
            )
            if record is not None:
                records.append(record)

        if not records:
            raise DataError(
                "No subject survived validation, so there is nothing to "
                "estimate. Diagnostics: "
                + "; ".join(str(d) for d in diagnostics)
            )

        return cls(
            endpoint=endpoint,
            design=design,
            records=tuple(records),
            diagnostics=tuple(diagnostics),
            subjects_received=tuple(subjects_received),
        )


def _validate_subject(
    subject_id: str,
    rows: list[ReplicateObservation],
    diagnostics: list[Diagnostic],
) -> SubjectRecord | None:
    """One subject's rows against the design. Returns None if excluded.

    Every rejection appends a diagnostic first, so an excluded subject can
    never be silent.
    """
    sequences = {r.sequence for r in rows}
    if len(sequences) != 1:
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.SEQUENCE_TREATMENT_MISMATCH,
                Severity.EXCLUSION,
                subject_id,
                "rows disagree about which sequence this subject was assigned "
                "to, so no expected treatment can be derived for any period",
                {"sequences": sorted(s.value for s in sequences)},
            )
        )
        return None
    sequence = sequences.pop()

    by_period: dict[int, ReplicateObservation] = {}
    excluded = False
    for row in rows:
        if not 1 <= row.period <= sequence.periods:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.PERIOD_OUT_OF_RANGE,
                    Severity.EXCLUSION,
                    subject_id,
                    f"period {row.period} is outside the {sequence.periods} "
                    f"periods of sequence {sequence.value}",
                    {"period": row.period, "sequence": sequence.value},
                )
            )
            excluded = True
            continue

        if row.period in by_period:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.DUPLICATE_SUBJECT_PERIOD,
                    Severity.EXCLUSION,
                    subject_id,
                    f"two rows for period {row.period}; which one is the real "
                    "measurement is not this package's decision",
                    {
                        "period": row.period,
                        "values": [by_period[row.period].value, row.value],
                    },
                )
            )
            excluded = True
            continue

        expected = sequence.expected_treatment(row.period)
        if row.treatment is not expected:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.SEQUENCE_TREATMENT_MISMATCH,
                    Severity.EXCLUSION,
                    subject_id,
                    f"period {row.period} of sequence {sequence.value} is "
                    f"{expected}, but the row says {row.treatment}. The file "
                    "disagrees with itself and repairing it would be a guess",
                    {
                        "period": row.period,
                        "expected": str(expected),
                        "observed": str(row.treatment),
                    },
                )
            )
            excluded = True
            continue

        if row.value is None or row.value <= 0:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.NON_POSITIVE_PK_VALUE,
                    Severity.EXCLUSION,
                    subject_id,
                    f"period {row.period} value {row.value} has no logarithm",
                    {"period": row.period, "value": row.value},
                )
            )
            excluded = True
            continue

        by_period[row.period] = row

    if excluded:
        return None

    missing = [p for p in range(1, sequence.periods + 1) if p not in by_period]
    reference_periods = sequence.reference_periods()
    missing_reference = [p for p in missing if p in reference_periods]
    missing_test = [p for p in missing if p in sequence.test_periods()]

    if missing_reference:
        # A subject short of a reference replicate contributes nothing to sWR,
        # which is the only quantity this release estimates.
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.MISSING_REFERENCE_REPLICATE,
                Severity.EXCLUSION,
                subject_id,
                "missing reference measurement at period "
                + ", ".join(str(p) for p in missing_reference)
                + ", so no within-subject reference difference exists",
                {"missing_periods": missing_reference},
            )
        )
        return None

    if missing_test:
        # Recorded, but NOT an exclusion: sWR is estimated from the reference
        # measurements alone, and dropping this subject would discard evidence
        # about reference variability for the sake of a contrast this release
        # does not compute. It becomes an exclusion in PR #56, where the
        # contrast is needed.
        diagnostics.append(
            Diagnostic(
                DiagnosticCode.MISSING_TEST_OBSERVATION,
                Severity.ADVISORY,
                subject_id,
                "missing test measurement at period "
                + ", ".join(str(p) for p in missing_test)
                + "; contributes to reference variability but has no treatment "
                "contrast",
                {"missing_periods": missing_test},
            )
        )

    return SubjectRecord(
        subject_id=subject_id,
        sequence=sequence,
        log_test=tuple(
            by_period[p].log_value for p in sequence.test_periods() if p in by_period
        ),
        log_reference=tuple(
            by_period[p].log_value for p in reference_periods if p in by_period
        ),
    )


def reference_differences(
    dataset: ReplicateDataset,
) -> dict[ReplicateSequence, list[float]]:
    """`Dij` for every surviving subject, grouped by sequence.

    Grouped because the estimator subtracts a *sequence* mean, not a grand
    mean: sequence carries the period effect, and pooling across sequences
    would put that effect into the variance.
    """
    grouped: dict[ReplicateSequence, list[float]] = {}
    for record in dataset.records:
        if record.has_reference_pair:
            grouped.setdefault(record.sequence, []).append(
                record.reference_difference()
            )
    return grouped


def treatment_contrasts(
    dataset: ReplicateDataset,
) -> dict[ReplicateSequence, list[float]]:
    """`Iij` for every subject that has both a test and a reference.

    Exposed, unused, and deliberately so - see `SubjectRecord.treatment_contrast`.
    """
    grouped: dict[ReplicateSequence, list[float]] = {}
    for record in dataset.records:
        if record.has_test and record.log_reference:
            grouped.setdefault(record.sequence, []).append(
                record.treatment_contrast()
            )
    return grouped
