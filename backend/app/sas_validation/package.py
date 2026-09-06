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

AND FOR ONE RELEASE THAT PARAGRAPH WAS NOT TRUE OF THE README

`_assert_neutral` skipped `README.md`, on the reasoning that a human should
see the reference values in context. The README then rendered
`target.references` in full - including the be-stats candidate 19.8906 and
ReplicateBE's 22.5403, each with a paragraph explaining which is better
supported - four lines under a heading that reads "It contains NO expected
answer".

An operator who reads that page before running SAS is no longer independent,
and the exemption is why nothing failed. `PackageAudience` now decides what a
package may contain, and the neutrality check reads no exemption list: for an
operator package it scans EVERY file, README included.

Presentation only. The dataset bytes, the SAS program and the model
specification are identical across audiences, and tests assert that rather
than trusting it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.sas_validation.dataset import validate_observations
from app.sas_validation.program import (
    DATASET_COLUMNS,
    DERIVED_ANALYSIS_DEFINITION,
    DERIVED_ANALYSIS_VARIABLE,
    RAW_ANALYSIS_INPUT,
    SyntaxNormalization,
    generate_program,
)
from app.sas_validation.targets import ValidationTarget

PACKAGE_SCHEMA = "pharma-copilot/sas-validation-package/1"


class PackageAudience(StrEnum):
    """Who the package is being assembled for. Presentation only.

    NOT a statistical switch. The dataset, the SAS program and the model
    specification are byte-identical whichever audience is chosen, and
    `test_the_two_audiences_ship_identical_statistics` asserts it. What
    changes is the README, because the README is the only file a human reads
    before deciding what to run.
    """

    #: For the licensed-SAS operator. Carries no candidate result, no
    #: comparison, no preference between candidates, and nothing that would
    #: let a reader work out which answer is hoped for. This is the default:
    #: a caller who has not thought about audience must not be able to hand
    #: an operator a leading question by omission.
    OPERATOR_BLINDED = "operator_blinded"
    #: For internal QA and reviewer use, where the candidate values are the
    #: point. Never sent outward; the workflow that produces an operator
    #: download does not offer this audience.
    INTERNAL_QA = "internal_qa"


#: Values that must never appear in an operator package. Both are candidate
#: denominator dfs from unconfirmed sources; shipping either would turn a
#: neutral execution package into a leading question.
FORBIDDEN_EXPECTED_VALUES: tuple[str, ...] = ("19.8906", "22.5403", "19.603")

#: The rest of the blind, which two literals cannot carry on their own.
#:
#: A candidate can leak as a name as easily as a number - "ReplicateBE says",
#: "expected_df", "the preferred result" - and the next candidate will have a
#: value nobody has hard-coded here. So the scan covers the VOCABULARY of
#: expectation as well as the two known figures, and is matched
#: case-insensitively.
FORBIDDEN_OPERATOR_PHRASES: tuple[str, ...] = (
    "replicatebe",
    "expected_df",
    "expected_ci",
    "expected_se",
    "expected_answer_value",
    "candidate_df",
    "candidate answer",
    "reference_result",
    "preferred_result",
    "target_result",
    "best-supported",
    "independent candidate",
    "external implementation result",
    "pass criterion",
    "pass criteria",
    "should be approximately",
)


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
    # The header IS `DATASET_COLUMNS`, not a second copy of it. The first
    # version declared one tuple and wrote a different list, so the manifest
    # advertised a column (`Y`) the file did not contain.
    writer.writerow(list(DATASET_COLUMNS))
    for row in materialised:
        writer.writerow([row[column] for column in DATASET_COLUMNS[:-1]]
                        + [repr(row["VALUE"])])
    return buffer.getvalue()


