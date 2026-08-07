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
3. document evidence is on an approved or effective version that is still in date
4. the acceptance criteria were explicitly confirmed by a person
5. a current, non-superseded approval exists
6. the approver was neither the owner nor the acceptance confirmer
7. every mandatory prerequisite is itself satisfied

Condition 3 was a comment describing an intention until Phase D. There was no
register to check against, so a requirement stayed satisfied indefinitely after
the document behind it was replaced — the exact false green this module exists to
prevent, live in the system for three phases. Migration 0019 made it code.

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

---

## The controlled document register

37 of the 50 seeded mandatory requirements demand document evidence, so until
this existed no gate could reach `is_ready` at all.

**Files are not stored here.** Each version records a **link** to the file of
record — SharePoint, or wherever the organisation already controls it — plus the
metadata a gate decision depends on: version label, status, effective and expiry
dates, who approved it, and an optional checksum. Copying the bytes would create
a second authoritative copy, and the day two authoritative copies disagree,
nobody can say which one the gate was approved against.

It is deliberately **not** the existing `documents` table, which holds uploads
for retrieval — mime types, byte counts, embeddings. Different object, different
name.

### The lifecycle

```
draft → in_review → approved → effective → superseded → obsolete
```

Only **approved** and **effective** may support a requirement, and only while
still within any expiry date. An approved-but-expired version fails, which is
the case a status label alone would hide. At most one version per document may
be effective at a time, enforced by a partial unique index.

Marking a version `approved` or `effective` requires approval authority — those
words assert that review happened.

### Superseding is the whole point

Recording a new version and superseding its predecessor happens in one call, so
the register is never briefly showing two effective versions or none. When it
does:

- the old version stops being usable, so **every requirement citing it stops
  being satisfied**;
- the approvals that rested on it are **invalidated by trigger** — otherwise the
  requirement would spring back green the moment the new version was attached,
  approved on paper by someone who never saw it;
- the gate lists it as a blocker reading *"The document version cited is not
  approved, effective and in date. Attach the current version."*

Evidence links use `ON DELETE RESTRICT`, not cascade: deleting a version a gate
decision was based on fails loudly rather than quietly erasing the evidence
behind an approval.

---

## The schedule: a date that cannot be quietly moved

A project tool's characteristic lie is not a wrong date. It is a **moved** date.
A task slips, someone edits the plan, and the programme reports on schedule
right up until it finishes a year late. Every individual edit looked reasonable,
and the record of what was originally promised is gone.

That is this module's false green wearing a different hat, so it gets the same
treatment.

| | |
|---|---|
| **Baseline** | The commitment. **Immutable** once approved — the trigger refuses the `UPDATE`, and no request model has a field for it |
| **Forecast** | The current plan. Moves freely; that is what it is for |
| **Actual** | What happened |
| **Variance** | `forecast − baseline`, computed. Not stored, so not editable |

Re-baselining is a separate act requiring **approval authority and a stated
reason**. Every previous baseline is kept with a snapshot of the dates it
replaced, so *"what did we commit to in March"* stays answerable after the plan
has moved three times.

### No percent complete, and no status column

`project_tasks` has neither — for the same reason `gate_requirements` has no
completion column. A percentage anyone can type is the notorious task that is
90% done for eight months. State is derived from three facts that are either
true or not: has it started, has it finished, is it past its forecast.

```
not_started · waiting_on_predecessor · late_to_start
in_progress · overdue · blocked · complete
```

### Float and the critical path

Float is how much a task can slip before the project end moves; zero float means
it is on the critical path. Computed backwards from the latest forecast finish
through the dependency graph, which the cycle trigger keeps acyclic — a cycle
would make the calculation non-terminating.

---

## The agents, and why they are safe

The PDP Operations Agent reads a gate and says what is actually holding it up.
The Manager Agent reports across the portfolio. Neither can approve anything.

**The guarantee does not live in the tool schema.** That would be a promise
about one file, lasting until somebody adds a convenience wrapper, or a model
composes two permitted calls into a forbidden one, or an agent is handed a
user's session so it can "just finish the paperwork".

It lives in the database. An agent marks itself for the life of its transaction,
and migration 0022 refuses three things while that mark is set:

- **approving a requirement** — the act the whole module is built around
- **deciding a gate** — even when readiness is 100% and no blockers remain
- **setting a baseline** — a machine committing an organisation to a date

Plus: an agent may not confirm its own `ai_assessment`, which is the human step
that assessment exists to prompt.

`AgentRepository` subclasses `PdpRepository` rather than wrapping it, so every
method the human path has, the agent path has too — with identical behaviour up
to the point where the database says no. There is no second implementation to
drift and no list of "agent-safe methods" to add to by mistake.

### An assessment may describe and doubt, not decide

`evidence_links.ai_assessment` has existed since Phase C precisely so a
machine's view has somewhere to live that is structurally not an approval. A
`CHECK` constraint now refuses four words — *approved, compliant, certified,
authorised* — which have no innocent reading in a gate pack.

