"use client";

import * as React from "react";
import { Check, Paperclip, ShieldCheck } from "lucide-react";

import {
  approvalBarredReason,
  roleLabel,
} from "@/components/pdp/gate/requirement-labels";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { pdp } from "@/lib/api";
import type { GateWorkspace, Requirement } from "@/lib/api";
export function RequirementActions({
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
  act: (
    key: string,
    fn: () => Promise<unknown>,
    done?: string
  ) => Promise<void>;
}) {
  const [rejectOpen, setRejectOpen] = React.useState(false);
  const [strandOpen, setStrandOpen] = React.useState(false);
  const [blockOpen, setBlockOpen] = React.useState(false);
  const [blockReason, setBlockReason] = React.useState("");
  const [comments, setComments] = React.useState("");

  const canApprove = capabilities.can_approve;
  const acceptanceReady = req.evidence_count > 0 && !req.is_blocked;

  // Confirming an acceptance is what bars you from approving. On a small team
  // that can remove the last eligible approver and strand the requirement, so
  // the click asks first rather than discovering it two steps later.
  const wouldStrand = req.approvers_if_i_accept.length === 0;
  const confirmAcceptance = () =>
    act(
      `${req.id}:accept`,
      () => pdp.setAcceptance(req.id, true),
      `${req.ref_code}: acceptance criteria confirmed`
    );

  return (
    // Two groups, not one row of five. "Approve" and "Block" were sitting
    // shoulder to shoulder in the same weight; the actions that move a
    // requirement forward now lead, and the ones that stop it are pushed right.
    <div className="flex flex-wrap items-center gap-2 border-t pt-4">
      <Button size="sm" variant="outline" disabled={busy} onClick={onAttach}>
        <Paperclip className="size-3.5" /> Attach evidence
      </Button>

      {req.acceptance_confirmed_by ? (
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() =>
            act(
              `${req.id}:accept`,
              () => pdp.setAcceptance(req.id, false),
              `${req.ref_code}: acceptance withdrawn, any approval superseded`
            )
          }
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
          onClick={() =>
            wouldStrand ? setStrandOpen(true) : void confirmAcceptance()
          }
        >
          <Check className="size-3.5" /> Confirm acceptance criteria
        </Button>
      )}

      {canApprove && (
        <>
          <Button
            size="sm"
            disabled={
              busy ||
              !req.acceptance_confirmed_by ||
              req.is_blocked ||
              !req.i_can_approve
            }
            title={
              !req.acceptance_confirmed_by
                ? "Approval agrees with a confirmed claim. There is no claim yet."
                : !req.i_can_approve
                  ? approvalBarredReason(req)
                  : undefined
            }
            onClick={() =>
              act(
                `${req.id}:approve`,
                () => pdp.decideRequirement(req.id, { decision: "approved" }),
                `${req.ref_code} approved and recorded against your name`
              )
            }
          >
            <ShieldCheck className="size-3.5" /> Approve
          </Button>
        </>
      )}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {canApprove && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy || !req.i_can_approve}
            title={req.i_can_approve ? undefined : approvalBarredReason(req)}
            onClick={() => setRejectOpen(true)}
          >
            Request changes
          </Button>
        )}

        {req.is_blocked ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              act(
                `${req.id}:block`,
                () => pdp.setBlocked(req.id, false),
                `${req.ref_code}: block cleared`
              )
            }
          >
            Clear block
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => setBlockOpen(true)}
          >
            Block
          </Button>
        )}
      </div>

      {/* Was `window.prompt`. Besides breaking the visual language entirely,
          the browser dialog is unstyleable, untranslatable, silently
          suppressible, and its single line is a poor place to write the
          reason that goes into an audit record. */}
      <Dialog open={blockOpen} onOpenChange={setBlockOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Block {req.ref_code}</DialogTitle>
            <DialogDescription>
              A block stops this requirement from being confirmed or approved
              until it is cleared. The reason is recorded and shown to whoever
              picks it up.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={3}
            value={blockReason}
            onChange={(e) => setBlockReason(e.target.value)}
            placeholder="What is preventing this from proceeding."
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setBlockOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!blockReason.trim()}
              onClick={() => {
                void act(
                  `${req.id}:block`,
                  () => pdp.setBlocked(req.id, true, blockReason.trim()),
                  `${req.ref_code} blocked`
                );
                setBlockOpen(false);
                setBlockReason("");
              }}
            >
              Block requirement
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={strandOpen} onOpenChange={setStrandOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirming this leaves nobody able to approve it</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 text-sm">
                <p>
                  Whoever confirms the acceptance criteria cannot also approve
                  them — that separation is the point of the step. If you
                  confirm {req.ref_code}, no one on this project will be able to
                  approve it
                  {req.approver_role_key
                    ? `, because approval needs ${roleLabel(
                        req.approver_role_key
                      )} and you are the only person who holds it`
                    : ""}
                  .
                </p>
                <p>
                  Better: ask a colleague to confirm the acceptance criteria,
                  and approve it yourself afterwards. You can also confirm now
                  and withdraw it later, or give a second person the approving
                  role.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStrandOpen(false)}>
              Leave it for a colleague
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setStrandOpen(false);
                void confirmAcceptance();
              }}
            >
              Confirm anyway
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
                void act(
                  `${req.id}:reject`,
                  () =>
                    pdp.decideRequirement(req.id, {
                      decision: "rejected",
                      comments: comments.trim(),
                    }),
                  `${req.ref_code}: changes requested, any approval superseded`
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
