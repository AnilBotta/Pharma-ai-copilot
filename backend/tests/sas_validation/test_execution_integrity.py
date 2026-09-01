"""Manual execution can never be reported as verified.

THE CLAIM THAT WAS BEING MADE, AND WAS NOT TRUE

The workflow called `compare()` with a hard-coded `program_hash_matched=True`,
so every report said the program hash had been verified. Nothing in the manual
workflow establishes which `validate.sas` a customer ran.

Three separate facts were collapsed into that one claim:

    we know the archive we generated and its hash   - ours, verifiable
    the result reports our dataset hash             - self-reported, checked
    the result reports our case id                  - self-reported, checked
    the customer ran our exact program              - NOT KNOWN

The first three are worth having. The fourth cannot be established from
anything a customer-controlled environment returns, and presenting it as
verified overstated the evidence on a record whose whole purpose is to be
trustworthy.

WHAT THESE TESTS PIN DOWN

That the three answers stay separate, that manual execution is permanently
UNVERIFIED_MANUAL_EXECUTION, that unverified is NOT treated as failure, and
that no code path can reintroduce the hard-coded claim.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.sas_validation.compare import compare
from app.sas_validation.ingest import ParsedSASResult
from app.sas_validation.integrity import (
    DatasetProvenance,
    EvidenceIntegrity,
    PackageIntegrity,
    ProgramExecutionIntegrity,
    manual_execution_integrity,
)
from app.sas_validation.modes import SASIntegrationMode, SASValidationRunStatus
from app.sas_validation.targets import get_target
from app.sas_validation.workflow import _manual_integrity

BACKEND = Path(__file__).resolve().parents[2]
SAS_PACKAGE = BACKEND / "app" / "sas_validation"
CASE = "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"

PACKAGE_ROW = {
    "case_id": CASE,
    "dataset_sha256": "a" * 64,
    "program_sha256": "b" * 64,
    "archive_sha256": "c" * 64,
}


def parsed(**overrides) -> ParsedSASResult:
    fields = {
        "estimate_log": 0.0223913,
        "standard_error": 0.0303172,
        "denominator_df": 19.8906,
        "ci_lower_log": -0.0299207,
        "ci_upper_log": 0.0747033,
        "convergence_status": "0",
        "sas_version": "9.04.01M8P011823",
        "emitted_case_id": CASE,
        "emitted_dataset_sha256": "a" * 64,
    }
    fields.update(overrides)
    return ParsedSASResult(**fields)


# --------------------------------------- 1. manual is never VERIFIED ---


def test_manual_execution_is_never_verified_however_well_the_stamps_match():
    """The requirement, stated directly.

    Matching dataset hash, matching case id, verified archive - and the
    program is still unverified, because none of those is evidence about the
    program.
    """
    integrity = _manual_integrity(parsed(), PACKAGE_ROW)

    assert integrity.dataset_provenance is DatasetProvenance.MATCH
    assert integrity.case_stamp is DatasetProvenance.MATCH
    assert integrity.package is PackageIntegrity.VERIFIED

    assert (
        integrity.program_execution
        is ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION
    )
    assert integrity.program_execution is not ProgramExecutionIntegrity.VERIFIED


def test_the_manual_constructor_does_not_accept_a_program_verdict():
    """Not a parameter, so it cannot be passed by mistake.

    A keyword argument defaulting to UNVERIFIED would still let a caller pass
    VERIFIED. Removing the parameter removes the possibility.
    """
    import inspect

    signature = inspect.signature(manual_execution_integrity)
    assert "program_execution" not in signature.parameters
    assert set(signature.parameters) == {
        "package",
        "dataset_provenance",
        "case_stamp",
    }


# ------------------------------- 2. match -> sound, still unverified ---


def test_matching_stamps_give_sound_provenance_and_a_usable_comparison():
    """Unverified execution must not suppress the numbers.

    Every honest manual run is unverified. If that removed the comparison,
    the feature would produce nothing on its intended happy path.
    """
    report = compare(
        target=get_target(CASE),
        package_id="p" * 64,
        parsed=parsed(),
        engine_result=None,
        integrity=_manual_integrity(parsed(), PACKAGE_ROW),
    )

    assert report.integrity.provenance_is_sound
    assert report.status is SASValidationRunStatus.REVIEW_REQUIRED
    assert report.status is not SASValidationRunStatus.HASH_MISMATCH
    assert report.quantities, "the numerical comparison disappeared"

    # And the qualification travels with the report.
    assert any("cannot cryptographically prove" in note for note in report.notes)


def test_unverified_execution_is_not_a_failure():
    """UNVERIFIED_MANUAL_EXECUTION != MISMATCH.

    Treating them the same would fail every valid manual upload and teach
    reviewers to ignore the field.
    """
    assert not ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION.is_failure
    assert ProgramExecutionIntegrity.MISMATCH.is_failure
    assert not ProgramExecutionIntegrity.VERIFIED.is_failure


# ------------------------------------- 3 & 4. wrong stamps -> mismatch ---


def test_a_wrong_dataset_hash_is_a_mismatch():
    integrity = _manual_integrity(
        parsed(emitted_dataset_sha256="f" * 64), PACKAGE_ROW
    )
    assert integrity.dataset_provenance is DatasetProvenance.MISMATCH
    assert not integrity.provenance_is_sound

    report = compare(
        target=get_target(CASE), package_id="p" * 64, parsed=parsed(),
        engine_result=None, integrity=integrity,
    )
    assert report.status is SASValidationRunStatus.HASH_MISMATCH


def test_a_wrong_case_id_is_a_mismatch():
    integrity = _manual_integrity(
        parsed(emitted_case_id="SOME_OTHER_CASE"), PACKAGE_ROW
    )
    assert integrity.case_stamp is DatasetProvenance.MISMATCH
    assert not integrity.provenance_is_sound

    report = compare(
        target=get_target(CASE), package_id="p" * 64, parsed=parsed(),
        engine_result=None, integrity=integrity,
    )
    assert report.status is SASValidationRunStatus.HASH_MISMATCH


def test_absent_stamps_are_missing_rather_than_matching():
    """A result with no stamps must not be treated as agreeing."""
    integrity = _manual_integrity(
        parsed(emitted_dataset_sha256=None, emitted_case_id=None), PACKAGE_ROW
    )
    assert integrity.dataset_provenance is DatasetProvenance.MISSING
    assert integrity.case_stamp is DatasetProvenance.MISSING
    assert not integrity.provenance_is_sound


# ------------------------- 5. package integrity is our own, server-side ---


def test_package_integrity_is_verified_from_our_own_stored_hash():
    """It depends on nothing the customer did."""
    assert (
        _manual_integrity(parsed(), PACKAGE_ROW).package
        is PackageIntegrity.VERIFIED
    )


def test_a_package_with_no_stored_archive_is_absent_not_verified():
    row = {**PACKAGE_ROW, "archive_sha256": None}
    integrity = _manual_integrity(parsed(), row)
    assert integrity.package is PackageIntegrity.ABSENT
    assert not integrity.provenance_is_sound


def test_the_three_answers_are_reported_separately():
    """Never collapsed into one "hash verification passed" statement."""
    payload = _manual_integrity(parsed(), PACKAGE_ROW).as_dict()

    assert payload["package_integrity"] == "verified"
    assert payload["dataset_provenance"] == "match"
    assert payload["validation_case_stamp"] == "match"
    assert payload["program_execution_integrity"] == "unverified_manual_execution"
    assert payload["program_execution_is_failure"] is False
    assert "cannot cryptographically prove" in str(payload["qualification"])
    # And the dataset stamp is described for what it is.
    assert "not cryptographic attestation" in str(payload["dataset_stamp_meaning"])


def test_the_rendered_report_shows_all_three(capsys=None):
    from app.sas_validation.compare import render_report

    rendered = render_report(
        compare(
            target=get_target(CASE), package_id="p" * 64, parsed=parsed(),
            engine_result=None,
            integrity=_manual_integrity(parsed(), PACKAGE_ROW),
        )
    )
    assert "package archive integrity  : VERIFIED" in rendered
    assert "dataset provenance stamp   : MATCH" in rendered
    assert "validation case stamp      : MATCH" in rendered
    assert "program execution integrity: UNVERIFIED_MANUAL_EXECUTION" in rendered
    # The old single line must not come back.
    assert "program hash matched" not in rendered


# ------------------------------ 6. the hard-coded claim cannot return ---


def test_no_module_hard_codes_a_program_verification():
    """An AST guard, because this is exactly the mistake that was made.

    `program_hash_matched=True` was a keyword argument nobody looked at twice.
    Searching the source is the only way to be sure an equivalent has not been
    reintroduced under another name.
    """
    offenders: list[str] = []

    for module in sorted(SAS_PACKAGE.glob("*.py")):
        if module.name == "integrity.py":
            continue  # defines the vocabulary; naming VERIFIED there is its job
        tree = ast.parse(module.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg in (
                    "program_hash_matched",
                    "program_execution",
                    "program_verified",
                ):
                    offenders.append(f"{module.name} passes {keyword.arg}=")

    assert not offenders, offenders


def test_the_word_verified_is_never_asserted_of_a_manual_program():
    """No module may name ProgramExecutionIntegrity.VERIFIED outside its home.

    Nothing implemented today can legitimately set it: only a provider that
    controlled the program bytes, the submission, the environment and the
    result retrieval could, and none exists.
    """
    for module in sorted(SAS_PACKAGE.glob("*.py")):
        if module.name == "integrity.py":
            continue
        source = module.read_text(encoding="utf-8")
        assert "ProgramExecutionIntegrity.VERIFIED" not in source, module.name


def test_managed_mode_is_documented_as_where_verified_could_apply():
    """The distinction is architecture, not a promise.

    Recorded so a future managed provider is understood as the thing that
    could earn VERIFIED - and so nobody sets it before that exists.
    """
    source = (SAS_PACKAGE / "integrity.py").read_text(encoding="utf-8")
    assert "MANAGED" in source
    assert "not implemented" in source.lower()


@pytest.mark.parametrize(
    "mode", [SASIntegrationMode.MANUAL_UPLOAD]
)
def test_the_integrity_record_names_the_mode_it_describes(mode):
    """A reviewer reading a stored record should not have to infer the mode."""
    integrity = _manual_integrity(parsed(), PACKAGE_ROW)
    assert integrity.mode is mode
    assert integrity.as_dict()["mode"] == mode.value


def test_an_explicit_mismatch_verdict_is_still_possible():
    """The enum has somewhere to put positive evidence of a wrong program.

    Not reachable today, and the type must still be able to express it - a
    two-state model would leave nowhere to record it if it ever became
    detectable.
    """
    integrity = EvidenceIntegrity(
        package=PackageIntegrity.VERIFIED,
        dataset_provenance=DatasetProvenance.MATCH,
        case_stamp=DatasetProvenance.MATCH,
        program_execution=ProgramExecutionIntegrity.MISMATCH,
        mode=SASIntegrationMode.MANUAL_UPLOAD,
    )
    report = compare(
        target=get_target(CASE), package_id="p" * 64, parsed=parsed(),
        engine_result=None, integrity=integrity,
    )
    assert report.status is SASValidationRunStatus.HASH_MISMATCH
    assert "different program was executed" in " ".join(report.notes)
