"""What must hold before a client is asked to run SAS for real.

This file covers the operational qualification, not the statistics:

    the two enums stay two enums          section 1
    the assistant runs last               section 7
    the assistant never parses raw files  section 8
    an attestation is not a verification  section 5
    a fixture is never regulatory evidence section 17

None of it implements or validates a statistical method.
`FDA_REPLICATE_STANDARD_ABE_PARTIAL` is NOT_IMPLEMENTED throughout, and
`test_no_automatic_promotion.py` still owns that guarantee.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.sas_validation.attestation import (
    ATTESTATION_LIMITATION,
    ATTESTATION_VERSION,
    AttestationRejected,
    EvidenceOrigin,
    attestation_hash,
    attestation_text,
    build_attestation,
)
from app.sas_validation.evidence_report import (
    DECISION_SEMANTICS,
    DRY_RUN_BANNER,
    build_evidence_report,
)
from app.sas_validation.integrity import ProgramExecutionIntegrity
from app.sas_validation.workflow import (
    DeterministicEvidenceNotReady,
    require_deterministic_evidence,
)

BACKEND = Path(__file__).resolve().parents[2]
SAS_PACKAGE = BACKEND / "app" / "sas_validation"
MIGRATIONS = BACKEND.parent / "supabase" / "migrations"

PACKAGE_ID = "a" * 64
ARCHIVE = "b" * 64


# =============================================== 1. two enums, on purpose ===
#
# `public.sas_oracle_closure` and `public.oracle_closure_decision` share two
# member names, which is exactly the coincidence that invites someone to merge
# them. They answer different questions, and merging them would make one of the
# two answers impossible to state.


def test_the_two_database_enums_are_not_the_same_enum():
    """RUN-LEVEL STATE versus APPEND-ONLY VERDICT.

        sas_oracle_closure         what is the CURRENT review state of this
                                   run? Includes not_assessed, because "nobody
                                   has looked yet" is a real state a run is in.

        oracle_closure_decision    what did a human DECIDE? A row in
                                   sas_human_reviews means a review actually
                                   happened, so not_assessed cannot be one of
                                   these - it would put an unreviewed run in
                                   the reviewed table.

    Merging them would either force not_assessed into the verdict vocabulary or
    strip a run of its "not yet examined" state. Both are worse than two types.
    """
    runs = (MIGRATIONS / "0032_sas_validation.sql").read_text(encoding="utf-8")
    review = (MIGRATIONS / "0034_sas_validation_review.sql").read_text(
        encoding="utf-8"
    )

    assert "create type public.sas_oracle_closure" in runs
    assert "create type public.oracle_closure_decision" in review

    # The run-level type carries the third state.
    run_type = runs[runs.index("create type public.sas_oracle_closure") :][:400]
    assert "'not_assessed'" in run_type

    # The verdict type does not, and must never.
    verdict = review[review.index("create type public.oracle_closure_decision") :][
        :400
    ]
    assert "'oracle_closure_accepted'" in verdict
    assert "'oracle_closure_rejected'" in verdict
    assert "'not_assessed'" not in verdict, (
        "not_assessed is the ABSENCE of a review. A row in sas_human_reviews "
        "means a review happened, so this value cannot be a verdict."
    )


def test_the_columns_use_the_type_that_matches_their_question():
    runs = (MIGRATIONS / "0032_sas_validation.sql").read_text(encoding="utf-8")
    review = (MIGRATIONS / "0034_sas_validation_review.sql").read_text(
        encoding="utf-8"
    )

    assert "review_status            public.sas_oracle_closure" in runs
    assert "decision                public.oracle_closure_decision" in review


def test_the_domain_layer_refuses_not_assessed_as_a_verdict():
    """The Python half of the same rule, enforced in `prepare_review`."""
    from app.sas_validation.human_review import RECORDABLE_DECISIONS
    from app.sas_validation.modes import OracleClosureDecision

    assert OracleClosureDecision.NOT_ASSESSED not in RECORDABLE_DECISIONS
    assert len(RECORDABLE_DECISIONS) == 2


# ================================= 7. the assistant runs last, on facts ===


def test_the_assistant_is_refused_a_run_with_no_comparison():
    """A hash-mismatched or incomplete run has no assembled facts.

    Handed one, the model would produce a confident paragraph about a dict of
    nulls, and a reviewer skimming Section B would read it as analysis.
    """
    with pytest.raises(DeterministicEvidenceNotReady, match="no comparison"):
        require_deterministic_evidence({"status": "hash_mismatch"})

    with pytest.raises(DeterministicEvidenceNotReady, match="no comparison"):
        require_deterministic_evidence({"status": "incomplete", "comparison": None})


def test_the_refusal_names_the_state_rather_than_failing_vaguely():
    with pytest.raises(DeterministicEvidenceNotReady) as error:
        require_deterministic_evidence({"status": "hash_mismatch"})
    assert "hash mismatch" in str(error.value)


def test_a_comparison_without_integrity_is_also_refused():
    """Provenance is deterministic code's answer, never the model's to infer."""
    with pytest.raises(DeterministicEvidenceNotReady, match="integrity"):
        require_deterministic_evidence(
            {"status": "review_required", "comparison": {"quantities": []}}
        )


def test_an_assembled_run_is_allowed_through():
    require_deterministic_evidence(
        {
            "status": "review_required",
            "comparison": {"integrity": {"package_integrity": "verified"}},
        }
    )


# ====================== 8. deterministic code owns parsing, not the model ===


def test_the_ai_module_never_reads_a_file_or_parses_a_result():
    """Structural, not a promise in a docstring.

    Parsing, hashing, numerical extraction, provenance and comparison belong to
    deterministic code. If the assistant could open `be_result.csv` it could
    disagree with the parser about what SAS said, and there would be two
    answers to a question that must have one.
    """
    tree = ast.parse((SAS_PACKAGE / "ai_reviewer.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app.sas_validation.ingest"), node.module
            assert not node.module.startswith("app.sas_validation.logscan")
            assert not node.module.startswith("app.sas_validation.storage")
            assert not node.module.startswith("be_stats")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in ("csv", "io"), alias.name

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in called, "the assistant must not read files"


def test_the_assistant_receives_parsed_numbers_not_raw_text():
    """`build_ai_evidence` hands over fields, never file contents."""
    from app.sas_validation.workflow import build_ai_evidence

    evidence = build_ai_evidence(
        run={
            "case_id": "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II",
            "denominator_df": 19.8906,
            "comparison": {"integrity": {"package_integrity": "verified"}},
        },
        package={"id": PACKAGE_ID},
    )
    serialised = str(evidence)

    assert evidence["sas_reported"]["denominator_df"] == 19.8906
    # The shapes a raw file would have.
    assert "section,name,value" not in serialised
    assert "PROC MIXED" not in serialised


# ================== 5. an attestation is provenance, not verification ===


def attestation(**overrides):
    fields = {
        "package_id": PACKAGE_ID,
        "archive_sha256": ARCHIVE,
        "operator_name": "A. Operator",
        "operator_organization": "Client Pharma Ltd",
        "confirmed": True,
        "sas_version": "9.04.01M8",
        "executed_at": datetime(2026, 9, 1, 10, 30, tzinfo=UTC),
    }
    fields.update(overrides)
    return build_attestation(**fields)


def test_an_attestation_records_who_says_they_ran_it():
    recorded = attestation()

    assert recorded.operator_name == "A. Operator"
    assert recorded.operator_organization == "Client Pharma Ltd"
    assert recorded.sas_version == "9.04.01M8"
    assert recorded.attestation_version == ATTESTATION_VERSION
    assert recorded.attestation_hash == attestation_hash(recorded.attestation_text)


def test_the_attestation_text_names_the_package_it_is_about():
    """A claim that did not identify the package would not identify anything."""
    assert PACKAGE_ID in attestation().attestation_text
    assert PACKAGE_ID in attestation_text(PACKAGE_ID)


def test_an_attestation_does_not_upgrade_program_execution_integrity():
    """THE POINT OF THE WHOLE MECHANISM'S LIMITS.

    "The operator signed something" is exactly the fact that gets rounded up to
    "verified" by the third person to read it. The stored record says otherwise
    in its own body, not only in a docstring here.
    """
    stored = attestation().as_dict()

    assert (
        stored["program_execution_integrity"]
        == ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION.value
    )
    assert stored["program_execution_integrity"] != "verified"
    assert "not cryptographic verification" in stored["limitation"]


def test_the_limitation_travels_with_the_attestation_everywhere():
    assert "cannot verify the exact SAS program bytes" in ATTESTATION_LIMITATION
    assert "UNVERIFIED_MANUAL_EXECUTION" in ATTESTATION_LIMITATION

    migration = (MIGRATIONS / "0035_sas_operator_attestation.sql").read_text(
        encoding="utf-8"
    )
    assert "NOT CRYPTOGRAPHIC VERIFICATION" in migration
    assert "unverified_manual_execution" in migration


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"confirmed": False}, "must affirm"),
        ({"operator_name": "  "}, "named operator"),
        ({"operator_organization": ""}, "operating organisation"),
        ({"archive_sha256": "short"}, "archive hash"),
    ],
)
def test_a_worthless_attestation_is_refused(override, expected):
    with pytest.raises(AttestationRejected, match=expected):
        attestation(**override)


def test_optional_fields_stay_optional():
    """An operator may legitimately not know these, and a required field people
    fill with "unknown" is worse than an absent one."""
    recorded = attestation(sas_version=None, operating_environment=None)
    assert recorded.sas_version is None
    assert recorded.operating_environment is None


# ================ 6. the operator and the reviewer are different people ===


def test_the_operator_is_declared_metadata_not_a_platform_identity():
    """The person with the SAS licence is usually in the client organisation
    and has no account here. Minting a user id for them would put a fiction in
    the audit trail that every later reader would have to un-learn."""
    migration = (MIGRATIONS / "0035_sas_operator_attestation.sql").read_text(
        encoding="utf-8"
    )
    table = migration[migration.index("create table public.sas_operator_attestations") :]

    operator = next(
        line for line in table.splitlines() if line.strip().startswith("operator_name")
    )
    assert "text" in operator
    assert "references" not in operator

    # The SUBMITTER is a real account, and is a separate column.
    submitter = next(
        line for line in table.splitlines() if line.strip().startswith("submitted_by")
    )
    assert "references public.profiles(id)" in submitter


def test_submitting_an_attestation_is_not_reviewing():
    """Different actions, so a query for "who approved what" cannot pick up an
    operator's declaration."""
    from app.sas_validation.repository import (
        ACTION_ATTESTATION_RECORDED,
        ACTION_REVIEW_ACCEPTED,
        ACTION_REVIEW_REJECTED,
        AUDIT_ACTIONS,
    )

    assert ACTION_ATTESTATION_RECORDED in AUDIT_ACTIONS
    assert ACTION_ATTESTATION_RECORDED not in (
        ACTION_REVIEW_ACCEPTED,
        ACTION_REVIEW_REJECTED,
    )


