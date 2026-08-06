"""Readiness engine verification against the live database.

Everything is created inside a transaction and rolled back, so the database is
unchanged afterwards.
"""

import asyncio
import contextlib
import pathlib
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, "backend")
import asyncpg


@dataclass
class Outcome:
    rejected: bool = False
    detail: str = ""


@contextlib.asynccontextmanager
async def expect_failure(conn, *exc_types):
    """Run a statement expected to fail, inside a savepoint.

    Postgres aborts the whole transaction on any statement error, so without a
    savepoint the first expected failure would poison every later assertion.
    """
    outcome = Outcome()
    tx = conn.transaction()
    await tx.start()
    try:
        yield outcome
    except exc_types as exc:
        outcome.rejected = True
        outcome.detail = str(exc).split(":")[-1].strip()[:60]
        await tx.rollback()
    else:
        await tx.rollback()
    return

OWNER = "c0000000-0000-0000-0000-000000000001"
APPROVER = "c0000000-0000-0000-0000-000000000002"
PROJECT = "c1000000-0000-0000-0000-000000000001"
STAGE = "c2000000-0000-0000-0000-000000000001"
R = {n: f"c3000000-0000-0000-0000-00000000000{n}" for n in range(1, 6)}

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def dsn() -> str:
    """Read DATABASE_URL, resolving backend/.env relative to this file.

    Resolved from __file__ rather than the working directory so the test runs
    the same whether invoked from the repo root or from backend/.
    """
    env_path = pathlib.Path(__file__).resolve().parents[2] / ".env"
    env = env_path.read_text(encoding="utf-8")
    match = re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE)
    if not match or not match.group(1).strip():
        raise SystemExit(f"DATABASE_URL is not set in {env_path}")
    return match.group(1).strip()


async def status(conn, rid):
    return await conn.fetchval("select private.requirement_status($1)", rid)


async def satisfied(conn, rid):
    return await conn.fetchval("select private.requirement_is_satisfied($1)", rid)


