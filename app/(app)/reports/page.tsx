"use client";

import * as React from "react";
import {
  Building2,
  CheckCircle2,
  FileText,
  FileType2,
  Layers,
  Loader2,
  Printer,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Wand2,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { AGENT_EXECUTION_STEPS, getAgent } from "@/lib/agents";
import { cn, downloadFile, formatDate } from "@/lib/utils";
import { generatedReport, projects, reports } from "@/lib/data";

const agent = getAgent("agent-reports")!;

const sectionIcons = [FileText, ShieldCheck, GitBranch, Microscope, ShieldAlert];

function ReportDocument() {
  return (
    <div className="mx-auto max-w-[760px] space-y-6 bg-white px-8 py-10 text-slate-800 shadow-sm dark:bg-white dark:text-slate-800">
      {/* Cover header */}
      <div className="rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 p-6 text-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-[11px] font-medium opacity-80">
            <Building2 className="size-3.5" />
            PharmaLabs Research Co. · R&D Intelligence
          </div>
          <Badge className="border-white/30 bg-white/10 text-white">v2.3 · CONFIDENTIAL</Badge>
        </div>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">{generatedReport.title}</h1>
        <p className="mt-2 text-xs text-white/80">
          Generated {formatDate(generatedReport.generated)} · {" "}
          {projects.find((p) => p.id === generatedReport.projectId)?.name ?? "All programs"} ·{" "}
          {generatedReport.sections.length} sections · 34 pages
        </p>
      </div>

      {/* Sections */}
      {generatedReport.sections.map((section, i) => {
        const Icon = sectionIcons[i] ?? FileText;
        return (
          <section key={section.id} className="rounded-xl border border-slate-200 bg-white p-6">
            <div className="flex items-center gap-3 border-b border-slate-100 pb-3">
              <div className="flex size-8 items-center justify-center rounded-lg bg-blue-600/10 text-blue-700">
                <Icon className="size-4" />
              </div>
              <div>
                <p className="text-[15px] font-semibold">{section.title}</p>
                <p className="text-[11px] text-slate-500">
                  Section {i + 1} of {generatedReport.sections.length}
                </p>
              </div>
            </div>
            <p className="mt-3 text-[13px] font-medium text-blue-700">{section.summary}</p>
            <div className="mt-3 space-y-3">
              {section.content.map((block, j) => (
                <div key={j}>
                  <p className="text-[13px] font-semibold">{block.heading}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{block.body}</p>
                  {block.bullets && (
                    <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[13px] text-slate-600">
                      {block.bullets.map((b) => (
                        <li key={b}>{b}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        );
      })}

      <div className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3 text-[11px] text-slate-500">
        <span>Prepared with Pharma AI Copilot · Research Copilot + 4 agents</span>
        <span>PharmaLabs Research Co.</span>
      </div>
    </div>
  );
}

function buildDocxHtml() {
  const body = generatedReport.sections
    .map(
      (s, i) => `
    <div style="margin-bottom:24px">
      <h2 style="font-size:16pt;font-weight:600;color:#1d4ed8;margin-bottom:8px">${i + 1}. ${s.title}</h2>
      <p style="font-size:11pt;color:#1e3a8a;font-style:italic;margin-bottom:8px">${s.summary}</p>
      ${s.content
        .map(
          (b) => `<h3 style="font-size:12pt;font-weight:600;margin:8px 0 4px">${b.heading}</h3>
      <p style="font-size:11pt;color:#334155;line-height:1.5">${b.body}</p>
      ${
        b.bullets
          ? `<ul style="font-size:11pt;color:#334155">${b.bullets.map((x) => `<li>${x}</li>`).join("")}</ul>`
          : ""
      }`
        )
        .join("")}
    </div>`
    )
    .join("");

  return `<!DOCTYPE html>
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head><meta charset="utf-8"><title>${generatedReport.title}</title></head>
<body>
  <h1 style="font-size:20pt;font-weight:700;color:#111827">${generatedReport.title}</h1>
  <p style="font-size:10pt;color:#64748b">PharmaLabs Research Co. · Generated ${formatDate(generatedReport.generated)} · Version ${generatedReport.version}</p>
  <hr/>
  ${body}
</body></html>`;
}

export default function ReportsPage() {
  const [projectId, setProjectId] = React.useState(generatedReport.projectId);
  const [generating, setGenerating] = React.useState(false);
  const [activeStep, setActiveStep] = React.useState(0);
  const steps = AGENT_EXECUTION_STEPS.report;
  const [exporting, setExporting] = React.useState<"pdf" | "docx" | null>(null);
  const [lastExport, setLastExport] = React.useState<string | null>(null);

  async function generateReport() {
    if (generating) return;
    setGenerating(true);
    setActiveStep(0);
    for (let i = 0; i < steps.length; i++) {
      setActiveStep(i);
      await new Promise((r) => setTimeout(r, 640 + Math.random() * 360));
    }
    setGenerating(false);
  }

  function exportPdf() {
    setExporting("pdf");
    setTimeout(() => {
      window.print();
      setExporting(null);
    }, 250);
    setLastExport("PDF");
  }

  function exportDocx() {
    setExporting("docx");
    setTimeout(() => {
      downloadFile(
        `${generatedReport.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.doc`,
        buildDocxHtml(),
        "application/msword"
      );
      setExporting(null);
      setLastExport("DOCX");
    }, 800);
  }

  const sectionTitles = ["Executive Summary", "Patent Landscape", "Development Plan", "Scientific Review", "Risk Assessment"];

  return (
    <div className="space-y-8">
      <PageHeader
        title={agent.name}
        description="Assemble board-ready PDF and DOCX intelligence dossiers from every agent in one click."
        icon={agent.icon}
        actions={
          <div className="no-print flex gap-2">
            <Button variant="outline" onClick={exportDocx} disabled={generating || !!exporting}>
              {exporting === "docx" ? <Loader2 className="size-4 animate-spin" /> : <FileType2 className="size-4" />}
              {exporting === "docx" ? "Exporting…" : "DOCX"}
            </Button>
            <Button onClick={exportPdf} disabled={generating || !!exporting}>
              {exporting === "pdf" ? <Loader2 className="size-4 animate-spin" /> : <FileType2 className="size-4" />}
              {exporting === "pdf" ? "Preparing…" : "Export PDF"}
            </Button>
          </div>
        }
      />

      <div className="no-print grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Controls */}
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Report settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Project scope</label>
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Dossier template</label>
                <Select defaultValue="board">
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="board">Board-ready (enterprise)</SelectItem>
                    <SelectItem value="investor">Investor brief</SelectItem>
                    <SelectItem value="regulatory">Regulatory annex</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button className="w-full gap-2" onClick={() => void generateReport()} disabled={generating}>
                {generating ? <Loader2 className="size-4 animate-spin" /> : <Wand2 className="size-4" />}
                {generating ? "Assembling dossier…" : "Generate report"}
              </Button>
              {lastExport && (
                <p className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="size-3.5" /> Exported {lastExport} successfully
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Sections included</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {sectionTitles.map((s, i) => (
                <div key={s} className="flex items-center gap-2.5 rounded-lg border border-blue-500/15 bg-blue-500/5 px-3 py-2">
                  <CheckCircle2 className="size-3.5 text-emerald-500" />
                  <span className="text-[13px]">{s}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    {[FileText, ShieldCheck, GitBranch, Microscope, ShieldAlert][i] ? "agent-fed" : ""}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Recent reports</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {reports.slice(0, 4).map((r) => (
                <div key={r.id} className="flex items-center gap-2.5 rounded-lg border p-2.5 transition-colors hover:border-blue-500/30">
                  <FileText className="size-4 shrink-0 text-blue-600 dark:text-blue-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{r.title}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {formatDate(r.updated)} · {r.pages} pages
                    </p>
                  </div>
                  <Badge variant={r.status === "Ready" ? "success" : r.status === "Generating" ? "warning" : "secondary"} className="text-[9px]">
                    {r.status}
                  </Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Preview */}
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between border-b py-3">
            <div className="flex items-center gap-2">
              <ScrollText className="size-4 text-blue-600 dark:text-blue-400" />
              <CardTitle className="text-[15px]">Document preview</CardTitle>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Printer className="size-3.5" />
              Print-to-PDF & DOCX export
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {generating ? (
              <div className="space-y-4 p-6">
                <div className="flex items-center gap-3">
                  <Loader2 className="size-5 animate-spin text-primary" />
                  <p className="text-sm font-medium">Assembling {generatedReport.title}…</p>
                </div>
                <div className="space-y-2">
                  {steps.map((s, i) => (
                    <div key={s} className="flex items-center gap-2.5">
                      <span
                        className={
                          i < activeStep
                            ? "text-emerald-500"
                            : i === activeStep
                              ? "animate-pulse text-blue-600 dark:text-blue-400"
                              : "text-muted-foreground/40"
                        }
                      >
                        {i < activeStep ? (
                          <CheckCircle2 className="size-3.5" />
                        ) : i === activeStep ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Layers className="size-3.5" />
                        )}
                      </span>
                      <span className={cn("text-xs", i === activeStep ? "font-medium text-foreground" : "text-muted-foreground")}>
                        {s}
                      </span>
                    </div>
                  ))}
                </div>
                <Skeleton className="h-64 w-full" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <ReportDocument />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="no-print flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-4">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-blue-600 dark:text-blue-400" />
        <p className="text-xs leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground">Print-to-PDF:</span> use the PDF button to open the print
          dialog — select “Save as PDF”. Every section is paginated and printable with company branding.
        </p>
      </div>
    </div>
  );
}

function GitBranch() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="size-4">
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="8" r="2.5" />
      <path d="M6 8.5v7M18 10.5a4 4 0 0 1-4 4H9" strokeLinecap="round" />
    </svg>
  );
}

function Microscope() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="size-4">
      <path d="M6 18h8M9 18a6 6 0 1 1 0-12h0a6 6 0 0 1 6 6h-3M15 10l4 4M3 22h6" strokeLinecap="round" />
    </svg>
  );
}

function ShieldAlert() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="size-4">
      <path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-3z" strokeLinejoin="round" />
      <path d="M12 8v4M12 15.5v.5" strokeLinecap="round" />
    </svg>
  );
}