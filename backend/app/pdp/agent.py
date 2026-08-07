"""The PDP Operations Agent and the Manager Agent.

WHAT MAKES THIS SAFE IS NOT IN THIS FILE
--------------------------------------

The agent calls the same repository a person's HTTP request calls. It gets no
private path, no elevated role and no bypass. When it tries to approve a
requirement, pass a gate or set a baseline, it is refused by the same database
triggers that refuse a human without the right role - plus three more, added in
migration 0022, that refuse it *because it is an agent* even when it is holding
a perfectly valid user session.

That distinction matters. A guarantee that lives in a tool schema is a promise
about this file. A guarantee that lives in a trigger survives somebody adding a
convenience wrapper next year without reading this docstring.

WHAT THE AGENT IS FOR
---------------------

Reading the record and saying something useful about it. A gate has 23
requirements across six disciplines; the useful question is not "what is the
percentage" but "which two things are actually holding this up, who owns them,
and what would unblock them". That is work, and it is work a model is good at.

What it produces is advisory by construction:

* `ai_assessment` on an evidence link - stored in a column that has existed
  since Phase C precisely so a machine's view has somewhere to live that is
  structurally not an approval, and that stays inert until a human confirms it.
* `recommendations` on the session - which nothing downstream reads as a
  decision, because nothing downstream reads it at all.

HANDOFF
-------

Scientific judgement is not this agent's job. When the outstanding question is
"is this stability data adequate for a depot formulation", it records a handoff
question for the Scientist Agent rather than answering it. The two agents have
different evidence standards and conflating them would let a project-management
model make a formulation claim.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from app.llm.provider import ModelRole
from app.models.agents import GateAssessment, PortfolioSummary
from app.pdp.repository import PdpRepository

logger = logging.getLogger(__name__)

#: Identifies the agent to the database for the life of a transaction. Set by
#: AgentRepository, checked by the triggers in migration 0022.
AGENT_SETTING = "app.acting_agent"


class AgentRepository(PdpRepository):
    """A PdpRepository that tells the database it is an agent.

    Subclassing rather than wrapping is deliberate: every method the human path
    has, the agent path has too, with identical behaviour up to the point where
    the database refuses. There is no second implementation to drift, and no
    list of "agent-safe methods" for somebody to add to by mistake.

    The mark is set per connection acquisition, so it covers every statement the
    method runs - including ones inside triggers.
    """

    def __init__(self, pool: Any, agent_name: str) -> None:
        # PdpRepository only ever reaches the database through
        # `self._pool.acquire()`, so handing it a pool whose connections arrive
        # already marked covers every method - including ones added later by
        # somebody who never reads this file.
        super().__init__(_MarkedPool(pool, agent_name))
        self._agent_name = agent_name


class _MarkedPool:
    """Hands out connections that identify themselves as an agent."""

    def __init__(self, pool: Any, agent_name: str) -> None:
        self._pool = pool
        self._agent_name = agent_name

    def acquire(self):
        return _MarkedAcquire(self._pool, self._agent_name)


class _MarkedAcquire:
    def __init__(self, pool: Any, agent_name: str) -> None:
        self._pool = pool
        self._agent_name = agent_name
        self._ctx = None
        self._conn = None

    async def __aenter__(self):
        self._ctx = self._pool.acquire()
        self._conn = await self._ctx.__aenter__()
        # `false` for is_local: the repository opens its transaction *after*
        # acquiring, so a transaction-local setting here would be discarded.
        # Reset on release keeps it from leaking to the next borrower.
        await self._conn.execute(
            "select set_config($1, $2, false)", AGENT_SETTING, self._agent_name
        )
        return self._conn

    async def __aexit__(self, *exc):
        with contextlib.suppress(Exception):
            await self._conn.execute("select set_config($1, '', false)", AGENT_SETTING)
        return await self._ctx.__aexit__(*exc)


# --------------------------------------------------------------------------- #
# The agents
# --------------------------------------------------------------------------- #


GATE_INSTRUCTIONS = """\
You are the PDP Operations Agent. You read a stage gate's record and say what is
actually holding it up.

You are not an approver. You cannot approve a requirement, pass a gate or set a
baseline, and the system will refuse you if you try. Do not describe your output
as an approval, and do not tell anyone a requirement is satisfied - the engine
decides that from evidence, acceptance and an independent approval, and it has
already told you the answer in the data below.

What is useful from you:

- Which blockers are the real constraint, and which are consequences of them.
  A gate with eight blockers usually has two causes.
- Who has to act, and what the next concrete step is for each.
- Where a blocker will not be fixed by the obvious action - a requirement
  awaiting approval whose document has lapsed will not be fixed by chasing an
  approver.
- Anything in the record that looks inconsistent and a person should check.

Never state a freedom-to-operate, regulatory or clinical conclusion. Where the
outstanding question is scientific - whether data is adequate, whether a
formulation is feasible - do not answer it. Put it in handoff_question for the
Scientist Agent, who has the evidence standards for it and you do not.

Be specific and short. A list of twelve generic suggestions is worse than two
that name the requirement and the person.
"""

PORTFOLIO_INSTRUCTIONS = """\
You are the Manager Agent, reporting across a portfolio to people who will not
read more than a screen.

