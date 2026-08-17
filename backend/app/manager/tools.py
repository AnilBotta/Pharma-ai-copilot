"""What the Manager Agent can see and do.

EVERY TOOL RUNS AS THE PERSON WHO ASKED

The repositories handed to a tool are built on `_MarkedPool` from
`app.pdp.agent`, so two things hold at once and neither depends on this file
being written carefully:

  * every read goes through the same access checks a human's HTTP request does,
    using the requesting user's id, so the agent cannot see a project its
    requester could not; and
  * every write is refused by migration 0022 if it is one of the four
    accountable acts, however the agent arrived at wanting to do it.

PROJECTIONS, NOT ROWS

Each tool returns a deliberately small shape. `get_gate` on a fifty-requirement
gate would otherwise return tens of thousands of tokens of timestamps and uuids
the model has no use for, on every single turn, and the loop may call several
tools before it answers. Cost here is not a rounding error - it is most of the
bill. Where a field is dropped it is because a person reading the answer would
not have wanted it quoted back at them either.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.manager import docs

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Everything a tool needs, assembled once per turn."""

    user_id: str
    #: Agent-marked. See app.pdp.agent.AgentRepository.
    pdp: Any
    core: Any
    pool: Any
    settings: Any
    models: Any
    #: time.monotonic() value after which slow tools must not start.
    deadline: float | None = None
    #: When the turn began, for tools that need to know how much of it is left.
    started: float = field(default_factory=time.monotonic)

    #: Set only inside a conversation; `propose` needs both to attach a
    #: proposal to the exchange that produced it.
    manager: Any = None
    conversation_id: str | None = None

    #: Research runs started by this turn. A run costs roughly $0.50 and nine
    #: minutes of compute, and the cap is here rather than only in the prompt
    #: because an instruction not to spend money is exactly the kind a
    #: sufficiently determined conversation talks its way past.
    runs_started: int = 0

    def seconds_spent(self) -> float:
        return time.monotonic() - self.started


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[Any]]

    def schema(self) -> dict:
        # Responses API function-tool shape: flat, not nested under "function".
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# --------------------------------------------------------------------------- #
# Projections
# --------------------------------------------------------------------------- #


def _programme(p: dict) -> dict:
    return {
        "project_id": str(p["id"]),
        "name": p["name"],
        "current_gate": p.get("current_stage_name"),
        "current_gate_id": str(p["current_stage_pk"]) if p.get("current_stage_pk") else None,
        "gate_status": p.get("current_gate_status"),
        "readiness_pct": p.get("readiness_pct"),
        # Both numbers, always together. Reporting the percentage without the
        # verdict is the specific error this system exists to prevent, and an
        # agent quoting one without the other would reintroduce it.
        "is_ready": p.get("is_ready"),
        "blocker_count": p.get("blocker_count"),
        "gate_count": p.get("stage_count"),
    }


def _requirement(r: dict) -> dict:
    return {
        "requirement_id": str(r["id"]),
        "ref_code": r["ref_code"],
        "title": r["title"],
        "status": r["status"],
        "is_mandatory": r["is_mandatory"],
        "is_satisfied": r.get("is_satisfied"),
        "evidence_count": r.get("evidence_count"),
        "owner": r.get("owner_name"),
        "due_date": str(r["due_date"]) if r.get("due_date") else None,
        "is_blocked": r.get("is_blocked"),
        "blocked_reason": r.get("blocked_reason"),
        "required_evidence_type": r.get("required_evidence_type"),
        "acceptance_confirmed_by": r.get("acceptance_confirmed_by_name"),
        "approved": bool(r.get("current_approval")),
    }


def _blocker(b: dict) -> dict:
    return {
        "ref_code": b["ref_code"],
        "title": b["title"],
        "status": b["status"],
        "reason": b["reason"],
        "requirement_id": str(b["requirement_id"]),
        "due_date": str(b["due_date"]) if b.get("due_date") else None,
    }


def _task(t: dict) -> dict:
    return {
        "task_id": str(t["id"]),
        "name": t.get("name"),
        "status": t.get("status"),
        "owner": t.get("owner_name"),
        "planned_start": str(t["planned_start"]) if t.get("planned_start") else None,
        "planned_finish": str(t["planned_finish"]) if t.get("planned_finish") else None,
        "actual_finish": str(t["actual_finish"]) if t.get("actual_finish") else None,
        # Computed, never stored - see migration 0020.
        "variance_days": t.get("variance_days"),
        "float_days": t.get("float_days"),
        "is_critical_path": t.get("is_critical_path"),
    }


def _document(d: dict) -> dict:
    version = d.get("current_version") or {}
    return {
        "document_id": str(d["id"]),
        "document_number": d.get("document_number"),
        "title": d.get("title"),
        "document_type": d.get("document_type"),
        "status": d.get("status"),
        "current_version": version.get("version_label"),
        "version_status": version.get("status"),
        # False means it no longer satisfies anything citing it.
        "is_usable": version.get("is_usable"),
        "effective_to": str(version["effective_to"]) if version.get("effective_to") else None,
    }


