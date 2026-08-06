# PDP Operations & Stage-Gate Guardian

Tracks a product development programme across Gate 0–7: what each gate demands,
who owns it, what evidence exists, who approved it, and whether the gate may
actually be reviewed.

The research module answers **episodic** questions — ask, retrieve, report, done.
This one is **long-lived and transactional**: the same programme is worked on for
years by people who change roles. They share one `projects` table, which is what
lets a completed research run be attached as evidence against a gate requirement
instead of the two being separate applications behind one login.

---

## The one rule

**No false green.** A requirement cannot be marked complete because someone
ticked a box.

There is no box. `gate_requirements` has no completion column, no status column,
and no percentage column. Nothing in the API writes one, because there is nothing
to write to. Satisfaction is computed on every read by
`private.requirement_is_satisfied()` from seven conditions:

1. at least one evidence link exists
2. the evidence is of the required type
3. document evidence is on a current, non-superseded version *(Phase D)*
4. the acceptance criteria were explicitly confirmed by a person
5. a current, non-superseded approval exists
6. the approver was neither the owner nor the acceptance confirmer
7. every mandatory prerequisite is itself satisfied

This is the same shape as the research module's guarantee — a citation cannot
exist unless the source was retrieved — and holds for the same reason. **The
shortcut does not exist**, so nobody has to be trusted not to take it. That
applies equally to the PDP Operations Agent arriving in Phase G: it calls the
same endpoints a person does, and they refuse it for the same reasons.

---

## Two numbers, and only one of them decides

`gate_readiness()` returns a percentage **and** a boolean, and they answer
different questions.

| | Question | Authority |
|---|---|---|
| `readiness_pct` | How much of the work is done? | Informational |
| `is_ready` | May this gate be reviewed? | Dispositive |

A gate at **93.1 % with one unsatisfied mandatory requirement is Not Ready**, and
`POST /pdp/stages/{id}/gate-decision` with `approved` is refused — the refusal
names the outstanding requirements. Verified live.

The blocker list travels with the number everywhere:

- `gate_readiness()` and `gate_blockers()` are returned in one payload by
  `GET /pdp/stages/{id}`, so a client cannot fetch the percentage alone.
- `Readiness` in `schemas.py` and `lib/api.ts` makes `blocker_count` required,
  not optional.
- `<GateReadiness>` takes `readiness` **and** `blockers` as required props. There
  is no way to call it and render a bare percentage.

A number shown alone reads as "nearly done". That reading is what this module
exists to prevent, so preventing it is structural rather than a style rule.

**`conditionally_approved` stays available while blockers exist.** Removing it
would push people to fabricate a clean gate. It requires written conditions, and
the blocker list *as it stood at that moment* is written into the audit record —
so a conditional approval granted over three outstanding items remains readable
as exactly that, years later.

---

## Who may do what

Resolved by `private.user_capabilities(user, project)` — the same predicate the
RLS policies use, so the API and the database cannot drift.

| Capability | Comes from |
|---|---|
| see the project | owner, a project-scoped grant, or any portfolio-wide role |
| approve a requirement | any role with `can_approve` |
| decide a gate | any role with `can_gate` |
| instantiate a programme | project owner, `project_manager`, or `system_administrator` |

**Segregation of duties is a database trigger, not a convention.** The owner of a
requirement, and whoever confirmed its acceptance criteria, are both refused
approval at the point of insert. No code path — present or future, human or agent
— can route around it.

The corollary is worth stating plainly: **one person cannot complete a
requirement.** Whoever confirms acceptance is refused approval. A pilot needs at
least two accounts.

Reassigning ownership to the person who approved a requirement is also refused,
since it would leave the record showing a requirement approved by its own owner.

---

## Approvals expire when what they described changes

An approval is a statement about one specific evidence set and one specific
claim. Two triggers keep it honest:

- **evidence changes** → approval superseded *(migration 0014)*
- **acceptance confirmation changes** → approval superseded *(migration 0016)*

