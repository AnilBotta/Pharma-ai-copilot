"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  FlaskConical,
  Gavel,
  Link2,
  Loader2,
  Lock,
  Paperclip,
  ShieldCheck,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";

import { AgentAssessment } from "@/components/pdp/agent-assessment";
import {
  GateReadiness,
  GateStatusBadge,
  RequirementStatusBadge,
} from "@/components/pdp/gate-readiness";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  pdp,
  type AttachableRun,
  type ControlledDocument,
  type GateWorkspace,
  type Requirement,
} from "@/lib/api";
import { cn, formatRelative } from "@/lib/utils";

export default function GatePage() {
  const params = useParams<{ projectId: string; stageId: string }>();
  const { projectId, stageId } = params;

  const [gate, setGate] = React.useState<GateWorkspace | null>(null);
  const [runs, setRuns] = React.useState<AttachableRun[]>([]);
  const [docs, setDocs] = React.useState<ControlledDocument[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    // Always re-read the whole gate after a write. A change to one requirement
    // moves the gate's readiness and can supersede an approval elsewhere, so
    // patching a single row locally would drift from what the engine says.
    const [workspace, attachable, documents] = await Promise.all([
      pdp.getGate(stageId),
      pdp.attachableRuns(projectId),
      pdp.listDocuments(projectId),
    ]);
    setGate(workspace);
    setRuns(attachable);
    setDocs(documents);
  }, [stageId, projectId]);

  React.useEffect(() => {
    reload()
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [reload]);

  const act = React.useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      setBusy(key);
      setError(null);
      try {
        await fn();
        await reload();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [reload]
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  if (!gate) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-start gap-3 py-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <p className="text-sm text-destructive">{error ?? "Gate not found."}</p>
        </CardContent>
      </Card>
    );
  }

  const { stage, readiness, blockers, requirements, capabilities } = gate;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href={`/programmes/${projectId}`}>
            <ArrowLeft className="size-4" /> Back to programme
          </Link>
        </Button>
        <PageHeader
          title={stage.name}
          description={stage.gate_question ?? undefined}
          icon={ShieldCheck}
          actions={<GateStatusBadge status={stage.gate_status} />}
        />
      </div>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="py-5">
            <GateReadiness readiness={readiness} blockers={blockers} />
          </CardContent>
        </Card>

        <GateDecisionCard
          gate={gate}
          busy={busy === "gate"}
          onDecide={(body) => act("gate", () => pdp.decideGate(stageId, body))}
        />
      </div>

      {stage.exit_criteria && (
        <Card>
          <CardContent className="py-4">
            <p className="text-xs font-medium text-muted-foreground">Exit criteria</p>
            <p className="mt-1 text-sm">{stage.exit_criteria}</p>
          </CardContent>
        </Card>
      )}

      <UnattendedThreshold
        stage={stage}
        busy={busy === "threshold"}
        onSet={(days) =>
          act("threshold", () => pdp.setUnattendedThreshold(stageId, { days }))
        }
      />

      {/* Below the readiness card by design. The engine's verdict is read
          first; the agent's opinion is a second, weaker thing. */}
      <AgentAssessment
        stageId={stageId}
        blockerCount={readiness.blocker_count}
      />

      <div className="space-y-3">
        <h2 className="text-sm font-semibold">
          Requirements ({requirements.length})
        </h2>
        {requirements.map((req) => (
          <RequirementCard
            key={req.id}
            requirement={req}
            runs={runs}
            docs={docs}
            projectId={projectId}
            capabilities={capabilities}
            busy={busy}
            act={act}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ gate decision */

/**
 * How long this gate may sit untouched before an alert is raised.
 *
 * Shows whether the number was chosen here or inherited, because printing only
 * the effective value would make a system default look like somebody's
 * decision — and the point of an inactivity alert is that it reflects a
 * deliberate expectation about this gate's tempo.
 */
function UnattendedThreshold({
  stage,
  busy,
  onSet,
}: {
  stage: GateWorkspace["stage"];
  busy: boolean;
  onSet: (days: number | null) => void;
}) {
  const effective = stage.unattended_effective_days ?? 7;
  const inherited = stage.unattended_is_inherited ?? true;
  const [value, setValue] = React.useState(String(effective));

  React.useEffect(() => {
    setValue(String(effective));
  }, [effective]);

  const parsed = Number.parseInt(value, 10);
  const valid = Number.isFinite(parsed) && parsed >= 1 && parsed <= 365;
  const changed = valid && parsed !== effective;

  return (
    <Card>
      <CardContent className="flex flex-wrap items-end gap-4 py-4">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-xs font-medium text-muted-foreground">
            Report this gate as unattended after
          </p>
          <p className="text-sm text-muted-foreground">
            Days with no recorded activity — no evidence attached, no approval,
            no status change — before an alert is raised for the gate as a whole.
          </p>
        </div>

        <div className="flex items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor="unattended-days" className="text-xs">
              Days
            </Label>
            <Input
              id="unattended-days"
              type="number"
              min={1}
              max={365}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-24"
            />
          </div>
          <Button
            size="sm"
            disabled={busy || !changed}
            onClick={() => onSet(parsed)}
          >
            Save
          </Button>
          {!inherited && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onSet(null)}
            >
              Use default
            </Button>
          )}
        </div>

        <p className="w-full text-xs text-muted-foreground">
          {inherited
            ? `Currently ${effective} days, inherited from the system default. Changing it here affects this gate only.`
            : `Set to ${effective} days for this gate specifically.`}
        </p>
      </CardContent>
    </Card>
  );
}

function GateDecisionCard({
  gate,
  busy,
  onDecide,
}: {
  gate: GateWorkspace;
  busy: boolean;
  onDecide: (body: {
    decision: "approved" | "conditionally_approved" | "rejected" | "on_hold";
    note?: string;
    conditions?: string;
  }) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [decision, setDecision] =
    React.useState<"approved" | "conditionally_approved" | "rejected" | "on_hold">(
      "approved"
    );
  const [note, setNote] = React.useState("");
  const [conditions, setConditions] = React.useState("");

  const { readiness, capabilities, stage } = gate;

  // Open on a decision that is actually available. Defaulting to "Approve"
  // while it is disabled meant the form submitted `approved` anyway — the
  // server refused it correctly, but presenting a refusal as the default
  // outcome trains people to ignore the refusal.
  const openDialog = () => {
    setDecision(readiness.is_ready ? "approved" : "conditionally_approved");
    setOpen(true);
  };

  if (!capabilities.can_gate) {
    return (
      <Card>
        <CardContent className="flex h-full flex-col justify-center gap-2 py-5">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Lock className="size-4 text-muted-foreground" />
            Gate decision
          </div>
          <p className="text-xs text-muted-foreground">
            Gate decisions require a role with gate authority — gate committee,
            quality, regulatory, department head or executive. Your roles:{" "}
            {capabilities.role_keys.join(", ") || "none on this project"}.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="flex h-full flex-col justify-between gap-3 py-5">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Gavel className="size-4" />
            Gate decision
          </div>
          {stage.gate_decision_at ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Recorded {formatRelative(stage.gate_decision_at)}.
              {stage.gate_conditions && (
                <span className="mt-1 block">
                  <span className="font-medium text-amber-700 dark:text-amber-400">
                    Conditions:
                  </span>{" "}
                  {stage.gate_conditions}
                </span>
              )}
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              {readiness.is_ready
                ? "Every mandatory requirement is satisfied. This gate may be reviewed."
                : `${readiness.blocker_count} mandatory requirement${
                    readiness.blocker_count === 1 ? " is" : "s are"
                  } outstanding. Approval will be refused until they are satisfied — a percentage does not unlock a gate.`}
            </p>
          )}
        </div>

        <Button
          size="sm"
          variant={readiness.is_ready ? "default" : "outline"}
          onClick={openDialog}
        >
          Record a decision
        </Button>
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record a gate decision</DialogTitle>
            <DialogDescription>
              This gate is {readiness.readiness_pct.toFixed(1)}% complete with{" "}
              {readiness.blocker_count} mandatory requirement
              {readiness.blocker_count === 1 ? "" : "s"} outstanding.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="gate-decision">Decision</Label>
              <select
                id="gate-decision"
                className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                value={decision}
                onChange={(e) =>
                  setDecision(e.target.value as typeof decision)
                }
              >
                <option value="approved" disabled={!readiness.is_ready}>
                  Approve{!readiness.is_ready && " — blocked, requirements outstanding"}
                </option>
                <option value="conditionally_approved">
                  Approve with conditions
                </option>
                <option value="rejected">Reject</option>
                <option value="on_hold">Place on hold</option>
              </select>
            </div>

            {decision === "conditionally_approved" && (
              <div className="space-y-2">
                <Label htmlFor="gate-conditions">
                  Conditions <span className="text-destructive">*</span>
                </Label>
                <Textarea
                  id="gate-conditions"
                  rows={3}
                  value={conditions}
                  onChange={(e) => setConditions(e.target.value)}
                  placeholder="What must still be done, and by when."
                />
                <p className="text-xs text-muted-foreground">
                  The outstanding requirements as they stand right now are written
                  into the audit record alongside this decision.
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="gate-note">
                Note
                {(decision === "rejected" || decision === "on_hold") && (
                  <span className="text-destructive"> *</span>
                )}
              </Label>
              <Textarea
                id="gate-note"
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy}
              onClick={() => {
                onDecide({
                  decision,
                  note: note.trim() || undefined,
                  conditions: conditions.trim() || undefined,
                });
                setOpen(false);
              }}
            >
              {busy && <Loader2 className="size-4 animate-spin" />}
              Record decision
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* -------------------------------------------------------------- requirement */

function RequirementCard({
  requirement: req,
  runs,
  docs,
  projectId,
  capabilities,
  busy,
  act,
}: {
  requirement: Requirement;
  runs: AttachableRun[];
  docs: ControlledDocument[];
  projectId: string;
  capabilities: GateWorkspace["capabilities"];
  busy: string | null;
  act: (key: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [attachOpen, setAttachOpen] = React.useState(false);

  const working = busy?.startsWith(req.id) ?? false;

  return (
    <Card className={cn(req.is_satisfied && "border-emerald-500/30")}>
      <CardContent className="py-4">
        <button
          type="button"
          className="flex w-full items-start gap-3 text-left"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          // Without this the control announces as an unnamed button: its
          // visible label is assembled from nested spans and badges, which
          // does not reliably produce an accessible name.
          aria-label={`${req.ref_code} ${req.title}, ${req.status.replace(/_/g, " ")}`}
        >
          <ChevronDown
            className={cn(
              "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180"
            )}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <code className="font-mono text-xs text-muted-foreground">
                {req.ref_code}
              </code>
              <span className="text-sm font-medium">{req.title}</span>
              {req.is_mandatory ? (
                <Badge variant="outline">Mandatory</Badge>
              ) : (
                <Badge variant="muted">Optional</Badge>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <RequirementStatusBadge status={req.status} />
              <span>{req.evidence_count} evidence</span>
              {req.owner_name && <span>· {req.owner_name}</span>}
              {req.due_date && <span>· due {req.due_date}</span>}
            </div>
          </div>
        </button>

        {expanded && (
          <div className="mt-4 space-y-4 border-t pt-4">
            {req.description && <p className="text-sm">{req.description}</p>}

            {req.acceptance_criteria && (
              <div className="rounded-lg border bg-muted/30 p-3">
                <p className="text-xs font-medium text-muted-foreground">
                  Acceptance criteria
                </p>
                <p className="mt-1 text-sm">{req.acceptance_criteria}</p>
              </div>
            )}

            {req.is_blocked && req.blocked_reason && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                <span className="font-medium text-destructive">Blocked:</span>{" "}
                {req.blocked_reason}
              </div>
            )}

            {req.depends_on && req.depends_on.length > 0 && (
              <div className="text-xs">
                <p className="font-medium text-muted-foreground">Prerequisites</p>
                <ul className="mt-1 space-y-1">
                  {req.depends_on.map((d) => (
                    <li key={d.id} className="flex items-center gap-2">
                      {d.is_satisfied ? (
                        <Check className="size-3 text-emerald-600" />
                      ) : (
                        <X className="size-3 text-amber-600" />
                      )}
                      <code className="font-mono">{d.ref_code}</code>
                      <span className="text-muted-foreground">{d.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <EvidenceList
              requirement={req}
              onDetach={(id) =>
                act(`${req.id}:detach`, () => pdp.detachEvidence(id))
              }
              busy={working}
            />

            {req.current_approval && (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
                <span className="font-medium text-emerald-700 dark:text-emerald-400">
                  Approved
                </span>{" "}
                by {req.current_approval.approver_name ?? "an approver"} as{" "}
                {req.current_approval.approver_role},{" "}
                {formatRelative(req.current_approval.approved_at)}.
                {req.current_approval.comments && (
                  <span className="mt-1 block text-muted-foreground">
                    &ldquo;{req.current_approval.comments}&rdquo;
                  </span>
                )}
              </div>
            )}

            {req.acceptance_confirmed_by_name && (
              <p className="text-xs text-muted-foreground">
                Acceptance criteria confirmed by{" "}
                {req.acceptance_confirmed_by_name}. Whoever confirms cannot also
                approve.
              </p>
            )}

            <RequirementActions
              requirement={req}
              capabilities={capabilities}
              busy={working}
              onAttach={() => setAttachOpen(true)}
              act={act}
            />
          </div>
        )}
      </CardContent>

      <AttachEvidenceDialog
        open={attachOpen}
        onOpenChange={setAttachOpen}
        requirement={req}
        runs={runs}
        docs={docs}
        projectId={projectId}
        onAttach={(body) =>
          act(`${req.id}:attach`, () => pdp.attachEvidence(req.id, body))
        }
      />
    </Card>
  );
}

function EvidenceList({
  requirement: req,
  onDetach,
  busy,
}: {
  requirement: Requirement;
  onDetach: (evidenceId: string) => void;
  busy: boolean;
}) {
  if (req.evidence.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No evidence attached. Required type:{" "}
        <code className="font-mono">{req.required_evidence_type}</code>.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">Evidence</p>
      {req.evidence.map((e) => (
        <div
          key={e.id}
          className="flex items-start gap-2 rounded-lg border px-3 py-2 text-xs"
        >
          {e.evidence_type === "document" ? (
            <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" />
          ) : e.evidence_type === "research_run" ? (
            <FlaskConical className="mt-0.5 size-3.5 shrink-0 text-primary" />
          ) : e.evidence_type === "url" ? (
            <Link2 className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <StickyNote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0 flex-1">
            <p className="font-medium">
              {e.title ??
                (e.document_number
                  ? `${e.document_number} — ${e.document_title}`
                  : null) ??
                e.research_run_question ??
                e.external_url ??
                e.note}
            </p>
            <p className="text-muted-foreground">
              {e.evidence_type}
              {e.document_version_label && ` · ${e.document_version_label}`}
              {e.added_by_name && ` · ${e.added_by_name}`} ·{" "}
              {formatRelative(e.created_at)}
            </p>

            {/* A superseded document is the quiet way a gate goes stale. Say it
                where the evidence is, not only in the blocker list. */}
            {e.document_is_usable === false && (
              <p className="mt-1 rounded border border-destructive/30 bg-destructive/5 px-2 py-1 text-destructive">
                This version is {e.document_version_status} and no longer
                satisfies the requirement. Attach the current version.
              </p>
            )}

            {e.document_storage_url && (
              <a
                href={e.document_storage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                Open the document <ExternalLink className="size-3" />
              </a>
            )}
            {e.research_run_id && (
              <Link
                href={`/runs/${e.research_run_id}`}
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                Open the run <ExternalLink className="size-3" />
              </Link>
            )}
            {e.external_url && (
              <a
                href={e.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                {e.external_url} <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onDetach(e.id)}
            aria-label="Remove evidence"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ))}
      <p className="text-xs text-muted-foreground">
        Changing evidence supersedes any approval — an approval is a statement
        about one evidence set.
      </p>
    </div>
  );
}

function RequirementActions({
  requirement: req,
  capabilities,
  busy,
  onAttach,
  act,
}: {
  requirement: Requirement;
  capabilities: GateWorkspace["capabilities"];
  busy: boolean;
  onAttach: () => void;
  act: (key: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [rejectOpen, setRejectOpen] = React.useState(false);
  const [comments, setComments] = React.useState("");

  const canApprove = capabilities.can_approve;
  const acceptanceReady = req.evidence_count > 0 && !req.is_blocked;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" disabled={busy} onClick={onAttach}>
        <Paperclip className="size-3.5" /> Attach evidence
      </Button>

      {req.acceptance_confirmed_by ? (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => act(`${req.id}:accept`, () => pdp.setAcceptance(req.id, false))}
        >
          Withdraw acceptance
        </Button>
      ) : (
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !acceptanceReady}
          title={
            acceptanceReady
              ? undefined
              : "Attach evidence first — there is nothing yet for the confirmation to refer to."
          }
          onClick={() => act(`${req.id}:accept`, () => pdp.setAcceptance(req.id, true))}
        >
          <Check className="size-3.5" /> Confirm acceptance criteria
        </Button>
      )}

      {canApprove && (
        <>
          <Button
            size="sm"
            disabled={busy || !req.acceptance_confirmed_by || req.is_blocked}
            title={
              req.acceptance_confirmed_by
                ? undefined
                : "Approval agrees with a confirmed claim. There is no claim yet."
            }
            onClick={() =>
              act(`${req.id}:approve`, () =>
                pdp.decideRequirement(req.id, { decision: "approved" })
              )
            }
          >
            <ShieldCheck className="size-3.5" /> Approve
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => setRejectOpen(true)}
          >
            Request changes
          </Button>
        </>
      )}

      {req.is_blocked ? (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => act(`${req.id}:block`, () => pdp.setBlocked(req.id, false))}
        >
          Clear block
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            const reason = window.prompt("Why is this blocked?");
            if (reason?.trim()) {
              void act(`${req.id}:block`, () =>
                pdp.setBlocked(req.id, true, reason.trim())
              );
            }
          }}
        >
          Block
        </Button>
      )}

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request changes</DialogTitle>
            <DialogDescription>
              A rejection must say what needs to change. It supersedes any current
              approval.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={4}
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            placeholder="What is missing or wrong."
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!comments.trim()}
              onClick={() => {
                void act(`${req.id}:reject`, () =>
                  pdp.decideRequirement(req.id, {
                    decision: "rejected",
                    comments: comments.trim(),
                  })
                );
                setRejectOpen(false);
                setComments("");
              }}
            >
              Request changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

type EvidenceKind = "document" | "research_run" | "url" | "note";

function AttachEvidenceDialog({
  open,
  onOpenChange,
  requirement: req,
  runs,
  docs,
  projectId,
  onAttach,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  requirement: Requirement;
  runs: AttachableRun[];
  docs: ControlledDocument[];
  projectId: string;
  onAttach: (body: {
    evidence_type: EvidenceKind;
    research_run_id?: string;
    document_version_id?: string;
    external_url?: string;
    note?: string;
    title?: string;
  }) => void;
}) {
  // Default to whatever this requirement actually demands, so the common case
  // needs no thought and the wrong type is not the path of least resistance.
  const [kind, setKind] = React.useState<EvidenceKind>(
    req.required_evidence_type === "any"
      ? "research_run"
      : (req.required_evidence_type as EvidenceKind)
  );
  const [runId, setRunId] = React.useState("");
  const [versionId, setVersionId] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [note, setNote] = React.useState("");
  const [title, setTitle] = React.useState("");

  // Only versions the engine would accept. Offering a superseded one and
  // rejecting it on submit would be a worse way to learn the same thing.
  const usableVersions = docs
    .filter((d) => d.current_version?.is_usable)
    .map((d) => ({ doc: d, version: d.current_version! }));

  const submit = () => {
    onAttach({
      evidence_type: kind,
      research_run_id: kind === "research_run" ? runId : undefined,
      document_version_id: kind === "document" ? versionId : undefined,
      external_url: kind === "url" ? url.trim() : undefined,
      note: kind === "note" ? note.trim() : undefined,
      title: title.trim() || undefined,
    });
    onOpenChange(false);
    setRunId("");
    setVersionId("");
    setUrl("");
    setNote("");
    setTitle("");
  };

  const valid =
    (kind === "research_run" && runId) ||
    (kind === "document" && versionId) ||
    (kind === "url" && url.trim()) ||
    (kind === "note" && note.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Attach evidence to {req.ref_code}</DialogTitle>
          <DialogDescription>
            Attaching evidence supersedes any current approval, because an
            approval describes one specific evidence set.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="evidence-kind">Type</Label>
            <select
              id="evidence-kind"
              className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
              value={kind}
              onChange={(e) => setKind(e.target.value as EvidenceKind)}
            >
              <option value="document">Controlled document</option>
              <option value="research_run">Completed research run</option>
              <option value="url">Link</option>
              <option value="note">Note</option>
            </select>
            {req.required_evidence_type !== "any" &&
              kind !== req.required_evidence_type && (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  This requirement asks for{" "}
                  <code className="font-mono">{req.required_evidence_type}</code>{" "}
                  evidence. Anything else can be attached, but it will not
                  satisfy the requirement.
                </p>
              )}
          </div>

          {kind === "document" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-doc">Document version</Label>
              <select
                id="evidence-doc"
                className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
              >
                <option value="">Select a document…</option>
                {usableVersions.map(({ doc, version }) => (
                  <option key={version.id} value={version.id}>
                    {doc.document_number} — {doc.title} ({version.version_label},{" "}
                    {version.status})
                  </option>
                ))}
              </select>
              {usableVersions.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No approved or effective document versions are registered for
                  this project yet. Only a version that is approved or
                  effective, and still in date, can satisfy a requirement —{" "}
                  <Link
                    href={`/programmes/${projectId}/documents`}
                    className="text-primary hover:underline"
                  >
                    open the document register
                  </Link>
                  .
                </p>
              )}
            </div>
          )}

          {kind === "research_run" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-run">Research run</Label>
              <select
                id="evidence-run"
                className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
              >
                <option value="">Select a run…</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.original_question.slice(0, 70)}
                    {r.original_question.length > 70 ? "…" : ""} ·{" "}
                    {r.evidence_count} sources
                  </option>
                ))}
              </select>
              {runs.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No completed research runs on this project yet. Only completed
                  runs may be cited — an unfinished run carries no verified
                  evidence.
                </p>
              )}
            </div>
          )}

          {kind === "url" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-url">URL</Label>
              <Input
                id="evidence-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
              />
            </div>
          )}

          {kind === "note" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-note">Note</Label>
              <Textarea
                id="evidence-note"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="evidence-title">Label</Label>
            <Input
              id="evidence-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="How this should appear in the gate pack"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!valid} onClick={submit}>
            Attach
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
