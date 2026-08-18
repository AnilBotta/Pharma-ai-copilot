"""Request and response models for the documents API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.documents.extract import SUPPORTED_MIME_TYPES


class RequestUploadRequest(BaseModel):
    """Ask for somewhere to put a file.

    `size_bytes` is the browser's claim about a file it has not yet sent. It is
    checked here so an oversized upload is refused before it starts rather than
    after 25 MB has crossed the network, and it is checked again against Storage
    afterwards, because this number is not evidence of anything.
    """

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str
    size_bytes: int = Field(gt=0)
    project_id: str | None = None

    @field_validator("mime_type")
    @classmethod
    def _supported(cls, v: str) -> str:
        # Browsers send "text/markdown" for .md inconsistently, and the database
        # CHECK constraint in 0004 permits exactly three values. Normalising here
        # gives a clear message instead of a constraint violation.
        cleaned = v.split(";")[0].strip().lower()
        if cleaned not in SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"{v} is not a supported document type. "
                f"Supported: {', '.join(SUPPORTED_MIME_TYPES)}."
            )
        return cleaned

    @field_validator("filename")
    @classmethod
    def _clean_filename(cls, v: str) -> str:
        cleaned = v.strip().replace("\\", "/").split("/")[-1]
        if not cleaned:
            raise ValueError("A filename is required.")
        return cleaned


class UploadTicket(BaseModel):
    """Where to put the file, and the row that will describe it."""

    document_id: str
    upload_url: str
    token: str
    storage_path: str
    max_size_bytes: int


class DocumentResponse(BaseModel):
    id: str
    project_id: str | None
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    error: str | None

    page_count: int | None
    extracted_chars: int | None

    #: Chunk counts make progress legible while a large document is embedding,
    #: rather than leaving "embedding" on screen with no sense of how far along
    #: it is or whether it is moving at all.
    chunk_count: int
    pending_chunk_count: int

    created_at: str
    updated_at: str


__all__ = ["DocumentResponse", "RequestUploadRequest", "UploadTicket"]
