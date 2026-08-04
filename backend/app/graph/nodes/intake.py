"""intake_and_scope and supervisor_planner.

The Scientist Supervisor's first two acts: work out what was actually asked,
then decide how to answer it. Both produce structured output, so the plan is
data the rest of the graph can act on rather than prose to be re-interpreted.
"""

from __future__ import annotations

import logging

from app.graph.context import RunContext
from app.graph.state import ResearchState
from app.llm.prompts import build_instructions, wrap_untrusted
from app.llm.provider import LLMError, ModelRole
from app.models.agents import ResearchPlan, StructuredObjective

logger = logging.getLogger(__name__)

NODE_INTAKE = "intake_and_scope"
NODE_PLANNER = "supervisor_planner"

INTAKE_INSTRUCTIONS = """\
You are the Scientist Supervisor. Convert the user's research request into a
structured objective.

- Restate the objective faithfully. Do not expand its scope or add goals the
  user did not ask for.
- Derive specific, answerable research questions. Prefer several precise
  questions over one broad one.
- Fill the structured fields only from what the user supplied or what the
  question unambiguously implies. Leave a field null rather than guessing.
- Record genuine ambiguities in `ambiguities` instead of silently resolving
  them. A question that could be read two ways is information the report needs
  to carry, not a decision for you to make quietly.
- Use `out_of_scope` to state what this assessment will not cover, so the
  report cannot be read as claiming more than it examined.
"""

PLANNER_INSTRUCTIONS = """\
You are the Scientist Supervisor. Produce a research plan for the structured
objective.

Design literature and patent search strategies:

- Literature queries target PubMed and Europe PMC. Use domain vocabulary,
  synonyms and MeSH-style terms. Prefer several focused queries over one long
  one, because an over-constrained query returns nothing and a vague one
  returns noise.
- Patent queries target EPO OPS. Express them as concepts, synonyms, applicant
  names and CPC/IPC classifications where you can identify plausible ones.
- Give each query a short rationale. The user sees these, so state what the
  query is for.

`required_agents` may contain: research_agent, literature_agent, patent_agent,
development_strategy_agent. Include an agent only when the objective genuinely
needs it.

Record real methodological risks in `known_risks` - a literature that is likely
sparse, a technology whose terminology is unstable, a field where most evidence
is preclinical. Do not pad this list.
"""


def _describe_request(state: ResearchState) -> str:
    """Render the user's request, fencing the free-text parts.

    The research question and additional instructions are user input. They are
    trusted as *intent* but still fenced, because a user can paste text from a
    document they did not write.
    """
    fields = [
        ("Molecule or modality", state.get("molecule")),
        ("Indication", state.get("indication")),
        ("Dosage form", state.get("dosage_form")),
        ("Route of administration", state.get("route_of_administration")),
        ("Delivery technology", state.get("delivery_technology")),
        ("Development stage", state.get("development_stage")),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value]

    if state.get("date_from") or state.get("date_to"):
        lines.append(
            f"Literature date range: {state.get('date_from') or 'any'}"
            f" to {state.get('date_to') or 'present'}"
        )
    if state.get("jurisdictions"):
        lines.append(f"Patent jurisdictions: {', '.join(state['jurisdictions'])}")

    parts = ["Research question:", wrap_untrusted(state["original_question"], source="user")]
    if lines:
        parts.append("\nStructured parameters:\n" + "\n".join(lines))
    if state.get("additional_instructions"):
        parts.append(
            "\nAdditional instructions from the user:\n"
            + wrap_untrusted(state["additional_instructions"], source="user")
        )
    return "\n".join(parts)


