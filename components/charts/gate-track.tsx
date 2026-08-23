"use client";

import Link from "next/link";

import { statusColor } from "@/lib/chart-tokens";
import { cn } from "@/lib/utils";
import type { StageSummary } from "@/lib/api";

/**
 * A programme's gates, end to end.
 *
 * Not Recharts. A stepped rail with per-segment status semantics and a
 * current-position marker is not a chart type, and forcing it into a stacked
 * bar produces something you then fight forever — no per-segment links, no
 * sensible labels, no control over the marker.
 *
 * Colour comes from `statusColor`, which carries the product's rule into the
 * chart layer: a segment is green only when the gate is actually `approved`.
 * A stage sitting at 96% readiness with `is_ready: false` renders amber here,
 * exactly as its own progress bar does.
 *
 * Uses `stages` the programme page has already fetched — no extra request.
 */
export function GateTrack({
  stages,
  projectId,
  className,
}: {
  stages: StageSummary[];
  projectId: string;
  className?: string;
}) {
  if (stages.length === 0) return null;

  const ordered = [...stages].sort((a, b) => a.position - b.position);
  const current = ordered.find((s) => s.gate_status === "in_progress") ?? null;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-stretch gap-1.5">
        {ordered.map((stage) => {
          const isCurrent = current?.id === stage.id;
          return (
            <Link
              key={stage.id}
              href={`/programmes/${projectId}/gates/${stage.id}`}
              title={`${stage.name} — ${stage.gate_status.replace(/_/g, " ")}, ${stage.readiness_pct.toFixed(1)}%`}
              className={cn(
                "group flex min-w-0 flex-1 flex-col gap-1.5 rounded-md outline-none",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50"
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-7 rounded-md border transition-transform group-hover:-translate-y-0.5",
                  isCurrent ? "border-primary" : "border-transparent"
                )}
                style={{
                  // Raw token, never the --color-* bridge: see lib/chart-tokens.
                  backgroundColor: statusColor(stage.gate_status),
                }}
              />
              <span className="truncate text-center text-2xs text-muted-foreground">
                {stage.position}
              </span>
            </Link>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        {current ? (
          <>
            Currently{" "}
            <span className="font-medium text-foreground">{current.name}</span>
            {" — "}
            {current.mandatory_satisfied} of {current.mandatory_count} mandatory
            requirements satisfied.
          </>
        ) : (
          <>
            {ordered.filter((s) => s.gate_status === "approved").length} of{" "}
            {ordered.length} gates approved.
          </>
        )}
      </p>
    </div>
  );
}
