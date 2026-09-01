"""Supabase Storage access for SAS validation evidence.

DELIBERATELY THE SAME ARCHITECTURE AS `documents/storage.py`

Private bucket, no policy on `storage.objects`, every access mediated by the
backend under the service role, short-lived signed URLs for anything the
browser touches, httpx against the Storage REST API rather than a new SDK. A
second storage architecture in one product is a second set of mistakes to make.

WHERE IT DELIBERATELY DIFFERS, AND WHY

Documents are uploaded BROWSER-DIRECT via a signed upload URL, because Vercel
caps a serverless request body at roughly 4.5 MB and a regulatory PDF is often
larger.

SAS evidence goes THROUGH the API instead. Two reasons, and the first is the
one that matters:

  1. The backend must hash the bytes ITSELF. A browser-direct upload leaves the
     server trusting a client-supplied SHA-256, which for regulatory evidence
     is not a hash at all - it is a claim. Routing through the API means the
     recorded hash is one we computed over the bytes we stored.

  2. The files are small. `be_result.csv` is a few kilobytes and a SAS log is
     tens of kilobytes; both sit far below the platform limit that forced the
     documents design. `MAX_RESULT_BYTES` and `MAX_LOG_BYTES` keep them there.

NOTHING HERE EXECUTES ANYTHING

Uploads are untrusted bytes. They are stored, hashed and parsed by a strict
reader; they are never executed, never used to build a shell command, never
rendered as HTML. Downloads are served with an attachment disposition so a
browser cannot be persuaded to run one.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

#: Bucket created by migration 0033. Private, and must stay private.
BUCKET = "sas-validation"

#: Short. A download link for regulatory evidence should not be a standing
#: grant that outlives the click that produced it.
SIGNED_DOWNLOAD_TTL_SECONDS = 300

#: Generous for a structured result of a few kilobytes, and small enough that
#: nothing resembling a data dump or an executable gets through. Well under the
#: platform's ~4.5 MB request cap, so the API route is never the binding limit.
MAX_RESULT_BYTES = 2 * 1024 * 1024

#: A SAS log for one PROC MIXED run is tens of kilobytes. Ten megabytes allows
#: a very verbose session without allowing an archive.
MAX_LOG_BYTES = 10 * 1024 * 1024

_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)


class StorageError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class SASValidationStorage:
    """Upload, download and sign objects in the private validation bucket."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self._key = settings.supabase_service_role_key.get_secret_value()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key}

    async def upload(
        self, path: str, payload: bytes, *, content_type: str
    ) -> str:
        """Store bytes and return the SHA-256 WE computed over them.

        The hash is returned rather than accepted, so no caller can record a
        digest that was never checked against the stored object.

        `x-upsert: false`: evidence is never overwritten. A collision means the
        key was reused, which is a bug worth hearing about rather than silently
        replacing a stored artifact.
        """
        url = f"{self._base}/object/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                url,
                headers={
                    **self._headers,
                    "content-type": content_type,
                    "x-upsert": "false",
                },
                content=payload,
            )

        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not store {path}."),
                status_code=response.status_code,
            )
        return sha256_bytes(payload)

    async def download(self, path: str) -> bytes:
        url = f"{self._base}/object/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not download {path}."),
                status_code=response.status_code,
            )
        return response.content

    async def create_signed_download_url(self, path: str, *, filename: str) -> str:
        """A short-lived, server-authorized link to one object.

        The service-role key never leaves the server; what the browser receives
        is a token scoped to one object for five minutes. `download=<filename>`
        makes Storage serve it as an attachment, so an uploaded file cannot be
        coaxed into rendering as active content in the viewer's origin.
        """
        url = f"{self._base}/object/sign/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                url,
                headers=self._headers,
                json={"expiresIn": SIGNED_DOWNLOAD_TTL_SECONDS},
            )

        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not sign {path}."),
                status_code=response.status_code,
            )

        payload: dict[str, Any] = response.json()
        relative = str(payload.get("signedURL") or payload.get("signedUrl") or "")
        if not relative:
            raise StorageError("Storage returned no signed URL.")

        absolute = (
            f"{self._base}{relative}" if relative.startswith("/") else relative
        )
        separator = "&" if "?" in absolute else "?"
        return f"{absolute}{separator}download={filename}"

    async def exists(self, path: str) -> bool:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.head(
                f"{self._base}/object/{BUCKET}/{path}", headers=self._headers
            )
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not check {path}."),
                status_code=response.status_code,
            )
        return True


def _explain(response: httpx.Response, fallback: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"{fallback} HTTP {response.status_code}."
    detail = body.get("message") or body.get("error") or body.get("msg")
    return (
        f"{fallback} {detail} (HTTP {response.status_code})"
        if detail
        else f"{fallback} HTTP {response.status_code}."
    )


__all__ = [
    "BUCKET",
    "MAX_LOG_BYTES",
    "MAX_RESULT_BYTES",
    "SIGNED_DOWNLOAD_TTL_SECONDS",
    "SASValidationStorage",
    "StorageError",
    "sha256_bytes",
]
