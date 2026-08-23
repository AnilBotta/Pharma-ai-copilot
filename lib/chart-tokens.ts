/**
 * Colour for charts, as unresolved CSS variable references.
 *
 * THE RULE THAT MATTERS: every value here is the RAW token — `var(--chart-1)`,
 * never `var(--color-chart-1)`. The `--color-*` names are declared inside
 * `@theme inline`, which substitutes their value into utilities rather than
 * emitting a variable, so they are not guaranteed to exist at runtime. A chart
 * that referenced them would silently render black.
 *
 * Handing Recharts an *unresolved* reference is also what makes charts
 * theme-reactive for free: SVG presentation attributes are parsed as CSS
 * values, so `fill="var(--chart-1)"` re-resolves when next-themes flips the
 * class on <html>. No MutationObserver, no `useTheme()` dependency, no chart
 * remount, and no flash on first paint.
 *
 * The alternative — reading getComputedStyle in an effect — snapshots a string
 * at mount, needs a `resolvedTheme`-keyed remount to update, and loses the
 * entry animation every time somebody toggles the theme.
 */
export const CHART = {
  /** Categorical series. Eight, because there are eight gate statuses. */
  series: [
    "var(--chart-1)",
    "var(--chart-2)",
    "var(--chart-3)",
    "var(--chart-4)",
    "var(--chart-5)",
    "var(--chart-6)",
    "var(--chart-7)",
    "var(--chart-8)",
  ],

  grid: "var(--chart-grid)",
  axis: "var(--chart-axis)",

  /** Schedule: the commitment is recessive, the forecast is not. */
  baseline: "var(--chart-baseline)",
  forecast: "var(--chart-forecast)",
  critical: "var(--chart-critical)",
  today: "var(--chart-today)",

  /**
   * Gate status. This map is the chart layer's copy of the product's central
   * rule: a segment goes green only when the gate is actually `approved`. A
   * stage at 96% readiness with `is_ready: false` renders amber, exactly as
   * its progress bar does. The no-false-green rule is a product rule, not a
   * component rule, and the charts inherit it.
   */
  status: {
    approved: "var(--success-solid)",
    conditionally_approved: "var(--warning-solid)",
    ready_for_human_review: "var(--info-solid)",
    in_progress: "var(--info-solid)",
    at_risk: "var(--warning-solid)",
    rejected: "var(--danger-solid)",
    on_hold: "var(--muted-foreground)",
    not_started: "var(--border)",
  },
} as const;

/**
 * A tint of a token, still unresolved.
 *
 * `color-mix` composes with `var()`, so an intensity ramp can be built as a
 * plain string and left for CSS to resolve per theme. That is what lets a
 * heatmap have a continuous scale without a colour library and without
 * snapshotting the theme in JavaScript.
 */
export function tint(token: string, percent: number): string {
  return `color-mix(in oklab, ${token} ${percent}%, transparent)`;
}

/** The gate-status colour for a stage, honouring the no-false-green rule. */
export function statusColor(gateStatus: string): string {
  return (
    CHART.status[gateStatus as keyof typeof CHART.status] ??
    CHART.status.not_started
  );
}
