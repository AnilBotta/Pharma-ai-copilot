"""Study data, and the checks that run before any arithmetic does.

Bad input is the likeliest source of a wrong bioequivalence verdict, and it is
the cheapest to catch. A subject with one period missing, a sequence label that
is not one of the two, a zero concentration that cannot be logged - each of
these produces a number if you let it, and the number is wrong in a way nobody
sees.

So the data classes refuse rather than coerce. Nothing here silently drops a
subject: an incomplete subject is either excluded by an explicit, recorded
decision or it stops the analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Treatment(StrEnum):
    TEST = "T"
    REFERENCE = "R"


class Sequence(StrEnum):
    """The two sequences of a 2x2 crossover, named by period order."""

    RT = "RT"
    TR = "TR"


class DataError(ValueError):
    """The data cannot support the analysis that was asked for."""


@dataclass(frozen=True, slots=True)
class CrossoverObservation:
    """One subject's pair of measurements in a 2x2 crossover."""

    subject: str
    sequence: Sequence
    #: The measured value in period 1, on the original (not log) scale.
    period_1: float
    #: The measured value in period 2, on the original scale.
    period_2: float

    def __post_init__(self) -> None:
        for period, value in ((1, self.period_1), (2, self.period_2)):
            if value is None:
                raise DataError(
                    f"Subject {self.subject} has no value for period {period}. "
                    "An incomplete subject must be excluded deliberately, not "
                    "carried into the analysis as a gap."
                )
            if value <= 0:
                raise DataError(
                    f"Subject {self.subject}, period {period}: value {value} is "
                    "not positive. Bioequivalence is assessed on the log scale, "
                    "so a zero or negative measurement has no logarithm and "
                    "cannot be analysed. Investigate the record rather than "
                    "substituting a small number."
                )

    def value_for(self, treatment: Treatment) -> float:
        """The measurement this subject contributed for one treatment."""
        first, second = (
            (Treatment.REFERENCE, Treatment.TEST)
            if self.sequence is Sequence.RT
            else (Treatment.TEST, Treatment.REFERENCE)
        )
        return self.period_1 if treatment is first else self.period_2


@dataclass(frozen=True, slots=True)
class CrossoverStudy:
    """A complete 2x2 crossover dataset for one endpoint."""

    #: What was measured. Carried through to the report so a result cannot be
    #: read as applying to an endpoint it was not computed for.
    endpoint: str
    observations: list[CrossoverObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.observations) < 3:
            raise DataError(
                f"{len(self.observations)} subjects is too few to estimate a "
                "within-subject variance and a treatment difference. At least "
                "3 are needed for one residual degree of freedom, and far more "
                "for a study anyone would file."
            )
        seen: set[str] = set()
        for obs in self.observations:
            if obs.subject in seen:
                raise DataError(
                    f"Subject {obs.subject} appears more than once. In a 2x2 "
                    "crossover each subject contributes exactly one row."
                )
            seen.add(obs.subject)

        for sequence in Sequence:
            if not any(o.sequence is sequence for o in self.observations):
                raise DataError(
                    f"No subject was assigned to sequence {sequence}. Both "
                    "sequences are required: the treatment effect is estimated "
                    "from the difference between them, and with one sequence it "
                    "is completely confounded with the period effect."
                )

    def by_sequence(self, sequence: Sequence) -> list[CrossoverObservation]:
        return [o for o in self.observations if o.sequence is sequence]


@dataclass(frozen=True, slots=True)
class ParallelStudy:
    """Two independent groups, one endpoint."""

    endpoint: str
    test: list[float] = field(default_factory=list)
    reference: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name, values in (("test", self.test), ("reference", self.reference)):
            if len(values) < 2:
                raise DataError(
                    f"The {name} group has {len(values)} subjects. At least 2 "
                    "per group are needed to estimate a variance."
                )
            for value in values:
                if value is None or value <= 0:
                    raise DataError(
                        f"The {name} group contains a non-positive value "
                        f"({value}). Bioequivalence is assessed on the log "
                        "scale, so it has no logarithm."
                    )
