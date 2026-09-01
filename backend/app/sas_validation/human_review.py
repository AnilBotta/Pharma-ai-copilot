"""The governed decision: preconditions, acknowledgement, and what was approved.

WHAT AN ACCEPTED REVIEW MEANS, AND WHAT IT DOES NOT

    "This SAS run is accepted as suitable ORACLE EVIDENCE."

That is all. It does not change `FDA_REPLICATE_STANDARD_ABE_PARTIAL`, does not
set `partial_oracle_ready`, and does not promote anything to VALIDATED.
Implementing and validating the statistical method is a separate task with its
own governance, and nothing in this module can begin it.

`test_ai_governance.py` asserts that no code path here touches a validation
status, because the temptation to wire "accepted" to "validated" is exactly
what a reviewer would expect this feature to do.

WHY PRECONDITIONS ARE CHECKED SERVER-SIDE RATHER THAN LEFT TO JUDGEMENT

A human reviewer may weigh evidence however their expertise directs - that is
the point of having one. But a decision recorded against evidence that is
incomplete, mismatched or non-converged is not a judgement call; it is a record
that will not survive being read back. So the machine refuses the states where
acceptance could not be meaningful, and leaves every genuine judgement to the
person.

Rejection has no preconditions. A reviewer must always be able to reject, and
requiring complete evidence before allowing that would trap a run in limbo
precisely when something is wrong with it.

THE SNAPSHOT ANSWERS ONE QUESTION LATER

    "What exactly did this human approve?"

A decision referencing only a run id becomes uninterpretable the moment
anything about the run is re-read. The snapshot fixes the evidence as it stood,
hashes it, and stores both.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.sas_validation.ai_reviewer import AIRecommendation
from app.sas_validation.authorization import ActorType, ReviewerIdentity
from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    ProgramExecutionIntegrity,
)
from app.sas_validation.modes import OracleClosureDecision

#: What a human may actually RECORD here, which is narrower than the enum.
#:
#: `OracleClosureDecision` is defined once, in modes.py, and re-exported from
#: this module - a second same-named enum would compare unequal under `is`
#: against the one service.py already uses, and the two would drift apart
#: without anything failing loudly.
#:
#: NOT_ASSESSED is the ABSENCE of a review, so it is not a verdict a reviewer
#: may submit; `prepare_review` refuses it below.
RECORDABLE_DECISIONS = (
    OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
    OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
)


#: Bumped whenever the wording changes, and stored with every acceptance, so
#: "what exactly did this person agree to" survives a later edit.
ACKNOWLEDGEMENT_VERSION = "oracle-closure-acknowledgement/1"

ACKNOWLEDGEMENT_TEXT = (
    "I reviewed the deterministic evidence and AI-assisted analysis. I "
    "understand that the SAS execution occurred in a customer-controlled "
    "environment and that the application cannot cryptographically verify the "
    "exact SAS program bytes executed. I accept this SAS run as suitable "
    "oracle evidence for subsequent statistical implementation/validation work."
)

ACKNOWLEDGEMENT_HASH = hashlib.sha256(
    ACKNOWLEDGEMENT_TEXT.encode("utf-8")
).hexdigest()


class PreconditionFailed(ValueError):
    """Acceptance was refused because the evidence cannot support it."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = tuple(failures)
        super().__init__(
            "This run cannot be accepted as oracle evidence:\n  - "
            + "\n  - ".join(failures)
        )