# ============ 17. a fixture is never regulatory evidence, whatever it says ===


def test_a_fixture_is_not_regulatory_evidence():
    assert EvidenceOrigin.TEST_FIXTURE.is_regulatory_evidence is False
    assert EvidenceOrigin.MANUAL_EXTERNAL_SAS.is_regulatory_evidence is True


def test_a_dry_run_report_says_so_before_it_says_anything_else():
    """The numbers below the banner look exactly like real ones. That is what a
    fixture is for, and why the banner has to come first."""
    report = build_evidence_report(
        run={
            "id": "run-1",
            "evidence_origin": "test_fixture",
            "denominator_df": 19.8906,
            "comparison": {"integrity": {"package_integrity": "verified"}},
        },
        package={"id": PACKAGE_ID},
    )

    assert report.is_regulatory_evidence is False
    assert report.banner == DRY_RUN_BANNER
    assert "NOT SAS VALIDATION EVIDENCE" in report.banner


def test_a_real_run_carries_no_banner():
    report = build_evidence_report(
        run={"id": "run-2", "evidence_origin": "manual_external_sas"},
        package={"id": PACKAGE_ID},
    )
    assert report.is_regulatory_evidence is True
    assert report.banner is None


def test_an_unknown_or_missing_origin_is_treated_as_a_fixture():
    """The safe direction. A row with no origin predates the column, which
    means no licensed SAS result had been collected."""
    for origin in (None, "", "something_else"):
        report = build_evidence_report(
            run={"id": "r", "evidence_origin": origin}, package={}
        )
        assert report.evidence_origin is EvidenceOrigin.TEST_FIXTURE


