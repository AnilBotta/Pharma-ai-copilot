"use client";

/**
 * The confirmation surface — the part of this feature that must not be got wrong.
 *
 * A one-click Approve button sitting next to an AI recommendation is precisely
 * how rubber-stamping happens, and rubber-stamping is this module's own failure
 * mode — a gate reported better than it is — wearing a new coat. Three rules
 * follow from that, and they are the whole design:
 *
 *  1. THE CARD FETCHES ITS OWN STATE. Everything above the button comes from
 *     `pdp.getGate` / `pdp.getRequirement`, read now, rendered with the same
 *     `GateReadiness` component the authoritative view uses. The agent's
 *     description of the situation appears nowhere in that region. A reviewer
 *     must be agreeing with the record, not with a summary of it.
 *
 *  2. IF THE PREMISE MOVED, THERE IS NO BUTTON. Not disabled with a tooltip —
 *     absent. A disabled control invites hunting for the way round it; an
 *     absent one says the decision is not available and here is what changed.
 *     The server refuses it too, so this is courtesy rather than enforcement.
 *
 *  3. THE RATIONALE IS SUBORDINATE. Smaller, below the evidence, labelled as
 *     the reason it was proposed. It is not grounds for approving.
 */

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  ShieldQuestion,
  XCircle,
} from "lucide-react";

import { GateReadiness } from "@/components/pdp/gate-readiness";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  pdp,
  type AgentProposal,
  type GateWorkspace,
  type Requirement,
} from "@/lib/api";

const ACTION_TITLE: Record<string, string> = {
  approve_requirement: "Approve a requirement",
  decide_gate: "Record a gate decision",
  attach_evidence: "Attach evidence",
  add_document_version: "Add a document version",
  set_acceptance: "Confirm acceptance criteria",
  rebaseline: "Re-baseline the schedule",
};

type Subject =
  | { kind: "gate"; gate: GateWorkspace }
  | { kind: "requirement"; requirement: Requirement }
  | { kind: "none" };

