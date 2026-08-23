"use client";

import * as React from "react";

import type { Milestone, Task } from "@/lib/api";

const DAY_MS = 86_400_000;

export type Zoom = "day" | "week" | "month";

/** Pixels per day at each zoom. Changing this is the whole zoom mechanism. */
const PX_PER_DAY: Record<Zoom, number> = { day: 24, week: 6, month: 2.2 };

export interface TimeScale {
  /** Domain start, midnight, padded to the 1st of its month. */
  start: Date;
  end: Date;
  pxPerDay: number;
  totalDays: number;
  width: number;
  /** Left offset in px for a date, or null when the date is missing. */
  x(date: string | null | undefined): number | null;
  /** Width in px for a date range, minimum 2px so a same-day task is visible. */
  span(from: string | null | undefined, to: string | null | undefined): number | null;
  /** First of each month inside the domain, for the axis. */
  months: { date: Date; x: number; label: string }[];
  todayX: number | null;
}

/**
 * Parse a schedule date as a LOCAL calendar day.
 *
 * `new Date("2026-07-31")` is specified to parse a date-only string as UTC
 * midnight. Reading local components back out of that lands on 30 July
 * anywhere west of Greenwich — measured on this machine (America/Toronto,
 * UTC-4), every bar sat exactly one day early. Widths were right, because
 * both ends shifted together, which is what makes it easy to miss.
 *
 * These fields are calendar dates, not instants: a task starting on the 31st
 * starts on the 31st wherever you open the page. So the components are split
 * out and handed to the local Date constructor.
 */
function parse(d: string | null | undefined): Date | null {
  if (!d) return null;

  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
  if (dateOnly) {
    const [, y, m, day] = dateOnly;
    return new Date(Number(y), Number(m) - 1, Number(day));
  }

  const t = new Date(d);
  if (Number.isNaN(t.getTime())) return null;
  // A full timestamp is an instant; take the local day it falls on.
  return new Date(t.getFullYear(), t.getMonth(), t.getDate());
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/**
 * Builds the horizontal scale a Gantt needs, from whatever dates the tasks
 * actually carry.
 *
 * The domain spans EVERY date field — baseline, forecast and actual, plus
 * milestones — not just the forecast. A task whose forecast has slipped past
 * its baseline must still fit, and so must one that finished early.
 *
 * Returns null when nothing is dated at all, which is a real state: the
 * schedule page is usable before anybody has put dates on anything, and a
 * timeline with no domain is not something to render apologetically — it is
 * something not to render.
 */
export function useTimeScale(
  tasks: Task[],
  milestones: Milestone[],
  zoom: Zoom
): TimeScale | null {
  return React.useMemo(() => {
    const dates: Date[] = [];
    for (const t of tasks) {
      for (const d of [
        t.baseline_start,
        t.baseline_end,
        t.forecast_start,
        t.forecast_end,
        t.actual_start,
        t.actual_end,
      ]) {
        const parsed = parse(d);
        if (parsed) dates.push(parsed);
      }
    }
    for (const m of milestones) {
      for (const d of [m.baseline_date, m.forecast_date, m.actual_date]) {
        const parsed = parse(d);
        if (parsed) dates.push(parsed);
      }
    }
    if (dates.length === 0) return null;

    // Today is always in the domain. Without this, a schedule whose last task
    // ended before now has no today line at all — which is precisely when
    // knowing how far past the plan you are matters most.
    dates.push(startOfDay(new Date()));

    const min = new Date(Math.min(...dates.map((d) => d.getTime())));
    const max = new Date(Math.max(...dates.map((d) => d.getTime())));

    // Pad out to whole months so the axis has somewhere to put its labels.
    const start = new Date(min.getFullYear(), min.getMonth(), 1);
    const end = new Date(max.getFullYear(), max.getMonth() + 1, 0);

    const pxPerDay = PX_PER_DAY[zoom];
    const totalDays = Math.max(
      1,
      Math.round((startOfDay(end).getTime() - start.getTime()) / DAY_MS) + 1
    );
    const width = totalDays * pxPerDay;

    const xFor = (d: Date) =>
      ((startOfDay(d).getTime() - start.getTime()) / DAY_MS) * pxPerDay;

    const months: TimeScale["months"] = [];
    const cursor = new Date(start);
    while (cursor <= end) {
      months.push({
        date: new Date(cursor),
        x: xFor(cursor),
        label: cursor.toLocaleDateString("en-GB", {
          month: "short",
          year: cursor.getMonth() === 0 ? "numeric" : undefined,
        }),
      });
      cursor.setMonth(cursor.getMonth() + 1);
    }

    const today = startOfDay(new Date());
    const todayX = today >= start && today <= end ? xFor(today) : null;

    return {
      start,
      end,
      pxPerDay,
      totalDays,
      width,
      months,
      todayX,
      x(date) {
        const d = parse(date);
        return d ? xFor(d) : null;
      },
      span(from, to) {
        const a = parse(from);
        const b = parse(to);
        if (!a || !b) return null;
        // Inclusive of the end day, and never thinner than 2px — a one-day
        // task that renders as nothing reads as a missing task.
        const days =
          (startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY_MS + 1;
        return Math.max(2, days * pxPerDay);
      },
    };
  }, [tasks, milestones, zoom]);
}
