"use client";

/**
 * The statistical review panel: three sections, three kinds of authority.
 *
 * WHY THE SECTIONS ARE SEPARATED VISUALLY AND NOT JUST LOGICALLY
 *
 *   A. Deterministic system checks   what the application verified. Facts.
 *   B. AI-assisted analysis          what a language model thinks. Advisory.
 *   C. Human decision                the only thing that decides anything.
 *
 * A confident paragraph of model prose sitting flush against a table of
 * verified hashes reads as equally authoritative, so B carries its own heading,
 * its own border, and a label on every screen it appears on. The label is not a
 * footnote — a reader who skims will read the recommendation and skip a legend.
 *
 * WHAT THE BROWSER DOES NOT DECIDE
 *
 * Whether the decision form appears at all comes from the server
 * (`authorization.authorized`). A caller who edited that flag locally would
 * still be refused by the endpoint, which resolves the reviewer from the
 * authenticated session and never from anything the page sends.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type AIResponse = {
  summary: string;
  evidence_strengths: string[];
  evidence_limitations: string[];
  detected_discrepancies: string[];
  regulatory_concerns: string[];
  statistical_concerns: string[];
  recommendation: string;
  recommendation_reason: string;
  confidence: string;
  requires_human_review: boolean;
};

type AIReview = {
  id: string;
  succeeded: boolean;
  recommendation: string | null;
  confidence: string | null;
  response: AIResponse | null;
  failure_reason: string | null;
  generated_at: string | null;
  prompt_version: string | null;
};

type HumanReview = {
  id: string;
  reviewer_role_key: string;
  decision: string;
  notes: string;
  decided_at: string;
  evidence_snapshot_hash: string;
  ai_recommendation_at_time: string | null;
};

type Attestation = {
  operator_name: string;
  operator_organization: string;
  sas_version: string | null;
  operating_environment: string | null;
  executed_at: string | null;
  attested_at: string | null;
  attestation_version: string;
  attestation_hash: string;
};

type EvidenceReport = {
  evidence_origin: string;
  is_regulatory_evidence: boolean;
  banner: string | null;
  package: Record<string, string | number | null>;
  execution: {
    sas_version: string | null;
    execution_timestamp: string | null;
    operator_attestations: Attestation[];
    attestation_limitation: string;
  };
  decision_semantics: {
    accepted_means: string;
    accepted_does_not_mean: string[];
  };
};

type ReviewContext = {
  run_id: string;
  status: string;
  evidence_report: EvidenceReport;
  evidence_origin: string;
  is_regulatory_evidence: boolean;
  deterministic: {
    comparison: {
      integrity?: Record<string, string | boolean | null>;
      status?: string;
    } | null;
    sas_version: string | null;
    convergence_status: string | null;
    warnings: string[];
  };
  ai_review: AIReview | null;
  advisory_label: string;
  authorization: {
    authorized: boolean;
    role: string | null;
    reason: string;
    required_roles: string[];
    how_to_grant: string;
  };
  preconditions: { acceptable: boolean; blocking: string[] };
  acknowledgement: { version: string; text: string };
  acceptance_meaning: string;
  human_reviews: HumanReview[];
};

async function call(path: string, init?: RequestInit) {
  const response = await fetch(`/api${path}`, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    if (detail && Array.isArray(detail.failures)) {
      throw new Error(detail.failures.join("\n"));
    }
    throw new Error(
      typeof detail === "string"
        ? detail
        : (detail?.message ?? `Request failed (${response.status})`),
    );
  }
  return body;
}

const humanReadable = (value: string) => value.replace(/_/g, " ");

export function StatisticalReview({ runId }: { runId: string }) {
  const [context, setContext] = useState<ReviewContext | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [decided, setDecided] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setContext(await call(`/sas-validation/runs/${runId}/review`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const requestAIReview = useCallback(async () => {
    setBusy("ai");
    setError(null);
    try {
      await call(`/sas-validation/runs/${runId}/ai-review`, { method: "POST" });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }, [runId, load]);

  const decide = useCallback(
    async (decision: "oracle_closure_accepted" | "oracle_closure_rejected") => {
      setBusy(decision);
      setError(null);
      try {
        const result = await call(`/sas-validation/runs/${runId}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, notes, acknowledged }),
        });
        setDecided(result.decision);
        setNotes("");
        setAcknowledged(false);
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(null);
      }
    },
    [runId, notes, acknowledged, load],
  );

  if (!context) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          {error ? (
            <>
              <AlertTriangle className="size-4 shrink-0 text-destructive" />
              {error}
            </>
          ) : (
            <>
              <Loader2 className="size-4 animate-spin" />
              Loading review…
            </>
          )}
        </CardContent>
      </Card>
    );
  }

  const integrity = context.deterministic.comparison?.integrity ?? {};
  const ai = context.ai_review;
  const canAccept = context.preconditions.acceptable && acknowledged;

  const report = context.evidence_report;
  const attestations = report?.execution.operator_attestations ?? [];

  return (
    <div className="space-y-4">
      {/* Before every section, because everything under it looks like a real
          result — which is exactly what a fixture is for. */}
      {report?.banner && (
        <p className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-xs font-medium">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" />
          {report.banner}
        </p>
      )}

      {/* ------------------------------------------ operator attestation --- */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-3">
          <ClipboardCheck className="size-4 shrink-0" />
          <CardTitle className="text-sm">Who ran the SAS</CardTitle>
          <Badge variant="outline">Declared, not verified</Badge>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {attestations.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No operator attestation has been recorded for this run. It is
              optional, and its absence does not block a review — but for a
              real SAS run it is the only record of who executed the package.
            </p>
          ) : (
            attestations.map((attestation) => (
              <dl
                key={attestation.attestation_hash}
                className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[12rem_1fr]"
              >
                <dt className="text-muted-foreground">Operator</dt>
                <dd>{attestation.operator_name}</dd>
                <dt className="text-muted-foreground">Organization</dt>
                <dd>{attestation.operator_organization}</dd>
                <dt className="text-muted-foreground">SAS version</dt>
                <dd className="font-mono">
                  {attestation.sas_version ?? "not reported"}
                </dd>
                <dt className="text-muted-foreground">Environment</dt>
                <dd>{attestation.operating_environment ?? "not reported"}</dd>
                <dt className="text-muted-foreground">Executed</dt>
                <dd>{attestation.executed_at ?? "not reported"}</dd>
                <dt className="text-muted-foreground">Attested</dt>
                <dd>{attestation.attested_at ?? "—"}</dd>
                <dt className="text-muted-foreground">Attestation hash</dt>
                <dd className="font-mono break-all">
                  {attestation.attestation_hash}
                </dd>
              </dl>
            ))
          )}

          {/* Shown whether or not anyone attested. Its absence is what a
              reader would otherwise take for verification. */}
          <p className="flex items-start gap-2 rounded-lg bg-muted p-3 text-xs">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            {report?.execution.attestation_limitation}
          </p>
        </CardContent>
      </Card>

      {/* ---------------------------------------- A. deterministic checks --- */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-3">
          <ShieldCheck className="size-4 shrink-0" />
          <CardTitle className="text-sm">
            Section A — Deterministic system checks
          </CardTitle>
          <Badge variant="secondary">Authoritative</Badge>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-xs text-muted-foreground">
            Computed by the application from the stored bytes. These are the
            facts a decision rests on.
          </p>

          <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[14rem_1fr]">
            {(
              [
                ["Package archive", integrity.package_integrity],
                ["Dataset provenance stamp", integrity.dataset_provenance],
                ["Validation case stamp", integrity.validation_case_stamp],
                ["Program execution", integrity.program_execution_integrity],
                ["SAS version", context.deterministic.sas_version],
                ["Convergence status", context.deterministic.convergence_status],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-mono">
                  {value == null || value === ""
                    ? "not reported"
                    : humanReadable(String(value))}
                </dd>
              </div>
            ))}
          </dl>

          {context.deterministic.warnings.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium">Log signals</p>
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {context.deterministic.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-1 rounded-lg bg-muted p-3 text-xs">
            <p className="font-medium">
              {context.preconditions.acceptable
                ? "Nothing blocks an acceptance."
                : "Acceptance is currently blocked:"}
            </p>
            {context.preconditions.blocking.length > 0 && (
              <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
                {context.preconditions.blocking.map((failure, index) => (
                  <li key={index}>{failure}</li>
                ))}
              </ul>
            )}
            <p className="pt-1 text-muted-foreground">
              A rejection is always available, whatever the evidence shows.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------- B. advisory analysis --- */}
      <Card className="border-dashed">
        <CardHeader className="flex flex-row flex-wrap items-center gap-2 space-y-0 pb-3">
          <Bot className="size-4 shrink-0" />
          <CardTitle className="text-sm">
            Section B — AI-assisted analysis
          </CardTitle>
          <Badge variant="outline">{context.advisory_label}</Badge>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!ai && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                No analysis has been requested for this run. It is optional —
                the deterministic evidence above is what a decision rests on.
              </p>
              <Button
                onClick={requestAIReview}
                disabled={busy !== null}
                variant="secondary"
                size="sm"
              >
                {busy === "ai" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Sparkles className="size-4" />
                )}
                Request advisory analysis
              </Button>
            </div>
          )}

          {ai && !ai.succeeded && (
            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span>
                {ai.failure_reason}
                <br />
                The deterministic evidence is unaffected and review may proceed.
              </span>
            </p>
          )}

          {ai?.response && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">
                  Recommends: {humanReadable(ai.response.recommendation)}
                </Badge>
                <Badge variant="outline">
                  Confidence: {ai.response.confidence}
                </Badge>
              </div>

              <p>{ai.response.summary}</p>
              <p className="text-xs text-muted-foreground">
                {ai.response.recommendation_reason}
              </p>

              {(
                [
                  ["Strengths", ai.response.evidence_strengths],
                  ["Limitations", ai.response.evidence_limitations],
                  ["Discrepancies", ai.response.detected_discrepancies],
                  ["Regulatory concerns", ai.response.regulatory_concerns],
                  ["Statistical concerns", ai.response.statistical_concerns],
                ] as const
              )
                .filter(([, items]) => items.length > 0)
                .map(([label, items]) => (
                  <div key={label} className="space-y-1">
                    <p className="text-xs font-medium">{label}</p>
                    <ul className="ml-4 list-disc space-y-0.5 text-xs text-muted-foreground">
                      {items.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}

              <p className="rounded-lg bg-muted p-3 text-xs">
                This analysis is not an approval. A qualified human reviewer
                decides, and may disagree with it in either direction.
              </p>

              <Button
                onClick={requestAIReview}
                disabled={busy !== null}
                variant="ghost"
                size="sm"
              >
                {busy === "ai" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Sparkles className="size-4" />
                )}
                Request a new analysis
              </Button>
            </>
          )}
        </CardContent>
      </Card>

      {/* ----------------------------------------------- C. human decision --- */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-3">
          <UserCheck className="size-4 shrink-0" />
          <CardTitle className="text-sm">
            Section C — Authorized human decision
          </CardTitle>
          {context.authorization.authorized && (
            <Badge variant="secondary">
              {humanReadable(context.authorization.role ?? "")}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!context.authorization.authorized ? (
            <div className="space-y-2 text-xs">
              <p className="text-muted-foreground">
                {context.authorization.reason}
              </p>
              <p className="text-muted-foreground">
                An administrator can grant a reviewer role from the server:
              </p>
              <pre className="overflow-x-auto rounded-lg bg-muted p-3 font-mono text-[11px]">
                {context.authorization.how_to_grant}
              </pre>
            </div>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {context.acceptance_meaning}
              </p>

              {/* Spelled out beside the button, not only in documentation. A
                  green "accepted" is read as a statement about the method
                  unless something on the same screen says otherwise. */}
              {report?.decision_semantics && (
                <div className="space-y-1 rounded-lg bg-muted p-3 text-xs">
                  <p className="font-medium">Accepting does NOT mean:</p>
                  <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
                    {report.decision_semantics.accepted_does_not_mean.map(
                      (item) => (
                        <li key={item}>{item}</li>
                      ),
                    )}
                  </ul>
                </div>
              )}

              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium">
                  Review notes (required for both decisions)
                </span>
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={4}
                  className="w-full rounded-lg border bg-background p-2 text-sm"
                  placeholder="What did you weigh, and why?"
                />
              </label>

              <label className="flex items-start gap-2 rounded-lg bg-muted p-3 text-xs">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  className="mt-0.5 size-4 shrink-0"
                />
                <span>{context.acknowledgement.text}</span>
              </label>

              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => decide("oracle_closure_accepted")}
                  disabled={busy !== null || !canAccept || notes.trim() === ""}
                  size="sm"
                >
                  {busy === "oracle_closure_accepted" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="size-4" />
                  )}
                  Accept as oracle evidence
                </Button>

                <Button
                  onClick={() => decide("oracle_closure_rejected")}
                  disabled={busy !== null || notes.trim() === ""}
                  variant="secondary"
                  size="sm"
                >
                  {busy === "oracle_closure_rejected" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <AlertTriangle className="size-4" />
                  )}
                  Reject
                </Button>
              </div>

              {!context.preconditions.acceptable && (
                <p className="text-xs text-muted-foreground">
                  Acceptance is disabled because Section A lists unmet
                  conditions. Rejection stays available.
                </p>
              )}
            </>
          )}

          {decided && (
            <p className="flex items-start gap-2 text-xs">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
              Recorded as {humanReadable(decided)}.
            </p>
          )}

          {error && (
            <p className="flex items-start gap-2 text-xs whitespace-pre-line text-destructive">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              {error}
            </p>
          )}

          {context.human_reviews.length > 0 && (
            <div className="space-y-2 border-t pt-3">
              <p className="text-xs font-medium">
                Recorded decisions — appended, never replaced
              </p>
              {context.human_reviews.map((review) => (
                <div key={review.id} className="space-y-0.5 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">
                      {humanReadable(review.decision)}
                    </Badge>
                    <span className="text-muted-foreground">
                      {humanReadable(review.reviewer_role_key)} ·{" "}
                      {review.decided_at}
                    </span>
                  </div>
                  <p className="text-muted-foreground">{review.notes}</p>
                  {review.ai_recommendation_at_time && (
                    <p className="text-muted-foreground">
                      AI recommended{" "}
                      {humanReadable(review.ai_recommendation_at_time)} at the
                      time.
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