@dataclass(frozen=True, slots=True)
class AcceptancePreconditions:
    """What must hold before acceptance is even offered."""

    package_integrity: PackageIntegrity
    dataset_provenance: DatasetProvenance
    case_stamp: DatasetProvenance
    program_execution: ProgramExecutionIntegrity
    result_complete: bool
    sas_version_present: bool
    denominator_df_present: bool
    confidence_interval_present: bool
    convergence_failed: bool
    comparison_available: bool
    acknowledged: bool

    def failures(self) -> list[str]:
        """Every unmet condition, not just the first.

        A reviewer fixing an upload should not discover the problems one
        attempt at a time.
        """
        problems: list[str] = []

        if self.package_integrity is not PackageIntegrity.VERIFIED:
            problems.append(
                f"package archive integrity is {self.package_integrity.value}, "
                "not verified"
            )
        if self.dataset_provenance is not DatasetProvenance.MATCH:
            problems.append(
                f"dataset provenance is {self.dataset_provenance.value} - the "
                "result does not identify this package's dataset"
            )
        if self.case_stamp is not DatasetProvenance.MATCH:
            problems.append(
                f"validation case stamp is {self.case_stamp.value}"
            )
        if not self.result_complete:
            problems.append("the structured result is incomplete")
        if not self.sas_version_present:
            problems.append("no SAS version was reported")
        if not self.denominator_df_present:
            problems.append("no denominator df was reported")
        if not self.confidence_interval_present:
            problems.append("no 90% confidence interval was reported")
        if self.convergence_failed:
            problems.append("SAS reported a non-converged fit")
        if not self.comparison_available:
            problems.append("no comparison report exists for this run")
        if not self.acknowledged:
            problems.append(
                "the reviewer acknowledgement was not given"
            )

        # NOT a precondition, deliberately: manual execution is permanently
        # unverifiable, so requiring it would make acceptance impossible for
        # every honest run. It must be VISIBLE - which the acknowledgement text
        # ensures - rather than satisfied.
        return problems

    @property
    def acceptable(self) -> bool:
        return not self.failures()


@dataclass(frozen=True, slots=True)
class HumanReviewRecord:
    """A governed decision, and everything needed to interpret it later."""

    run_id: str
    tenant_id: str
    reviewer_user_id: str
    reviewer_role_key: str
    decision: OracleClosureDecision
    notes: str
    evidence_snapshot: dict[str, Any]
    evidence_snapshot_hash: str
    acknowledgement_version: str | None
    acknowledgement_text: str | None
    acknowledgement_hash: str | None
    ai_review_id: str | None
    ai_recommendation_at_time: AIRecommendation | None
    actor_type: ActorType = ActorType.HUMAN

    @property
    def disagreed_with_ai(self) -> bool | None:
        """Did the human depart from the assistant's recommendation?

        Recorded because it is interesting in both directions and must never be
        prevented. None when there was no recommendation to depart from.
        """
        if self.ai_recommendation_at_time is None:
            return None
        recommended_acceptable = (
            self.ai_recommendation_at_time
            is AIRecommendation.ACCEPTABLE_FOR_HUMAN_REVIEW
        )
        accepted = self.decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
        return recommended_acceptable is not accepted


