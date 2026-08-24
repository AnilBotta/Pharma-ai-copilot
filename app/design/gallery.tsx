"use client";

import * as React from "react";

import { ContrastTable } from "@/app/design/contrast-table";
import {
  GateReadiness,
  GateStatusBadge,
  RequirementStatusBadge,
  ReadyVerdict,
} from "@/components/pdp/gate-readiness";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { CHART, needsDecision, statusColor } from "@/lib/chart-tokens";

const BADGES = [
  "default",
  "secondary",
  "destructive",
  "outline",
  "success",
  "warning",
  "info",
  "muted",
] as const;

const BUTTON_VARIANTS = [
  "default",
  "destructive",
  "outline",
  "secondary",
  "ghost",
  "link",
] as const;

const CARD_VARIANTS = [
  "default",
  "flush",
  "elevated",
  "dashed",
  "interactive",
] as const;
const CARD_TONES = ["neutral", "success", "warning", "info", "danger"] as const;

const PROGRESS_TONES = [
  "brand",
  "success",
  "warning",
  "danger",
  "neutral",
] as const;

const GATE_STATUSES = [
  "not_started",
  "in_progress",
  "at_risk",
  "ready_for_human_review",
  "conditionally_approved",
  "approved",
  "rejected",
  "on_hold",
] as const;

const REQUIREMENT_STATUSES = [
  "not_started",
  "in_progress",
  "awaiting_dependency",
  "awaiting_approval",
  "satisfied",
  "overdue",
  "blocked",
] as const;

const TYPE_STEPS = [
  ["text-2xs", "0.6875rem"],
  ["text-xs", "0.75rem"],
  ["text-sm", "0.875rem"],
  ["text-md", "0.9375rem"],
  ["text-base", "1rem"],
  ["text-lg", "1.125rem"],
  ["text-xl", "1.25rem"],
  ["text-2xl", "1.5rem"],
] as const;

const SURFACE_TOKENS = [
  "background",
  "card",
  "muted",
  "accent",
  "primary",
  "secondary",
  "border",
] as const;

const STATUS_FAMILIES = ["success", "warning", "danger", "info"] as const;

/** A gate at 96% that is NOT ready, beside one at 87.5% that is. */
const NOT_READY = {
  readiness_pct: 96,
  is_ready: false,
  blocker_count: 2,
  applicable_count: 8,
  satisfied_count: 7,
  mandatory_count: 7,
  mandatory_satisfied: 5,
} as never;

const READY = {
  readiness_pct: 87.5,
  is_ready: true,
  blocker_count: 0,
  applicable_count: 8,
  satisfied_count: 7,
  mandatory_count: 7,
  mandatory_satisfied: 7,
} as never;

