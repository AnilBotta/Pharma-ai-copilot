"""Phase C API layer, exercised against the live database.

The readiness engine already has its own suite (test_readiness_engine.py). This
one drives PdpRepository - the code an HTTP request or, in Phase G, an agent
tool actually reaches - so that authorisation, the write guards and the audit
trail are tested through the same path a caller takes rather than through SQL
written for the occasion.

Everything happens inside one transaction that is rolled back, so the database
is unchanged afterwards. The repository opens its own transactions; nested
inside an open one, asyncpg turns those into savepoints, which is exactly the
semantics we want.
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.pdp.repository import (
    Conflict,
    Forbidden,
    NotFound,
    PdpRepository,
)

# ---------------------------------------------------------------- fixtures ---

OWNER = "d0000000-0000-0000-0000-000000000001"       # project owner and doer
APPROVER = "d0000000-0000-0000-0000-000000000002"    # senior_scientist
GATEKEEPER = "d0000000-0000-0000-0000-000000000003"  # gate_committee_member
CONTRIB = "d0000000-0000-0000-0000-000000000004"     # scientist: access only
OUTSIDER = "d0000000-0000-0000-0000-000000000005"    # no grant at all

PROJECT = "d1000000-0000-0000-0000-000000000001"
OTHER_PROJECT = "d1000000-0000-0000-0000-000000000002"

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


async def raises(exc_type, coro):
    """Await `coro`, returning (matched, message).

    The repository runs inside savepoints, so a refused call leaves the outer
    transaction usable and the next assertion still runs.
    """
    try:
        await coro
    except exc_type as exc:
        return True, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return False, "no exception raised"


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class PoolShim:
    """Hands the repository the one connection our transaction is open on."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def dsn() -> str:
    env_path = pathlib.Path(__file__).resolve().parents[2] / ".env"
    match = re.search(
        r"^DATABASE_URL=(.+)$", env_path.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match or not match.group(1).strip():
        raise SystemExit(f"DATABASE_URL is not set in {env_path}")
    return match.group(1).strip()


async def make_user(conn, uid: str, email: str) -> None:
    await conn.execute(
        """
        insert into auth.users (id, instance_id, aud, role, email,
            encrypted_password, email_confirmed_at, created_at, updated_at)
        values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                'authenticated',$2,'x',now(),now(),now())
        """,
        uid, email,
    )


async def grant(conn, uid: str, role_key: str, project_id: str | None) -> None:
    await conn.execute(
        """
        insert into public.user_roles (user_id, role_id, project_id)
        select $1, r.id, $3 from public.roles r where r.key = $2
        """,
        uid, role_key, project_id,
    )


async def build_template(conn, *, status: str, key: str) -> str:
    """A small template shaped to exercise the engine's edges.

    R-002 depends on R-001, so blocking R-001 must cascade. R-004 is a small
    mandatory item nothing depends on - that is what makes the "97% and not
    ready" case constructible, which is the claim this module rests on.
    """
    template_id = await conn.fetchval(
        """
        insert into public.pdp_templates
            (template_key, version, name, product_type, status, approved_by, approved_at)
        values ($1, 1, 'Phase C Test Template', 'general', $2,
                case when $2 = 'active' then $3::uuid else null end,
                case when $2 = 'active' then now() else null end)
        returning id
        """,
        key, status, GATEKEEPER,
    )
    stage_id = await conn.fetchval(
        """
        insert into public.template_stages
            (template_id, position, key, name, gate_question)
        values ($1, 0, 'gate_1', 'Gate 1: Feasibility',
                'Is the concept scientifically feasible?')
        returning id
        """,
        template_id,
    )
    reqs = {}
    specs = [
        ("R-001", "Literature landscape", True, 50, "any", 30),
        ("R-002", "Preformulation data", True, 45, "any", 60),
        ("R-003", "Optional nice-to-have", False, 5, "any", None),
        ("R-004", "Small mandatory sign-off", True, 2, "any", 45),
    ]
    for position, (code, title, mandatory, weight, etype, lead) in enumerate(specs):
        reqs[code] = await conn.fetchval(
            """
            insert into public.template_requirements
                (template_stage_id, position, ref_code, title, is_mandatory,
                 weight, required_evidence_type, default_lead_days,
                 acceptance_criteria)
            values ($1,$2,$3,$4,$5,$6,$7,$8,'Data reviewed and complete.')
            returning id
            """,
            stage_id, position, code, title, mandatory, weight, etype, lead,
        )
    # R-002 cannot be satisfied before R-001.
    await conn.execute(
        """
        insert into public.template_requirement_dependencies
            (requirement_id, depends_on_id) values ($1, $2)
        """,
        reqs["R-002"], reqs["R-001"],
    )
    return str(template_id)


# -------------------------------------------------------------------- main ---


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)
    repo = PdpRepository(PoolShim(conn))

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (OWNER, "pc-owner@test.local"),
            (APPROVER, "pc-approver@test.local"),
            (GATEKEEPER, "pc-gate@test.local"),
            (CONTRIB, "pc-contrib@test.local"),
            (OUTSIDER, "pc-outsider@test.local"),
        ):
            await make_user(conn, uid, email)

        for pid, name in ((PROJECT, "Phase C Test"), (OTHER_PROJECT, "Unrelated")):
            await conn.execute(
                "insert into public.projects (id, user_id, name) values ($1,$2,$3)",
                pid, OWNER, name,
            )

        await grant(conn, APPROVER, "senior_scientist", PROJECT)
        await grant(conn, GATEKEEPER, "gate_committee_member", PROJECT)
        await grant(conn, CONTRIB, "scientist", PROJECT)

        draft_template = await build_template(conn, status="draft", key="pc_draft")
        active_template = await build_template(conn, status="active", key="pc_active")

        # ------------------------------------------------- 1. authorisation ---
        print("\n1. Who may see and who may build the programme")

        ok, msg = await raises(
            NotFound, repo.capabilities(OUTSIDER, PROJECT)
        )
        check("a user with no grant cannot see the project", ok, msg[:60])

        caps = await repo.capabilities(CONTRIB, PROJECT)
        check("a project-scoped scientist can see it", caps.can_access)
        check("...but holds no approval authority", not caps.can_approve)
        check("...and no gate authority", not caps.can_gate)

        caps = await repo.capabilities(APPROVER, PROJECT)
        check("senior_scientist may approve", caps.can_approve)
        check("...but may not decide a gate", not caps.can_gate)

        caps = await repo.capabilities(GATEKEEPER, PROJECT)
        check("gate_committee_member may decide a gate", caps.can_gate)

        caps = await repo.capabilities(OWNER, PROJECT)
        check("the project owner may administer", caps.can_administer)

        # ----------------------------------------------- 2. instantiation ---
        print("\n2. Instantiating a programme from a template")

        ok, msg = await raises(
            Forbidden,
            repo.instantiate(CONTRIB, PROJECT, template_id=active_template),
        )
        check("a contributor cannot instantiate", ok, msg[:60])

        ok, msg = await raises(
            Conflict,
            repo.instantiate(OWNER, PROJECT, template_id=draft_template),
        )
        check("an unapproved (draft) template is refused", ok, msg[:70])

        from datetime import date

        result = await repo.instantiate(
            OWNER, PROJECT, template_id=active_template, start_date=date(2026, 1, 5)
        )
        check("instantiated", result["stages_created"] == 1, str(result["stages_created"]))
        check("4 requirements copied", result["requirements_created"] == 4)
        check("1 dependency remapped", result["dependencies_created"] == 1)

        ok, msg = await raises(
            Conflict,
            repo.instantiate(OWNER, PROJECT, template_id=active_template),
        )
        check("instantiating twice is refused", ok, msg[:60])

        programme = await repo.get_programme(OWNER, PROJECT)
        stage_id = str(programme["stages"][0]["id"])
        gate = await repo.get_gate(OWNER, stage_id)
        by_code = {r["ref_code"]: r for r in gate["requirements"]}
        r1, r2, r3, r4 = (
            by_code["R-001"], by_code["R-002"], by_code["R-003"], by_code["R-004"]
        )

        check(
            "due dates derived from the start date",
            str(r1["due_date"]) == "2026-02-04",
            str(r1["due_date"]),
        )
        check(
            "acceptance criteria copied, not referenced",
            r1["acceptance_criteria"] == "Data reviewed and complete.",
        )

        # ------------------------------------------------- 3. the two numbers ---
        print("\n3. Readiness starts at zero and says why")
        check("0% ready", float(gate["readiness"]["readiness_pct"]) == 0.0)
        check("is_ready is false", gate["readiness"]["is_ready"] is False)
        check("3 blockers, matching the 3 mandatory items",
              gate["readiness"]["blocker_count"] == 3)
        check("blocker list is returned with the number",
              len(gate["blockers"]) == 3)

        # ------------------------------------------------------- 4. evidence ---
        print("\n4. Evidence, and what is refused as evidence")

        queued_run = await conn.fetchval(
            """
            insert into public.research_runs (project_id, user_id, original_question, status)
            values ($1,$2,'Is a depot feasible for this peptide?','queued') returning id
            """,
            PROJECT, OWNER,
        )
        done_run = await conn.fetchval(
            """
            insert into public.research_runs
                (project_id, user_id, original_question, status, completed_at)
            values ($1,$2,'Depot feasibility, completed run','completed', now()) returning id
            """,
            PROJECT, OWNER,
        )
        foreign_run = await conn.fetchval(
            """
            insert into public.research_runs
                (project_id, user_id, original_question, status, completed_at)
            values ($1,$2,'Run belonging to another project','completed', now()) returning id
            """,
            OTHER_PROJECT, OWNER,
        )

        ok, msg = await raises(
            Conflict,
            repo.attach_evidence(
                OWNER, r1["id"], evidence_type="research_run",
                research_run_id=str(queued_run),
            ),
        )
        check("an unfinished research run is refused as evidence", ok, msg[:60])

        ok, msg = await raises(
            Conflict,
            repo.attach_evidence(
                OWNER, r1["id"], evidence_type="research_run",
                research_run_id=str(foreign_run),
            ),
        )
        check("a run from another project is refused", ok, msg[:60])

        await repo.attach_evidence(
            OWNER, r1["id"], evidence_type="research_run",
            research_run_id=str(done_run), title="Literature landscape run",
        )
        check("a completed run on this project is accepted", True)

        # ----------------------------------------------------- 5. acceptance ---
        print("\n5. Acceptance is a claim, and needs something to be about")

        ok, msg = await raises(
            Conflict, repo.set_acceptance(OWNER, r2["id"], confirmed=True)
        )
        check("acceptance with no evidence is refused", ok, msg[:60])

        after = await repo.set_acceptance(OWNER, r1["id"], confirmed=True)
        check("acceptance confirmed", after["acceptance_confirmed_by"] is not None)
        check("status is now awaiting_approval",
              after["status"] == "awaiting_approval", after["status"])
        check("still NOT satisfied on acceptance alone", not after["is_satisfied"])

        # ------------------------------------------------------ 6. approval ---
        print("\n6. Approval: three independent gates in front of it")

        ok, msg = await raises(
            Forbidden,
            repo.decide_requirement(CONTRIB, r1["id"], decision="approved"),
        )
        check("no approval role: refused", ok, msg[:60])

        ok, msg = await raises(
            Conflict,
            repo.decide_requirement(APPROVER, r3["id"], decision="approved"),
        )
        check("approving a requirement with no evidence: refused", ok, msg[:60])

        # Segregation of duties reached through the API: give the approver
        # ownership of a requirement they would otherwise be entitled to approve.
        await repo.set_assignment(OWNER, r2["id"], owner_user_id=APPROVER)
        await repo.attach_evidence(
            OWNER, r2["id"], evidence_type="note", note="Preformulation summary."
        )
        await repo.set_acceptance(OWNER, r2["id"], confirmed=True)
        ok, msg = await raises(
            Forbidden,
            repo.decide_requirement(APPROVER, r2["id"], decision="approved"),
        )
        check("the owner of a requirement cannot approve it", ok, msg[:70])

        # And whoever confirmed acceptance cannot approve either.
        await repo.set_acceptance(GATEKEEPER, r2["id"], confirmed=True)
        ok, msg = await raises(
            Forbidden,
            repo.decide_requirement(GATEKEEPER, r2["id"], decision="approved"),
        )
        check("the acceptance confirmer cannot approve", ok, msg[:70])

        approval = await repo.decide_requirement(
            APPROVER, r1["id"], decision="approved", comments="Landscape is adequate."
        )
        check("an independent approver with the role succeeds",
              approval["decision"] == "approved")
        check("the role exercised is recorded",
              approval["approver_role"] == "senior_scientist",
              str(approval["approver_role"]))
        check("the evidence set is snapshotted at approval",
              len(approval["evidence_snapshot"]) == 1)

        gate = await repo.get_gate(OWNER, stage_id)
        r1_now = {r["ref_code"]: r for r in gate["requirements"]}["R-001"]
        check("R-001 is now satisfied", r1_now["is_satisfied"])

        # ------------------------------------- 7. approvals do not survive change ---
        print("\n7. An approval is about one evidence set, and only that one")

        await repo.attach_evidence(
            OWNER, r1["id"], evidence_type="url",
            external_url="https://example.org/late-addition",
        )
        gate = await repo.get_gate(OWNER, stage_id)
        r1_now = {r["ref_code"]: r for r in gate["requirements"]}["R-001"]
        check("adding evidence supersedes the approval", not r1_now["is_satisfied"])
        check("status returns to awaiting_approval",
              r1_now["status"] == "awaiting_approval", r1_now["status"])

        await repo.decide_requirement(APPROVER, r1["id"], decision="approved")
        gate = await repo.get_gate(OWNER, stage_id)
        r1_now = {r["ref_code"]: r for r in gate["requirements"]}["R-001"]
        check("re-approval restores it", r1_now["is_satisfied"])

        # The 0016 fix: withdrawing acceptance must not leave a live approval
        # that springs back when anyone re-confirms.
        await repo.set_acceptance(OWNER, r1["id"], confirmed=False)
        await repo.set_acceptance(CONTRIB, r1["id"], confirmed=True)
        gate = await repo.get_gate(OWNER, stage_id)
        r1_now = {r["ref_code"]: r for r in gate["requirements"]}["R-001"]
        check("withdrawing acceptance supersedes the approval too",
              not r1_now["is_satisfied"])
        check("re-confirming by someone else does not resurrect it",
              r1_now["status"] == "awaiting_approval", r1_now["status"])

        await repo.decide_requirement(APPROVER, r1["id"], decision="approved")

        # --------------------------------------------- 8. dependency ordering ---
        print("\n8. A prerequisite that is not satisfied blocks its dependant")

        await repo.set_assignment(OWNER, r2["id"], clear_owner=True)
        await repo.set_acceptance(OWNER, r2["id"], confirmed=True)
        await repo.decide_requirement(APPROVER, r2["id"], decision="approved")

        gate = await repo.get_gate(OWNER, stage_id)
        by_code = {r["ref_code"]: r for r in gate["requirements"]}
        check("R-002 satisfied once R-001 is", by_code["R-002"]["is_satisfied"])
        check("dependency is reported to the client",
              by_code["R-002"]["depends_on"] is not None
              and by_code["R-002"]["depends_on"][0]["ref_code"] == "R-001")

        # Blocking the prerequisite must take the dependant down with it.
        await repo.set_blocked(
            OWNER, r1["id"], blocked=True, reason="Awaiting a re-run of the search."
        )
        gate = await repo.get_gate(OWNER, stage_id)
        by_code = {r["ref_code"]: r for r in gate["requirements"]}
        check("blocking R-001 unsatisfies it", not by_code["R-001"]["is_satisfied"])
        check("...and cascades to its dependant R-002",
              not by_code["R-002"]["is_satisfied"])
        check("R-002 is reported as awaiting_dependency, not as its own failure",
              by_code["R-002"]["status"] == "awaiting_dependency",
              by_code["R-002"]["status"])
        await repo.set_blocked(OWNER, r1["id"], blocked=False, reason=None)

        # ----------------------------------------------- 9. the gate decision ---
        print("\n9. The gate: a percentage never unlocks it")

        # R-004 is a small mandatory sign-off that nothing depends on. With the
        # two heavy items done, the gate is 97% complete by weight and must
        # still refuse to open. This is the whole thesis of the module.
        gate = await repo.get_gate(OWNER, stage_id)
        pct = float(gate["readiness"]["readiness_pct"])
        check("percentage is high", pct >= 90.0, f"{pct}%")
        check("but is_ready is false", gate["readiness"]["is_ready"] is False)
        check("exactly one mandatory item outstanding",
              gate["readiness"]["blocker_count"] == 1,
              str(gate["readiness"]["blocker_count"]))

        ok, msg = await raises(
            Forbidden,
            repo.decide_gate(APPROVER, stage_id, decision="approved"),
        )
        check("approval authority is not gate authority", ok, msg[:60])

        ok, msg = await raises(
            Conflict,
            repo.decide_gate(GATEKEEPER, stage_id, decision="approved"),
        )
        check("gate approval refused at 97% with one item outstanding", ok, msg[:100])
        check("the refusal names the blocker", "R-004" in msg, msg[:100])

        ok, msg = await raises(
            Conflict,
            repo.decide_gate(GATEKEEPER, stage_id, decision="conditionally_approved"),
        )
        check("conditional approval requires written conditions", ok, msg[:60])

        stage_row = await repo.decide_gate(
            GATEKEEPER, stage_id, decision="conditionally_approved",
            note="Proceeding at risk.", conditions="R-004 sign-off within 14 days.",
        )
        check("conditional approval is allowed, with conditions",
              stage_row["gate_status"] == "conditionally_approved")

        recorded = await conn.fetchrow(
            """
            select new_value from public.audit_events
             where entity_id = $1 and action = 'pdp.gate.conditionally_approved'
          order by occurred_at desc limit 1
            """,
            stage_id,
        )
        outstanding = recorded["new_value"]["outstanding_blockers"]
        check("the outstanding blocker is written into the audit record",
              len(outstanding) == 1 and outstanding[0]["ref_code"] == "R-004",
              str(len(outstanding)))
        check("...along with the readiness it was granted over",
              float(recorded["new_value"]["readiness_pct"]) >= 90.0,
              str(recorded["new_value"]["readiness_pct"]))

        # Satisfy the last mandatory item and confirm a clean approval opens.
        await repo.attach_evidence(
            OWNER, r4["id"], evidence_type="note", note="QA sign-off recorded."
        )
        await repo.set_acceptance(OWNER, r4["id"], confirmed=True)
        await repo.decide_requirement(APPROVER, r4["id"], decision="approved")
        gate = await repo.get_gate(OWNER, stage_id)
        check("gate is ready once nothing mandatory is outstanding",
              gate["readiness"]["is_ready"] is True,
              f"{gate['readiness']['readiness_pct']}%")
        check("the optional item is still unsatisfied",
              not {r["ref_code"]: r for r in gate["requirements"]}["R-003"]["is_satisfied"])
        check("...so readiness is under 100 while is_ready is true",
              float(gate["readiness"]["readiness_pct"]) < 100.0,
              f"{gate['readiness']['readiness_pct']}%")

        stage_row = await repo.decide_gate(
            GATEKEEPER, stage_id, decision="approved", note="Gate 1 passed."
        )
        check("gate approved", stage_row["gate_status"] == "approved")

        # --------------------------------------------------- 10. scoping out ---
        print("\n10. Scoping requirements out")

        ok, msg = await raises(
            Conflict,
            repo.set_not_applicable(
                APPROVER, r1["id"], not_applicable=True, reason="Not needed."
            ),
        )
        check("a mandatory requirement cannot be marked N/A", ok, msg[:70])

        ok, msg = await raises(
            Forbidden,
            repo.set_not_applicable(
                CONTRIB, r3["id"], not_applicable=True, reason="Out of scope."
            ),
        )
        check("scoping out needs approval authority", ok, msg[:60])

        na = await repo.set_not_applicable(
            APPROVER, r3["id"], not_applicable=True,
            reason="Superseded by the platform assessment.",
        )
        check("an optional requirement may be scoped out with a reason",
              na["status"] == "not_applicable", na["status"])

        # ------------------------------------------- 11. retroactive SoD hole ---
        print("\n11. Ownership cannot be used to launder an approval")

        ok, msg = await raises(
            Conflict,
            repo.set_assignment(OWNER, r1["id"], owner_user_id=APPROVER),
        )
        check("cannot make the approver the owner of what they approved",
              ok, msg[:70])

        # ----------------------------------------------------- 12. the record ---
        print("\n12. Everything above left an audit trail")

        events = await repo.project_audit(OWNER, PROJECT, limit=500)
        actions = [e["action"] for e in events]
        for expected in (
            "pdp.project.instantiated",
            "pdp.evidence.attached",
            "pdp.requirement.acceptance_confirmed",
            "pdp.requirement.approved",
            "pdp.requirement.blocked",
            "pdp.gate.conditionally_approved",
            "pdp.gate.approved",
            "pdp.requirement.scoped_out",
        ):
            check(f"recorded: {expected}", expected in actions)

        check("every event names an actor",
              all(e["actor_user_id"] is not None for e in events))
        check("audit is still append-only",
              await mutation_refused(conn), "update refused")

        # ---------------------------------------------- 13. no completion API ---
        print("\n13. The shortcut does not exist")
        column = await conn.fetchval(
            """
            select count(*) from information_schema.columns
             where table_schema = 'public' and table_name = 'gate_requirements'
               and column_name in ('is_complete','completed','status','is_satisfied')
            """
        )
        check("gate_requirements still has no completion column", column == 0)

        writable = [
            m for m in dir(PdpRepository)
            if not m.startswith("_") and ("complete" in m or "satisf" in m)
        ]
        check("the repository exposes no completion method", not writable, str(writable))

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n{'=' * 62}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'=' * 62}")
    return 1 if failed else 0


async def mutation_refused(conn) -> bool:
    """UPDATE on audit_events must still fail."""
    sp = conn.transaction()
    await sp.start()
    try:
        await conn.execute("update public.audit_events set reason = 'tampered'")
    except asyncpg.PostgresError:
        await sp.rollback()
        return True
    await sp.rollback()
    return False


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