export function ProposalCard({
  proposal,
  onSettled,
}: {
  proposal: AgentProposal;
  onSettled: () => void;
}) {
  const [subject, setSubject] = React.useState<Subject>({ kind: "none" });
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<"confirm" | "reject" | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [refused, setRefused] = React.useState<string | null>(null);

  const params = proposal.params as Record<string, string | undefined>;

  // Read the record now. Nothing here comes from the proposal itself.
  const readSubject = React.useCallback(async () => {
    try {
      if (params.stage_id) {
        setSubject({ kind: "gate", gate: await pdp.getGate(params.stage_id) });
      } else if (params.requirement_id) {
        setSubject({
          kind: "requirement",
          requirement: await pdp.getRequirement(params.requirement_id),
        });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [params.stage_id, params.requirement_id]);

  React.useEffect(() => {
    void readSubject();
  }, [readSubject]);

  const act = async (kind: "confirm" | "reject") => {
    setBusy(kind);
    setError(null);
    setRefused(null);
    try {
      if (kind === "confirm") await pdp.confirmProposal(proposal.id);
      else await pdp.rejectProposal(proposal.id);
      onSettled();
    } catch (err) {
      // 409 from the server is the premise check, and it is the interesting
      // case: it means somebody changed the record while this sat here.
      if (err instanceof ApiError && err.status === 409) {
        setRefused(err.message);
        // Re-read, or the card would go on displaying the state it loaded on
        // mount while telling you that state has changed - which is the exact
        // confusion this card exists to prevent, just pointed inward.
        void readSubject();
      } else {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setBusy(null);
    }
  };

  if (proposal.status !== "pending") {
    return <SettledCard proposal={proposal} />;
  }

  const expired = new Date(proposal.expires_at).getTime() < Date.now();

  return (
    <div className="space-y-3 rounded-lg border border-primary/30 bg-primary/[0.03] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <ShieldQuestion className="size-3.5 text-primary" />
          {ACTION_TITLE[proposal.action_type] ?? proposal.action_type}
        </div>
        <Badge variant="outline">Needs your decision</Badge>
      </div>

      <p className="text-xs text-muted-foreground">
        The agent prepared this. It cannot take the action itself — if you
        confirm, it is recorded as your decision.
      </p>

      {/* ---------- the record, read now ---------- */}
      {loading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" /> Reading the current state…
        </p>
      ) : subject.kind === "gate" ? (
        <div className="rounded-lg border bg-background p-3">
          <p className="mb-2 text-xs font-medium">{subject.gate.stage.name}</p>
          <GateReadiness
            readiness={subject.gate.readiness}
            blockers={subject.gate.blockers}
          />
        </div>
      ) : subject.kind === "requirement" ? (
        <RequirementFacts requirement={subject.requirement} />
      ) : null}

      {/* ---------- what it wants to do ---------- */}
      <ProposedChange proposal={proposal} />

      {/* ---------- subordinate: why ---------- */}
      <div className="rounded border-l-2 border-muted pl-2.5">
        <p className="text-[11px] font-medium text-muted-foreground">
          The agent&rsquo;s reason for proposing this
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{proposal.rationale}</p>
      </div>

      {refused && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-800 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <div>
            <p className="font-medium">This can no longer be confirmed.</p>
            <p className="mt-0.5">{refused}</p>
            <p className="mt-1">
              Ask the agent to look again — what it recommended was about a
              different state of the record.
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {expired ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="size-3" /> This expired. A proposal is a statement
          about a moment — ask again if it still matters.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {/* Absent, not disabled, once the premise has moved. */}
          {!refused && (
            <Button size="sm" disabled={busy !== null} onClick={() => act("confirm")}>
              {busy === "confirm" && <Loader2 className="size-3.5 animate-spin" />}
              Confirm as me
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy !== null}
            onClick={() => act("reject")}
          >
            Discard
          </Button>
        </div>
      )}
    </div>
  );
}

function RequirementFacts({ requirement }: { requirement: Requirement }) {
  return (
    <div className="space-y-2 rounded-lg border bg-background p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-muted-foreground">
          {requirement.ref_code}
        </code>
        <span className="font-medium">{requirement.title}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-muted-foreground">
        <dt>Status</dt>
        <dd className="text-foreground">
          {requirement.status.replace(/_/g, " ")}
        </dd>
        <dt>Evidence attached</dt>
        <dd className="text-foreground">{requirement.evidence_count}</dd>
        <dt>Acceptance confirmed by</dt>
        <dd className="text-foreground">
          {requirement.acceptance_confirmed_by_name ?? "nobody yet"}
        </dd>
        <dt>Owner</dt>
        <dd className="text-foreground">{requirement.owner_name ?? "unassigned"}</dd>
      </dl>
      {requirement.acceptance_criteria && (
        <div className="rounded bg-muted/40 p-2">
          <p className="font-medium text-muted-foreground">Acceptance criteria</p>
          <p className="mt-0.5">{requirement.acceptance_criteria}</p>
        </div>
      )}
      {requirement.is_blocked && requirement.blocked_reason && (
        <p className="rounded border border-destructive/30 bg-destructive/5 p-2 text-destructive">
          Blocked: {requirement.blocked_reason}
        </p>
      )}
    </div>
  );
}

function ProposedChange({ proposal }: { proposal: AgentProposal }) {
  const p = proposal.params as Record<string, string | undefined>;
  const lines: string[] = [];

  if (proposal.action_type === "decide_gate") {
    lines.push(`Decision: ${(p.decision ?? "").replace(/_/g, " ")}`);
    if (p.conditions) lines.push(`Conditions: ${p.conditions}`);
    if (p.note) lines.push(`Note: ${p.note}`);
  } else if (proposal.action_type === "approve_requirement") {
    lines.push(`Decision: ${p.decision ?? "approved"}`);
    if (p.comments) lines.push(`Comments: ${p.comments}`);
  } else if (proposal.action_type === "rebaseline") {
    lines.push(`Name: ${p.name ?? ""}`);
    lines.push(`Reason: ${p.reason ?? ""}`);
  } else {
    for (const [key, value] of Object.entries(p)) {
      if (value) lines.push(`${key.replace(/_/g, " ")}: ${value}`);
    }
  }

  return (
    <div className="rounded-lg border border-dashed p-2.5 text-xs">
      <p className="font-medium text-muted-foreground">What will happen</p>
      <ul className="mt-1 space-y-0.5">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

function SettledCard({ proposal }: { proposal: AgentProposal }) {
  const done = proposal.status === "confirmed";
  return (
    <div className="flex items-start gap-2 rounded-lg border p-2.5 text-xs text-muted-foreground">
      {done ? (
        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
      ) : (
        <XCircle className="mt-0.5 size-3.5 shrink-0" />
      )}
      <span>
        {ACTION_TITLE[proposal.action_type] ?? proposal.action_type} —{" "}
        {proposal.status}
        {done && ", recorded as your decision"}.
      </span>
    </div>
  );
}
