"""Request and response models for the PDP module.

The response models are permissive about extra fields because the readiness
functions return computed columns that grow with the engine. The *request*
models are strict, because they are the boundary an agent will eventually call
through: a tool that can send an arbitrary field is a tool that can eventually
send `is_complete`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_REASON_LENGTH = 2000


class StrictRequest(BaseModel):
    """Rejects unknown fields.

    Not pedantry. This module's guarantee is that no caller can assert
    completion, and the cheapest future violation is a field quietly accepted
    and passed into an UPDATE. An unknown field is an error here, always.
    """

    model_config = ConfigDict(extra="forbid")


def _required_text(value: str | None, what: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{what} is required.")
    return value.strip()


# --------------------------------------------------------------- templates ---


class TemplateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    template_key: str
    version: int
    name: str
    description: str | None = None
    product_type: str
    status: str
    is_default: bool = False
    stage_count: int = 0
    requirement_count: int = 0
    approved_at: datetime | None = None


class InstantiateRequest(StrictRequest):
    template_id: str
    #: Used to derive requirement due dates from each template's lead days.
    #: Omitted means no due dates, which is honest rather than inventing them.
    start_date: date | None = None


class InstantiateResponse(BaseModel):
    project_id: str
    template_id: str
    template_name: str
    template_version: int
    stages_created: int
    requirements_created: int
    dependencies_created: int


# -------------------------------------------------------------- readiness ---


class Readiness(BaseModel):
    """The two numbers, always together.

    `readiness_pct` says how much is done. `is_ready` says whether the gate may
    be reviewed. They are different questions and the second is the dispositive
    one: 96.1% with one unsatisfied mandatory requirement is not ready.

    `blocker_count` is not optional in this model. A caller that has the
    percentage necessarily has the count of reasons it is not 100.
    """

    readiness_pct: float
    is_ready: bool
    blocker_count: int
    applicable_count: int = 0
    satisfied_count: int = 0
    mandatory_count: int = 0
    mandatory_satisfied: int = 0


class Blocker(BaseModel):
    requirement_id: str
    ref_code: str
    title: str
    status: str
    reason: str
    owner_user_id: str | None = None
    due_date: date | None = None


class Capabilities(BaseModel):
    can_access: bool
    can_approve: bool
    can_gate: bool
    can_administer: bool
    is_portfolio_wide: bool
    is_project_owner: bool
    role_keys: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- programme ---


class ProgrammeSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    code: str | None = None
    description: str | None = None
    product_type: str | None = None
    health: str | None = None
    stage_count: int = 0
    current_stage_pk: str | None = None
    current_stage_key: str | None = None
    current_stage_name: str | None = None
    current_stage_position: int | None = None
    current_gate_status: str | None = None
    readiness_pct: float | None = None
    is_ready: bool | None = None
    blocker_count: int | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None


class StageSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    project_id: str
    position: int
    key: str
    name: str
    description: str | None = None
    gate_question: str | None = None
    exit_criteria: str | None = None
    gate_status: str
    gate_decision_by: str | None = None
    gate_decision_at: datetime | None = None
    gate_decision_note: str | None = None
    gate_conditions: str | None = None
    readiness_pct: float = 0
    is_ready: bool = False
    blocker_count: int = 0
    applicable_count: int = 0
    satisfied_count: int = 0
    mandatory_count: int = 0
    mandatory_satisfied: int = 0
    requirement_count: int = 0
    overdue_count: int = 0


class ProgrammeDetail(BaseModel):
    project: dict[str, Any]
    stages: list[StageSummary]
    capabilities: Capabilities


# ------------------------------------------------------------------- gate ---


class EvidenceLink(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    requirement_id: str
    evidence_type: str
    research_run_id: str | None = None
    research_run_status: str | None = None
    research_run_question: str | None = None
    document_version_id: str | None = None
    document_number: str | None = None
    document_title: str | None = None
    document_version_label: str | None = None
    document_version_status: str | None = None
    document_storage_url: str | None = None
    #: Computed on read. False means this link no longer satisfies anything —
    #: the version was superseded, went obsolete, or passed its expiry.
    document_is_usable: bool | None = None
    external_url: str | None = None
    note: str | None = None
    title: str | None = None
    description: str | None = None
    ai_assessment: str | None = None
    ai_confidence: float | None = None
    human_confirmed_by: str | None = None
    added_by: str | None = None
    added_by_name: str | None = None
    created_at: datetime


class Approval(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    requirement_id: str
    approver_id: str
    approver_name: str | None = None
    approver_role: str
    decision: str
    comments: str | None = None
    approved_at: datetime
    superseded_at: datetime | None = None
    superseded_reason: str | None = None


class RequirementDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    project_stage_id: str
    position: int
    ref_code: str
    title: str
    description: str | None = None
    guidance: str | None = None
    discipline: str | None = None
    is_mandatory: bool
    weight: float
    required_evidence_type: str
    acceptance_criteria: str | None = None

    #: Computed by the engine on every read. There is no stored counterpart.
    status: str
    is_satisfied: bool
    evidence_count: int = 0

    acceptance_confirmed_by: str | None = None
    acceptance_confirmed_by_name: str | None = None
    acceptance_confirmed_at: datetime | None = None
    owner_user_id: str | None = None
    owner_name: str | None = None
    approver_role_key: str | None = None
    due_date: date | None = None
    priority: str
    is_blocked: bool
    blocked_reason: str | None = None
    is_not_applicable: bool
    not_applicable_reason: str | None = None

    depends_on: list[dict[str, Any]] | None = None
    evidence: list[EvidenceLink] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    current_approval: Approval | None = None


class GateWorkspace(BaseModel):
    project_id: str
    stage: StageSummary
    readiness: Readiness
    blockers: list[Blocker]
    requirements: list[RequirementDetail]
    capabilities: Capabilities


# ----------------------------------------------------------------- writes ---


class AttachEvidenceRequest(StrictRequest):
    evidence_type: Literal["research_run", "url", "note", "data", "document"]
    research_run_id: str | None = None
    document_version_id: str | None = None
    external_url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _payload_matches_type(self) -> AttachEvidenceRequest:
        """Each evidence type must carry its own payload.

        The database enforces this too. Checking here as well turns a 500 from a
        constraint violation into a message that says which field is missing.
        """
        required = {
            "research_run": "research_run_id",
            "document": "document_version_id",
            "url": "external_url",
            "note": "note",
        }.get(self.evidence_type)

        if required and not getattr(self, required):
            raise ValueError(f"{self.evidence_type} evidence requires '{required}'.")
        if self.evidence_type == "data" and not (self.external_url or self.note):
            raise ValueError("data evidence requires 'external_url' or 'note'.")
        return self

    @field_validator("external_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("A URL must start with http:// or https://.")
        return v


class AcceptanceRequest(StrictRequest):
    confirmed: bool


class DecisionRequest(StrictRequest):
    decision: Literal["approved", "rejected"]
    comments: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _rejection_explains_itself(self) -> DecisionRequest:
        if self.decision == "rejected":
            _required_text(self.comments, "A reason for rejection")
        return self


class ReviewRequest(StrictRequest):
    outcome: Literal["changes_requested", "recommended", "not_recommended"]
    comments: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class AssignmentRequest(StrictRequest):
    owner_user_id: str | None = None
    reviewer_user_id: str | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    clear_owner: bool = False
    clear_due_date: bool = False


class BlockRequest(StrictRequest):
    blocked: bool
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _block_has_reason(self) -> BlockRequest:
        if self.blocked:
            _required_text(self.reason, "A reason for blocking")
        return self


class NotApplicableRequest(StrictRequest):
    not_applicable: bool
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _scoping_out_has_reason(self) -> NotApplicableRequest:
        if self.not_applicable:
            _required_text(self.reason, "A justification")
        return self


class GateDecisionRequest(StrictRequest):
    decision: Literal["approved", "conditionally_approved", "rejected", "on_hold"]
    note: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
    conditions: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _conditions_present_when_conditional(self) -> GateDecisionRequest:
        if self.decision == "conditionally_approved":
            _required_text(
                self.conditions,
                "Conditions stating what must still be done",
            )
        if self.decision in ("rejected", "on_hold"):
            _required_text(self.note, "A reason")
        return self


# ------------------------------------------------------------ ancillaries ---


class AttachableRun(BaseModel):
    id: str
    original_question: str
    status: str
    completed_at: datetime | None = None
    evidence_count: int = 0


# ------------------------------------------------- controlled documents ---


DOCUMENT_TYPES = Literal[
    "protocol", "report", "specification", "method", "sop", "batch_record",
    "risk_assessment", "plan", "summary", "certificate", "drawing", "other",
]

#: Only these two may support a requirement. `draft` and `in_review` are not
#: reviewed work; `superseded` and `obsolete` no longer describe reality.
USABLE_STATUSES = ("approved", "effective")

VERSION_STATUSES = Literal[
    "draft", "in_review", "approved", "effective", "superseded", "obsolete"
]


class DocumentVersion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    document_id: str
    version_label: str
    status: VERSION_STATUSES
    storage_url: str
    checksum: str | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    #: Computed. Whether this version may currently support a requirement.
    is_usable: bool | None = None
    approved_by: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    superseded_at: datetime | None = None
    superseded_by_version_id: str | None = None
    cited_by_count: int = 0
    created_at: datetime


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    project_id: str | None = None
    document_number: str
    title: str
    document_type: str
    discipline: str | None = None
    description: str | None = None
    owner_user_id: str | None = None
    owner_name: str | None = None
    is_controlled: bool = True
    version_count: int = 0
    current_version: dict[str, Any] | None = None
    created_at: datetime


class DocumentDetail(DocumentSummary):
    versions: list[DocumentVersion] = Field(default_factory=list)


class CreateDocumentRequest(StrictRequest):
    document_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    document_type: DOCUMENT_TYPES = "other"
    discipline: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
    owner_user_id: str | None = None

    @field_validator("document_number", "title")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        return _required_text(v, "This field")


class AddDocumentVersionRequest(StrictRequest):
    version_label: str = Field(min_length=1, max_length=50)
    #: A link to the file of record, not an upload. See migration 0019.
    storage_url: str = Field(min_length=1, max_length=2000)
    status: VERSION_STATUSES = "draft"
    checksum: str | None = Field(default=None, max_length=200)
    effective_date: date | None = None
    expiry_date: date | None = None
    supersedes_version_id: str | None = None

    @field_validator("storage_url")
    @classmethod
    def _must_be_a_link(cls, v: str) -> str:
        if not v.strip().startswith(("http://", "https://")):
            raise ValueError(
                "storage_url must be a link to the file of record "
                "(http:// or https://). Files are not uploaded here."
            )
        return v.strip()

    @model_validator(mode="after")
    def _dates_ordered(self) -> AddDocumentVersionRequest:
        if (
            self.effective_date
            and self.expiry_date
            and self.expiry_date < self.effective_date
        ):
            raise ValueError("expiry_date cannot precede effective_date.")
        return self


class SetVersionStatusRequest(StrictRequest):
    status: VERSION_STATUSES
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    occurred_at: datetime
    actor_user_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    actor_agent: str | None = None
    action: str
    entity_type: str
    entity_id: str
    previous_value: Any = None
    new_value: Any = None
    reason: str | None = None
    source_channel: str
