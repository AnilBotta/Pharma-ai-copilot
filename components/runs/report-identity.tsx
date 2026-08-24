"use client";

import { RunStatusBadge } from "@/components/runs/run-status-badge";
import { formatRelative } from "@/lib/utils";
import type {
  Evidence,
  ReportSection,
  RunDetail,
  SearchQuery,
} from "@/lib/api";

/**
 * Who this report is, printed at the top of it.
 *
 * The printed report used to carry no identification at all: the question, the
 * run id and the date were in the page header, which is `no-print`. An auditor
 * received pages of findings with nothing on them saying what was asked, when,
 * or against which run — while the Markdown export, built by `buildMarkdown`
 * in the same file, had carried exactly that header all along. This closes the
 * gap so both deliverables identify themselves.
 *
 * It is also the screen hero, so the two cannot drift apart.
 */
export function ReportIdentity({
  run,
  report,
  evidence,
  queries,
}: {
  run: RunDetail;
  report: ReportSection[];
  evidence: Evidence[];
  queries: SearchQuery[];
}) {
  const facts: [string, string][] = [
    ["Sections", String(report.length)],
    ["Sources", String(evidence.length)],
    ["Searches", String(queries.length)],
    [
      "Tokens",
      (run.total_input_tokens + run.total_output_tokens).toLocaleString(),
    ],
    ["Est. cost", `$${run.estimated_cost_usd.toFixed(4)}`],
  ];

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="type-label text-muted-foreground">
          Research report
        </span>
        <RunStatusBadge status={run.status} />
      </div>

      {/* The question is the subject of the document, so it is the heading.
          "Research run" was the heading before, which named the mechanism
          rather than the thing anybody is reading. */}
      <h1 className="max-w-3xl text-balance text-lg font-semibold tracking-tight sm:text-xl">
        {run.original_question}
      </h1>

      <dl className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        {facts.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <dt className="type-label text-muted-foreground">{label}</dt>
            <dd className="metric text-sm">{value}</dd>
          </div>
        ))}
        <div className="flex items-baseline gap-1.5">
          <dt className="type-label text-muted-foreground">Created</dt>
          <dd className="text-sm">{formatRelative(run.created_at)}</dd>
        </div>
      </dl>

      {/* Print only. On screen the run id is noise beside a readable date; on
          paper it is the only way to trace the document back to the record. */}
      <p className="hidden text-2xs text-muted-foreground print:block">
        Run <span className="type-mono">{run.id}</span> · created{" "}
        {new Date(run.created_at).toISOString()} · printed{" "}
        {new Date().toISOString()}
      </p>
    </header>
  );
}