def _readme(
    target: ValidationTarget,
    result_filename: str,
    normalizations: tuple[SyntaxNormalization, ...],
    audience: PackageAudience,
) -> str:
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
        "## Do not edit the program",
        "",
        "`validate.sas` is ready to run as supplied. The only line you should",
        "change is `%let packagedir = ...;`, which tells SAS where the package",
        "files are.",
        "",
        "Any other edit breaks the program hash that ties your output back to",
        "this package, and the upload will be rejected as evidence for a",
        "different program. If the program genuinely cannot run without a",
        "change, this package is invalid: tell us what was needed and why, and",
        "we will generate a new one. Please do not adjust it locally.",
        "",]
    if normalizations:
        lines += [
            "### Syntax normalizations already applied for you",
            "",
            "The regulatory source and the executable SAS differ in one place,",
            "and we have resolved it here rather than asking you to:",
            "",
        ]
        for normalization in normalizations:
            lines += [
                f"- `{normalization.source_keyword}` -> "
                f"`{normalization.executable_keyword}` "
                f"(`{normalization.identifier}`)",
                f"  - {normalization.reason}",
                "  - Changes SAS syntax only. The statistical model is "
                "unchanged.",
            ]
        lines += [
            "",
            "The regulator's original statements are recorded verbatim in",
            "`model_specification.json`, so the source text and what actually",
            "ran are both part of this package's evidence.",
            "",
        ]
    if audience is PackageAudience.OPERATOR_BLINDED:
        lines += _operator_sections(result_filename)
        return "\n".join(lines) + "\n"

    lines += [
        "## Reference values",
        "",
        "INTERNAL QA COPY. Not for an operator: a reader who sees these before",
        "running SAS is no longer independent of the question being asked.",
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


def _operator_sections(result_filename: str) -> list[str]:
    """Everything the operator needs, and nothing about what we hope to see.

    Deliberately says what is withheld rather than staying silent about it.
    An operator who notices the absence and asks is better than one who goes
    looking, and a stated blind is a blind somebody can hold us to.
    """
    return [
        "## Before you start",
        "",
        "You need SAS with SAS/STAT licensed, and `PROC MIXED` available in",
        "that installation. Nothing else: the package runs entirely inside",
        "your environment and makes no outbound connection.",
        "",
        "## Steps",
        "",
        "1. Extract every file in this package into one folder.",
        "2. Open `validate.sas` and set `%let packagedir = ...;` to that folder.",
        "3. Run `validate.sas` unmodified.",
        "4. Do not edit the dataset, the model, or any other line of the program.",
        f"5. Return `{result_filename}` exactly as written, without opening and",
        "   re-saving it in a spreadsheet.",
        "6. Return the COMPLETE SAS log, including any notes and warnings.",
        "7. State your SAS version, as printed in the log.",
        "8. State the date and time the program was executed, and the time zone.",
        "",
        "## What you must not do",
        "",
        "- Do not edit the dataset, in any way, for any reason.",
        "- Do not edit the model statements or substitute another procedure.",
        "- Do not hand-correct warnings, or re-run with options changed to",
        "  silence them. A warning is part of the evidence.",
        "- Do not copy any value from another system into the result file.",
        "- Do not adjust the output to match anything.",
        "",
        "If the program genuinely cannot run as supplied, stop and tell us what",
        "was needed and why. We will generate a new package. Please do not",
        "adjust this one locally: an edited program produces evidence for a",
        "program nobody specified.",
        "",
        "## Package identity",
        "",
        "`manifest.json` carries this package's id and the SHA-256 of every",
        "file. Your returned output is tied back to those hashes, which is what",
        "makes the run auditable months later.",
        "",
        "## Attestation",
        "",
        "When you return the files, please state, as the person who ran it:",
        "",
        "- that you executed the supplied `validate.sas` unmodified,",
        "- in a licensed SAS environment you are authorised to use,",
        "- that the returned result and log are the unedited outputs of that run,",
        "- your name and role, and the execution date and time.",
        "",
        "This attestation is recorded as YOUR STATEMENT. The platform does not",
        "treat it as proof that the program ran - nothing outside your",
        "environment can establish that - and the evidence stays marked as",
        "manually executed for exactly that reason.",
        "",
        "## What is deliberately not in this package",
        "",
        "No expected denominator degrees of freedom, no expected confidence",
        "interval, no standard error to aim at, and no result from any other",
        "software. None is withheld because it is secret; they are withheld",
        "because this run exists to produce that number independently, and a",
        "reader who knows the hoped-for answer cannot produce one.",
        "",
        "Nothing here defines a right answer, and you are not being asked",
        "whether the run agrees with anything. Return what SAS produced.",
        "",
    ]


def build_package(
    *,
    target: ValidationTarget,
    observations: Sequence[Mapping[str, object]],
    be_stats_version: str,
    git_sha: str,
    generated_at: datetime | None = None,
    audience: PackageAudience = PackageAudience.OPERATOR_BLINDED,
) -> ValidationPackage:
    """Assemble the package. Pure, apart from the timestamp it is handed.

    Raises `InvalidObservations` before producing anything if any supplied
    value cannot be analysed on the log scale. It never drops a row and
    continues: a package whose manifest counts more observations than SAS will
    fit is evidence for an analysis nobody specified.
    """
    validate_observations(observations)

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
        # The regulator's text and what SAS actually runs, kept separate
        # because for one statement they differ - see `syntax_normalizations`.
        "regulatory_source_statements": list(program.source_statements),
        "executable_sas_statements": list(program.executable_statements),
        "syntax_normalizations": program.normalization_records(),
        "syntax_normalization_note": (
            "Each substitution above changes SAS SYNTAX ONLY and leaves the "
            "statistical model unchanged. The program is ready to run as "
            "supplied: a client must not hand-edit it, because any edit breaks "
            "the program hash that ties the output back to this package. If a "
            "further change is genuinely required, this package is invalid and "
            "a new one must be generated."
        ),
        # The shipped CSV columns, and the variable derived from them. `Y` is
        # NOT a column of dataset.csv.
        "dataset_columns": list(DATASET_COLUMNS),
        "raw_analysis_input": RAW_ANALYSIS_INPUT,
        "derived_analysis_variable": DERIVED_ANALYSIS_VARIABLE,
        "derived_analysis_definition": DERIVED_ANALYSIS_DEFINITION,
        "observation_validity_rule": (
            "Every value was checked to be present, numeric, finite and "
            "strictly positive before this package was generated. The program "
            "therefore drops nothing; its defensive check aborts rather than "
            "silently excluding an observation."
        ),
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

    readme_text = _readme(
        target, program.result_filename, program.normalizations_applied, audience
    )
    readme_hash = sha256_text(readme_text)

    files = (
        PackageFile(dataset_name, dataset_csv, dataset_hash),
        PackageFile(program_name, program.text, program_hash),
        PackageFile("model_specification.json", specification_text, specification_hash),
        PackageFile("README.md", readme_text, readme_hash),
    )

    manifest: dict[str, object] = {
        "schema": PACKAGE_SCHEMA,
        "case_id": target.case_id,
        "regulatory_method": target.regulatory_method,
        # In the manifest, so the package's identity depends on it. Two
        # packages differing only in audience are different packages, and a
        # reviewer holding one can tell which was handed out.
        "audience": str(audience),
        "readme_sha256": readme_hash,
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
    _assert_neutral(package, audience)
    return package


def _assert_neutral(package: ValidationPackage, audience: PackageAudience) -> None:
    """No candidate answer may travel inside a package. Checked, not trusted.

    NO EXEMPTION LIST FOR AN OPERATOR PACKAGE

    This function used to skip `README.md` and `manifest.json`, reasoning that
    a human should see the reference values in context. The README was the one
    file the operator was certain to read, and it carried both candidate dfs
    and named the software that produced one of them. The exemption was the
    leak, and an exemption keyed by filename cannot distinguish the human who
    should see a value from the one who must not.

    So the audience decides, and for an operator package the answer is every
    file. The DATASET, the PROGRAM and the SPECIFICATION are scanned whatever
    the audience: those are what SAS reads, and no reader needs a candidate
    answer in them.
    """
    always_scanned = {"dataset.csv", "validate.sas", "model_specification.json"}

    for file in package.files:
        blinded = audience is PackageAudience.OPERATOR_BLINDED
        if not blinded and file.name not in always_scanned:
            continue

        for forbidden in FORBIDDEN_EXPECTED_VALUES:
            if forbidden in file.content:
                raise ValueError(
                    f"{file.name} contains {forbidden!r}. A validation package "
                    "must not ship a candidate answer to the question it is "
                    "being run to settle."
                )
        if not blinded:
            continue

        lowered = file.content.lower()
        for phrase in FORBIDDEN_OPERATOR_PHRASES:
            if phrase in lowered:
                raise ValueError(
                    f"{file.name} contains {phrase!r}. An "
                    f"{PackageAudience.OPERATOR_BLINDED} package may not name "
                    "another engine, an expected value, or a preference "
                    "between candidates - a candidate leaks as a name as "
                    "easily as it leaks as a number."
                )


__all__ = [
    "FORBIDDEN_EXPECTED_VALUES",
    "FORBIDDEN_OPERATOR_PHRASES",
    "PACKAGE_SCHEMA",
    "PackageAudience",
    "PackageFile",
    "ValidationPackage",
    "build_package",
    "sha256_text",
    "write_dataset_csv",
]
