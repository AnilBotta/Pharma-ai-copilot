"""Apply a SQL file through a direct asyncpg connection.

The Supabase MCP tool rejects very large statements, and PowerShell's
Set-Content adds a UTF-8 BOM that Postgres will not parse. This reads the file
as UTF-8, strips any BOM, and executes it.

    python apply_sql.py <path-to-sql> [<path-to-sql> ...]
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, "backend")

import asyncpg


def dsn() -> str:
    """Read DATABASE_URL, resolving backend/.env relative to this file."""
    env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
    match = re.search(
        r"^DATABASE_URL=(.+)$", env_path.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match or not match.group(1).strip():
        raise SystemExit(f"DATABASE_URL is not set in {env_path}")
    return match.group(1).strip()


async def main() -> int:
    paths = [pathlib.Path(p) for p in sys.argv[1:]]
    if not paths:
        raise SystemExit("usage: apply_sql.py <file.sql> ...")

    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    try:
        for path in paths:
            sql = path.read_text(encoding="utf-8").lstrip("﻿")
            try:
                await conn.execute(sql)
                print(f"  applied  {path.name}  ({len(sql):,} chars)")
            except Exception as exc:
                print(f"  FAILED   {path.name}")
                print(f"           {type(exc).__name__}: {exc}")
                return 1
    finally:
        await conn.close()
    return 0


raise SystemExit(asyncio.run(main()))
