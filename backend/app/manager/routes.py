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
from app.pdp.repository import NotFound

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
    from app.llm.provider import ModelProvider

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
    models = ModelProvider(settings)

    async def stream():
        answer: list[str] = []
        try:
            async for event in manager_agent.run_turn(
                user_id=user.id,
                conversation=transcript,
                pool=pool,
                settings=settings,
                models=models,
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
