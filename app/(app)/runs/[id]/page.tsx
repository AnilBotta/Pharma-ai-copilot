"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  Download,
  Loader2,
  Printer,
  RotateCcw,
  Search,
} from "lucide-react";

import { AgentTimeline } from "@/components/runs/agent-timeline";
import { RunStatusBadge } from "@/components/runs/run-status-badge";
import { SourceExplorer } from "@/components/runs/source-explorer";
import { LightMarkdown } from "@/components/chat/light-markdown";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  ApiError,
  getRunEvents,
  subscribeToRun,
  TERMINAL_RUN_STATUSES,
  type Evidence,
  type ReportSection,
  type RunDetail,
  type RunError,
  type RunEvent,
  type SearchQuery,
} from "@/lib/api";
import { downloadFile, formatRelative } from "@/lib/utils";

const CONFIDENCE_VARIANT: Record<string, "success" | "warning" | "muted" | "destructive"> = {
  high: "success",
  moderate: "warning",
  low: "muted",
  insufficient_evidence: "destructive",
};

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [run, setRun] = React.useState<RunDetail | null>(null);
  const [events, setEvents] = React.useState<RunEvent[]>([]);
  const [evidence, setEvidence] = React.useState<Evidence[]>([]);
  const [report, setReport] = React.useState<ReportSection[]>([]);
  const [queries, setQueries] = React.useState<SearchQuery[]>([]);
  const [errors, setErrors] = React.useState<RunError[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [acting, setActing] = React.useState(false);

  const terminal = run ? TERMINAL_RUN_STATUSES.includes(run.status) : false;

  const loadArtifacts = React.useCallback(async () => {
    const [ev, rep, qs, errs] = await Promise.all([
      api.getEvidence(id),
      api.getReport(id),
      api.getQueries(id),
      api.getErrors(id),
    ]);
    setEvidence(ev);
    setReport(rep);
    setQueries(qs);
    setErrors(errs);
  }, [id]);

  React.useEffect(() => {
    let active = true;

    api
      .getRun(id)
      .then(async (detail) => {
        if (!active) return;
        setRun(detail);
        setEvents(await getRunEvents(id));
        await loadArtifacts();
      })
      .catch((err) => {
        if (active)
          setLoadError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => active && setLoading(false));

    return () => {
      active = false;
    };
  }, [id, loadArtifacts]);

  // Live progress while the run is active. Every event shown was recorded by
  // the worker; nothing here is simulated.
  React.useEffect(() => {
    if (!run || terminal) return;

    const unsubscribe = subscribeToRun(id, {
      onEvent: (event) =>
        setEvents((prev) =>
          prev.some((e) => e.id === event.id) ? prev : [...prev, event]
        ),
      onStatus: (status) => {
        setRun((prev) => (prev ? { ...prev, status } : prev));
        // Includes `awaiting_review`. A run held for review has a full report
        // and full evidence; refusing to load them would mean the one case a
        // reader most needs to inspect is the one they cannot see.
        if (TERMINAL_RUN_STATUSES.includes(status)) {
          void api.getRun(id).then(setRun);
          void loadArtifacts();
        }
      },
    });

    return unsubscribe;
  }, [id, run, terminal, loadArtifacts]);

  async function handleCancel() {
    setActing(true);
    try {
      await api.cancelRun(id);
      setRun((prev) => (prev ? { ...prev, cancel_requested: true } : prev));
    } finally {
      setActing(false);
    }
  }

  async function handleRetry() {
    setActing(true);
    try {
      await api.retryRun(id);
      setRun(await api.getRun(id));
    } finally {
      setActing(false);
    }
  }

  function handleExportMarkdown() {
    if (!run) return;
    downloadFile(
      `research-run-${id.slice(0, 8)}.md`,
      buildMarkdown(run, report, evidence),
      "text/markdown"
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  if (loadError || !run) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="py-8 text-center">
          <AlertTriangle className="mx-auto mb-3 size-8 text-destructive" />
          <p className="font-medium text-destructive">Could not load this run</p>
          <p className="mt-1 text-sm text-muted-foreground">{loadError}</p>
          <Button asChild variant="outline" className="mt-4">
            <Link href="/runs">Back to runs</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="no-print">
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2 gap-1.5">
          <Link href="/runs">
            <ArrowLeft className="size-4" /> All runs
          </Link>
        </Button>

        <PageHeader
          title="Research run"
          description={run.original_question}
          icon={Search}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <RunStatusBadge status={run.status} />
              {!terminal && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCancel}
                  disabled={acting || run.cancel_requested}
                >
                  <Ban className="size-4" />
                  {run.cancel_requested ? "Cancelling…" : "Cancel"}
                </Button>
              )}
              {(run.status === "failed" || run.status === "cancelled") && (
                <Button variant="outline" size="sm" onClick={handleRetry} disabled={acting}>
                  <RotateCcw className="size-4" /> Retry
                </Button>
              )}
              {report.length > 0 && (
                <>
                  <Button variant="outline" size="sm" onClick={handleExportMarkdown}>
                    <Download className="size-4" /> Markdown
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => window.print()}>
                    <Printer className="size-4" /> Print / PDF
                  </Button>
                </>
              )}
            </div>
          }
        />
      </div>

      {/* A badge reading "Awaiting review" does not tell anyone what happened
          or what to do. This report failed its own verification and is one
          click from being exported and circulated, so the reason says so
          plainly and points at where the findings are written down. */}
      {run.status === "awaiting_review" && (
        <Card className="border-amber-500/40 bg-amber-500/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="space-y-1">
              <p className="text-sm font-medium">
                This report did not pass its own verification
              </p>
              <p className="text-sm text-muted-foreground">
                High-severity findings were still outstanding after the report
                was revised, so the run is held rather than reported as
                complete. The findings are listed at the top of the{" "}
                <span className="font-medium">Limitations</span> section. Treat
                every affected statement as unverified until someone has checked
                it.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {run.status === "running" && (
        <Card className="no-print">
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <Loader2 className="size-4 animate-spin text-primary" />
              <div className="flex-1">
                <div className="flex items-baseline justify-between">
                  <p className="text-sm font-medium">
                    {run.current_node
                      ? run.current_node.replace(/_/g, " ")
                      : "Starting"}
                  </p>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {run.progress_pct}%
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-500"
                    style={{ width: `${run.progress_pct}%` }}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {run.status === "failed" && run.error_message && (
        <Card className="border-destructive/40 bg-destructive/5 no-print">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <div className="text-sm">
              <p className="font-medium text-destructive">Run failed</p>
              <p className="mt-1 text-muted-foreground">{run.error_message}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {run.warnings.length > 0 && (
        <Card className="border-amber-500/40 bg-amber-500/5 no-print">
          <CardContent className="py-4">
            <p className="mb-2 text-sm font-medium">Warnings</p>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              {run.warnings.map((warning, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden>·</span>
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue={report.length > 0 ? "report" : "progress"}>
        <TabsList className="no-print">
          <TabsTrigger value="report">Report</TabsTrigger>
          <TabsTrigger value="sources">Sources ({evidence.length})</TabsTrigger>
          <TabsTrigger value="progress">Agent activity</TabsTrigger>
          <TabsTrigger value="queries">Searches ({queries.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="report" className="mt-4">
          {report.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-sm text-muted-foreground">
                {terminal
                  ? "This run produced no report."
                  : "The report appears here once the run completes."}
              </CardContent>
            </Card>
          ) : (
            <div className="print-area space-y-6">
              {report.map((section) => (
                <Card key={section.id}>
                  <CardHeader className="flex-row items-center justify-between space-y-0">
                    <CardTitle className="text-[15px]">{section.title}</CardTitle>
                    {section.confidence && (
                      <Badge variant={CONFIDENCE_VARIANT[section.confidence] ?? "muted"}>
                        {section.confidence.replace(/_/g, " ")}
                      </Badge>
                    )}
                  </CardHeader>
                  <CardContent>
                    <LightMarkdown content={section.body_markdown} />
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="sources" className="mt-4">
          <SourceExplorer evidence={evidence} />
        </TabsContent>

        <TabsContent value="progress" className="mt-4 grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Agents</CardTitle>
            </CardHeader>
            <CardContent>
              <AgentTimeline events={events} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Activity log</CardTitle>
            </CardHeader>
            <CardContent>
              {events.length === 0 ? (
                <p className="text-sm text-muted-foreground">No events recorded.</p>
              ) : (
                <ol className="max-h-[480px] space-y-2 overflow-y-auto text-sm">
                  {events.map((event) => (
                    <li key={event.id} className="flex gap-2 border-b pb-2 last:border-0">
                      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                        {new Date(event.created_at).toLocaleTimeString()}
                      </span>
                      <span
                        className={
                          event.event_type === "error"
                            ? "text-destructive"
                            : event.event_type === "warning"
                              ? "text-amber-600 dark:text-amber-400"
                              : ""
                        }
                      >
                        {event.message}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>

          {errors.length > 0 && (
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-[15px]">
                  Provider and processing errors
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {errors.map((error) => (
                    <li key={error.id} className="rounded-lg border p-3">
                      <div className="flex items-center gap-2">
                        <Badge variant={error.is_fatal ? "destructive" : "warning"}>
                          {error.error_type.replace(/_/g, " ")}
                        </Badge>
                        {error.provider && (
                          <span className="text-xs text-muted-foreground">
                            {error.provider}
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-muted-foreground">{error.message}</p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="queries" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">Searches executed</CardTitle>
            </CardHeader>
            <CardContent>
              {queries.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No searches were recorded for this run.
                </p>
              ) : (
                <ul className="space-y-3">
                  {queries.map((query) => (
                    <li key={query.id} className="rounded-lg border p-3">
                      <div className="flex items-center justify-between gap-3">
                        <Badge variant="outline">{query.provider}</Badge>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          {query.from_cache && <Badge variant="muted">cached</Badge>}
                          <span>
                            {query.status === "ok"
                              ? `${query.result_count ?? 0} results`
                              : query.status}
                          </span>
                          {query.duration_ms !== null && (
                            <span>{query.duration_ms} ms</span>
                          )}
                        </div>
                      </div>
                      <p className="mt-2 break-words font-mono text-xs">
                        {query.query_text}
                      </p>
                      {query.error && (
                        <p className="mt-1 text-xs text-destructive">{query.error}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <p className="text-xs text-muted-foreground">
        Run created {formatRelative(run.created_at)} ·{" "}
        {run.total_input_tokens + run.total_output_tokens} tokens · estimated $
        {run.estimated_cost_usd.toFixed(4)}
      </p>
    </div>
  );
}

function buildMarkdown(
  run: RunDetail,
  report: ReportSection[],
  evidence: Evidence[]
): string {
  const lines = [
    "# Pharma R&D Copilot research report",
    "",
    `**Research question.** ${run.original_question}`,
    "",
    `Generated ${new Date().toISOString()} · run ${run.id}`,
    `Sources retrieved: ${evidence.length}`,
    "",
    "---",
    "",
  ];

  for (const section of report) {
    lines.push(`## ${section.title}`, "");
    if (section.confidence) {
      lines.push(`*Confidence: ${section.confidence.replace(/_/g, " ")}*`, "");
    }
    lines.push(section.body_markdown, "");
  }

  return lines.join("\n");
}
