"""research_agent — scientific and technical background.

Runs concurrently with the literature and patent agents. It establishes
background and the target product profile.

It has no search tools of its own in version one, which creates an obvious
risk: an agent asked for "background" with no retrieval will produce fluent
recall, and recall is exactly what this system must not present as evidence.
The mitigation is structural. Every statement it makes carries a SupportLevel,
and with no evidence markers available to it, its claims are necessarily marked
`assumption` or `unsupported`. The report renders them as background framing,
never as findings, and the reviewer counts them as uncited.
"""

from __future__ import annotations

import logging

from app.graph.context import RunContext
from app.graph.state import ResearchState
from app.llm.prompts import build_instructions, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import BackgroundSummary

logger = logging.getLogger(__name__)

NODE = "research_agent"

INSTRUCTIONS = """\
You are the General Research Agent. Establish the scientific and technical
background for the objective.

You have NO retrieval tools in this run. That constrains what you may claim.

- Every statement must carry an honest support level. Because you have no
  citations available, essentially all of your statements are `assumption`
  (established domain framing that a specialist would recognise) or
  `unsupported`. Do not mark anything `direct` or `inferred`: those levels
  require cited evidence you do not have.
- Do not state specific numbers, percentages, durations, trial results or
  product names as fact. If a quantity matters, say that it needs to be
  established from evidence and put it in `open_questions`.
- Prefer framing over assertion. "Peptide stability in aqueous depots is
  typically governed by hydrolysis and aggregation" is useful background.
  "Peptide X retains 95% potency at 28 days" is a claim you cannot support.
- Use `open_questions` for what the literature and patent agents should
  resolve. This is your most valuable output, because those agents do have
  retrieval.

Cover: the disease or indication context, the molecule or modality, the
delivery technology and its mechanism, the route of administration and intended
use, a draft target product profile, competing technologies, and relevant
precedents.
"""


async def research_agent(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    objective = state.get("structured_objective")

    await context.emit(
        run_id,
        "node_started",
        "Establishing scientific and technical background",
        node=NODE,
        agent_id="research_agent",
    )

    objective_block = (
        objective.model_dump_json(indent=2)
        if objective
        else wrap_untrusted(state["original_question"], source="user")
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.RESEARCH,
            schema=BackgroundSummary,
            instructions=build_instructions(INSTRUCTIONS, includes_untrusted=False),
            user_input=f"Objective:\n{objective_block}",
            node=NODE,
            purpose="scientific background",
        )
    except LLMError as exc:
        logger.warning("Background research failed: %s", exc)
        await context.emit(
            run_id, "node_failed", f"Background research failed: {exc}", node=NODE
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
            "warnings": ["Background section unavailable: the research agent failed."],
        }

    summary = result.output

    # Enforce the support ceiling rather than trusting the instruction. An
    # agent with no evidence cannot produce a directly supported claim, so any
    # such label is downgraded here.
    downgraded = 0
    for claims in (
        summary.scientific_background,
        summary.target_product_profile,
        summary.competing_technologies,
        summary.relevant_precedents,
    ):
        for claim in claims:
            if claim.support in ("direct", "inferred") and not claim.citations:
                claim.support = "assumption"  # type: ignore[assignment]
                downgraded += 1

    warnings = list(result.warnings)
    if downgraded:
        warnings.append(
            f"{downgraded} background statement(s) claimed evidential support "
            "without citations and were relabelled as assumptions."
        )

    await context.emit(
        run_id,
        "node_completed",
        f"Background established with {len(summary.open_questions)} open questions",
        node=NODE,
        agent_id="research_agent",
        data={"open_questions": summary.open_questions},
    )

    return {
        "background_summary": summary,
        "warnings": warnings + summary.warnings,
        "total_input_tokens": result.usage.input_tokens,
        "total_output_tokens": result.usage.output_tokens,
    }