def _notification(n: dict) -> dict:
    return {
        "event_id": str(n["id"]),
        "severity": n.get("severity"),
        "title": n.get("title"),
        "rule": n.get("rule_name"),
        "raised_at": str(n["raised_at"]) if n.get("raised_at") else None,
        "escalation_level": n.get("escalation_level"),
        "acknowledged_by": n.get("acknowledged_by_name"),
        "resolved": n.get("resolved_at") is not None,
    }


def _run(r: dict) -> dict:
    return {
        "run_id": str(r["id"]),
        "question": r.get("original_question"),
        "status": r.get("status"),
        "project": r.get("project_name"),
        "evidence_count": r.get("evidence_count"),
        "created_at": str(r["created_at"]) if r.get("created_at") else None,
    }


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


async def _list_projects(ctx: ToolContext) -> Any:
    rows = await ctx.core.list_projects(ctx.user_id)
    return [
        {
            "project_id": str(p["id"]),
            "name": p["name"],
            "description": p.get("description"),
            "pdp_enabled": p.get("pdp_enabled"),
            "run_count": p.get("run_count"),
        }
        for p in rows
    ]


async def _list_programmes(ctx: ToolContext) -> Any:
    return [_programme(p) for p in await ctx.pdp.list_programmes(ctx.user_id)]


async def _get_programme(ctx: ToolContext, project_id: str) -> Any:
    detail = await ctx.pdp.get_programme(ctx.user_id, project_id)
    return {
        "project_id": project_id,
        "name": detail.get("name"),
        "gates": [
            {
                "stage_id": str(s["id"]),
                "position": s.get("position"),
                "name": s.get("name"),
                "gate_status": s.get("gate_status"),
                "readiness_pct": s.get("readiness_pct"),
                "is_ready": s.get("is_ready"),
                "blocker_count": s.get("blocker_count"),
                "gate_question": s.get("gate_question"),
            }
            for s in detail.get("stages", [])
        ],
        "capabilities": detail.get("capabilities"),
    }


async def _get_gate(ctx: ToolContext, stage_id: str) -> Any:
    gate = await ctx.pdp.get_gate(ctx.user_id, stage_id)
    stage, readiness = gate["stage"], gate["readiness"]
    return {
        "stage_id": stage_id,
        "name": stage.get("name"),
        "gate_question": stage.get("gate_question"),
        "exit_criteria": stage.get("exit_criteria"),
        "gate_status": stage.get("gate_status"),
        "readiness_pct": readiness.get("readiness_pct"),
        "is_ready": readiness.get("is_ready"),
        "blocker_count": readiness.get("blocker_count"),
        "blockers": [_blocker(b) for b in gate.get("blockers", [])],
        "requirements": [_requirement(r) for r in gate.get("requirements", [])],
        "capabilities": gate.get("capabilities"),
    }


async def _get_blockers(ctx: ToolContext, project_id: str) -> Any:
    """Every blocker across every gate in a programme, in one call.

    Added after watching a live turn: asked "which gates cannot open and why",
    the agent read the programme and then called `get_gate` eight separate
    times - once per gate - pulling back every requirement of each in order to
    use only the blockers. 38,687 tokens for a question this answers in a
    fraction of that.

    The per-gate tool is still right when the subject is one gate. This one is
    right when the subject is the programme, and having both is what stops the
    model choosing between accuracy and cost.
    """
    detail = await ctx.pdp.get_programme(ctx.user_id, project_id)
    out = []
    for stage in detail.get("stages", []):
        gate = await ctx.pdp.get_gate(ctx.user_id, str(stage["id"]))
        readiness = gate["readiness"]
        out.append(
            {
                "stage_id": str(stage["id"]),
                "gate": stage.get("name"),
                "gate_status": stage.get("gate_status"),
                "readiness_pct": readiness.get("readiness_pct"),
                "is_ready": readiness.get("is_ready"),
                "blockers": [_blocker(b) for b in gate.get("blockers", [])],
            }
        )
    return {"project_id": project_id, "gates": out}


async def _get_requirement(ctx: ToolContext, requirement_id: str) -> Any:
    r = await ctx.pdp.get_requirement(ctx.user_id, requirement_id)
    out = _requirement(r)
    out["description"] = r.get("description")
    out["acceptance_criteria"] = r.get("acceptance_criteria")
    out["depends_on"] = [
        {"ref_code": d["ref_code"], "is_satisfied": d["is_satisfied"]}
        for d in (r.get("depends_on") or [])
    ]
    out["evidence"] = [
        {
            "evidence_id": str(e["id"]),
            "type": e.get("evidence_type"),
            "title": e.get("title") or e.get("document_title"),
            "document_number": e.get("document_number"),
            "document_is_usable": e.get("document_is_usable"),
            "ai_assessment": e.get("ai_assessment"),
            "human_confirmed": e.get("human_confirmed_by") is not None,
        }
        for e in (r.get("evidence") or [])
    ]
    return out


