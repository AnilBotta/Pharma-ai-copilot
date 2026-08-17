"""Accountable acts, prepared by an agent and confirmed by a person.

WHY THE PREMISE IS THE INTERESTING PART

A proposal is a conclusion about a moment. "Approve G1-QA-001" is only a sound
recommendation while the evidence it rested on is still the evidence attached,
and "pass Gate 1" only while the blocker list is still empty.

Between the agent writing that and somebody clicking, minutes or hours pass, and
in that time a colleague can attach a document, withdraw an acceptance, or
supersede the specification the whole thing depended on. The proposal still
LOOKS right - same words, same requirement - and confirming it would apply a
judgement to a state nobody judged.

So each proposal records what it was reasoned from, and confirmation recomputes
that and refuses if it has moved. Not a warning: a refusal. This is the module's
own rule, that nothing is reported as better than it is, applied to the agent
that reports on it.

EXECUTION IS NOT AGENT-MARKED, AND THAT IS THE POINT

`confirm` runs through the plain PdpRepository. No `_MarkedPool`, no
`app.acting_agent`, so migration 0022's triggers see an ordinary human action -
which is what it is. The person clicking is the actor, the approval is recorded
against them, and the segregation-of-duties triggers apply to them exactly as
if they had used the form.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.pdp.repository import Conflict, NotFound

logger = logging.getLogger(__name__)


class PremiseMoved(Exception):
    """The state the proposal was reasoned from is no longer the state."""


@dataclass
class Action:
    """One accountable act the agent may prepare."""

    name: str
    #: Shown on the confirmation card as the thing about to happen.
    summary: str
    required: tuple[str, ...]
    #: Which record the card must re-read to show current state.
    subject: str  # "requirement" | "gate" | "project" | "document"
    capture: Callable[..., Awaitable[dict]]
    execute: Callable[..., Awaitable[Any]]


# --------------------------------------------------------------------------- #
# Premise capture
#
# Deliberately coarse. The premise is not a hash of the whole record - a
# changed description or a new comment should not invalidate an approval. It is
# the specific facts the decision rests on, and nothing else.
# --------------------------------------------------------------------------- #


async def _requirement_premise(repo: Any, user_id: str, params: dict) -> dict:
    req = await repo.get_requirement(user_id, params["requirement_id"])
    return {
        "kind": "requirement",
        "requirement_id": str(params["requirement_id"]),
        "ref_code": req.get("ref_code"),
        # The evidence set is the thing an approval is *about*. Sorted so that
        # attaching and detaching the same item is not seen as a change.
        "evidence_ids": sorted(str(e["id"]) for e in (req.get("evidence") or [])),
        "acceptance_confirmed_by": (
            str(req["acceptance_confirmed_by"])
            if req.get("acceptance_confirmed_by")
            else None
        ),
        "is_blocked": bool(req.get("is_blocked")),
    }


async def _gate_premise(repo: Any, user_id: str, params: dict) -> dict:
    gate = await repo.get_gate(user_id, params["stage_id"])
    readiness = gate["readiness"]
    return {
        "kind": "gate",
        "stage_id": str(params["stage_id"]),
        "gate_name": gate["stage"].get("name"),
        # is_ready, not the percentage: the percentage moving is informational,
        # the verdict moving changes whether the decision was even available.
        "is_ready": bool(readiness.get("is_ready")),
        "blocker_count": int(readiness.get("blocker_count") or 0),
        "blocking_ref_codes": sorted(b["ref_code"] for b in gate.get("blockers", [])),
    }


async def _project_premise(repo: Any, user_id: str, params: dict) -> dict:
    schedule = await repo.get_schedule(user_id, params["project_id"])
    baseline = schedule.get("current_baseline") or {}
    return {
        "kind": "project",
        "project_id": str(params["project_id"]),
        # Re-baselining twice off one recommendation would commit an
        # organisation to a date twice over.
        "baseline_id": str(baseline["id"]) if baseline.get("id") else None,
        "task_count": len(schedule.get("tasks") or []),
    }


async def _document_premise(repo: Any, user_id: str, params: dict) -> dict:
    doc = await repo.get_document(user_id, params["document_id"])
    current = doc.get("current_version") or {}
    return {
        "kind": "document",
        "document_id": str(params["document_id"]),
        "document_number": doc.get("document_number"),
        "current_version_id": str(current["id"]) if current.get("id") else None,
    }


# --------------------------------------------------------------------------- #
# Execution — plain repository, no agent mark
# --------------------------------------------------------------------------- #


async def _do_approve(repo: Any, user_id: str, params: dict) -> Any:
    return await repo.decide_requirement(
        user_id,
        params["requirement_id"],
        decision=params.get("decision", "approved"),
        comments=params.get("comments"),
    )


async def _do_gate(repo: Any, user_id: str, params: dict) -> Any:
    return await repo.decide_gate(
        user_id,
        params["stage_id"],
        decision=params["decision"],
        note=params.get("note"),
        conditions=params.get("conditions"),
    )


async def _do_attach(repo: Any, user_id: str, params: dict) -> Any:
    return await repo.attach_evidence(
        user_id,
        params["requirement_id"],
        evidence_type=params["evidence_type"],
        research_run_id=params.get("research_run_id"),
        document_version_id=params.get("document_version_id"),
        external_url=params.get("external_url"),
        note=params.get("note"),
        title=params.get("title"),
    )


async def _do_version(repo: Any, user_id: str, params: dict) -> Any:
    effective = params.get("effective_date")
    return await repo.add_document_version(
        user_id,
        params["document_id"],
        version_label=params["version_label"],
        storage_url=params["storage_url"],
        status=params.get("status", "draft"),
        effective_date=date.fromisoformat(effective) if effective else None,
        supersedes_version_id=params.get("supersedes_version_id"),
    )


async def _do_acceptance(repo: Any, user_id: str, params: dict) -> Any:
    return await repo.set_acceptance(
        user_id, params["requirement_id"], confirmed=params.get("confirmed", True)
    )


async def _do_rebaseline(repo: Any, user_id: str, params: dict) -> Any:
    return await repo.rebaseline(
        user_id, params["project_id"], name=params["name"], reason=params["reason"]
    )


ACTIONS: dict[str, Action] = {
    "approve_requirement": Action(
        "approve_requirement",
        "Approve a requirement",
        ("requirement_id",),
        "requirement",
        _requirement_premise,
        _do_approve,
    ),
    "decide_gate": Action(
        "decide_gate",
        "Record a gate decision",
        ("stage_id", "decision"),
        "gate",
        _gate_premise,
        _do_gate,
    ),
    "attach_evidence": Action(
        "attach_evidence",
        "Attach evidence to a requirement",
        ("requirement_id", "evidence_type"),
        "requirement",
        _requirement_premise,
        _do_attach,
    ),
    "add_document_version": Action(
        "add_document_version",
        "Add a version to a controlled document",
        ("document_id", "version_label", "storage_url"),
        "document",
        _document_premise,
        _do_version,
    ),
    "set_acceptance": Action(
        "set_acceptance",
        "Confirm the acceptance criteria are met",
        ("requirement_id",),
        "requirement",
        _requirement_premise,
        _do_acceptance,
    ),
    "rebaseline": Action(
        "rebaseline",
        "Re-baseline the schedule",
        ("project_id", "name", "reason"),
        "project",
        _project_premise,
        _do_rebaseline,
    ),
}


def validate(action_type: str, params: dict) -> Action:
    """Reject an unknown action or missing parameters at WRITE time.

    Discovering at confirmation that a proposal cannot be executed wastes the
    reviewer's attention on something that was never actionable, and teaches
    them that the cards are unreliable.
    """
    action = ACTIONS.get(action_type)
    if action is None:
        raise ValueError(
            f"{action_type!r} is not a proposable action. Available: "
            + ", ".join(sorted(ACTIONS))
        )
    missing = [key for key in action.required if not params.get(key)]
    if missing:
        raise ValueError(
            f"{action_type} needs {', '.join(missing)}."
        )
    return action


async def capture_premise(repo: Any, user_id: str, action: Action, params: dict) -> dict:
    return await action.capture(repo, user_id, params)


def describe_drift(recorded: dict, current: dict) -> list[str]:
    """What changed, in words a person can act on.

    Returning the differences rather than a boolean because "this is out of
    date" is not useful; "somebody attached evidence since this was written" is.
    """
    drift: list[str] = []
    if recorded.get("kind") != current.get("kind"):
        return ["The subject of this proposal has changed entirely."]

    kind = recorded.get("kind")
    if kind == "requirement":
        if recorded.get("evidence_ids") != current.get("evidence_ids"):
            before = len(recorded.get("evidence_ids") or [])
            after = len(current.get("evidence_ids") or [])
            drift.append(
                f"The attached evidence has changed since this was prepared "
                f"({before} item(s) then, {after} now)."
            )
        if recorded.get("acceptance_confirmed_by") != current.get(
            "acceptance_confirmed_by"
        ):
            drift.append("The acceptance confirmation has changed.")
        if recorded.get("is_blocked") != current.get("is_blocked"):
            drift.append(
                "This requirement is now blocked."
                if current.get("is_blocked")
                else "This requirement is no longer blocked."
            )
    elif kind == "gate":
        if recorded.get("is_ready") != current.get("is_ready"):
            drift.append(
                "The gate is no longer ready."
                if not current.get("is_ready")
                else "The gate has become ready since this was prepared."
            )
        if recorded.get("blocking_ref_codes") != current.get("blocking_ref_codes"):
            drift.append(
                f"The blocker list has changed "
                f"({recorded.get('blocker_count')} then, "
                f"{current.get('blocker_count')} now)."
            )
    elif kind == "project":
        if recorded.get("baseline_id") != current.get("baseline_id"):
            drift.append("The schedule has been re-baselined since this was prepared.")
    elif kind == "document":
        if recorded.get("current_version_id") != current.get("current_version_id"):
            drift.append("A new version of this document has been added since.")

    return drift


async def confirm(
    *,
    repo: Any,
    user_id: str,
    proposal: dict,
) -> Any:
    """Re-check the premise, then execute as the confirming person.

    `repo` MUST be a plain PdpRepository. Passing an agent-marked one would
    hand the accountable act back to the agent through the longest possible
    route, which is exactly what this whole flow exists to prevent.
    """
    action = ACTIONS.get(proposal["action_type"])
    if action is None:
        raise Conflict(
            f"{proposal['action_type']!r} is no longer a supported action."
        )

    params = proposal["params"]
    try:
        current = await action.capture(repo, user_id, params)
    except NotFound as exc:
        raise Conflict(
            "What this proposal refers to no longer exists."
        ) from exc

    drift = describe_drift(proposal["premise"], current)
    if drift:
        raise PremiseMoved(" ".join(drift))

    return await action.execute(repo, user_id, params)
