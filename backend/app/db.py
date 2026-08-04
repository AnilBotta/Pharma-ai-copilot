"""Database connection pool.

The backend connects with the service role, so RLS does not restrict it. Every
query is therefore written to filter by user_id explicitly - RLS is defence in
depth here, not the access-control mechanism. See app/auth.py.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.config import Settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Decode jsonb to Python objects instead of strings."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create the shared connection pool.

    `statement_cache_size=0` is required: Supabase's transaction-mode pooler
    (port 6543) multiplexes connections, so server-side prepared statements
    cannot be relied upon between queries.
    """
    global _pool
    if _pool is not None:
        return _pool

    _pool = await asyncpg.create_pool(
        dsn=str(settings.database_url),
        min_size=1,
        max_size=10,
        command_timeout=60,
        statement_cache_size=0,
        init=_init_connection,
    )
    logger.info("Database pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialised.")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[Any]:
    async with get_pool().acquire() as conn:
        yield conn


async def health_check() -> tuple[bool, str]:
    try:
        async with acquire() as conn:
            await conn.fetchval("select 1")
        return True, "Connected."
    except Exception as exc:
        return False, f"Database unreachable: {type(exc).__name__}."