const BLOCKERS = [
  {
    requirement_id: "a",
    ref_code: "G1-PM-001",
    title: "Preformulation report",
    reason: "Past its due date with no evidence attached.",
  },
  {
    requirement_id: "b",
    ref_code: "G1-RA-001",
    title: "Regulatory pathway assessment",
    reason: "Evidence attached and accepted, awaiting approval.",
  },
] as never;

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="type-label text-muted-foreground">{title}</h2>
        {note && (
          <p className="mt-1 max-w-prose text-2xs text-muted-foreground">
            {note}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

function Swatch({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div
        className="h-9 rounded-md border"
        style={{ backgroundColor: value }}
        aria-hidden="true"
      />
      <p className="mt-1 truncate text-2xs text-muted-foreground">{label}</p>
    </div>
  );
}

/**
 * Every primitive, in every variant, in one theme.
 *
 * Rendered twice by the page — once bare and once inside `.dark`. That nesting
 * only works because the dark variant is `&:where(.dark, .dark *)`; the
 * original `&:is(.dark *)` excluded the `.dark` element itself, so a scoped
 * dark region like this one would have rendered light components on a dark
 * ground. Side-by-side theming is the payoff for that fix.
 */
export function Gallery({ dark }: { dark: boolean }) {
  return (
    <div className="space-y-10 bg-background p-6 text-foreground">
      <header>
        <h1 className="text-lg font-semibold">
          {dark ? "Dark" : "Light"} theme
        </h1>
        <p className="mt-1 text-2xs text-muted-foreground">
          Every value below is resolved live from the tokens, not transcribed.
        </p>
      </header>

      <Section
        title="Contrast"
        note="Measured in the browser through a canvas, so the figures cannot go stale when a token is retuned."
      >
        <ContrastTable dark={dark} />
      </Section>

      <Section title="Surfaces">
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
          {SURFACE_TOKENS.map((t) => (
            <Swatch key={t} label={t} value={`var(--${t})`} />
          ))}
        </div>
      </Section>

      <Section
        title="Status families"
        note="Each is a quartet: text, surface, border, solid. Brand colour never appears here — status and identity are disjoint."
      >
        <div className="space-y-2">
          {STATUS_FAMILIES.map((f) => (
            <div key={f} className="grid grid-cols-4 gap-2">
              {["", "-surface", "-border", "-solid"].map((suffix) => (
                <Swatch
                  key={suffix}
                  label={`${f}${suffix || ""}`}
                  value={`var(--${f}${suffix})`}
                />
              ))}
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="Chart tokens"
        note="Eight categorical slots, because there are eight gate statuses."
      >
        <div className="grid grid-cols-8 gap-2">
          {CHART.series.map((v, i) => (
            <Swatch key={i} label={`chart-${i + 1}`} value={v} />
          ))}
        </div>
      </Section>

      <Section
        title="Gate status colour"
        note="Green means approved, never merely ready. All eight are distinct and all clear 3:1 against the card — but the ringed one is separated by more than colour, because depth alone got it only 1.4:1 from in_progress in this theme."
      >
        <div className="grid grid-cols-4 gap-2">
          {GATE_STATUSES.map((s) => (
            <div key={s} className="min-w-0">
              <div
                aria-hidden="true"
                className={
                  "flex h-9 items-center justify-center rounded-md border" +
                  (needsDecision(s) ? " ring-2 ring-foreground/70 ring-inset" : "")
                }
                style={{ backgroundColor: statusColor(s) }}
              >
                {needsDecision(s) && (
                  <span className="size-1.5 rounded-full bg-foreground/80" />
                )}
              </div>
              <p className="mt-1 truncate text-2xs text-muted-foreground">{s}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type scale">
        <div className="space-y-1">
          {TYPE_STEPS.map(([cls, rem]) => (
            <div key={cls} className="flex items-baseline gap-3">
              <code className="type-mono w-24 shrink-0 text-2xs text-muted-foreground">
                {cls}
              </code>
              <span className={cls}>Grid 480 mg extended release</span>
              <span className="ml-auto text-2xs text-muted-foreground">
                {rem}
              </span>
            </div>
          ))}
          <div className="flex items-baseline gap-3 pt-2">
            <code className="type-mono w-24 shrink-0 text-2xs text-muted-foreground">
              type-label
            </code>
            <span className="type-label">Uppercase label</span>
          </div>
          <div className="flex items-baseline gap-3">
            <code className="type-mono w-24 shrink-0 text-2xs text-muted-foreground">
              type-mono
            </code>
            <span className="type-mono">G1-PM-001 · 0123456789</span>
          </div>
          <div className="flex items-baseline gap-3">
            <code className="type-mono w-24 shrink-0 text-2xs text-muted-foreground">
              metric
            </code>
            <span className="metric text-lg">94.4%</span>
          </div>
        </div>
      </Section>

      <Section title="Elevation">
        <div className="grid grid-cols-4 gap-3">
          {["shadow-e1", "shadow-e2", "shadow-e3", "shadow-e4"].map((s) => (
            <div
              key={s}
              className={`rounded-lg border bg-card p-3 text-2xs ${s}`}
            >
              {s}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Badge">
        <div className="flex flex-wrap gap-2">
          {BADGES.map((v) => (
            <Badge key={v} variant={v}>
              {v}
            </Badge>
          ))}
        </div>
      </Section>

      <Section title="Button">
        <div className="space-y-2">
          {(["default", "sm", "lg"] as const).map((size) => (
            <div key={size} className="flex flex-wrap items-center gap-2">
              <code className="type-mono w-16 shrink-0 text-2xs text-muted-foreground">
                {size}
              </code>
              {BUTTON_VARIANTS.map((v) => (
                <Button key={v} variant={v} size={size}>
                  {v}
                </Button>
              ))}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <code className="type-mono w-16 shrink-0 text-2xs text-muted-foreground">
              disabled
            </code>
            {BUTTON_VARIANTS.map((v) => (
              <Button key={v} variant={v} disabled>
                {v}
              </Button>
            ))}
          </div>
        </div>
      </Section>

      <Section title="Card variants">
        <div className="grid gap-3 sm:grid-cols-5">
          {CARD_VARIANTS.map((v) => (
            <Card key={v} variant={v}>
              <CardContent className="py-4 text-2xs">{v}</CardContent>
            </Card>
          ))}
        </div>
      </Section>

      <Section title="Card tones">
        <div className="grid gap-3 sm:grid-cols-5">
          {CARD_TONES.map((t) => (
            <Card key={t} variant="flush" tone={t}>
              <CardContent className="py-4 text-2xs">{t}</CardContent>
            </Card>
          ))}
        </div>
      </Section>

      <Section title="Progress tones">
        <div className="space-y-2">
          {PROGRESS_TONES.map((t) => (
            <div key={t} className="flex items-center gap-3">
              <code className="type-mono w-16 shrink-0 text-2xs text-muted-foreground">
                {t}
              </code>
              <Progress value={64} tone={t} valueText={`64 percent, ${t}`} />
            </div>
          ))}
        </div>
      </Section>

      <Section title="Status badges">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {GATE_STATUSES.map((s) => (
              <GateStatusBadge key={s} status={s} />
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {REQUIREMENT_STATUSES.map((s) => (
              <RequirementStatusBadge key={s} status={s} />
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            <ReadyVerdict isReady={false} blockerCount={2} />
            <ReadyVerdict isReady blockerCount={0} />
          </div>
        </div>
      </Section>

      <Section
        title="Readiness — the case this product exists for"
        note="96% is not ready and draws amber; 87.5% is ready and draws green. The higher number is the amber one. If these ever swap, the product rule has been broken."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="py-5">
              <GateReadiness readiness={NOT_READY} blockers={BLOCKERS} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="py-5">
              <GateReadiness readiness={READY} blockers={[] as never} />
            </CardContent>
          </Card>
        </div>
      </Section>

      <Section title="Form controls">
        <div className="grid gap-3 sm:grid-cols-3">
          <Input placeholder="Input" />
          <NativeSelect defaultValue="a">
            <option value="a">Native select</option>
            <option value="b">Second option</option>
          </NativeSelect>
          <Input placeholder="Disabled" disabled />
          <Textarea placeholder="Textarea" rows={2} className="sm:col-span-2" />
          <Skeleton className="h-9" />
        </div>
      </Section>
    </div>
  );
}
