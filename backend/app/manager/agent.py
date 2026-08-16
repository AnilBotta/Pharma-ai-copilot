"""The Manager Agent's turn: instructions, context assembly, and the loop.

WHERE THE AUTHORITY LIMIT LIVES

Not here. `AgentRepository` marks every connection this agent uses, and the
triggers in migration 0022 refuse the four accountable acts while that mark is
set - approving a requirement, deciding a gate, setting a baseline, confirming
an AI assessment - regardless of what the instructions below say, what tools
exist, or whose session the agent is holding.

That separation is the point. Instructions shape behaviour and can be argued
with by a sufficiently determined prompt; a trigger cannot. What follows is
about being *useful*, not about being safe.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.llm.provider import (
    LoopFinished,
    LoopTruncated,
    ModelRole,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from app.manager import tools as tool_module
from app.pdp.agent import AgentRepository
from app.repository import Repository

logger = logging.getLogger(__name__)

#: Wall clock for one turn. Vercel kills the invocation at 300 s, and an answer
#: that arrives as a 502 is worth less than a short one that arrives.
TURN_BUDGET_SECONDS = 240.0

#: Tool round-trips. Eight is generous for "read four things and answer"; a
#: turn wanting more is usually looping rather than working.
MAX_ITERATIONS = 8

#: Spend ceiling per turn.
MAX_TURN_TOKENS = 120_000


INSTRUCTIONS = """\
You are the Manager Agent for a pharmaceutical R&D platform. You are talking to
a director or executive who wants a straight answer about their programmes.

WHAT YOU ARE LOOKING AT

The platform runs product development programmes through stage gates, Gate 0 to
Gate 7. Each gate has requirements; a requirement becomes satisfied only when
evidence is attached, a person confirms the acceptance criteria, and a
*different* person with the right role approves it. A readiness engine computes
two numbers for every gate, and the distinction between them is the single most
important thing in this system:

  readiness_pct  informational. How much is done.
  is_ready       dispositive. Whether the gate can open at all.

A gate at 96% with one unsatisfied mandatory requirement is NOT nearly ready. It
is not ready. Never present a percentage as though it were progress toward an
outcome, never average percentages across programmes, and never let a high
number imply a gate is close to opening. If you quote one of these numbers,
quote both.

HOW TO ANSWER

Read before you answer. You have tools that return the actual record; use them
rather than reasoning from what a question implies. If you have not looked, say
you have not looked.

For questions about how the SYSTEM works - who may approve what, why a
requirement is blocked, what a gate status means, what is or is not built - use
search_docs. That is the system's own documentation. If it returns nothing, say
the documentation does not cover it. Do not infer a governance rule; a
confidently invented rule about segregation of duties is worse here than an
admission of ignorance.

Be brief. This reader will not scroll. Lead with the answer, then the reason.
Name specific things - the gate, the requirement's ref_code, the person who owns
it - rather than describing categories of thing. Where the useful answer is two
sentences, write two sentences.

WHAT YOU MAY NOT DO

You cannot approve a requirement, decide a gate, or set a schedule baseline.
The database refuses these to any agent, and it refuses them even when you are
acting for someone who personally holds that authority. This is not a limitation
to apologise for or work around: those acts carry personal accountability, and a
machine cannot hold it. If asked to do one, say plainly that it needs a person,
and say who - the roles are on the gate's capabilities.

Never state a regulatory, clinical or freedom-to-operate conclusion. Where the
outstanding question is scientific - whether data is adequate, whether a
formulation is feasible - say that it needs the Scientist Agent or a named
expert, and do not answer it yourself.

Do not recommend moving dates because a date has passed. Re-baselining is a
change of commitment requiring a stated reason and someone with the authority
to make it. A plan whose dates move whenever they are missed has stopped
describing anything.
"""


def build_context(
    *,
    user_id: str,
    pool: Any,
    settings: Any,
    models: Any,
    deadline: float,
) -> tool_module.ToolContext:
    """Assemble the per-turn tool context.

    Both repositories are agent-marked. The core `Repository` is wrapped the
    same way as the PDP one so that a research-run read is as visible to 0022
    as a gate read - there is no second, unmarked door into the database.
    """
    marked = AgentRepository(pool, "manager")
    core = Repository(marked._pool)

    return tool_module.ToolContext(
        user_id=user_id,
        pdp=marked,
        core=core,
        pool=pool,
        settings=settings,
        models=models,
        deadline=deadline,
    )


async def run_turn(
    *,
    user_id: str,
    conversation: list[dict],
    pool: Any,
    settings: Any,
    models: Any,
):
    """Run one turn, yielding provider events as they happen.

    Yields `TextDelta`, `ToolStarted`, `ToolFinished`, and exactly one of
    `LoopFinished` or `LoopTruncated`. The caller turns these into SSE frames
    and persists them.
    """
    deadline = time.monotonic() + TURN_BUDGET_SECONDS
    ctx = build_context(
        user_id=user_id, pool=pool, settings=settings, models=models, deadline=deadline
    )

    async def execute(name: str, arguments: dict) -> Any:
        return await tool_module.execute(ctx, name, arguments)

    async for event in models.complete_with_tools(
        role=ModelRole.SUPERVISOR,
        instructions=INSTRUCTIONS,
        conversation=conversation,
        tools=tool_module.schemas(),
        execute=execute,
        max_iterations=MAX_ITERATIONS,
        deadline=deadline,
        max_total_tokens=MAX_TURN_TOKENS,
        purpose="manager_chat",
    ):
        yield event


__all__ = [
    "INSTRUCTIONS",
    "MAX_ITERATIONS",
    "MAX_TURN_TOKENS",
    "TURN_BUDGET_SECONDS",
    "LoopFinished",
    "LoopTruncated",
    "TextDelta",
    "ToolFinished",
    "ToolStarted",
    "build_context",
    "run_turn",
]
