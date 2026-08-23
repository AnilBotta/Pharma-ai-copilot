"use client";

import * as React from "react";
import { Lock, Zap } from "lucide-react";

import { useTimeScale, type Zoom } from "@/components/charts/gantt/use-time-scale";
import { Button } from "@/components/ui/button";
import { CHART } from "@/lib/chart-tokens";
import { cn } from "@/lib/utils";
import type { Milestone, Task } from "@/lib/api";

/**
 * The schedule, on a date axis.
 *
 * The page had no axis at all — a stack of cards with dates written as text,
 * which for a stage-gate product is a conspicuous gap. This is deliberately
 * hand-built rather than a library or a Recharts bar:
 *
 *   - Two tracks per row. The whole argument of the schedule module is that a
 *     forecast means nothing without the commitment beside it; the file's own
 *     comment says "showing the forecast alone is how a plan quietly becomes
 *     fiction". Recharts gives one categorical row per series, not two
 *     overlaid tracks of different heights.
 *   - Read-only. Every Gantt library's headline feature is dragging bars to
 *     reschedule, and `baseline_*` is immutable by design — no endpoint can
 *     change it. An affordance that teaches the opposite of the module's rule
 *     is worse than no affordance.
 *   - Read-only also removes the hard 80% of a Gantt: hit testing, drag maths,
 *     collision resolution.
 *
 * The baseline is drawn recessive and outlined; the forecast solid and inset.
 * A slip is therefore a SHAPE — forecast extending past the ghost — before it
 * is ever a number.
 */
