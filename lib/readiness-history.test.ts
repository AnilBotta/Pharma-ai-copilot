import assert from "node:assert/strict";
import { test } from "node:test";

// Explicit extension: Node's native TypeScript stripping resolves this file
// as ESM, where the specifier is not rewritten for you.
import { buildReadinessHistory } from "./readiness-history.ts";
import type { AuditEntry } from "./api.ts";

/**
 * The reconstruction is the risky part of the chart, and it is pure, so it is
 * tested here rather than eyeballed in a browser. The cases that matter are
 * the ones where a naive running total drifts away from the engine.
 */

let seq = 0;
function ev(
  action: string,
  entityId: string,
  occurredAt: string,
  entityType = "gate_requirement"
): AuditEntry {
  return {
    id: ++seq,
    occurred_at: occurredAt,
    actor_user_id: null,
    actor_name: null,
    actor_role: null,
    actor_agent: null,
    action,
    entity_type: entityType,
    entity_id: entityId,
    previous_value: null,
    new_value: null,
    reason: null,
    source_channel: "ui",
  };
}

const NOW = Date.parse("2026-08-24T00:00:00Z");

test("REGRESSION: evidence on an unapproved requirement must not go negative", () => {
  // A +1/-1 counter reaches -1 here. Attaching evidence is the single most
  // common event in the log and most of it lands on unapproved requirements.
  const h = buildReadinessHistory(
    [
      ev("pdp.evidence.attached", "r1", "2026-08-01T10:00:00Z"),
      ev("pdp.evidence.attached", "r2", "2026-08-01T11:00:00Z"),
    ],
    0,
    NOW
  );
  assert.equal(h.reconstructed, 0);
  assert.ok(h.agrees, "should agree with an engine count of 0");
  assert.ok(
    h.points.every((p) => p.satisfied >= 0),
    "no point may be negative"
  );
});

test("REGRESSION: approving the same requirement twice counts once", () => {
  // The set is what makes this true; a counter would read 2.
  const h = buildReadinessHistory(
    [
      ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
      ev("pdp.requirement.approved", "r1", "2026-08-02T10:00:00Z"),
    ],
    1,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.ok(h.agrees);
});

test("an approval superseded by new evidence comes back off the count", () => {
  const h = buildReadinessHistory(
    [
      ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
      ev("pdp.requirement.approved", "r2", "2026-08-01T11:00:00Z"),
      ev("pdp.evidence.attached", "r1", "2026-08-03T09:00:00Z"),
    ],
    1,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.ok(h.agrees);
});

test("every event that supersedes an approval subtracts", () => {
  for (const action of [
    "pdp.requirement.rejected",
    "pdp.evidence.attached",
    "pdp.evidence.detached",
    "pdp.requirement.acceptance_withdrawn",
    "pdp.requirement.scoped_out",
  ]) {
    const h = buildReadinessHistory(
      [
        ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
        ev(action, "r1", "2026-08-02T10:00:00Z"),
      ],
      0,
      NOW
    );
    assert.equal(h.reconstructed, 0, `${action} did not subtract`);
  }
});

test("out-of-order rows are replayed in time order", () => {
  // The endpoint returns most-recent-first. Replaying in arrival order would
  // process the supersede before the approval and end at 1 instead of 0.
  const h = buildReadinessHistory(
    [
      ev("pdp.evidence.attached", "r1", "2026-08-02T10:00:00Z"),
      ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
    ],
    0,
    NOW
  );
  assert.equal(h.reconstructed, 0);
});

test("GUARD: the series always terminates on the engine's number", () => {
  // Even when the replay disagrees. The chart must never end somewhere the
  // page's own badge does not.
  const h = buildReadinessHistory(
    [ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z")],
    7,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.equal(h.engine, 7);
  assert.equal(h.agrees, false, "must report the disagreement");
  assert.equal(h.points.at(-1)?.satisfied, 7);
  assert.equal(h.points.at(-1)?.t, NOW);
});

test("gate decisions are collected separately, not counted as requirements", () => {
  const h = buildReadinessHistory(
    [
      ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
      ev("pdp.gate.approved", "s1", "2026-08-02T10:00:00Z", "project_stage"),
      ev(
        "pdp.gate.conditionally_approved",
        "s2",
        "2026-08-03T10:00:00Z",
        "project_stage"
      ),
    ],
    1,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.equal(h.gates.length, 2);
  assert.equal(h.gates[0].label, "Gate approved");
  assert.equal(h.gates[1].label, "Approved with conditions");
});

test("unrelated actions and entity types are ignored", () => {
  const h = buildReadinessHistory(
    [
      ev("pdp.requirement.approved", "r1", "2026-08-01T10:00:00Z"),
      ev("pdp.requirement.assigned", "r2", "2026-08-01T12:00:00Z"),
      ev("pdp.requirement.blocked", "r3", "2026-08-01T13:00:00Z"),
      ev("pdp.role.granted", "u1", "2026-08-01T14:00:00Z", "user_role"),
      // Same action, wrong entity type: must not touch the count.
      ev("pdp.requirement.approved", "x1", "2026-08-01T15:00:00Z", "project"),
    ],
    1,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.equal(h.relevant, 1, "only one event moved the line");
});

test("an unparseable timestamp is skipped rather than poisoning the axis", () => {
  const h = buildReadinessHistory(
    [
      ev("pdp.requirement.approved", "r1", "not a date"),
      ev("pdp.requirement.approved", "r2", "2026-08-01T10:00:00Z"),
    ],
    1,
    NOW
  );
  assert.equal(h.reconstructed, 1);
  assert.ok(
    h.points.every((p) => Number.isFinite(p.t)),
    "every point needs a real time"
  );
});

test("an empty log still produces a chart that ends at the engine", () => {
  const h = buildReadinessHistory([], 3, NOW);
  assert.equal(h.points.length, 1);
  assert.equal(h.points[0].satisfied, 3);
  assert.equal(h.agrees, false);
});
