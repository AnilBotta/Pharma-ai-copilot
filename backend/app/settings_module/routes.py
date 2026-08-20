"""HTTP API for notification settings.

Open to any signed-in user, and every change is audited. Restricting this to
`executive` or `system_administrator` is the better long-term answer and is one
predicate away - but nobody currently holds either role, and shipping the
restriction first would lock the owner out of their own settings page. The audit
trail is the part that matters immediately: it answers who changed the routing,
regardless of who was permitted to.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.serialise import serialise
from app.auth import AuthenticatedUser, current_user
from app.repository import NotFound
from app.settings_module.repository import RecipientRepository
from app.settings_module.schemas import (
    AlertType,
    CreateRecipientRequest,
    RecipientResponse,
    UpdateRecipientRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def get_recipient_repository(request: Request) -> RecipientRepository:
    repository = getattr(request.app.state, "recipient_repository", None)
    if repository is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not available."
        )
    return repository


@router.get("/alert-types", response_model=list[AlertType])
async def list_alert_types(
    user: AuthenticatedUser = Depends(current_user),
    repository: RecipientRepository = Depends(get_recipient_repository),
):
    """The conditions a recipient can subscribe to, named as a person sees them."""
    return [AlertType(**row) for row in await repository.list_alert_types()]


@router.get("/notification-recipients", response_model=list[RecipientResponse])
async def list_recipients(
    user: AuthenticatedUser = Depends(current_user),
    repository: RecipientRepository = Depends(get_recipient_repository),
):
    return [_to_response(row) for row in await repository.list_all()]


@router.post(
    "/notification-recipients", response_model=RecipientResponse, status_code=201
)
async def add_recipient(
    payload: CreateRecipientRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: RecipientRepository = Depends(get_recipient_repository),
):
    row = await repository.create(
        user.id,
        email=payload.email,
        name=payload.name,
        conditions=payload.conditions,
        wants_immediate=payload.wants_immediate,
        wants_digest=payload.wants_digest,
    )
    return _to_response(row)


@router.patch(
    "/notification-recipients/{recipient_id}", response_model=RecipientResponse
)
async def update_recipient(
    recipient_id: str,
    payload: UpdateRecipientRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: RecipientRepository = Depends(get_recipient_repository),
):
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        row = await repository.update(user.id, recipient_id, changes)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _to_response(row)


@router.delete(
    "/notification-recipients/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_recipient(
    recipient_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: RecipientRepository = Depends(get_recipient_repository),
):
    """Deactivates rather than deletes; the delivery history keeps its subject."""
    try:
        await repository.delete(user.id, recipient_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return None


def _to_response(row: dict) -> RecipientResponse:
    data = serialise(row)
    return RecipientResponse(
        id=data["id"],
        email=data["email"],
        name=data.get("name"),
        is_active=data["is_active"],
        conditions=list(data.get("conditions") or []),
        wants_immediate=data["wants_immediate"],
        wants_digest=data["wants_digest"],
        sent_count=int(data.get("sent_count") or 0),
        last_sent_at=data.get("last_sent_at"),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


__all__ = ["router"]
