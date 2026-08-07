"""Phase D: the controlled document register, against the live database.

The claim under test is the third of the readiness engine's seven conditions —
"any document evidence is on a current, non-superseded version". Until migration
0019 that condition was a comment describing an intention: there was no register
to check against, so a requirement stayed satisfied forever after the document
behind it was replaced. That is the exact shape of false green this module
exists to prevent, and it was live in the system for three phases.

Everything runs through PdpRepository — the code an HTTP request reaches — and
is rolled back afterwards.
"""

import asyncio
import pathlib
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.pdp.repository import (
    Conflict,
    Forbidden,
    PdpRepository,
)

OWNER = "e9000000-0000-0000-0000-000000000001"
APPROVER = "e9000000-0000-0000-0000-000000000002"
CONTRIB = "e9000000-0000-0000-0000-000000000003"
PROJECT = "e9100000-0000-0000-0000-000000000001"
STAGE = "e9200000-0000-0000-0000-000000000001"
REQ = "e9300000-0000-0000-0000-000000000001"

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
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def dsn() -> str:
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


async def satisfied(conn) -> bool:
    return await conn.fetchval("select private.requirement_is_satisfied($1)", REQ)


async def status_of(conn) -> str:
    return await conn.fetchval("select private.requirement_status($1)", REQ)


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)
    repo = PdpRepository(PoolShim(conn))

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (OWNER, "dr-owner@test.local"),
            (APPROVER, "dr-approver@test.local"),
            (CONTRIB, "dr-contrib@test.local"),
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
            "values ($1,$2,'Doc Register Test', true)",
            PROJECT, OWNER,
        )
        # After the project: user_roles carries a foreign key to it.
        for uid, role in ((APPROVER, "senior_scientist"), (CONTRIB, "scientist")):
            await conn.execute(
                """
                insert into public.user_roles (user_id, role_id, project_id)
                select $1, r.id, $3 from public.roles r where r.key = $2
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
            values ($1,$2,$3,0,'D-001','Development report',true,10,'document',$4)
            """,
            REQ, PROJECT, STAGE, OWNER,
        )

        # ------------------------------------------------ 1. the register ---
        print("\n1. Registering a document")

        doc = await repo.create_document(
            OWNER, PROJECT,
            document_number="FD-RPT-0001",
            title="Formulation development report",
            document_type="report",
        )
        check("document registered", doc["document_number"] == "FD-RPT-0001")

        ok, msg = await raises(
            Conflict,
            repo.create_document(
                OWNER, PROJECT, document_number="FD-RPT-0001",
                title="A different report", document_type="report",
            ),
        )
        check("a duplicate document number is refused", ok, msg[:70])

        # ------------------------------------------- 2. version authority ---
        print("\n2. Recording versions")

        ok, msg = await raises(
            Forbidden,
            repo.add_document_version(
                CONTRIB, doc["id"],
                version_label="1.0",
                storage_url="https://sharepoint.example/fd-rpt-0001-v1",
                status="effective",
            ),
        )
        check("marking a version effective needs approval authority", ok, msg[:70])

        draft = await repo.add_document_version(
            CONTRIB, doc["id"],
            version_label="0.1",
            storage_url="https://sharepoint.example/fd-rpt-0001-draft",
            status="draft",
        )
        check("anyone with access may record a draft", draft["status"] == "draft")
        check(
            "a draft is not usable as evidence",
            not await conn.fetchval(
                "select private.document_version_is_usable($1)", draft["id"]
            ),
        )

        v1 = await repo.add_document_version(
            APPROVER, doc["id"],
            version_label="1.0",
            storage_url="https://sharepoint.example/fd-rpt-0001-v1",
            status="effective",
            effective_date=date.today() - timedelta(days=30),
        )
        check("an approver may record an effective version", v1["status"] == "effective")
        check("it records who approved it", v1["approved_by"] is not None)
        check(
            "and it is usable",
            await conn.fetchval("select private.document_version_is_usable($1)", v1["id"]),
        )

        # ------------------------------------------- 3. attaching evidence ---
        print("\n3. Attaching a document as evidence")

        ok, msg = await raises(
            Conflict,
            repo.attach_evidence(
                OWNER, REQ, evidence_type="document", document_version_id=draft["id"]
            ),
        )
        check("a draft version is refused at attach time", ok, msg[:80])

        await repo.attach_evidence(
            OWNER, REQ, evidence_type="document", document_version_id=v1["id"],
            title="Formulation development report v1.0",
        )
        check("the effective version attaches", True)

        await repo.set_acceptance(OWNER, REQ, confirmed=True)
        await repo.decide_requirement(APPROVER, REQ, decision="approved")
        check("requirement is satisfied", await satisfied(conn))
        check("status reads approved", await status_of(conn) == "approved",
              await status_of(conn))

        # ---------------------------------- 4. THE POINT OF THE WHOLE PHASE ---
        print("\n4. Superseding the document pulls the requirement back down")
        print("   (condition 3 of the seven, unenforceable until now)")

        v2 = await repo.add_document_version(
            APPROVER, doc["id"],
            version_label="2.0",
            storage_url="https://sharepoint.example/fd-rpt-0001-v2",
            status="effective",
            supersedes_version_id=v1["id"],
        )
        check("version 2.0 recorded", v2["version_label"] == "2.0")

        v1_after = await conn.fetchrow(
            "select status, superseded_at, superseded_by_version_id "
            "from public.controlled_document_versions where id = $1",
            v1["id"],
        )
        check("1.0 was superseded", v1_after["status"] == "superseded")
        check("and points at its replacement",
              str(v1_after["superseded_by_version_id"]) == str(v2["id"]))
        check("1.0 is no longer usable",
              not await conn.fetchval(
                  "select private.document_version_is_usable($1)", v1["id"]))

        check(
            "THE REQUIREMENT IS NO LONGER SATISFIED",
            not await satisfied(conn),
            "it cites a superseded version",
        )
        check(
            "and says so actionably",
            await status_of(conn) == "superseded_document",
            await status_of(conn),
        )

        approval = await conn.fetchrow(
            "select superseded_at, superseded_reason from public.approvals "
            "where requirement_id = $1 order by approved_at desc limit 1",
            REQ,
        )
        check(
            "the approval that rested on it was invalidated",
            approval["superseded_at"] is not None,
            (approval["superseded_reason"] or "")[:60],
        )

        blockers = await conn.fetch("select * from private.gate_blockers($1)", STAGE)
        check(
            "the gate now lists it as a blocker with a usable reason",
            any("current version" in (b["reason"] or "") for b in blockers),
            blockers[0]["reason"][:70] if blockers else "no blockers",
        )

        # ------------------------------------------------ 5. and recovery ---
        print("\n5. Attaching the new version restores it")

        old_link = await conn.fetchval(
            "select id from public.evidence_links "
            "where requirement_id = $1 and document_version_id = $2",
            REQ, v1["id"],
        )
        await repo.detach_evidence(OWNER, str(old_link))
        await repo.attach_evidence(
            OWNER, REQ, evidence_type="document", document_version_id=v2["id"]
        )
        await repo.set_acceptance(OWNER, REQ, confirmed=True)
        await repo.decide_requirement(APPROVER, REQ, decision="approved")

        check("satisfied again on the current version", await satisfied(conn))
        check(
            "a fresh approval was required to get there",
            await conn.fetchval(
                "select count(*) from public.approvals where requirement_id = $1", REQ
            ) == 2,
        )

        # ------------------------------------------------- 6. expiry dates ---
        print("\n6. An in-date document is not the same as an approved one")

        expired = await repo.add_document_version(
            APPROVER, doc["id"],
            version_label="3.0-expired",
            storage_url="https://sharepoint.example/fd-rpt-0001-v3",
            status="approved",
            effective_date=date.today() - timedelta(days=400),
            expiry_date=date.today() - timedelta(days=1),
        )
        check(
            "an approved but expired version is not usable",
            not await conn.fetchval(
                "select private.document_version_is_usable($1)", expired["id"]
            ),
            "status says approved; the date says otherwise",
        )
        ok, msg = await raises(
            Conflict,
            repo.attach_evidence(
                OWNER, REQ, evidence_type="document",
                document_version_id=expired["id"],
            ),
        )
        check("and is refused as evidence", ok, msg[:80])

        # ------------------------------------------------ 7. integrity ---
        print("\n7. Evidence cannot be quietly orphaned")

        ok, msg = await raises(
            asyncpg.PostgresError,
            conn.execute(
                "delete from public.controlled_document_versions where id = $1",
                v2["id"],
            ),
        )
        check(
            "deleting a cited version is refused, not cascaded",
            ok,
            "ON DELETE RESTRICT",
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
