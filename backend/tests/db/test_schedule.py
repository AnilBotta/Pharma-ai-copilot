"""Phase E: tasks, dependencies and the frozen baseline.

A project tool's characteristic lie is not a wrong date. It is a date that was
moved: a task slips, someone edits the plan, and the programme reports on
schedule right up until it finishes a year late. Every individual edit looked
reasonable, and the record of what was originally promised is gone.

That is this module's false green wearing a different hat, so it gets the same
treatment — the shortcut is made structurally unavailable. These assertions are
what that claim rests on.

    python tests/db/test_schedule.py
"""

import asyncio
import pathlib
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

OWNER = "ea000000-0000-0000-0000-000000000001"
PROJECT = "ea100000-0000-0000-0000-000000000001"
T = {n: f"ea300000-0000-0000-0000-00000000000{n}" for n in range(1, 6)}

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


class Outcome:
    def __init__(self):
        self.rejected = False
        self.detail = ""


async def expect_failure(conn, coro, *exc_types):
    """Run something expected to fail, inside a savepoint.

    Postgres aborts the whole transaction on any statement error, so without
    this the first expected failure would poison every later assertion.
    """
    outcome = Outcome()
    sp = conn.transaction()
    await sp.start()
    try:
        await coro
    except exc_types as exc:
        outcome.rejected = True
        outcome.detail = str(exc).split("\n")[0][:70]
    finally:
        await sp.rollback()
    return outcome


def dsn() -> str:
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