async def _get_schedule(ctx: ToolContext, project_id: str) -> Any:
    s = await ctx.pdp.get_schedule(ctx.user_id, project_id)
    return {
        "project_id": project_id,
        "tasks": [_task(t) for t in s.get("tasks", [])],
        "milestones": [
            {
                "milestone_id": str(m["id"]),
                "name": m.get("name"),
                "target_date": str(m["target_date"]) if m.get("target_date") else None,
                "achieved_date": str(m["achieved_date"]) if m.get("achieved_date") else None,
            }
            for m in s.get("milestones", [])
        ],
        "baseline": s.get("current_baseline"),
    }


async def _list_documents(ctx: ToolContext, project_id: str) -> Any:
    return [_document(d) for d in await ctx.pdp.list_documents(ctx.user_id, project_id)]


async def _get_document(ctx: ToolContext, document_id: str) -> Any:
    d = await ctx.pdp.get_document(ctx.user_id, document_id)
    out = _document(d)
    out["versions"] = [
        {
            "version_id": str(v["id"]),
            "version_label": v.get("version_label"),
            "status": v.get("status"),
            "is_usable": v.get("is_usable"),
            "effective_from": str(v["effective_from"]) if v.get("effective_from") else None,
            "effective_to": str(v["effective_to"]) if v.get("effective_to") else None,
        }
        for v in (d.get("versions") or [])
    ]
    return out


async def _list_notifications(
    ctx: ToolContext, project_id: str, include_resolved: bool = False
) -> Any:
    rows = await ctx.pdp.list_notifications(
        ctx.user_id, project_id, include_resolved=include_resolved
    )
    return [_notification(n) for n in rows]


async def _project_audit(ctx: ToolContext, project_id: str, limit: int = 40) -> Any:
    rows = await ctx.pdp.project_audit(ctx.user_id, project_id, min(limit, 100))
    return [
        {
            "occurred_at": str(a["occurred_at"]),
            "actor": a.get("actor_name") or a.get("actor_agent") or "system",
            "is_agent": bool(a.get("actor_agent")),
            "role": a.get("actor_role"),
            "action": a.get("action"),
            "entity_type": a.get("entity_type"),
            "reason": a.get("reason"),
        }
        for a in rows
    ]


async def _list_agent_sessions(ctx: ToolContext, project_id: str, limit: int = 10) -> Any:
    rows = await ctx.pdp.list_agent_sessions(ctx.user_id, project_id, min(limit, 50))
    return [
        {
            "session_id": str(s["id"]),
            "agent": s.get("agent"),
            "objective": s.get("objective"),
            "status": s.get("status"),
            "requested_by": s.get("requested_by_name"),
            "started_at": str(s["started_at"]) if s.get("started_at") else None,
            "handoff_question": s.get("handoff_question"),
        }
        for s in rows
    ]


async def _list_runs(ctx: ToolContext, project_id: str | None = None, limit: int = 20) -> Any:
    rows = await ctx.core.list_runs(ctx.user_id, project_id=project_id, limit=min(limit, 50))
    return [_run(r) for r in rows]


async def _get_run_report(ctx: ToolContext, run_id: str) -> Any:
    run = await ctx.core.get_run(ctx.user_id, run_id)
    sections = await ctx.core.get_report(ctx.user_id, run_id)
    evidence = await ctx.core.get_evidence(ctx.user_id, run_id)
    return {
        "run_id": run_id,
        "question": run.get("original_question"),
        "status": run.get("status"),
        "sections": [
            {
                "heading": s.get("heading"),
                # Enough to summarise from; the full report is a page away in
                # the UI and quoting it whole would dominate the turn.
                "content": (s.get("content") or "")[:1500],
            }
            for s in sections
        ],
        "evidence": [
            {
                "title": e.get("title"),
                "source": e.get("source"),
                "identifier": e.get("external_id"),
                "url": e.get("url"),
            }
            for e in evidence
        ],
    }


# --------------------------------------------------------------------------- #
# Dispatch — commanding the other agents and starting work
#
# None of these is an accountable act. Each is something the requesting user
# could do from the UI, done on their behalf and recorded against them.
# --------------------------------------------------------------------------- #

#: A gate assessment is one model call of about a minute. Starting one late in
#: a turn risks the invocation being killed with the work half done and paid
#: for, so past this point it is refused rather than attempted.
ASSESS_LATEST_START_SECONDS = 120.0


