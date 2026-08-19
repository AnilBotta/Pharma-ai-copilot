"""supervisor_synthesis and report_generation.

Synthesis writes the report body. Report generation is deterministic assembly:
it applies citation validation to every section, computes confidence from
evidence coverage, and appends the references and disclaimers sections from
stored data rather than from generated text.

Splitting them this way means the parts of the report that must be exactly
right - the reference list, the disclaimers, the citation markers - are built
by code, not by a model.
"""

from __future__ import annotations

import logging

from app.graph.context import RunContext
from app.graph.evidence import format_evidence_for_prompt
from app.graph.nodes.patents import PATENT_DISCLAIMER
from app.graph.state import ResearchState, evidence_markers
from app.llm.citations import (
    compute_section_confidence,
    extract_markers,
    find_overconfident_language,
    find_uncited_numeric_claims,
    validate_and_clean,
)
from app.llm.prompts import build_instructions, format_evidence_allowlist, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import SECTION_TITLES, ReportDraft, ReportSectionDraft

logger = logging.getLogger(__name__)

NODE_SYNTHESIS = "supervisor_synthesis"
NODE_REPORT = "report_generation"

GENERAL_DISCLAIMER = (
    "This platform provides research support only. It does not provide medical, "
    "regulatory, toxicological, clinical, or legal decisions, and does not replace "
    "qualified scientists, patent counsel, regulatory experts, toxicologists, "
    "clinicians, or statisticians."
)

#: Sections synthesis writes. The remainder are assembled deterministically.
GENERATED_SECTIONS = [
    key
    for key, _ in SECTION_TITLES.items()
    if key not in {"references", "limitations"}
]

INSTRUCTIONS = """\
You are the Scientist Supervisor writing the final report.

Write each section in Markdown. Ground every evidential statement in a cited
marker from the allowlist. Where you state something that is method or standard
practice rather than a finding, phrase it so a reader can tell the difference.

Requirements:
- Compare what the literature and the patent evidence show. Where they point
  different ways, say so explicitly rather than blending them.
- Carry contradictions into the report. A section that hides disagreement is
  worse than one that reports it.
- Label evidence limitations in place: preprint, in vitro only, animal only,
  abstract only, single study, small sample.
- Never describe full text as reviewed for a source marked abstract_only.
- Where a section has no supporting evidence, write "No reliable evidence was
  retrieved for this section." and stop. Do not fill it.
- Avoid words that assert certainty research cannot deliver: proven,
  conclusively, guarantees, definitively, always, will ensure.
- State no freedom-to-operate, validity or infringement conclusion.
- Do not give medical advice.

Write the executive summary last in your reasoning but place it first. It must
not contain any claim that does not appear, cited, in a later section.

Produce a section for each requested key. Use the exact section_key values
given; they are matched programmatically.
"""


async def supervisor_synthesis(state: ResearchState, context: RunContext) -> dict:
    """Write the report body."""
    run_id = state["run_id"]
    evidence = state.get("evidence_records", [])

    revision = state.get("revision_count", 0)
    label = "Revising the report" if revision else "Synthesising the final report"
    await context.emit(
        run_id, "node_started", label, node=NODE_SYNTHESIS, agent_id="supervisor"
    )

    sections = [
        f"Research question:\n{state['original_question']}",
        f"Sections to write (use these exact keys): {', '.join(GENERATED_SECTIONS)}",
    ]

    if objective := state.get("structured_objective"):
        sections.append(f"Structured objective:\n{objective.model_dump_json(indent=2)}")
    if background := state.get("background_summary"):
        sections.append(
            "Background framing (mostly unevidenced; treat as context, not findings):\n"
            + background.model_dump_json(indent=2)
        )
    if literature := state.get("literature_findings"):
        sections.append(f"Literature findings:\n{literature.model_dump_json(indent=2)}")
    if patents := state.get("patent_findings"):
        sections.append(f"Patent findings:\n{patents.model_dump_json(indent=2)}")
    if strategy := state.get("development_strategy"):
        sections.append(f"Development strategy:\n{strategy.model_dump_json(indent=2)}")

    if state.get("contradictions"):
        sections.append(
            "Contradictions that MUST appear in the report:\n"
            + "\n".join(f"- {c}" for c in state["contradictions"])
        )
    if state.get("patent_search_unavailable"):
        sections.append(
            "IMPORTANT: no patent search was performed. The patent landscape "
            "section must state that patents were not searched, and must not "
            "imply that no relevant patents exist."
        )
    if state.get("no_literature_found"):
        sections.append(
            "IMPORTANT: no literature was retrieved. Sections depending on "
            "literature must state that no reliable evidence was found."
        )

    # Corrections from a previous verification pass.
    if verification := state.get("verification"):
        if revision and verification.issues:
            sections.append(
                "The previous draft had these verified problems. Fix each one:\n"
                + "\n".join(
                    f"- [{i.severity}] {i.section_key}: {i.detail}"
                    + (f" (suggested: {i.suggested_correction})" if i.suggested_correction else "")
                    for i in verification.issues
                )
            )

    sections.append(format_evidence_allowlist([dict(e) for e in evidence]))
    sections.append(
        "Evidence detail:\n"
        + wrap_untrusted(format_evidence_for_prompt(evidence), source="retrieved evidence")
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.SYNTHESIS,
            schema=ReportDraft,
            instructions=build_instructions(INSTRUCTIONS),
            user_input="\n\n".join(sections),
            node=NODE_SYNTHESIS,
            purpose="report synthesis",
        )
    except LLMError as exc:
        logger.warning("Synthesis failed: %s", exc)
        await context.emit(
            run_id, "node_failed", f"Report synthesis failed: {exc}", node=NODE_SYNTHESIS
        )
        return {
            "errors": [
                {
                    "node": NODE_SYNTHESIS,
                    "provider": None,
                    "error_type": getattr(exc, "error_type", "model_error"),
                    "message": str(exc),
                    "is_fatal": True,
                }
            ]
        }

    draft = result.output
    await context.emit(
        run_id,
        "node_completed",
        f"Report drafted: {len(draft.sections)} sections",
        node=NODE_SYNTHESIS,
        agent_id="supervisor",
    )

    return {
        "report": draft,
        "warnings": list(result.warnings) + draft.warnings,
        "total_input_tokens": result.usage.input_tokens,
        "total_output_tokens": result.usage.output_tokens,
    }


