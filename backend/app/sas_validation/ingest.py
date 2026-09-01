"""Parse the one result file our own package tells SAS to write.

ONE SUPPORTED PATH, DOCUMENTED, RATHER THAN BEST-EFFORT SCRAPING

SAS can emit listing text, HTML, RTF, PDF and half a dozen ODS destinations,
and a parser that tries to read all of them reads none of them reliably. Worse,
a scraper that half-works fails by producing a NUMBER rather than an error -
and a wrong denominator df that looks plausible is the exact failure this whole
programme of work exists to prevent.

So the supported path is narrow and ours: `validate.sas` writes a structured
CSV with a fixed section/name/value shape, and this module reads that. A raw
SAS log may be uploaded alongside and is retained as evidence, but it is never
parsed for numbers.

WHY THE HASHES ARE CHECKED BEFORE THE NUMBERS

An upload is evidence about a specific dataset and a specific program. If
either hash fails to match the package, the numbers may be perfectly correct
about something we did not ask - so the result is rejected as HASH_MISMATCH
rather than parsed and compared. Evidence for a different question is not weak
evidence; it is no evidence.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

from app.sas_validation.modes import SASValidationRunStatus

RESULT_SCHEMA_SECTIONS = ("estimate", "covparm", "convergence", "environment")

#: The label PROC MIXED gives the contrast, set by the ESTIMATE statement in
#: the regulator's own text: ESTIMATE 'T vs. R' TRT 1 -1 / CL ALPHA=0.1;
CONTRAST_LABEL = "T vs. R"


@dataclass(frozen=True, slots=True)
class ParsedSASResult:
    """What SAS reported. Not what is true - what SAS reported."""

    estimate_log: float | None = None
    standard_error: float | None = None
    denominator_df: float | None = None
    ci_lower_log: float | None = None
    ci_upper_log: float | None = None
    covariance_parameters: dict[str, float] = field(default_factory=dict)
    convergence_status: str | None = None
    convergence_reason: str | None = None
    sas_version: str | None = None
    run_datetime: str | None = None

    #: Stamped into the output by the generated program, so the result
    #: identifies its own package. PROGRAM-EMITTED evidence - distinct from
    #: anything a person types into a form, and the only kind used to decide
    #: whether an upload belongs to the package it was uploaded against.
    emitted_case_id: str | None = None
    emitted_dataset_sha256: str | None = None

    problems: tuple[str, ...] = ()

    @property
    def estimate_ratio_percent(self) -> float | None:
        if self.estimate_log is None:
            return None
        return 100.0 * math.exp(self.estimate_log)

    @property
    def ci_lower_percent(self) -> float | None:
        if self.ci_lower_log is None:
            return None
        return 100.0 * math.exp(self.ci_lower_log)

    @property
    def ci_upper_percent(self) -> float | None:
        if self.ci_upper_log is None:
            return None
        return 100.0 * math.exp(self.ci_upper_log)

    @property
    def converged(self) -> bool | None:
        """PROC MIXED reports 0 for a converged fit."""
        if self.convergence_status is None:
            return None
        return self.convergence_status.strip() == "0"

    @property
    def is_complete(self) -> bool:
        return None not in (
            self.estimate_log,
            self.standard_error,
            self.denominator_df,
            self.ci_lower_log,
            self.ci_upper_log,
        )


class ResultParseError(ValueError):
    """The uploaded file is not the result file this package asked for."""


def _number(raw: str) -> float | None:
    text = raw.strip()
    if not text or text.upper() in (".", "NA", "NAN", "NULL"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return None if math.isnan(value) else value


def parse_result_csv(content: str) -> ParsedSASResult:
    """Read the structured result file. Strict about shape, lenient about extras."""
    try:
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
    except csv.Error as error:  # pragma: no cover - malformed beyond csv's tolerance
        raise ResultParseError(f"not readable as CSV: {error}") from error

    if not rows:
        raise ResultParseError("the result file is empty")

    columns = {name.strip().lower() for name in (rows[0].keys() or set()) if name}
    if not {"section", "name", "value"} <= columns:
        raise ResultParseError(
            "expected columns section, name, value - got "
            f"{sorted(columns)}. This does not look like the result file "
            "validate.sas writes; a SAS log or listing cannot be parsed."
        )

    estimate = standard_error = df = lower = upper = None
    covariance: dict[str, float] = {}
    convergence_status = convergence_reason = None
    sas_version = run_datetime = None
    emitted_case_id = emitted_dataset_sha256 = None
    problems: list[str] = []

    for row in rows:
        section = (row.get("section") or "").strip().lower()
        name = (row.get("name") or "").strip()
        value = (row.get("value") or "").strip()

        if section == "estimate":
            if name != CONTRAST_LABEL:
                problems.append(
                    f"ignored estimate row labelled {name!r}; the package's "
                    f"program labels the contrast {CONTRAST_LABEL!r}"
                )
                continue
            parts = value.split("|")
            if len(parts) != 5:
                problems.append(
                    f"estimate row has {len(parts)} fields, expected 5 "
                    "(estimate|stderr|df|lower|upper)"
                )
                continue
            estimate, standard_error, df, lower, upper = (_number(p) for p in parts)

        elif section == "covparm":
            parsed = _number(value)
            if parsed is not None:
                covariance[name] = parsed

        elif section == "convergence":
            parts = value.split("|", 1)
            convergence_status = parts[0].strip() or None
            convergence_reason = parts[1].strip() if len(parts) > 1 else None

        elif section == "environment":
            if name == "sas_version":
                sas_version = value or None
            elif name == "run_datetime":
                run_datetime = value or None
            elif name == "case_id":
                emitted_case_id = value or None
            elif name == "dataset_sha256":
                emitted_dataset_sha256 = value or None

    if estimate is None and not covariance:
        raise ResultParseError(
            "no estimate and no covariance parameters were found - the file "
            "has the right columns but none of the expected sections"
        )

    return ParsedSASResult(
        estimate_log=estimate,
        standard_error=standard_error,
        denominator_df=df,
        ci_lower_log=lower,
        ci_upper_log=upper,
        covariance_parameters=covariance,
        convergence_status=convergence_status,
        convergence_reason=convergence_reason,
        sas_version=sas_version,
        run_datetime=run_datetime,
        emitted_case_id=emitted_case_id,
        emitted_dataset_sha256=emitted_dataset_sha256,
        problems=tuple(problems),
    )


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: SASValidationRunStatus
    parsed: ParsedSASResult | None
    detail: str


def ingest_upload(
    *,
    content: str,
    declared_dataset_sha256: str,
    declared_program_sha256: str,
    package_dataset_sha256: str,
    package_program_sha256: str,
) -> IngestOutcome:
    """Hashes first, then parse. Never the other way round.

    The declared hashes come from the uploader's own copy of the package. If
    they do not match what we generated, the customer ran a different dataset
    or a different program - possibly a perfectly good analysis, but not of the
    question this run asked.
    """
    if declared_dataset_sha256 != package_dataset_sha256:
        return IngestOutcome(
            SASValidationRunStatus.HASH_MISMATCH,
            None,
            "dataset hash does not match the generated package: this output "
            "was produced from different data",
        )
    if declared_program_sha256 != package_program_sha256:
        return IngestOutcome(
            SASValidationRunStatus.HASH_MISMATCH,
            None,
            "program hash does not match the generated package: this output "
            "was produced by a modified or different SAS program",
        )

    try:
        parsed = parse_result_csv(content)
    except ResultParseError as error:
        return IngestOutcome(
            SASValidationRunStatus.INCOMPLETE, None, f"could not parse: {error}"
        )

    if not parsed.is_complete:
        missing = [
            field_name
            for field_name, value in (
                ("estimate", parsed.estimate_log),
                ("standard error", parsed.standard_error),
                ("denominator df", parsed.denominator_df),
                ("lower limit", parsed.ci_lower_log),
                ("upper limit", parsed.ci_upper_log),
            )
            if value is None
        ]
        return IngestOutcome(
            SASValidationRunStatus.INCOMPLETE,
            parsed,
            "SAS did not report: " + ", ".join(missing),
        )

    if parsed.converged is False:
        return IngestOutcome(
            SASValidationRunStatus.REVIEW_REQUIRED,
            parsed,
            "SAS reported a non-converged fit "
            f"({parsed.convergence_reason or 'no reason given'}). The numbers "
            "are retained as evidence but must not be compared as if the model "
            "had fitted.",
        )

    return IngestOutcome(
        SASValidationRunStatus.PARSED, parsed, "parsed and ready for comparison"
    )


__all__ = [
    "CONTRAST_LABEL",
    "IngestOutcome",
    "ParsedSASResult",
    "ResultParseError",
    "ingest_upload",
    "parse_result_csv",
]
