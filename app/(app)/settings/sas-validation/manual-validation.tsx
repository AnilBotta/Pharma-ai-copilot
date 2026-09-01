"use client";

/**
 * The manual validation controls.
 *
 * WHAT THIS COMPONENT IS CAREFUL ABOUT
 *
 * Two sentences have to survive every state this screen can be in, because
 * they are the ones a customer is most likely to get wrong:
 *
 *   - running the package needs no SAS credentials from us
 *   - uploading a result does not validate or approve anything
 *
 * The second is repeated on the comparison itself rather than only in the
 * introduction, because that is where someone reading a table of matching
 * numbers is most likely to conclude otherwise.
 *
 * Reference values are never rendered as bare numbers. Each carries its
 * evidence status, so 102.26 (published by EMA) and 19.8906 (our own
 * candidate) cannot look equally authoritative on a screen.
 */

import { useCallback, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileUp,
  Loader2,
  Package,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { StatisticalReview } from "./statistical-review";

const CASE_ID = "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II";

type GeneratedPackage = {
  package_id: string;
  case_id: string;
  filename: string;
  archive_sha256: string;
  archive_bytes: number;
  dataset_sha256: string;
  n_observations: number;
  be_stats_version: string;
};

type Reference = {
  quantity: string;
  value: number | null;
  evidence_status: string;
  regulator_confirmed: boolean;
  source: string;
  note: string;
};

/**
 * Three separate integrity answers.
 *
 * Rendered as three rows rather than one "verified" badge, because they are
 * three different questions. In particular `program_execution_integrity` is
 * `unverified_manual_execution` for every manual run — the application cannot
 * prove which validate.sas a customer executed — and showing a single green
 * tick would tell a reviewer something untrue.
 */
type Integrity = {
  package_integrity: string;
  dataset_provenance: string;
  validation_case_stamp: string;
  program_execution_integrity: string;
  program_execution_is_failure: boolean;
  qualification: string | null;
};

type Comparison = {
  status: string;
  sas_version: string | null;
  integrity: Integrity;
  quantities: {
    quantity: string;
    sas_value: number | null;
    engine_value: number | null;
    agreement: string;
  }[];
  reference_context: Reference[];
  reviewer_question: string;
  notes: string[];
};

type UploadResponse = {
  run_id: string;
  status: string;
  detail: string;
  duplicate: boolean;
  comparison: Comparison | null;
};

/** The stages a customer moves through, so progress is legible at a glance. */
const STAGES = [
  "Package generated",
  "Awaiting SAS execution",
  "Result uploaded",
  "Evidence verified",
  "Comparison ready",
  "Statistical review required",
] as const;

function stageIndex(pkg: GeneratedPackage | null, upload: UploadResponse | null) {
  if (!pkg) return -1;
  if (!upload) return 1;
  if (upload.status === "hash_mismatch" || upload.status === "incomplete") return 2;
  if (!upload.comparison) return 3;
  return 5;
}

async function call(path: string, init?: RequestInit) {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : (body.detail?.message ?? `Request failed (${response.status})`),
    );
  }
  return response.json();
}

function evidenceLabel(reference: Reference) {
  if (reference.regulator_confirmed) return "Regulator published";
  if (reference.evidence_status === "independent_candidate") {
    return "Independent candidate — not regulator-confirmed";
  }
  return "External implementation — not regulator-confirmed";
}