def build_evidence_snapshot(
    *,
    run: dict[str, Any],
    package: dict[str, Any],
    artifacts: list[dict[str, Any]],
    ai_review_id: str | None,
    ai_review_hash: str | None,
) -> tuple[dict[str, Any], str]:
    """Freeze what the reviewer was looking at, and hash it.

    Hashes rather than contents: an artefact is identified without being
    reproduced, which keeps the snapshot small and keeps raw SAS output out of
    a record that will be read by people who do not need it.
    """
    snapshot = {
        "package_id": package.get("id"),
        "archive_sha256": package.get("archive_sha256"),
        "dataset_sha256": package.get("dataset_sha256"),
        "program_sha256": package.get("program_sha256"),
        "case_id": run.get("case_id"),
        "sas_version": run.get("sas_version"),
        "estimate_log": run.get("estimate_log"),
        "estimate_ratio": run.get("estimate_ratio"),
        "standard_error": run.get("standard_error"),
        "denominator_df": run.get("denominator_df"),
        "ci_lower_ratio": run.get("ci_lower_ratio"),
        "ci_upper_ratio": run.get("ci_upper_ratio"),
        "convergence_status": run.get("convergence_status"),
        "run_status": run.get("status"),
        "integrity": (run.get("comparison") or {}).get("integrity"),
        "comparison": run.get("comparison"),
        "artifacts": sorted(
            (
                {
                    "kind": artifact.get("kind"),
                    "content_sha256": artifact.get("content_sha256"),
                }
                for artifact in artifacts
            ),
            key=lambda item: (str(item["kind"]), str(item["content_sha256"])),
        ),
        "ai_review_id": ai_review_id,
        "ai_review_hash": ai_review_hash,
    }
    serialised = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), default=str
    )
    return snapshot, hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def prepare_review(
    *,
    reviewer: ReviewerIdentity,
    run_id: str,
    tenant_id: str,
    decision: OracleClosureDecision,
    notes: str,
    acknowledged: bool,
    preconditions: AcceptancePreconditions,
    evidence_snapshot: dict[str, Any],
    evidence_snapshot_hash: str,
    ai_review_id: str | None = None,
    ai_recommendation: AIRecommendation | None = None,
) -> HumanReviewRecord:
    """Validate and assemble a decision. Persistence is the caller's job.

    `reviewer` is a `ReviewerIdentity`, which can only be built for a human -
    so an AI or worker identity cannot reach this function with a plausible
    argument.

    The AI recommendation is recorded but never consulted: the human may
    disagree in either direction, and nothing here compares the two before
    accepting the decision.
    """
    if reviewer.actor_type is not ActorType.HUMAN:  # pragma: no cover - guarded
        raise PermissionError("only a human may record an oracle-closure decision")

    if decision not in RECORDABLE_DECISIONS:
        raise ValueError(
            f"{decision.value} is not a verdict. NOT_ASSESSED means no review "
            "has happened, and recording it as one would put an unreviewed run "
            "in the reviewed table."
        )

    if not notes or not notes.strip():
        raise ValueError(
            "review notes are required. An accepted oracle closure with no "
            "recorded reasoning is not reviewable evidence, and a rejection "
            "without a reason cannot be acted on."
        )

    if decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED:
        failures = preconditions.failures()
        if failures:
            raise PreconditionFailed(failures)

    accepted = decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
    return HumanReviewRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        reviewer_user_id=reviewer.user_id,
        reviewer_role_key=reviewer.role_key,
        decision=decision,
        notes=notes.strip(),
        evidence_snapshot=evidence_snapshot,
        evidence_snapshot_hash=evidence_snapshot_hash,
        # The acknowledgement belongs to acceptance. A rejection needs reasons,
        # not a statement that the reviewer accepts unverifiable execution.
        acknowledgement_version=ACKNOWLEDGEMENT_VERSION if accepted else None,
        acknowledgement_text=ACKNOWLEDGEMENT_TEXT if accepted else None,
        acknowledgement_hash=ACKNOWLEDGEMENT_HASH if accepted else None,
        ai_review_id=ai_review_id,
        ai_recommendation_at_time=ai_recommendation,
    )


#: Said wherever an acceptance is displayed or recorded, so nobody reads a
#: green "accepted" as a statement about the statistical method.
ACCEPTANCE_MEANING = (
    "Accepting this run records that the SAS evidence is suitable for "
    "subsequent statistical work. It does not implement or validate any "
    "method: FDA_REPLICATE_STANDARD_ABE_PARTIAL remains NOT_IMPLEMENTED and "
    "partial_oracle_ready remains false until a separate, governed statistical "
    "change is made."
)


__all__ = [
    "ACCEPTANCE_MEANING",
    "ACKNOWLEDGEMENT_HASH",
    "ACKNOWLEDGEMENT_TEXT",
    "ACKNOWLEDGEMENT_VERSION",
    "RECORDABLE_DECISIONS",
    "AcceptancePreconditions",
    "HumanReviewRecord",
    "OracleClosureDecision",
    "PreconditionFailed",
    "build_evidence_snapshot",
    "prepare_review",
]
