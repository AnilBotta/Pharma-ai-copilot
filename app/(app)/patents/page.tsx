"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Copy,
  Globe2,
  Landmark,
  Lightbulb,
  Link2,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Target,
  Trophy,
  Wand2,
} from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AgentRunLoader } from "@/components/shared/agent-run-loader";
import { ChartTooltip } from "@/components/shared/chart-tooltip";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_EXECUTION_STEPS, getAgent } from "@/lib/agents";
import { semaglutidePatentLandscape } from "@/lib/data";
import { cn } from "@/lib/utils";

const agent = getAgent("agent-patent")!;

const ownerColors = [
  "oklch(0.55 0.22 262)",
  "oklch(0.62 0.19 225)",
  "oklch(0.7 0.14 190)",
  "oklch(0.65 0.2 300)",
  "oklch(0.65 0.16 145)",
];

function ScoreGauge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative size-20">
        <svg viewBox="0 0 80 80" className="size-full -rotate-90">
          <circle cx="40" cy="40" r="34" fill="none" stroke="var(--muted)" strokeWidth="7" opacity="0.4" />
          <circle
            cx="40"
            cy="40"
            r="34"
            fill="none"
            stroke={color}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={`${(value / 100) * 213.6} 213.6`}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-semibold tabular-nums">{value}</span>
        </div>
      </div>
      <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
    </div>
  );
}