async def status_of(conn, task_id) -> str:
    return await conn.fetchval("select private.task_status($1)", task_id)


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        await conn.execute(
            """
            insert into auth.users (id, instance_id, aud, role, email,
                encrypted_password, email_confirmed_at, created_at, updated_at)
            values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                    'authenticated','sched@test.local','x',now(),now(),now())
            """,
            OWNER,
        )
        await conn.execute(
            "insert into public.projects (id, user_id, name, pdp_enabled) "
            "values ($1,$2,'Schedule Test', true)",
            PROJECT, OWNER,
        )

        # A short chain: 1 -> 2 -> 3, plus 4 hanging off 1 with slack.
        specs = [
            (T[1], "Preformulation", TODAY, TODAY + timedelta(days=10)),
            (T[2], "Candidate selection", TODAY + timedelta(days=10), TODAY + timedelta(days=25)),
            (T[3], "Process definition", TODAY + timedelta(days=25), TODAY + timedelta(days=40)),
            (T[4], "Optional characterisation", TODAY, TODAY + timedelta(days=5)),
        ]
        for tid, title, start, end in specs:
            await conn.execute(
                """
                insert into public.project_tasks
                  (id, project_id, title, forecast_start, forecast_end, owner_user_id)
                values ($1,$2,$3,$4,$5,$6)
                """,
                tid, PROJECT, title, start, end, OWNER,
            )
        for pre, suc in ((T[1], T[2]), (T[2], T[3]), (T[1], T[4])):
            await conn.execute(
                "insert into public.task_dependencies (predecessor_id, successor_id) "
                "values ($1,$2)",
                pre, suc,
            )

        # -------------------------------------------------- 1. derived state ---
        print("\n1. Task state is derived, never stored")

        columns = await conn.fetch(
            "select column_name from information_schema.columns "
            "where table_name = 'project_tasks'"
        )
        names = {c["column_name"] for c in columns}
        check(
            "there is no percent_complete column",
            "percent_complete" not in names,
            "a percentage anyone can type is the 90%-for-eight-months lie",
        )
        check("there is no status column", "status" not in names)

        check("not started", await status_of(conn, T[1]) == "not_started",
              await status_of(conn, T[1]))
        check(
            "a successor is waiting, not merely unstarted",
            await status_of(conn, T[2]) == "waiting_on_predecessor",
            await status_of(conn, T[2]),
        )

        await conn.execute(
            "update public.project_tasks set actual_start = $2 where id = $1",
            T[1], TODAY,
        )
        check("in progress once started", await status_of(conn, T[1]) == "in_progress")

        # Both dates move: task_dates_ordered rightly refuses an end before a
        # start, so "overdue" has to be set up by shifting the whole window.
        await conn.execute(
            "update public.project_tasks "
            "   set forecast_start = $2, forecast_end = $3 where id = $1",
            T[1], TODAY - timedelta(days=5), TODAY - timedelta(days=1),
        )
        check("overdue once past its forecast", await status_of(conn, T[1]) == "overdue",
              await status_of(conn, T[1]))
        await conn.execute(
            "update public.project_tasks "
            "   set forecast_start = $2, forecast_end = $3 where id = $1",
            T[1], TODAY, TODAY + timedelta(days=10),
        )

        outcome = await expect_failure(
            conn,
            conn.execute(
                "update public.project_tasks set actual_end = $2 where id = $1",
                T[3], TODAY,
            ),
            asyncpg.PostgresError,
        )
        check("a task cannot finish without starting", outcome.rejected, outcome.detail)

        # ------------------------------------------------- 2. cycle refusal ---
        print("\n2. The dependency graph stays acyclic")

        outcome = await expect_failure(
            conn,
            conn.execute(
                "insert into public.task_dependencies (predecessor_id, successor_id) "
                "values ($1,$2)",
                T[3], T[1],
            ),
            asyncpg.PostgresError,
        )
        check("a cycle is refused at write time", outcome.rejected, outcome.detail)

        # ------------------------------------------------- 3. critical path ---
        print("\n3. Float and the critical path")

        rows = await conn.fetch("select * from private.task_float_days($1)", PROJECT)
        floats = {str(r["task_id"]): r for r in rows}
        check("every dated task got a float", len(rows) == 4, f"{len(rows)} rows")
        check(
            "the long chain is critical",
            all(floats[T[n]]["is_critical"] for n in (1, 2, 3)),
            "tasks 1-3",
        )
        check(
            "the short branch has slack",
            not floats[T[4]]["is_critical"],
            f"float {floats[T[4]]['float_days']} days",
        )

        # ------------------------------- 4. THE POINT: the frozen baseline ---
        print("\n4. A baseline cannot be quietly moved")

        # Before any baseline exists, the plan is still being drafted.
        await conn.execute(
            "update public.project_tasks set baseline_end = $2 where id = $1",
            T[1], TODAY + timedelta(days=10),
        )
        check("baselines are editable while nothing is committed", True)

        baseline_id = await conn.fetchval(
            "select private.rebaseline($1,$2,'Baseline 1','Initial commitment.')",
            PROJECT, OWNER,
        )
        check("a baseline was approved", baseline_id is not None)

        committed = await conn.fetchrow(
            "select baseline_start, baseline_end, forecast_end "
            "from public.project_tasks where id = $1",
            T[1],
        )
        check(
            "the forecast became the commitment",
            committed["baseline_end"] == committed["forecast_end"],
        )

        outcome = await expect_failure(
            conn,
            conn.execute(
                "update public.project_tasks set baseline_end = $2 where id = $1",
                T[1], TODAY + timedelta(days=90),
            ),
            asyncpg.PostgresError,
        )
        check(
            "EDITING A BASELINE DATE IS REFUSED",
            outcome.rejected,
            outcome.detail,
        )

        # The forecast is exactly what is allowed to move.
        await conn.execute(
            "update public.project_tasks set forecast_end = $2 where id = $1",
            T[1], TODAY + timedelta(days=25),
        )
        check("but the forecast moves freely", True)

        variance = await conn.fetchval("select private.task_variance_days($1)", T[1])
        check(
            "and the slip is computed, not hidden",
            variance == 15,
            f"{variance} days late against the commitment",
        )

        outcome = await expect_failure(
            conn,
            conn.fetchval(
                "select private.rebaseline($1,$2,'Baseline 2',null)", PROJECT, OWNER
            ),
            asyncpg.PostgresError,
        )
        check("re-baselining without a reason is refused", outcome.rejected,
              outcome.detail)

        # ------------------------------------------------- 5. history kept ---
        print("\n5. Re-baselining keeps what it replaced")

        second = await conn.fetchval(
            "select private.rebaseline($1,$2,'Baseline 2','Scope increased "
            "after the Gate 2 review.')",
            PROJECT, OWNER,
        )
        check("a second baseline was approved", second is not None)

        baselines = await conn.fetch(
            "select version, name, reason, superseded_at, snapshot "
            "from public.schedule_baselines where project_id = $1 order by version",
            PROJECT,
        )
        check("both baselines are kept", len(baselines) == 2, f"{len(baselines)}")
        check("the first is marked superseded", baselines[0]["superseded_at"] is not None)
        check("the second is current", baselines[1]["superseded_at"] is None)
        check(
            "the old commitment is still answerable",
            len(baselines[1]["snapshot"]) > 0,
            "snapshot captured before the dates moved",
        )
        check(
            "variance resets against the new commitment",
            await conn.fetchval("select private.task_variance_days($1)", T[1]) == 0,
        )

        current = await conn.fetchval(
            "select count(*) from public.schedule_baselines "
            "where project_id = $1 and superseded_at is null",
            PROJECT,
        )
        check("exactly one baseline is current", current == 1, str(current))

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n{'=' * 62}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'=' * 62}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
