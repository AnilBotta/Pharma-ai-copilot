"""Response caching for external providers.

Defined as a Protocol so tests can run against an in-memory implementation
without a database, while production uses Postgres. Cached payloads are public
data from PubMed, Europe PMC and EPO; no user content is ever written here,
which is why the cache is shared across users rather than partitioned.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol, runtime_checkable


def cache_key(provider: str, operation: str, params: dict[str, Any]) -> str:
    """Deterministic key for a provider call.

    Parameters are sorted so that argument ordering cannot produce two keys for
    the same request. The digest is truncated to keep keys index-friendly;
    collisions are not a correctness concern because a wrong hit would only
    return another public record, and 128 bits makes it vanishingly unlikely.
    """
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    return f"{provider}:{operation}:{digest}"


@runtime_checkable
class ResponseCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def set(self, key: str, provider: str, value: dict[str, Any], ttl: int) -> None: ...


class NullCache:
    """Disables caching. Used in tests that assert on request counts."""

    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, provider: str, value: dict[str, Any], ttl: int) -> None:
        return None


class MemoryCache:
    """Process-local cache with TTL. Suitable for tests and single-process runs."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._entries[key]
            return None
        return value

    async def set(self, key: str, provider: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        self._entries[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._entries.clear()


class PostgresCache:
    """Durable cache backed by the provider_cache table.

    A cache failure is never fatal: if the database is briefly unavailable the
    call proceeds uncached rather than failing the research run.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "select response from public.provider_cache "
                    "where cache_key = $1 and expires_at > now()",
                    key,
                )
        except Exception:
            return None
        if row is None:
            return None
        value = row["response"]
        return json.loads(value) if isinstance(value, str) else value

    async def set(self, key: str, provider: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into public.provider_cache (cache_key, provider, response, expires_at)
                    values ($1, $2, $3::jsonb, now() + make_interval(secs => $4))
                    on conflict (cache_key) do update
                      set response = excluded.response,
                          expires_at = excluded.expires_at,
                          created_at = now()
                    """,
                    key,
                    provider,
                    json.dumps(value, default=str),
                    float(ttl),
                )
        except Exception:
            return None