export default function PatentPage() {
  const [input, setInput] = React.useState("Analyze the patent landscape for Semaglutide.");
  const [running, setRunning] = React.useState(false);
  const [activeStep, setActiveStep] = React.useState(0);
  const [done, setDone] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const steps = AGENT_EXECUTION_STEPS.patent;
  const result = semaglutidePatentLandscape;

  async function runAnalysis(prompt?: string) {
    const text = (prompt ?? input).trim();
    if (!text || running) return;
    setRunning(true);
    setDone(false);
    setActiveStep(0);
    for (let i = 0; i < steps.length; i++) {
      setActiveStep(i);
      await new Promise((r) => setTimeout(r, 620 + Math.random() * 420));
    }
    setRunning(false);
    setDone(true);
  }

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(result.summary);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title={agent.name}
        description="Landscape mapping, freedom-to-operate, expiry calendars and infringement triage — grounded in 41+ global patent authorities."
        icon={agent.icon}
        actions={
          <Badge variant="info" className="gap-1.5">
            <span className="size-1.5 animate-pulse rounded-full bg-current" />
            Live · GPT-4.1 · cutoff Jul 2026
          </Badge>
        }
      />

      {/* Input */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.05 }}
        className="glass-strong rounded-2xl p-4"
      >
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Wand2 className="size-3.5 text-blue-600 dark:text-blue-400" />
              Describe the molecule or technology space
            </div>
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runAnalysis();
                }
              }}
              placeholder="e.g. Analyze the patent landscape for Semaglutide."
              className="min-h-[64px] resize-none text-[15px]"
            />
          </div>
          <Button
            size="lg"
            onClick={() => void runAnalysis()}
            disabled={running || !input.trim()}
            className="gap-2"
          >
            {running ? (
              <>
                <span className="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Analyzing…
              </>
            ) : (
              <>
                <ShieldCheck className="size-4" />
                Analyze landscape
              </>
            )}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="text-[11px] text-muted-foreground">Try:</span>
          {["Semaglutide", "DepotPep platform", "SNAC oral excipients", "Anti-HER2 ADCs"].map((s) => (
            <button
              key={s}
              onClick={() => {
                setInput(`Analyze the patent landscape for ${s}.`);
                void runAnalysis(`Analyze the patent landscape for ${s}.`);
              }}
              className="rounded-full border border-blue-500/25 bg-blue-500/5 px-2.5 py-1 text-[11px] font-medium text-blue-600 transition-colors hover:bg-blue-500/15 dark:text-blue-400"
            >
              {s}
            </button>
          ))}
        </div>
      </motion.div>

      {/* Loading */}
      {running && (
        <div className="flex justify-center py-4">
          <AgentRunLoader
            steps={steps}
            activeStep={activeStep}
            agentName={agent.name}
            agentIcon={agent.icon}
          />
        </div>
      )}

      {/* Results */}
      {done && !running && (
        <div className="space-y-6">
          {/* Hero stats */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="grid gap-4 sm:grid-cols-3"
          >
            {[
              { icon: ScrollText, label: "Patents analyzed", value: result.patentsAnalyzed.toLocaleString() },
              { icon: Globe2, label: "Jurisdictions", value: String(result.jurisdictions) },
              { icon: Link2, label: "Patent families", value: String(result.families) },
            ].map((s, i) => (
              <motion.div
                key={s.label}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.08 + i * 0.07 }}
                className="glass rounded-xl p-4"
              >
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <s.icon className="size-3.5 text-blue-600 dark:text-blue-400" />
                  {s.label}
                </div>
                <p className="mt-1.5 text-2xl font-semibold tabular-nums">{s.value}</p>
              </motion.div>
            ))}
          </motion.div>

          <div className="grid gap-6 xl:grid-cols-3">
            {/* Summary */}
            <Card className="xl:col-span-2">
              <CardHeader className="flex-row items-start justify-between">
                <CardTitle className="text-[15px]">Patent summary</CardTitle>
                <button
                  onClick={copySummary}
                  className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  {copied ? <CheckCircle2 className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </CardHeader>
              <CardContent>
                <div className="flex items-start gap-2">
                  <Landmark className="mt-0.5 size-4 shrink-0 text-blue-600 dark:text-blue-400" />
                  <div>
                    <p className="text-sm leading-relaxed">{result.summary}</p>
                    <p className="mt-3 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{result.drug}</span> · {result.molecule}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Scores */}
            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Landscape scores</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-around">
                  <ScoreGauge label="FTO freedom" value={result.score.freedom} color="oklch(0.55 0.22 262)" />
                  <ScoreGauge label="Patent density" value={result.score.density} color="oklch(0.65 0.2 300)" />
                  <ScoreGauge label="Expiry runway" value={result.score.expiry} color="oklch(0.7 0.14 190)" />
                </div>
                <p className="mt-4 text-center text-[11px] text-muted-foreground">
                  Composite of claim breadth, owner concentration and expiry pressure.
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Owners */}
            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Patent owners by share</CardTitle>
                <p className="text-xs text-muted-foreground">Active families per assignee</p>
              </CardHeader>
              <CardContent>
                <div className="h-[240px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={result.owners} layout="vertical" margin={{ left: 8, right: 8 }}>
                      <XAxis type="number" hide domain={[0, 100]} />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={92}
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip content={<ChartTooltip formatter={(v) => `${v}%`} />} cursor={{ fill: "var(--muted)", opacity: 0.4 }} />
                      <Bar dataKey="share" name="Share of families" radius={[0, 6, 6, 0]} barSize={18}>
                        {result.owners.map((_, i) => (
                          <Cell key={i} fill={ownerColors[i % ownerColors.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* Expiry calendar */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <CalendarClock className="size-4 text-blue-600 dark:text-blue-400" />
                  Estimated expiry calendar
                </CardTitle>
                <p className="text-xs text-muted-foreground">Patent counts with key family expiries</p>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.expiries.map((e, i) => (
                  <motion.div
                    key={e.year}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className="flex items-center gap-4"
                  >
                    <div className="w-14 shrink-0 text-lg font-semibold tabular-nums">
                      {e.year}
                    </div>
                    <div className="flex-1">
                      <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${(e.patents / 22) * 100}%` }}
                          transition={{ delay: 0.3 + i * 0.1, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
                          className="h-full rounded-full bg-gradient-to-r from-blue-600 to-violet-600"
                        />
                      </div>
                      <p className="mt-1.5 text-xs text-muted-foreground">{e.notes}</p>
                    </div>
                    <div className="w-16 shrink-0 text-right">
                      <p className="text-sm font-medium tabular-nums">{e.patents}</p>
                      <p className="text-[10px] text-muted-foreground">{e.families} families</p>
                    </div>
                  </motion.div>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Key claims */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <Target className="size-4 text-blue-600 dark:text-blue-400" />
                  Key claims
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {result.keyClaims.map((claim, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.07 }}
                    className="flex gap-3 rounded-lg border bg-card/60 p-3"
                  >
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-500/12 text-[10px] font-semibold text-blue-600 dark:text-blue-400">
                      {i + 1}
                    </span>
                    <p className="text-[13px] leading-relaxed">{claim}</p>
                  </motion.div>
                ))}
              </CardContent>
            </Card>

            <div className="space-y-6">
              {/* Opportunities */}
              <Card className="border-emerald-500/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-[15px]">
                    <Lightbulb className="size-4 text-emerald-600 dark:text-emerald-400" />
                    Opportunities
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2.5">
                  {result.opportunities.map((o, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.07 }}
                      className="flex gap-2.5 rounded-lg border border-emerald-500/15 bg-emerald-500/5 p-3"
                    >
                      <Trophy className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      <p className="text-[13px] leading-relaxed">{o}</p>
                    </motion.div>
                  ))}
                </CardContent>
              </Card>

              {/* Risks */}
              <Card className="border-rose-500/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-[15px]">
                    <AlertTriangle className="size-4 text-rose-600 dark:text-rose-400" />
                    Risk analysis
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2.5">
                  {result.risks.map((r, i) => (
                    <motion.div
                      key={r.title}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.07 }}
                      className="rounded-lg border p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-[13px] font-medium">{r.title}</p>
                        <Badge
                          variant={
                            r.level === "High" ? "destructive" : r.level === "Medium" ? "warning" : "success"
                          }
                          className="shrink-0"
                        >
                          {r.level}
                        </Badge>
                      </div>
                      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{r.detail}</p>
                    </motion.div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Timeline */}
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Key family timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative space-y-5 before:absolute before:top-2 before:bottom-2 before:left-[7px] before:w-px before:bg-border">
                {result.timeline.map((t, i) => (
                  <motion.div
                    key={`${t.patent}-${i}`}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className="relative flex gap-5 pl-6"
                  >
                    <span
                      className={cn(
                        "absolute top-1 left-0 size-[15px] rounded-full border-2 bg-background",
                        t.status === "Active" && "border-blue-500",
                        t.status === "Expired" && "border-emerald-500",
                        t.status === "Pending" && "border-amber-500"
                      )}
                    />
                    <div className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-sm font-medium">
                          {t.year} · {t.type}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {t.patent} — {t.owner}
                        </p>
                      </div>
                      <Badge
                        variant={
                          t.status === "Active" ? "info" : t.status === "Expired" ? "success" : "warning"
                        }
                        className="w-fit"
                      >
                        {t.status}
                      </Badge>
                    </div>
                  </motion.div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* CTA */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-blue-500/20 bg-gradient-to-r from-blue-600/10 to-violet-600/10 p-6 sm:flex-row sm:items-center"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400">
                <Sparkles className="size-5" />
              </div>
              <div>
                <p className="font-medium">Turn this into a board-ready dossier</p>
                <p className="text-xs text-muted-foreground">
                  Combine with literature and strategy into a 34-page PDF report.
                </p>
              </div>
            </div>
            <Button asChild className="gap-2">
              <Link href="/reports">
                Open Report Generator <ArrowRight className="size-4" />
              </Link>
            </Button>
          </motion.div>
        </div>
      )}
    </div>
  );
}