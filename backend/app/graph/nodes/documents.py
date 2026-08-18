"""document_agent.

Retrieves passages from the documents the user uploaded to this run's project,
records them as evidence, then asks the model to extract and synthesise *from
those passages only*.

Same order as the literature agent, and for the same reason: evidence rows exist
before the model is asked to say anything, so the citation allowlist is a fact
about what was retrieved rather than a promise the model is asked to keep.

WHAT MAKES THIS SOURCE DIFFERENT

Everything else in the graph retrieved its evidence from a published, external,
identifiable source. This did not. It came from a file somebody in the
organisation uploaded, and it has not been peer-reviewed, published or checked
by anyone. It is carried as `internal_document` from here to the report so that
distinction survives all the way to the reader, who must never mistake an
internal memo for a clinical trial.

The text is also untrusted in the security sense - it is wrapped before it
reaches the model, exactly as provider output is.
"""

from __future__ import annotations

import logging

from app.graph.context import RunContext
from app.graph.evidence import (
    allocate_markers,
    chunk_to_evidence,
    format_evidence_for_prompt,
    marker_block_start,
)
from app.graph.state import ResearchState
from app.llm.prompts import build_instructions, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import DocumentFindings

logger = logging.getLogger(__name__)

NODE = "document_agent"

#: Passages retrieved. Enough to cover a question from several angles without
#: crowding out the external evidence, which is the better-supported material
#: and should not be displaced by whatever happens to be on the file share.
MAX_PASSAGES = 12

INSTRUCTIONS = """\
You are the Internal Document Agent.

You are given passages retrieved from documents that people inside the
organisation uploaded. Work only from them. Do not add anything from memory.

These are NOT published literature. They have not been peer-reviewed, and
nobody outside the organisation has checked them. Treat them as the
organisation's own account of its own work:

- Report what a passage says, attributed to the document it came from.
- Never present an internal claim as established fact. "The internal stability
  report states X" is right; "X is the case" is not.
- Where an internal document conflicts with published evidence, say so in the
  claim's caveat rather than choosing between them.
- Every claim cites the markers supporting it.

If the retrieved passages do not address the research question, say so plainly
and leave the lists empty. Do not stretch a passage to make it relevant.
"""


async def document_agent(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    retriever = context.document_retriever

    # Announce the node whatever the outcome. It was scheduled and it ran, and
    # every other node in NODE_SEQUENCE says so - a branch that stayed silent
    # when it found nothing would be missing from the progress display for
    # exactly the runs where a reader might wonder whether it was consulted.
    await context.emit(
        run_id,
        "node_started",
        (
            f"Searching {retriever.document_count} uploaded document(s)"
            if retriever is not None
            else "No uploaded documents on this project"
        ),
        node=NODE,
        agent_id="document_agent",
        data={"documents": retriever.document_count if retriever else 0},
    )

    if retriever is None:
        # A project with no uploads is the ordinary case. It is reported as
        # progress, above, and NOT as a warning: a caution repeated on every
        # run teaches people to stop reading them.
        await context.emit(
            run_id,
            "node_completed",
            "No uploaded documents to search.",
            node=NODE,
            agent_id="document_agent",
        )
        return {"uploaded_document_results": []}

    question = state["original_question"]

    try:
        chunks = await retriever.search(question, limit=MAX_PASSAGES)
    except Exception as exc:  # a retrieval failure must not kill the run
        logger.warning("Document retrieval failed: %s", exc)
        await context.emit(
            run_id, "error", f"Internal document search failed: {exc}", node=NODE
        )
        return {
            "uploaded_document_results": [],
            "errors": [
                {
                    "node": NODE,
                    "provider": None,
                    "error_type": "provider_failure",
                    "message": str(exc),
                    "is_fatal": False,
                }
            ],
            "warnings": [
                "Uploaded documents could not be searched; the report rests on "
                "external evidence alone."
            ],
        }

    if not chunks:
        await context.emit(
            run_id,
            "node_completed",
            "No uploaded document passages matched this question.",
            node=NODE,
            agent_id="document_agent",
        )
        return {"uploaded_document_results": []}

    start = marker_block_start(NODE, state.get("max_results", 50))
    markers = allocate_markers(start, len(chunks))
    evidence = [
        chunk_to_evidence(chunk, marker, relevance_score=chunk.get("similarity"))
        for chunk, marker in zip(chunks, markers, strict=True)
    ]

    await context.emit(
        run_id,
        "evidence_stored",
        f"{len(evidence)} internal passages recorded as evidence "
        f"({markers[0]}-{markers[-1]})",
        node=NODE,
        data={"count": len(evidence)},
    )

    findings = None
    warnings: list[str] = []
    errors: list[dict] = []

    try:
        result = await context.models.complete_structured(
            role=ModelRole.EXTRACTION,
            schema=DocumentFindings,
            instructions=build_instructions(INSTRUCTIONS),
            user_input=(
                f"Research question:\n{question}\n\n"
                "Retrieved internal passages:\n"
                + wrap_untrusted(
                    format_evidence_for_prompt(evidence),
                    source="documents uploaded by users",
                )
            ),
            node=NODE,
            purpose="extract and synthesise internal documents",
        )
        findings = result.output
        warnings.extend(result.warnings)
    except LLMError as exc:
        # The passages are real and citable; only the interpretation is missing.
        logger.warning("Document synthesis failed: %s", exc)
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
            "Internal passages were retrieved but could not be summarised; they "
            "are listed without an interpretive summary."
        )

    if findings:
        by_marker = {e.marker: e for e in findings.extractions}
        for entry in evidence:
            extraction = by_marker.get(entry["marker"])
            if extraction:
                entry["relevance_score"] = extraction.relevance_score

    await context.emit(
        run_id,
        "node_completed",
        f"Internal documents reviewed: {len(evidence)} passages",
        node=NODE,
        agent_id="document_agent",
    )

    return {
        "uploaded_document_results": [dict(c) for c in chunks],
        "evidence_records": evidence,
        "document_findings": findings,
        "evidence_gaps": findings.evidence_gaps if findings else [],
        "errors": errors,
        "warnings": warnings + (findings.warnings if findings else []),
    }


__all__ = ["MAX_PASSAGES", "NODE", "document_agent"]
