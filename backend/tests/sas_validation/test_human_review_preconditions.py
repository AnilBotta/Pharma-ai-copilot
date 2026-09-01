"""What must hold before acceptance, and what accepting does not mean.

WHY THE MACHINE CHECKS PRECONDITIONS AT ALL

A reviewer with the authority to accept evidence should weigh it however their
expertise directs - that is the point of having one. But a decision recorded
against evidence that is incomplete, mismatched or non-converged is not a
judgement call; it is a record that will not survive being read back.

So the machine refuses the states where acceptance could not be meaningful,
and leaves every genuine judgement to the person.

REJECTION HAS NO PRECONDITIONS

A reviewer must always be able to reject. Requiring complete evidence first
would trap a run in limbo exactly when something is wrong with it.
"""

from __future__ import annotations

import pytest

from app.sas_validation.ai_reviewer import AIRecommendation
from app.sas_validation.attestation import EvidenceOrigin
from app.sas_validation.authorization import ReviewerIdentity
from app.sas_validation.human_review import (
    ACCEPTANCE_MEANING,
    ACKNOWLEDGEMENT_HASH,
    ACKNOWLEDGEMENT_TEXT,
    ACKNOWLEDGEMENT_VERSION,
    AcceptancePreconditions,
    OracleClosureDecision,
    PreconditionFailed,
    build_evidence_snapshot,
    prepare_review,
)
from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    ProgramExecutionIntegrity,
)

REVIEWER = ReviewerIdentity.for_human(
    user_id="human-1", role_key="system_administrator"
)


def preconditions(**overrides) -> AcceptancePreconditions:
    fields = {
        # A sound REAL run, so these tests exercise whether GOOD EVIDENCE is
        # accepted. Whether a fixture can be accepted at all is a different
        # question, answered in test_first_live_run_readiness.py.
        "evidence_origin": EvidenceOrigin.MANUAL_EXTERNAL_SAS,
        "package_integrity": PackageIntegrity.VERIFIED,
        "dataset_provenance": DatasetProvenance.MATCH,
        "case_stamp": DatasetProvenance.MATCH,
        "program_execution": ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION,
        "result_complete": True,
        "sas_version_present": True,
        "denominator_df_present": True,
        "confidence_interval_present": True,
        "convergence_failed": False,
        "comparison_available": True,
        "acknowledged": True,
    }
    fields.update(overrides)
    return AcceptancePreconditions(**fields)


def accept(**overrides):
    kwargs = {
        "reviewer": REVIEWER,
        "run_id": "run-1",
        "tenant_id": "t-1",
        "decision": OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
        "notes": "Reproduces the published interval; evidence is sufficient.",
        "acknowledged": True,
        "preconditions": preconditions(),
        "evidence_snapshot": {},
        "evidence_snapshot_hash": "a" * 64,
    }
    kwargs.update(overrides)
    return prepare_review(**kwargs)


# ------------------------------------------------- acceptance may proceed ---


def test_a_sound_manual_run_can_be_accepted():
    """The intended happy path, INCLUDING unverifiable manual execution.

    That qualification is permanent for customer-run SAS. If it blocked
    acceptance, no manual run could ever be accepted and the feature would have
    no purpose.
    """
    record = accept()

    assert record.decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
    assert (
        record.evidence_snapshot_hash == "a" * 64
    )
    assert record.acknowledgement_version == ACKNOWLEDGEMENT_VERSION
    assert record.acknowledgement_hash == ACKNOWLEDGEMENT_HASH


def test_unverifiable_manual_execution_is_not_a_precondition_failure():
    assert preconditions().acceptable
    assert (
        preconditions().program_execution
        is ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION
    )


# ------------------------------------------------- acceptance is refused ---


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"dataset_provenance": DatasetProvenance.MISMATCH}, "dataset provenance"),
        ({"dataset_provenance": DatasetProvenance.MISSING}, "dataset provenance"),
        ({"case_stamp": DatasetProvenance.MISMATCH}, "validation case stamp"),
        ({"case_stamp": DatasetProvenance.MISSING}, "validation case stamp"),
        ({"package_integrity": PackageIntegrity.ABSENT}, "package archive"),
        ({"result_complete": False}, "incomplete"),
        ({"denominator_df_present": False}, "denominator df"),
        ({"confidence_interval_present": False}, "confidence interval"),
        ({"sas_version_present": False}, "SAS version"),
        ({"convergence_failed": True}, "non-converged"),
        ({"comparison_available": False}, "no comparison"),
        ({"acknowledged": False}, "acknowledgement"),
    ],
)
def test_acceptance_is_refused_when_the_evidence_cannot_support_it(
    override, expected
):
    with pytest.raises(PreconditionFailed) as error:
        accept(preconditions=preconditions(**override))
    assert expected in str(error.value)


