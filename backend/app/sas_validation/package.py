"""Build the immutable validation package a customer runs inside SAS.

IMMUTABILITY IS THE WHOLE POINT

A validation package is evidence. Its identity is the SHA-256 of its manifest,
and the manifest covers the dataset, the program, the model specification, the
engine version and the commit. Change any of those and you get a DIFFERENT
package with a different id - never a quietly updated one, because the record
of what was run must survive the thing that ran it.

`build_package` is a pure function of its inputs for exactly this reason: the
same dataset and the same engine version produce a byte-identical package and
therefore the same id, and a reviewer comparing two runs months apart can tell
whether they were looking at the same thing.

WHAT IS DELIBERATELY ABSENT FROM THE PACKAGE

No expected denominator df. Not 19.8906, not 22.5403, and no pass criterion
derived from either. A package that shipped an expected answer would be asking
SAS to confirm a number rather than to produce one, and the whole reason for
running SAS is that neither candidate is regulator-confirmed.
`test_package_is_neutral.py` asserts those values appear nowhere in it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.sas_validation.program import DATASET_COLUMNS, generate_program
from app.sas_validation.targets import ValidationTarget

PACKAGE_SCHEMA = "pharma-copilot/sas-validation-package/1"

#: Values that must never appear in a generated package. Both are candidate
#: denominator dfs from unconfirmed sources; shipping either would turn a
#: neutral execution package into a leading question.
FORBIDDEN_EXPECTED_VALUES: tuple[str, ...] = ("19.8906", "22.5403", "19.603")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PackageFile:
    name: str
    content: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidationPackage:
    package_id: str
    case_id: str
    regulatory_method: str
    files: tuple[PackageFile, ...]
    manifest: Mapping[str, object]
    generated_at: str
    be_stats_version: str
    git_sha: str

    def file(self, name: str) -> PackageFile:
        for candidate in self.files:
            if candidate.name == name:
                return candidate
        raise KeyError(f"{name!r} is not in package {self.package_id}")

    def as_dict(self) -> dict[str, object]:
        return {
            "package_id": self.package_id,
            "case_id": self.case_id,
            "regulatory_method": self.regulatory_method,
            "generated_at": self.generated_at,
            "be_stats_version": self.be_stats_version,
            "git_sha": self.git_sha,
            "manifest": dict(self.manifest),
            "files": [
                {"name": f.name, "sha256": f.sha256, "bytes": len(f.content.encode())}
                for f in self.files
            ],
        }


def write_dataset_csv(rows: Iterable[Mapping[str, object]]) -> str:
    """Deterministic CSV: fixed column order, sorted rows, LF endings.

    Sorting matters more than it looks. The hash of this file is what ties an
    uploaded SAS result back to the data it was computed from, so two packages
    built from the same observations in a different order must not produce
    different hashes and appear to be different evidence.
    """
    materialised = [
        {
            "SUBJ": str(row["subject"]),
            "SEQ": str(row["sequence"]),
            "PER": int(row["period"]),
            "TRT": str(row["treatment"]),
            "VALUE": float(row["value"]),
        }
        for row in rows
    ]
    materialised.sort(key=lambda r: (r["SUBJ"], r["PER"]))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["SUBJ", "SEQ", "PER", "TRT", "VALUE"])
    for row in materialised:
        writer.writerow([row["SUBJ"], row["SEQ"], row["PER"], row["TRT"],
                         repr(row["VALUE"])])
    return buffer.getvalue()


def _readme(target: ValidationTarget, result_filename: str) -> str:
    lines = [
        f"# SAS validation package - {target.case_id}",
        "",
        target.title,
        "",
        "## What this is",
        "",
        "A neutral execution package. It contains a dataset, the exact SAS",
        "program to run on it, and a record of what model that program fits.",
        "It contains NO expected answer: the point of running it is to obtain",
        "a number that no regulator has published.",
        "",
        f"Design: {target.design}",
        f"Dataset source: {target.dataset_source}",
        "",
        "## Why it is being run",
        "",
        target.purpose,
        "",
        "## How to run it",
        "",
        "1. Put every file in this package in one folder.",
        "2. Open `validate.sas` and set `%let packagedir = ...;` to that folder.",
        "3. Run it in your own SAS environment. Nothing connects outward and no",
        "   credential is needed - your SAS environment stays under your",
        "   organisation's control.",
        f"4. Upload `{result_filename}` together with the SAS log.",
        "",
        "## What happens to the result",
        "",
        "The uploaded file is checked against this package's dataset and",
        "program hashes, parsed, and compared with the engine's own result.",
        "The comparison is reported to a reviewer.",
        "",
        "An upload does NOT change any method's validation status. Only an",
        "explicit, recorded review can do that.",
        "",
        "## Do not edit the model",
        "",
        "The PROC MIXED statements are reproduced verbatim from the cited",
        "regulatory source. Editing them makes this a test of a different",
        "model and the comparison meaningless. If the program will not run in",
        "your environment, report that rather than adjusting it.",
        "",
        "### One syntax note, and its limits",
        "",
        "The guidance writes `CLASSES`. If your SAS session rejects that word,",
        "`CLASS` is the accepted spelling of the same statement - a SYNTAX",
        "alias, not a change of model. That substitution is the only edit that",
        "is safe to make without invalidating the run, and it must still be",
        "reported with your result so the reviewer knows the program that ran",
        "was not byte-identical to the one shipped.",
        "",
        "We cannot verify this against a live SAS session - this organisation",
        "has no SAS licence, which is why we are asking you to run it. If the",
        "program needs any other change to execute, please tell us what and",
        "why instead of adjusting it locally.",
        "",
        "## Reference values",
        "",
        "For context only. None of these is a target to match.",
        "",
    ]
    for reference in target.references:
        shown = "not published" if reference.value is None else f"{reference.value}"
        lines.append(
            f"- **{reference.quantity}** = {shown} "
            f"[{reference.status.value.replace('_', ' ').upper()}] - "
            f"{reference.source}"
        )
        if reference.note:
            lines.append(f"  - {reference.note}")
    return "\n".join(lines) + "\n"


def build_package(
    *,
    target: ValidationTarget,
    observations: Sequence[Mapping[str, object]],
    be_stats_version: str,
    git_sha: str,
    generated_at: datetime | None = None,
) -> ValidationPackage:
    """Assemble the package. Pure, apart from the timestamp it is handed."""
    stamp = (generated_at or datetime.now(UTC)).replace(microsecond=0).isoformat()

    dataset_csv = write_dataset_csv(observations)
    dataset_name = "dataset.csv"
    dataset_hash = sha256_text(dataset_csv)

    program = generate_program(
        case_id=target.case_id,
        dataset_filename=dataset_name,
        dataset_sha256=dataset_hash,
    )
    program_name = "validate.sas"
    program_hash = sha256_text(program.text)

    specification = {
        "case_id": target.case_id,
        "regulatory_method": target.regulatory_method,
        "design": target.design,
        "model_citation": program.model_citation,
        "model_statements": list(program.model_statements),
        "dataset_columns": list(DATASET_COLUMNS),
        "expected_output_fields": [
            "fixed effect estimate (T vs. R, log scale)",
            "standard error",
            "denominator degrees of freedom (Satterthwaite)",
            "90% confidence limits (log scale)",
            "covariance parameter estimates",
            "convergence status",
            "SAS version",
        ],
        "missing_data_rule": (
            "available case analysis - PROC MIXED uses all observed data"
        ),
        "expected_answer": None,
        "expected_answer_note": (
            "Deliberately absent. No denominator df is shipped with this "
            "package, because none has been confirmed by a regulator and a "
            "shipped expectation would bias the run it is meant to settle."
        ),
    }
    specification_text = json.dumps(specification, indent=2, sort_keys=True) + "\n"
    specification_hash = sha256_text(specification_text)

    readme_text = _readme(target, program.result_filename)

    files = (
        PackageFile(dataset_name, dataset_csv, dataset_hash),
        PackageFile(program_name, program.text, program_hash),
        PackageFile("model_specification.json", specification_text, specification_hash),
        PackageFile("README.md", readme_text, sha256_text(readme_text)),
    )

    manifest: dict[str, object] = {
        "schema": PACKAGE_SCHEMA,
        "case_id": target.case_id,
        "regulatory_method": target.regulatory_method,
        "generated_at": stamp,
        "be_stats_version": be_stats_version,
        "git_sha": git_sha,
        "dataset_filename": dataset_name,
        "dataset_sha256": dataset_hash,
        "program_filename": program_name,
        "program_sha256": program_hash,
        "model_specification_sha256": specification_hash,
        "result_filename": program.result_filename,
        "n_observations": len(observations),
        "files": [{"name": f.name, "sha256": f.sha256} for f in files],
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    # The package's identity IS its manifest hash. Anything that changes the
    # dataset, the program, the specification, the engine version or the
    # commit changes this, which is what makes a new package rather than an
    # edited one.
    package_id = sha256_text(manifest_text)

    # The manifest joins the package only after its own hash has become the
    # package id - it describes the other four files and cannot describe itself.
    files = (
        *files,
        PackageFile("manifest.json", manifest_text, sha256_text(manifest_text)),
    )

    package = ValidationPackage(
        package_id=package_id,
        case_id=target.case_id,
        regulatory_method=target.regulatory_method,
        files=files,
        manifest=manifest,
        generated_at=stamp,
        be_stats_version=be_stats_version,
        git_sha=git_sha,
    )
    _assert_neutral(package)
    return package


def _assert_neutral(package: ValidationPackage) -> None:
    """No candidate df may travel inside a package. Checked, not trusted.

    The README prints reference values with their evidence status, which is
    context a human should see. The DATASET, the PROGRAM and the SPECIFICATION
    must contain none of them - those are what SAS reads.
    """
    for file in package.files:
        if file.name in ("README.md", "manifest.json"):
            continue
        for forbidden in FORBIDDEN_EXPECTED_VALUES:
            if forbidden in file.content:
                raise ValueError(
                    f"{file.name} contains {forbidden!r}. A validation package "
                    "must not ship a candidate answer to the question it is "
                    "being run to settle."
                )


__all__ = [
    "FORBIDDEN_EXPECTED_VALUES",
    "PACKAGE_SCHEMA",
    "PackageFile",
    "ValidationPackage",
    "build_package",
    "sha256_text",
    "write_dataset_csv",
]
