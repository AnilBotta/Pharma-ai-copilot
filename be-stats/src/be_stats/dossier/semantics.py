"""`passes`, `decided` and `validation_status` are three answers, not one.

THE COLLAPSE THIS FORBIDS

    passes = False   because the method is not implemented

That single line is the most dangerous thing this package could do. A reader -
a person, a report generator, a downstream system - sees `False` beside a
bioequivalence endpoint and concludes the study FAILED. It did not. Nothing was
computed. The regulator's criterion was never evaluated against these data, and
"we did not run the test" and "the product is not bioequivalent" are opposite
conclusions with identical spelling.

So three fields, and each answers exactly one question:

    decided             was a regulatory criterion evaluated at all?
    passes              if it was, which way? None when it was not.
    validation_status   may anybody rely on the answer for a filing?

The third is orthogonal to the first two. An IMPLEMENTED_UNVALIDATED method
DECIDES, and correctly - it just cannot be filed on without stating what it is.
Conflating the third with the first would make an unvalidated method silently
refuse, which loses a result the caller is entitled to see, labelled.

WHAT THIS MODULE PROVIDES

`assert_result_semantics` checks the invariant on any object carrying the two
fields. It is used by `tests/unit/test_dossier_semantics.py` across every
result type in the package, so a new result model cannot be added with a
`passes` that lies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DecidableResult(Protocol):
    """Anything that reports a regulatory decision or the absence of one."""

    decided: bool
    passes: bool | None


@dataclass(frozen=True, slots=True)
class SemanticsViolation:
    """One way a result model lied about what it knew."""

    what: str
    detail: str

    def __str__(self) -> str:
        return f"{self.what}: {self.detail}"


def check_result_semantics(result: Any, label: str = "result") -> list[SemanticsViolation]:
    """Every way this object breaks the three-field contract.

    Returns violations rather than raising, so a test can report all of them
    at once. A caller that wants an exception uses `assert_result_semantics`.
    """
    violations: list[SemanticsViolation] = []

    if not hasattr(result, "decided") or not hasattr(result, "passes"):
        violations.append(
            SemanticsViolation(
                label,
                "carries no decided/passes pair, so it cannot express "
                "'no decision' at all. Any boolean it does carry will be read "
                "as a verdict.",
            )
        )
        return violations

    decided = result.decided
    passes = result.passes

    if not isinstance(decided, bool):
        violations.append(
            SemanticsViolation(label, f"decided is {type(decided).__name__}, not bool")
        )

    if decided and passes is None:
        violations.append(
            SemanticsViolation(
                label,
                "decided=True with passes=None. If a criterion was evaluated "
                "it has an answer; if it was not, decided must be False.",
            )
        )

    if not decided and passes is not None:
        violations.append(
            SemanticsViolation(
                label,
                f"decided=False with passes={passes!r}. THIS IS THE DANGEROUS "
                "ONE: no criterion was evaluated, so passes must be None. A "
                "False here reads as a failed study.",
            )
        )

    return violations


def assert_result_semantics(result: Any, label: str = "result") -> None:
    """Raise if the three-field contract is broken."""
    violations = check_result_semantics(result, label)
    if violations:
        raise AssertionError(
            "Result semantics violated:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


#: The contract in one place, for a report or a docstring that needs to quote
#: it rather than paraphrase it.
CONTRACT = (
    "decided says whether a regulatory criterion was evaluated. passes says "
    "which way it went, and is null whenever decided is false - never false. "
    "validation_status is orthogonal to both: it says whether the answer may "
    "be relied on for a filing, and an unvalidated method still decides."
)
