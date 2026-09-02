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
#: NOTE ON `sas_validation_audit`, WHICH DOES NOT EXIST.
#:
#: An earlier version of this map expected a table by that name. 0032 never
#: creates one - the SAS module writes through `private.record_audit_event`
#: into the shared `public.audit_events` that predates it. The effect was that
#: this audit reported 0032 as PARTIAL forever, including immediately after a
#: clean and fully verified application of it.
#:
#: A readiness audit that cries wolf is worse than none: the next person to see
#: PARTIAL either re-applies a migration that was already applied, or learns to
#: ignore the one tool whose whole job is to be believed.
MIGRATIONS = {
    "0032_sas_validation.sql": (
        "integrations, packages, runs, artifacts",
        ("sas_integrations", "sas_validation_packages",
         "sas_validation_runs", "sas_validation_artifacts"),
    ),
    "0033_sas_validation_storage.sql": (
        "private bucket + archive columns",
        (),
    ),
    "0034_sas_validation_review.sql": (
        "AI reviews, human reviews, role lookup",
        ("sas_ai_reviews", "sas_human_reviews"),
    ),
    "0035_sas_operator_attestation.sql": (
        "operator attestation + evidence origin",
        ("sas_operator_attestations",),
    ),
    # 0036 adds no object, so it is checked by the privilege audit below rather
    # than by a table name.
    "0036_sas_attestation_revoke.sql": (
        "revoke default anon/authenticated grants",
        (),
    ),
}

#: Every SAS table that must be reachable only through the backend's
#: service_role connection. Checked as a group, because the failure this
#: catches is one table being forgotten while its siblings are correct - which
#: is exactly what happened to `sas_operator_attestations` in 0035.
SERVICE_ROLE_ONLY_TABLES = (
    "sas_integrations",
    "sas_validation_packages",
    "sas_validation_runs",
    "sas_validation_artifacts",
    "sas_ai_reviews",
    "sas_human_reviews",
    "sas_operator_attestations",
)

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

    # 0036 adds no object, so it is judged by the state it produces.
    applied["0036_sas_attestation_revoke.sql"] = await audit_privileges(conn)
    return applied


async def audit_privileges(conn) -> bool:
    """Is every SAS table reachable ONLY through the backend?

    Checked table by table rather than as a single yes/no, because the failure
    this exists to catch is one table being forgotten while its siblings are
    correct. RLS is not sufficient on its own: it filters rows, and TRUNCATE
    does not operate on rows, so a role holding TRUNCATE can empty a
    fully RLS-protected table.
    """
    print("\nBROWSER-FACING PRIVILEGES (anon / authenticated must hold none)")
    clean = True
    for table in SERVICE_ROLE_ONLY_TABLES:
        if not await conn.fetchval(
            "select to_regclass($1) is not null", "public." + table
        ):
            line(table, "n/a", "table not deployed")
            continue
        holders = await conn.fetch(
            """
            select grantee, string_agg(privilege_type, ',' order by privilege_type) p
              from information_schema.role_table_grants
             where table_schema = 'public' and table_name = $1
               and grantee in ('anon', 'authenticated')
             group by grantee order by grantee
            """,
            table,
        )
        if not holders:
            line(table, "LOCKED", "service_role only")
            continue
        clean = False
        for holder in holders:
            line(
                table,
                "EXPOSED",
                f"{holder['grantee']} holds {holder['p']}",
            )
            if "TRUNCATE" in holder["p"]:
                line(
                    "",
                    "",
                    "TRUNCATE is NOT filtered by RLS - this table can be emptied",
                )
    return clean


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
    # The SAS module has no audit table of its own. It writes into the shared
    # `public.audit_events` that predates it, which is the point: "who did what"
    # is one trail for the whole product, not one per feature.
    if await conn.fetchval("select to_regclass('public.audit_events') is not null"):
        events = await conn.fetchval(
            "select count(*) from public.audit_events where action like 'SAS_%'"
        )
        line("  audit_events rows with a SAS_ action", str(events), "")


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
        if "0036_sas_attestation_revoke.sql" in missing:
            print(
                "\n  NOTE: 0036 adds no table, so it shows as missing whenever any\n"
                "  SAS table still grants anon or authenticated. See the\n"
                "  BROWSER-FACING PRIVILEGES section above for which one."
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
