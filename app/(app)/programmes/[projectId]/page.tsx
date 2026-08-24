"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bell,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  FileText,
  GitBranch,
  History,
} from "lucide-react";

import { GateTrack } from "@/components/charts/gate-track";
import { MandatoryByGate } from "@/components/charts/mandatory-by-gate";
import { ReadinessHistory } from "@/components/charts/readiness-history";
import { GateStatusBadge, ReadyVerdict } from "@/components/pdp/gate-readiness";
import { MandatoryPips } from "@/components/pdp/mandatory-pips";
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
  type Notification,
  type ProgrammeDetail,
  type StageSummary,
} from "@/lib/api";
import { cn, formatRelative } from "@/lib/utils";

/** The audit window. Named so the chart caption can state it rather than
 *  imply that the history is complete. */
const AUDIT_WINDOW = 200;

export default function ProgrammePage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;

  const [detail, setDetail] = React.useState<ProgrammeDetail | null>(null);
  const [audit, setAudit] = React.useState<AuditEntry[]>([]);
  const [notifications, setNotifications] = React.useState<Notification[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const openAlerts = notifications.filter((n) => !n.resolved_at).length;
  const hasCritical = notifications.some(
    (n) => !n.resolved_at && n.severity === "critical"
  );

  // The engine's own numbers, summed across the programme's gates. The history
  // chart is terminated on these so it cannot contradict the page it sits on.
  const totals = React.useMemo(
    () =>
      (detail?.stages ?? []).reduce(
        (acc, s) => ({
          satisfied: acc.satisfied + s.satisfied_count,
          applicable: acc.applicable + s.applicable_count,
        }),
        { satisfied: 0, applicable: 0 }
      ),
    [detail]
  );

  React.useEffect(() => {
    let active = true;
    Promise.all([
      pdp.getProgramme(projectId),
      pdp.audit(projectId, AUDIT_WINDOW),
      pdp.listNotifications(projectId),
    ])
      .then(([programme, events, alerts]) => {
        if (!active) return;
        setDetail(programme);
        setAudit(events);
        setNotifications(alerts);
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

      {/* The programme end to end, above the tabs, because "where is this
          thing" is the first question anybody opening it has. */}
      <Card>
        <CardContent className="grid gap-8 py-6 lg:grid-cols-[1.1fr_1fr]">
          <div className="min-w-0">
            <p className="type-label mb-3 text-muted-foreground">Gates</p>
            <GateTrack stages={detail.stages} projectId={projectId} />
          </div>
          <div className="min-w-0">
            <p className="type-label mb-3 text-muted-foreground">
              Mandatory requirements
            </p>
            <MandatoryByGate stages={detail.stages} height={180} />
          </div>
        </CardContent>
      </Card>

      {/* Counts, never a percentage — see components/charts/readiness-history.
          Below the two charts above, which show the current state; this one is
          the weaker claim because it is reconstructed rather than recorded. */}
      <Card>
        <CardContent className="py-6">
          <p className="type-label mb-3 text-muted-foreground">
            Requirements satisfied over time
          </p>
          <ReadinessHistory
            audit={audit}
            satisfied={totals.satisfied}
            applicable={totals.applicable}
            windowLimit={AUDIT_WINDOW}
          />
        </CardContent>
      </Card>

      <Tabs defaultValue="gates">
        <TabsList>
          <TabsTrigger value="gates">
            <ClipboardList className="size-4" /> Gates
          </TabsTrigger>
          <TabsTrigger value="alerts">
            <Bell className="size-4" /> Alerts
            {openAlerts > 0 && (
              <Badge
                variant={hasCritical ? "destructive" : "warning"}
                className="ml-1 px-1.5 py-0 text-[10px]"
              >
                {openAlerts}
              </Badge>
            )}
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

        <TabsContent value="alerts" className="mt-6">
          <Alerts
            notifications={notifications}
            onAcknowledge={async (id) => {
              await pdp.acknowledgeNotification(id);
              setNotifications(await pdp.listNotifications(projectId));
            }}
          />
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
              satisfied
            </p>
          </div>

          <div className="w-full space-y-2 sm:w-56">
            <div className="flex items-baseline justify-between gap-2">
              <span className="metric text-base">
                {stage.readiness_pct.toFixed(1)}%
              </span>
              <ReadyVerdict
                isReady={stage.is_ready}
                blockerCount={stage.blocker_count}
              />
            </div>
            <Progress
              value={stage.readiness_pct}
              tone={stage.is_ready ? "success" : "warning"}
              valueText={`${stage.readiness_pct.toFixed(1)} percent, ${
                stage.is_ready ? "ready for review" : "not ready"
              }`}
            />
            {/* Replaces the prose "N of M mandatory" that used to sit under
                the title. The count is the verdict, so it is drawn rather
                than mentioned. */}
            <MandatoryPips
              satisfied={stage.mandatory_satisfied}
              total={stage.mandatory_count}
              isReady={stage.is_ready}
              label="Mand."
            />
          </div>

          <ChevronRight className="hidden size-4 shrink-0 text-muted-foreground sm:block" />
        </Link>
      </CardContent>
    </Card>
  );
}

/**
 * Open alerts, most severe first.
 *
 * Every entry is recomputed from the record on each sweep, so this is what is
 * currently wrong rather than a log of what once was. That is also why there is
 * no dismiss button: an alert leaves this list when its condition stops being
 * true, and not before. Acknowledging says "I have this" — it stops the
 * escalation ladder without pretending the problem is gone.
 */
function Alerts({
  notifications,
  onAcknowledge,
}: {
  notifications: Notification[];
  onAcknowledge: (id: string) => Promise<void>;
}) {
  const open = notifications.filter((n) => !n.resolved_at);

  if (open.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <CheckCircle2 className="size-8 text-emerald-600" />
        <p className="text-sm font-medium">Nothing needs attention</p>
        <p className="max-w-sm text-xs text-muted-foreground">
          No overdue requirements, lapsing documents or slipping critical tasks.
          Conditions are re-checked every minute.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {open.map((n) => (
        <Card
          key={n.id}
          className={cn(
            n.severity === "critical" && "border-destructive/40 bg-destructive/5",
            n.severity === "warning" && "border-amber-500/40 bg-amber-500/5"
          )}
        >
          <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant={
                    n.severity === "critical"
                      ? "destructive"
                      : n.severity === "warning"
                        ? "warning"
                        : "info"
                  }
                >
                  {n.severity}
                </Badge>
                <span className="text-sm font-medium">{n.title}</span>
                {n.escalation_level > 0 && (
                  <Badge variant="destructive">Escalated</Badge>
                )}
              </div>
              {n.detail && (
                <p className="mt-1 text-xs text-muted-foreground">{n.detail}</p>
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                {n.rule_name} · raised {formatRelative(n.raised_at)}
                {n.acknowledged_by_name &&
                  ` · acknowledged by ${n.acknowledged_by_name}`}
              </p>
            </div>

            {!n.acknowledged_at && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void onAcknowledge(n.id)}
              >
                Acknowledge
              </Button>
            )}
          </CardContent>
        </Card>
      ))}

      <p className="pt-2 text-xs text-muted-foreground">
        Acknowledging stops an alert escalating. It does not close it — an alert
        clears only when the condition behind it stops being true.
      </p>
    </div>
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