def test_every_unmet_condition_is_reported_at_once():
    """A reviewer fixing an upload should not find the problems one at a time."""
    failures = preconditions(
        result_complete=False,
        denominator_df_present=False,
        acknowledged=False,
    ).failures()
    assert len(failures) == 3


# --------------------------------------------------- rejection is always ---


@pytest.mark.parametrize(
    "override",
    [
        {"dataset_provenance": DatasetProvenance.MISMATCH},
        {"result_complete": False},
        {"convergence_failed": True},
        {"comparison_available": False},
    ],
)
def test_rejection_is_possible_whatever_the_evidence_shows(override):
    """Otherwise a broken run could never be closed out."""
    record = prepare_review(
        reviewer=REVIEWER,
        run_id="run-1",
        tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
        notes="Provenance does not match; this is not evidence about our package.",
        acknowledged=False,
        preconditions=preconditions(**override),
        evidence_snapshot={},
        evidence_snapshot_hash="a" * 64,
    )
    assert record.decision is OracleClosureDecision.ORACLE_CLOSURE_REJECTED


def test_the_schema_permits_the_rejection_shape_the_domain_produces():
    """The bug this pair of layers had, caught without a database.

    `prepare_review` correctly returns null acknowledgement fields for a
    rejection. Migration 0034 originally declared those three columns NOT NULL,
    so every rejection failed at insert - and neither layer's own tests could
    see it, because each was right about its own half.

    `tests/db/test_human_review_persistence.py` proves the fixed behaviour
    against the real server. This is the cheap guard that runs by default, so a
    future edit reintroducing NOT NULL fails here rather than in production.
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/0034_sas_validation_review.sql"
    ).read_text(encoding="utf-8")

    table = migration[
        migration.index("create table public.sas_human_reviews") : migration.index(
            "create index sas_human_reviews_run_idx"
        )
    ]

    for column in (
        "acknowledgement_version",
        "acknowledgement_text",
        "acknowledgement_hash",
    ):
        declaration = next(
            line for line in table.splitlines() if line.strip().startswith(column)
        )
        assert "not null" not in declaration, declaration

    # Nullable is only half of it. Without the decision-dependent constraint,
    # an ACCEPTANCE with no acknowledgement would also become storable, which
    # is the opposite failure.
    assert "sas_human_reviews_acknowledgement_matches_decision" in table
    assert "decision = 'oracle_closure_accepted'" in table
    assert "decision = 'oracle_closure_rejected'" in table
    # The hash is still required to be a hash where it is present.
    assert "acknowledgement_hash ~ '^[0-9a-f]{64}$'" in table
    # And the evidence snapshot hash is required for BOTH decisions: a
    # rejection also has to say what it was a rejection of.
    assert "sas_human_reviews_evidence_hash_is_a_hash" in table


def test_a_rejection_carries_no_acceptance_acknowledgement():
    """The acknowledgement is a statement about accepting unverifiable
    execution. Attaching it to a rejection would be nonsense in the record."""
    record = prepare_review(
        reviewer=REVIEWER, run_id="run-1", tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
        notes="Non-converged fit.",
        acknowledged=False,
        preconditions=preconditions(convergence_failed=True),
        evidence_snapshot={}, evidence_snapshot_hash="a" * 64,
    )
    assert record.acknowledgement_text is None
    assert record.acknowledgement_hash is None


# ------------------------------------------------------------- notes ---


@pytest.mark.parametrize("notes", ["", "   ", "\n\t"])
@pytest.mark.parametrize(
    "decision",
    [
        OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
        OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
    ],
)
def test_notes_are_required_for_both_decisions(notes, decision):
    with pytest.raises(ValueError, match="notes are required"):
        prepare_review(
            reviewer=REVIEWER, run_id="run-1", tenant_id="t-1",
            decision=decision, notes=notes, acknowledged=True,
            preconditions=preconditions(),
            evidence_snapshot={}, evidence_snapshot_hash="a" * 64,
        )


# ------------------------------------------- the acknowledgement itself ---


def test_the_acknowledgement_says_what_cannot_be_verified():
    """A reviewer must accept the actual limitation, in words."""
    assert "customer-controlled environment" in ACKNOWLEDGEMENT_TEXT
    assert "cannot cryptographically verify" in ACKNOWLEDGEMENT_TEXT
    assert "suitable oracle evidence" in ACKNOWLEDGEMENT_TEXT


def test_it_is_not_the_environment_acknowledgement():
    """Two acknowledgements exist and they say opposite-sized things.

    `modes.ENVIRONMENT_ACKNOWLEDGEMENT_TEXT` is "we are authorised to use this
    SAS", shown before connecting an environment. This one is "I accept that
    the executed program cannot be verified", which is a governed statement
    stored with a hash. Both were called ACKNOWLEDGEMENT_TEXT until PR #66, and
    the review endpoint imported the wrong one.
    """
    from app.sas_validation.modes import ENVIRONMENT_ACKNOWLEDGEMENT_TEXT

    assert ACKNOWLEDGEMENT_TEXT != ENVIRONMENT_ACKNOWLEDGEMENT_TEXT
    assert "cannot cryptographically verify" not in ENVIRONMENT_ACKNOWLEDGEMENT_TEXT

    from app.sas_validation import routes

    assert routes.ACKNOWLEDGEMENT_TEXT == ACKNOWLEDGEMENT_TEXT


def test_the_acknowledgement_is_versioned_and_hashed():
    """So "what exactly did this person agree to" survives a later edit."""
    import hashlib

    assert ACKNOWLEDGEMENT_VERSION.startswith("oracle-closure-acknowledgement/")
    assert (
        ACKNOWLEDGEMENT_HASH
        == hashlib.sha256(ACKNOWLEDGEMENT_TEXT.encode("utf-8")).hexdigest()
    )


# ---------------------------------------------------- evidence snapshot ---


def test_the_snapshot_records_what_was_approved():
    snapshot, digest = build_evidence_snapshot(
        run={
            "case_id": "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II",
            "sas_version": "9.04.01M8",
            "denominator_df": 19.8906,
            "ci_lower_ratio": 97.05,
            "ci_upper_ratio": 107.76,
            "convergence_status": "0",
            "status": "review_required",
            "comparison": {"integrity": {"program_execution_integrity": "x"}},
        },
        package={
            "id": "p" * 64,
            "archive_sha256": "b" * 64,
            "dataset_sha256": "c" * 64,
            "program_sha256": "d" * 64,
        },
        artifacts=[
            {"kind": "result_file", "content_sha256": "e" * 64},
            {"kind": "sas_log", "content_sha256": "f" * 64},
        ],
        ai_review_id="ai-1",
        ai_review_hash="9" * 64,
    )

    assert snapshot["archive_sha256"] == "b" * 64
    assert snapshot["denominator_df"] == 19.8906
    assert len(snapshot["artifacts"]) == 2
    assert snapshot["ai_review_id"] == "ai-1"
    assert len(digest) == 64


def test_the_snapshot_hash_is_order_independent():
    """Two identical snapshots must hash the same however the artefacts arrive."""
    args = {
        "run": {"case_id": "X"},
        "package": {"id": "p"},
        "ai_review_id": None,
        "ai_review_hash": None,
    }
    first = build_evidence_snapshot(
        artifacts=[
            {"kind": "sas_log", "content_sha256": "f" * 64},
            {"kind": "result_file", "content_sha256": "e" * 64},
        ],
        **args,
    )[1]
    second = build_evidence_snapshot(
        artifacts=[
            {"kind": "result_file", "content_sha256": "e" * 64},
            {"kind": "sas_log", "content_sha256": "f" * 64},
        ],
        **args,
    )[1]
    assert first == second


def test_the_snapshot_carries_hashes_not_file_contents():
    """An artefact is identified without being reproduced."""
    snapshot, _ = build_evidence_snapshot(
        run={}, package={},
        artifacts=[{"kind": "result_file", "content_sha256": "e" * 64}],
        ai_review_id=None, ai_review_hash=None,
    )
    serialised = str(snapshot)
    assert "section,name,value" not in serialised
    assert "e" * 64 in serialised


# ------------------------------- accepting changes no regulatory status ---


def test_accepting_does_not_claim_to_validate_anything():
    assert "does not implement or validate any method" in ACCEPTANCE_MEANING
    assert "NOT_IMPLEMENTED" in ACCEPTANCE_MEANING
    assert "partial_oracle_ready remains false" in ACCEPTANCE_MEANING


def test_the_review_module_cannot_reach_a_validation_status():
    """Structural: the module that records acceptance never imports the
    machinery that could promote a method."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[2]
        / "app/sas_validation/human_review.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("be_stats"), node.module


def test_an_ai_recommendation_is_recorded_but_never_required():
    record = accept(ai_recommendation=AIRecommendation.REJECT_RECOMMENDED)
    assert record.ai_recommendation_at_time is AIRecommendation.REJECT_RECOMMENDED
    assert record.decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
