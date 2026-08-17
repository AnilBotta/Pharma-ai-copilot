"""Step 3: what the Manager Agent may change, proven against the live database.

The claim being tested is not "the write worked". It is that the write is
ATTRIBUTABLE: an edit made by an agent has to be distinguishable from the same
edit made by a person, months later, by somebody reading the audit trail rather
than remembering the conversation.

The second claim is that the line held. The agent gets tools for the reversible
things and gets refused the rest by migration 0022, and the tools it does have
must not quietly reach past their remit - registering a document must not
satisfy a requirement, acknowledging an alert must not resolve it.

    python tests/db/test_manager_writes.py
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.manager import tools as T
from app.pdp.agent import AgentRepository
from app.pdp.repository import Conflict, PdpRepository

HUMAN = "cd000000-0000-0000-0000-000000000001"
OWNER = "cd000000-0000-0000-0000-000000000002"
PROJECT = "cd100000-0000-0000-0000-000000000001"
STAGE = "cd200000-0000-0000-0000-000000000001"
REQ = "cd300000-0000-0000-0000-000000000001"

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class PoolShim:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def dsn() -> str:
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


async def refused(conn, coro, *exc_types):
    sp = conn.transaction()
    await sp.start()
    result = (False, "")
    try:
        await coro
    except exc_types as exc:
        result = (True, str(exc).split("\n")[0][:80])
    except Exception as exc:
        result = (False, f"wrong error: {type(exc).__name__}: {exc}"[:80])
    finally:
        await sp.rollback()
    return result


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)

    pool = PoolShim(conn)
    human = PdpRepository(pool)
    agent_repo = AgentRepository(pool, "manager")

    ctx = T.ToolContext(
        user_id=HUMAN,
        pdp=agent_repo,
        core=None,
        pool=pool,
        settings=None,
        models=None,
    )

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email, name in (
            (HUMAN, "mw-human@test.local", "Dana Human"),
            (OWNER, "mw-owner@test.local", "Sam Owner"),
        ):
            await conn.execute(
                """
                insert into auth.users (id, instance_id, aud, role, email,
                    encrypted_password, email_confirmed_at, created_at, updated_at)
                values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                        'authenticated',$2,'x',now(),now(),now())
                """,
                uid, email,
            )
            await conn.execute(
                "update public.profiles set full_name = $2 where id = $1", uid, name
            )
        await conn.execute(
            "insert into public.projects (id, user_id, name, pdp_enabled) "
            "values ($1,$2,'Manager Writes Test', true)",
            PROJECT, HUMAN,
        )
        for uid, role in ((HUMAN, "project_manager"), (OWNER, "senior_scientist")):
            await conn.execute(
                """
                insert into public.user_roles (user_id, role_id, project_id)
                select $1, r.id, $3 from public.roles r where r.key = $2
                on conflict do nothing
                """,
                uid, role, PROJECT,
            )
        await conn.execute(
            "insert into public.project_stages (id, project_id, position, key, name) "
            "values ($1,$2,0,'gate_1','Gate 1')",
            STAGE, PROJECT,
        )
        await conn.execute(
            """
            insert into public.gate_requirements
              (id, project_id, project_stage_id, position, ref_code, title,
               is_mandatory, weight, required_evidence_type)
            values ($1,$2,$3,0,'M-001','Preformulation report',true,10,'document')
            """,
            REQ, PROJECT, STAGE,
        )

        # -------------------------------------------------- who is on this ---
        print("\n  LOOKING PEOPLE UP BEFORE ASSIGNING TO THEM")
        people = await T._list_people(ctx, PROJECT)
        by_name = {p["name"]: p for p in people}
        check("list_people returns real ids", len(people) >= 2, f"{len(people)} people")
        check(
            "and the names a person would actually say",
            "Sam Owner" in by_name,
            ", ".join(sorted(by_name)[:3]),
        )

        # ------------------------------------------------- the attribution ---
        print("\n  AN AGENT EDIT IS DISTINGUISHABLE FROM A HUMAN ONE")
        before = await conn.fetchval("select coalesce(max(id), 0) from public.audit_events")

        result = await T._set_assignment(
            ctx,
            requirement_id=REQ,
            owner_user_id=by_name["Sam Owner"]["user_id"],
            due_date="2026-11-30",
        )
        check("the agent can assign an owner", result["updated"] is True)
        check("and the due date lands", result["due_date"] == "2026-11-30")

        agent_rows = await conn.fetch(
            "select action, actor_agent, actor_user_id from public.audit_events "
            "where id > $1 order by id",
            before,
        )
        check(
            "the edit is in the audit trail",
            len(agent_rows) > 0,
            f"{len(agent_rows)} event(s)",
        )
        check(
            "marked as done by an agent",
            any(r["actor_agent"] == "manager" for r in agent_rows),
            str([r["actor_agent"] for r in agent_rows]),
        )
        check(
            "and still attributed to the person it acted for",
            all(str(r["actor_user_id"]) == HUMAN for r in agent_rows if r["actor_user_id"]),
        )

        # The same edit by a person must NOT be marked as an agent, or the
        # distinction is decorative.
        mid = await conn.fetchval("select coalesce(max(id), 0) from public.audit_events")
        await human.set_assignment(HUMAN, REQ, priority="high")
        human_rows = await conn.fetch(
            "select actor_agent from public.audit_events where id > $1", mid
        )
        check(
            "the same edit by a person is not",
            len(human_rows) > 0 and all(r["actor_agent"] is None for r in human_rows),
            str([r["actor_agent"] for r in human_rows]),
        )

        # --------------------------------------------------------- the line ---
        print("\n  THE TOOLS DO NOT REACH PAST THEIR REMIT")

        doc = await T._create_document(
            ctx,
            project_id=PROJECT,
            document_number="SOP-014",
            title="Preformulation procedure",
            document_type="sop",
        )
        check("the agent can register a document", doc["created"] is True)
        usable = await conn.fetchval(
            "select count(*) from public.controlled_document_versions v "
            "where v.document_id = $1",
            doc["document_id"],
        )
        check(
            "registering it creates no version, so it satisfies nothing",
            usable == 0,
            f"{usable} versions",
        )

        task = await T._create_task(
            ctx, project_id=PROJECT, title="Draft the preformulation report"
        )
        check("the agent can create a task", task["created"] is True)

        milestone = await T._create_milestone(
            ctx, project_id=PROJECT, name="Preformulation complete"
        )
        contractual = await conn.fetchval(
            "select is_contractual from public.project_milestones where id = $1",
            milestone["milestone_id"],
        )
        check(
            "a milestone it adds is never contractual",
            contractual is False,
            f"is_contractual={contractual}",
        )

        ok, detail = await refused(
            conn,
            T._set_blocked(ctx, requirement_id=REQ, blocked=True, reason="   "),
            Conflict,
        )
        check("blocking without a reason is refused", ok, detail)

        # The accountable acts are NOT re-tested here. A first draft called
        # decide_requirement and passed - on "the acceptance criteria have not
        # been confirmed", which a human would have hit identically. That
        # proves nothing about agent authority while looking like it does, and
        # it is the same false pass this suite's sibling already caught once.
        # tests/db/test_agent_authority.py does it properly, with the setup
        # needed to reach the trigger.

        # ---------------------------------------------------- date handling ---
        print("\n  A DATE IS PARSED, NOT GUESSED")
        bad = False
        try:
            T._date("30/11/2026")
        except ValueError:
            bad = True
        check("an ambiguous date is refused rather than interpreted", bad)
        check("an ISO date parses", str(T._date("2026-11-30")) == "2026-11-30")
        check("and absent stays absent", T._date(None) is None)

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
raise SystemExit(asyncio.run(main()))
