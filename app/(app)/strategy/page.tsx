"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Beaker,
  CalendarCheck2,
  CheckCircle2,
  ClipboardList,
  Factory,
  Flag,
  GitBranch,
  Microscope,
  Milestone,
  ShieldAlert,
  Target,
  Wand2,
} from "lucide-react";

import { AgentRunLoader } from "@/components/shared/agent-run-loader";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AGENT_EXECUTION_STEPS, getAgent } from "@/lib/agents";
import { buildStrategyOutput } from "@/lib/data";
import type { StrategyInput, StrategyOutput } from "@/lib/types";
import { cn } from "@/lib/utils";

const agent = getAgent("agent-strategy")!;

const diseases = ["Type 2 Diabetes", "Obesity", "Osteoporosis", "Parkinson's Disease", "Solid Tumors", "Rare Endocrine"];
const targets = ["GLP-1 Receptor", "SGLT2", "PTH1R", "HER2", "LRRK2", "GIP/GLP-1 Dual"];
const dosageForms = ["Oral tablet", "Subcutaneous injection", "Depot microsphere", "In situ hydrogel", "Nasal spray"];
const routes = ["Oral", "Subcutaneous", "Intramuscular", "Nasal", "Transdermal"];

const cqaCriticality = {
  Critical: "destructive",
  Key: "warning",
  "Non-Critical": "secondary",
} as const;

