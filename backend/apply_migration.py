"""Apply one migration file to the configured database.

Reads DATABASE_URL from backend/.env and prints nothing but the filename and the
outcome, so its output is safe to paste when asking for help.

    python apply_migration.py ../supabase/migrations/0016_....sql
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys

import asyncpg


def dsn() -> str:
    env_path = pathlib.Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        raise SystemExit(f"No .env at {env_path}")
    match = re.search(
        r"^DATABASE_URL=(.+)$", env_path.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match or not match.group(1).strip():
        raise SystemExit(f"DATABASE_URL is not set in {env_path}")
    return match.group(1).strip()


async def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_migration.py <path-to-sql>")

    path = pathlib.Path(sys.argv[1]).resolve()
    if not path.exists():
        raise SystemExit(f"No such file: {path}")

    sql = path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    try:
        # One transaction: a migration that fails halfway leaves the schema in a
        # state no later migration was written against.
        async with conn.transaction():
            await conn.execute(sql)
    except Exception as exc:
        print(f"FAILED  {path.name}")
        print(f"        {type(exc).__name__}: {exc}")
        return 1
    finally:
        await conn.close()

    print(f"APPLIED {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
