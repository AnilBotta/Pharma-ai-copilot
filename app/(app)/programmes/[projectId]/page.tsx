"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  ChevronRight,
  ClipboardList,
  FileText,
  GitBranch,
  History,
} from "lucide-react";

import { GateStatusBadge, ReadyVerdict } from "@/components/pdp/gate-readiness";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ApiError,
  pdp,
  type AuditEntry,
  type ProgrammeDetail,
  type StageSummary,
} from "@/lib/api";
import { formatRelative } from "@/lib/utils";

export default function ProgrammePage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;

  const [detail, setDetail] = React.useState<ProgrammeDetail | null>(null);
  const [audit, setAudit] = React.useState<AuditEntry[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    Promise.all([pdp.getProgramme(projectId), pdp.audit(projectId, 60)])
      .then(([programme, events]) => {
        if (!active) return;
        setDetail(programme);
        setAudit(events);
      })
      .catch(
        (err) => active && setError(err instanceof ApiError ? err.message : String(err))
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-start gap-3 py-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <p className="text-sm text-destructive">{error ?? "Programme not found."}</p>
        </CardContent>
      </Card>
    );
  }

  const projectName = String(detail.project.name);

  return (
    <div className="space-y-8">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/programmes">
            <ArrowLeft className="size-4" /> All programmes
          </Link>
        </Button>
        <PageHeader
          title={projectName}
          description="Each gate shows how much is done and, separately, whether it may be reviewed."
          icon={GitBranch}
          actions={
            <div className="flex gap-2">
              <Button asChild variant="outline">
                <Link href={`/programmes/${projectId}/schedule`}>
                  <CalendarClock className="size-4" /> Schedule
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href={`/programmes/${projectId}/documents`}>
                  <FileText className="size-4" /> Document register
                </Link>
              </Button>
            </div>
          }
        />
      </div>

      <Tabs defaultValue="gates">
        <TabsList>
          <TabsTrigger value="gates">
            <ClipboardList className="size-4" /> Gates
          </TabsTrigger>
          <TabsTrigger value="audit">
            <History className="size-4" /> Audit trail
          </TabsTrigger>
        </TabsList>

        <TabsContent value="gates" className="mt-6 space-y-3">
          {detail.stages.map((stage) => (
            <StageRow key={stage.id} stage={stage} projectId={projectId} />
          ))}
        </TabsContent>

        <TabsContent value="audit" className="mt-6">
          <AuditTrail entries={audit} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function StageRow({ stage, projectId }: { stage: StageSummary; projectId: string }) {
  return (
    <Card className="transition-colors hover:border-primary/40">
      <CardContent className="py-4">
        <Link
          href={`/programmes/${projectId}/gates/${stage.id}`}
          className="flex flex-col gap-4 sm:flex-row sm:items-center"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">{stage.name}</h3>
              <GateStatusBadge status={stage.gate_status} />
              {stage.overdue_count > 0 && (
                <Badge variant="destructive">{stage.overdue_count} overdue</Badge>
              )}
            </div>
            {stage.gate_question && (
              <p className="mt-1 text-xs italic text-muted-foreground">
                {stage.gate_question}
              </p>
            )}
            <p className="mt-1.5 text-xs text-muted-foreground">
              {stage.satisfied_count} of {stage.applicable_count} requirements
              satisfied · {stage.mandatory_satisfied} of {stage.mandatory_count}{" "}
              mandatory
            </p>
          </div>

          <div className="w-full space-y-2 sm:w-56">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-base font-semibold tabular-nums">
                {stage.readiness_pct.toFixed(1)}%
              </span>
              <ReadyVerdict
                isReady={stage.is_ready}
                blockerCount={stage.blocker_count}
              />
            </div>
            <Progress
              value={stage.readiness_pct}
              indicatorClassName={stage.is_ready ? "bg-emerald-500" : "bg-amber-500"}
            />
          </div>

          <ChevronRight className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
        </Link>
      </CardContent>
    </Card>
  );
}

/** Actions are shown verbatim. An audit trail that paraphrases is not one. */
function AuditTrail({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No recorded activity yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border px-3 py-2 text-xs"
        >
          <code className="font-mono text-[11px] text-primary">{entry.action}</code>
          <span className="text-muted-foreground">
            {entry.actor_name ?? entry.actor_agent ?? "unknown actor"}
          </span>
          {entry.actor_role && <Badge variant="muted">{entry.actor_role}</Badge>}
          {entry.reason && (
            <span className="min-w-0 flex-1 text-muted-foreground">
              &ldquo;{entry.reason}&rdquo;
            </span>
          )}
          <span className="ml-auto shrink-0 text-muted-foreground">
            {formatRelative(entry.occurred_at)}
          </span>
        </div>
      ))}
    </div>
  );
}
