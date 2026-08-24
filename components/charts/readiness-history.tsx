"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer } from "@/components/charts/chart-container";
import { CHART } from "@/lib/chart-tokens";
import { buildReadinessHistory } from "@/lib/readiness-history";
import type { AuditEntry } from "@/lib/api";

const fmtDate = (t: number) =>
  new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/**
 * Requirements satisfied over time.
 *
 * COUNTS, NEVER A PERCENTAGE. There is no stored readiness timeseries, so this
 * curve is reconstructed from the audit log — and a reconstruction rendered as
 * a percentage invites comparison with `readiness_pct`, which is computed a
 * different way from a different source. A rising green percentage beside a
 * "Not ready" badge is the single worst thing this product can display.
 *
 * The reconstruction is `buildReadinessHistory`, which is pure and has its own
 * tests. The series always terminates on the engine's current count, and when
 * the replay did not reach that number on its own the caption says so instead
 * of letting the reader assume the line is authoritative.
 *
 * The applicable-count reference line is TODAY'S applicable count, not a
 * historical one — requirements can be scoped in and out, and reconstructing
 * the denominator as well would compound one guess with another. Labelled as
 * such rather than implied.
 */
export function ReadinessHistory({
  audit,
  satisfied,
  applicable,
  windowLimit,
}: {
  audit: AuditEntry[];
  /** The engine's current satisfied count. The series ends here. */
  satisfied: number;
  /** The engine's current applicable count. Drawn as today's target. */
  applicable: number;
  /** The limit the audit window was fetched with, so the caption can be honest. */
  windowLimit: number;
}) {
  const history = React.useMemo(
    () => buildReadinessHistory(audit, satisfied),
    [audit, satisfied]
  );

  // One terminating point is not a history. Below two real points the picture
  // would be a dot dressed up as a trend.
  if (history.relevant < 2) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
        Not enough recorded activity yet to draw a history. Requirements
        currently satisfied: {satisfied} of {applicable}.
      </p>
    );
  }

  const domainMax = Math.max(applicable, history.engine);

  return (
    <div className="space-y-2">
      <ChartContainer
        height={200}
        summary={`Requirements satisfied over time, ending at ${history.engine} of ${applicable} applicable requirements.`}
        table={
          <table>
            <caption>Requirements satisfied over time</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Requirements satisfied</th>
              </tr>
            </thead>
            <tbody>
              {history.points.map((p) => (
                <tr key={p.t}>
                  <td>{new Date(p.t).toISOString()}</td>
                  <td>{p.satisfied}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
      >
        <AreaChart
          data={history.points}
          margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
        >
          <defs>
            <linearGradient id="readiness-fill" x1="0" y1="0" x2="0" y2="1">
              {/* Raw token, never the --color-* bridge: see lib/chart-tokens. */}
              <stop offset="0%" stopColor={CHART.series[0]} stopOpacity={0.28} />
              <stop offset="100%" stopColor={CHART.series[0]} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={fmtDate}
            stroke={CHART.axis}
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            allowDecimals={false}
            domain={[0, domainMax]}
            stroke={CHART.axis}
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={34}
          />

          {/* Today's applicable count. A target, explicitly not a history. */}
          <ReferenceLine
            y={applicable}
            stroke={CHART.axis}
            strokeDasharray="4 4"
          />

          {history.gates.map((g) => (
            <ReferenceLine
              key={`${g.t}-${g.label}`}
              x={g.t}
              stroke={CHART.today}
              strokeDasharray="2 3"
            />
          ))}

          {/* stepAfter: a requirement becomes satisfied at an instant and stays
              that way. Interpolating between events would draw fractional
              requirements, which do not exist. */}
          <Area
            type="stepAfter"
            dataKey="satisfied"
            stroke={CHART.series[0]}
            strokeWidth={2}
            fill="url(#readiness-fill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ChartContainer>

      <p className="text-2xs text-muted-foreground">
        Reconstructed from the last {history.events} recorded events
        {history.events >= windowLimit && " (the window is capped)"};{" "}
        {history.relevant} of them changed the count.{" "}
        {history.gates.length > 0 && (
          <>Dotted verticals are gate decisions. </>
        )}
        The dashed horizontal is today&rsquo;s {applicable} applicable
        requirements, not a historical figure.{" "}
        {history.agrees ? (
          <>The reconstruction agrees with the engine at {history.engine}.</>
        ) : (
          <span className="text-warning">
            The reconstruction reached {history.reconstructed} but the engine
            reports {history.engine}; the series is drawn to the engine&rsquo;s
            number, and the step at the right is that difference. Events older
            than the window explain most of it.
          </span>
        )}
      </p>
    </div>
  );
}
