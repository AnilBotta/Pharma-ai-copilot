"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Download,
  FileJson,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  statistics,
  type StatisticalDisplayStatus,
  type ValidationReport,
  type ValidationReportCapability,
} from "@/lib/api";

/**
 * Validation & Evidence — the reviewer's half of the statistics page.
 *
 * WHO THIS IS FOR
 *
 * A QA reviewer, statistician, auditor or regulatory reviewer asking what this
 * engine has actually been checked against. The catalogue above answers "can I
 * use this"; this answers "what would I have to tell an inspector".
 *
 * THE ONE THING IT MUST NOT DO
 *
 * Let a reader come away thinking an implemented method is a validated one.
 * Every capability shows its status, its qualification, and — in the same
 * visual weight — what it does NOT establish. A badge a reader sees from
 * across the room with a caveat in grey underneath is a design that lies, so
 * the caveat is body text.
 *
 * WHY IT RENDERS THE REPORT RATHER THAN THE SUMMARY
 *
 * The page and the exported document read the same object, served by
 * `/statistics/validation-report`. Assembling the view here from the other
 * endpoints would create a second place where validation truth gets composed,
 * and the one a customer read would be whichever we happened not to review.
 */

const STATUS_VARIANT: Record<StatisticalDisplayStatus, BadgeVariant> = {
  VALIDATED: "success",
  "IMPLEMENTED - VALIDATION PENDING": "warning",
  "NOT IMPLEMENTED": "muted",
};

/** Tier ids the API sends, with the label a reviewer reads. */
const TIER_LABEL: Record<string, string> = {
  tier_1a: "Tier 1A — regulator's stated algorithm or decision rule",
  tier_1b: "Tier 1B — regulator's own published numerical output",
  tier_2: "Tier 2 — published textbook or reference dataset",
  tier_3: "Tier 3 — independent implementation (not regulatory authority)",
  tier_4: "Tier 4 — internal simulation or structural check",
};

function statusBadge(status: StatisticalDisplayStatus) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "muted"} className="whitespace-nowrap">
      {status}
    </Badge>
  );
}

