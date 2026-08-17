# The Manager Agent

A conversational interface over the whole application. A director asks it
something; it reads the record, answers, and where it can help by doing
something, does it — or prepares it for a person to confirm.

This document exists twice over. It is written for a person, and it is also
**indexed by the agent itself**: `search_docs` splits every file in `docs/` at
its headings and searches them, so this is where the agent's answers about its
own rules come from. If it is wrong here, the agent is wrong to your face.

---

## What it can do, in four kinds

The distinction between these is not decoration. It is what the panel styles
from, what the four tool lists in `backend/app/manager/tools.py` enforce, and
what a reader needs in order to answer "what can this thing change".

### Reading the record — 16 tools

Programmes, gates, requirements, schedule, documents, notifications, the audit
trail, research runs and their reports, previous agent sessions, and who holds
a role on a programme.

Every read goes through `AgentRepository`, which runs under the **requesting
user's** identity. The agent cannot see a project its requester could not.

`get_blockers` returns every blocker across a whole programme in one call. It
exists because the first live run answered "which gates cannot open" by calling
`get_gate` eight times — once per gate — pulling back fifty requirements each to
use only the blockers. 38,687 tokens became 11,176.

### Dispatch: assessing a gate, starting a research run, sweeping alerts

`assess_gate` sends the PDP Operations Agent at one gate.
`start_research_run` queues a run. `sweep_notifications` recomputes alerts.

None is an accountable act; each is something the person asking could do from
the interface. Two spend money, and both limits live in code rather than in the
prompt, because an instruction not to spend is the kind a long enough
conversation talks its way past:

* a gate assessment is **refused past 120 seconds into a turn**, because it
  takes about a minute and being killed halfway means paying for nothing;
* **one research run per turn**, enforced before the call reaches the database.

### Changing the record: tasks, owners, due dates, documents, alerts

`create_task`, `update_task`, `add_task_dependency`, `create_milestone`,
`set_assignment`, `set_blocked`, `acknowledge_notification`, `create_document`.

The line is not "risky versus safe". It is: **does this change what the
readiness engine concludes, or is it an accountable act?** Everything here fails
both tests — reversible, not evidence, not a decision about whether a gate may
open.

Two of them are easy to get backwards, so the agent is told to say the
distinction out loud:

* **Acknowledging an alert is not resolving it.** It stops the alert
  escalating. Only the underlying condition ceasing to be true resolves it.
* **Registering a document is not adding one.** It creates the record. The
  document has no version, so it satisfies no requirement until a person adds an
  approved one.

Every one of these lands in `audit_events` with `actor_agent` set to `manager`,
so "the agent did this" is answerable from the record rather than from memory.

### Asking: proposing an act it may not take

`propose`, covering six acts the agent may not perform: approving a
requirement, deciding a gate, attaching evidence, adding a document version,
confirming acceptance criteria, and re-baselining a schedule.

One tool rather than six, deliberately. These are not six capabilities the
agent has. They are one capability — asking — applied to six acts it cannot
take.

---

## What it cannot do: approve a requirement, decide a gate, set a baseline

Migration `0022` refuses four acts whenever an agent is acting, by database
trigger, and the refusal holds **even when the agent is carrying the session of
someone who personally holds that authority**:

* approving a requirement
* deciding a gate
* setting a schedule baseline
* confirming its own `ai_assessment`

Attaching evidence is not on that list — the database permits it — but the
agent still cannot do it directly, because evidence supersedes existing
approvals and therefore moves what the readiness engine concludes. It goes
through `propose` instead.

The guarantee lives in the database rather than in the tool list on purpose. A
guarantee in a tool schema is a promise about one file, and it lasts until
somebody adds a convenience wrapper. A trigger survives that.

---

## How a proposal works

1. The agent writes one, recording **the state it reasoned from** — the evidence
   ids an approval rests on, who confirmed acceptance, whether the gate was
   ready, which baseline was current.
2. A card appears in the panel. Everything above the button is **fetched fresh
   from the record**, not taken from the proposal. The agent's rationale sits
   below it, smaller, labelled as the reason it was proposed.
3. If you confirm, the act executes **as you**, through the plain repository
   with no agent mark. The approval is attributed to you and every
   segregation-of-duties rule applies exactly as if you had used the form.

### Why a proposal can be refused

Because the premise moved. Between the agent writing it and you clicking, a
colleague can attach a document, withdraw an acceptance, or supersede the
specification the whole thing rested on. The proposal still *looks* right —
same words, same requirement — and confirming it would apply a judgement to a
state nobody judged.

So confirmation recomputes the premise and **refuses** if it changed, saying
what changed. The confirm button is then absent rather than disabled: a
disabled control invites hunting for the way round it.

Proposals also expire after 24 hours, for the same reason more bluntly stated.

### Why your own approval can still be refused

Because the flow is not a bypass. If you confirmed the acceptance criteria on a
requirement, you cannot approve it — a proposal does not change that, and
attempting it says:

> segregation of duties: whoever confirmed the acceptance criteria cannot also
> approve

That is the system working, not a bug in the agent.

---

## What it is told about numbers

The readiness engine computes two figures for every gate, and the agent is
instructed that the distinction between them is the most important thing in the
system:

| | |
|---|---|
| `readiness_pct` | informational. How much is done. |
| `is_ready` | dispositive. Whether the gate can open at all. |

A gate at 96% with one unsatisfied mandatory requirement is not nearly ready. It
is **not ready**. The agent is told never to present a percentage as progress
toward an outcome, never to average percentages across programmes, and to quote
both numbers if it quotes either.

---

## Cost and limits

A turn is bounded three ways: **8 tool round-trips**, a **240-second wall
clock** against the host's 300-second ceiling, and **120,000 tokens**.

Reaching any of them stops the turn and marks the answer **truncated** — stored
on the message, so it still says so after a reload. A partial answer presented
as complete is the failure this whole system is organised against.

Every turn's spend is recorded in `usage_records` with `purpose = 'manager_chat'`.
Typical measured costs:

| | |
|---|---|
| A portfolio question | ~$0.03 |
| A gate assessment dispatched to the Operations Agent | ~$0.04 |
| A research run | ~$0.50 and about nine minutes |

---

## Where the conversation lives

`manager_conversations` and `manager_messages`, server-side, private to one
user by row-level security.

Kept in the database rather than the browser because a proposal must be
traceable to the exchange that produced it. Tool calls are stored — they are
what make an answer checkable afterwards — but are **not replayed** to the
model, because feeding every historical tool result back would grow the cost of
a long thread without bound.
