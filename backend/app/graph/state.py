"""Shared graph state.

One typed dictionary threaded through every node. Fields written by the
parallel branch (research, literature, patent) use additive reducers, because
LangGraph merges concurrent updates and a plain assignment from three branches
at once would be a lost-update race.

The state is deliberately serialisable: it is checkpointed to Postgres after
every node so an interrupted run resumes from the last completed step rather
than re-running paid API calls and model tokens.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, NotRequired, TypedDict

from app.models.agents import (
    BackgroundSummary,
    DevelopmentStrategy,
    DocumentFindings,
    LiteratureFindings,
    PatentFindings,
    ReportDraft,
    ResearchPlan,
    StructuredObjective,
    VerificationReport,
)
from app.models.records import LiteratureRecord, PatentRecord


class EvidenceEntry(TypedDict):
    """An evidence_records row, as carried through the graph.

    Written before any synthesis node runs. `marker` is what synthesis is
    allowed to cite, and what the reviewer validates against.
    """

    marker: str
    source_type: str
    provider: str
    title: str
    authors: list[str]
    identifier_type: str | None
    identifier: str | None
    publication_date: str | None
    url: str | None
    retrieved_text: str | None
    access_level: str
    evidence_category: str | None
    relevance_score: float | None
    retrieved_by_agent: str

    #: Set only for `internal_document` evidence. It is what makes a citation
    #: resolve to the exact passage on the exact page, rather than to a filename
    #: the reader then has to search. Literature and patent evidence leave it
    #: absent; they are located by their own identifiers.
    document_chunk_id: NotRequired[str | None]


class RunError(TypedDict):
    """A failure worth surfacing to the user rather than hiding."""

    node: str | None
    provider: str | None
    error_type: str
    message: str
    is_fatal: bool


class SearchQueryLog(TypedDict):
    node: str
    provider: str
    query_text: str
    result_count: int | None
    from_cache: bool
    duration_ms: int | None
    status: str
    error: str | None


class ResearchState(TypedDict, total=False):
    """State shared by every node in the research graph."""

    # --- identity -------------------------------------------------------
    run_id: str
    user_id: str
    project_id: str

    # --- user input -----------------------------------------------------
    original_question: str
    molecule: str | None
    indication: str | None
    dosage_form: str | None
    route_of_administration: str | None
    delivery_technology: str | None
    development_stage: str | None
    jurisdictions: list[str]
    date_from: int | None
    date_to: int | None
    max_results: int
    additional_instructions: str | None

    # --- supervisor output ----------------------------------------------
    structured_objective: StructuredObjective | None
    research_plan: ResearchPlan | None

    # --- retrieval ------------------------------------------------------
    # Additive: the three specialist branches run concurrently.
    search_queries: Annotated[list[SearchQueryLog], operator.add]
    literature_results: Annotated[list[LiteratureRecord], operator.add]
    patent_results: Annotated[list[PatentRecord], operator.add]
    uploaded_document_results: Annotated[list[dict[str, Any]], operator.add]
    evidence_records: Annotated[list[EvidenceEntry], operator.add]

    # --- agent findings -------------------------------------------------
    background_summary: BackgroundSummary | None
    literature_findings: LiteratureFindings | None
    patent_findings: PatentFindings | None
    document_findings: DocumentFindings | None
    development_strategy: DevelopmentStrategy | None
    verification: VerificationReport | None
    report: ReportDraft | None

    # --- cross-cutting --------------------------------------------------
    contradictions: Annotated[list[str], operator.add]
    evidence_gaps: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[RunError], operator.add]
    section_confidence: dict[str, str]

    # --- control --------------------------------------------------------
    #: Set when the reviewer found high-severity problems. Bounded to one
    #: revision so a model that cannot satisfy the reviewer does not loop.
    revision_count: int
    #: High-severity findings still standing when the revision budget ran out.
    #:
    #: This exists because `verification.requires_revision` cannot answer the
    #: question. It is forced False once the budget is spent, so it means
    #: "clean OR we gave up" - and nothing downstream could tell those apart.
    #: A report finalised with unresolved findings must not be presented the
    #: same way as one that passed.
    unresolved_high_severity: int
    #: True when the patent provider was unavailable, so the report can say so
    #: rather than implying no patents exist.
    patent_search_unavailable: bool
    #: True when literature retrieval produced nothing at all.
    no_literature_found: bool

    # --- accounting -----------------------------------------------------
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float

    created_at: datetime
    updated_at: datetime


def initial_state(
    *,
    run_id: str,
    user_id: str,
    project_id: str,
    original_question: str,
    molecule: str | None = None,
    indication: str | None = None,
    dosage_form: str | None = None,
    route_of_administration: str | None = None,
    delivery_technology: str | None = None,
    development_stage: str | None = None,
    jurisdictions: list[str] | None = None,
    date_from: int | None = None,
    date_to: int | None = None,
    max_results: int = 50,
    additional_instructions: str | None = None,
) -> ResearchState:
    """Build the starting state for a run.

    Every accumulating field starts as an empty list rather than being absent,
    so nodes can append without first checking for existence.
    """
    now = datetime.now()
    return ResearchState(
        run_id=run_id,
        user_id=user_id,
        project_id=project_id,
        original_question=original_question,
        molecule=molecule,
        indication=indication,
        dosage_form=dosage_form,
        route_of_administration=route_of_administration,
        delivery_technology=delivery_technology,
        development_stage=development_stage,
        jurisdictions=jurisdictions or [],
        date_from=date_from,
        date_to=date_to,
        max_results=max_results,
        additional_instructions=additional_instructions,
        structured_objective=None,
        research_plan=None,
        search_queries=[],
        literature_results=[],
        patent_results=[],
        uploaded_document_results=[],
        evidence_records=[],
        background_summary=None,
        literature_findings=None,
        patent_findings=None,
        document_findings=None,
        development_strategy=None,
        verification=None,
        report=None,
        contradictions=[],
        evidence_gaps=[],
        warnings=[],
        errors=[],
        section_confidence={},
        revision_count=0,
        unresolved_high_severity=0,
        patent_search_unavailable=False,
        no_literature_found=False,
        total_input_tokens=0,
        total_output_tokens=0,
        estimated_cost_usd=0.0,
        created_at=now,
        updated_at=now,
    )


def evidence_markers(state: ResearchState) -> set[str]:
    """The citation allowlist for this run."""
    return {entry["marker"] for entry in state.get("evidence_records", [])}
