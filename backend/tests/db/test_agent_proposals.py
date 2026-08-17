"""Step 4: the agent prepares, a person decides — proven against the database.

Three claims, and the second is the one this step exists for.

  1. An agent cannot confirm its own proposal. Same shape as 0022: if it could,
     the whole flow is the accountable act handed back through a longer route.

  2. A proposal whose PREMISE has moved cannot be confirmed. Between writing
     and clicking, a colleague can attach evidence or withdraw an acceptance;
     the proposal still looks right and confirming it would apply a judgement
     to a state nobody judged.

  3. Confirming executes as the PERSON. Segregation of duties applies to them
     exactly as if they had used the form - an owner still cannot approve their
     own requirement - and the approval is attributed to them, not to an agent.

    python tests/db/test_agent_proposals.py
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.manager import proposals as P
from app.manager.repository import ManagerRepository
from app.pdp.agent import AgentRepository
from app.pdp.repository import Forbidden, PdpRepository

DOER = "ab000000-0000-0000-0000-000000000001"
APPROVER = "ab000000-0000-0000-0000-000000000002"
PROJECT = "ab100000-0000-0000-0000-000000000001"
STAGE = "ab200000-0000-0000-0000-000000000001"
REQ = "ab300000-0000-0000-0000-000000000001"
RUN = "ab400000-0000-0000-0000-000000000001"

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
        result = (True, str(exc).split("\n")[0][:85])
    except Exception as exc:
        result = (False, f"wrong error: {type(exc).__name__}: {exc}"[:85])
    finally:
        await sp.rollback()
    return result


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)

    pool = PoolShim(conn)
    human = PdpRepository(pool)
    agent_repo = AgentRepository(pool, "manager")
    manager = ManagerRepository(pool)

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (DOER, "ap-doer@test.local"), (APPROVER, "ap-approver@test.local")
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
            "values ($1,$2,'Proposal Test', true)",
            PROJECT, DOER,
        )
        for uid, role in (
            (DOER, "senior_scientist"),
            (APPROVER, "gate_committee_member"),
            (APPROVER, "project_manager"),
        ):
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
               is_mandatory, weight, required_evidence_type, owner_user_id)
            values ($1,$2,$3,0,'P-001','Feasibility report',true,10,'any',$4)
            """,
            REQ, PROJECT, STAGE, DOER,
        )
        await conn.execute(
            """
            insert into public.research_runs
              (id, project_id, user_id, original_question, status, completed_at)
            values ($1,$2,$3,'Depot feasibility','completed', now())
            """,
            RUN, PROJECT, DOER,
        )
        # Evidence attached and acceptance confirmed by the doer, so the
        # approver has something real to approve.
        await human.attach_evidence(
            DOER, REQ, evidence_type="research_run", research_run_id=RUN
        )
        await human.set_acceptance(DOER, REQ, confirmed=True)

        convo = await manager.create_conversation(APPROVER, "proposal test")

        # ------------------------------------------------ the agent proposes ---
        print("\n  THE AGENT PREPARES AN ACT IT CANNOT TAKE")
        action = P.validate("approve_requirement", {"requirement_id": REQ})
        premise = await P.capture_premise(agent_repo, APPROVER, action, {"requirement_id": REQ})
        check(
            "the premise records the evidence the decision rests on",
            len(premise["evidence_ids"]) == 1,
            f"{len(premise['evidence_ids'])} evidence id(s)",
        )
        check(
            "and who confirmed acceptance",
            premise["acceptance_confirmed_by"] == DOER,
        )

        proposal = await manager.create_proposal(
            conversation_id=str(convo["id"]),
            requested_by=APPROVER,
            project_id=PROJECT,
            action_type="approve_requirement",
            params={"requirement_id": REQ},
            rationale="Evidence is attached and acceptance is confirmed.",
            premise=premise,
        )
        check("the proposal is pending", proposal["status"] == "pending")

        # The jsonb columns must come back as OBJECTS. They did not once: the
        # pool's codec encodes with json.dumps, so passing an already-serialised
        # string stored JSON-inside-JSON. It read back as `str` and surfaced far
        # away, as a response-validation error on an endpoint that looked fine.
        fetched = await manager.get_proposal(APPROVER, str(proposal["id"]))
        check(
            "params round-trips as an object, not a string",
            isinstance(fetched["params"], dict),
            type(fetched["params"]).__name__,
        )
        check(
            "premise round-trips as an object, not a string",
            isinstance(fetched["premise"], dict),
            type(fetched["premise"]).__name__,
        )
        check(
            "and the values survive intact",
            fetched["params"].get("requirement_id") == REQ,
        )

        # -------------------------------------- an agent may not confirm one ---
        print("\n  AN AGENT MAY NOT CONFIRM ITS OWN PROPOSAL")
        sp = conn.transaction()
        await sp.start()
        agent_refused = False
        detail = ""
        try:
            await conn.execute("select set_config('app.acting_agent','manager',true)")
            await conn.execute(
                "update public.agent_proposals set status='confirmed', "
                "confirmed_by=$2, confirmed_at=now() where id=$1",
                proposal["id"], APPROVER,
            )
        except Exception as exc:
            agent_refused = "agent authority" in str(exc)
            detail = str(exc).split("\n")[0][:85]
        finally:
            await sp.rollback()
        check("refused while an agent is acting", agent_refused, detail)

        # ------------------------------------------------ the premise moved ---
        print("\n  A PROPOSAL WHOSE BASIS HAS MOVED CANNOT BE CONFIRMED")
        stored = fetched

        # Somebody withdraws the acceptance while the card sits on screen.
        await human.set_acceptance(DOER, REQ, confirmed=False)

        moved, detail = await refused(
            conn,
            P.confirm(repo=human, user_id=APPROVER, proposal=stored),
            P.PremiseMoved,
        )
        check("confirmation is refused, not warned about", moved, detail)
        check(
            "and it says what changed",
            "acceptance" in detail.lower(),
            detail,
        )

        # Put it back so the happy path can be tested.
        await human.set_acceptance(DOER, REQ, confirmed=True)

        # ------------------------------------- confirming acts as the person ---
        print("\n  CONFIRMING EXECUTES AS THE PERSON, NOT THE AGENT")
        before = await conn.fetchval("select coalesce(max(id),0) from public.audit_events")
        result = await P.confirm(repo=human, user_id=APPROVER, proposal=stored)
        check("the approval is recorded", result is not None)

        approval = await conn.fetchrow(
            "select approver_id, approver_role from public.approvals "
            "where requirement_id = $1 order by approved_at desc limit 1",
            REQ,
        )
        check(
            "attributed to the confirming person",
            str(approval["approver_id"]) == APPROVER,
            approval["approver_role"],
        )
        agent_marks = await conn.fetch(
            "select actor_agent from public.audit_events where id > $1", before
        )
        check(
            "and NOT marked as an agent action",
            all(r["actor_agent"] is None for r in agent_marks),
            str([r["actor_agent"] for r in agent_marks]),
        )

        # ---------------------------------------- segregation still applies ---
        print("\n  SEGREGATION OF DUTIES STILL APPLIES TO THE CONFIRMER")
        doer_proposal = dict(stored)
        # `Forbidden` specifically, not any exception. The route distinguishes
        # by type: Forbidden leaves the proposal PENDING, because "you may not
        # do this" is a fact about the person who clicked and a colleague with
        # authority still can. Anything else marks it spent.
        #
        # The first version marked every failure spent, and production showed
        # what that costs: a proposal sitting at `failed` purely because the
        # person who confirmed the acceptance was the one who opened the card.
        ok, detail = await refused(
            conn,
            P.confirm(repo=human, user_id=DOER, proposal=doer_proposal),
            Forbidden,
        )
        check(
            "the doer cannot confirm an approval of their own work",
            ok,
            detail,
        )
        check(
            "...and it is Forbidden, so the proposal stays open for someone else",
            ok and "segregation" in detail.lower(),
            detail,
        )

        # ------------------------------------------------- decided only once ---
        print("\n  A PROPOSAL IS DECIDED ONCE")
        await manager.settle_proposal(
            str(proposal["id"]), status="confirmed", confirmed_by=APPROVER
        )
        ok, detail = await refused(
            conn,
            manager.settle_proposal(
                str(proposal["id"]), status="rejected", rejected_reason="changed my mind"
            ),
            Exception,
        )
        check("a settled proposal cannot be decided again", ok, detail)

        # ------------------------------------------------------- validation ---
        print("\n  AN UNEXECUTABLE PROPOSAL FAILS WHEN IT IS WRITTEN")
        bad_action = False
        try:
            P.validate("delete_everything", {})
        except ValueError:
            bad_action = True
        check("an unknown action is refused", bad_action)

        missing = False
        try:
            P.validate("decide_gate", {"stage_id": STAGE})
        except ValueError as exc:
            missing = "decision" in str(exc)
        check("missing parameters are named", missing)

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
raise SystemExit(asyncio.run(main()))