async def _assess_gate(ctx: ToolContext, stage_id: str) -> Any:
    """Run the PDP Operations Agent against one gate, inline."""
    spent = ctx.seconds_spent()
    if spent > ASSESS_LATEST_START_SECONDS:
        return {
            "started": False,
            "reason": (
                f"This turn has already run for {spent:.0f}s. A gate assessment "
                "takes about a minute and would risk being cut off part-way. "
                "Tell the user to ask for the assessment on its own."
            ),
        }

    from app.pdp.agent import assess_gate as run_assessment

    session_id = await ctx.pdp.start_agent_session(
        ctx.user_id,
        agent="pdp_operations",
        project_id=(await ctx.pdp.capabilities_for_stage(ctx.user_id, stage_id))[0],
        objective=f"Assess gate {stage_id} (dispatched by the Manager Agent)",
    )
    try:
        result = await run_assessment(
            pool=ctx.pool, models=ctx.models, user_id=ctx.user_id, stage_id=stage_id
        )
    except Exception as exc:
        await ctx.pdp.finish_agent_session(session_id, error=str(exc)[:1000])
        raise

    await ctx.pdp.finish_agent_session(
        session_id,
        findings={"blocker_analysis": result["blocker_analysis"]},
        recommendations=result["recommended_actions"],
        handoff_question=result["handoff_question"],
        usage=result.get("usage"),
    )
    return {
        "started": True,
        "session_id": session_id,
        "summary": result["summary"],
        "blocker_analysis": result["blocker_analysis"],
        "recommended_actions": result["recommended_actions"],
        "handoff_question": result["handoff_question"],
    }


async def _start_research_run(
    ctx: ToolContext,
    project_id: str,
    question: str,
    molecule: str | None = None,
    indication: str | None = None,
    max_results: int = 12,
) -> Any:
    """Queue a research run. It executes in the background, not in this turn."""
    if ctx.runs_started >= 1:
        return {
            "queued": False,
            "reason": (
                "A research run has already been started in this turn. Each one "
                "costs real money and takes about nine minutes; starting more "
                "than one at a time needs the user to ask again."
            ),
        }

    run = await ctx.core.create_run(
        ctx.user_id,
        project_id,
        {
            "original_question": question,
            "molecule": molecule,
            "indication": indication,
            "dosage_form": None,
            "route_of_administration": None,
            "delivery_technology": None,
            "development_stage": None,
            "jurisdictions": None,
            "date_from": None,
            "date_to": None,
            "max_results": max(1, min(max_results, 25)),
            "additional_instructions": None,
        },
    )
    ctx.runs_started += 1

    # Best effort, exactly as POST /api/runs does it: a lost trigger costs a
    # minute, because pg_cron sweeps the queue.
    from app.worker import trigger_tick

    with contextlib.suppress(Exception):
        await trigger_tick(ctx.settings)

    return {
        "queued": True,
        "run_id": str(run["id"]),
        "note": (
            "Running in the background; it takes roughly nine minutes and "
            "completes across several slices. Tell the user it is under way "
            "and that they can watch it under Research Runs."
        ),
    }


async def _sweep_notifications(ctx: ToolContext) -> Any:
    """Recompute alert conditions across every programme the sweep covers."""
    from app.notifications import sweep_all_projects

    result = await sweep_all_projects(ctx.pool)
    return {
        "raised": result.get("raised", 0),
        "resolved": result.get("resolved", 0),
        "escalated": result.get("escalated", 0),
        "note": (
            "Detection is a query over current state, so this raises nothing "
            "new when nothing has changed."
        ),
    }


async def _list_people(ctx: ToolContext, project_id: str) -> Any:
    """Who holds a role on this programme, and their user ids.

    The one place this module writes its own SQL. Every write that names a
    person - assigning an owner, setting a reviewer - needs a uuid, and the
    agent is talking to someone who says "give it to Sarah". Without this it
    would have to guess an id, and guessing an id is how work gets assigned to
    the wrong person silently.
    """
    async with ctx.pool.acquire() as conn:
        # Access is checked the same way every other read is, before anything
        # about the project's people is returned.
        await ctx.pdp.capabilities(ctx.user_id, project_id)
        rows = await conn.fetch(
            """
            select ur.user_id,
                   coalesce(p.full_name, p.email) as name,
                   array_agg(distinct r.key order by r.key) as roles
              from public.user_roles ur
              join public.roles r on r.id = ur.role_id
         left join public.profiles p on p.id = ur.user_id
             where (ur.project_id is null or ur.project_id = $1)
               and (ur.expires_at is null or ur.expires_at > now())
          group by ur.user_id, coalesce(p.full_name, p.email)
          order by 2
            """,
            project_id,
        )
    return [
        {"user_id": str(r["user_id"]), "name": r["name"], "roles": list(r["roles"])}
        for r in rows
    ]


async def _search_docs(ctx: ToolContext, query: str) -> Any:
    hits = docs.search(query)
    if not hits:
        return {
            "results": [],
            "note": (
                "The documentation does not cover this. Say so rather than "
                "inferring how the system behaves."
            ),
        }
    return {"results": hits}


# --------------------------------------------------------------------------- #
# Tier 1 writes — executed immediately, under the agent mark
#
# WHERE THE LINE IS
#
# Not "risky versus safe". It is: does this change what the readiness engine
# concludes, or is it an accountable act? Everything here fails both tests. A
# task, a milestone, an owner, a due date, an acknowledgement - all reversible,
# none of them evidence, none of them a decision about whether a gate may open.
#
# Attaching evidence is NOT here despite the database permitting it, because
# evidence supersedes approvals and therefore moves what the engine concludes.
# That waits for the proposal flow.
#
# Every one of these lands in `audit_events` with `actor_agent` set, so "the
# agent did this" is answerable from the record rather than from memory.
# --------------------------------------------------------------------------- #


