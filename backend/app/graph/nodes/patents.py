"""patent_agent.

Same shape as the literature agent, with two differences that matter.

First, deduplication is by patent family: one invention filed in twelve
jurisdictions is one filing, and listing twelve entries would misrepresent it
as broad activity.

Second, the output schema has nowhere to put a freedom-to-operate, validity or
infringement conclusion, and the instructions forbid one. When the provider is
unavailable the state records that explicitly, so the report says "patents were
not searched" rather than implying none exist.
"""

from __future__ import annotations

import asyncio
import logging

from app.graph.context import RunContext
from app.graph.evidence import (
    allocate_markers,
    format_evidence_for_prompt,
    marker_block_start,
    patent_to_evidence,
)
from app.graph.state import ResearchState, SearchQueryLog
from app.llm.prompts import build_instructions, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import PatentFindings
from app.models.records import SearchFilters
from app.providers.dedup import deduplicate_patents

logger = logging.getLogger(__name__)

NODE = "patent_agent"

PATENT_DISCLAIMER = (
    "This patent analysis is preliminary research support and is not a legal "
    "opinion, validity analysis, infringement analysis, or freedom-to-operate "
    "opinion. Consult qualified patent counsel."
)

INSTRUCTIONS = """\
You are the Patent Research Agent.

You are given the patent documents that were actually retrieved. Work only from
them. Do not recall patents from memory or infer the existence of filings you
were not shown.

For each patent family, summarise the technical disclosure and, where the text
supports it, characterise formulation, material, delivery route, release
mechanism and claimed application. Leave a field null when the retrieved text
does not say. Score technical relevance from 0 to 1.

Distinguish document types accurately. A published application is not a granted
patent, and a family record is neither. Never describe legal status that was not
supplied to you.

ABSOLUTE CONSTRAINT. You must not state or imply any of the following:
- that a concept is free to practise, clear, available, or unencumbered
- that a patent is valid, invalid, infringed or not infringed
- any freedom-to-operate conclusion, however hedged

Describe technical overlap between the retrieved patents and the proposed
concept as *technical* overlap only, and say that legal assessment requires
qualified patent counsel.

`white_space_observations` describes areas where THIS SEARCH returned few
results. That is a statement about the search, not about the patent landscape.
Word it that way: absence of retrieved results is not absence of patents.
"""


async def patent_agent(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    plan = state.get("research_plan")

    providers = [p for p in context.patent_providers if p.is_configured]
    if not providers:
        # The honest-degradation path. The run continues on literature alone
        # and the report will carry this warning.
        unconfigured = [p.name for p in context.patent_providers]
        detail = (
            f"Patent providers are not configured ({', '.join(unconfigured)}). "
            "No patent search was performed. This is not evidence that no "
            "relevant patents exist."
        ) if unconfigured else (
            "No patent provider is configured. No patent search was performed."
        )
        await context.emit(run_id, "warning", detail, node=NODE, agent_id="patent_agent")
        return {
            "patent_search_unavailable": True,
            "warnings": [detail],
            "errors": [
                {
                    "node": NODE,
                    "provider": "epo_ops",
                    "error_type": "provider_unavailable",
                    "message": detail,
                    "is_fatal": False,
                }
            ],
        }

    queries = (
        [s.query for s in plan.patent_searches]
        if plan and plan.patent_searches
        else [state["original_question"]]
    )

    await context.emit(
        run_id,
        "node_started",
        f"Searching patents: {len(queries)} queries",
        node=NODE,
        agent_id="patent_agent",
        data={"queries": queries, "providers": [p.name for p in providers]},
    )

    filters = SearchFilters(
        date_from=state.get("date_from"),
        date_to=state.get("date_to"),
        max_results=max(1, state.get("max_results", 30) // max(1, len(queries))),
        jurisdictions=tuple(state.get("jurisdictions") or ()),
    )

    tasks = [p.search(query, filters) for p in providers for query in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    query_logs: list[SearchQueryLog] = []
    errors = []
    warnings = []
    all_failed = True

    for outcome in results:
        if isinstance(outcome, BaseException):
            logger.exception("Patent provider raised", exc_info=outcome)
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
            warnings.append(f"{outcome.provider} patent search failed: {outcome.error}")
            await context.emit(
                run_id, "error", f"{outcome.provider} failed: {outcome.error}", node=NODE
            )
            continue

        all_failed = False
        records.extend(outcome.records)
        await context.emit(
            run_id,
            "provider_result",
            f"{outcome.provider}: {outcome.count} documents",
            node=NODE,
            data={"provider": outcome.provider, "count": outcome.count},
        )

    if all_failed:
        return {
            "patent_search_unavailable": True,
            "search_queries": query_logs,
            "errors": errors,
            "warnings": [
                *warnings,
                "Every patent search failed, so no patent evidence is included. "
                "This is not evidence that no relevant patents exist.",
            ],
        }

    families = deduplicate_patents(records)
    if len(records) != len(families):
        await context.emit(
            run_id,
            "status",
            f"Grouped {len(records)} documents into {len(families)} patent families",
            node=NODE,
        )

    if not families:
        return {
            "search_queries": query_logs,
            "errors": errors,
            "warnings": [*warnings, "No patent documents matched the searches performed."],
        }

    families.sort(key=lambda r: (r.priority_date is None, r.priority_date), reverse=False)
    selected = families[: state.get("max_results", 30)]

    start = marker_block_start(NODE, state.get("max_results", 30))
    markers = allocate_markers(start, len(selected))
    evidence = [
        patent_to_evidence(record, marker)
        for record, marker in zip(selected, markers, strict=True)
    ]

    await context.emit(
        run_id,
        "evidence_stored",
        f"{len(evidence)} patent families recorded as evidence",
        node=NODE,
        data={"count": len(evidence)},
    )

    findings = None
    try:
        result = await context.models.complete_structured(
            role=ModelRole.EXTRACTION,
            schema=PatentFindings,
            instructions=build_instructions(INSTRUCTIONS),
            user_input=(
                f"Research question:\n{state['original_question']}\n\n"
                "Retrieved patent documents:\n"
                + wrap_untrusted(
                    format_evidence_for_prompt(evidence), source="epo_ops"
                )
            ),
            node=NODE,
            purpose="analyse patent landscape",
        )
        findings = result.output
        warnings.extend(result.warnings)
    except LLMError as exc:
        logger.warning("Patent analysis failed: %s", exc)
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
            "Patent documents were retrieved but could not be analysed; they are "
            "listed without an interpretive summary."
        )

    if findings:
        by_marker = {a.marker: a for a in findings.analyses}
        for entry in evidence:
            analysis = by_marker.get(entry["marker"])
            if analysis:
                entry["relevance_score"] = analysis.relevance_score

    await context.emit(
        run_id,
        "node_completed",
        f"Patent analysis complete: {len(evidence)} families",
        node=NODE,
        agent_id="patent_agent",
    )

    return {
        "patent_results": selected,
        "evidence_records": evidence,
        "search_queries": query_logs,
        "patent_findings": findings,
        "errors": errors,
        # The disclaimer is attached here so it travels with the findings and
        # cannot be lost between the agent and the report.
        "warnings": warnings + [PATENT_DISCLAIMER] + (findings.warnings if findings else []),
        "patent_search_unavailable": False,
    }