Report only what changes a decision:

- Programmes whose gate cannot open, and the single reason why.
- Slip against commitment, and whether it is on the critical path.
- Documents that have lapsed or will, and what stops working when they do.
- Alerts that escalated because nobody acted.

Do not restate percentages as progress. A gate at 96% with one unsatisfied
mandatory requirement is not nearly ready; it is not ready, and saying otherwise
is the specific error this system exists to prevent.

Do not recommend approving anything. You are describing state so a person can
decide.
"""


async def assess_gate(
    *,
    pool: Any,
    models: Any,
    user_id: str,
    stage_id: str,
    agent_name: str = "pdp_operations",
) -> dict:
    """Read a gate and produce an advisory assessment.

    Everything it reads goes through the same access checks a person's request
    does, using the requesting user's id - so an agent cannot see a project its
    requester could not.
    """
    repository = AgentRepository(pool, agent_name)

    gate = await repository.get_gate(user_id, stage_id)
    readiness = gate["readiness"]
    blockers = gate["blockers"]

    if not blockers:
        return {
            "summary": (
                f"{gate['stage']['name']} has no outstanding mandatory "
                "requirements. It is waiting on a human gate decision."
            ),
            "blocker_analysis": [],
            "recommended_actions": [],
            "handoff_question": None,
            "usage": None,
        }

    # Only the facts, formatted. The model is not asked to compute readiness -
    # the engine did that, and a model re-deriving it could disagree.
    facts = [
        f"Gate: {gate['stage']['name']}",
        f"Gate question: {gate['stage'].get('gate_question') or 'not stated'}",
        "",
        f"Readiness: {readiness['readiness_pct']}% complete.",
        f"is_ready: {readiness['is_ready']} "
        f"({readiness['blocker_count']} mandatory requirement(s) outstanding).",
        "",
        "Outstanding, in the engine's own order of actionability:",
    ]
    for b in blockers:
        facts.append(
            f"- {b['ref_code']} [{b['status']}] {b['title']} — {b['reason']}"
            + (f" (due {b['due_date']})" if b.get("due_date") else "")
        )

    facts.append("")
    facts.append("Evidence attached to each outstanding requirement:")
    by_id = {str(r["id"]): r for r in gate["requirements"]}
    for b in blockers:
        req = by_id.get(str(b["requirement_id"]))
        if not req:
            continue
        if not req["evidence"]:
            facts.append(f"- {b['ref_code']}: none")
            continue
        for e in req["evidence"]:
            stale = e.get("document_is_usable") is False
            facts.append(
                f"- {b['ref_code']}: {e['evidence_type']}"
                + (f" {e.get('document_number') or ''}" if e.get("document_number") else "")
                + (" [NO LONGER USABLE]" if stale else "")
            )

    result = await models.complete_structured(
        role=ModelRole.SUPERVISOR,
        schema=GateAssessment,
        instructions=GATE_INSTRUCTIONS,
        user_input="\n".join(facts),
        node="pdp_operations_agent",
    )

    assessment = result.output
    return {
        "summary": assessment.summary,
        "blocker_analysis": [b.model_dump() for b in assessment.blocker_analysis],
        "recommended_actions": [a.model_dump() for a in assessment.recommended_actions],
        "handoff_question": assessment.handoff_question,
        "usage": result.usage,
    }


async def summarise_portfolio(
    *, pool: Any, models: Any, user_id: str, agent_name: str = "manager"
) -> dict:
    """Portfolio-level state for someone who will read one screen."""
    repository = AgentRepository(pool, agent_name)

    programmes = await repository.list_programmes(user_id)
    if not programmes:
        return {
            "headline": "No programmes are being tracked.",
            "items": [],
            "usage": None,
        }

    lines = []
    for p in programmes:
        lines.append(
            f"- {p['name']}: current gate {p.get('current_stage_name') or 'none'}, "
            f"{p.get('readiness_pct') or 0}% complete, "
            f"is_ready={p.get('is_ready')}, "
            f"{p.get('blocker_count') or 0} mandatory item(s) outstanding, "
            f"status {p.get('current_gate_status')}"
        )

    async with pool.acquire() as conn:
        alerts = await conn.fetch(
            """
            select e.severity, e.title, e.escalation_level, p.name as project_name
              from public.notification_events e
              join public.projects p on p.id = e.project_id
             where e.resolved_at is null
               and private.user_can_access_project($1, e.project_id)
          order by case e.severity when 'critical' then 0
                                   when 'warning' then 1 else 2 end,
                   e.raised_at
             limit 40
            """,
            user_id,
        )
    if alerts:
        lines.append("")
        lines.append("Open alerts:")
        for a in alerts:
            lines.append(
                f"- [{a['severity']}] {a['project_name']}: {a['title']}"
                + (" (escalated)" if a["escalation_level"] > 0 else "")
            )

    result = await models.complete_structured(
        role=ModelRole.SUPERVISOR,
        schema=PortfolioSummary,
        instructions=PORTFOLIO_INSTRUCTIONS,
        user_input="\n".join(lines),
        node="manager_agent",
    )

    return {
        "headline": result.output.headline,
        "items": [i.model_dump() for i in result.output.items],
        "usage": result.usage,
    }