Negative and hedged findings are deliberately unrestricted. An earlier draft
also banned "satisfies the requirement", and testing showed it refused *"does
not satisfy the requirement"* — the most useful kind of finding. A regex cannot
tell those apart, so phrase bans push the agent toward vaguer language.

### Handoff, not overreach

Scientific judgement is not this agent's job. When the outstanding question is
*"is this stability data adequate for a depot formulation"*, it records a
`handoff_question` for the Scientist Agent instead of answering. The two hold
different evidence standards, and conflating them would let a project-management
model make a formulation claim.

Every session records `requested_by` **NOT NULL**: an agent always acts on
somebody's behalf, and an action with no accountable person behind it is not
representable here.

---

## Notifications: the failure here is noise

Every earlier phase guards against a state that looks better than it is. This
one guards against something subtler — a system that reports everything, which
produces the same outcome as a system that reports nothing while **looking like
coverage**. People stop reading, and the one alert that mattered arrives in a
stream of forty that did not.

So the restraint is structural:

| | |
|---|---|
| **Deduplication** | A partial unique index on `dedup_key`. One open event per condition — a requirement overdue for six weeks raises one alert, not forty-two |
| **Auto-resolution** | An event closes when its condition stops being true. An alert that outlives its problem teaches people that alerts mean nothing |
| **Escalation** | Requires elapsed time since the previous rung and climbs exactly one. A ladder that climbs itself puts everyone on every notification |
| **Acknowledging ≠ resolving** | Acknowledging stops escalation. Only the condition ceasing to be true closes an alert — otherwise it would be a way to clear a problem from the list without fixing it |

### Detection is a query, not a trigger

Conditions are recomputed from the record on every sweep. Nothing accumulates in
a queue, so a missed trigger cannot leave a permanent hole, and running the
sweep five more times changes nothing.

**A notification is a pointer to state, never the state itself.** If mail is
down for a week nothing is lost: the gate still knows it is blocked. That is
also why a failed send marks one delivery row `failed` and moves on.

With no email provider configured, deliveries are recorded as `skipped` **with
the reason on the row** — the alternative would let an operator believe mail was
going out for months.

### What is detected

`requirement_overdue` · `requirement_awaiting_approval` · `document_expiring` ·
`document_expired_in_use` · `task_overdue` · `critical_task_slipping` ·
`gate_ready_for_review`

The two document rules close a hole Phase D left open: expiry was *enforced* but
silent, so a version could lapse and three requirements quietly stop being
satisfied with nobody told. `document_expiring` warns beforehand and says what
will happen.

`gate_ready_for_review` exists because not everything worth saying is bad news —
a gate that has become reviewable is exactly the thing that sits unnoticed for a
fortnight.

The sweep rides on the worker tick that already runs every minute, so it needs
no scheduler of its own.

---

## Approvals expire when what they described changes

An approval is a statement about one specific evidence set and one specific
claim. Three triggers keep it honest:

- **evidence changes** → approval superseded *(migration 0014)*
- **acceptance confirmation changes** → approval superseded *(migration 0016)*
- **the document version behind it is superseded or made obsolete** → approval
  superseded *(migration 0019)*

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
| `GET /projects/{id}/documents` | The register, plus organisation-wide documents |
| `POST /projects/{id}/documents` | Register a document; the number must be unique |
| `GET /documents/{id}` | One document and its full version history |
| `POST /documents/{id}/versions` | Add a version, optionally superseding its predecessor |
| `POST /document-versions/{id}/status` | Move a version through its lifecycle |
| `GET /projects/{id}/schedule` | Tasks, milestones, baselines, with status/variance/float derived |
| `POST /projects/{id}/tasks` | Add a task |
| `POST /tasks/{id}` | Move forecast and actual dates — **no baseline field exists** |
| `POST /tasks/{id}/dependencies` | Add a predecessor; cycles refused |
| `POST /projects/{id}/milestones` | Add a milestone |
| `POST /projects/{id}/baseline` | Re-baseline; `can_approve` and a reason required |
| `GET /projects/{id}/notifications` | Open alerts, most severe first |
| `POST /notifications/{id}/acknowledge` | Stop escalation — does **not** close the alert |
| `POST /stages/{id}/assess` | PDP Operations Agent: what is really blocking this gate |
| `POST /portfolio/summary` | Manager Agent: what across the portfolio needs a decision |
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

```bash
cd backend; .venv\Scripts\python.exe tests\db\test_document_register.py
```

```bash
cd backend; .venv\Scripts\python.exe tests\db\test_schedule.py
```

22, 75, 25 and 25 assertions, against the live database inside a transaction
that is rolled back. Each suite has one assertion the rest exists to support:

- **documents** — a satisfied requirement whose document is superseded goes
  **unsatisfied**, its approval is invalidated, and the gate says why;
- **schedule** — *"EDITING A BASELINE DATE IS REFUSED"*, while the forecast
  moves freely and the slip is computed rather than hidden. They are excluded from `pytest -q` — they are scripts
needing a real database, and letting a database outage abort the unit suite was
its own small disaster.

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) §1.2 for what is **not**
verified, including the browser UI beyond the sign-in wall.