export function ManualValidation() {
  const [pkg, setPackage] = useState<GeneratedPackage | null>(null);
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const resultInput = useRef<HTMLInputElement>(null);
  const logInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    setBusy("generate");
    setError(null);
    try {
      setPackage(
        await call("/sas-validation/packages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ validation_case_id: CASE_ID }),
        }),
      );
      setUpload(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }, []);

  const download = useCallback(async () => {
    if (!pkg) return;
    setBusy("download");
    setError(null);
    try {
      const { download_url } = await call(
        `/sas-validation/packages/${pkg.package_id}/download`,
      );
      // A short-lived signed link to private storage. Opened rather than
      // fetched, so the browser handles the attachment.
      window.location.href = download_url;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }, [pkg]);

  const uploadResult = useCallback(
    async (file: File) => {
      if (!pkg) return;
      setBusy("result");
      setError(null);
      try {
        const form = new FormData();
        form.append("file", file);
        setUpload(
          await call(`/sas-validation/packages/${pkg.package_id}/result`, {
            method: "POST",
            body: form,
          }),
        );
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(null);
      }
    },
    [pkg],
  );

  const uploadLog = useCallback(
    async (file: File) => {
      if (!upload) return;
      setBusy("log");
      setError(null);
      try {
        const form = new FormData();
        form.append("file", file);
        const response = await call(
          `/sas-validation/runs/${upload.run_id}/log`,
          { method: "POST", body: form },
        );
        setUpload({ ...upload, status: response.status, detail: response.detail });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(null);
      }
    },
    [upload],
  );

  const current = stageIndex(pkg, upload);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Manual validation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <p className="text-muted-foreground">
            You run this package in your organization&apos;s SAS environment.
            The application does not need your SAS username, password, or
            license key.
          </p>

          <ol className="space-y-1.5">
            {STAGES.map((stage, index) => (
              <li key={stage} className="flex items-center gap-2">
                <span
                  className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] ${
                    index <= current
                      ? "bg-foreground text-background"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {index + 1}
                </span>
                <span
                  className={
                    index <= current ? "font-medium" : "text-muted-foreground"
                  }
                >
                  {stage}
                </span>
              </li>
            ))}
          </ol>

          <div className="flex flex-wrap gap-2">
            <Button onClick={generate} disabled={busy !== null} size="sm">
              {busy === "generate" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Package className="size-4" />
              )}
              Generate validation package
            </Button>

            <Button
              onClick={download}
              disabled={!pkg || busy !== null}
              variant="secondary"
              size="sm"
            >
              {busy === "download" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Download className="size-4" />
              )}
              Download package
            </Button>

            {/* A hidden input driven by a real <Button>, rather than a
                <Button asChild> wrapping a <span> inside a <label>. The latter
                type-checks and renders, but `disabled` on a span is cosmetic:
                the label still forwards the click and the picker still opens.
                A control that looks disabled and is not is worse than one that
                looks enabled. */}
            <Button
              onClick={() => resultInput.current?.click()}
              disabled={!pkg || busy !== null}
              variant="secondary"
              size="sm"
            >
              {busy === "result" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <FileUp className="size-4" />
              )}
              Upload SAS result
            </Button>
            <input
              ref={resultInput}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadResult(file);
                event.target.value = "";
              }}
            />

            <Button
              onClick={() => logInput.current?.click()}
              disabled={!upload || busy !== null}
              variant="secondary"
              size="sm"
            >
              {busy === "log" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <FileUp className="size-4" />
              )}
              Upload SAS log
            </Button>
            <input
              ref={logInput}
              type="file"
              accept=".log,.txt,text/plain"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadLog(file);
                event.target.value = "";
              }}
            />
          </div>

          {error && (
            <p className="flex items-start gap-2 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              {error}
            </p>
          )}

          {pkg && (
            <dl className="grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-[10rem_1fr]">
              <dt>Package</dt>
              <dd className="font-mono">{pkg.package_id.slice(0, 32)}…</dd>
              <dt>Archive SHA-256</dt>
              <dd className="font-mono break-all">{pkg.archive_sha256}</dd>
              <dt>Observations</dt>
              <dd>{pkg.n_observations}</dd>
              <dt>Engine version</dt>
              <dd>be-stats {pkg.be_stats_version}</dd>
            </dl>
          )}
        </CardContent>
      </Card>

      {upload && (
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 space-y-0 pb-3">
            <CardTitle className="text-sm">Comparison</CardTitle>
            <Badge variant={upload.comparison ? "secondary" : "outline"}>
              {upload.status.replace(/_/g, " ")}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <p className="text-muted-foreground">{upload.detail}</p>

            {upload.duplicate && (
              <p className="text-xs text-muted-foreground">
                These exact bytes were already uploaded for this run, so the
                existing evidence was kept rather than duplicated.
              </p>
            )}

            {upload.comparison && (
              <>
                <div className="space-y-1.5">
                  <p className="text-xs font-medium">Evidence integrity</p>
                  {(
                    [
                      ["Package archive", upload.comparison.integrity.package_integrity],
                      [
                        "Dataset provenance stamp",
                        upload.comparison.integrity.dataset_provenance,
                      ],
                      [
                        "Validation case stamp",
                        upload.comparison.integrity.validation_case_stamp,
                      ],
                      [
                        "Program execution",
                        upload.comparison.integrity.program_execution_integrity,
                      ],
                    ] as const
                  ).map(([label, value]) => (
                    <div
                      key={label}
                      className="flex flex-wrap items-baseline justify-between gap-2 text-xs"
                    >
                      <span className="text-muted-foreground">{label}</span>
                      <Badge
                        variant={
                          value === "verified" || value === "match"
                            ? "secondary"
                            : "outline"
                        }
                      >
                        {value.replace(/_/g, " ")}
                      </Badge>
                    </div>
                  ))}
                  {upload.comparison.integrity.qualification && (
                    <p className="pt-1 text-xs text-muted-foreground">
                      {upload.comparison.integrity.qualification}
                    </p>
                  )}
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="py-1 text-left font-medium">Quantity</th>
                        <th className="py-1 text-right font-medium">SAS</th>
                        <th className="py-1 text-right font-medium">Engine</th>
                        <th className="py-1 text-left font-medium">&nbsp;</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono tabular-nums">
                      {upload.comparison.quantities.map((q) => (
                        <tr key={q.quantity} className="border-t">
                          <td className="py-1 font-sans">{q.quantity}</td>
                          <td className="py-1 text-right">
                            {q.sas_value ?? "—"}
                          </td>
                          <td className="py-1 text-right">
                            {q.engine_value ?? "—"}
                          </td>
                          <td className="py-1 pl-2 font-sans text-muted-foreground">
                            {q.agreement.replace(/_/g, " ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="space-y-1.5">
                  <p className="text-xs font-medium">
                    Reference values — context only, not targets to match
                  </p>
                  {upload.comparison.reference_context.map((reference, index) => (
                    <div
                      key={`${reference.quantity}-${index}`}
                      className="flex flex-wrap items-baseline gap-x-2 text-xs"
                    >
                      <span className="font-mono tabular-nums">
                        {reference.quantity} ={" "}
                        {reference.value ?? "not published"}
                      </span>
                      <Badge
                        variant={
                          reference.regulator_confirmed ? "secondary" : "outline"
                        }
                      >
                        {evidenceLabel(reference)}
                      </Badge>
                    </div>
                  ))}
                </div>

                <p className="flex items-start gap-2 rounded-lg bg-muted p-3 text-xs">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                  <span>
                    Uploading a SAS result does not automatically validate or
                    approve a statistical method.{" "}
                    {upload.comparison.reviewer_question}
                  </span>
                </p>

                <p className="flex items-start gap-2 text-xs text-muted-foreground">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                  A decision on this comparison is recorded below, by an
                  authorized human reviewer.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* The review panel loads its own context, including whether this caller
          may decide at all. It is rendered only once there is a comparison to
          review — a decision against an unparsed upload would be a record of
          nothing. */}
      {upload?.comparison && <StatisticalReview runId={upload.run_id} />}
    </div>
  );
}
