"""Supabase JWT verification.

Every data route depends on :func:`current_user`. The token's signature is
verified rather than merely decoded, so a client cannot mint its own claims.

Two signing schemes exist in the wild and both are supported:

* **Asymmetric (ES256/RS256)** - what current Supabase projects use. Public keys
  are published at ``/auth/v1/.well-known/jwks.json``, so no shared secret is
  needed at all. Preferred: there is no symmetric key to leak, and rotation is
  handled by refetching.
* **HS256 shared secret** - legacy projects. Used only when
  ``SUPABASE_JWT_SECRET`` is set and JWKS is unavailable.

The scheme is detected rather than configured, because getting it wrong
produces a blanket 401 for every user with no obvious cause.

The JWKS client here is deliberately hand-rolled on httpx rather than using
``jwt.PyJWKClient``. PyJWKClient fetches with blocking ``urllib``, which inside
an async request handler stalls the whole event loop for the duration of the
network call.

This is the actual access control. The backend connects with the service role,
which bypasses RLS, so ownership is enforced by passing the verified user id
into every repository call. RLS is a second line of defence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

#: Accepted algorithms, listed explicitly. Without this an attacker could
#: present an HS256 token and have the verifier use the EC public key as an
#: HMAC secret - the classic algorithm-confusion attack.
ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]
SYMMETRIC_ALGORITHMS = ["HS256"]

#: How long a fetched key set is trusted before refetching.
JWKS_TTL_SECONDS = 600.0
JWKS_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None
    role: str


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


class JWKSCache:
    """Async JWKS fetcher with TTL and rotation handling.

    A cache miss on `kid` forces one refetch even inside the TTL, so a key
    rotation is picked up without waiting for expiry or restarting the process.
    The lock prevents a thundering herd of concurrent requests all refetching.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._keys: dict[str, Any] = {}
        self._raw: list[dict] = []
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def raw_keys(self) -> list[dict]:
        return self._raw

    def _expired(self) -> bool:
        return time.monotonic() - self._fetched_at > JWKS_TTL_SECONDS

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(self._url)
            response.raise_for_status()
            payload = response.json()

        key_set = jwt.PyJWKSet.from_dict(payload)
        self._keys = {k.key_id: k.key for k in key_set.keys if k.key_id}
        self._raw = payload.get("keys", [])
        self._fetched_at = time.monotonic()
        logger.info("Fetched %d JWKS key(s) from %s", len(self._keys), self._url)

    async def get_key(self, kid: str | None) -> Any:
        """Public key for `kid`, refetching if unknown or stale."""
        async with self._lock:
            if self._expired() or not self._keys:
                await self._refresh()
            if kid and kid not in self._keys:
                # Unknown kid inside the TTL means rotation; refetch once.
                await self._refresh()

        if kid is None:
            if len(self._keys) == 1:
                return next(iter(self._keys.values()))
            raise jwt.InvalidTokenError("Token has no key id and the key set is ambiguous.")

        key = self._keys.get(kid)
        if key is None:
            raise jwt.InvalidTokenError(f"No public key matches key id {kid!r}.")
        return key

    async def probe(self) -> list[dict]:
        """Fetch for health reporting. Raises if unreachable."""
        async with self._lock:
            await self._refresh()
        return self._raw


_caches: dict[str, JWKSCache] = {}


def get_jwks_cache(supabase_url: str) -> JWKSCache:
    url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if url not in _caches:
        _caches[url] = JWKSCache(url)
    return _caches[url]


def reset_jwks_cache() -> None:
    """Drop cached key sets. Used by tests."""
    _caches.clear()


async def _decode(token: str, settings: Settings) -> dict:
    """Verify and decode, preferring asymmetric verification."""
    options = {"require": ["exp", "sub"], "verify_aud": True}

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise

    cache = get_jwks_cache(settings.supabase_url)
    try:
        key = await cache.get_key(header.get("kid"))
    except jwt.InvalidTokenError:
        # We reached the key set but it does not contain this token's key.
        raise
    except Exception as exc:
        # JWKS unreachable, or the project predates asymmetric keys.
        if not settings.supabase_jwt_secret:
            raise _unauthorised(
                "Cannot verify tokens: the JWKS endpoint is unreachable and no "
                "SUPABASE_JWT_SECRET is configured."
            ) from exc
        logger.warning("JWKS unavailable (%s); falling back to shared secret", exc)
        return jwt.decode(
            token,
            settings.supabase_jwt_secret.get_secret_value(),
            algorithms=SYMMETRIC_ALGORITHMS,
            audience="authenticated",
            options=options,
        )

    # Reached only when a public key was found. Restricting algorithms here is
    # what stops an HS256 token being verified against this public key.
    return jwt.decode(
        token,
        key,
        algorithms=ASYMMETRIC_ALGORITHMS,
        audience="authenticated",
        options=options,
    )


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """Verify the bearer token and return the caller."""
    if credentials is None or not credentials.credentials:
        raise _unauthorised("Authentication required.")

    try:
        claims = await _decode(credentials.credentials, settings)
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorised("Session expired. Sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise _unauthorised("Token audience is not 'authenticated'.") from exc
    except jwt.InvalidTokenError as exc:
        # Do not echo the underlying reason: it tells an attacker which part of
        # a forged token to fix next.
        logger.info("Rejected token: %s", exc)
        raise _unauthorised("Invalid authentication token.") from exc

    subject = claims.get("sub")
    if not subject:
        raise _unauthorised("Token has no subject claim.")

    return AuthenticatedUser(
        id=str(subject),
        email=claims.get("email"),
        role=str(claims.get("role", "authenticated")),
    )


async def describe_jwt_verification(settings: Settings) -> tuple[bool, str]:
    """Report which verification scheme is active. Used by /health.

    Worth surfacing: a project using asymmetric keys with only a shared secret
    configured rejects every real token, and the symptom is a blanket 401.
    """
    try:
        keys = await get_jwks_cache(settings.supabase_url).probe()
        if keys:
            algs = sorted({k.get("alg", "?") for k in keys})
            return True, f"Asymmetric JWKS ({', '.join(algs)}); no shared secret needed."
    except Exception as exc:
        logger.info("JWKS probe failed: %s", exc)

    if settings.supabase_jwt_secret:
        return True, "Legacy HS256 shared secret."
    return False, (
        "No verification method available: JWKS unreachable and "
        "SUPABASE_JWT_SECRET is not set."
    )


def get_repository(request: Request):
    """The shared Repository, created during application startup."""
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available.",
        )
    return repository
