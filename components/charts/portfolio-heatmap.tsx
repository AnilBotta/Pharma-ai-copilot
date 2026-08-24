"use client";

import * as React from "react";
import Link from "next/link";

import { statusColor } from "@/lib/chart-tokens";
import { pdp, type ProgrammeSummary, type StageSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The statuses a cell can carry, in the order the legend lists them. */
const LEGEND: [string, string][] = [
  ["approved", "Approved"],
  ["conditionally_approved", "Approved with conditions"],
  ["ready_for_human_review", "Ready for review"],
  ["in_progress", "In progress"],
  ["at_risk", "At risk"],
  ["rejected", "Rejected"],
  ["on_hold", "On hold"],
  ["not_started", "Not started"],
];

const MAX_ROWS = 24;

export interface MatrixRow {
  programme: ProgrammeSummary;
  stages: StageSummary[];
}

/**
 * Every programme's gates at once, fetched one programme at a time.
 *
 * `listProgrammes()` returns only the CURRENT stage per programme, so a full
 * matrix needs `getProgramme()` for each. Three things follow from that, and
 * they are the whole reason this is a hook rather than one `await`:
 *
 * 1. Each request settles on its own. A row appears the moment its programme
 *    answers, rather than the grid waiting on the slowest one.
 * 2. One rejection must never blank the grid. A failed programme is counted
 *    and named as failed; the other twenty-three still render. `Promise.all`
 *    would have thrown the lot away for one 500.
 * 3. It is capped. Twenty-four programmes is twenty-four requests; an
 *    unbounded portfolio would quietly turn a page load into a stampede. The
 *    cap is stated in the UI rather than hidden, because a portfolio view that
 *    silently omits programmes is worse than one that admits it.
 */
export function usePortfolioMatrix(programmes: ProgrammeSummary[]) {
  const [rows, setRows] = React.useState<MatrixRow[]>([]);
  const [failed, setFailed] = React.useState<string[]>([]);
  const [pending, setPending] = React.useState(0);

  const shown = React.useMemo(
    () => programmes.slice(0, MAX_ROWS),
    [programmes]
  );

  React.useEffect(() => {
    if (shown.length === 0) {
      setRows([]);
      setFailed([]);
      setPending(0);
      return;
    }

    let live = true;
    setRows([]);
    setFailed([]);
    setPending(shown.length);

    // Rows arrive in whatever order the network answers, but the grid must not
    // reshuffle as they land — a row jumping under the pointer is how a reader
    // clicks the wrong programme. Position is fixed up front by list order.
    const order = new Map(shown.map((p, i) => [p.id, i]));

    for (const programme of shown) {
      pdp
        .getProgramme(programme.id)
        .then((detail) => {
          if (!live) return;
          setRows((prev) =>
            [...prev, { programme, stages: detail.stages }].sort(
              (a, b) =>
                (order.get(a.programme.id) ?? 0) -
                (order.get(b.programme.id) ?? 0)
            )
          );
        })
        .catch(() => {
          if (live) setFailed((prev) => [...prev, programme.name]);
        })
        .finally(() => {
          if (live) setPending((n) => n - 1);
        });
    }

    return () => {
      live = false;
    };
  }, [shown]);

  return {
    rows,
    failed,
    loading: pending > 0,
    shownCount: shown.length,
    totalCount: programmes.length,
    truncated: programmes.length > MAX_ROWS,
  };
}

/**
 * The portfolio as a grid: one row per programme, one cell per gate.
 *
 * CSS grid rather than Recharts. This is a categorical matrix with a link and
 * an accessible name behind every cell — a charting library would fight it on
 * all three counts and win none of them.
 *
 * Colour comes from `statusColor`, which carries the product's rule into the
 * chart layer: a cell is green only when the gate is actually `approved`. A
 * stage at 96% readiness with `is_ready: false` renders amber here exactly as
 * it does on its own page.
 *
 * Colour is never the only encoding. Every cell has a title and an accessible
 * name naming the gate and its status in words, because a grid of coloured
 * squares is unreadable to anyone who cannot separate the hues — and because
 * this is a compliance tool, where "I could not tell" is a real failure.
 */
export function PortfolioHeatmap({
  rows,
  failed,
  loading,
  shownCount,
  totalCount,
  truncated,
  className,
}: {
  rows: MatrixRow[];
  failed: string[];
  loading: boolean;
  shownCount: number;
  totalCount: number;
  truncated: boolean;
  className?: string;
}) {
  // The widest programme decides the column count. Templates need not agree on
  // how many gates they have, so this is read from the data rather than fixed
  // at eight.
  const columns = rows.reduce((max, r) => Math.max(max, r.stages.length), 0);

  if (rows.length === 0 && !loading && failed.length === 0) return null;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="overflow-x-auto">
        <div
          className="grid min-w-max gap-1"
          style={{
            gridTemplateColumns: `minmax(9rem, 14rem) repeat(${Math.max(columns, 1)}, minmax(1.5rem, 1fr))`,
          }}
        >
          {/* Column headers: gate positions. */}
          <div aria-hidden="true" />
          {Array.from({ length: columns }).map((_, i) => (
            <div
              key={`h-${i}`}
              aria-hidden="true"
              className="pb-1 text-center text-2xs text-muted-foreground"
            >
              {i}
            </div>
          ))}

          {rows.map(({ programme, stages }) => {
            const ordered = [...stages].sort((a, b) => a.position - b.position);
            return (
              <React.Fragment key={programme.id}>
                <Link
                  href={`/programmes/${programme.id}`}
                  className="truncate rounded pr-2 text-xs outline-none hover:text-primary hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  title={programme.name}
                >
                  {programme.name}
                </Link>
                {Array.from({ length: columns }).map((_, i) => {
                  const stage = ordered[i];
                  if (!stage) {
                    return (
                      <div
                        key={`${programme.id}-${i}`}
                        aria-hidden="true"
                        className="h-6 rounded-sm"
                      />
                    );
                  }
                  const status = stage.gate_status.replace(/_/g, " ");
                  return (
                    <Link
                      key={stage.id}
                      href={`/programmes/${programme.id}/gates/${stage.id}`}
                      title={`${stage.name} — ${status}, ${stage.mandatory_satisfied} of ${stage.mandatory_count} mandatory satisfied`}
                      aria-label={`${programme.name}, ${stage.name}: ${status}, ${stage.mandatory_satisfied} of ${stage.mandatory_count} mandatory requirements satisfied`}
                      className="h-6 rounded-sm border border-transparent outline-none transition-transform hover:scale-110 hover:border-foreground/30 focus-visible:ring-[3px] focus-visible:ring-ring/50"
                      style={{ backgroundColor: statusColor(stage.gate_status) }}
                    />
                  );
                })}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {LEGEND.map(([key, label]) => (
          <span
            key={key}
            className="flex items-center gap-1.5 text-2xs text-muted-foreground"
          >
            <span
              aria-hidden="true"
              className="size-2.5 rounded-sm border border-border/60"
              style={{ backgroundColor: statusColor(key) }}
            />
            {label}
          </span>
        ))}
      </div>

      {(loading || truncated || failed.length > 0) && (
        <p className="text-2xs text-muted-foreground">
          {loading && <>Loading {shownCount - rows.length - failed.length} more… </>}
          {truncated && (
            <>
              Showing the first {shownCount} of {totalCount} programmes.{" "}
            </>
          )}
          {failed.length > 0 && (
            <span className="text-warning">
              {failed.length === 1
                ? `${failed[0]} could not be loaded and is missing from the grid.`
                : `${failed.length} programmes could not be loaded and are missing from the grid: ${failed.join(", ")}.`}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