def test_no_code_path_infers_the_origin_from_file_content():
    """'It parsed, so it must be real' is how a dry-run artefact ends up in a
    regulatory record. The origin is declared by the caller, never derived."""
    workflow = (SAS_PACKAGE / "workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(workflow)

    upload = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload_result"
    )
    names = {
        argument.arg
        for argument in upload.args.kwonlyargs
    }
    assert "evidence_origin" in names

    # And it has no default, so every caller must state it.
    defaults = dict(
        zip(upload.args.kwonlyargs, upload.args.kw_defaults, strict=True)
    )
    origin_default = next(
        default
        for argument, default in defaults.items()
        if argument.arg == "evidence_origin"
    )
    assert origin_default is None, "evidence_origin must not have a default"


def test_the_stored_origin_cannot_be_changed_by_a_later_write():
    """The laundering step this column exists to prevent: a second upsert that
    flips a run from test_fixture to manual_external_sas."""
    repository = (SAS_PACKAGE / "repository.py").read_text(encoding="utf-8")
    update_clause = repository[
        repository.index("on conflict (id) do update set") : repository.index(
            "returning id"
        )
    ]
    assert "evidence_origin" not in update_clause.replace(
        "-- evidence_origin is deliberately NOT updated. It is", ""
    )


# ========================= 12. what an acceptance does and does not mean ===


