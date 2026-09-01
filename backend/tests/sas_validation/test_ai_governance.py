"""AI may recommend. AI must not be the final approver.

HOW THAT IS ENFORCED, AND WHY IT IS NOT A POLICY

A rule written only in documentation is a rule that holds until someone is in a
hurry. This one is enforced by vocabulary: `AIRecommendation` and
`OracleClosureDecision` are disjoint enums, so there is no value the assistant
can produce that means "accepted". The model is not trusted to stay on the
right side of the line - it is given a language in which the wrong side cannot
be expressed.

These tests assert that separation holds, that the AI cannot reach any
regulatory state, and that its absence never blocks a human.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.sas_validation.ai_reviewer import (
    ADVISORY_LABEL,
    AI_REVIEW_MISCONFIGURED,
    AI_REVIEW_UNAVAILABLE,
    AIConfidence,
    AIRecommendation,
    AIReviewResponse,
    ModelProviderReviewAdapter,
    SASValidationAIReviewer,
    build_prompt,
)
from app.sas_validation.authorization import ActorType, ReviewerIdentity
from app.sas_validation.human_review import (
    AcceptancePreconditions,
    OracleClosureDecision,
    prepare_review,
)
from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    ProgramExecutionIntegrity,
)

BACKEND = Path(__file__).resolve().parents[2]
SAS_PACKAGE = BACKEND / "app" / "sas_validation"


def sound_preconditions(**overrides) -> AcceptancePreconditions:
    fields = {
        "package_integrity": PackageIntegrity.VERIFIED,
        "dataset_provenance": DatasetProvenance.MATCH,
        "case_stamp": DatasetProvenance.MATCH,
        "program_execution": (
            ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION
        ),
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


def reviewer() -> ReviewerIdentity:
    return ReviewerIdentity.for_human(
        user_id="human-1", role_key="system_administrator"
    )


# ------------------------------------------ the enums cannot overlap ---


def test_the_ai_and_human_vocabularies_share_no_value():
    """The whole enforcement mechanism, in one assertion.

    If these ever intersected, an AI recommendation could be stored in a human
    decision column by a single mistaken assignment.
    """
    ai_values = {member.value for member in AIRecommendation}
    human_values = {member.value for member in OracleClosureDecision}

    assert not (ai_values & human_values)
    assert "oracle_closure_accepted" not in ai_values
    assert "oracle_closure_rejected" not in ai_values


def test_the_ai_has_no_way_to_express_acceptance():
    """Its nearest option asserts only that a person's time is not wasted."""
    assert AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW.value == (
        "acceptable_for_human_review"
    )
    for member in AIRecommendation:
        assert "accepted" not in member.value
        assert "approve" not in member.value


def test_the_ai_response_model_carries_no_decision_field():
    """A field called `decision` would eventually be read as one."""
    fields = set(AIReviewResponse.model_fields)
    for forbidden in ("decision", "approved", "accepted", "oracle_closure"):
        assert forbidden not in fields
    assert fields >= {"recommendation", "requires_human_review", "confidence"}


def test_every_ai_response_says_a_human_is_required():
    response = AIReviewResponse(
        summary="…",
        recommendation=AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW,
        recommendation_reason="…",
        confidence=AIConfidence.HIGH,
    )
    assert response.requires_human_review is True


# ------------------------------- the AI cannot reach regulatory state ---


