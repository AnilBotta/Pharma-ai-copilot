"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { AgentAssessment } from "@/components/pdp/agent-assessment";
import { GateDecisionCard } from "@/components/pdp/gate/gate-decision-card";
import { RequirementCard } from "@/components/pdp/gate/requirement-card";
import { UnattendedThreshold } from "@/components/pdp/gate/unattended-threshold";
import { GateReadiness, GateStatusBadge } from "@/components/pdp/gate-readiness";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  pdp,
  type AttachableRun,
  type ControlledDocument,
  type GateWorkspace,
} from "@/lib/api";
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
    async (key: string, fn: () => Promise<unknown>, done?: string) => {
      setBusy(key);
      setError(null);
      try {
        await fn();
        await reload();
        if (done) toast.success(done);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : String(err);
        // Kept inline as well as toasted. A refusal here is the product
        // working — segregation of duties, an unsatisfied gate — and it
        // belongs on the page, not only in something that fades. The toast
        // exists because this page is long enough that a message at the top
        // is invisible to somebody acting on the fourteenth requirement.
        setError(message);
        toast.error("That change was not made", { description: message });
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
      <Card variant="flush" tone="danger">
        <CardContent className="flex items-start gap-3 py-4">
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-danger"
          />
          <p className="text-sm text-danger">{error ?? "Gate not found."}</p>
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
        <Card variant="flush" tone="danger">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-danger"
            />
            <p className="text-sm text-danger">{error}</p>
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
          onDecide={(body) =>
            act(
              "gate",
              () => pdp.decideGate(stageId, body),
              "Gate decision recorded in the audit trail"
            )
          }
        />
      </div>

      {stage.exit_criteria && (
        <Card variant="flush">
          <CardContent className="py-4">
            <p className="type-label text-muted-foreground">Exit criteria</p>
            <p className="mt-1.5 max-w-prose text-sm">{stage.exit_criteria}</p>
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
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">
            Requirements ({requirements.length})
          </h2>
          {/* The dispositive count, restated where the work is done. The pips
              say it at the top of the page; by the time you have scrolled to
              the list you can no longer see them. */}
          <span className="metric text-xs text-muted-foreground">
            {readiness.mandatory_satisfied} of {readiness.mandatory_count}{" "}
            mandatory satisfied
          </span>
        </div>
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
