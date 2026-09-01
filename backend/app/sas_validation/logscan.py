"""Read a SAS log for signals, and never for numbers.

THE LINE THIS MODULE DOES NOT CROSS

The log is archived as evidence. It is scanned for the presence of error and
warning lines. It is NEVER parsed for an estimate, a standard error or a
denominator df - those come only from the structured result file our own
program writes.

The distinction matters because a log is unstructured, version-dependent and
full of numbers that look like results. A scraper would eventually read one of
them and produce a plausible wrong denominator df, which is precisely the
failure this whole programme of work exists to prevent.

WHAT A SIGNAL DOES AND DOES NOT DO

Finding `ERROR:` in a log while the structured result claims convergence is a
contradiction, and a contradiction is for a human. It raises
`REVIEW_REQUIRED`. It does not reject the run and it does not accept it - a
text match is not strong enough to decide either way on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: SAS writes these at the start of a line. Anchored so a line merely
#: mentioning the word - "no errors were detected" - is not a finding.
_ERROR = re.compile(r"^ERROR(?: \d+-\d+)?:", re.MULTILINE)
_WARNING = re.compile(r"^WARNING:", re.MULTILINE)

#: How much of a line to keep. Enough to identify the problem, short enough
#: that no plausible data value is carried into an audit row or a report.
_EXCERPT = 200

#: At most this many of each, so a pathological log cannot fill a record.
_MAX_LINES = 20


@dataclass(frozen=True, slots=True)
class LogScan:
    error_lines: tuple[str, ...]
    warning_lines: tuple[str, ...]
    truncated: bool

    @property
    def has_errors(self) -> bool:
        return bool(self.error_lines)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warning_lines)


def scan_log(text: str) -> LogScan:
    """Collect ERROR and WARNING lines. Nothing else is extracted."""
    errors: list[str] = []
    warnings: list[str] = []

    for line in text.splitlines():
        if _ERROR.match(line):
            if len(errors) < _MAX_LINES:
                errors.append(line.strip()[:_EXCERPT])
        elif _WARNING.match(line):
            if len(warnings) < _MAX_LINES:
                warnings.append(line.strip()[:_EXCERPT])

    truncated = (
        len(_ERROR.findall(text)) > _MAX_LINES
        or len(_WARNING.findall(text)) > _MAX_LINES
    )
    return LogScan(tuple(errors), tuple(warnings), truncated)


def contradicts_convergence(scan: LogScan, *, converged: bool | None) -> bool:
    """Does the log contradict what the structured result claims?

    Only in one direction. A log with errors while the result reports a
    converged fit is a contradiction worth a reviewer's attention. A log with
    errors while the result already reports non-convergence is agreement, and
    raising the same flag twice would be noise.
    """
    return converged is True and scan.has_errors


__all__ = ["LogScan", "contradicts_convergence", "scan_log"]