def test_the_ai_module_cannot_touch_a_validation_status():
    """Checked by import graph, not by intention."""
    tree = ast.parse((SAS_PACKAGE / "ai_reviewer.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert not any(name.startswith("be_stats") for name in imported)
    source = (SAS_PACKAGE / "ai_reviewer.py").read_text(encoding="utf-8")
    for forbidden in (
        "partial_oracle_ready",
        "ValidationStatus",
        "CAPABILITY_VALIDATION",
        "NOT_IMPLEMENTED",
    ):
        assert forbidden not in source


def test_the_ai_module_writes_nothing():
    """It analyses and returns. It has no repository and no persistence call."""
    source = (SAS_PACKAGE / "ai_reviewer.py").read_text(encoding="utf-8")
    for forbidden in ("execute(", "commit(", "insert into", "upsert_run"):
        assert forbidden not in source


def test_the_ai_cannot_invoke_the_human_review_mutation():
    """`ai_reviewer` must not import the module that records decisions.

    Checked by import graph and call name, not by substring: the AI's own
    recommendation value is `acceptable_for_human_review`, which contains
    "human_review" and made a naive search fail. That is the same blunt-search
    mistake PR #64 made with "validation_status", and the same fix applies.
    """
    tree = ast.parse((SAS_PACKAGE / "ai_reviewer.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "human_review" not in node.module, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "human_review" not in alias.name, alias.name

        # And no call to the function that assembles a governed decision.
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(
                node.func, "attr", None
            )
            assert name != "prepare_review"


def test_no_human_review_can_be_prepared_by_a_non_human_identity():
    for actor in (ActorType.AI_SYSTEM, ActorType.SYSTEM):
        with pytest.raises(PermissionError):
            ReviewerIdentity.for_human(
                user_id="bot-1", role_key="system_administrator",
                actor_type=actor,
            )


# ------------------------------- the AI does not control the outcome ---


@pytest.mark.parametrize(
    "recommendation",
    [
        AIRecommendation.REJECT_RECOMMENDED,
        AIRecommendation.INSUFFICIENT_EVIDENCE,
        AIRecommendation.ESCALATE_TO_STATISTICIAN,
    ],
)
def test_a_human_may_accept_against_the_ai_recommendation(recommendation):
    """Disagreement is allowed in both directions and recorded.

    A system that required the human to agree would have made the AI the
    approver by another route.
    """
    record = prepare_review(
        reviewer=reviewer(),
        run_id="run-1",
        tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
        notes="The df matches the independent candidate and the CI reproduces "
              "the published interval; I judge the evidence sufficient.",
        acknowledged=True,
        preconditions=sound_preconditions(),
        evidence_snapshot={},
        evidence_snapshot_hash="a" * 64,
        ai_recommendation=recommendation,
    )
    assert record.decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
    assert record.ai_recommendation_at_time is recommendation
    assert record.disagreed_with_ai is True


def test_a_human_may_reject_what_the_ai_found_acceptable():
    record = prepare_review(
        reviewer=reviewer(),
        run_id="run-1",
        tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
        notes="The SAS version predates the one our protocol specifies.",
        acknowledged=False,
        preconditions=sound_preconditions(),
        evidence_snapshot={},
        evidence_snapshot_hash="a" * 64,
        ai_recommendation=AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW,
    )
    assert record.decision is OracleClosureDecision.ORACLE_CLOSURE_REJECTED
    assert record.disagreed_with_ai is True


def test_agreement_is_recorded_as_agreement():
    record = prepare_review(
        reviewer=reviewer(),
        run_id="run-1", tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
        notes="Concur with the analysis.",
        acknowledged=True,
        preconditions=sound_preconditions(),
        evidence_snapshot={}, evidence_snapshot_hash="a" * 64,
        ai_recommendation=AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW,
    )
    assert record.disagreed_with_ai is False


# ---------------------------------- an absent assistant blocks nothing ---


@pytest.mark.asyncio
async def test_no_provider_yields_an_unavailable_outcome_not_an_error():
    """A regulatory review must not be blocked by an LLM outage."""
    outcome = await SASValidationAIReviewer(provider=None).review({"a": 1})

    assert outcome.succeeded is False
    assert AI_REVIEW_UNAVAILABLE in str(outcome.failure_reason)
    assert outcome.response is None
    assert outcome.evidence_snapshot_hash


@pytest.mark.asyncio
async def test_a_failing_provider_is_a_state_not_an_exception():
    class Exploding:
        async def complete_structured(self, **kwargs):
            raise RuntimeError("model gateway timed out")

    outcome = await SASValidationAIReviewer(provider=Exploding()).review({"a": 1})
    assert outcome.succeeded is False
    assert "model gateway timed out" in str(outcome.failure_reason)


# ------------------------------- a wiring bug must not look like an outage ---


@pytest.mark.asyncio
async def test_a_provider_with_the_wrong_signature_is_reported_as_misconfigured():
    """The catch-all above is right for an outage and wrong for a wiring bug.

    `app/llm/provider.py::ModelProvider` takes `role`/`instructions`/
    `user_input`, not `schema`/`system`/`prompt`. Passing it directly would
    raise TypeError on every call, and reporting that as AI_REVIEW_UNAVAILABLE
    would leave the assistant permanently absent with nothing saying why.
    """

    class WrongSignature:
        async def complete_structured(self, *, role, schema, instructions, user_input):
            raise AssertionError("unreachable - the call never matches")

    outcome = await SASValidationAIReviewer(provider=WrongSignature()).review({})

    assert outcome.succeeded is False
    assert AI_REVIEW_MISCONFIGURED in str(outcome.failure_reason)
    assert AI_REVIEW_UNAVAILABLE not in str(outcome.failure_reason)


@pytest.mark.asyncio
async def test_the_adapter_makes_the_application_provider_usable():
    """And the adapter is what makes the real ModelProvider work.

    It is checked against the SHAPE `ModelProvider` actually has - keyword
    names in, `.output` and `.usage.model` out - so a change to either side
    fails here rather than silently in production.
    """
    seen: dict[str, object] = {}

    class Usage:
        model = "a-configured-model"

    class Result:
        output = AIReviewResponse(
            summary="The reported interval reproduces the published one.",
            recommendation=AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW,
            recommendation_reason="No material discrepancy was detected.",
            confidence=AIConfidence.MEDIUM,
        )
        usage = Usage()

    class FakeModelProvider:
        async def complete_structured(self, **kwargs):
            seen.update(kwargs)
            return Result()

    reviewer_service = SASValidationAIReviewer(
        provider=ModelProviderReviewAdapter(FakeModelProvider())
    )
    outcome = await reviewer_service.review({"validation_case": "X"})

    assert outcome.succeeded is True
    assert outcome.model_name == "a-configured-model"
    assert seen["schema"] is AIReviewResponse
    assert set(seen) >= {"role", "schema", "instructions", "user_input"}


def test_a_human_can_decide_with_no_ai_review_at_all():
    record = prepare_review(
        reviewer=reviewer(),
        run_id="run-1", tenant_id="t-1",
        decision=OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
        notes="Assistant unavailable; reviewed the deterministic evidence.",
        acknowledged=True,
        preconditions=sound_preconditions(),
        evidence_snapshot={}, evidence_snapshot_hash="a" * 64,
        ai_review_id=None,
        ai_recommendation=None,
    )
    assert record.ai_review_id is None
    assert record.disagreed_with_ai is None


# ------------------------------------------- versioning, not replacing ---


@pytest.mark.asyncio
async def test_two_reviews_of_the_same_evidence_are_distinct_artefacts():
    """Model output is non-deterministic, so a re-run is a new version.

    The evidence hash is stable, which is what lets two analyses of the same
    evidence be compared; the responses themselves may differ.
    """
    class Stub:
        provider_name = "stub"

        def __init__(self, text: str) -> None:
            self.text = text

        async def complete_structured(self, **kwargs):
            return AIReviewResponse(
                summary=self.text,
                recommendation=AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW,
                recommendation_reason="…",
                confidence=AIConfidence.MEDIUM,
            )

    evidence = {"denominator_df": 19.8906}
    first = await SASValidationAIReviewer(Stub("first opinion")).review(evidence)
    second = await SASValidationAIReviewer(Stub("second opinion")).review(evidence)

    assert first.evidence_snapshot_hash == second.evidence_snapshot_hash
    assert first.response_hash() != second.response_hash()


# -------------------------------------------------- prompt discipline ---


def test_the_prompt_separates_settled_facts_from_interpretation():
    prompt = build_prompt(
        {
            "program_execution_integrity": "unverified_manual_execution",
            "denominator_df": 19.8906,
        }
    )
    assert "FACTS" in prompt
    assert "do not revise" in prompt
    assert "INTERPRETATION REQUESTED" in prompt
    assert "may disagree with you" in prompt


def test_the_system_prompt_forbids_calling_a_candidate_the_regulator_value():
    """The specific misreading that would corrupt this record.

    19.8906 is our own candidate. A summary calling it "the regulator value"
    would invert the evidence hierarchy three PRs were spent establishing.
    """
    from app.sas_validation.ai_reviewer import SYSTEM_PROMPT

    assert "the regulator value" in SYSTEM_PROMPT
    assert "Never refer to such a value" in SYSTEM_PROMPT
    assert "UNVERIFIED_MANUAL_EXECUTION" in SYSTEM_PROMPT
    assert "not a defect" in SYSTEM_PROMPT.lower()


def test_the_advisory_label_is_unambiguous():
    assert "not an approval" in ADVISORY_LABEL
