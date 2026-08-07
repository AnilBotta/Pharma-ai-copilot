"""Phase G: what an agent cannot do, proven against the live database.

The claim this suite exists to test is the one the whole module rests on when
agents arrive: an agent gets NO privileged path. It calls the same repository a
person's HTTP request calls, and the accountable acts are refused by the
database rather than by the absence of a tool.

So these tests do the thing a careless integration would do — hand the agent a
real user's id, one holding every approving role — and check it is still
refused. If the guarantee lived in the tool schema, every one of these would
pass by accident, because the test calls the repository directly.

    python tests/db/test_agent_authority.py
"""

import asyncio
import pathlib
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.pdp.agent import AgentRepository
from app.pdp.repository import Forbidden, PdpRepository

HUMAN = "ec000000-0000-0000-0000-000000000001"
APPROVER = "ec000000-0000-0000-0000-000000000002"
PROJECT = "ec100000-0000-0000-0000-000000000001"
STAGE = "ec200000-0000-0000-0000-000000000001"
REQ = "ec300000-0000-0000-0000-000000000001"
TASK = "ec400000-0000-0000-0000-000000000001"

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


async def refused(conn, coro, *exc_types):
    """Await something expected to be refused, inside a savepoint."""
    sp = conn.transaction()
    await sp.start()
    result = (False, "")
    try:
        await coro
    except exc_types as exc:
        result = (True, str(exc).split("\n")[0][:90])
    except Exception as exc:
        result = (False, f"wrong error: {type(exc).__name__}: {exc}"[:90])
    finally:
        await sp.rollback()
    return result


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


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)

    human = PdpRepository(PoolShim(conn))
    agent = AgentRepository(PoolShim(conn), "pdp_operations")

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (HUMAN, "ag-human@test.local"), (APPROVER, "ag-approver@test.local")
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
            "insert into public.projects (id, user_id, name, pdp_enabled) "
            "values ($1,$2,'Agent Authority Test', true)",
            PROJECT, HUMAN,
        )
        # The approver holds every authority there is. The agent will be handed
        # this id — the careless-integration case.
        for role in ("gate_committee_member", "project_manager", "senior_scientist"):
            await conn.execute(
                """
                insert into public.user_roles (user_id, role_id, project_id)
                select $1, r.id, $3 from public.roles r where r.key = $2
                on conflict do nothing
                """,
                APPROVER, role, PROJECT,
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
               is_mandatory, weight, required_evidence_type, owner_user_id)
            values ($1,$2,$3,0,'A-001','Development report',true,10,'any',$4)
            """,
            REQ, PROJECT, STAGE, HUMAN,
        )
        await conn.execute(
            """
            insert into public.project_tasks
              (id, project_id, title, forecast_start, forecast_end)
            values ($1,$2,'Draft the report',$3,$4)
            """,
            TASK, PROJECT, date.today(), date.today() + timedelta(days=10),
        )

        # ---------------------------------------------- 1. what it CAN do ---
        print("\n1. The agent reads and contributes like anyone else")

        gate = await agent.get_gate(APPROVER, STAGE)
        check("it can read the gate", gate["stage"]["key"] == "gate_1")
        check("including the blocker list", len(gate["blockers"]) == 1,
              f"{len(gate['blockers'])}")

        evidence = await agent.attach_evidence(
            APPROVER, REQ, evidence_type="note",
            note="Draft report located in the team folder; not yet in the register.",
            title="Agent-located draft",
        )
        check("it can attach evidence", evidence["id"] is not None)

        await conn.execute(
            """
            update public.evidence_links
               set ai_assessment = $2, ai_confidence = 0.4, ai_agent = 'pdp_operations',
                   ai_assessed_at = now()
             where id = $1
            """,
            evidence["id"],
            "Covers three of the four acceptance criteria; stability data is absent.",
        )
        check("it can record an assessment", True, "a description, not a verdict")

        # ------------------------------ 2. the vocabulary of a decision ---
        print("\n2. An assessment may describe and doubt, not decide")

        for phrase, must_fail in (
            ("This evidence is approved for the requirement.", True),
            ("Compliant with the acceptance criteria.", True),
            ("Does not satisfy the acceptance criteria.", False),
            ("Unclear whether the stability data is adequate.", False),
        ):
            ok, detail = await refused(
                conn,
                conn.execute(
                    "update public.evidence_links set ai_assessment = $2 where id = $1",
                    evidence["id"], phrase,
                ),
                asyncpg.PostgresError,
            )
            if must_fail:
                check(f"refused: {phrase[:44]}", ok, "verdict vocabulary")
            else:
                check(f"allowed: {phrase[:44]}", not ok,
                      "negative and hedged findings are the useful kind")

        # ------------------------------------ 3. THE POINT OF THE PHASE ---
        print("\n3. Holding a fully authorised user's id, the agent is STILL refused")
        print("   (the careless-integration case: 'just let it finish the paperwork')")

        await human.set_acceptance(HUMAN, REQ, confirmed=True)

        ok, detail = await refused(
            conn,
            agent.decide_requirement(APPROVER, REQ, decision="approved"),
            Forbidden,
        )
        check("it cannot APPROVE A REQUIREMENT", ok, detail)
        check(
            "...and it is the AGENT rule that refuses, not a role check",
            "agent authority" in detail,
            detail[:60],
        )

        # Make the gate genuinely ready first. The earlier version of this test
        # tried the gate decision on an unready gate and "passed" on the
        # readiness refusal — proving nothing about the agent trigger, because
        # a human would have been refused identically.
        await human.decide_requirement(APPROVER, REQ, decision="approved")
        readiness = await conn.fetchrow(
            "select * from private.gate_readiness($1)", STAGE
        )
        check("the gate is now genuinely ready", readiness["is_ready"] is True,
              f"{readiness['readiness_pct']}%, {readiness['blocker_count']} blockers")

        ok, detail = await refused(
            conn,
            agent.decide_gate(APPROVER, STAGE, decision="approved", note="Looks fine."),
            Exception,
        )
        check("it cannot PASS A GATE even when the gate is ready", ok, detail)
        check(
            "...and again it is the AGENT rule",
            "agent authority" in detail,
            detail[:60],
        )

        ok, detail = await refused(
            conn,
            agent.rebaseline(APPROVER, PROJECT, name="B1", reason="Agent decided."),
            Exception,
        )
        check("it cannot SET A BASELINE", ok, detail)

        # Through the agent's own connection wrapper, which is what sets the
        # mark. Running the raw UPDATE on the bare connection would test
        # nothing: that connection is not an agent.
        async def agent_confirms():
            async with agent._pool.acquire() as marked:
                await marked.execute(
                    "update public.evidence_links set human_confirmed_by = $2 "
                    "where id = $1",
                    evidence["id"], APPROVER,
                )

        ok, detail = await refused(conn, agent_confirms(), asyncpg.PostgresError)
        check("it cannot CONFIRM ITS OWN ASSESSMENT", ok, detail)

        # --------------------------------- 4. and the human path still works ---
        print("\n4. The same calls succeed for a person")

        current = await conn.fetchrow(
            "select decision from public.approvals "
            " where requirement_id = $1 and superseded_at is null",
            REQ,
        )
        check("a person with the role already approved it above",
              current and current["decision"] == "approved")

        stage_row = await human.decide_gate(
            APPROVER, STAGE, decision="approved", note="Reviewed."
        )
        check("a person with gate authority can pass the gate",
              stage_row["gate_status"] == "approved")

        baseline = await human.rebaseline(
            APPROVER, PROJECT, name="Baseline 1", reason="Initial commitment."
        )
        check("a person with approval authority can baseline",
              baseline["version"] == 1)

        # ------------------------------------------- 5. no leakage ---
        print("\n5. The agent mark does not leak")

        marker = await conn.fetchval("select current_setting('app.acting_agent', true)")
        check(
            "the connection is unmarked after the agent releases it",
            not marker,
            f"marker={marker!r}",
        )

        # A human repository sharing the same connection is unaffected.
        await conn.execute(
            "update public.gate_requirements set acceptance_confirmed_by = null "
            "where id = $1",
            REQ,
        )
        await human.set_acceptance(HUMAN, REQ, confirmed=True)
        second = await human.decide_requirement(
            APPROVER, REQ, decision="approved", comments="Re-approved after change."
        )
        check("the human path still works on the same connection",
              second["decision"] == "approved")

        # ----------------------------------------------- 6. accountability ---
        print("\n6. An agent session names the person it ran for")

        columns = await conn.fetch(
            "select column_name, is_nullable from information_schema.columns "
            "where table_name = 'pdp_agent_sessions'"
        )
        requested_by = [c for c in columns if c["column_name"] == "requested_by"]
        check(
            "requested_by is NOT NULL",
            requested_by and requested_by[0]["is_nullable"] == "NO",
            "an action with no accountable person is not representable",
        )

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n{'=' * 62}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'=' * 62}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
