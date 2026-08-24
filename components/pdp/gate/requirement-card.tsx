"use client";

import * as React from "react";
import { Check, ChevronDown, X } from "lucide-react";

import { AttachEvidenceDialog } from "@/components/pdp/gate/attach-evidence-dialog";
import { EvidenceList } from "@/components/pdp/gate/evidence-list";
import { RequirementActions } from "@/components/pdp/gate/requirement-actions";
import { nameList, roleLabel } from "@/components/pdp/gate/requirement-labels";
import { RequirementStatusBadge } from "@/components/pdp/gate-readiness";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { pdp } from "@/lib/api";
import { cn, formatRelative } from "@/lib/utils";
import type {
  AttachableRun,
  ControlledDocument,
  GateWorkspace,
  Requirement,
} from "@/lib/api";
export function RequirementCard({
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
  act: (
    key: string,
    fn: () => Promise<unknown>,
    done?: string
  ) => Promise<void>;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [attachOpen, setAttachOpen] = React.useState(false);

  const working = busy?.startsWith(req.id) ?? false;

  return (
    <Card
      variant="interactive"
      className={cn(
        "overflow-hidden py-0",
        req.is_satisfied && "border-success-border"
      )}
    >
      <CardContent className="px-0 py-0">
        <button
          type="button"
          className="flex w-full items-center gap-3 px-5 py-4 text-left outline-none focus-visible:bg-accent/40"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          // Without this the control announces as an unnamed button: its
          // visible label is assembled from nested spans and badges, which
          // does not reliably produce an accessible name.
          aria-label={`${req.ref_code} ${req.title}, ${req.status.replace(/_/g, " ")}`}
        >
          {/* A status rail, so the state of a requirement is legible while
              scanning a list of eight without reading any of the badges. */}
          <span
            aria-hidden="true"
            className={cn(
              "-my-4 w-0.5 self-stretch rounded-full",
              req.is_satisfied
                ? "bg-success-solid"
                : req.is_blocked || req.status === "overdue"
                  ? "bg-danger-solid"
                  : req.status === "awaiting_approval" ||
                      req.status === "awaiting_dependency"
                    ? "bg-warning-solid"
                    : "bg-border"
            )}
          />

          <ChevronDown
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180"
            )}
          />

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <code className="type-mono shrink-0 text-2xs text-muted-foreground">
                {req.ref_code}
              </code>
              <span className="text-sm font-medium">{req.title}</span>
              {!req.is_mandatory && <Badge variant="muted">Optional</Badge>}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-2xs text-muted-foreground">
              <RequirementStatusBadge status={req.status} />
              <span>{req.evidence_count} evidence</span>
              {req.owner_name && <span>· {req.owner_name}</span>}
              {req.due_date && <span>· due {req.due_date}</span>}
            </div>
          </div>
        </button>

        {expanded && (
          <div className="space-y-4 border-t bg-muted/20 px-5 py-5">
            {req.description && (
              <p className="max-w-prose text-sm text-muted-foreground">
                {req.description}
              </p>
            )}

            {req.acceptance_criteria && (
              <div className="rounded-lg border bg-card p-3">
                <p className="type-label text-muted-foreground">
                  Acceptance criteria
                </p>
                <p className="mt-1.5 text-sm">{req.acceptance_criteria}</p>
              </div>
            )}

            {req.is_blocked && req.blocked_reason && (
              <div className="rounded-lg border border-danger-border bg-danger-surface p-3 text-sm">
                <span className="font-medium text-danger">Blocked:</span>{" "}
                {req.blocked_reason}
              </div>
            )}

            {req.depends_on && req.depends_on.length > 0 && (
              <div>
                <p className="type-label text-muted-foreground">Prerequisites</p>
                <ul className="mt-2 space-y-1.5">
                  {req.depends_on.map((d) => (
                    <li key={d.id} className="flex items-center gap-2 text-xs">
                      {d.is_satisfied ? (
                        <Check
                          aria-hidden="true"
                          className="size-3.5 shrink-0 text-success"
                        />
                      ) : (
                        <X
                          aria-hidden="true"
                          className="size-3.5 shrink-0 text-warning"
                        />
                      )}
                      <code className="type-mono text-muted-foreground">
                        {d.ref_code}
                      </code>
                      <span className="min-w-0 truncate">{d.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <EvidenceList
              requirement={req}
              onDetach={(id) =>
                act(
                  `${req.id}:detach`,
                  () => pdp.detachEvidence(id),
                  `Evidence removed from ${req.ref_code}. Any approval was superseded.`
                )
              }
              busy={working}
            />

            {req.current_approval && (
              <div className="rounded-lg border border-success-border bg-success-surface p-3 text-xs">
                <span className="font-medium text-success">Approved</span> by{" "}
                {req.current_approval.approver_name ?? "an approver"} as{" "}
                {req.current_approval.approver_role},{" "}
                {formatRelative(req.current_approval.approved_at)}.
                {req.current_approval.comments && (
                  <span className="mt-1 block text-muted-foreground">
                    &ldquo;{req.current_approval.comments}&rdquo;
                  </span>
                )}
              </div>
            )}

            {req.acceptance_confirmed_by_name &&
              (req.eligible_approvers.length === 0 ? (
                <div className="rounded-lg border border-warning-border bg-warning-surface p-3 text-sm">
                  <p className="font-medium text-warning">
                    Nobody can approve this requirement.
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {req.acceptance_confirmed_by_name} confirmed the acceptance
                    criteria, and whoever confirms cannot also approve.{" "}
                    {req.approver_role_key
                      ? `Approval here needs ${roleLabel(
                          req.approver_role_key
                        )}, and nobody else holds it.`
                      : "Nobody else holds a role with approval authority."}
                  </p>
                  <p className="mt-2 text-muted-foreground">
                    To move it on: withdraw the acceptance, have a colleague
                    confirm it instead, then approve. Or grant{" "}
                    {req.approver_role_key
                      ? roleLabel(req.approver_role_key)
                      : "an approving role"}{" "}
                    to a second person.
                  </p>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Acceptance criteria confirmed by{" "}
                  {req.acceptance_confirmed_by_name}. Whoever confirms cannot
                  also approve, so this one is for{" "}
                  {nameList(req.eligible_approvers.map((a) => a.name))}.
                </p>
              ))}

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
          act(
            `${req.id}:attach`,
            () => pdp.attachEvidence(req.id, body),
            `Evidence attached to ${req.ref_code}. Any approval was superseded.`
          )
        }
      />
    </Card>
  );
}
