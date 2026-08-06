"""literature_agent.

Runs the planned searches against every configured literature provider,
deduplicates across them, converts survivors into evidence records, then asks
the model to extract and synthesise *from the retrieved evidence only*.

The order matters: evidence rows exist before the model is asked to say
anything, so the citation allowlist is a fact about what was retrieved rather
than a promise the model is asked to keep.
"""

from __future__ import annotations

import asyncio
import logging

from app.graph.context import RunContext
from app.graph.evidence import (
    allocate_markers,
    format_evidence_for_prompt,
    literature_to_evidence,
    marker_block_start,
)
from app.graph.state import ResearchState, SearchQueryLog
from app.llm.prompts import build_instructions, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import LiteratureFindings
from app.models.records import SearchFilters
from app.providers.dedup import deduplicate_literature

logger = logging.getLogger(__name__)

NODE = "literature_agent"

INSTRUCTIONS = """\
You are the Literature Review Agent.

You are given the publications that were actually retrieved. Work only from
them. Do not add studies from memory, however well known.

For each retrieved paper, produce an extraction:
- Categorise it: review, in_vitro, in_vivo, clinical, formulation, toxicology,
  manufacturing, analytical, or other.
- Record objective, methods, materials, key findings and limitations, taking
  them from the supplied text. Leave a field null when the text does not say.
- Score relevance to the research question from 0 to 1.

Note each source's access level. Where it is abstract_only you have read an
abstract, not a paper: do not describe methods or results in a way that implies
you saw the full text, and record that limitation.

Then synthesise across the papers:
- Every claim cites the markers supporting it.
- Report disagreements between sources in `contradictions`. Do not average them
  away or pick a winner.
- Record what the retrieved literature does not answer in `evidence_gaps`.
- Where the evidence is only preclinical, only in vitro, or only from a single
  study, say so in the claim's caveat.

If nothing relevant was retrieved, say so plainly and leave the lists empty.
Do not compensate with general knowledge.
"""


def _queries_by_provider(
    plan, providers, fallback_question: str
) -> dict[str, list[str]]:
    """Route each planned query to the provider it was written for.

    PubMed and Europe PMC use incompatible query syntax. PubMed takes field tags
    like ``[tiab]`` and ``[MeSH]``; Europe PMC takes ``TITLE_ABS:`` and its own
    field names. Running every query against every provider therefore wastes
    half of them.

    That is not hypothetical. In the first live run all ten planned queries were
    written in PubMed syntax and sent to both providers: PubMed returned six
    usable records, Europe PMC returned zero for all ten. An entire provider was
    silently contributing nothing, and the failure was invisible because zero
    results is a legitimate outcome.

    `PlannedSearch` already carries a `provider` field; it was simply being
    discarded. A provider with no query addressed to it falls back to the raw
    question, so it still contributes rather than being skipped.
    """
    routed: dict[str, list[str]] = {p.name: [] for p in providers}
    known = set(routed)

    for search in getattr(plan, "literature_searches", None) or []:
        name = (search.provider or "").strip().lower()
        if name in known:
            routed[name].append(search.query)
        else:
            # Planner named a provider we do not have, or none at all. Give the
            # query to every provider rather than dropping it.
            for queries in routed.values():
                queries.append(search.query)

    for name, queries in routed.items():
        if not queries:
            routed[name] = [fallback_question]

    return routed