async def intake_and_scope(state: ResearchState, context: RunContext) -> dict:
    """Turn the raw request into a structured objective."""
    run_id = state["run_id"]
    await context.emit(
        run_id,
        "node_started",
        "Interpreting the research objective",
        node=NODE_INTAKE,
        agent_id="supervisor",
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.SUPERVISOR,
            schema=StructuredObjective,
            instructions=build_instructions(INTAKE_INSTRUCTIONS),
            user_input=_describe_request(state),
            node=NODE_INTAKE,
            purpose="structure the research objective",
        )
    except LLMError as exc:
        # Without a structured objective there is nothing to plan against, so
        # this failure is fatal rather than degraded.
        await context.emit(
            run_id, "node_failed", f"Could not interpret the objective: {exc}", node=NODE_INTAKE
        )
        return {
            "errors": [
                {
                    "node": NODE_INTAKE,
                    "provider": None,
                    "error_type": getattr(exc, "error_type", "model_error"),
                    "message": str(exc),
                    "is_fatal": True,
                }
            ]
        }

    objective = result.output
    await context.emit(
        run_id,
        "node_completed",
        f"Objective structured into {len(objective.research_questions)} research questions",
        node=NODE_INTAKE,
        agent_id="supervisor",
        data={
            "research_questions": objective.research_questions,
            "ambiguities": objective.ambiguities,
        },
    )

    warnings = list(result.warnings)
    if objective.ambiguities:
        warnings.append(
            "The request was ambiguous in "
            f"{len(objective.ambiguities)} respect(s); the report states the "
            "interpretation used."
        )

    return {
        "structured_objective": objective,
        "warnings": warnings,
        "total_input_tokens": result.usage.input_tokens,
        "total_output_tokens": result.usage.output_tokens,
    }


async def supervisor_planner(state: ResearchState, context: RunContext) -> dict:
    """Produce the research plan and search strategies."""
    run_id = state["run_id"]
    objective = state.get("structured_objective")
    if objective is None:
        return {}  # intake failed; the conditional edge routes around this

    await context.emit(
        run_id,
        "node_started",
        "Planning the research approach",
        node=NODE_PLANNER,
        agent_id="supervisor",
    )

    available = _available_providers(context)
    user_input = (
        f"Structured objective:\n{objective.model_dump_json(indent=2)}\n\n"
        f"Available search providers: {', '.join(available) or 'none'}.\n"
        f"Maximum results per provider: {state.get('max_results', 50)}.\n\n"
        "Design searches only for providers listed as available."
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.SUPERVISOR,
            schema=ResearchPlan,
            instructions=build_instructions(PLANNER_INSTRUCTIONS, includes_untrusted=False),
            user_input=user_input,
            node=NODE_PLANNER,
            purpose="produce the research plan",
        )
    except LLMError as exc:
        await context.emit(
            run_id, "node_failed", f"Could not build a research plan: {exc}", node=NODE_PLANNER
        )
        return {
            "errors": [
                {
                    "node": NODE_PLANNER,
                    "provider": None,
                    "error_type": getattr(exc, "error_type", "model_error"),
                    "message": str(exc),
                    "is_fatal": True,
                }
            ]
        }

    plan = result.output
    await context.emit(
        run_id,
        "node_completed",
        (
            f"Plan ready: {len(plan.literature_searches)} literature "
            f"and {len(plan.patent_searches)} patent searches"
        ),
        node=NODE_PLANNER,
        agent_id="supervisor",
        data={
            "literature_queries": [s.query for s in plan.literature_searches],
            "patent_queries": [s.query for s in plan.patent_searches],
            "required_agents": plan.required_agents,
        },
    )

    return {
        "research_plan": plan,
        "warnings": result.warnings,
        "total_input_tokens": result.usage.input_tokens,
        "total_output_tokens": result.usage.output_tokens,
    }


def _available_providers(context: RunContext) -> list[str]:
    """Only configured providers are offered to the planner.

    Planning searches for a provider that cannot run would produce queries the
    user sees but that never execute, which reads as work that was done.
    """
    names = [p.name for p in context.literature_providers if p.is_configured]
    names += [p.name for p in context.patent_providers if p.is_configured]
    return names
