"use client";

import * as React from "react";
import { ResponsiveContainer } from "recharts";

import { cn } from "@/lib/utils";

/**
 * Wrapper for every Recharts chart in the app.
 *
 * Two things it exists to enforce:
 *
 * 1. A FIXED PIXEL HEIGHT on the wrapper. Recharts renders nothing until
 *    ResponsiveContainer has measured its parent, so a percentage height gives
 *    a layout jump on every chart, on every load. The height is a prop, not a
 *    guess.
 *
 * 2. AN ACCESSIBLE FALLBACK. An SVG of coloured rectangles is nothing to a
 *    screen reader, and this is a compliance tool — the numbers behind a chart
 *    have to be reachable. `summary` is announced, and `table` renders a
 *    visually-hidden real table of the series.
 *
 * Also worth knowing: never mount one of these inside a container that is
 * hidden rather than unmounted. Radix TabsContent unmounts by default, which
 * is correct here; adding `forceMount` would make ResponsiveContainer measure
 * 0×0 and warn.
 */
export function ChartContainer({
  height = 220,
  summary,
  table,
  className,
  children,
}: {
  height?: number;
  /** One sentence naming what the chart shows. Required — a chart with no description is decoration. */
  summary: string;
  /** The same data as a table, for anyone not looking at the picture. */
  table?: React.ReactNode;
  className?: string;
  children: React.ReactElement;
}) {
  return (
    <div className={cn("w-full", className)}>
      <div style={{ height }} role="img" aria-label={summary}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
      {table && <div className="sr-only">{table}</div>}
    </div>
  );
}