async def readiness(conn):
    return await conn.fetchrow("select * from private.gate_readiness($1)", STAGE)


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    try:
        # ---------------------------------------------------------- setup ---
        for uid, email in ((OWNER, "rt-owner@test.local"), (APPROVER, "rt-approver@test.local")):
            await conn.execute("""
                insert into auth.users (id, instance_id, aud, role, email,
                    encrypted_password, email_confirmed_at, created_at, updated_at)
                values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                        'authenticated',$2,'x',now(),now(),now())
            """, uid, email)

        await conn.execute("""
            insert into public.projects (id, user_id, name, pdp_enabled)
            values ($1,$2,'Readiness Test', true)""", PROJECT, OWNER)

        await conn.execute("""
            insert into public.project_stages (id, project_id, position, key, name)
            values ($1,$2,0,'gate_1','Gate 1')""", STAGE, PROJECT)

        # Weights give ~98% when everything but the small R4 is satisfied.
        specs = [
            (R[1], 1, "R1", "Heavy requirement one",   True, 40, "any"),
            (R[2], 2, "R2", "Heavy requirement two",   True, 40, "any"),
            (R[3], 3, "R3", "Heavy requirement three", True, 18, "any"),
            (R[4], 4, "R4", "Small mandatory item",    True,  2, "document"),
            (R[5], 5, "R5", "Second small item",       True,  2, "any"),
        ]
        for rid, pos, code, title, mand, weight, etype in specs:
            await conn.execute("""
                insert into public.gate_requirements
                 (id, project_id, project_stage_id, position, ref_code, title,
                  is_mandatory, weight, required_evidence_type, owner_user_id)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """, rid, PROJECT, STAGE, pos, code, title, mand, weight, etype, OWNER)

        print("\n1. Fresh requirement, nothing attached")
        check("not satisfied", not await satisfied(conn, R[1]))
        st = await status(conn, R[1])
        check("status is not_started/in_progress", st in ("not_started", "in_progress"), st)

        # ------------------------------ evidence + acceptance, NO approval ---
        for n in (1, 2, 3):
            await conn.execute("""
                insert into public.evidence_links
                 (requirement_id, project_id, evidence_type, note, added_by)
                values ($1,$2,'note','Evidence',$3)""", R[n], PROJECT, OWNER)
            await conn.execute("""
                update public.gate_requirements
                   set acceptance_confirmed_by=$2, acceptance_confirmed_at=now()
                 where id=$1""", R[n], OWNER)

        print("\n2. Evidence attached and accepted, but NOT approved")
        print("   (the core no-false-green case)")
        check("still NOT satisfied", not await satisfied(conn, R[1]))
        check("status is awaiting_approval", await status(conn, R[1]) == "awaiting_approval",
              await status(conn, R[1]))

        print("\n3. Segregation of duties: the owner tries to approve their own work")
        # A failed statement aborts the enclosing transaction, so every
        # expected-failure case runs inside its own savepoint.
        async with expect_failure(conn, asyncpg.InsufficientPrivilegeError) as outcome:
            await conn.execute("""
                insert into public.approvals
                 (requirement_id, project_id, approver_id, approver_role, decision)
                values ($1,$2,$3,'senior_scientist','approved')""", R[1], PROJECT, OWNER)
        check("owner blocked from self-approval", outcome.rejected, outcome.detail)

        # ------------------------------------- independent approver signs ---
        for n in (1, 2, 3):
            await conn.execute("""
                insert into public.approvals
                 (requirement_id, project_id, approver_id, approver_role, decision)
                values ($1,$2,$3,'senior_scientist','approved')""", R[n], PROJECT, APPROVER)

        print("\n4. Approved by an independent approver")
        check("now satisfied", await satisfied(conn, R[1]))
        st = await status(conn, R[1])
        check("status is approved", st == "approved", st)

        print("\n5. THE KEY CASE: high readiness, small mandatory items outstanding")
        row = await readiness(conn)
        pct, ready = float(row["readiness_pct"]), row["is_ready"]
        print(f"   readiness_pct={pct}  is_ready={ready}  blockers={row['blocker_count']}")
        check("readiness is high (>=95%)", pct >= 95, f"{pct}%")
        check("is_ready is FALSE despite high percentage", ready is False)
        check("blockers reported", row["blocker_count"] == 2, f"{row['blocker_count']}")

        blockers = await conn.fetch("select * from private.gate_blockers($1)", STAGE)
        print("   blockers:")
        for b in blockers:
            print(f"     {b['ref_code']}  {b['status']:20} {b['reason'][:58]}")

        print("\n6. Wrong evidence type: R4 requires a document, receives a note")
        await conn.execute("""
            insert into public.evidence_links
             (requirement_id, project_id, evidence_type, note, added_by)
            values ($1,$2,'note','A note, not a document',$3)""", R[4], PROJECT, OWNER)
        await conn.execute("""
            update public.gate_requirements
               set acceptance_confirmed_by=$2, acceptance_confirmed_at=now() where id=$1""",
            R[4], OWNER)
        await conn.execute("""
            insert into public.approvals
             (requirement_id, project_id, approver_id, approver_role, decision)
            values ($1,$2,$3,'senior_scientist','approved')""", R[4], PROJECT, APPROVER)
        check("wrong evidence type does not satisfy", not await satisfied(conn, R[4]))
        check("status names the actual problem", await status(conn, R[4]) == "wrong_evidence_type",
              await status(conn, R[4]))

        print("\n7. Evidence changed after approval")
        check("satisfied before the change", await satisfied(conn, R[1]))
        await conn.execute("""
            insert into public.evidence_links
             (requirement_id, project_id, evidence_type, note, added_by)
            values ($1,$2,'note','Swapped evidence',$3)""", R[1], PROJECT, OWNER)
        check("approval superseded, no longer satisfied", not await satisfied(conn, R[1]),
              await status(conn, R[1]))
        n_sup = await conn.fetchval(
            "select count(*) from public.approvals "
            "where requirement_id=$1 and superseded_at is not null", R[1])
        check("supersession recorded", n_sup == 1, f"{n_sup} superseded")

        print("\n8. Dependency blocking")
        await conn.execute("""
            insert into public.gate_requirement_dependencies (requirement_id, depends_on_id)
            values ($1,$2)""", R[5], R[4])
        await conn.execute("""
            insert into public.evidence_links
             (requirement_id, project_id, evidence_type, note, added_by)
            values ($1,$2,'note','Own work done',$3)""", R[5], PROJECT, OWNER)
        await conn.execute("""
            update public.gate_requirements
               set acceptance_confirmed_by=$2, acceptance_confirmed_at=now() where id=$1""",
            R[5], OWNER)
        await conn.execute("""
            insert into public.approvals
             (requirement_id, project_id, approver_id, approver_role, decision)
            values ($1,$2,$3,'senior_scientist','approved')""", R[5], PROJECT, APPROVER)
        check("own work complete but prerequisite unmet", not await satisfied(conn, R[5]))
        check("status is awaiting_dependency", await status(conn, R[5]) == "awaiting_dependency",
              await status(conn, R[5]))

        print("\n9. Explicit block overrides everything")
        await conn.execute("""
            update public.gate_requirements
               set is_blocked=true, blocked_reason='Awaiting external test house',
                   blocked_by=$2, blocked_at=now() where id=$1""", R[2], APPROVER)
        check("blocked requirement not satisfied", not await satisfied(conn, R[2]))
        check("status is blocked", await status(conn, R[2]) == "blocked", await status(conn, R[2]))

        print("\n10. Blocking without a reason")
        async with expect_failure(conn, asyncpg.CheckViolationError) as outcome:
            await conn.execute(
                "update public.gate_requirements "
                "set is_blocked=true, blocked_reason=null where id=$1", R[3])
        check("block requires a reason", outcome.rejected)

        print("\n11. Waiving a mandatory requirement as not-applicable")
        async with expect_failure(conn, asyncpg.CheckViolationError) as outcome:
            await conn.execute("""
                update public.gate_requirements
                   set is_not_applicable=true, not_applicable_reason='Not needed',
                       not_applicable_by=$2 where id=$1""", R[3], APPROVER)
        check("mandatory cannot be waived", outcome.rejected)

        print("\n12. Final gate state")
        row = await readiness(conn)
        print(f"   readiness_pct={float(row['readiness_pct'])}  is_ready={row['is_ready']}  "
              f"blockers={row['blocker_count']}")
        check("gate remains not ready", row["is_ready"] is False)

        print(f"\n{'=' * 62}")
        print(f"  {passed} passed, {failed} failed")
        print(f"{'=' * 62}")
        return 0 if failed == 0 else 1
    finally:
        await tx.rollback()
        await conn.close()


raise SystemExit(asyncio.run(main()))
