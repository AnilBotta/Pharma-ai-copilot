"""Compare a SAS result with the engine's, and report - never conclude.

WHAT THIS MODULE REFUSES TO DO

It does not decide that a method is validated. It does not decide that an
oracle is closed. It does not treat SAS output as truth and the engine as the
thing under test, nor the reverse. It produces a comparison a statistician
reads, and every path out of here that could change a regulatory status runs
through a human.

That restraint is the requirement, not a stylistic preference:
`test_no_automatic_promotion.py` asserts that nothing in this package can move
a validation status, and `ComparisonReport` deliberately has no field that
could be mistaken for a verdict on one.

WHY AGREEMENT IS REPORTED PER QUANTITY

A single overall MATCH/MISMATCH would hide the case that matters most here. On
EMA Data set II the estimate and the standard error are expected to agree
between every implementation tried, and the denominator df is the entire open
question. Collapsing those into one boolean would let a df disagreement hide
behind two agreements, or an estimate disagreement - which would be far more
serious - be reported with the same word.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from app.sas_validation.ingest import ParsedSASResult
from app.sas_validation.modes import SASValidationRunStatus
from app.sas_validation.targets import ReferenceValue, ValidationTarget


class QuantityAgreement(StrEnum):
    AGREES = "agrees"
    DIFFERS = "differs"
    #: One side did not report it. Common and not a failure: EMA published no
    #: standard error, and that is why this whole exercise exists.
    NOT_COMPARABLE = "not_comparable"


#: Relative tolerances, per quantity, with the reason each was chosen.
#:
#: These are COMPARISON tolerances for a report a human reads, not acceptance
#: criteria for a regulatory decision. They are set where a difference stops
#: being attributable to floating-point and optimiser noise and starts being
#: something to look at.
TOLERANCES: dict[str, tuple[float, str]] = {
    "estimate_log": (
        1e-6,
        "The fixed-effect estimate is a GLS solution and barely depends on the "
        "covariance fit. Implementations that agree at all agree here to many "
        "digits; 1e-6 is loose enough for optimiser noise and tight enough "
        "that a real difference cannot hide.",
    ),
    "standard_error": (
        1e-4,
        "Depends on the fitted covariance, so it carries the optimiser's "
        "convergence tolerance. Four independent fits of EMA Data set II agree "
        "on it to seven significant figures, so 1e-4 is undemanding.",
    ),
    "denominator_df": (
        1e-3,
        "The open question. A relative tolerance rather than an absolute one, "
        "because the same absolute difference means very different things at "
        "20 df and at 208. At 1e-3 the two candidate answers for the partial "
        "replicate - about 19.89 and about 22.54 - are unambiguously "
        "different, which is the discrimination this comparison must have.",
    ),
}


@dataclass(frozen=True, slots=True)
class QuantityComparison:
    quantity: str
    sas_value: float | None
    engine_value: float | None
    agreement: QuantityAgreement
    relative_difference: float | None
    tolerance: float | None
    tolerance_basis: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """Everything a reviewer needs, and no verdict on anything regulatory."""

    case_id: str
    package_id: str
    dataset_hash_matched: bool
    program_hash_matched: bool
    sas_version: str | None
    convergence_status: str | None
    quantities: tuple[QuantityComparison, ...]
    reference_context: tuple[ReferenceValue, ...]
    reviewer_question: str
    status: SASValidationRunStatus
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def any_differs(self) -> bool:
        return any(q.agreement is QuantityAgreement.DIFFERS for q in self.quantities)

    def quantity(self, name: str) -> QuantityComparison | None:
        for candidate in self.quantities:
            if candidate.quantity == name:
                return candidate
        return None


def _compare_one(
    quantity: str, sas_value: float | None, engine_value: float | None
) -> QuantityComparison:
    tolerance, basis = TOLERANCES.get(quantity, (1e-6, "default"))

    if sas_value is None or engine_value is None:
        return QuantityComparison(
            quantity=quantity,
            sas_value=sas_value,
            engine_value=engine_value,
            agreement=QuantityAgreement.NOT_COMPARABLE,
            relative_difference=None,
            tolerance=tolerance,
            tolerance_basis=basis,
            note=(
                "not reported by SAS" if sas_value is None
                else "not produced by the engine for this design"
            ),
        )

    scale = max(abs(engine_value), 1e-12)
    relative = abs(sas_value - engine_value) / scale
    agrees = relative <= tolerance
    return QuantityComparison(
        quantity=quantity,
        sas_value=sas_value,
        engine_value=engine_value,
        agreement=QuantityAgreement.AGREES if agrees else QuantityAgreement.DIFFERS,
        relative_difference=relative,
        tolerance=tolerance,
        tolerance_basis=basis,
    )


def compare(
    *,
    target: ValidationTarget,
    package_id: str,
    parsed: ParsedSASResult,
    engine_result: dict[str, float | None] | None,
    dataset_hash_matched: bool,
    program_hash_matched: bool,
) -> ComparisonReport:
    """Build the report.

    `engine_result` is optional and is None exactly when be-stats declines to
    compute the case - which is the situation for the partial replicate today,
    since that capability is NOT_IMPLEMENTED. The report is still worth having:
    it records what SAS produced, beside the published and unconfirmed
    reference values, which is the evidence a reviewer needs even when there is
    nothing of ours to compare it with.
    """
    engine = engine_result or {}
    notes: list[str] = []

    if engine_result is None:
        notes.append(
            "The engine does not compute this case: the capability is "
            "NOT_IMPLEMENTED and deliberately refuses rather than producing an "
            "unvalidated number. The SAS result is recorded as external "
            "evidence with nothing of ours to compare against."
        )

    quantities = tuple(
        _compare_one(name, sas_value, engine.get(name))
        for name, sas_value in (
            ("estimate_log", parsed.estimate_log),
            ("standard_error", parsed.standard_error),
            ("denominator_df", parsed.denominator_df),
        )
    )

    if not (dataset_hash_matched and program_hash_matched):
        status = SASValidationRunStatus.HASH_MISMATCH
        notes.append(
            "Hashes do not match the generated package, so this output is not "
            "evidence about the question that was asked."
        )
    elif parsed.converged is False:
        status = SASValidationRunStatus.REVIEW_REQUIRED
        notes.append("SAS reported a non-converged fit.")
    elif any(q.agreement is QuantityAgreement.DIFFERS for q in quantities):
        status = SASValidationRunStatus.MISMATCH
    elif all(q.agreement is QuantityAgreement.NOT_COMPARABLE for q in quantities):
        status = SASValidationRunStatus.REVIEW_REQUIRED
        notes.append(
            "Nothing could be compared numerically. A reviewer must read the "
            "SAS output against the published reference values directly."
        )
    else:
        status = SASValidationRunStatus.MATCH

    notes.append(
        "This report does not change any method's validation status. A "
        "reviewer records an explicit decision, and only a later statistical "
        "implementation PR may act on it."
    )

    if parsed.problems:
        notes.extend(parsed.problems)

    return ComparisonReport(
        case_id=target.case_id,
        package_id=package_id,
        dataset_hash_matched=dataset_hash_matched,
        program_hash_matched=program_hash_matched,
        sas_version=parsed.sas_version,
        convergence_status=parsed.convergence_status,
        quantities=quantities,
        reference_context=target.references,
        reviewer_question=target.reviewer_question,
        status=status,
        notes=tuple(notes),
    )


def render_report(report: ComparisonReport) -> str:
    """A plain-text rendering, because a reviewer should not need the UI."""
    lines = [
        f"SAS validation comparison - {report.case_id}",
        f"package {report.package_id[:16]}...",
        "",
        f"  dataset hash matched : {report.dataset_hash_matched}",
        f"  program hash matched : {report.program_hash_matched}",
        f"  SAS version          : {report.sas_version or 'not reported'}",
        f"  convergence status   : {report.convergence_status or 'not reported'}",
        f"  comparison status    : {report.status.value.upper()}",
        "",
        f"  {'quantity':<18}{'SAS':>18}{'engine':>18}{'rel diff':>12}  agreement",
    ]
    for q in report.quantities:
        sas = "-" if q.sas_value is None else f"{q.sas_value:.8g}"
        engine = "-" if q.engine_value is None else f"{q.engine_value:.8g}"
        diff = "-" if q.relative_difference is None else f"{q.relative_difference:.2e}"
        lines.append(
            f"  {q.quantity:<18}{sas:>18}{engine:>18}{diff:>12}  {q.agreement.value}"
        )

    lines += ["", "  reference context (not targets to match):"]
    for reference in report.reference_context:
        shown = "not published" if reference.value is None else f"{reference.value}"
        lines.append(
            f"    {reference.quantity:<20} {shown:>14}   "
            f"[{reference.status.value}]"
        )

    lines += ["", "  reviewer question:", "    " + report.reviewer_question, ""]
    for note in report.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines) + "\n"


def _unused_guard() -> None:  # pragma: no cover
    """`math` is imported for the ratio helpers on ParsedSASResult."""
    _ = math


__all__ = [
    "TOLERANCES",
    "ComparisonReport",
    "QuantityAgreement",
    "QuantityComparison",
    "compare",
    "render_report",
]
