"""Supabase Storage access for uploaded documents.

WHY THE BROWSER UPLOADS DIRECTLY

Vercel caps a serverless request body at roughly 4.5 MB. `max_upload_size_mb`
defaults to 25, and a regulatory PDF above 4.5 MB is entirely ordinary, so a
multipart POST through the API function cannot carry the files this feature
exists for. The browser therefore uploads straight to Supabase Storage using a
short-lived signed URL that the backend mints only after checking ownership.

The bucket is private and carries no policy. A signed URL bears its own token
and does not consult RLS, so every path in and out is mediated by this module
running under the service-role key - and no DDL is ever issued against
`storage.objects`, which the deployment's postgres role does not own.

No Supabase SDK is used; the Storage REST API over httpx is enough and keeps the
deployment bundle unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

#: Bucket created by migration 0025. Private.
BUCKET = "documents"

#: How long a mint stays usable. Long enough for a 25 MB upload on a poor
#: connection, short enough that a leaked URL is not a standing grant.
SIGNED_UPLOAD_TTL_SECONDS = 900

#: Storage is a different service from the database and can be slow for large
#: objects, so this is generous compared with the provider timeouts.
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


class StorageError(RuntimeError):
    """A Storage operation failed.

    Carries the status code where there was one, because "upload failed" and
    "the bucket does not exist" call for very different responses and the
    difference is worth keeping as far as the caller.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DocumentStorage:
    """Signed-URL minting, download and removal for the documents bucket."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self._key = settings.supabase_service_role_key.get_secret_value()

    @property
    def _headers(self) -> dict[str, str]:
        # Storage wants both. The apikey header is what identifies the project;
        # Authorization is what grants the service role.
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key}

    async def create_signed_upload_url(self, path: str) -> dict[str, str]:
        """Mint a URL the browser can PUT a file to.

        Returns the absolute URL and the token separately. The caller hands both
        to the client, which needs the absolute form; the token is returned too
        so a client library that expects it can be used without re-parsing.
        """
        url = f"{self._base}/object/upload/sign/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                url,
                headers=self._headers,
                json={"expiresIn": SIGNED_UPLOAD_TTL_SECONDS},
            )

        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not create an upload URL for {path}."),
                status_code=response.status_code,
            )

        payload: dict[str, Any] = response.json()
        # The API returns a path-relative URL such as
        # "/object/upload/sign/documents/<path>?token=...". Relative is useless
        # to a browser on another origin, so it is resolved here rather than in
        # the client, where getting it wrong would be a runtime-only failure.
        relative = str(payload.get("url") or "")
        if not relative:
            raise StorageError("Storage returned no upload URL.")

        return {
            "upload_url": f"{self._base}{relative}"
            if relative.startswith("/")
            else relative,
            "token": str(payload.get("token") or ""),
            "path": path,
        }

    async def download(self, path: str) -> bytes:
        """Fetch an object's bytes for extraction.

        This is an outbound request from the function, so the platform's inbound
        body limit does not apply - which is the whole reason the upload goes
        around the API rather than through it.
        """
        url = f"{self._base}/object/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not download {path}."),
                status_code=response.status_code,
            )
        return response.content

    async def exists(self, path: str) -> int | None:
        """Object size in bytes, or None if it is not there.

        Used to confirm an upload actually landed. A client that reports success
        over a bucket that does not have the file is a state worth catching at
        the point of claim, rather than discovering it in the worker minutes
        later with nothing useful to say about why.

        A HEAD against the object itself, deliberately, rather than the
        `/object/info` endpoint. If that endpoint were unavailable it would
        answer 404 - identical to "no such object" - and every upload would be
        rejected at the confirmation step with a message blaming the user's
        browser. HEAD on the download path has no such ambiguity: this is the
        route the worker will use to fetch the bytes, so a 200 here means the
        thing that matters is true.
        """
        url = f"{self._base}/object/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.head(url, headers=self._headers)

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not check {path}."),
                status_code=response.status_code,
            )

        try:
            return int(response.headers.get("content-length", 0))
        except (TypeError, ValueError):
            # Present but unmeasurable. Report existence, since that is the
            # question actually being asked; the true size is not load-bearing.
            return 0

    async def remove(self, path: str) -> None:
        """Delete an object. A missing object is not an error.

        Called when a document row is deleted. The row is the record; a bucket
        object without one is litter, so failing the delete because the file was
        already gone would leave the user unable to remove the document.
        """
        url = f"{self._base}/object/{BUCKET}/{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.delete(url, headers=self._headers)

        if response.status_code == 404:
            return
        if response.status_code >= 400:
            raise StorageError(
                _explain(response, f"Could not delete {path}."),
                status_code=response.status_code,
            )


def _explain(response: httpx.Response, fallback: str) -> str:
    """Prefer Storage's own message over a bare status code.

    Its errors are specific - "Bucket not found", "The resource already exists" -
    and losing them turns a five-second fix into an investigation.
    """
    try:
        body = response.json()
    except ValueError:
        return f"{fallback} HTTP {response.status_code}."

    detail = body.get("message") or body.get("error") or body.get("msg")
    if detail:
        return f"{fallback} {detail} (HTTP {response.status_code})"
    return f"{fallback} HTTP {response.status_code}."


__all__ = ["BUCKET", "DocumentStorage", "StorageError"]
