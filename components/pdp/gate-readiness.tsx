"use client";

import { AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react";

import { MandatoryPips } from "@/components/pdp/mandatory-pips";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { Blocker, Readiness } from "@/lib/api";

/**
 * Gate readiness, rendered as two numbers that answer different questions.
 *
 * The percentage says how much of the work is done. `is_ready` says whether the
 * gate may be reviewed at all, and it is the one that decides. A gate at 93%
 * with one unsatisfied mandatory requirement is Not Ready.
 *
 * The verdict and the blockers are not optional props. There is no way to call
 * this component and get a bare percentage, which is the point: a number shown
 * alone is read as "nearly done", and that reading is what this module exists
 * to prevent.
 */
export function GateReadiness({
  readiness,
  blockers,
  className,
  compact = false,
}: {
  readiness: Readiness;
  blockers: Blocker[];
  className?: string;
  compact?: boolean;
}) {
  const { readiness_pct, is_ready, blocker_count } = readiness;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums">
            {readiness_pct.toFixed(1)}%
          </span>
          <span className="text-xs text-muted-foreground">
            {readiness.satisfied_count} of {readiness.applicable_count} satisfied
          </span>
        </div>
        <ReadyVerdict isReady={is_ready} blockerCount={blocker_count} />
      </div>

      <Progress
        value={readiness_pct}
        // Amber while not ready, however high the number climbs. Green here
        // would contradict the verdict standing next to it.
        tone={is_ready ? "success" : "warning"}
        valueText={`${readiness_pct.toFixed(1)} percent, ${
          is_ready ? "ready for review" : `not ready, ${blocker_count} outstanding`
        }`}
      />

      {/* The dispositive quantity, drawn. The bar above is weighted across
          optional work and so can sit at 94% on a ready gate and 96% on one
          that is not; these pips are what actually decides it. */}
      <MandatoryPips
        satisfied={readiness.mandatory_satisfied}
        total={readiness.mandatory_count}
        isReady={is_ready}
      />

      {!is_ready && blockers.length > 0 && (
        <div className="rounded-lg border border-warning-border bg-warning-surface p-3">
          <p className="text-xs font-medium text-warning">
            {blocker_count} mandatory requirement{blocker_count === 1 ? "" : "s"} outstanding
          </p>
          <ul className="mt-2 space-y-1.5">
            {(compact ? blockers.slice(0, 3) : blockers).map((b) => (
              <li key={b.requirement_id} className="flex gap-2 text-xs">
                <span className="font-mono text-muted-foreground">{b.ref_code}</span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{b.title}</span>
                  <span className="text-muted-foreground"> — {b.reason}</span>
                </span>
              </li>
            ))}
          </ul>
          {compact && blockers.length > 3 && (
            <p className="mt-2 text-xs text-muted-foreground">
              and {blockers.length - 3} more
            </p>
          )}
        </div>
      )}

      {!is_ready && blockers.length === 0 && readiness.applicable_count === 0 && (
        <p className="text-xs text-muted-foreground">
          This gate has no applicable requirements, so there is nothing to be
          ready for.
        </p>
      )}
    </div>
  );
}

export function ReadyVerdict({
  isReady,
  blockerCount,
}: {
  isReady: boolean;
  blockerCount: number;
}) {
  if (isReady) {
    return (
      <Badge variant="success" className="gap-1.5">
        <CheckCircle2 className="size-3" />
        Ready for review
      </Badge>
    );
  }
  return (
    <Badge variant="warning" className="gap-1.5">
      <AlertTriangle className="size-3" />
      Not ready
      {blockerCount > 0 && ` · ${blockerCount}`}
    </Badge>
  );
}

const GATE_STATUS_LABELS: Record<string, { label: string; variant: BadgeVariant }> = {
  not_started: { label: "Not started", variant: "muted" },
  in_progress: { label: "In progress", variant: "info" },
  at_risk: { label: "At risk", variant: "warning" },
  ready_for_human_review: { label: "Ready for review", variant: "success" },
  approved: { label: "Approved", variant: "success" },
  conditionally_approved: { label: "Approved with conditions", variant: "warning" },
  rejected: { label: "Rejected", variant: "destructive" },
  on_hold: { label: "On hold", variant: "muted" },
};

export function GateStatusBadge({ status }: { status: string }) {
  const entry = GATE_STATUS_LABELS[status] ?? { label: status, variant: "muted" as const };
  return <Badge variant={entry.variant}>{entry.label}</Badge>;
}

const REQUIREMENT_STATUS: Record<string, { label: string; variant: BadgeVariant }> = {
  approved: { label: "Satisfied", variant: "success" },
  not_started: { label: "Not started", variant: "muted" },
  in_progress: { label: "In progress", variant: "info" },
  overdue: { label: "Overdue", variant: "destructive" },
  awaiting_acceptance: { label: "Awaiting acceptance", variant: "info" },
  awaiting_approval: { label: "Awaiting approval", variant: "warning" },
  awaiting_dependency: { label: "Awaiting prerequisite", variant: "warning" },
  changes_requested: { label: "Changes requested", variant: "destructive" },
  blocked: { label: "Blocked", variant: "destructive" },
  wrong_evidence_type: { label: "Wrong evidence type", variant: "warning" },
  not_applicable: { label: "Not applicable", variant: "muted" },
};

export function RequirementStatusBadge({ status }: { status: string }) {
  const entry = REQUIREMENT_STATUS[status] ?? { label: status, variant: "muted" as const };
  return (
    <Badge variant={entry.variant} className="gap-1">
      {status === "not_applicable" && <CircleSlash className="size-3" />}
      {entry.label}
    </Badge>
  );
}
