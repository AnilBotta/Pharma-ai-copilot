"use client";

import * as React from "react";
import { Gavel, Loader2, Lock } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatRelative } from "@/lib/utils";
import type { GateWorkspace } from "@/lib/api";
export function GateDecisionCard({
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
    // Conditions left over from a previous decision would attach themselves to
    // this one, and they are written into the audit record verbatim.
    setNote("");
    setConditions("");
    setOpen(true);
  };

  // The same two rules the server enforces, said before the request rather
  // than after it. The server remains the authority: these only decide whether
  // it is worth sending, and what to tell somebody who is stuck on the form.
  const missing =
    decision === "conditionally_approved" && !conditions.trim()
      ? "Conditions are required — a conditional approval that does not say what the conditions are is just an approval."
      : (decision === "rejected" || decision === "on_hold") && !note.trim()
        ? "A note is required. It is what the audit record carries as the reason."
        : undefined;

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

            {/* A disabled <option> is the weakest way to state the rule this
                module exists for, and in testing it read as "there is no way
                to approve a gate" rather than "not yet, and here is why". The
                server refusal names the blockers; so should this. */}
            {!readiness.is_ready && (
              <div className="rounded-lg border bg-muted/30 p-3 text-sm">
                <p className="font-medium">
                  Approve is unavailable until{" "}
                  {readiness.blocker_count === 1
                    ? "one mandatory requirement is"
                    : `${readiness.blocker_count} mandatory requirements are`}{" "}
                  satisfied.
                </p>
                <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {gate.blockers.slice(0, 6).map((b) => (
                    <li key={b.requirement_id}>
                      <span className="font-medium text-foreground">
                        {b.ref_code}
                      </span>{" "}
                      — {b.reason}
                    </li>
                  ))}
                  {gate.blockers.length > 6 && (
                    <li>and {gate.blockers.length - 6} more.</li>
                  )}
                </ul>
                <p className="mt-2 text-xs text-muted-foreground">
                  Approving with conditions stays open. It records what is
                  outstanding right now alongside the decision, so the gate is
                  never made to look clean.
                </p>
              </div>
            )}

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

          <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center">
            {missing && (
              <p className="mr-auto text-xs text-muted-foreground">{missing}</p>
            )}
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy || Boolean(missing)}
              title={missing}
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

