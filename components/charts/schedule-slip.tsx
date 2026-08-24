"use client";

import * as React from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, XAxis, YAxis } from "recharts";

import { ChartContainer } from "@/components/charts/chart-container";
import { CHART } from "@/lib/chart-tokens";
import type { Task } from "@/lib/api";

const MAX_ROWS = 20;

/**
 * Slip against the commitment, one bar per task.
 *
 * THE NUMBER IS THE ENGINE'S, NOT ONE THIS FILE COMPUTES
 *
 * `variance_days` is `coalesce(actual_end, forecast_end) - baseline_end`,
 * computed on read by `private.task_variance_days` and stored nowhere. The
 * obvious client-side version — forecast_end minus baseline_end — is WRONG,
 * and measurably so on this project's real data: a task with
 *
 *     baseline_end 2026-08-15   forecast_end 2026-08-15   actual_end 2026-08-21
 *
 * carries a variance of 6. Recomputing from the forecast would have drawn it
 * as ON TIME while the row beneath it said "6d late". A chart that contradicts
 * the page it sits on is worse than no chart.
 *
 * NO BASELINE, NO CHART
 *
 * Slip is a distance from a promise. Without a baseline there is no promise,
 * and a slip chart drawn against a freely-moving forecast measures nothing at
 * all — it would read as reassuring precisely when the schedule is least
 * accountable. So that case renders a refusal, not an empty axis.
 */
export function ScheduleSlip({
  tasks,
  hasBaseline,
}: {
  tasks: Task[];
  hasBaseline: boolean;
}) {
  const { rows, unbaselined, hidden } = React.useMemo(() => {
    const measurable = tasks.filter((t) => t.variance_days !== null);
    const sorted = [...measurable].sort(
      (a, b) => (b.variance_days ?? 0) - (a.variance_days ?? 0)
    );
    return {
      rows: sorted.slice(0, MAX_ROWS).map((t) => ({
        id: t.id,
        label: t.title.length > 34 ? `${t.title.slice(0, 33)}…` : t.title,
        title: t.title,
        variance: t.variance_days ?? 0,
        critical: t.is_critical,
        // A finished task's slip is a fact; an unfinished one's is a
        // prediction. Saying "finished 6 days late" and "forecast to finish 6
        // days late" as if they were the same claim is how a plan quietly
        // becomes fiction.
        settled: t.actual_end !== null,
      })),
      unbaselined: tasks.length - measurable.length,
      hidden: Math.max(0, measurable.length - MAX_ROWS),
    };
  }, [tasks]);

  if (!hasBaseline) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
        No baseline has been set, so there is nothing to slip against. Dates are
        still a draft plan rather than a commitment, and a slip measured against
        a forecast that moves freely would measure nothing.
      </p>
    );
  }

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
        The baseline is set, but no task carries a baselined end date yet.
      </p>
    );
  }

  const worst = Math.max(...rows.map((r) => Math.abs(r.variance)), 1);
  const late = rows.filter((r) => r.variance > 0).length;

  return (
    <div className="space-y-2">
      <ChartContainer
        height={Math.max(140, rows.length * 30 + 40)}
        summary={`Slip against the baseline for ${rows.length} tasks. ${late} later than promised.`}
        table={
          <table>
            <caption>Slip against the baseline, in days</caption>
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Days against baseline</th>
                <th scope="col">Recorded or forecast</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.title}</td>
                  <td>{r.variance}</td>
                  <td>{r.settled ? "recorded" : "forecast"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      >
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
          barCategoryGap="22%"
        >
          <CartesianGrid stroke={CHART.grid} horizontal={false} />
          <XAxis
            type="number"
            domain={[-worst, worst]}
            allowDecimals={false}
            stroke={CHART.axis}
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => (v > 0 ? `+${v}d` : `${v}d`)}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={150}
            stroke={CHART.axis}
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          {/* The commitment. Everything to its right was promised sooner. */}
          <ReferenceLine x={0} stroke={CHART.baseline} strokeWidth={1.5} />
          <Bar dataKey="variance" isAnimationActive={false} radius={2}>
            {rows.map((r) => (
              <Cell
                key={r.id}
                // Raw tokens, never the --color-* bridge: see lib/chart-tokens.
                fill={
                  r.variance > 0
                    ? r.critical
                      ? "var(--danger-solid)"
                      : "var(--warning-solid)"
                    : r.variance < 0
                      ? "var(--success-solid)"
                      : "var(--border)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>

      <p className="text-2xs text-muted-foreground">
        Days against the baseline: right is later than promised.{" "}
        {late === 0
          ? "Nothing is later than promised."
          : `${late} task${late === 1 ? " is" : "s are"} later than promised`}
        {late > 0 &&
          rows.some((r) => r.variance > 0 && r.critical) &&
          "; those in red are on the critical path, where a day of slip is a day of programme slip"}
        {late > 0 && ". "}
        A bar for a finished task is what happened; for an unfinished one it is
        a forecast.
        {unbaselined > 0 && (
          <>
            {" "}
            {unbaselined} task{unbaselined === 1 ? "" : "s"} carr
            {unbaselined === 1 ? "ies" : "y"} no baselined end date and{" "}
            {unbaselined === 1 ? "is" : "are"} not shown.
          </>
        )}
        {hidden > 0 && <> Showing the {MAX_ROWS} worst of {rows.length + hidden}.</>}
      </p>
    </div>
  );
}
