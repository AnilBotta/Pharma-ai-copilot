"""Fakes for exercising the real graph without external services.

These stand in at the boundary only. The graph, nodes, routing, evidence
allocation, citation validation and report assembly under test are the
production code paths.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.llm.provider import StructuredResult, Usage
from app.models.agents import (
    BackgroundSummary,
    Claim,
    DevelopmentStrategy,
    ExperimentProposal,
    LiteratureFindings,
    PatentAnalysis,
    PatentFindings,
    PlannedSearch,
    QualityAttribute,
    ReportDraft,
    ReportSectionDraft,
    ResearchPlan,
    RiskItem,
    SectionConfidence,
    StructuredObjective,
    StudyExtraction,
    VerificationReport,
)
from app.models.records import (
    LiteratureRecord,
    PatentRecord,
    PatentRecordType,
    SearchFilters,
    SearchResult,
)
from app.providers.base import LiteratureProvider, PatentProvider

# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


def sample_literature(n: int = 3, provider: str = "pubmed") -> list[LiteratureRecord]:
    return [
        LiteratureRecord(
            provider=provider,
            title=f"Sustained release of therapeutic peptides, study {i}",
            abstract=f"Abstract text for study {i} describing depot formulation work.",
            authors=[f"Author{i} A", f"Author{i} B"],
            journal="Journal of Controlled Release",
            publication_date=date(2020 + i, 1, 15),
            publication_year=2020 + i,
            doi=f"10.1016/j.jconrel.2020.{i:04d}",
            pmid=f"3000000{i}",
            publication_types=["Journal Article"],
        )
        for i in range(1, n + 1)
    ]


def sample_patents(n: int = 2) -> list[PatentRecord]:
    return [
        PatentRecord(
            provider="epo_ops",
            publication_number=f"EP{3000000 + i}B1",
            title=f"Depot formulation {i}",
            abstract=f"A depot formulation comprising carrier {i}.",
            family_id=f"FAM{i}",
            kind_code="B1",
            jurisdiction="EP",
            record_type=PatentRecordType.GRANTED_PATENT,
            priority_date=date(2015 + i, 3, 1),
            publication_date=date(2019 + i, 6, 1),
            applicants=[f"Example Pharma {i}"],
            cpc_classifications=["A61K9/16"],
        )
        for i in range(1, n + 1)
    ]


class FakeLiteratureProvider(LiteratureProvider):
    def __init__(
        self,
        name: str = "pubmed",
        records: list[LiteratureRecord] | None = None,
        *,
        configured: bool = True,
        fail_with: str | None = None,
    ) -> None:
        self.name = name
        self._records = records if records is not None else sample_literature()
        self._configured = configured
        self._fail_with = fail_with
        self.searches: list[str] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def search(self, query: str, filters: SearchFilters) -> SearchResult[LiteratureRecord]:
        self.searches.append(query)
        if self._fail_with:
            return SearchResult[LiteratureRecord](
                provider=self.name, query=query, records=[], ok=False, error=self._fail_with
            )
        return SearchResult[LiteratureRecord](
            provider=self.name,
            query=query,
            records=self._records,
            total_available=len(self._records),
        )

    async def fetch_record(self, identifier: str) -> LiteratureRecord | None:
        return self._records[0] if self._records else None


class FakePatentProvider(PatentProvider):
    def __init__(
        self,
        name: str = "epo_ops",
        records: list[PatentRecord] | None = None,
        *,
        configured: bool = True,
        fail_with: str | None = None,
    ) -> None:
        self.name = name
        self._records = records if records is not None else sample_patents()
        self._configured = configured
        self._fail_with = fail_with
        self.searches: list[str] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def search(self, query: str, filters: SearchFilters) -> SearchResult[PatentRecord]:
        self.searches.append(query)
        if self._fail_with:
            return SearchResult[PatentRecord](
                provider=self.name, query=query, records=[], ok=False, error=self._fail_with
            )
        return SearchResult[PatentRecord](
            provider=self.name,
            query=query,
            records=self._records,
            total_available=len(self._records),
        )

    async def fetch_record(self, identifier: str) -> PatentRecord | None:
        return self._records[0] if self._records else None


# --------------------------------------------------------------------------- #
# Model provider
# --------------------------------------------------------------------------- #


def _default_for(schema: type, citations: list[str]) -> Any:
    """A schema-appropriate response using only allowed citation markers."""
    cite = citations[:2]

    if schema is StructuredObjective:
        return StructuredObjective(
            restated_objective="Assess feasibility of a peptide depot injection.",
            research_questions=[
                "What sustained-release mechanisms suit therapeutic peptides?",
                "What are the stability risks?",
            ],
            molecule_or_modality="therapeutic peptide",
            delivery_technology="carbon nanotube carrier",
            route_of_administration="subcutaneous",
            dosage_form="depot injection",
            ambiguities=[],
            out_of_scope=["Clinical trial design"],
        )

    if schema is ResearchPlan:
        return ResearchPlan(
            approach="Search literature and patents, then derive a strategy.",
            literature_searches=[
                PlannedSearch(
                    provider="pubmed",
                    query="peptide depot sustained release",
                    rationale="core",
                ),
            ],
            patent_searches=[
                PlannedSearch(
                    provider="epo_ops",
                    query="peptide depot nanotube",
                    rationale="landscape",
                ),
            ],
            required_agents=["research_agent", "literature_agent", "patent_agent"],
            known_risks=["Literature may be sparse."],
        )

    if schema is BackgroundSummary:
        return BackgroundSummary(
            scientific_background=[
                Claim(
                    statement="Peptides degrade by hydrolysis in aqueous depots.",
                    support="assumption",
                ),
            ],
            target_product_profile=[
                Claim(statement="Monthly subcutaneous dosing is the target.", support="assumption"),
            ],
            open_questions=["What burst release is achievable?"],
        )

    if schema is LiteratureFindings:
        return LiteratureFindings(
            summary="Retrieved studies describe depot formulation approaches.",
            extractions=[
                StudyExtraction(
                    marker=m,
                    evidence_category="formulation",
                    study_objective="Assess depot release.",
                    key_findings=["Release was sustained."],
                    limitations=["In vitro only."],
                    relevance_score=0.8,
                )
                for m in citations
            ],
            synthesis=[
                Claim(
                    statement="Sustained release over weeks has been demonstrated in vitro.",
                    support="direct",
                    citations=cite,
                    caveat="In vitro only.",
                )
            ],
            contradictions=["Two studies disagree on burst magnitude."],
            evidence_gaps=["No head-to-head in vivo comparison."],
        )

    if schema is PatentFindings:
        return PatentFindings(
            summary="Retrieved patent families describe depot carriers.",
            analyses=[
                PatentAnalysis(
                    marker=m,
                    technical_summary="A depot carrier formulation.",
                    delivery_route="subcutaneous",
                    relevance_score=0.7,
                )
                for m in citations
            ],
            overlapping_concepts=[
                Claim(
                    statement="Technical overlap in carrier chemistry.",
                    support="direct",
                    citations=cite,
                )
            ],
        )

    if schema is DevelopmentStrategy:
        return DevelopmentStrategy(
            product_concept=[
                Claim(
                    statement="A subcutaneous depot delivering peptide over 28 days.",
                    support="assumption",
                )
            ],
            stability_risks=[
                Claim(
                    statement="Aggregation is a principal risk.",
                    support="inferred",
                    citations=cite,
                )
            ],
            critical_quality_attributes=[
                QualityAttribute(
                    attribute="In vitro release profile",
                    criticality="critical",
                    rationale="Governs exposure.",
                    citations=cite,
                )
            ],
            risks=[
                RiskItem(
                    category="Formulation",
                    risk="Burst release",
                    likelihood="medium",
                    impact="high",
                    mitigation="Coating optimisation.",
                    citations=cite,
                )
            ],
            evidence_gaps=["No long-term local tolerance data."],
            recommended_experiments=[
                ExperimentProposal(
                    objective="Characterise burst release",
                    approach="In vitro release study",
                    addresses_gap="Burst magnitude unknown",
                    priority="high",
                )
            ],
        )

    if schema is ReportDraft:
        from app.models.agents import SECTION_TITLES

        summary_citation = f"[{cite[0]}]" if cite else ""
        body_claim = (
            f"Sustained release was observed [{cite[0]}]."
            if cite
            else "No reliable evidence was retrieved."
        )
        return ReportDraft(
            executive_summary=f"Feasibility appears plausible {summary_citation}.",
            sections=[
                ReportSectionDraft(
                    section_key=key,
                    title=title,
                    body_markdown=f"Findings for {title}. {body_claim}",
                )
                for key, title in SECTION_TITLES.items()
                if key not in {"references", "limitations"}
            ],
            key_uncertainties=["Long-term tolerability is unknown."],
        )

    if schema is VerificationReport:
        return VerificationReport(
            issues=[],
            section_confidence=[
                SectionConfidence(
                    section_key="literature_review",
                    confidence="moderate",
                    rationale="Limited source count.",
                    supporting_source_count=len(citations),
                )
            ],
            contradictions=[],
            requires_revision=False,
            overall_note="No blocking issues found.",
        )

    raise AssertionError(f"FakeModelProvider has no response for {schema.__name__}")


class FakeModelProvider:
    """Model provider returning schema-valid responses without network calls.

    `citation_override` makes a call cite markers that were never retrieved,
    which is how the citation-integrity tests inject a hallucination.
    """

    def __init__(
        self,
        *,
        citation_override: list[str] | None = None,
        fail_on: set[type] | None = None,
        responses: dict[type, Any] | None = None,
    ) -> None:
        self.citation_override = citation_override
        self.fail_on = fail_on or set()
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    async def complete_structured(
        self,
        *,
        role: Any,
        schema: type,
        instructions: str,
        user_input: str,
        max_output_tokens: int | None = None,
        node: str | None = None,
        purpose: str | None = None,
    ) -> StructuredResult:
        self.calls.append((node or "?", schema.__name__))

        if schema in self.fail_on:
            from app.llm.provider import LLMError

            raise LLMError(f"Simulated failure for {schema.__name__}")

        if schema in self.responses:
            output = self.responses[schema]
        else:
            markers = self.citation_override
            if markers is None:
                markers = _markers_in(user_input)
            output = _default_for(schema, markers)

        return StructuredResult(
            output=output,
            usage=Usage(model="fake-model", input_tokens=100, output_tokens=50),
        )

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], Usage]:
        return [[0.0] * 1536 for _ in texts], Usage(model="fake-embed")

    def model_for(self, role: Any) -> str:
        return "fake-model"


def _markers_in(text: str) -> list[str]:
    """Read the allowlist back out of the prompt, as a real model would."""
    import re

    return list(dict.fromkeys(re.findall(r"\[(E\d+)\]", text)))