function RiskMatrix({ output }: { output: StrategyOutput }) {
  const levels = [1, 2, 3, 4, 5];
  const colorFor = (l: number, i: number) => {
    const product = l * i;
    if (product >= 12) return "bg-rose-500/70";
    if (product >= 6) return "bg-amber-400/70";
    return "bg-emerald-400/50";
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-6 gap-1.5">
        <div className="flex items-end justify-center pb-1 text-[10px] text-muted-foreground">
          Impact →
        </div>
        {levels.map((l) => (
          <div key={`top-${l}`} className="text-center text-[10px] text-muted-foreground">
            {l}
          </div>
        ))}
        {levels.map((i) => (
          <React.Fragment key={i}>
            <div className="flex items-center justify-center text-[10px] text-muted-foreground">
              {i}
            </div>
            {levels.map((l) => (
              <div
                key={`${i}-${l}`}
                className={cn(
                  "flex aspect-[2/1] items-center justify-center rounded-md text-[9px] font-semibold text-white/90",
                  colorFor(l, i)
                )}
              >
                {l * i}
              </div>
            ))}
          </React.Fragment>
        ))}
      </div>
      <p className="text-center text-[11px] text-muted-foreground">
        Likelihood (rows) × Impact (columns) — 5×5 heat matrix
      </p>
      <div className="space-y-2.5">
        {output.risks.map((r, idx) => (
          <motion.div
            key={r.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.06 }}
            className="flex items-start gap-3 rounded-lg border p-3"
          >
            <div className="flex size-7 shrink-0 flex-col items-center justify-center rounded-md bg-muted text-[9px] leading-none">
              <span className="font-semibold">{r.likelihood}</span>
              <span className="text-muted-foreground">×{r.impact}</span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[13px] font-medium">{r.risk}</p>
                <Badge variant="secondary" className="text-[10px]">
                  {r.category}
                </Badge>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">Mitigation:</span> {r.mitigation}
              </p>
            </div>
            <Badge
              variant={r.likelihood * r.impact >= 12 ? "destructive" : r.likelihood * r.impact >= 6 ? "warning" : "success"}
              className="shrink-0"
            >
              {r.likelihood * r.impact >= 12 ? "High" : r.likelihood * r.impact >= 6 ? "Medium" : "Low"}
            </Badge>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

export default function StrategyPage() {
  const [form, setForm] = React.useState<StrategyInput>({
    disease: "Type 2 Diabetes",
    target: "GLP-1 Receptor",
    dosageForm: "Oral tablet",
    route: "Oral",
  });
  const [running, setRunning] = React.useState(false);
  const [activeStep, setActiveStep] = React.useState(0);
  const [done, setDone] = React.useState(false);
  const [output, setOutput] = React.useState<StrategyOutput | null>(null);
  const steps = AGENT_EXECUTION_STEPS.strategy;

  async function runStrategy() {
    if (running) return;
    setRunning(true);
    setDone(false);
    setActiveStep(0);
    for (let i = 0; i < steps.length; i++) {
      setActiveStep(i);
      await new Promise((r) => setTimeout(r, 600 + Math.random() * 400));
    }
    setOutput(buildStrategyOutput(form));
    setRunning(false);
    setDone(true);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title={agent.name}
        description="Phase-gate roadmaps, QbD CQA matrices, manufacturing and analytical strategy with risk scoring."
        icon={agent.icon}
        actions={
          <Badge variant="warning" className="gap-1.5">
            <span className="size-1.5 rounded-full bg-current" />
            Beta · GPT-4.1
          </Badge>
        }
      />

      {/* Input form */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay: 0.05 }}
        className="glass-strong rounded-2xl p-5"
      >
        <div className="mb-4 flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Wand2 className="size-3.5 text-blue-600 dark:text-blue-400" />
          Define the target product profile
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="disease">Disease</Label>
            <Select value={form.disease} onValueChange={(v) => setForm((f) => ({ ...f, disease: v }))}>
              <SelectTrigger id="disease" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {diseases.map((d) => (
                  <SelectItem key={d} value={d}>{d}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="target">Biological target</Label>
            <Select value={form.target} onValueChange={(v) => setForm((f) => ({ ...f, target: v }))}>
              <SelectTrigger id="target" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {targets.map((t) => (
                  <SelectItem key={t} value={t}>{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="form">Dosage form</Label>
            <Select value={form.dosageForm} onValueChange={(v) => setForm((f) => ({ ...f, dosageForm: v }))}>
              <SelectTrigger id="form" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {dosageForms.map((d) => (
                  <SelectItem key={d} value={d}>{d}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="route">Delivery route</Label>
            <Select value={form.route} onValueChange={(v) => setForm((f) => ({ ...f, route: v }))}>
              <SelectTrigger id="route" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {routes.map((r) => (
                  <SelectItem key={r} value={r}>{r}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="mt-5 flex items-center justify-between gap-3">
          <p className="hidden text-xs text-muted-foreground sm:block">
            Generates a complete development blueprint for{" "}
            <span className="font-medium text-foreground">
              {form.dosageForm.toLowerCase()} · {form.route.toLowerCase()} · {form.target}
            </span>
          </p>
          <Button onClick={() => void runStrategy()} disabled={running} className="ml-auto gap-2">
            {running ? (
              <>
                <span className="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Designing roadmap…
              </>
            ) : (
              <>
                <GitBranch className="size-4" />
                Generate development plan
              </>
            )}
          </Button>
        </div>
      </motion.div>

      {running && (
        <div className="flex justify-center py-4">
          <AgentRunLoader steps={steps} activeStep={activeStep} agentName={agent.name} agentIcon={agent.icon} />
        </div>
      )}

      {done && output && !running && (
        <div className="space-y-6">
          {/* Overview */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="glass relative overflow-hidden rounded-2xl p-6"
          >
            <div className="pointer-events-none absolute -top-20 right-0 size-56 rounded-full bg-blue-500/10 blur-3xl" />
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="info">{form.disease}</Badge>
              <Badge variant="secondary">{form.target}</Badge>
              <Badge variant="secondary">{form.dosageForm}</Badge>
              <Badge variant="secondary">{form.route}</Badge>
            </div>
            <p className="mt-4 max-w-3xl text-sm leading-relaxed">{output.overview}</p>
          </motion.div>

          {/* Roadmap */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <Milestone className="size-4 text-blue-600 dark:text-blue-400" />
                Development roadmap — phase-gate model
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative space-y-6 before:absolute before:top-3 before:bottom-3 before:left-[15px] before:w-px before:bg-gradient-to-b before:from-blue-500/50 before:via-border before:to-border">
                {output.roadmap.map((phase, i) => (
                  <motion.div
                    key={phase.phase}
                    initial={{ opacity: 0, x: -12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.1 }}
                    className="relative pl-12"
                  >
                    <div className="absolute top-0 left-0 flex size-8 items-center justify-center rounded-full border-2 border-blue-500 bg-background text-blue-600 dark:text-blue-400">
                      <span className="text-[11px] font-semibold">{i + 1}</span>
                    </div>
                    <div className="rounded-xl border bg-card/70 p-4 transition-colors hover:border-blue-500/30">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold">{phase.phase}</p>
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="gap-1 text-[10px]">
                            <CalendarCheck2 className="size-3" />
                            {phase.timeframe}
                          </Badge>
                        </div>
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {phase.activities.map((a) => (
                          <div key={a} className="flex items-center gap-2 text-[13px] text-muted-foreground">
                            <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
                            {a}
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex items-start gap-2 rounded-lg border border-blue-500/15 bg-blue-500/5 px-3 py-2">
                        <Flag className="mt-0.5 size-3.5 shrink-0 text-blue-600 dark:text-blue-400" />
                        <p className="text-xs leading-relaxed text-muted-foreground">
                          <span className="font-medium text-foreground">Gate:</span> {phase.gate}
                        </p>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* CQAs */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <Target className="size-4 text-blue-600 dark:text-blue-400" />
                Critical quality attributes (QbD)
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Derived from quality risk assessment on comparable NDAs in the same modality
              </p>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">CQA</th>
                    <th className="pb-3 pr-4 font-medium">Target</th>
                    <th className="pb-3 pr-4 font-medium">Criticality</th>
                    <th className="pb-3 font-medium">Rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {output.cqas.map((cqa, i) => (
                    <motion.tr
                      key={cqa.attribute}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="border-b last:border-0 hover:bg-muted/40"
                    >
                      <td className="py-3.5 pr-4 font-medium">{cqa.attribute}</td>
                      <td className="py-3.5 pr-4 font-mono text-xs text-muted-foreground">{cqa.target}</td>
                      <td className="py-3.5 pr-4">
                        <Badge variant={cqaCriticality[cqa.criticality]}>{cqa.criticality}</Badge>
                      </td>
                      <td className="py-3.5 text-xs text-muted-foreground">{cqa.rationale}</td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          {/* Manufacturing + Analytical */}
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <Factory className="size-4 text-blue-600 dark:text-blue-400" />
                  Manufacturing strategy
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-[13px] leading-relaxed">{output.manufacturing.strategy}</p>
                <div className="space-y-2">
                  {output.manufacturing.highlights.map((h, i) => (
                    <div key={i} className="flex items-start gap-2 text-[13px] text-muted-foreground">
                      <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                      {h}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <Microscope className="size-4 text-blue-600 dark:text-blue-400" />
                  Analytical strategy
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-[13px] leading-relaxed">{output.analytical.strategy}</p>
                <div className="space-y-2">
                  {output.analytical.methods.map((m, i) => (
                    <div key={i} className="flex items-center gap-2.5 rounded-lg border bg-card/60 px-3 py-2">
                      <Beaker className="size-3.5 shrink-0 text-blue-600 dark:text-blue-400" />
                      <span className="text-[13px]">{m}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Timeline */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <ClipboardList className="size-4 text-blue-600 dark:text-blue-400" />
                Program timeline
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
                {output.timeline.map((year, i) => (
                  <motion.div
                    key={year.year}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className="rounded-xl border p-4"
                  >
                    <p className="text-lg font-semibold tabular-nums">{year.year}</p>
                    <div className="mt-3 space-y-2">
                      {year.milestones.map((m) => (
                        <div key={m.label} className="flex items-start gap-2">
                          <span
                            className={cn(
                              "mt-0.5 size-2 shrink-0 rounded-full",
                              m.status === "Done" && "bg-emerald-500",
                              m.status === "In Progress" && "bg-blue-500 animate-pulse",
                              m.status === "Planned" && "bg-muted-foreground/40"
                            )}
                          />
                          <div className="min-w-0">
                            <p className="text-[13px] leading-snug">{m.label}</p>
                            <p className="text-[10px] text-muted-foreground">{m.status}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Risk matrix */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <ShieldAlert className="size-4 text-rose-600 dark:text-rose-400" />
                Risk matrix
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                12 risks scored across likelihood and impact, with mitigations
              </p>
            </CardHeader>
            <CardContent>
              <RiskMatrix output={output} />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}