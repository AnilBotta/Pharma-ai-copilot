"""Validate observations before a package exists, and never drop one.

WHY THIS FILE EXISTS

The first version of the generated SAS program contained, in effect:

    if VALUE > 0 then Y = log(VALUE);
    else delete;

which silently removed any non-positive observation from the analysis. The
package's manifest would then claim N observations, the CSV would contain N,
and SAS would fit fewer - with nothing anywhere recording the difference.

For regulatory validation evidence that is not acceptable. The whole point of
hashing the dataset is that the analysis provably ran on the data we shipped;
a program that quietly changes the analysis set defeats the hash without
breaking it.

So validity is established BEFORE a package can exist. Every value must be
present, numeric, finite and strictly positive - because the model is fitted on
log(VALUE), and those are exactly the conditions under which that is defined.
If any observation fails, generation REFUSES with a typed error naming the
offending rows. It does not drop them and continue.

The SAS program keeps a defensive check that ABORTS on invalid data. It should
never fire; if it does, stopping loudly is the only acceptable behaviour.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InvalidObservation:
    """One row that cannot enter the analysis, and why."""

    index: int
    subject: str
    sequence: str
    period: str
    treatment: str
    reason: str
    offending_value: str

    def describe(self) -> str:
        return (
            f"row {self.index}: subject {self.subject}, sequence "
            f"{self.sequence}, period {self.period}, treatment "
            f"{self.treatment} - {self.reason} (value: {self.offending_value})"
        )


class InvalidObservations(ValueError):
    """Generation refused. Carries every failing row, not just the first.

    All of them, because a customer fixing a dataset should not have to
    discover the problems one package at a time.
    """

    def __init__(self, problems: Sequence[InvalidObservation]) -> None:
        self.problems = tuple(problems)
        detail = "\n  ".join(problem.describe() for problem in self.problems)
        super().__init__(
            f"{len(self.problems)} observation(s) cannot be analysed on the log "
            f"scale, so no validation package was generated:\n  {detail}\n"
            "No observation was dropped. Correct the data and generate again."
        )


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def validate_observations(
    observations: Sequence[Mapping[str, object]],
) -> None:
    """Raise `InvalidObservations` unless every row can be analysed.

    Checks, in the order a value fails them:

        present      a missing value has no log
        numeric      a string that is not a number has no log
        finite       inf and NaN propagate through the whole fit
        positive     log is undefined at zero and below

    Structural fields are checked too. A row with no subject cannot be grouped,
    and a package built from one would fit a model on data whose design nobody
    can reconstruct.
    """
    problems: list[InvalidObservation] = []

    for index, row in enumerate(observations):
        subject = _text(row, "subject")
        sequence = _text(row, "sequence")
        period = _text(row, "period")
        treatment = _text(row, "treatment")

        # Bound explicitly rather than captured. The closure is only ever
        # called within its own iteration, so late binding would not bite
        # today - but a helper that silently reports the wrong row is a bad
        # thing to leave one refactor away.
        def fail(
            reason: str,
            raw: object,
            *,
            _index: int = index,
            _subject: str = subject,
            _sequence: str = sequence,
            _period: str = period,
            _treatment: str = treatment,
        ) -> None:
            problems.append(
                InvalidObservation(
                    index=_index,
                    subject=_subject or "(missing)",
                    sequence=_sequence or "(missing)",
                    period=_period or "(missing)",
                    treatment=_treatment or "(missing)",
                    reason=reason,
                    offending_value="(missing)" if raw is None else repr(raw),
                )
            )

        for name, present in (
            ("subject", subject),
            ("sequence", sequence),
            ("period", period),
            ("treatment", treatment),
        ):
            if not present:
                fail(f"{name} is missing", row.get(name))

        if "value" not in row or row.get("value") is None:
            fail("value is missing", None)
            continue

        raw = row["value"]
        if isinstance(raw, bool):
            # bool is a subclass of int; True would otherwise pass as 1.0.
            fail("value is a boolean, not a measurement", raw)
            continue

        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            fail("value is not numeric", raw)
            continue

        if math.isnan(numeric):
            fail("value is NaN", raw)
        elif math.isinf(numeric):
            fail("value is infinite", raw)
        elif numeric <= 0.0:
            fail(
                "value is not strictly positive, and the model is fitted on "
                "log(VALUE)",
                raw,
            )

    if problems:
        raise InvalidObservations(problems)


__all__ = [
    "InvalidObservation",
    "InvalidObservations",
    "validate_observations",
]
