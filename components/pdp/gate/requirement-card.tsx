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
                act(
                  `${req.id}:detach`,
                  () => pdp.detachEvidence(id),
                  `Evidence removed from ${req.ref_code}. Any approval was superseded.`
                )
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

            {req.acceptance_confirmed_by_name &&
              (req.eligible_approvers.length === 0 ? (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                  <p className="font-medium text-amber-700 dark:text-amber-400">
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
