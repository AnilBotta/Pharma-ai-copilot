"""Phase F: the notification rules engine, against the live database.

Every earlier phase guarded against a state that looks better than it is. This
one guards against something subtler — a system that reports everything, which
produces the same outcome as a system that reports nothing while looking like
coverage. People stop reading, and the one alert that mattered arrives in a
stream of forty that did not.

So the assertions here are mostly about restraint: that a condition true for six
weeks raises one event and not forty-two, that an alert dies when its problem is
fixed, and that escalation cannot cascade the moment nobody happens to be
looking.

    python tests/db/test_notifications.py
"""

import asyncio
import pathlib
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

OWNER = "eb000000-0000-0000-0000-000000000001"
APPROVER = "eb000000-0000-0000-0000-000000000002"
PROJECT = "eb100000-0000-0000-0000-000000000001"
STAGE = "eb200000-0000-0000-0000-000000000001"
REQ = "eb300000-0000-0000-0000-000000000001"
TASK = "eb400000-0000-0000-0000-000000000001"

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


class _Acquire:
    """Hands `dispatch_pending` the one connection this suite's transaction owns."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def sweep(conn):
    return await conn.fetchrow("select * from private.sweep_notifications($1)", PROJECT)


async def open_events(conn):
    return await conn.fetch(
        """
        select e.*, r.condition
          from public.notification_events e
          join public.notification_rules r on r.id = e.rule_id
         where e.project_id = $1 and e.resolved_at is null
      order by r.condition
        """,
        PROJECT,
    )


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (OWNER, "nt-owner@test.local"), (APPROVER, "nt-approver@test.local")
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
            "values ($1,$2,'Notify Test', true)",
            PROJECT, OWNER,
        )
        await conn.execute(
            "insert into public.project_stages (id, project_id, position, key, name) "
            "values ($1,$2,0,'gate_1','Gate 1')",
            STAGE, PROJECT,
        )
        # Overdue by a fortnight, mandatory, unsatisfied.
        await conn.execute(
            """
            insert into public.gate_requirements
              (id, project_id, project_stage_id, position, ref_code, title,
               is_mandatory, weight, required_evidence_type, owner_user_id, due_date)
            values ($1,$2,$3,0,'N-001','Stability protocol',true,10,'any',$4,$5)
            """,
            REQ, PROJECT, STAGE, OWNER, TODAY - timedelta(days=14),
        )
        # A task overdue by 10 days (rule threshold is 3).
        await conn.execute(
            """
            insert into public.project_tasks
              (id, project_id, title, forecast_start, forecast_end, owner_user_id)
            values ($1,$2,'Write the protocol',$3,$4,$5)
            """,
            TASK, PROJECT, TODAY - timedelta(days=20), TODAY - timedelta(days=10), OWNER,
        )

        # ------------------------------------------------- 1. detection ---
        print("\n1. Conditions are detected from the record")

        conditions = await conn.fetch(
            "select * from private.detect_notification_conditions($1)", PROJECT
        )
        found = {c["condition"] for c in conditions}
        check("the overdue requirement is detected", "requirement_overdue" in found)
        check("the overdue task is detected", "task_overdue" in found, str(sorted(found)))

        # -------------------------------------- 2. THE DEDUPLICATION RULE ---
        print("\n2. A condition true for weeks raises ONE event")

        first = await sweep(conn)
        check("the first sweep raises them", first["raised"] >= 2, f"{first['raised']}")

        second = await sweep(conn)
        third = await sweep(conn)
        check(
            "sweeping again raises nothing",
            second["raised"] == 0 and third["raised"] == 0,
            f"{second['raised']}, {third['raised']}",
        )

        events = await open_events(conn)
        overdue = [e for e in events if e["condition"] == "requirement_overdue"]
        check(
            "ONE open event for the requirement, not three",
            len(overdue) == 1,
            f"{len(overdue)} after three sweeps",
        )
        check("nothing was resolved spuriously", second["resolved"] == 0)

        # The index, not the code, is what guarantees it. Inside a savepoint:
        # a failed statement otherwise aborts the whole transaction and poisons
        # every assertion after it.
        sp = conn.transaction()
        await sp.start()
        duplicate_refused = False
        try:
            await conn.execute(
                """
                insert into public.notification_events
                  (rule_id, project_id, subject_type, subject_id, severity, title,
                   dedup_key)
                select rule_id, project_id, subject_type, subject_id, severity,
                       title, dedup_key
                  from public.notification_events where id = $1
                """,
                overdue[0]["id"],
            )
        except asyncpg.UniqueViolationError:
            duplicate_refused = True
        finally:
            await sp.rollback()
        check("a duplicate is refused by the database", duplicate_refused, "unique index")

        # ------------------------------------------ 3. AUTO-RESOLUTION ---
        print("\n3. Fixing the problem closes the alert")

        await conn.execute(
            "update public.project_tasks set actual_start = $2, actual_end = $3 "
            "where id = $1",
            TASK, TODAY - timedelta(days=20), TODAY,
        )
        after = await sweep(conn)
        check("completing the task resolves its alert", after["resolved"] >= 1,
              f"{after['resolved']} resolved")

        still_open = {e["condition"] for e in await open_events(conn)}
        check("the task alert is gone", "task_overdue" not in still_open)
        check("the requirement alert remains", "requirement_overdue" in still_open,
              "its condition is still true")

        resolved_row = await conn.fetchrow(
            """
            select resolved_reason from public.notification_events
             where project_id = $1 and resolved_at is not null limit 1
            """,
            PROJECT,
        )
        check("and says why it closed", resolved_row["resolved_reason"] is not None,
              resolved_row["resolved_reason"])

        # ------------------------------------------------ 4. escalation ---
        print("\n4. Escalation waits, and climbs one rung")

        escalated_now = await conn.fetchval("select private.escalate_notifications()")
        check(
            "a fresh alert does not escalate immediately",
            escalated_now == 0,
            "the rule requires 72 hours to pass first",
        )

        # Age it past the rule's window.
        await conn.execute(
            "update public.notification_events set raised_at = now() - interval '5 days' "
            "where project_id = $1 and resolved_at is null",
            PROJECT,
        )
        first_climb = await conn.fetchval("select private.escalate_notifications()")
        check("an aged, unacknowledged alert escalates", first_climb >= 1,
              f"{first_climb}")

        second_climb = await conn.fetchval("select private.escalate_notifications()")
        check(
            "but only one rung — it does not keep climbing",
            second_climb == 0,
            "a ladder that climbs itself puts everyone on every notification",
        )

        level = await conn.fetchval(
            "select max(escalation_level) from public.notification_events "
            "where project_id = $1 and resolved_at is null",
            PROJECT,
        )
        check("escalation level recorded", level == 1, str(level))

        # ----------------------------------- 5. acknowledgement stops it ---
        print("\n5. Acknowledging stops the ladder")

        await conn.execute(
            "update public.notification_events "
            "   set acknowledged_by = $2, acknowledged_at = now(), "
            "       escalation_level = 0, raised_at = now() - interval '10 days' "
            " where project_id = $1 and resolved_at is null",
            PROJECT, APPROVER,
        )
        after_ack = await conn.fetchval("select private.escalate_notifications()")
        check("an acknowledged alert does not escalate", after_ack == 0,
              "somebody is already on it")

        # ------------------------------- 6. the Phase D gap, now covered ---
        print("\n6. A lapsing document is warned about before it lapses")

        doc = await conn.fetchval(
            """
            insert into public.controlled_documents
              (project_id, document_number, title, document_type, owner_user_id)
            values ($1,'NT-SPEC-001','Stability specification','specification',$2)
            returning id
            """,
            PROJECT, OWNER,
        )
        version = await conn.fetchval(
            """
            insert into public.controlled_document_versions
              (document_id, version_label, status, storage_url, approved_by,
               approved_at, expiry_date)
            values ($1,'1.0','effective','https://example.test/spec',$2,now(),$3)
            returning id
            """,
            doc, APPROVER, TODAY + timedelta(days=10),
        )
        await conn.execute(
            """
            insert into public.evidence_links
              (requirement_id, project_id, evidence_type, document_version_id, added_by)
            values ($1,$2,'document',$3,$4)
            """,
            REQ, PROJECT, version, OWNER,
        )

        conditions = await conn.fetch(
            "select * from private.detect_notification_conditions($1)", PROJECT
        )
        expiring = [c for c in conditions if c["condition"] == "document_expiring"]
        check(
            "an expiring document raises a warning BEFORE it lapses",
            len(expiring) == 1,
            expiring[0]["title"] if expiring else "not detected",
        )
        check(
            "and explains the consequence",
            "stop being satisfied" in (expiring[0]["detail"] if expiring else ""),
            "requirements relying on it will stop being satisfied",
        )

        # Push it past expiry: the warning should become the harder alert.
        await conn.execute(
            "update public.controlled_document_versions set expiry_date = $2 "
            "where id = $1",
            version, TODAY - timedelta(days=1),
        )
        conditions = await conn.fetch(
            "select * from private.detect_notification_conditions($1)", PROJECT
        )
        found = {c["condition"] for c in conditions}
        check("once lapsed it becomes a critical alert",
              "document_expired_in_use" in found)
        check("and the pre-expiry warning stops firing",
              "document_expiring" not in found,
              "one condition at a time, not both")

        await sweep(conn)
        severities = await conn.fetch(
            """
            select e.severity, r.condition
              from public.notification_events e
              join public.notification_rules r on r.id = e.rule_id
             where e.project_id = $1 and e.resolved_at is null
            """,
            PROJECT,
        )
        lapsed = [s for s in severities if s["condition"] == "document_expired_in_use"]
        check("raised as critical", lapsed and lapsed[0]["severity"] == "critical",
              lapsed[0]["severity"] if lapsed else "missing")

        # ------------------------------------------------ 7. idempotence ---
        print("\n7. The sweep is safe to run every minute")

        before = len(await open_events(conn))
        for _ in range(5):
            await sweep(conn)
        after_count = len(await open_events(conn))
        check(
            "five more sweeps change nothing",
            before == after_count,
            f"{before} open events, unchanged",
        )

        # -------------------------------- 8. delivery, and the skipped trap ---
        #
        # This path had no test, which is how the bug below survived to
        # production: 44 deliveries recorded, every one `skipped` because no
        # email provider was configured, and every one permanently
        # undeliverable - because the "already told them" check excluded any
        # delivery row regardless of whether anything was actually sent.
        #
        # A table full of deliveries that never happened reads as coverage.
        print("\n8. A delivery that never left the building is not a delivery")

        from app.notifications import LoggingNotifier, dispatch_pending

        class Pool:
            def acquire(self):
                return _Acquire(conn)

        class Recording:
            """A notifier that is NOT LoggingNotifier, so sends are real."""

            def __init__(self) -> None:
                self.sent: list[str] = []
                self.bodies: list[str] = []

            async def send(self, *, to: str, subject: str, body: str) -> None:
                self.sent.append(to)
                self.bodies.append(body)

        # Give the project manager somebody to be.
        await conn.execute(
            """
            insert into public.user_roles (user_id, role_id, project_id)
            select $1, r.id, $2 from public.roles r where r.key = 'project_manager'
            on conflict do nothing
            """,
            APPROVER, PROJECT,
        )

        first = await dispatch_pending(Pool(), LoggingNotifier())
        check(
            "with no provider, deliveries are recorded as skipped",
            first["skipped"] > 0 and first["sent"] == 0,
            f"{first}",
        )
        rows = await conn.fetch(
            "select status, error from public.notification_deliveries "
            "where recipient_user_id = $1", APPROVER,
        )
        check(
            "and the row says so rather than claiming success",
            bool(rows) and all(r["status"] == "skipped" for r in rows),
            f"{len(rows)} row(s)",
        )

        # The whole point: configure a provider later and the backlog goes out.
        recording = Recording()
        second = await dispatch_pending(
            Pool(), recording, base_url="https://app.test"
        )
        check(
            "a provider arriving later DELIVERS the skipped backlog",
            second["sent"] > 0,
            f"sent {second['sent']}",
        )

        # An alert that names something and offers no route to it is noise.
        # This exercises the SQL rather than the formatting: subject_type has to
        # survive the audience query, and for a requirement the gate has to be
        # resolved by the sub-select.
        #
        # Which alerts are still open here depends on what earlier sections
        # resolved, so this asserts the property that holds for all of them
        # rather than naming one. The per-subject routing is pinned in
        # tests/test_config.py, where the row can be constructed directly.
        check(
            "every email carries a link",
            bool(recording.bodies)
            and all("https://app.test/programmes/" in b for b in recording.bodies),
            f"{sum('https://app.test/programmes/' in b for b in recording.bodies)}"
            f" of {len(recording.bodies)}",
        )
        specific = [
            b for b in recording.bodies
            if any(p in b for p in ("/gates/", "/schedule", "/documents"))
        ]
        check(
            "and it points at the page that deals with it, not just the programme",
            len(specific) == len(recording.bodies),
            f"{len(specific)} of {len(recording.bodies)} are subject-specific",
        )
        check(
            "and the notifier actually received them",
            len(recording.sent) == second["sent"],
            f"{len(recording.sent)} message(s)",
        )
        rows = await conn.fetch(
            "select status from public.notification_deliveries "
            "where recipient_user_id = $1", APPROVER,
        )
        check(
            "the skipped rows became sent rather than duplicating",
            bool(rows) and all(r["status"] == "sent" for r in rows),
            f"{len(rows)} row(s), statuses {sorted({r['status'] for r in rows})}",
        )

        # ...and the original guarantee still holds.
        third = await dispatch_pending(Pool(), Recording())
        check(
            "a real delivery is never repeated",
            third["sent"] == 0 and third["considered"] == 0,
            f"{third}",
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