Without the first, a requirement could be approved and the document swapped
underneath it. Without the second, withdrawing acceptance left the approval live,
so re-confirming — possibly by a different person, against different criteria —
resurrected it, recording an approver as having agreed with a claim they never
saw.

---

## Endpoints

All under `/api/pdp`. Note what is absent: no `PATCH /requirements/{id}` taking a
status, no `/complete`, no way to write a percentage.

| | |
|---|---|
| `GET /templates` | Templates; only `active` ones may be instantiated |
| `GET /programmes` | PDP-enabled projects, with current-gate readiness |
| `POST /projects/{id}/instantiate` | Copy an approved template version into a project |
| `GET /projects/{id}` | Stage ladder with per-gate readiness |
| `GET /projects/{id}/attachable-runs` | **Completed** research runs, citable as evidence |
| `GET /projects/{id}/audit` | Append-only trail |
| `GET /stages/{id}` | Gate workspace: readiness, blockers, requirements, evidence |
| `POST /stages/{id}/gate-decision` | Human gate decision; `can_gate` required |
| `POST /requirements/{id}/evidence` | Attach; supersedes any approval |
| `DELETE /evidence/{id}` | Detach; supersedes any approval |
| `POST /requirements/{id}/acceptance` | Confirm or withdraw the doer's claim |
| `POST /requirements/{id}/decision` | Approve or reject; `can_approve` + SoD |
| `POST /requirements/{id}/review` | Independent review — a recommendation, never an approval |
| `POST /requirements/{id}/assignment` | Owner, due date, priority |
| `POST /requirements/{id}/block` | Block with a stated reason |
| `POST /requirements/{id}/not-applicable` | Scope out with a justification; mandatory items refused |

Every mutating endpoint returns the requirement **as the engine now sees it**,
not the row it wrote. Attaching evidence supersedes an approval, so the state
after a write is frequently not what the write alone would suggest.

---

## Instantiation copies, it does not reference

Template content is **copied** into `project_stages` and `gate_requirements`. A
later edit to the template cannot change what a gate demands halfway through a
programme. Each row keeps a pointer back to the template row it came from, so a
migration to a newer version can be offered and diffed — and accepted by a
person.

Only an **active** template may be instantiated, and the schema refuses to
activate one without a recorded human approval.

**The seeded Gate 0–7 content is scaffolding, not regulatory advice.** Which
requirements are genuinely mandatory for a given product is domain knowledge that
has to come from your scientific, quality and regulatory people. There is
deliberately no "approve" button — a button is how that review becomes a
formality.

---

## Setting up a pilot

These two actions have no HTTP endpoint on purpose. A self-service role grant
would let a user give themselves approval authority, which empties segregation of
duties of meaning.

```bash
cd backend; .venv\Scripts\python.exe -m app.pdp_admin list-templates
```

```bash
cd backend; .venv\Scripts\python.exe -m app.pdp_admin approve-template --key default_pdp --email you@example.com --note "Reviewed with QA and Regulatory."
```

```bash
cd backend; .venv\Scripts\python.exe -m app.pdp_admin grant-role --email you@example.com --role gate_committee_member
```

```bash
cd backend; .venv\Scripts\python.exe -m app.pdp_admin who --email you@example.com
```

Both actions write to `audit_events`. Roles are rows, so `list-templates` will
name the available role keys if you pass an unknown one.

---

## Verification

```bash
cd backend; .venv\Scripts\python.exe tests\db\test_readiness_engine.py
```

```bash
cd backend; .venv\Scripts\python.exe tests\db\test_phase_c_workflow.py
```

22 and 75 assertions respectively, against the live database inside a transaction
that is rolled back. They are excluded from `pytest -q` — they are scripts
needing a real database, and letting a database outage abort the unit suite was
its own small disaster.

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) §1.2 for what is **not**
verified, including the browser UI beyond the sign-in wall.
