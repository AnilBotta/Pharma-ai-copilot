"""HTTP API for the Manager Agent.

The interesting endpoint is the streaming one. A turn that reads six tables
before it can answer takes tens of seconds, and a chat that goes silent for that
long reads as broken. So the turn is streamed: tool activity as it happens, then
the prose as it is generated.

The stream also does the persisting. It would be simpler to run the turn, save
the result and then send it, but the user would wait for the whole thing - and
if the invocation died at second 200 the exchange would be lost entirely rather
than partially recorded.
"""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.serialise import serialise
from app.auth import AuthenticatedUser, current_user
from app.config import Settings, get_settings
from app.manager import agent as manager_agent
from app.manager import schemas as s
from app.manager.repository import ManagerRepository
from app.pdp.repository import Conflict, Forbidden, NotFound, PdpRepository
from app.pdp.routes import get_pdp_repository


def _translate_pdp(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    raise exc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manager", tags=["manager"])


def get_manager_repository(request: Request) -> ManagerRepository:
    repository = getattr(request.app.state, "manager_repository", None)
    if repository is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not available."
        )
    return repository


def _frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


# ------------------------------------------------------------ conversations ---


@router.post("/conversations", response_model=s.ConversationSummary, status_code=201)
async def create_conversation(
    payload: s.CreateConversationRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    row = await repository.create_conversation(user.id, payload.title)
    return serialise({**row, "message_count": 0})


@router.get("/conversations", response_model=list[s.ConversationSummary])
async def list_conversations(
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    return [serialise(c) for c in await repository.list_conversations(user.id)]


@router.get("/conversations/{conversation_id}", response_model=s.ConversationDetail)
async def get_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    try:
        conversation = await repository.get_conversation(user.id, conversation_id)
        messages = await repository.list_messages(user.id, conversation_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return {
        "id": str(conversation["id"]),
        "title": conversation["title"],
        "messages": [serialise(m) for m in messages],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
async def archive_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    try:
        await repository.archive_conversation(user.id, conversation_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# ------------------------------------------------------------------- a turn ---


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: s.SendMessageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    """Send a message and stream the agent's turn back as server-sent events.

    Frames: `tool_started`, `tool_finished`, `token`, `truncated`, `done`,
    `error`.
    """
    from app import db
    from app.llm.provider import ModelProvider, Usage
    from app.repository import Repository

    try:
        conversation = await repository.get_conversation(user.id, conversation_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    # Persisted before the model is called. If the invocation dies mid-turn the
    # question is still on the record, which is what makes the thread resumable
    # rather than mysteriously missing a message.
    await repository.add_message(conversation_id, role="user", content=payload.content)

    # First question names the thread. No second model call for a title.
    if conversation["title"] == "New conversation":
        await repository.set_title(user.id, conversation_id, payload.content.strip())

    transcript = await repository.transcript_for_model(conversation_id)
    pool = db.get_pool()
    core = Repository(pool)
    manager_repo = repository
    active_conversation = conversation_id

    async def usage_sink(usage: Usage, node: str | None, purpose: str | None) -> None:
        """Persist what this turn cost.

        Without this the chat is the one part of the system that spends money
        invisibly. `run_id` is null - a conversation is not a research run -
        which is why 0004 left that column nullable.
        """
        await core.record_usage(
            run_id=None,
            user_id=user.id,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_tokens=usage.cached_tokens,
            estimated_cost_usd=(
                float(usage.estimated_cost_usd)
                if usage.estimated_cost_usd is not None
                else None
            ),
            duration_ms=usage.duration_ms,
            node=node,
            purpose=purpose,
        )

    models = ModelProvider(settings, usage_sink=usage_sink)

    async def stream():
        answer: list[str] = []
        try:
            async for event in manager_agent.run_turn(
                user_id=user.id,
                conversation=transcript,
                pool=pool,
                settings=settings,
                models=models,
                manager=manager_repo,
                conversation_id=active_conversation,
            ):
                if isinstance(event, manager_agent.TextDelta):
                    answer.append(event.text)
                    yield _frame("token", {"text": event.text})

                elif isinstance(event, manager_agent.ToolStarted):
                    yield _frame(
                        "tool_started",
                        {"name": event.name, "arguments": event.arguments},
                    )

                elif isinstance(event, manager_agent.ToolFinished):
                    await repository.add_message(
                        conversation_id,
                        role="tool",
                        tool_name=event.name,
                        tool_result=event.result,
                    )
                    yield _frame("tool_finished", {"name": event.name, "ok": event.ok})

                elif isinstance(event, manager_agent.LoopFinished):
                    text = event.text or "".join(answer)
                    await repository.add_message(
                        conversation_id,
                        role="assistant",
                        content=text,
                        input_tokens=event.usage.input_tokens,
                        output_tokens=event.usage.output_tokens,
                        estimated_cost_usd=event.usage.estimated_cost_usd,
                    )
                    yield _frame(
                        "done",
                        {
                            "tokens": event.usage.total_tokens,
                            "cost_usd": str(event.usage.estimated_cost_usd or 0),
                        },
                    )
                    return

                elif isinstance(event, manager_agent.LoopTruncated):
                    # Saved as truncated rather than as an answer. A partial
                    # response presented as complete is the failure this whole
                    # system is organised against.
                    await repository.add_message(
                        conversation_id,
                        role="assistant",
                        content="".join(answer),
                        truncated=True,
                        truncated_reason=event.detail,
                    )
                    yield _frame(
                        "truncated", {"reason": event.reason, "detail": event.detail}
                    )
                    return

        except Exception as exc:
            logger.exception("Manager turn failed for conversation %s", conversation_id)
            with contextlib.suppress(Exception):
                await repository.add_message(
                    conversation_id,
                    role="assistant",
                    content="".join(answer),
                    truncated=True,
                    truncated_reason=f"The turn failed: {exc}",
                )
            yield _frame(
                "error",
                {"message": "The Manager Agent could not complete this turn."},
            )
        finally:
            with contextlib.suppress(Exception):
                await models.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------- proposals ---


@router.get("/proposals", response_model=list[s.ProposalOut])
async def list_proposals(
    status_filter: str = "pending",
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    """Acts the agent has prepared and is waiting on.

    Anything past its window is expired first, so a stale proposal is never
    offered for confirmation and then refused - the reviewer sees its state
    before they invest attention in it.
    """
    await repository.expire_stale_proposals(user.id)
    return [
        serialise(p) for p in await repository.list_proposals(user.id, status=status_filter)
    ]


@router.post("/proposals/{proposal_id}/confirm", response_model=s.ProposalOutcome)
async def confirm_proposal(
    proposal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
    pdp: PdpRepository = Depends(get_pdp_repository),
):
    """Take the act the agent prepared, as yourself.

    `pdp` is the PLAIN repository - no agent mark - because at this moment the
    caller is the actor. Migration 0022's triggers see an ordinary human
    action, and every segregation-of-duties rule applies to them exactly as if
    they had used the form: an owner still cannot approve their own
    requirement, and a gate with blockers is still refused.

    The premise is re-checked first. A proposal whose basis has moved is not
    the proposal that was reviewed, so it is refused rather than applied.
    """
    from app.manager import proposals as P

    await repository.expire_stale_proposals(user.id)

    try:
        proposal = await repository.get_proposal(user.id, proposal_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    if proposal["status"] != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This proposal was already {proposal['status']}.",
        )

    try:
        result = await P.confirm(repo=pdp, user_id=user.id, proposal=proposal)
    except P.PremiseMoved as exc:
        # Not recorded as a failure of the proposal: nothing was attempted.
        # It stays pending so the card can show what changed.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Forbidden as exc:
        # NOT a failure of the proposal. "You may not do this" is a fact about
        # the person who clicked, and the commonest case is the honest one -
        # you confirmed the acceptance criteria yourself, so you cannot also
        # approve. A colleague with gate authority still can.
        #
        # This was marked `failed` in the first version, which quietly threw
        # away the proposal because the wrong person opened it. Found by
        # reading production after the merge: one proposal sitting at `failed`
        # for exactly that reason.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{exc} This proposal is still open for someone who can.",
        ) from exc
    except (Conflict, NotFound) as exc:
        # These are about the act itself - a gate with blockers, a requirement
        # that no longer exists - so the proposal really is spent.
        await repository.settle_proposal(
            proposal_id, status="failed", error=str(exc)[:1000]
        )
        raise _translate_pdp(exc) from exc
    except Exception as exc:
        logger.exception("Confirming proposal %s failed", proposal_id)
        await repository.settle_proposal(
            proposal_id, status="failed", error=str(exc)[:1000]
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "The act could not be completed. Nothing was changed.",
        ) from exc

    await repository.settle_proposal(
        proposal_id,
        status="confirmed",
        confirmed_by=user.id,
        result=serialise(result) if isinstance(result, dict) else None,
    )
    return {"status": "confirmed", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject", response_model=s.ProposalOutcome)
async def reject_proposal(
    proposal_id: str,
    payload: s.RejectProposalRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: ManagerRepository = Depends(get_manager_repository),
):
    try:
        proposal = await repository.get_proposal(user.id, proposal_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    if proposal["status"] != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This proposal was already {proposal['status']}.",
        )

    await repository.settle_proposal(
        proposal_id, status="rejected", rejected_reason=payload.reason
    )
    return {"status": "rejected", "proposal_id": proposal_id}
