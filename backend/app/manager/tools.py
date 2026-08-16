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

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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


def registry() -> dict[str, Tool]:
    return {t.name: t for t in READ_TOOLS}


def schemas() -> list[dict]:
    return [t.schema() for t in READ_TOOLS]


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