async def report_generation(state: ResearchState, context: RunContext) -> dict:
    """Assemble the final report deterministically.

    No model call. Citation stripping, confidence computation, the reference
    list and the disclaimers are all produced from stored data, so they cannot
    drift from what was actually retrieved.
    """
    run_id = state["run_id"]
    await context.emit(
        run_id, "node_started", "Assembling the final report", node=NODE_REPORT
    )

    draft = state.get("report")
    evidence = state.get("evidence_records", [])
    known = evidence_markers(state)

    if draft is None:
        return {
            "warnings": ["No report was produced because synthesis did not complete."]
        }

    cleaned_sections: list[ReportSectionDraft] = []
    confidence: dict[str, str] = {}
    stripped_total = 0
    all_stripped: set[str] = set()

    for section in draft.sections:
        validation = validate_and_clean(section.body_markdown, known)
        stripped_total += len(validation.invalid_markers)
        all_stripped.update(validation.invalid_markers)

        body = validation.cleaned_text
        cited = validation.valid_markers

        # Confidence from coverage, not from the model's opinion of itself.
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        cited_paragraphs = sum(1 for p in paragraphs if extract_markers(p))
        level, rationale = compute_section_confidence(
            total_claims=len(paragraphs),
            cited_claims=cited_paragraphs,
            distinct_sources=len(set(cited)),
            has_contradictions=bool(state.get("contradictions")),
        )
        confidence[section.section_key] = level

        notes = []
        if uncited_numbers := find_uncited_numeric_claims(body):
            notes.append(
                f"{len(uncited_numbers)} quantitative statement(s) in this section "
                "are not tied to a cited source."
            )
        if overconfident := find_overconfident_language(body):
            notes.append(
                "Language asserting certainty beyond the evidence: "
                + ", ".join(sorted(set(overconfident))[:5])
            )
        if notes:
            body += "\n\n> **Verification notes.** " + " ".join(notes)

        body += f"\n\n> *Confidence: {level.replace('_', ' ')}. {rationale}*"

        cleaned_sections.append(
            ReportSectionDraft(
                section_key=section.section_key,
                title=SECTION_TITLES.get(section.section_key, section.title),
                body_markdown=body,
            )
        )

    cleaned_sections.append(_build_limitations(state, stripped_total))
    cleaned_sections.append(_build_references(evidence))

    warnings = []
    if stripped_total:
        message = (
            f"{stripped_total} citation(s) referenced sources that were never "
            f"retrieved ({', '.join(sorted(all_stripped))}) and were removed."
        )
        warnings.append(message)
        await context.emit(run_id, "warning", message, node=NODE_REPORT)

    await context.emit(
        run_id,
        "node_completed",
        f"Report assembled: {len(cleaned_sections)} sections, {len(evidence)} references",
        node=NODE_REPORT,
    )

    return {
        "report": ReportDraft(
            executive_summary=validate_and_clean(draft.executive_summary, known).cleaned_text,
            sections=cleaned_sections,
            key_uncertainties=draft.key_uncertainties,
            warnings=draft.warnings,
        ),
        "section_confidence": confidence,
        "warnings": warnings,
    }