def _date(value: str | None) -> Any:
    """Parse an ISO date, refusing anything else rather than guessing."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{value!r} is not an ISO date. Use YYYY-MM-DD."
        ) from exc


async def _create_task(
    ctx: ToolContext,
    project_id: str,
    title: str,
    description: str | None = None,
    requirement_id: str | None = None,
    owner_user_id: str | None = None,
    forecast_start: str | None = None,
    forecast_end: str | None = None,
    priority: str = "medium",
) -> Any:
    row = await ctx.pdp.create_task(
        ctx.user_id,
        project_id,
        title=title,
        description=description,
        requirement_id=requirement_id,
        owner_user_id=owner_user_id,
        forecast_start=_date(forecast_start),
        forecast_end=_date(forecast_end),
        priority=priority,
    )
    return {"created": True, "task_id": str(row["id"]), "title": row.get("title")}


async def _update_task(
    ctx: ToolContext,
    task_id: str,
    forecast_start: str | None = None,
    forecast_end: str | None = None,
    actual_start: str | None = None,
    actual_end: str | None = None,
    owner_user_id: str | None = None,
    priority: str | None = None,
    reason: str | None = None,
) -> Any:
    row = await ctx.pdp.update_task(
        ctx.user_id,
        task_id,
        forecast_start=_date(forecast_start),
        forecast_end=_date(forecast_end),
        actual_start=_date(actual_start),
        actual_end=_date(actual_end),
        owner_user_id=owner_user_id,
        priority=priority,
        reason=reason,
    )
    return {
        "updated": True,
        "task_id": str(row["id"]),
        # Returned so the model can report the consequence rather than just
        # the edit: moving a forecast changes variance against the baseline,
        # and the baseline is what was promised.
        "variance_days": row.get("variance_days"),
    }


async def _add_task_dependency(
    ctx: ToolContext,
    successor_id: str,
    predecessor_id: str,
    dependency_type: str = "FS",
    lag_days: int = 0,
) -> Any:
    await ctx.pdp.add_task_dependency(
        ctx.user_id,
        successor_id,
        predecessor_id=predecessor_id,
        dependency_type=dependency_type,
        lag_days=lag_days,
    )
    return {"linked": True, "successor_id": successor_id, "predecessor_id": predecessor_id}


async def _create_milestone(
    ctx: ToolContext,
    project_id: str,
    name: str,
    forecast_date: str | None = None,
    description: str | None = None,
) -> Any:
    row = await ctx.pdp.create_milestone(
        ctx.user_id,
        project_id,
        name=name,
        forecast_date=_date(forecast_date),
        description=description,
        # An agent may not declare something contractual. That is a commitment
        # and belongs with the same authority as a baseline.
        is_contractual=False,
    )
    return {"created": True, "milestone_id": str(row["id"]), "name": row.get("name")}


async def _set_assignment(
    ctx: ToolContext,
    requirement_id: str,
    owner_user_id: str | None = None,
    reviewer_user_id: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
) -> Any:
    row = await ctx.pdp.set_assignment(
        ctx.user_id,
        requirement_id,
        owner_user_id=owner_user_id,
        reviewer_user_id=reviewer_user_id,
        due_date=_date(due_date),
        priority=priority,
    )
    return {
        "updated": True,
        "requirement_id": requirement_id,
        "ref_code": row.get("ref_code"),
        "owner": row.get("owner_name"),
        "due_date": str(row["due_date"]) if row.get("due_date") else None,
    }


async def _set_blocked(
    ctx: ToolContext, requirement_id: str, blocked: bool, reason: str | None = None
) -> Any:
    row = await ctx.pdp.set_blocked(
        ctx.user_id, requirement_id, blocked=blocked, reason=reason
    )
    return {
        "updated": True,
        "ref_code": row.get("ref_code"),
        "is_blocked": row.get("is_blocked"),
        "blocked_reason": row.get("blocked_reason"),
    }


async def _acknowledge_notification(ctx: ToolContext, event_id: str) -> Any:
    row = await ctx.pdp.acknowledge_notification(ctx.user_id, event_id)
    return {
        "acknowledged": True,
        "event_id": event_id,
        "title": row.get("title"),
        "note": (
            "Acknowledged, not resolved. Only the underlying condition ceasing "
            "to be true resolves an alert - say so rather than implying the "
            "problem is dealt with."
        ),
    }


async def _create_document(
    ctx: ToolContext,
    project_id: str,
    document_number: str,
    title: str,
    document_type: str,
    discipline: str | None = None,
    description: str | None = None,
) -> Any:
    row = await ctx.pdp.create_document(
        ctx.user_id,
        project_id,
        document_number=document_number,
        title=title,
        document_type=document_type,
        discipline=discipline,
        description=description,
    )
    return {
        "created": True,
        "document_id": str(row["id"]),
        "document_number": row.get("document_number"),
        "note": (
            "This registers the document. It has no version yet, so it cannot "
            "satisfy any requirement until an approved version is added by a "
            "person."
        ),
    }


# --------------------------------------------------------------------------- #
# Proposing an accountable act
#
# ONE TOOL, NOT SIX
#
# `propose` takes an action name and its parameters rather than there being an
# approve_requirement tool, a decide_gate tool and so on. Three reasons, and the
# third is the real one:
#
#   * one confirmation surface in the UI instead of six that drift apart;
#   * one place where the premise is captured, so no action can be added later
#     that forgets to record what it was reasoned from;
#   * and it keeps the shape of the thing honest. These are not six
#     capabilities the agent has. They are one capability - asking - applied to
#     six acts it cannot perform.
# --------------------------------------------------------------------------- #


async def _propose(
    ctx: ToolContext, action_type: str, params: dict, rationale: str
) -> Any:
    from app.manager import proposals as P

    if ctx.manager is None or ctx.conversation_id is None:
        raise ValueError("Proposals can only be made inside a conversation.")

    action = P.validate(action_type, params)

    # Captured through the agent's own repository, so the premise is exactly
    # what the agent could see when it decided to propose - not a privileged
    # view somebody would have to reconcile later.
    premise = await P.capture_premise(ctx.pdp, ctx.user_id, action, params)

    project_id = params.get("project_id")
    if not project_id:
        # Every subject resolves to a project; the card needs it to check access.
        if "requirement_id" in params:
            req = await ctx.pdp.get_requirement(ctx.user_id, params["requirement_id"])
            project_id = str(req["project_id"])
        elif "stage_id" in params:
            project_id, _caps = await ctx.pdp.capabilities_for_stage(
                ctx.user_id, params["stage_id"]
            )
        elif "document_id" in params:
            doc = await ctx.pdp.get_document(ctx.user_id, params["document_id"])
            project_id = str(doc["project_id"])

    row = await ctx.manager.create_proposal(
        conversation_id=ctx.conversation_id,
        requested_by=ctx.user_id,
        project_id=str(project_id) if project_id else None,
        action_type=action_type,
        params=params,
        rationale=rationale,
        premise=premise,
    )
    return {
        "proposed": True,
        "proposal_id": str(row["id"]),
        "action": action.summary,
        "expires_at": str(row["expires_at"]),
        "note": (
            "This is NOT done. It is waiting for the person you are talking to "
            "to confirm it, and they will see the current state of the record "
            "rather than your description of it. Tell them what you have "
            "prepared and why, and that it needs their confirmation."
        ),
    }


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_PROJECT = {
    "project_id": {"type": "string", "description": "Project (programme) UUID."}
}


def _params(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


READ_TOOLS: list[Tool] = [
    Tool(
        "list_projects",
        "Every project the user can see, whether or not it has a stage-gate programme.",
        _params({}, []),
        _list_projects,
    ),
    Tool(
        "list_programmes",
        "Stage-gate programmes with each one's current gate, readiness percentage, "
        "is_ready verdict and blocker count. Start here for portfolio questions.",
        _params({}, []),
        _list_programmes,
    ),
    Tool(
        "get_programme",
        "Every gate in one programme, with per-gate readiness and status.",
        _params(dict(_PROJECT), ["project_id"]),
        _get_programme,
    ),
    Tool(
        "get_gate",
        "One gate in full: readiness, the blocker list in the engine's order of "
        "actionability, and every requirement with its status and evidence count.",
        _params(
            {"stage_id": {"type": "string", "description": "Gate (stage) UUID."}},
            ["stage_id"],
        ),
        _get_gate,
    ),
    Tool(
        "get_blockers",
        "Every outstanding blocker across ALL gates of one programme, in a "
        "single call. Use this for 'which gates cannot open and why' rather "
        "than calling get_gate once per gate - it returns the same blockers "
        "without each gate's full requirement list.",
        _params(dict(_PROJECT), ["project_id"]),
        _get_blockers,
    ),
    Tool(
        "get_requirement",
        "One requirement in detail: acceptance criteria, prerequisites, attached "
        "evidence, whether a document backing it is still usable.",
        _params(
            {"requirement_id": {"type": "string", "description": "Requirement UUID."}},
            ["requirement_id"],
        ),
        _get_requirement,
    ),
    Tool(
        "get_schedule",
        "Tasks, milestones and the approved baseline. Variance and float are "
        "computed from baseline versus forecast, never stored.",
        _params(dict(_PROJECT), ["project_id"]),
        _get_schedule,
    ),
    Tool(
        "list_documents",
        "The controlled document register. is_usable=false means the version no "
        "longer satisfies any requirement citing it.",
        _params(dict(_PROJECT), ["project_id"]),
        _list_documents,
    ),
    Tool(
        "get_document",
        "One controlled document and its full version history.",
        _params(
            {"document_id": {"type": "string", "description": "Document UUID."}},
            ["document_id"],
        ),
        _get_document,
    ),
    Tool(
        "list_notifications",
        "Open alerts for a programme, with severity and escalation level.",
        _params(
            {
                **_PROJECT,
                "include_resolved": {
                    "type": "boolean",
                    "description": "Include alerts that have already been resolved.",
                },
            },
            ["project_id"],
        ),
        _list_notifications,
    ),
    Tool(
        "project_audit",
        "The append-only audit trail: who did what, when, and whether it was a "
        "person or an agent.",
        _params(
            {**_PROJECT, "limit": {"type": "integer", "description": "Max 100."}},
            ["project_id"],
        ),
        _project_audit,
    ),
    Tool(
        "list_agent_sessions",
        "Previous agent runs against a programme and what they concluded.",
        _params(
            {**_PROJECT, "limit": {"type": "integer", "description": "Max 50."}},
            ["project_id"],
        ),
        _list_agent_sessions,
    ),
    Tool(
        "list_runs",
        "Research runs, optionally filtered to one project.",
        _params(
            {
                "project_id": {"type": "string", "description": "Optional project UUID."},
                "limit": {"type": "integer", "description": "Max 50."},
            },
            [],
        ),
        _list_runs,
    ),
    Tool(
        "get_run_report",
        "A completed research run's report sections and cited evidence.",
        _params({"run_id": {"type": "string", "description": "Run UUID."}}, ["run_id"]),
        _get_run_report,
    ),
    Tool(
        "list_people",
        "Who holds a role on this programme, with their user ids and role keys. "
        "Use this before assigning anything to anyone - never invent a user id.",
        _params(dict(_PROJECT), ["project_id"]),
        _list_people,
    ),
    Tool(
        "search_docs",
        "Search this system's own documentation for how it works and why - roles, "
        "segregation of duties, what the readiness engine requires, what a gate "
        "status means, what is deliberately not built. Use this for any question "
        "about the system's rules rather than answering from memory.",
        _params(
            {"query": {"type": "string", "description": "What you want to know."}},
            ["query"],
        ),
        _search_docs,
    ),
]


#: Tools that start work rather than read it. Listed separately from
#: READ_TOOLS so that "what can this agent set in motion" is answerable by
#: looking at one list, rather than by reading thirty descriptions.
DISPATCH_TOOLS: list[Tool] = [
    Tool(
        "assess_gate",
        "Dispatch the PDP Operations Agent to analyse one gate: which blockers "
        "are the real constraint rather than consequences, who must act, and "
        "where the obvious action would not help. Takes about a minute and "
        "costs a few cents. Use it when the user wants analysis of a gate, not "
        "when they just want to know what is outstanding - get_gate answers "
        "that for free.",
        _params(
            {"stage_id": {"type": "string", "description": "Gate (stage) UUID."}},
            ["stage_id"],
        ),
        _assess_gate,
    ),
    Tool(
        "start_research_run",
        "Queue a literature and patent research run. It executes in the "
        "background over about nine minutes and costs real money - roughly "
        "fifty cents. Only start one when the user has actually asked for "
        "research; do not start one to answer a question you could answer by "
        "reading the record.",
        _params(
            {
                **_PROJECT,
                "question": {
                    "type": "string",
                    "description": "The research objective, in full.",
                },
                "molecule": {"type": "string", "description": "Optional."},
                "indication": {"type": "string", "description": "Optional."},
                "max_results": {
                    "type": "integer",
                    "description": "Sources per provider, 1-25. Default 12.",
                },
            },
            ["project_id", "question"],
        ),
        _start_research_run,
    ),
    Tool(
        "sweep_notifications",
        "Recompute alert conditions now rather than waiting for the scheduled "
        "sweep. Raises newly-true alerts and resolves ones whose condition has "
        "stopped being true. Safe to run at any time.",
        _params({}, []),
        _sweep_notifications,
    ),
]

#: Writes the agent performs immediately, under its own mark. Reversible, and
#: none of them changes what the readiness engine concludes. See the block
#: comment above the handlers for where the line sits and why.
WRITE_TOOLS: list[Tool] = [
    Tool(
        "create_task",
        "Create a task on a programme, optionally linked to a requirement and "
        "assigned to someone. Use list_people to get a user_id; never guess one.",
        _params(
            {
                **_PROJECT,
                "title": {"type": "string", "description": "What the task is."},
                "description": {"type": "string"},
                "requirement_id": {
                    "type": "string",
                    "description": "Optional requirement this task delivers.",
                },
                "owner_user_id": {"type": "string", "description": "From list_people."},
                "forecast_start": {"type": "string", "description": "YYYY-MM-DD."},
                "forecast_end": {"type": "string", "description": "YYYY-MM-DD."},
                "priority": {
                    "type": "string",
                    "description": "low, medium, high or critical.",
                },
            },
            ["project_id", "title"],
        ),
        _create_task,
    ),
    Tool(
        "update_task",
        "Move a task's forecast or actual dates, its owner or its priority. "
        "Baseline dates cannot be touched here - those are the commitment, and "
        "changing one is a re-baselining that needs a person.",
        _params(
            {
                "task_id": {"type": "string"},
                "forecast_start": {"type": "string", "description": "YYYY-MM-DD."},
                "forecast_end": {"type": "string", "description": "YYYY-MM-DD."},
                "actual_start": {"type": "string", "description": "YYYY-MM-DD."},
                "actual_end": {"type": "string", "description": "YYYY-MM-DD."},
                "owner_user_id": {"type": "string"},
                "priority": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "Why it moved. Recorded in the audit trail.",
                },
            },
            ["task_id"],
        ),
        _update_task,
    ),
    Tool(
        "add_task_dependency",
        "Make one task depend on another. Refused if it would create a cycle.",
        _params(
            {
                "successor_id": {"type": "string", "description": "The task that waits."},
                "predecessor_id": {
                    "type": "string",
                    "description": "The task that must happen first.",
                },
                "dependency_type": {
                    "type": "string",
                    "description": "FS, SS, FF or SF. Default FS.",
                },
                "lag_days": {"type": "integer"},
            },
            ["successor_id", "predecessor_id"],
        ),
        _add_task_dependency,
    ),
    Tool(
        "create_milestone",
        "Add a milestone with a forecast date. It is never marked contractual - "
        "that is a commitment and needs a person.",
        _params(
            {
                **_PROJECT,
                "name": {"type": "string"},
                "forecast_date": {"type": "string", "description": "YYYY-MM-DD."},
                "description": {"type": "string"},
            },
            ["project_id", "name"],
        ),
        _create_milestone,
    ),
    Tool(
        "set_assignment",
        "Set a requirement's owner, reviewer, due date or priority. Use "
        "list_people for user ids.",
        _params(
            {
                "requirement_id": {"type": "string"},
                "owner_user_id": {"type": "string"},
                "reviewer_user_id": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD."},
                "priority": {"type": "string"},
            },
            ["requirement_id"],
        ),
        _set_assignment,
    ),
    Tool(
        "set_blocked",
        "Mark a requirement blocked, or clear a block. Blocking requires a "
        "stated reason.",
        _params(
            {
                "requirement_id": {"type": "string"},
                "blocked": {"type": "boolean"},
                "reason": {"type": "string", "description": "Required when blocking."},
            },
            ["requirement_id", "blocked"],
        ),
        _set_blocked,
    ),
    Tool(
        "acknowledge_notification",
        "Take ownership of an alert so it stops escalating. This does NOT "
        "resolve it - only the underlying condition ceasing to be true does "
        "that. Say so when you report it.",
        _params({"event_id": {"type": "string"}}, ["event_id"]),
        _acknowledge_notification,
    ),
    Tool(
        "create_document",
        "Register a controlled document. It has no version, so it satisfies "
        "nothing until a person adds an approved version.",
        _params(
            {
                **_PROJECT,
                "document_number": {"type": "string", "description": "e.g. SOP-014."},
                "title": {"type": "string"},
                "document_type": {
                    "type": "string",
                    "description": "sop, protocol, report, specification, plan.",
                },
                "discipline": {"type": "string"},
                "description": {"type": "string"},
            },
            ["project_id", "document_number", "title", "document_type"],
        ),
        _create_document,
    ),
]

#: Asking a person to take an act the agent cannot. One tool; see the block
#: comment above `_propose` for why it is not six.
PROPOSE_TOOLS: list[Tool] = [
    Tool(
        "propose",
        "Prepare an act you cannot perform, for the person you are talking to "
        "to confirm. Use this when asked to approve a requirement, decide a "
        "gate, attach evidence, add a document version, confirm acceptance "
        "criteria, or re-baseline a schedule.\n\n"
        "action_type is one of: approve_requirement (requirement_id, "
        "optional comments), decide_gate (stage_id, decision, optional note "
        "and conditions), attach_evidence (requirement_id, evidence_type, and "
        "one of research_run_id / document_version_id / external_url / note), "
        "add_document_version (document_id, version_label, storage_url), "
        "set_acceptance (requirement_id, confirmed), rebaseline (project_id, "
        "name, reason).\n\n"
        "It does NOT perform the act. Say clearly that it is waiting for them.",
        _params(
            {
                "action_type": {
                    "type": "string",
                    "description": "One of the six named above.",
                },
                "params": {
                    "type": "object",
                    "description": "Parameters for that action.",
                    "additionalProperties": True,
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "Why you are proposing it. Shown to the reviewer "
                        "beneath the evidence, not as grounds for approving."
                    ),
                },
            },
            ["action_type", "params", "rationale"],
        ),
        _propose,
    ),
]

ALL_TOOLS: list[Tool] = [
    *READ_TOOLS,
    *DISPATCH_TOOLS,
    *WRITE_TOOLS,
    *PROPOSE_TOOLS,
]


def registry() -> dict[str, Tool]:
    return {t.name: t for t in ALL_TOOLS}


def schemas() -> list[dict]:
    return [t.schema() for t in ALL_TOOLS]


async def execute(ctx: ToolContext, name: str, arguments: dict) -> Any:
    """Dispatch one tool call.

    Raises on an unknown name or bad arguments rather than returning an error
    shape; the loop in `ModelProvider.complete_with_tools` catches it and hands
    the message back to the model, which is where a recoverable mistake belongs.
    """
    tool = registry().get(name)
    if tool is None:
        raise ValueError(f"There is no tool called {name!r}.")
    return await tool.handler(ctx, **arguments)
