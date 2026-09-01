# Database-level tests

These exercise logic that lives **in Postgres** — RLS predicates, check
constraints, triggers and the readiness engine — so they need a real database
and are not part of the default `pytest` run.

They matter because the guarantees they cover are enforced in the database
precisely so that no application code path can route around them. Testing them
through mocks would test the mock.

## Running them

Requires `DATABASE_URL` in `backend/.env`:

```bash
cd backend; .venv\Scripts\python.exe tests\db\test_readiness_engine.py
```

Everything runs inside a transaction that is rolled back, so the database is
unchanged afterwards. Expected-failure cases use savepoints, because a failed
statement otherwise aborts the enclosing transaction and poisons every later
assertion.

## What `test_readiness_engine.py` proves

| # | Case |
|---|---|
| 1 | A fresh requirement is not satisfied |
| 2 | Evidence attached and accepted but **not approved** is not satisfied — the core no-false-green case |
| 3 | The **owner cannot approve their own work** (segregation of duties, enforced by trigger) |
| 4 | An independent approver satisfies it |
| 5 | **96.1 % readiness with `is_ready = false`** — a percentage never unlocks a gate |
| 6 | Wrong evidence type does not satisfy, and the status says so rather than blaming the approver |
| 7 | Changing evidence **supersedes an existing approval** — a document cannot be swapped under an approval |
| 8 | An unsatisfied mandatory prerequisite blocks its dependant |
| 9 | An explicit block overrides everything else |
| 10 | A block without a stated reason is rejected |
| 11 | A **mandatory** requirement cannot be waived as not-applicable |
| 12 | The gate stays not-ready while any mandatory blocker remains |

## What `test_human_review_persistence.py` proves

The acknowledgement rule is decision-dependent, and the schema enforces it
rather than trusting the API. This one applies migrations 0032 and 0034 inside
the rolled-back transaction, so it also proves both files are valid SQL.

| # | Case |
|---|---|
| A | An accepted review with a valid acknowledgement persists, storing the real text and hash |
| B | An acceptance with no acknowledgement is refused by the domain layer **and** by the constraint |
| C | A rejection with null acknowledgement fields persists — **the bug this file was written for** |
| D | A rejection carrying an acknowledgement is refused by the decision-dependent constraint |
| E | A rejection still requires non-empty notes, in both layers |
| F | A rejection needs none of the acceptance preconditions, so a broken run can always be closed out |

## Applying migrations

`scripts/apply_sql.py` executes a SQL file over a direct connection. Use it when
a migration is too large for the Supabase MCP tool, or when PowerShell's
`Set-Content` has added a UTF-8 BOM that Postgres rejects.

```bash
cd backend; .venv\Scripts\python.exe scripts\apply_sql.py ..\supabase\migrations\0014_readiness_engine.sql
```