function CapabilityDetail({ capability }: { capability: ValidationReportCapability }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-1 py-3 text-left transition-colors hover:bg-accent/40"
      >
        <ChevronDown
          className={`mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{capability.method}</span>
            {statusBadge(capability.display_status)}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {capability.jurisdiction} · {capability.capability_id}
          </p>
        </div>
      </button>

      {open && (
        <div className="space-y-3 px-1 pb-4 pl-8 text-sm">
          <p>{capability.qualification}</p>

          {/* Same weight as the status, deliberately. */}
          <div className="rounded-md border border-dashed p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              What this does not establish
            </p>
            <p className="mt-1">{capability.does_not_establish}</p>
          </div>

          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[13rem_1fr]">
            <dt className="text-muted-foreground">Validation status</dt>
            <dd>{capability.validation_status}</dd>
            <dt className="text-muted-foreground">Implementation status</dt>
            <dd>{capability.implementation_status}</dd>
            <dt className="text-muted-foreground">Produces a decision</dt>
            <dd>{capability.decision_supported ? "yes" : "no"}</dd>
            <dt className="text-muted-foreground">Submission-ready</dt>
            <dd>{capability.submission_ready ? "yes" : "no"}</dd>
            <dt className="text-muted-foreground">Design</dt>
            <dd>{capability.design}</dd>
            <dt className="text-muted-foreground">Regulatory source</dt>
            <dd>{capability.regulatory_source}</dd>
            <dt className="text-muted-foreground">Source pinned</dt>
            <dd>
              {capability.source_pinned ? (
                "yes"
              ) : (
                <span className="text-warning">
                  no — {capability.source_pinning_gap}
                </span>
              )}
            </dd>
            <dt className="text-muted-foreground">Evidence established</dt>
            <dd>{capability.established_evidence_tier}</dd>
          </dl>

          {capability.explainability.limitations.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Limitations
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                {capability.explainability.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {capability.evidence.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Evidence
              </p>
              <div className="mt-1 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1 pr-3 font-medium">Evidence</th>
                      <th className="py-1 pr-3 font-medium">Tier</th>
                      <th className="py-1 pr-3 font-medium">Authority</th>
                      <th className="py-1 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {capability.evidence.map((row) => (
                      <tr key={row.evidence_id} className="border-t align-top">
                        <td className="py-1 pr-3">{row.evidence_id}</td>
                        <td className="py-1 pr-3">
                          {row.tier}
                          <span className="block text-muted-foreground">
                            {row.tier_meaning}
                          </span>
                        </td>
                        <td className="py-1 pr-3">{row.source_authority}</td>
                        <td className="py-1">{row.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {capability.refusal_conditions.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Refuses when
              </p>
              <ul className="mt-1 space-y-1.5 text-muted-foreground">
                {capability.refusal_conditions.map((row) => (
                  <li key={row.code}>
                    <span className="text-foreground">{row.meaning}</span>{" "}
                    <span className="block text-xs">Lifted by: {row.lifted_by}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ValidationEvidence() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await statistics.validationReport());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    if (!report) return null;
    const tally: Record<string, number> = {};
    for (const capability of report.capabilities) {
      tally[capability.display_status] = (tally[capability.display_status] ?? 0) + 1;
    }
    return tally;
  }, [report]);

  const download = async (format: "json" | "markdown" | "html") => {
    setExporting(format);
    setExportError(null);
    try {
      await statistics.downloadValidationReport(format);
    } catch (caught) {
      setExportError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setExporting(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading the validation report…
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border-danger-border">
        <CardContent className="space-y-3 py-4 text-sm">
          <p className="font-medium">The validation report could not be loaded.</p>
          <p className="text-muted-foreground">{error}</p>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-3.5" />
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!report) return null;

  const coverage = report.provenance.coverage;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">Validation &amp; Evidence</h2>
          <p className="text-sm text-muted-foreground">
            What has been checked, against whose authority, and what is
            outstanding.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={exporting !== null}
            onClick={() => void download("html")}
          >
            {exporting === "html" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Globe className="size-3.5" />
            )}
            Export report (HTML)
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={exporting !== null}
            onClick={() => void download("markdown")}
          >
            {exporting === "markdown" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <FileText className="size-3.5" />
            )}
            Markdown
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={exporting !== null}
            onClick={() => void download("json")}
          >
            {exporting === "json" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <FileJson className="size-3.5" />
            )}
            JSON
          </Button>
        </div>
      </div>

      {exportError && (
        <Card className="border-danger-border">
          <CardContent className="flex items-center gap-2 py-3 text-sm">
            <Download className="size-4 shrink-0" />
            <span>{exportError}</span>
          </CardContent>
        </Card>
      )}

      {counts && (
        <Card>
          <CardContent className="flex flex-wrap gap-x-6 gap-y-2 py-4 text-sm">
            {(
              [
                "VALIDATED",
                "IMPLEMENTED - VALIDATION PENDING",
                "NOT IMPLEMENTED",
              ] as StatisticalDisplayStatus[]
            ).map((status) => (
              <div key={status} className="flex items-center gap-2">
                <span className="text-lg font-semibold tabular-nums">
                  {counts[status] ?? 0}
                </span>
                {statusBadge(status)}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm">Capabilities</CardTitle>
        </CardHeader>
        <CardContent className="py-0">
          {report.capabilities.map((capability) => (
            <CapabilityDetail
              key={capability.capability_id}
              capability={capability}
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Evidence by tier</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            {report.reading_notes.evidence_tiers}
          </p>
          {Object.entries(report.evidence_by_tier).map(([tier, records]) => (
            <div key={tier}>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {TIER_LABEL[tier] ?? tier}
              </p>
              {records.length === 0 ? (
                <p className="mt-0.5 text-muted-foreground">
                  No evidence of this tier exists in this package.
                </p>
              ) : (
                <ul className="mt-0.5 space-y-0.5">
                  {records.map((row) => (
                    <li key={row.evidence_id}>
                      <span className="font-medium">{row.evidence_id}</span>{" "}
                      <span className="text-muted-foreground">
                        · {row.source_authority} · {row.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Source provenance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-muted-foreground">{report.provenance.note}</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              Regulatory constants written by a regulator:{" "}
              <strong>{coverage.normative}</strong>, of which{" "}
              <strong>
                {coverage.normative_pinned}/{coverage.normative}
              </strong>{" "}
              are pinned to a named document, section and version.
            </li>
            <li>
              Carrying a recorded citation exception:{" "}
              {coverage.normative_exceptions} — listed below as outstanding.
            </li>
            <li>
              Values computed from those: {coverage.derived}, each stating its
              formula and its inputs.
            </li>
          </ul>
          {report.provenance.unresolved_citation_gaps.length > 0 && (
            <ul className="space-y-1 text-muted-foreground">
              {report.provenance.unresolved_citation_gaps.map((gap) => (
                <li key={gap.constant_id}>
                  <span className="text-foreground">{gap.constant_id}</span> —{" "}
                  {gap.why}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Outstanding</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">{report.limitations.note}</p>

          {report.limitations.open_blockers.map((blocker) => (
            <div key={blocker.blocker_id} className="flex gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
              <div>
                <p>{blocker.summary}</p>
                <p className="text-xs text-muted-foreground">
                  Resolved by: {blocker.required_evidence}
                </p>
              </div>
            </div>
          ))}

          {report.limitations.evidence_not_established.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Evidence not established
              </p>
              <ul className="mt-1 space-y-0.5 text-muted-foreground">
                {report.limitations.evidence_not_established.map((row) => (
                  <li key={row.evidence_id}>
                    <span className="text-foreground">{row.evidence_id}</span> ·{" "}
                    {row.tier} · {row.status}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Governance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>{report.governance.promotion_policy}</p>
          <p>{report.governance.release_gate_meaning}</p>
          <p>{report.governance.tenancy}</p>
          <p className="text-xs">
            Report {report.identity.schema} · be-stats{" "}
            {report.identity.be_stats_version} · generated{" "}
            {report.identity.generated_at}
          </p>
        </CardContent>
      </Card>
    </section>
  );
}
