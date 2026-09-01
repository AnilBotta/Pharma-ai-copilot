"""What is actually deployed, read-only, before anyone runs SAS for real.

WHY THIS IS A SCRIPT AND NOT A TEST

A test asserts what should be true. This reports what IS true in a particular
deployment, which is a different question and one that gets answered wrongly
from memory. Before a client is asked to run a validation package in their own
licensed SAS environment, somebody has to be able to say - with evidence, not
recollection - whether the receiving end can store what comes back.

IT WRITES NOTHING.

Every statement below is a read. It does not create the bucket, apply a
migration, or grant a role, because each of those is a change to a shared
environment and belongs to a person who chose to make it. Where something is
missing, the script prints the exact command that would fix it and stops
there.

    python scripts/sas_readiness_audit.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import asyncpg

from app.config import get_settings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The three migrations the manual validation path needs, and what each one is
#: for. Reported individually because a partial application is the dangerous
#: state: 0032 without 0034 gives you a system that accepts uploads and cannot
#: record a review of them.
MIGRATIONS = {
    "0032_sas_validation.sql": (
        "packages, runs, artifacts, audit",
        ("sas_validation_packages", "sas_validation_runs",
         "sas_validation_artifacts", "sas_validation_audit"),
    ),
    "0033_sas_validation_storage.sql": (
        "private bucket + archive columns",
        (),
    ),
    "0034_sas_validation_review.sql": (
        "AI reviews, human reviews, role lookup",
        ("sas_ai_reviews", "sas_human_reviews"),
    ),
}

BUCKET = "sas-validation"

#: Section 15: reported, never granted. A script that made whoever ran it a
#: reviewer would have no authorisation model at all.
GRANT_COMMAND = (
    "python -m app.pdp_admin grant-role \\\n"
    "  --email reviewer@example.com \\\n"
    "  --role system_administrator"
)
VERIFY_COMMAND = "python -m app.pdp_admin who --email reviewer@example.com"


def line(label: str, state: str, detail: str = "") -> None:
    print(f"  {label:<44} {state:<14} {detail}")


async def audit_migrations(conn) -> dict[str, bool]:
    print("\nMIGRATIONS")
    applied: dict[str, bool] = {}
    for name, (purpose, tables) in MIGRATIONS.items():
        if not tables:
            applied[name] = None  # judged by its own artefacts, below
            line(name, "see below", purpose)
            continue
        present = []
        for table in tables:
            exists = await conn.fetchval(
                "select to_regclass($1) is not null", "public." + table
            )
            present.append(bool(exists))
        state = (
            "APPLIED" if all(present)
            else "ABSENT" if not any(present)
            else "PARTIAL"
        )
        applied[name] = all(present)
        line(name, state, purpose)
        if state == "PARTIAL":
            missing = [t for t, ok in zip(tables, present, strict=True) if not ok]
            line("", "", f"missing: {', '.join(missing)}")

    # 0033 adds columns rather than tables, plus the bucket row.
    columns = await conn.fetchval(
        """
        select count(*) from information_schema.columns
         where table_schema = 'public'
           and table_name = 'sas_validation_packages'
           and column_name in ('archive_storage_path','archive_sha256','archive_bytes')
        """
    )
    applied["0033_sas_validation_storage.sql"] = columns == 3
    line(
        "  0033 archive columns",
        "APPLIED" if columns == 3 else "ABSENT",
        f"{columns}/3 present on sas_validation_packages",
    )

    # The role lookup 0034 adds. Its absence is what closed the review
    # endpoint in PR #64.
    has_function = await conn.fetchval(
        """
        select exists(
          select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'private' and p.proname = 'user_has_global_role'
        )
        """
    )
    line(
        "  private.user_has_global_role",
        "PRESENT" if has_function else "ABSENT",
        "without it, no reviewer can be identified",
    )
    return applied


async def audit_storage(conn) -> None:
    print("\nPRIVATE STORAGE")
    row = await conn.fetchrow(
        "select id, public from storage.buckets where id = $1", BUCKET
    )
    if row is None:
        line(f"bucket {BUCKET}", "ABSENT", "0033 creates it, or the dashboard can")
        return
    line(f"bucket {BUCKET}", "PRESENT", "")
    # `public` must be false. These objects are regulatory validation evidence
    # and customer-run SAS output; a permanently public URL for any of it would
    # be a disclosure that cannot be withdrawn.
    line(
        "  bucket is private",
        "YES" if row["public"] is False else "NO - FIX THIS",
        f"public = {row['public']}",
    )
    objects = await conn.fetchval(
        "select count(*) from storage.objects where bucket_id = $1", BUCKET
    )
    line("  objects stored", str(objects), "")


async def audit_audit_trail(conn) -> None:
    print("\nAUDIT TRAIL")
    has_function = await conn.fetchval(
        """
        select exists(
          select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'private' and p.proname = 'record_audit_event'
        )
        """
    )
    line(
        "private.record_audit_event",
        "PRESENT" if has_function else "ABSENT",
        "every package, upload and review writes through it",
    )
    if await conn.fetchval(
        "select to_regclass('public.sas_validation_audit') is not null"
    ):
        events = await conn.fetchval("select count(*) from public.sas_validation_audit")
        line("  sas_validation_audit rows", str(events), "")


async def audit_reviewers(conn) -> int:
    """Who could actually review. REPORTED, NEVER GRANTED."""
    print("\nAUTHORIZED REVIEWERS")
    if not await conn.fetchval("select to_regclass('public.user_roles') is not null"):
        line("user_roles", "ABSENT", "role model not deployed")
        return 0

    holders = await conn.fetch(
        """
        select p.email, r.key, ur.expires_at
          from public.user_roles ur
          join public.roles r on r.id = ur.role_id
          join public.profiles p on p.id = ur.user_id
         where r.key in ('system_administrator','executive')
           and ur.project_id is null
           and (ur.expires_at is null or ur.expires_at > now())
         order by r.key, p.email
        """
    )
    if not holders:
        line("holders of a reviewer role", "NONE", "no human can record a decision")
        print("\n  To grant one (NOT executed by this script):\n")
        for text in GRANT_COMMAND.splitlines():
            print(f"      {text}")
        print(f"\n  Then verify:\n\n      {VERIFY_COMMAND}\n")
        return 0

    for holder in holders:
        line(
            f"  {holder['key']}",
            "GRANTED",
            f"{holder['email']}"
            + (f" (expires {holder['expires_at']})" if holder["expires_at"] else ""),
        )
    return len(holders)


def audit_configuration() -> None:
    """Names only. No value of any secret is printed, ever."""
    print("\nBACKEND CONFIGURATION (names and states only, never values)")
    settings = get_settings()
    summary = settings.safe_summary()

    line("environment", str(summary.get("environment")), "")
    line(
        "openai integration",
        str(summary.get("integrations", {}).get("openai")),
        "the AI advisory reviewer needs this",
    )
    for name in ("supabase_url", "supabase_service_role_key", "database_url"):
        value = getattr(settings, name, None)
        line(f"{name}", "SET" if value else "MISSING", "")


async def main() -> int:
    settings = get_settings()
    print("=" * 72)
    print("SAS VALIDATION READINESS AUDIT - read-only, changes nothing")
    print("=" * 72)

    conn = await asyncpg.connect(str(settings.database_url), statement_cache_size=0)
    try:
        applied = await audit_migrations(conn)
        await audit_storage(conn)
        await audit_audit_trail(conn)
        reviewers = await audit_reviewers(conn)
    finally:
        await conn.close()

    audit_configuration()

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    missing = [name for name, ok in applied.items() if not ok]
    if missing:
        print("\n  NOT READY for a first live SAS run. Missing migrations:\n")
        for name in missing:
            print(f"      {name}")
        print("\n  Apply each, in order, with:\n")
        for name in missing:
            print(f"      python scripts/apply_sql.py ../supabase/migrations/{name}")
        print(
            "\n  This script will not apply them. Migrations change a shared\n"
            "  environment and that is a decision for a person who chose it."
        )
    elif reviewers == 0:
        print(
            "\n  Schema is ready; NO AUTHORIZED REVIEWER EXISTS. Uploaded evidence\n"
            "  could be stored and compared, but nobody could record a decision\n"
            "  about it. Grant a role with the command above first."
        )
    else:
        print(
            f"\n  Schema deployed, storage present, {reviewers} authorized "
            "reviewer(s).\n  The remaining input is a real SAS result, which "
            "only a licensed SAS\n  environment can produce."
        )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