def _build_references(evidence: list) -> ReportSectionDraft:
    """The reference list, built from stored evidence only.

    Every entry corresponds to a record that was retrieved. There is no path by
    which a reference can appear here without a matching evidence row.
    """
    if not evidence:
        body = "No sources were retrieved for this run."
    else:
        lines = []
        for entry in sorted(evidence, key=lambda e: int(e["marker"][1:])):
            authors = ", ".join(entry.get("authors", [])[:3])
            if len(entry.get("authors", [])) > 3:
                authors += " et al."
            parts = [f"**[{entry['marker']}]**"]
            if authors:
                parts.append(f"{authors}.")
            parts.append(f"{entry['title']}.")
            if entry.get("publication_date"):
                parts.append(f"{entry['publication_date'][:4]}.")
            if entry.get("identifier"):
                kind = (entry.get("identifier_type") or "id").upper()
                parts.append(f"{kind}: {entry['identifier']}.")
            if entry.get("url"):
                parts.append(f"<{entry['url']}>")
            # For an external source the provider and access level say how much
            # of it we actually read. For an uploaded document the provider IS
            # the filename - already printed as the title - and `full_text` is
            # true of the passage but reads as a retrieval achievement, borrowing
            # the language of a paper we obtained in full. What a reader needs to
            # know about this source is that it is internal.
            if entry["source_type"] == "internal_document":
                parts.append("*(internal document, not peer-reviewed)*")
            else:
                parts.append(
                    f"*({entry['provider']}, {entry['access_level'].replace('_', ' ')})*"
                )
            lines.append(" ".join(parts))
        body = "\n\n".join(lines)

    return ReportSectionDraft(
        section_key="references", title=SECTION_TITLES["references"], body_markdown=body
    )


def _build_limitations(state: ResearchState, stripped: int) -> ReportSectionDraft:
    """Limitations and disclaimers, assembled from what actually happened."""
    lines = [GENERAL_DISCLAIMER, "", "### Scope of this assessment", ""]

    evidence = state.get("evidence_records", [])
    literature_count = sum(1 for e in evidence if e["source_type"] == "literature")
    patent_count = sum(1 for e in evidence if e["source_type"] == "patent")
    document_count = sum(1 for e in evidence if e["source_type"] == "internal_document")
    abstract_only = sum(1 for e in evidence if e["access_level"] == "abstract_only")

    # The breakdown has to account for every source in the total. It listed only
    # publications and patents, so a run drawing on uploaded documents printed
    # "14 retrieved sources (4 publications, 4 patent families)" - six sources
    # unaccounted for, in the section a careful reader turns to first. Worse
    # than a wrong number: a reader who does not reconcile it concludes the
    # report rests on eight published sources, when a third of its citations are
    # internal material nobody outside the organisation has reviewed.
    breakdown = [
        f"{literature_count} publications",
        f"{patent_count} patent families",
    ]
    if document_count:
        breakdown.append(f"{document_count} passages from uploaded internal documents")

    lines.append(
        f"- This report is based on {len(evidence)} retrieved sources "
        f"({', '.join(breakdown)})."
    )
    if document_count:
        lines.append(
            f"- {document_count} of those sources are internal documents uploaded "
            "to this workspace. They have not been peer-reviewed, published or "
            "verified by anyone outside your organisation, and carry no "
            "independent standing. Claims resting on them are the "
            "organisation's own account of its own work."
        )
    if abstract_only:
        lines.append(
            f"- {abstract_only} source(s) were reviewed at abstract level only. "
            "Full texts were not retrieved and their methods were not examined."
        )
    if state.get("patent_search_unavailable"):
        lines.append(
            "- **No patent search was performed.** The patent provider was "
            "unavailable. Absence of patent findings here is not evidence that "
            "no relevant patents exist."
        )
    if state.get("no_literature_found"):
        lines.append(
            "- **No literature was retrieved.** Conclusions drawn without "
            "retrieved literature are unsupported."
        )
    if stripped:
        lines.append(
            f"- {stripped} generated citation(s) did not correspond to any "
            "retrieved record and were removed during verification."
        )
    if state.get("date_from") or state.get("date_to"):
        lines.append(
            f"- Literature was restricted to {state.get('date_from') or 'any'}"
            f" to {state.get('date_to') or 'present'}. Work outside that window "
            "was not considered."
        )
    if errors := state.get("errors"):
        non_fatal = [e for e in errors if not e.get("is_fatal")]
        if non_fatal:
            lines.append(
                f"- {len(non_fatal)} provider or processing error(s) occurred "
                "during this run; affected sources are missing from the evidence base."
            )

    lines += [
        "",
        "### Patent notice",
        "",
        PATENT_DISCLAIMER,
        "",
        "### Interpretation",
        "",
        "- Statements labelled as assumptions reflect standard development "
        "practice rather than retrieved evidence.",
        "- Confidence ratings are computed from evidence coverage and source "
        "count, not from the model's own assessment of its output.",
        "- Absence of evidence in this report reflects what these searches "
        "retrieved, and is not evidence of absence.",
    ]

    return ReportSectionDraft(
        section_key="limitations",
        title=SECTION_TITLES["limitations"],
        body_markdown="\n".join(lines),
    )
