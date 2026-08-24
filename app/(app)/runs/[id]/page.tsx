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
} from "lucide-react";

import { AgentTimeline } from "@/components/runs/agent-timeline";
import { ReportCaveats } from "@/components/runs/report-caveats";
import { ReportIdentity } from "@/components/runs/report-identity";
import { ReviewHeldNotice } from "@/components/runs/review-held-notice";
import { SearchesTable } from "@/components/runs/searches-table";
import { SourceExplorer } from "@/components/runs/source-explorer";
import { LightMarkdown } from "@/components/chat/light-markdown";
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
import { downloadFile } from "@/lib/utils";

const CONFIDENCE_VARIANT: Record<
  string,
  "success" | "warning" | "muted" | "destructive"
> = {
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
      <Card variant="flush" tone="danger">
        <CardContent className="py-8 text-center">
          <AlertTriangle
            aria-hidden="true"
            className="mx-auto mb-3 size-8 text-danger"
          />
          <p className="font-medium text-danger">Could not load this run</p>
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
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 gap-1.5">
          <Link href="/runs">
            <ArrowLeft className="size-4" /> All runs
          </Link>
        </Button>

        <div className="flex flex-wrap items-center gap-2">
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
            <Button
              variant="outline"
              size="sm"
              onClick={handleRetry}
              disabled={acting}
            >
              <RotateCcw className="size-4" /> Retry
            </Button>
          )}
          {report.length > 0 && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportMarkdown}
              >
                <Download className="size-4" /> Markdown
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.print()}
              >
                <Printer className="size-4" /> Print / PDF
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Page level so it is visible from every tab. The printed copy is the
          second render, inside `.print-area`. */}
      {run.status === "awaiting_review" && (
        <ReviewHeldNotice className="no-print" />
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
        <Card variant="flush" tone="danger" className="no-print">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-danger"
            />
            <div className="text-sm">
              <p className="font-medium text-danger">Run failed</p>
              <p className="mt-1 text-muted-foreground">{run.error_message}</p>
            </div>
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

        {/* `forceMount` is the print fix, and it is deliberately structural
            rather than timed. Radix hides an inactive panel with the `hidden`
            attribute, and `.print-area` lives in this one — so printing from
            the Sources or Searches tab produced a document containing none of
            the report. Switching tabs inside a `beforeprint` handler would
            have raced React's commit against the browser's pagination; keeping
            the panel mounted and letting the print stylesheet reveal it cannot
            race anything. The other three panels are `no-print`. */}
        <TabsContent
          value="report"
          forceMount
          data-print-report=""
          className="mt-4 data-[state=inactive]:hidden"
        >
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
              <ReportIdentity
                run={run}
                report={report}
                evidence={evidence}
                queries={queries}
              />

              {run.status === "awaiting_review" && (
                <ReviewHeldNotice className="hidden print:block" />
              )}

              <ReportCaveats warnings={run.warnings} />

              {report.map((section) => (
                <Card key={section.id} className="print:break-inside-avoid">
                  <CardHeader className="flex-row items-baseline justify-between space-y-0 gap-3">
                    <CardTitle className="text-md">{section.title}</CardTitle>
                    {section.confidence && (
                      <Badge
                        variant={
                          CONFIDENCE_VARIANT[section.confidence] ?? "muted"
                        }
                      >
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

        <TabsContent value="sources" className="no-print mt-4">
          <SourceExplorer evidence={evidence} />
        </TabsContent>

        <TabsContent
          value="progress"
          className="no-print mt-4 grid gap-6 lg:grid-cols-2"
        >
          <Card>
            <CardHeader>
              <CardTitle className="text-md">Agents</CardTitle>
            </CardHeader>
            <CardContent>
              <AgentTimeline events={events} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-md">Activity log</CardTitle>
            </CardHeader>
            <CardContent>
              {events.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No events recorded.
                </p>
              ) : (
                <ol className="max-h-[480px] space-y-2 overflow-y-auto text-sm">
                  {events.map((event) => (
                    <li
                      key={event.id}
                      className="flex gap-2 border-b pb-2 last:border-0"
                    >
                      <span className="type-mono shrink-0 text-2xs text-muted-foreground">
                        {new Date(event.created_at).toLocaleTimeString()}
                      </span>
                      <span
                        className={
                          event.event_type === "error"
                            ? "text-danger"
                            : event.event_type === "warning"
                              ? "text-warning"
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
                <CardTitle className="text-md">
                  Provider and processing errors
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {errors.map((error) => (
                    <li key={error.id} className="rounded-lg border p-3">
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={error.is_fatal ? "destructive" : "warning"}
                        >
                          {error.error_type.replace(/_/g, " ")}
                        </Badge>
                        {error.provider && (
                          <span className="text-xs text-muted-foreground">
                            {error.provider}
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-muted-foreground">
                        {error.message}
                      </p>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="queries" className="no-print mt-4">
          <Card variant="flush">
            <CardHeader>
              <CardTitle className="text-md">Searches executed</CardTitle>
            </CardHeader>
            <CardContent>
              <SearchesTable queries={queries} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
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
