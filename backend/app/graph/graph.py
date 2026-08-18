"""The research workflow graph.

    START
      -> intake_and_scope
      -> supervisor_planner
      -> { research_agent, literature_agent, patent_agent,
           document_agent }                                   (parallel)
      -> development_strategy_agent
      -> supervisor_synthesis
      -> evidence_reviewer
      -> report_generation  (or back to synthesis once, on verification failure)
      -> END

The four specialist agents run concurrently because none depends on the
others' output; they are joined by a fan-in edge before strategy runs. State
fields they all write use additive reducers, so concurrent updates merge rather
than overwrite.

Conditional edges handle: a missing objective or plan (fatal, skip to end),
verification failure (one bounded revision), and cancellation between nodes.
Provider unavailability is *not* an edge - it is handled inside the agent
nodes, which record the failure and let the run continue with what remains.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.context import RunContext
from app.graph.nodes.documents import NODE as NODE_DOCUMENTS
from app.graph.nodes.documents import document_agent
from app.graph.nodes.intake import (
    NODE_INTAKE,
    NODE_PLANNER,
    intake_and_scope,
    supervisor_planner,
)
from app.graph.nodes.literature import NODE as NODE_LITERATURE
from app.graph.nodes.literature import literature_agent
from app.graph.nodes.patents import NODE as NODE_PATENT
from app.graph.nodes.patents import patent_agent
from app.graph.nodes.research import NODE as NODE_RESEARCH
from app.graph.nodes.research import research_agent
from app.graph.nodes.reviewer import NODE as NODE_REVIEWER
from app.graph.nodes.reviewer import evidence_reviewer
from app.graph.nodes.strategy import NODE as NODE_STRATEGY
from app.graph.nodes.strategy import development_strategy_agent
from app.graph.nodes.synthesis import (
    NODE_REPORT,
    NODE_SYNTHESIS,
    report_generation,
    supervisor_synthesis,
)
from app.graph.state import ResearchState

logger = logging.getLogger(__name__)

NodeFn = Callable[[ResearchState, RunContext], Awaitable[dict]]


def _bind(fn: NodeFn, context: RunContext) -> Callable[[ResearchState], Awaitable[dict]]:
    """Inject the run context, and guard every node with a cancellation check.

    Checking between nodes rather than inside them means a cancel takes effect
    at the next boundary without aborting an in-flight API call, so partial
    work is still checkpointed.
    """

    async def node(state: ResearchState) -> dict:
        if await context.check_cancelled():
            logger.info("Run %s cancelled before %s", state.get("run_id"), fn.__name__)
            return {"warnings": [f"Run cancelled before {fn.__name__}."]}
        return await fn(state, context)

    node.__name__ = fn.__name__
    return node


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def _has_fatal_error(state: ResearchState) -> bool:
    return any(e.get("is_fatal") for e in state.get("errors", []))


def route_after_intake(state: ResearchState) -> str:
    """Without a structured objective there is nothing to research."""
    if _has_fatal_error(state) or state.get("structured_objective") is None:
        return "abort"
    return "plan"


def route_after_planning(state: ResearchState) -> list[str]:
    """Fan out to the four specialists, or abort.

    Returns node names rather than a semantic key because LangGraph fans out on
    a returned *sequence* of destinations; a path_map value cannot itself be a
    list.
    """
    if _has_fatal_error(state) or state.get("research_plan") is None:
        return [END]
    return [NODE_RESEARCH, NODE_LITERATURE, NODE_PATENT, NODE_DOCUMENTS]


def route_after_verification(state: ResearchState) -> str:
    """One bounded revision when verification finds high-severity problems.

    The bound matters: without it a model that repeatedly fails the same check
    would loop, and every pass costs real tokens.
    """
    verification = state.get("verification")
    if verification is not None and verification.requires_revision:
        return "revise"
    return "finalise"


def route_after_strategy(state: ResearchState) -> str:
    if _has_fatal_error(state):
        return "abort"
    return "synthesise"


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def build_graph(context: RunContext, checkpointer: Any = None) -> Any:
    """Build and compile the research graph."""
    builder = StateGraph(ResearchState)

    builder.add_node(NODE_INTAKE, _bind(intake_and_scope, context))
    builder.add_node(NODE_PLANNER, _bind(supervisor_planner, context))
    builder.add_node(NODE_RESEARCH, _bind(research_agent, context))
    builder.add_node(NODE_LITERATURE, _bind(literature_agent, context))
    builder.add_node(NODE_PATENT, _bind(patent_agent, context))
    builder.add_node(NODE_DOCUMENTS, _bind(document_agent, context))
    builder.add_node(NODE_STRATEGY, _bind(development_strategy_agent, context))
    builder.add_node(NODE_SYNTHESIS, _bind(supervisor_synthesis, context))
    builder.add_node(NODE_REVIEWER, _bind(evidence_reviewer, context))
    builder.add_node(NODE_REPORT, _bind(report_generation, context))

    builder.add_edge(START, NODE_INTAKE)

    builder.add_conditional_edges(
        NODE_INTAKE,
        route_after_intake,
        {"plan": NODE_PLANNER, "abort": END},
    )

    # Fan out to the four specialists. Returning several destinations makes
    # LangGraph schedule them concurrently.
    builder.add_conditional_edges(
        NODE_PLANNER,
        route_after_planning,
        [NODE_RESEARCH, NODE_LITERATURE, NODE_PATENT, NODE_DOCUMENTS, END],
    )

    # Fan in: strategy waits for all four. The document branch is included even
    # when the project has no uploads - it returns immediately in that case, and
    # a node that is always scheduled is simpler to reason about than one whose
    # presence in the graph depends on data.
    builder.add_edge(
        [NODE_RESEARCH, NODE_LITERATURE, NODE_PATENT, NODE_DOCUMENTS], NODE_STRATEGY
    )

    builder.add_conditional_edges(
        NODE_STRATEGY,
        route_after_strategy,
        {"synthesise": NODE_SYNTHESIS, "abort": END},
    )

    builder.add_edge(NODE_SYNTHESIS, NODE_REVIEWER)

    builder.add_conditional_edges(
        NODE_REVIEWER,
        route_after_verification,
        {"revise": NODE_SYNTHESIS, "finalise": NODE_REPORT},
    )

    builder.add_edge(NODE_REPORT, END)

    return builder.compile(checkpointer=checkpointer)


def build_graph_for(
    context: RunContext, checkpointer: Any = None
) -> Any:
    """Alias kept for readability at call sites."""
    return build_graph(context, checkpointer)


#: Node order for progress estimation in the UI.
NODE_SEQUENCE = (
    NODE_INTAKE,
    NODE_PLANNER,
    NODE_RESEARCH,
    NODE_LITERATURE,
    NODE_PATENT,
    NODE_DOCUMENTS,
    NODE_STRATEGY,
    NODE_SYNTHESIS,
    NODE_REVIEWER,
    NODE_REPORT,
)

NODE_AGENT = {
    NODE_INTAKE: "supervisor",
    NODE_PLANNER: "supervisor",
    NODE_RESEARCH: "research_agent",
    NODE_LITERATURE: "literature_agent",
    NODE_PATENT: "patent_agent",
    NODE_DOCUMENTS: "document_agent",
    NODE_STRATEGY: "development_strategy_agent",
    NODE_SYNTHESIS: "supervisor",
    NODE_REVIEWER: "evidence_reviewer",
    NODE_REPORT: "supervisor",
}


def progress_for(node: str) -> int:
    """Rough completion percentage, from real node position rather than a timer."""
    try:
        return int(((NODE_SEQUENCE.index(node) + 1) / len(NODE_SEQUENCE)) * 100)
    except ValueError:
        return 0


__all__ = [
    "NODE_AGENT",
    "NODE_SEQUENCE",
    "build_graph",
    "build_graph_for",
    "progress_for",
    "route_after_intake",
    "route_after_planning",
    "route_after_strategy",
    "route_after_verification",
]
