"""Request and response models for the HTTP API.

Input validation lives here. Bounds on free text and result counts are not
cosmetic: an unbounded research question becomes an unbounded prompt, and an
unbounded result count becomes unbounded spend on external APIs and tokens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_QUESTION_LENGTH = 4000
MAX_INSTRUCTIONS_LENGTH = 2000


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, max_length=50)
    molecule: str | None = Field(default=None, max_length=200)
    indication: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name cannot be blank.")
        return v.strip()


class ProjectResponse(BaseModel):
    id: str
    name: str
    code: str | None = None
    description: str | None = None
    molecule: str | None = None
    indication: str | None = None
    is_seed: bool = False
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


class CreateRunRequest(BaseModel):
    project_id: str
    original_question: str = Field(min_length=10, max_length=MAX_QUESTION_LENGTH)

    molecule: str | None = Field(default=None, max_length=200)
    indication: str | None = Field(default=None, max_length=200)
    dosage_form: str | None = Field(default=None, max_length=200)
    route_of_administration: str | None = Field(default=None, max_length=200)
    delivery_technology: str | None = Field(default=None, max_length=200)
    development_stage: str | None = Field(default=None, max_length=100)

    jurisdictions: list[str] = Field(default_factory=list, max_length=20)
    date_from: int | None = Field(default=None, ge=1800, le=2200)
    date_to: int | None = Field(default=None, ge=1800, le=2200)
    max_results: int = Field(default=50, ge=1, le=200)
    additional_instructions: str | None = Field(
        default=None, max_length=MAX_INSTRUCTIONS_LENGTH
    )

    @field_validator("original_question")
    @classmethod
    def _meaningful_question(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 10:
            raise ValueError("The research question is too short to act on.")
        return cleaned

    @field_validator("jurisdictions")
    @classmethod
    def _normalise_jurisdictions(cls, v: list[str]) -> list[str]:
        codes = [j.strip().upper() for j in v if j.strip()]
        for code in codes:
            if not code.isalpha() or len(code) > 3:
                raise ValueError(f"'{code}' is not a valid jurisdiction code.")
        return codes

    @model_validator(mode="after")
    def _dates_ordered(self) -> CreateRunRequest:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to.")
        return self


class RunSummary(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    status: str
    original_question: str
    current_node: str | None = None
    progress_pct: int = 0
    evidence_count: int = 0
    error_message: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class RunDetail(RunSummary):
    molecule: str | None = None
    indication: str | None = None
    dosage_form: str | None = None
    route_of_administration: str | None = None
    delivery_technology: str | None = None
    development_stage: str | None = None
    jurisdictions: list[str] = Field(default_factory=list)
    date_from: int | None = None
    date_to: int | None = None
    max_results: int = 50
    additional_instructions: str | None = None
    structured_objective: dict[str, Any] | None = None
    research_plan: dict[str, Any] | None = None
    contradictions: list[Any] = Field(default_factory=list)
    evidence_gaps: list[Any] = Field(default_factory=list)
    warnings: list[Any] = Field(default_factory=list)
    section_confidence: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False


class RunCreatedResponse(BaseModel):
    """Returned immediately, before any research has run."""

    run_id: str
    status: str
    message: str


class EventResponse(BaseModel):
    id: int
    run_id: str
    node: str | None = None
    agent_id: str | None = None
    event_type: str
    message: str
    data: dict[str, Any] | None = None
    created_at: datetime


class EvidenceResponse(BaseModel):
    id: str
    marker: str
    source_type: str
    provider: str
    title: str
    authors: list[str] = Field(default_factory=list)
    identifier_type: str | None = None
    identifier: str | None = None
    publication_date: Any = None
    url: str | None = None
    access_level: str
    evidence_category: str | None = None
    relevance_score: float | None = None
    retrieved_by_agent: str
    cited_in_sections: list[str] = Field(default_factory=list)
    retrieved_at: datetime


class ReportSectionResponse(BaseModel):
    id: str
    section_key: str
    position: int
    title: str
    body_markdown: str
    confidence: str | None = None
    confidence_rationale: str | None = None


class SearchQueryResponse(BaseModel):
    id: str
    node: str | None = None
    provider: str
    query_text: str
    result_count: int | None = None
    from_cache: bool = False
    duration_ms: int | None = None
    status: str
    error: str | None = None
    created_at: datetime


class RunErrorResponse(BaseModel):
    id: str
    node: str | None = None
    provider: str | None = None
    error_type: str
    message: str
    is_fatal: bool
    created_at: datetime


class IntegrationStatus(BaseModel):
    name: str
    state: str
    required: bool
    detail: str


class HealthResponse(BaseModel):
    status: str
    database: str
    integrations: list[IntegrationStatus]


class DashboardResponse(BaseModel):
    running: int = 0
    queued: int = 0
    completed: int = 0
    failed: int = 0
    total_runs: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    source_counts: dict[str, int] = Field(default_factory=dict)
