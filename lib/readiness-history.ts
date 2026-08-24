import type { AuditEntry } from "@/lib/api";

/**
 * Requirements satisfied over time, reconstructed from the audit log.
 *
 * THE DANGER THIS MODULE IS BUILT AROUND
 *
 * There is no stored readiness timeseries. Any curve is a reconstruction, and
 * a reconstruction that disagreed with the readiness engine would put a rising
 * green line next to a "Not ready" badge — the single worst thing this product
 * can display. So three rules:
 *
 * 1. It counts requirements, never a percentage. A percentage invites the
 *    comparison with `readiness_pct` that must never be made loosely.
 * 2. It replays a SET of requirement ids, not a running total. `entity_id` is
 *    the requirement, so "approved twice, superseded once" resolves correctly.
 *    A +1/-1 counter drifts the moment an event arrives for a requirement that
 *    was not in the state the counter assumed.
 * 3. It is reconciled against the engine and SAYS SO when they disagree. The
 *    series is terminated with the engine's own current count, and `agrees`
 *    reports whether the replay landed there on its own.
 *
 * THE EVENT VOCABULARY IS DERIVED FROM THE WRITER, NOT FROM THE DATA
 *
 * Read off `PdpRepository`: `decide_requirement` writes
 * `pdp.requirement.{decision}` where DecisionRequest permits only "approved"
 * and "rejected"; evidence and acceptance changes each supersede a standing
 * approval, which is why they subtract.
 */

/** An approval starts here. */
const SATISFIES = "pdp.requirement.approved";

/**
 * These end one.
 *
 * Evidence and acceptance changes supersede a standing approval — the product
 * says so on the buttons that cause them ("Any approval was superseded"). A
 * scoped-out requirement stops being an applicable satisfied one.
 */
const UNSATISFIES = new Set([
  "pdp.requirement.rejected",
  "pdp.evidence.attached",
  "pdp.evidence.detached",
  "pdp.requirement.acceptance_withdrawn",
  "pdp.requirement.scoped_out",
]);

/** Gate decisions, drawn as reference lines. */
const GATE_DECISIONS: Record<string, string> = {
  "pdp.gate.approved": "Gate approved",
  "pdp.gate.conditionally_approved": "Approved with conditions",
  "pdp.gate.rejected": "Gate rejected",
  "pdp.gate.on_hold": "Gate put on hold",
};

export interface ReadinessPoint {
  /** Epoch ms — Recharts needs a number for a time axis. */
  t: number;
  satisfied: number;
}

export interface GateMark {
  t: number;
  label: string;
}

export interface ReadinessHistory {
  points: ReadinessPoint[];
  gates: GateMark[];
  /** Where the replay ended on its own. */
  reconstructed: number;
  /** What the engine says right now. The series is terminated here. */
  engine: number;
  /** Did the replay land on the engine's count without being told to? */
  agrees: boolean;
  /** How many audit rows were considered. Reported honestly in the caption. */
  events: number;
  /** How many of those actually moved the line. */
  relevant: number;
}

/**
 * @param audit  Audit rows, in any order. Sorted here.
 * @param engineSatisfied  The engine's CURRENT satisfied count. The series is
 *   terminated at this value so the chart cannot contradict the page it is on.
 * @param now  Injectable for tests.
 */
export function buildReadinessHistory(
  audit: AuditEntry[],
  engineSatisfied: number,
  now: number = Date.now()
): ReadinessHistory {
  const ordered = [...audit].sort(
    (a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at)
  );

  const satisfied = new Set<string>();
  const points: ReadinessPoint[] = [];
  const gates: GateMark[] = [];
  let relevant = 0;

  for (const entry of ordered) {
    const t = Date.parse(entry.occurred_at);
    if (Number.isNaN(t)) continue;

    const gateLabel = GATE_DECISIONS[entry.action];
    if (gateLabel) {
      gates.push({ t, label: gateLabel });
      continue;
    }

    if (entry.entity_type !== "gate_requirement") continue;

    const before = satisfied.size;
    if (entry.action === SATISFIES) {
      satisfied.add(entry.entity_id);
    } else if (UNSATISFIES.has(entry.action)) {
      // A no-op when the requirement was not satisfied, which is exactly what
      // makes this safe: evidence gets attached to unapproved requirements all
      // the time, and a counter would have gone negative on the first one.
      satisfied.delete(entry.entity_id);
    } else {
      continue;
    }

    if (satisfied.size !== before) {
      relevant += 1;
      points.push({ t, satisfied: satisfied.size });
    }
  }

  const reconstructed = satisfied.size;

  // Terminate on the engine's number. If the replay already agrees this adds a
  // flat segment to "now"; if it does not, the step is visible and `agrees`
  // is false so the caller can say why rather than let the reader guess.
  points.push({ t: now, satisfied: engineSatisfied });

  return {
    points,
    gates,
    reconstructed,
    engine: engineSatisfied,
    agrees: reconstructed === engineSatisfied,
    events: audit.length,
    relevant,
  };
}
