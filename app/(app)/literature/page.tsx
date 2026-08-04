"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  ArrowDown,
  ArrowUp,
  BookOpenCheck,
  CalendarRange,
  CheckCircle2,
  FileSearch,
  FlaskConical,
  BookOpen,
  Lightbulb,
  Newspaper,
  Search,
  ShieldAlert,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wand2,
} from "lucide-react";

import { AgentRunLoader } from "@/components/shared/agent-run-loader";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_EXECUTION_STEPS, getAgent } from "@/lib/agents";
import { depotPeptideLiterature } from "@/lib/data";


const agent = getAgent("agent-literature")!;

export default function LiteraturePage() {
  const [input, setInput] = React.useState("Review depot peptide delivery technologies.");
  const [running, setRunning] = React.useState(false);
  const [activeStep, setActiveStep] = React.useState(0);
  const [done, setDone] = React.useState(false);
  const steps = AGENT_EXECUTION_STEPS.literature;
  const result = depotPeptideLiterature;

  async function runReview(prompt?: string) {
    const text = (prompt ?? input).trim();
    if (!text || running) return;
    setRunning(true);
    setDone(false);
    setActiveStep(0);
    for (let i = 0; i < steps.length; i++) {
      setActiveStep(i);
      await new Promise((r) => setTimeout(r, 560 + Math.random() * 380));
    }
    setRunning(false);
    setDone(true);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title={agent.name}
        description="PRISMA-style systematic reviews with evidence grading, technology comparisons and research-gap detection."
        icon={agent.icon}
        actions={
          <Badge variant="info" className="gap-1.5">
            <span className="size-1.5 animate-pulse rounded-full bg-current" />
            Live · GPT-4.1 · cutoff Jun 2026
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
              Topic or technology space to review
            </div>
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runReview();
                }
              }}
              placeholder="e.g. Review depot peptide delivery technologies."
              className="min-h-[64px] resize-none text-[15px]"
            />
          </div>
          <Button size="lg" onClick={() => void runReview()} disabled={running || !input.trim()} className="gap-2">
            {running ? (
              <>
                <span className="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Reviewing…
              </>
            ) : (
              <>
                <Newspaper className="size-4" />
                Run review
              </>
            )}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="text-[11px] text-muted-foreground">Try:</span>
          {["Depot peptide delivery", "Oral insulin bioavailability", "SNAC permeation enhancers", "Lyophilized mRNA-LNP stability"].map(
            (s) => (
              <button
                key={s}
                onClick={() => {
                  setInput(`Review ${s}.`);
                  void runReview(`Review ${s}.`);
                }}
                className="rounded-full border border-blue-500/25 bg-blue-500/5 px-2.5 py-1 text-[11px] font-medium text-blue-600 transition-colors hover:bg-blue-500/15 dark:text-blue-400"
              >
                {s}
              </button>
            )
          )}
        </div>
      </motion.div>

      {running && (
        <div className="flex justify-center py-4">
          <AgentRunLoader steps={steps} activeStep={activeStep} agentName={agent.name} agentIcon={agent.icon} />
        </div>
      )}

      {done && !running && (
        <div className="space-y-6">
          {/* Stats */}
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              { icon: FileSearch, label: "Papers analyzed", value: result.papersAnalyzed.toString() },
              { icon: CalendarRange, label: "Coverage window", value: result.yearsSpan },
              { icon: BookOpen, label: "Journals screened", value: String(result.journals) },
            ].map((s, i) => (
              <motion.div
                key={s.label}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.07 }}
                className="glass rounded-xl p-4"
              >
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <s.icon className="size-3.5 text-blue-600 dark:text-blue-400" />
                  {s.label}
                </div>
                <p className="mt-1.5 text-2xl font-semibold tabular-nums">{s.value}</p>
              </motion.div>
            ))}
          </div>

          {/* Summary + confidence */}
          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <BookOpenCheck className="size-4 text-blue-600 dark:text-blue-400" />
                  Scientific summary
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed">{result.summary}</p>
                <div className="mt-4 flex items-start gap-2 rounded-lg border border-blue-500/15 bg-blue-500/5 p-3">
                  <Search className="mt-0.5 size-4 shrink-0 text-blue-600 dark:text-blue-400" />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    <span className="font-medium text-foreground">Methodology.</span> {result.methods}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Confidence score</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col items-center justify-center gap-4 pt-2">
                <div className="relative flex size-36 items-center justify-center">
                  <svg viewBox="0 0 120 120" className="size-full -rotate-90">
                    <circle cx="60" cy="60" r="50" fill="none" stroke="var(--muted)" strokeWidth="9" opacity="0.35" />
                    <circle
                      cx="60"
                      cy="60"
                      r="50"
                      fill="none"
                      stroke="oklch(0.7 0.16 150)"
                      strokeWidth="9"
                      strokeLinecap="round"
                      strokeDasharray={`${(result.confidence / 100) * 314.16} 314.16`}
                    />
                  </svg>
                  <div className="absolute flex flex-col items-center">
                    <span className="text-3xl font-semibold tabular-nums">{result.confidence}%</span>
                    <span className="text-[11px] text-muted-foreground">evidence grade</span>
                  </div>
                </div>
                <div className="w-full space-y-2">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-muted-foreground">Strong evidence</span>
                    <Badge variant="success">High</Badge>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-muted-foreground">Conflicting findings</span>
                    <Badge variant="warning">Low</Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Advantages / disadvantages */}
          <div className="grid gap-6 lg:grid-cols-2">
            <Card className="border-emerald-500/20">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <ThumbsUp className="size-4 text-emerald-600 dark:text-emerald-400" />
                  Advantages
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {result.advantages.map((a, i) => (
                  <motion.div
                    key={a.title}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.06 }}
                    className="flex gap-3 rounded-lg border border-emerald-500/15 bg-emerald-500/5 p-3"
                  >
                    <ArrowUp className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <div>
                      <p className="text-[13px] font-medium">{a.title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{a.detail}</p>
                    </div>
                  </motion.div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-rose-500/20">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-[15px]">
                  <ThumbsDown className="size-4 text-rose-600 dark:text-rose-400" />
                  Disadvantages
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {result.disadvantages.map((d, i) => (
                  <motion.div
                    key={d.title}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.06 }}
                    className="flex gap-3 rounded-lg border border-rose-500/15 bg-rose-500/5 p-3"
                  >
                    <ArrowDown className="mt-0.5 size-4 shrink-0 text-rose-600 dark:text-rose-400" />
                    <div>
                      <p className="text-[13px] font-medium">{d.title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{d.detail}</p>
                    </div>
                  </motion.div>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Technology comparison */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <FlaskConical className="size-4 text-blue-600 dark:text-blue-400" />
                Technology comparison
              </CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">Technology</th>
                    <th className="pb-3 pr-4 font-medium">Release profile</th>
                    <th className="pb-3 pr-4 font-medium">Duration</th>
                    <th className="pb-3 pr-4 font-medium">Payload</th>
                    <th className="pb-3 pr-4 font-medium">Maturity</th>
                    <th className="pb-3 font-medium">Key risks</th>
                  </tr>
                </thead>
                <tbody>
                  {result.comparison.map((c, i) => (
                    <motion.tr
                      key={c.technology}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="border-b last:border-0 hover:bg-muted/40"
                    >
                      <td className="py-3.5 pr-4 font-medium">{c.technology}</td>
                      <td className="py-3.5 pr-4 text-muted-foreground">{c.profile}</td>
                      <td className="py-3.5 pr-4 text-muted-foreground">{c.duration}</td>
                      <td className="py-3.5 pr-4 text-muted-foreground">{c.payload}</td>
                      <td className="py-3.5 pr-4">
                        <div className="flex items-center gap-2">
                          <Progress value={c.maturity} className="h-1.5 w-16" />
                          <span className="text-xs tabular-nums text-muted-foreground">{c.maturity}%</span>
                        </div>
                      </td>
                      <td className="py-3.5 text-xs text-muted-foreground">{c.risks}</td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          {/* Key publications */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <BookOpen className="size-4 text-blue-600 dark:text-blue-400" />
                Key publications
              </CardTitle>
              <p className="text-xs text-muted-foreground">Highest-confidence sources retrieved for this review</p>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {result.publications.filter((p) => p.relevant).map((p, i) => (
                <motion.div
                  key={p.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06 }}
                  className="flex items-start justify-between gap-4 rounded-lg border p-3.5 transition-colors hover:border-blue-500/30"
                >
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium leading-snug">{p.title}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {p.authors} · {p.journal}, {p.year} · DOI: {p.doi}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge variant="secondary" className="gap-1">
                      <Sparkles className="size-3 text-amber-500" />
                      {p.confidence}% conf
                    </Badge>
                    <span className="hidden text-xs text-muted-foreground sm:block">{p.citations} cites</span>
                  </div>
                </motion.div>
              ))}
            </CardContent>
          </Card>

          {/* Research gaps */}
          <Card className="border-amber-500/20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-[15px]">
                <Lightbulb className="size-4 text-amber-600 dark:text-amber-400" />
                Research gaps — where your program can lead
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              {result.gaps.map((g, i) => (
                <motion.div
                  key={g.title}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.06 }}
                  className="rounded-lg border border-amber-500/15 bg-amber-500/5 p-3.5"
                >
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <p className="text-[13px] font-medium">{g.title}</p>
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{g.detail}</p>
                </motion.div>
              ))}
            </CardContent>
          </Card>

          {/* CTA */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3 rounded-2xl border border-blue-500/20 bg-gradient-to-r from-blue-600/10 to-violet-600/10 p-5"
          >
            <CheckCircle2 className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <p className="text-sm text-muted-foreground">
              Review complete — <span className="font-medium text-foreground">184 sources graded</span>. Ask the{" "}
              <span className="font-medium text-blue-600 dark:text-blue-400">Research Copilot</span> to expand any
              section, or send this straight to the Report Generator.
            </p>
            <Button asChild variant="outline" size="sm" className="ml-auto shrink-0">
              <a href="/reports">To reports →</a>
            </Button>
          </motion.div>
        </div>
      )}
    </div>
  );
}