def test_the_report_carries_the_decision_semantics_with_it():
    assert "ORACLE EVIDENCE" in DECISION_SEMANTICS["accepted_means"]
    not_meant = DECISION_SEMANTICS["accepted_does_not_mean"]
    assert "the statistical method is implemented" in not_meant
    assert "the statistical method is validated" in not_meant
    assert "FDA has confirmed the denominator df" in not_meant
    assert "partial_oracle_ready may be set true" in not_meant


def test_the_reference_values_keep_their_labels_in_the_report():
    """19.8906 and 22.5403 are candidates, not targets. A report that printed
    either as "expected" would turn an open question into an answer key."""
    report = build_evidence_report(
        run={
            "id": "run-3",
            "evidence_origin": "manual_external_sas",
            "comparison": {
                "integrity": {},
                "reference_context": [
                    {
                        "quantity": "denominator_df",
                        "value": 19.8906,
                        "evidence_status": "independent_candidate",
                        "regulator_confirmed": False,
                    }
                ],
            },
        },
        package={"id": PACKAGE_ID},
    )
    reference = report.reference_context[0]
    assert reference["regulator_confirmed"] is False
    assert reference["evidence_status"] == "independent_candidate"


def test_the_runbook_names_the_only_line_an_operator_may_change():
    """A runbook that named the wrong macro variable would cost an operator an
    afternoon, and would invite them to edit something else to make it work."""
    from app.sas_validation.program import generate_program

    runbook = (
        BACKEND.parent / "docs" / "SAS_FIRST_LIVE_RUN.md"
    ).read_text(encoding="utf-8")
    assert "packagedir" in runbook

    # And that is genuinely what the generated program says.
    program = generate_program(
        case_id="FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II",
        dataset_filename="dataset.csv",
        dataset_sha256="c" * 64,
        result_filename="be_result.csv",
    )
    assert "%let packagedir" in program.text
    assert "ONLY line you should change" in program.text


def test_the_runbook_does_not_tell_the_operator_what_answer_to_expect():
    """The whole point of the first live run is that the answer is open.

    A runbook naming 19.8906 or 22.5403 as expected would prime an operator to
    treat a different result as a mistake to be fixed.
    """
    runbook = (
        BACKEND.parent / "docs" / "SAS_FIRST_LIVE_RUN.md"
    ).read_text(encoding="utf-8")

    operator_section = runbook[
        runbook.index("## 3. Operator runbook") : runbook.index(
            "## 4. Operator attestation"
        )
    ]
    for candidate in ("19.8906", "22.5403", "102.26"):
        assert candidate not in operator_section, (
            f"{candidate} appears in the operator instructions; an operator "
            "must not be told what to expect"
        )


def test_the_documented_statuses_are_still_the_conservative_ones():
    """Section 18. Unchanged by this milestone, and unchanged even if the
    first live run succeeds perfectly."""
    runbook = (
        BACKEND.parent / "docs" / "SAS_FIRST_LIVE_RUN.md"
    ).read_text(encoding="utf-8")

    assert "FDA_REPLICATE_STANDARD_ABE_FULL     IMPLEMENTED_UNVALIDATED" in runbook
    assert "FDA_REPLICATE_STANDARD_ABE_PARTIAL  NOT_IMPLEMENTED" in runbook
    assert "FDA_NTI_RSABE                       IMPLEMENTED_UNVALIDATED" in runbook
    assert "partial_oracle_ready                false" in runbook


def test_one_accepted_run_is_not_documented_as_validation():
    runbook = (
        BACKEND.parent / "docs" / "SAS_FIRST_LIVE_RUN.md"
    ).read_text(encoding="utf-8")
    assert "one accepted SAS run   ≠   method VALIDATED" in runbook


def test_verified_execution_integrity_is_not_required_for_acceptance():
    """Section 10. It cannot be achieved on this path, so requiring it would
    make acceptance impossible for every honest run."""
    runbook = (
        BACKEND.parent / "docs" / "SAS_FIRST_LIVE_RUN.md"
    ).read_text(encoding="utf-8")
    criteria = runbook[
        runbook.index("## 5. What would count as strong") : runbook.index(
            "## 6. One good run"
        )
    ]
    assert "### Not required" in criteria
    assert "program_execution_integrity = VERIFIED" in criteria


def test_the_statistics_section_says_the_numbers_are_what_sas_reported():
    report = build_evidence_report(
        run={"id": "r", "evidence_origin": "manual_external_sas", "denominator_df": 1.0},
        package={},
    )
    assert "as reported by SAS" in report.statistics["source"]
