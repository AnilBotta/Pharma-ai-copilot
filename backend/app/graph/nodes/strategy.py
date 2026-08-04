"""development_strategy_agent.

Turns verified literature and patent evidence into a preliminary development
strategy: CQAs, formulation pathway, analytical and nonclinical needs, risks,
recommended experiments and a stage-gate plan.

Runs after the retrieval branch has joined, so it sees the full evidence set.
"""

from __future__ import annotations

import logging

from app.graph.context import RunContext
from app.graph.evidence import format_evidence_for_prompt
from app.graph.state import ResearchState
from app.llm.prompts import build_instructions, format_evidence_allowlist, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import DevelopmentStrategy

logger = logging.getLogger(__name__)

NODE = "development_strategy_agent"

INSTRUCTIONS = """\
You are the Development Strategy Agent. Produce a preliminary pharmaceutical
development strategy grounded in the supplied evidence.

Grounding rules:
- Cite evidence markers wherever a statement is evidence-based.
- Where you are applying standard development practice rather than citing a
  source, mark the claim `assumption` and say so. This is legitimate and
  expected: much of a development strategy is method, not finding.
- Where you are reasoning from cited evidence to a consequence, mark it
  `inferred` and cite what you reasoned from.
- Never mark a claim `direct` without a citation.

Do not present speculative content as established. Specifically:
- Do not assert numerical targets, specifications or acceptance criteria as
  known. Propose them as ranges to be established, and say what work would
  establish them.
- Do not claim any regulatory precedent, acceptance or expectation without a
  citation supporting it.
- Do not claim safety, biocompatibility or tolerability. Frame these as
  questions the nonclinical programme must answer.
- Do not assert patent clearance or freedom to operate in any form.

Every section may be empty. An empty section means the evidence did not support
saying anything, which is a legitimate and useful answer. Leaving it empty is
strongly preferred to filling it with plausible-sounding text.

`evidence_gaps` and `recommended_experiments` are the most valuable outputs
here: they say what is not yet known and what would resolve it. Tie each
recommended experiment to a specific gap.
"""


async def development_strategy_agent(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    evidence = state.get("evidence_records", [])

    await context.emit(
        run_id,
        "node_started",
        f"Deriving development strategy from {len(evidence)} sources",
        node=NODE,
        agent_id="development_strategy_agent",
    )

    literature = state.get("literature_findings")
    patents = state.get("patent_findings")
    background = state.get("background_summary")

    sections = [f"Research question:\n{state['original_question']}"]
    if objective := state.get("structured_objective"):
        sections.append(f"Structured objective:\n{objective.model_dump_json(indent=2)}")
    if background:
        sections.append(
            "Background (largely unevidenced framing):\n"
            + background.model_dump_json(indent=2)
        )
    if literature:
        sections.append(f"Literature findings:\n{literature.model_dump_json(indent=2)}")
    if patents:
        sections.append(f"Patent findings:\n{patents.model_dump_json(indent=2)}")

    if state.get("patent_search_unavailable"):
        sections.append(
            "NOTE: no patent search was performed for this run. Do not comment on "
            "the patent landscape, and do not treat the absence of patent evidence "
            "as evidence of absence."
        )

    sections.append(format_evidence_allowlist([dict(e) for e in evidence]))
    sections.append(
        "Evidence detail:\n"
        + wrap_untrusted(format_evidence_for_prompt(evidence), source="retrieved evidence")
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.SYNTHESIS,
            schema=DevelopmentStrategy,
            instructions=build_instructions(INSTRUCTIONS),
            user_input="\n\n".join(sections),
            node=NODE,
            purpose="development strategy",
        )
    except LLMError as exc:
        logger.warning("Development strategy failed: %s", exc)
        await context.emit(
            run_id, "node_failed", f"Development strategy failed: {exc}", node=NODE
        )
        return {
            "errors": [
                {
                    "node": NODE,
                    "provider": None,
                    "error_type": getattr(exc, "error_type", "model_error"),
                    "message": str(exc),
                    "is_fatal": False,
                }
            ],
            "warnings": [
                "The development strategy could not be produced. The report "
                "contains the retrieved evidence without a strategy section."
            ],
        }

    strategy = result.output

    await context.emit(
        run_id,
        "node_completed",
        (
            f"Strategy drafted: {len(strategy.critical_quality_attributes)} CQAs, "
            f"{len(strategy.risks)} risks, "
            f"{len(strategy.recommended_experiments)} recommended experiments"
        ),
        node=NODE,
        agent_id="development_strategy_agent",
        data={
            "cqa_count": len(strategy.critical_quality_attributes),
            "risk_count": len(strategy.risks),
            "gap_count": len(strategy.evidence_gaps),
        },
    )

    return {
        "development_strategy": strategy,
        "evidence_gaps": strategy.evidence_gaps,
        "warnings": list(result.warnings) + strategy.warnings,
        "total_input_tokens": result.usage.input_tokens,
        "total_output_tokens": result.usage.output_tokens,
    }
