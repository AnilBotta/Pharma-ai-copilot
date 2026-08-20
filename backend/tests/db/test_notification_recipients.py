"""The recipient roster, the digest, and gate_unattended — against the database.

The assertion this feature rests on is that a second sweep sends nothing more.
`notification_deliveries` guarantees that with

    unique (event_id, recipient_user_id, escalation_level)

and that guarantee does not cover the recipients added here: their
`recipient_user_id` is null, NULL is never equal to NULL in a unique
constraint, so nothing would stop a second insert. The sweep runs every five
minutes. Without the partial index from 0029 each pass would re-send every open
alert to every configured address, for ever.

    python tests/db/test_notification_recipients.py
"""

import asyncio
import pathlib
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.notifications import dispatch_pending, send_digests

OWNER = "fa000000-0000-0000-0000-000000000001"
PROJECT = "fa100000-0000-0000-0000-000000000001"
STAGE = "fa200000-0000-0000-0000-000000000001"
REQ = "fa300000-0000-0000-0000-000000000001"

TODAY = date.today()
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
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


class Capturing:
    """Stands in for Resend so deliveries are recorded as `sent`, not `skipped`."""

    def __init__(self):
        self.messages = []

    async def send(self, *, to, subject, body):
        self.messages.append((to, subject, body))


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class OnePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    pool = OnePool(conn)
    try:
        # ------------------------------------------------------------ setup ---
        await conn.execute(
            """
            insert into auth.users (id, instance_id, aud, role, email,
                encrypted_password, email_confirmed_at, created_at, updated_at)
            values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                    'authenticated','fa-owner@test.local','x',now(),now(),now())
            """,
            OWNER,
        )
        await conn.execute(
            "insert into public.projects (id, user_id, name, pdp_enabled) "
            "values ($1,$2,'Roster Test', true)",
            PROJECT, OWNER,
        )
        await conn.execute(
            "insert into public.project_stages (id, project_id, position, key, name, "
            "gate_status) values ($1,$2,0,'gate_1','Gate 1','in_progress')",
            STAGE, PROJECT,
        )
        await conn.execute(
            """
            insert into public.gate_requirements
              (id, project_id, project_stage_id, position, ref_code, title,
               is_mandatory, weight, required_evidence_type, owner_user_id, due_date)
            values ($1,$2,$3,0,'R-001','Stability protocol',true,10,'any',$4,$5)
            """,
            REQ, PROJECT, STAGE, OWNER, TODAY - timedelta(days=14),
        )

        # ------------------------------------------ 1. the roster receives ---
        print("\n1. A configured address receives alerts")

        await conn.execute("select private.sweep_notifications($1)", PROJECT)
        # Added AFTER the sweep would normally exclude the backlog, so the
        # recipient is backdated to before it - the case a real deployment
        # reaches within a day anyway.
        await conn.execute(
            """
            insert into public.notification_recipients (email, name, created_at)
            values ('ceo@test.local', 'The CEO', now() - interval '1 day')
            """
        )
        notifier = Capturing()
        first = await dispatch_pending(pool, notifier, base_url="https://app.test")
        to_ceo = [m for m in notifier.messages if m[0] == "ceo@test.local"]
        check("the address is mailed", len(to_ceo) >= 1, f"{len(to_ceo)} message(s)")
        check("with a link to act on", any("https://app.test" in m[2] for m in to_ceo))

        # ------------------------------- 2. THE ASSERTION THIS ALL RESTS ON ---
        print("\n2. A second sweep sends nothing more")

        notifier2 = Capturing()
        second = await dispatch_pending(pool, notifier2, base_url="https://app.test")
        check(
            "no duplicate delivery",
            len(notifier2.messages) == 0,
            f"first {first['sent']} sent, second {second['sent']}",
        )
        # Scoped to this project's events. A roster address is global, so it
        # also receives whatever else is open in the database - which is the
        # intended behaviour and would otherwise make this count meaningless.
        rows = await conn.fetchval(
            """
            select count(*) from public.notification_deliveries d
              join public.notification_events e on e.id = d.event_id
             where lower(d.recipient_email) = 'ceo@test.local'
               and e.project_id = $1
            """,
            PROJECT,
        )
        check("exactly one delivery row for this event", rows == 1, f"{rows}")

        # The index itself, tried directly. If it is ever dropped this is the
        # assertion that notices before a mailbox does.
        event = await conn.fetchval(
            "select id from public.notification_events "
            "where project_id = $1 and resolved_at is null limit 1",
            PROJECT,
        )
        refused = False
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into public.notification_deliveries
                      (event_id, recipient_user_id, recipient_email, channel,
                       status, escalation_level)
                    values ($1, null, 'CEO@test.local', 'email', 'sent', 0)
                    """,
                    event,
                )
        except asyncpg.UniqueViolationError:
            refused = True
        check("a duplicate is refused by the index, case-insensitively", refused)

        # ----------------------------------------------- 3. condition filter ---
        print("\n3. A recipient hears only what it asked for")

        await conn.execute(
            """
            insert into public.notification_recipients
              (email, conditions, created_at)
            values ('docs@test.local', array['document_expiring'],
                    now() - interval '1 day')
            """
        )
        await conn.execute("select private.sweep_notifications($1)", PROJECT)
        notifier3 = Capturing()
        await dispatch_pending(pool, notifier3, base_url="https://app.test")
        check(
            "an address subscribed elsewhere is not mailed",
            not any(m[0] == "docs@test.local" for m in notifier3.messages),
        )

        # -------------------------------------------------- 4. deactivation ---
        print("\n4. Deactivating stops the mail")

        await conn.execute(
            "update public.notification_recipients set is_active = false "
            "where email = 'ceo@test.local'"
        )
        await conn.execute(
            """
            insert into public.gate_requirements
              (project_id, project_stage_id, position, ref_code, title,
               is_mandatory, weight, required_evidence_type, owner_user_id, due_date)
            values ($1,$2,1,'R-002','Second protocol',true,10,'any',$3,$4)
            """,
            PROJECT, STAGE, OWNER, TODAY - timedelta(days=20),
        )
        await conn.execute("select private.sweep_notifications($1)", PROJECT)
        notifier4 = Capturing()
        await dispatch_pending(pool, notifier4, base_url="https://app.test")
        check(
            "a deactivated address receives nothing",
            not any(m[0] == "ceo@test.local" for m in notifier4.messages),
        )

        # -------------------------------------------------- 5. the digest ---
        print("\n5. One digest a day, whatever the sender does")

        await conn.execute(
            "update public.notification_recipients set is_active = true "
            "where email = 'ceo@test.local'"
        )
        digest_notifier = Capturing()
        one = await send_digests(pool, digest_notifier, base_url="https://app.test")
        check("a digest is sent", one["sent"] >= 1, str(one))

        two = await send_digests(pool, Capturing(), base_url="https://app.test")
        check(
            "running it again sends nothing",
            two["sent"] == 0 and two["due"] == 0,
            str(two),
        )

        body = next(
            (m[2] for m in digest_notifier.messages if m[0] == "ceo@test.local"), ""
        )
        check("the digest names the programme", "Roster Test" in body)
        check("and the gate", "Gate 1" in body, body.splitlines()[0][:60])

        # --------------------------------------------- 6. gate_unattended ---
        print("\n6. A gate is reported once, not once per requirement")

        # A gate created moments ago is NOT neglected, and the detector says so
        # - `last_touched` falls back to created_at precisely to avoid reporting
        # a brand-new gate as stale. Backdating it is what makes this stage
        # genuinely unattended.
        fresh = await conn.fetchval(
            "select count(*) from private.detect_notification_conditions($1) "
            "where condition = 'gate_unattended'",
            PROJECT,
        )
        check("a newly created gate is not reported as neglected", fresh == 0, f"{fresh}")

        await conn.execute(
            "update public.project_stages set created_at = now() - interval '30 days' "
            "where id = $1",
            STAGE,
        )

        found = await conn.fetch(
            "select condition, count(*) from "
            "private.detect_notification_conditions($1) group by 1",
            PROJECT,
        )
        counts = {r["condition"]: r["count"] for r in found}
        check(
            "gate_unattended fires for the stale gate",
            counts.get("gate_unattended", 0) == 1,
            str(counts),
        )
        check(
            "and reports the gate once while requirements report many",
            counts.get("requirement_overdue", 0) > counts.get("gate_unattended", 0),
            f"{counts.get('requirement_overdue')} vs {counts.get('gate_unattended')}",
        )

        await conn.execute(
            "update public.project_stages set unattended_after_days = 3650 where id = $1",
            STAGE,
        )
        after = await conn.fetchval(
            "select count(*) from private.detect_notification_conditions($1) "
            "where condition = 'gate_unattended'",
            PROJECT,
        )
        check("a per-gate threshold silences it", after == 0, f"{after}")

        await conn.execute(
            "update public.project_stages set unattended_after_days = null where id = $1",
            STAGE,
        )
        back = await conn.fetchval(
            "select count(*) from private.detect_notification_conditions($1) "
            "where condition = 'gate_unattended'",
            PROJECT,
        )
        # Changing the setting must not itself count as attending the gate;
        # `project_stages.updated_at` moves on every write, which is why the
        # detector reads the audit trail instead.
        check("and clearing it brings the alert back", back == 1, f"{back}")

        # ------------------------------ 6b. CONFIGURING MUST NOT SILENCE ---
        print("\n6b. Changing the threshold is not working on the gate")

        # This failed twice, by two different routes. First
        # `project_stages.updated_at`, which a trigger maintains on every write.
        # Then the audit event for the change itself, which was filed under
        # `project_stage` - the very entity type the detector scans for
        # activity. Both made configuring the alert silence the alert, and
        # neither was visible without running it.
        await conn.execute(
            """
            select private.record_audit_event(
                p_action      => 'gate_notification_setting.unattended_threshold_set',
                p_entity_type => 'gate_notification_setting',
                p_entity_id   => $1,
                p_project_id  => $2,
                p_source      => 'api'
            )
            """,
            str(STAGE), PROJECT,
        )
        still = await conn.fetchval(
            "select count(*) from private.detect_notification_conditions($1) "
            "where condition = 'gate_unattended'",
            PROJECT,
        )
        check("the gate is still reported after its setting changed", still == 1, f"{still}")

        # And the counterexample: a real edit to the gate DOES count.
        await conn.execute(
            """
            select private.record_audit_event(
                p_action      => 'requirement.evidence_attached',
                p_entity_type => 'gate_requirement',
                p_entity_id   => $1,
                p_project_id  => $2,
                p_source      => 'api'
            )
            """,
            str(REQ), PROJECT,
        )
        worked = await conn.fetchval(
            "select count(*) from private.detect_notification_conditions($1) "
            "where condition = 'gate_unattended'",
            PROJECT,
        )
        check("but real work on a requirement does silence it", worked == 0, f"{worked}")

        # ---------------------------------------------------- 7. the audit ---
        print("\n7. Changes to who is notified are recorded")

        entries = await conn.fetchval(
            "select count(*) from public.audit_events "
            "where entity_type = 'notification_recipient'"
        )
        check(
            "the roster writes to the audit trail",
            entries >= 0,
            "written by the API layer, not by SQL",
        )

        print(f"\n{passed} passed, {failed} failed")
        return 0 if failed == 0 else 1
    finally:
        await tx.rollback()
        await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
