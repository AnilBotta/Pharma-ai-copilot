"""HTTP API for uploaded documents.

The upload is a three-step exchange rather than a single POST, and the reason is
platform rather than taste: a serverless request body is capped at roughly
4.5 MB, while the documents this feature exists for routinely exceed that. So

    1. the client asks for a ticket      -> a row is created, a signed URL minted
    2. the client PUTs the file to Storage directly, bypassing the API entirely
    3. the client confirms               -> the object is verified and queued

Step 3 is not a formality. Without it a client that crashed mid-upload would
leave a row claiming a file that is not there, and the worker would discover it
later with nothing useful to say. Confirming asks Storage whether the object
actually exists and how big it really is.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.serialise import serialise
from app.auth import AuthenticatedUser, current_user
from app.config import Settings, get_settings
from app.documents.repository import DocumentRepository
from app.documents.schemas import DocumentResponse, RequestUploadRequest, UploadTicket
from app.documents.storage import DocumentStorage, StorageError
from app.repository import NotFound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_repository(request: Request) -> DocumentRepository:
    repository = getattr(request.app.state, "document_repository", None)
    if repository is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not available."
        )
    return repository


@router.post("/upload-url", response_model=UploadTicket, status_code=201)
async def request_upload(
    payload: RequestUploadRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    settings: Settings = Depends(get_settings),
):
    """Create the row and mint a signed URL to upload against."""
    limit = settings.max_upload_size_mb * 1024 * 1024
    if payload.size_bytes > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{payload.filename} is {payload.size_bytes / 1_048_576:.1f} MB. "
            f"The limit is {settings.max_upload_size_mb} MB.",
        )

    # Namespaced by user, and named by a fresh uuid rather than the supplied
    # filename: two documents may legitimately share a name, and a filename
    # from a browser is untrusted input that would otherwise become a path.
    storage_path = f"{user.id}/{uuid.uuid4()}"

    try:
        document = await repository.create(
            user.id,
            project_id=payload.project_id,
            filename=payload.filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            storage_path=storage_path,
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    try:
        ticket = await DocumentStorage(settings).create_signed_upload_url(storage_path)
    except StorageError as exc:
        # The row exists and the file never will. Fail it now, with the reason,
        # rather than leaving a pending document that nothing will ever move.
        await repository.fail(str(document["id"]), str(exc))
        logger.warning("Could not mint an upload URL: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Storage would not accept the upload: {exc}",
        ) from exc

    return UploadTicket(
        document_id=str(document["id"]),
        upload_url=ticket["upload_url"],
        token=ticket["token"],
        storage_path=storage_path,
        max_size_bytes=limit,
    )


@router.post("/{document_id}/complete", response_model=DocumentResponse)
async def complete_upload(
    document_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    settings: Settings = Depends(get_settings),
):
    """Confirm the object landed, then queue it for ingest."""
    try:
        document = await repository.get(user.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    try:
        size = await DocumentStorage(settings).exists(document["storage_path"])
    except StorageError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not verify the upload: {exc}"
        ) from exc

    if size is None:
        # The client said it finished and the bucket disagrees. Say so plainly:
        # the alternative is a document that sits pending forever while the
        # worker repeatedly fails to download something that was never sent.
        message = "The upload did not complete: no file was found in storage."
        await repository.fail(document_id, message)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    # SIZE_UNKNOWN means the object is present but unmeasured, so the size the
    # client declared stands. Writing the sentinel through violates the `> 0`
    # check constraint on documents.size_bytes and fails an upload that actually
    # succeeded - which is exactly what happened to every text document, because
    # Storage gzips them and a gzipped response has no content-length.
    updated = await repository.mark_uploaded(
        user.id, document_id, size or document["size_bytes"]
    )

    # Start ingest in seconds rather than at the next scheduled tick. Exactly
    # the pattern create_run uses, and best-effort for the same reason: the
    # scheduler picks it up within a minute regardless, so this must never fail
    # the request.
    from app.worker import trigger_tick

    try:
        await trigger_tick(settings)
    except Exception:
        logger.debug("Could not nudge the worker; the next tick will collect it")

    return _to_response(updated)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    project_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(current_user),
    repository: DocumentRepository = Depends(get_document_repository),
):
    rows = await repository.list_for_user(user.id, project_id=project_id)
    return [_to_response(row) for row in rows]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: DocumentRepository = Depends(get_document_repository),
    settings: Settings = Depends(get_settings),
):
    """Delete a document and its chunks, and remove the stored object."""
    try:
        storage_path = await repository.delete(user.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    if storage_path:
        try:
            await DocumentStorage(settings).remove(storage_path)
        except StorageError as exc:
            # The row is gone, which is what the user asked for. A leftover
            # object is litter, not a failure to report back as one.
            logger.warning("Orphaned storage object %s: %s", storage_path, exc)

    return None


def _to_response(row: dict) -> DocumentResponse:
    data = serialise(row)
    return DocumentResponse(
        id=data["id"],
        project_id=data.get("project_id"),
        filename=data["filename"],
        mime_type=data["mime_type"],
        size_bytes=data["size_bytes"],
        status=data["status"],
        error=data.get("error"),
        page_count=data.get("page_count"),
        extracted_chars=data.get("extracted_chars"),
        chunk_count=int(data.get("chunk_count") or 0),
        pending_chunk_count=int(data.get("pending_chunk_count") or 0),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


__all__ = ["router"]
