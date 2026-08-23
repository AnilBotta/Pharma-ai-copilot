"use client";

import { useReducedMotion } from "framer-motion";
import { Bar, BarChart, Cell, CartesianGrid, XAxis, YAxis } from "recharts";

import { ChartContainer } from "@/components/charts/chart-container";
import { CHART, statusColor } from "@/lib/chart-tokens";
import type { StageSummary } from "@/lib/api";

/**
 * Mandatory requirements satisfied, per gate.
 *
 * Deliberately counts, not percentages. There is no stored readiness
 * timeseries, and a reconstructed percentage could disagree with the engine —
 * a chart reading "96%" beside a "Not ready" badge is the single worst thing
 * this product can render. Counts cannot disagree: they are the same numbers
 * the pips draw and the same ones the engine decides on.
 *
 * Each bar takes its gate's status colour through the same `statusColor` the
 * track uses, so a gate that is complete-but-not-approved is amber in both
 * places.
 */
export function MandatoryByGate({
  stages,
  height = 200,
}: {
  stages: StageSummary[];
  height?: number;
}) {
  // Recharts grows bars from zero on mount. That is its own animation system,
  // untouched by the CSS in globals.css, so it has to be switched off
  // explicitly for anyone who asked for less motion.
  const reduceMotion = useReducedMotion();

  const data = [...stages]
    .sort((a, b) => a.position - b.position)
    .map((s) => ({
      gate: `G${s.position}`,
      name: s.name,
      satisfied: s.mandatory_satisfied,
      total: s.mandatory_count,
      outstanding: Math.max(0, s.mandatory_count - s.mandatory_satisfied),
      status: s.gate_status,
    }));

  if (data.length === 0) return null;

  return (
    <ChartContainer
      height={height}
      summary="Mandatory requirements satisfied against the total for each gate."
      table={
        <table>
          <caption>Mandatory requirements by gate</caption>
          <thead>
            <tr>
              <th>Gate</th>
              <th>Satisfied</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.gate}>
                <td>{d.name}</td>
                <td>{d.satisfied}</td>
                <td>{d.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
        <CartesianGrid vertical={false} stroke={CHART.grid} />
        <XAxis
          dataKey="gate"
          tickLine={false}
          axisLine={false}
          tick={{ fill: CHART.axis, fontSize: 11 }}
        />
        <YAxis
          allowDecimals={false}
          tickLine={false}
          axisLine={false}
          tick={{ fill: CHART.axis, fontSize: 11 }}
        />
        {/* The outstanding remainder, so a short bar reads as "and this much
            is missing" rather than just "short". */}
        <Bar
          dataKey="outstanding"
          stackId="m"
          fill={CHART.grid}
          radius={[3, 3, 0, 0]}
          isAnimationActive={!reduceMotion}
        />
        <Bar
          dataKey="satisfied"
          stackId="m"
          radius={[3, 3, 0, 0]}
          isAnimationActive={!reduceMotion}
        >
          {data.map((d) => (
            // fill is an unresolved var(): re-resolves on theme change with no
            // remount. See lib/chart-tokens.
            <Cell key={d.gate} fill={statusColor(d.status)} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