async def literature_agent(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    plan = state.get("research_plan")

    providers = [p for p in context.literature_providers if p.is_configured]
    if not providers:
        await context.emit(
            run_id, "warning", "No literature provider is configured.", node=NODE
        )
        return {
            "no_literature_found": True,
            "warnings": ["No literature provider was configured; no literature was searched."],
        }

    plan_by_provider = _queries_by_provider(plan, providers, state["original_question"])
    total_queries = sum(len(q) for q in plan_by_provider.values())

    await context.emit(
        run_id,
        "node_started",
        f"Searching literature: {total_queries} queries across {len(providers)} providers",
        node=NODE,
        agent_id="literature_agent",
        data={
            "providers": [p.name for p in providers],
            "queries_per_provider": {k: len(v) for k, v in plan_by_provider.items()},
        },
    )

    filters = SearchFilters(
        date_from=state.get("date_from"),
        date_to=state.get("date_to"),
        max_results=max(1, state.get("max_results", 50) // max(1, total_queries)),
    )

    # Each query goes only to the provider it was written for. Each provider
    # paces itself, so fanning all of them out at once is safe.
    tasks = [
        provider.search(query, filters)
        for provider in providers
        for query in plan_by_provider.get(provider.name, ())
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    query_logs: list[SearchQueryLog] = []
    errors = []
    warnings = []

    for outcome in results:
        if isinstance(outcome, BaseException):
            # A provider that raised despite the non-raising contract.
            logger.exception("Literature provider raised", exc_info=outcome)
            errors.append(
                {
                    "node": NODE,
                    "provider": None,
                    "error_type": "provider_failure",
                    "message": str(outcome),
                    "is_fatal": False,
                }
            )
            continue

        query_logs.append(
            SearchQueryLog(
                node=NODE,
                provider=outcome.provider,
                query_text=outcome.query,
                result_count=outcome.count,
                from_cache=outcome.from_cache,
                duration_ms=outcome.duration_ms,
                status="ok" if outcome.ok else "failed",
                error=outcome.error,
            )
        )

        if not outcome.ok:
            errors.append(
                {
                    "node": NODE,
                    "provider": outcome.provider,
                    "error_type": "provider_failure",
                    "message": outcome.error or "Unknown provider failure.",
                    "is_fatal": False,
                }
            )
            warnings.append(
                f"{outcome.provider} search failed and returned no results: {outcome.error}"
            )
            await context.emit(
                run_id,
                "error",
                f"{outcome.provider} search failed: {outcome.error}",
                node=NODE,
            )
            continue

        records.extend(outcome.records)
        await context.emit(
            run_id,
            "provider_result",
            f"{outcome.provider}: {outcome.count} records for \"{outcome.query[:80]}\"",
            node=NODE,
            data={"provider": outcome.provider, "count": outcome.count},
        )

    deduplicated = deduplicate_literature(records)
    removed = len(records) - len(deduplicated)
    if removed:
        await context.emit(
            run_id,
            "status",
            f"Deduplicated {len(records)} results to {len(deduplicated)} distinct papers",
            node=NODE,
        )

    if not deduplicated:
        await context.emit(
            run_id,
            "node_completed",
            "No literature was retrieved for this question.",
            node=NODE,
            agent_id="literature_agent",
        )
        return {
            "search_queries": query_logs,
            "errors": errors,
            "warnings": [*warnings, "No literature results were retrieved."],
            "no_literature_found": True,
        }

    # Rank by how much text we actually have, then recency. This is a
    # deterministic pre-filter before the model scores true relevance; it only
    # decides what fits in the context window.
    deduplicated.sort(
        key=lambda r: (
            0 if r.access_level.value == "full_text" else 1 if r.abstract else 2,
            -(r.publication_year or 0),
        )
    )
    selected = deduplicated[: state.get("max_results", 50)]

    start = marker_block_start(NODE, state.get("max_results", 50))
    markers = allocate_markers(start, len(selected))
    evidence = [
        literature_to_evidence(record, marker)
        for record, marker in zip(selected, markers, strict=True)
    ]

    await context.emit(
        run_id,
        "evidence_stored",
        f"{len(evidence)} publications recorded as evidence ({markers[0]}-{markers[-1]})",
        node=NODE,
        data={"count": len(evidence)},
    )

    findings = None
    try:
        result = await context.models.complete_structured(
            role=ModelRole.EXTRACTION,
            schema=LiteratureFindings,
            instructions=build_instructions(INSTRUCTIONS),
            user_input=(
                f"Research question:\n{state['original_question']}\n\n"
                "Retrieved publications:\n"
                + wrap_untrusted(
                    format_evidence_for_prompt(evidence), source="literature providers"
                )
            ),
            node=NODE,
            purpose="extract and synthesise literature",
        )
        findings = result.output
        warnings.extend(result.warnings)
    except LLMError as exc:
        # The evidence is still real and still citable; only the synthesis is
        # missing. Degrade rather than discard the retrieval work.
        logger.warning("Literature synthesis failed: %s", exc)
        errors.append(
            {
                "node": NODE,
                "provider": None,
                "error_type": getattr(exc, "error_type", "model_error"),
                "message": str(exc),
                "is_fatal": False,
            }
        )
        warnings.append(
            "Literature was retrieved but could not be synthesised; the sources "
            "are listed without an interpretive summary."
        )

    # Fold the model's category and relevance judgements back onto the evidence.
    if findings:
        by_marker = {e.marker: e for e in findings.extractions}
        for entry in evidence:
            extraction = by_marker.get(entry["marker"])
            if extraction:
                entry["evidence_category"] = extraction.evidence_category
                entry["relevance_score"] = extraction.relevance_score

    await context.emit(
        run_id,
        "node_completed",
        f"Literature review complete: {len(evidence)} sources analysed",
        node=NODE,
        agent_id="literature_agent",
    )

    return {
        "literature_results": selected,
        "evidence_records": evidence,
        "search_queries": query_logs,
        "literature_findings": findings,
        "contradictions": findings.contradictions if findings else [],
        "evidence_gaps": findings.evidence_gaps if findings else [],
        "errors": errors,
        "warnings": warnings + (findings.warnings if findings else []),
        "no_literature_found": False,
    }
