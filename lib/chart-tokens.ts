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
/**
 * A deeper version of a token, still unresolved and still opaque.
 *
 * DIRECTION MATTERS, AND THE FIRST ATTEMPT GOT IT WRONG.
 *
 * Separating two statuses within one hue family by making the recessive member
 * LIGHTER is the obvious move, and it is wrong here: a heatmap cell is drawn on
 * a card, so lighter means closer to the background. Measured, that took
 * `conditionally_approved` from 2.75:1 to 1.67:1 against the card — solving a
 * legibility problem by creating a worse one.
 *
 * Mixing toward `--foreground` instead separates the pair AND raises contrast,
 * and it reads correctly: the deeper cell is the more consequential one.
 *
 * Mixing with a real token rather than with `transparent` keeps the result
 * opaque, which is what makes it measurable at all. A contrast figure nobody
 * can verify is how a 1.31:1 cell survived this long.
 */
export function deepen(token: string, percent: number): string {
  return `color-mix(in oklab, ${token} ${percent}%, var(--foreground))`;
}

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
   *
   * HUE CARRIES THE VERDICT, LIGHTNESS SEPARATES STATES WITHIN IT
   *
   * Four statuses used to share two colours: `in_progress` was identical to
   * `ready_for_human_review`, and `at_risk` to `conditionally_approved`. On the
   * portfolio heatmap colour is the ONLY visual encoding, so a gate waiting for
   * a person to decide was indistinguishable from one merely being worked on —
   * and "waiting for a person" is the state this product exists to surface.
   *
   * Changing the hues would have put the no-false-green rule at risk, so the
   * families are untouched and each pair is separated by depth instead — see
   * `deepen`. The more consequential member goes deeper, which both reads
   * correctly and raises its contrast. `conditionally_approved` is still
   * unmistakably amber and still never green.
   */
  status: {
    approved: "var(--success-solid)",
    // Amber on a near-white card is inherently weak: bare `--warning-solid`
    // measured 2.75:1 against the card, under the 3:1 threshold, and that
    // predates this change. Both ambers are deepened enough to clear it —
    // without touching the token itself, which the readiness bar and the
    // mandatory pips also draw with and which nobody asked to change.
    conditionally_approved: deepen("var(--warning-solid)", 88),
    // `at_risk` is the deeper of the two: a gate drifting with no decision at
    // all is more alarming than one that was decided, with conditions. Reading
    // the swatches side by side is what settled which way round this went —
    // the first attempt had it backwards, and made the status that appears on
    // the real portfolio heatmap the odd dark one.
    at_risk: deepen("var(--warning-solid)", 55),
    // Deeper blue: this one is waiting on a person, which is the whole point
    // of the portfolio view. `in_progress` keeps the familiar bright blue.
    ready_for_human_review: deepen("var(--info-solid)", 62),
    in_progress: "var(--info-solid)",
    rejected: "var(--danger-solid)",
    on_hold: "var(--muted-foreground)",
    // `--border` measured 1.31:1 against the card it is drawn on, well under
    // the 3:1 WCAG 1.4.11 asks of a graphical object that carries meaning. On
    // a row where six of eight gates are not started, six cells were all but
    // invisible.
    not_started: deepen("var(--border)", 55),
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

/**
 * Does this gate need a person, right now?
 *
 * Exists because colour could not carry this on its own, and measuring said so.
 * Separating `ready_for_human_review` from `in_progress` by depth alone got
 * them only 1.91:1 apart in light and 1.40:1 in dark — better than the byte
 * identical pair they started as, but nowhere near telling two adjacent cells
 * apart. The gap cannot be widened much either: both members must stay inside
 * their hue family and both must clear 3:1 against the card, and in the dark
 * theme those two constraints squeeze the range almost shut.
 *
 * So the status that matters most gets an encoding that is not colour at all.
 * That is the accessible answer regardless — a portfolio grid should not ask
 * anyone to discriminate two blues to find the gate waiting on them.
 */
export function needsDecision(gateStatus: string): boolean {
  return gateStatus === "ready_for_human_review";
}
