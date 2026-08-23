"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { statusColor } from "@/lib/chart-tokens";
import type { ProgrammeSummary } from "@/lib/api";

/**
 * Statuses that mean the gate has already been decided.
 *
 * `is_ready` alone is NOT "needs a decision", and assuming it was produced a
 * false positive on real data: PDX-114 reports `is_ready: true` with
 * `current_gate_status: "approved"` — every mandatory requirement satisfied
 * AND the decision already recorded. Listing that as awaiting a decision would
 * send somebody to a gate that has nothing left to do, which is precisely the
 * kind of false signal this module exists to prevent.
 *
 * So a gate is awaiting a person only when it is ready and has NOT been
 * decided.
 */
const DECIDED = new Set(["approved", "rejected"]);

/**
 * Exported so the page heading counts exactly what the list shows. Deriving
 * the number separately is how a "2 gates need a decision" headline ends up
 * above a list of one.
 */
export function awaitingDecision(
  programmes: ProgrammeSummary[]
): ProgrammeSummary[] {
  return programmes.filter((p) => {
    const status = p.current_gate_status ?? "not_started";
    if (status === "conditionally_approved") return true;
    return p.is_ready === true && !DECIDED.has(status);
  });
}

/**
 * Programmes whose current gate is waiting on a person.
 *
 * Two different kinds of waiting, deliberately distinguished:
 *
 *   ready, not yet decided   — somebody needs to record a gate decision
 *   conditionally approved   — decided, but with conditions still open, which
 *                              is a quieter thing that ages badly
 *
 * Deliberately NOT keyed on `readiness_pct`: a gate at 96% with one
 * unsatisfied mandatory item is waiting on WORK, not on a decision, and
 * putting it here would send somebody to a gate that will refuse them.
 */
export function NeedsDecision({
  programmes,
}: {
  programmes: ProgrammeSummary[];
}) {
  const waiting = awaitingDecision(programmes);

  if (waiting.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-5">
          <CheckCircle2
            aria-hidden="true"
            className="size-5 shrink-0 text-success"
          />
          <p className="text-sm text-muted-foreground">
            No gate is waiting on a decision — every current gate is either
            already decided or still has mandatory work outstanding.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {waiting.map((p) => {
        const conditional = p.current_gate_status === "conditionally_approved";
        return (
          <Card key={p.id} className="transition-colors hover:border-primary/40">
            <CardContent className="py-0">
              <Link
                href={
                  p.current_stage_pk
                    ? `/programmes/${p.id}/gates/${p.current_stage_pk}`
                    : `/programmes/${p.id}`
                }
                className="flex flex-col gap-4 py-5 outline-none sm:flex-row sm:items-center"
              >
                <span
                  aria-hidden="true"
                  className="hidden w-1 self-stretch rounded-full sm:block"
                  style={{
                    backgroundColor: statusColor(
                      p.current_gate_status ?? "not_started"
                    ),
                  }}
                />

                <div className="min-w-0 flex-1">
                  <p className="truncate text-md font-semibold">{p.name}</p>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {p.current_stage_name ?? "No current gate"}
                  </p>
                </div>

                <div className="flex items-center gap-4 sm:w-72">
                  <span className="metric text-xl">
                    {p.readiness_pct?.toFixed(1) ?? "—"}%
                  </span>
                  <Badge variant={conditional ? "warning" : "success"} dot>
                    {conditional ? "Conditions open" : "Ready for review"}
                  </Badge>
                </div>

                <ArrowRight
                  aria-hidden="true"
                  className="hidden size-4 shrink-0 text-muted-foreground sm:block"
                />
              </Link>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

/**
 * The portfolio as one row per programme: name, current gate, and the
 * mandatory count that decides whether it can move.
 */
export function PortfolioRows({
  programmes,
}: {
  programmes: ProgrammeSummary[];
}) {
  return (
    <div className="flex flex-col divide-y">
      {programmes.map((p) => (
        <Link
          key={p.id}
          href={`/programmes/${p.id}`}
          className="flex flex-col gap-3 py-4 outline-none transition-colors hover:bg-accent/40 sm:flex-row sm:items-center sm:gap-6"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{p.name}</p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {p.current_stage_name ?? "Not started"}
            </p>
          </div>

          <div className="flex items-center gap-3 sm:w-64">
            <span className="metric w-14 shrink-0 text-sm">
              {p.readiness_pct?.toFixed(1) ?? "—"}%
            </span>
            {p.blocker_count !== null && p.blocker_count > 0 ? (
              <span className="text-xs text-warning">
                {p.blocker_count} outstanding
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">
                nothing outstanding
              </span>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