export function GanttTimeline({
  tasks,
  milestones,
  className,
}: {
  tasks: Task[];
  milestones: Milestone[];
  className?: string;
}) {
  const [zoom, setZoom] = React.useState<Zoom>("week");
  const scale = useTimeScale(tasks, milestones, zoom);

  const dated = tasks.filter(
    (t) => t.baseline_start || t.forecast_start || t.actual_start
  );
  const undated = tasks.length - dated.length;

  if (!scale) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No task carries a date yet, so there is nothing to place on a timeline.
      </p>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-4 rounded-sm border"
              style={{ borderColor: CHART.baseline }}
            />
            baseline
          </span>
          <span className="mx-3 inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-4 rounded-sm"
              style={{ backgroundColor: CHART.forecast }}
            />
            forecast
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-4 rounded-sm"
              style={{ backgroundColor: CHART.critical }}
            />
            slip
          </span>
        </p>

        <div className="flex items-center gap-1 rounded-lg bg-muted p-0.5">
          {(["day", "week", "month"] as const).map((z) => (
            <Button
              key={z}
              size="sm"
              variant={zoom === z ? "default" : "ghost"}
              className="h-6 px-2 text-2xs capitalize"
              onClick={() => setZoom(z)}
            >
              {z}
            </Button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border">
        <div className="max-h-[32rem] overflow-auto">
          <div
            className="grid"
            style={{ gridTemplateColumns: `minmax(180px, 240px) ${scale.width}px` }}
          >
            {/* ── axis ─────────────────────────────────────────────────── */}
            <div className="sticky top-0 left-0 z-30 border-r border-b bg-card px-3 py-2">
              <span className="type-label text-muted-foreground">Task</span>
            </div>
            <div className="sticky top-0 z-20 border-b bg-card">
              <div className="relative h-9">
                {scale.months.map((m) => (
                  <div
                    key={m.date.toISOString()}
                    className="absolute top-0 flex h-full items-center border-l pl-1.5"
                    style={{ left: m.x }}
                  >
                    <span className="text-2xs whitespace-nowrap text-muted-foreground">
                      {m.label}
                    </span>
                  </div>
                ))}
                {scale.todayX !== null && (
                  <div
                    className="absolute top-0 h-full w-px"
                    style={{ left: scale.todayX, background: CHART.today }}
                  >
                    <span
                      className="absolute top-1 left-1 text-2xs font-medium whitespace-nowrap"
                      style={{ color: CHART.today }}
                    >
                      today
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* ── rows ─────────────────────────────────────────────────── */}
            {dated.map((task) => (
              <GanttRow key={task.id} task={task} scale={scale} />
            ))}

            {/* ── milestones ───────────────────────────────────────────── */}
            {milestones.length > 0 && (
              <>
                <div className="sticky left-0 z-10 border-t border-r bg-card px-3 py-2">
                  <span className="type-label text-muted-foreground">
                    Milestones
                  </span>
                </div>
                <div className="relative border-t" style={{ height: 36 }}>
                  {scale.todayX !== null && (
                    <div
                      className="absolute inset-y-0 w-px"
                      style={{ left: scale.todayX, background: CHART.today }}
                    />
                  )}
                  {milestones.map((m) => {
                    const x = scale.x(m.forecast_date ?? m.baseline_date);
                    if (x === null) return null;
                    return (
                      <span
                        key={m.id}
                        title={`${m.name}${m.is_contractual ? " (contractual)" : ""}`}
                        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px]"
                        style={{
                          left: x,
                          backgroundColor: m.is_contractual
                            ? CHART.critical
                            : CHART.forecast,
                        }}
                      />
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {undated > 0 && (
        <p className="text-xs text-muted-foreground">
          {undated} task{undated === 1 ? "" : "s"} not shown — no dates
          recorded. A task invisible because nobody dated it is exactly the one
          that slips.
        </p>
      )}
    </div>
  );
}

function GanttRow({
  task,
  scale,
}: {
  task: Task;
  scale: NonNullable<ReturnType<typeof useTimeScale>>;
}) {
  const bx = scale.x(task.baseline_start);
  const bw = scale.span(task.baseline_start, task.baseline_end);
  const fx = scale.x(task.forecast_start);
  const fw = scale.span(task.forecast_start, task.forecast_end);
  const ax = scale.x(task.actual_start);
  const aw = scale.span(task.actual_start, task.actual_end ?? task.forecast_end);

  // A slip is drawn where the forecast runs past the baseline's end, so it
  // reads as an overhang rather than as a number somewhere else.
  const baselineEndX = bx !== null && bw !== null ? bx + bw : null;
  const forecastEndX = fx !== null && fw !== null ? fx + fw : null;
  const slipFrom = baselineEndX;
  const slipWidth =
    baselineEndX !== null && forecastEndX !== null && forecastEndX > baselineEndX
      ? forecastEndX - baselineEndX
      : null;

  return (
    <>
      <div
        className={cn(
          "sticky left-0 z-10 flex min-w-0 items-center gap-2 border-t border-r bg-card px-3 py-2",
          task.is_critical && "border-l-2"
        )}
        style={task.is_critical ? { borderLeftColor: CHART.critical } : undefined}
      >
        {task.is_critical && (
          <Zap
            aria-hidden="true"
            className="size-3 shrink-0"
            style={{ color: CHART.critical }}
          />
        )}
        {task.baseline_start && (
          <Lock aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate text-xs" title={task.title}>
          {task.title}
        </span>
      </div>

      <div className="relative border-t" style={{ height: 36 }}>
        {scale.todayX !== null && (
          <div
            className="absolute inset-y-0 w-px"
            style={{ left: scale.todayX, background: CHART.today }}
          />
        )}

        {/* baseline: the commitment, recessive on purpose */}
        {bx !== null && bw !== null && (
          <span
            className="absolute top-1/2 h-5 -translate-y-1/2 rounded-md border"
            style={{ left: bx, width: bw, borderColor: CHART.baseline }}
            title={`Baseline ${task.baseline_start} → ${task.baseline_end}`}
          />
        )}

        {/* forecast: the plan */}
        {fx !== null && fw !== null && (
          <span
            className="absolute top-1/2 h-3 -translate-y-1/2 rounded-sm"
            style={{ left: fx, width: fw, backgroundColor: CHART.forecast }}
            title={`Forecast ${task.forecast_start} → ${task.forecast_end}`}
          />
        )}

        {/* the overhang past the commitment */}
        {slipFrom !== null && slipWidth !== null && (
          <span
            className="absolute top-1/2 h-3 -translate-y-1/2 rounded-r-sm"
            style={{
              left: slipFrom,
              width: slipWidth,
              backgroundColor: CHART.critical,
            }}
            title={`${task.variance_days ?? ""} days past baseline`}
          />
        )}

        {/* what has actually happened, inside the forecast */}
        {ax !== null && aw !== null && (
          <span
            className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-foreground/50"
            style={{ left: ax, width: aw }}
            title="Actual"
          />
        )}
      </div>
    </>
  );
}
