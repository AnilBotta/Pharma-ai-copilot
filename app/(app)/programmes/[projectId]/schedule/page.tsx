"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  Flag,
  Lock,
  Plus,
  Zap,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { GanttTimeline } from "@/components/charts/gantt/timeline";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
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
import { ApiError, pdp, type Schedule, type Task } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function SchedulePage() {
  const { projectId } = useParams<{ projectId: string }>();

  const [schedule, setSchedule] = React.useState<Schedule | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [taskOpen, setTaskOpen] = React.useState(false);
  const [baselineOpen, setBaselineOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    setSchedule(await pdp.getSchedule(projectId));
  }, [projectId]);

  React.useEffect(() => {
    load()
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  if (!schedule) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex items-start gap-3 py-4">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <p className="text-sm text-destructive">{error ?? "Schedule not found."}</p>
        </CardContent>
      </Card>
    );
  }

  const current = schedule.baselines.find((b) => !b.superseded_at);
  const slipping = schedule.tasks.filter((t) => (t.variance_days ?? 0) > 0);
  const worstSlip = Math.max(0, ...slipping.map((t) => t.variance_days ?? 0));

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href={`/programmes/${projectId}`}>
            <ArrowLeft className="size-4" /> Back to programme
          </Link>
        </Button>
        <PageHeader
          title="Schedule"
          description="Baseline is the commitment and cannot be edited. Forecast is the current plan. The difference is the slip."
          icon={CalendarClock}
          actions={
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setTaskOpen(true)}>
                <Plus className="size-4" /> Task
              </Button>
              {schedule.capabilities.can_approve && (
                <Button onClick={() => setBaselineOpen(true)}>Set baseline</Button>
              )}
            </div>
          }
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

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">Baseline</p>
            {current ? (
              <>
                <p className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                  <Lock className="size-3.5" /> v{current.version} · {current.name}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  approved by {current.approved_by_name ?? "someone"}
                </p>
              </>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                None yet — dates are still a draft plan, not a commitment.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className={cn(worstSlip > 0 && "border-amber-500/40")}>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">Slip against commitment</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {current ? `${worstSlip}d` : "—"}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {current
                ? `${slipping.length} task${slipping.length === 1 ? "" : "s"} later than promised`
                : "no baseline to measure against"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-muted-foreground">Critical path</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">
              {schedule.tasks.filter((t) => t.is_critical).length}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              tasks with no float — each day they slip, the programme slips
            </p>
          </CardContent>
        </Card>
      </div>

      {schedule.tasks.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No tasks yet"
          description="Add the work that delivers this programme's gate requirements."
          actionLabel="Add a task"
          onAction={() => setTaskOpen(true)}
        />
      ) : (
        <>
          {/* The timeline is the overview; the rows below remain the place
              where work is actually recorded. Hidden below md: a horizontally
              scrolling Gantt on a phone is worse than the card list, which
              already reads well there. */}
          <div className="hidden space-y-2 md:block">
            <h2 className="text-sm font-semibold">Timeline</h2>
            <GanttTimeline
              tasks={schedule.tasks}
              milestones={schedule.milestones}
            />
          </div>

          <div className="space-y-2">
            <h2 className="text-sm font-semibold">Tasks ({schedule.tasks.length})</h2>
          {schedule.tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              hasBaseline={Boolean(current)}
              onComplete={() =>
                act(() =>
                  pdp.updateTask(task.id, {
                    actual_start: task.actual_start ?? todayISO(),
                    actual_end: todayISO(),
                  })
                )
              }
              onStart={() =>
                act(() => pdp.updateTask(task.id, { actual_start: todayISO() }))
              }
            />
          ))}
          </div>
        </>
      )}

      {schedule.milestones.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Milestones</h2>
          {schedule.milestones.map((m) => (
            <Card key={m.id}>
              <CardContent className="flex items-center justify-between py-3">
                <div className="flex items-center gap-2">
                  <Flag className="size-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{m.name}</span>
                  {m.is_contractual && <Badge variant="warning">Contractual</Badge>}
                </div>
                <div className="text-right text-xs">
                  <span className="text-muted-foreground">
                    {m.forecast_date ?? "no date"}
                  </span>
                  <VarianceBadge days={m.variance_days} />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <CreateTaskDialog
        open={taskOpen}
        onOpenChange={setTaskOpen}
        onCreate={(body) => act(() => pdp.createTask(projectId, body))}
      />
      <BaselineDialog
        open={baselineOpen}
        onOpenChange={setBaselineOpen}
        hasExisting={Boolean(current)}
        onSet={(body) => act(() => pdp.rebaseline(projectId, body))}
      />
    </div>
  );
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const STATUS_LABELS: Record<string, { label: string; variant: BadgeVariant }> = {
  not_started: { label: "Not started", variant: "muted" },
  waiting_on_predecessor: { label: "Waiting", variant: "muted" },
  late_to_start: { label: "Late to start", variant: "warning" },
  in_progress: { label: "In progress", variant: "info" },
  overdue: { label: "Overdue", variant: "destructive" },
  blocked: { label: "Blocked", variant: "destructive" },
  complete: { label: "Complete", variant: "success" },
};

function VarianceBadge({ days }: { days: number | null }) {
  if (days === null || days === 0) return null;
  return (
    <Badge variant={days > 0 ? "destructive" : "success"} className="ml-2">
      {days > 0 ? `+${days}d` : `${days}d`}
    </Badge>
  );
}

function TaskRow({
  task,
  hasBaseline,
  onStart,
  onComplete,
}: {
  task: Task;
  hasBaseline: boolean;
  onStart: () => void;
  onComplete: () => void;
}) {
  const entry = STATUS_LABELS[task.status] ?? {
    label: task.status,
    variant: "muted" as const,
  };

  return (
    <Card className={cn(task.is_critical && "border-l-2 border-l-amber-500")}>
      <CardContent className="flex flex-col gap-3 py-3 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {task.wbs_code && (
              <code className="font-mono text-xs text-muted-foreground">
                {task.wbs_code}
              </code>
            )}
            <span className="text-sm font-medium">{task.title}</span>
            <Badge variant={entry.variant}>{entry.label}</Badge>
            {task.is_critical && (
              <Badge variant="warning" className="gap-1">
                <Zap className="size-3" /> Critical path
              </Badge>
            )}
            {task.requirement_ref && (
              <Badge variant="outline">{task.requirement_ref}</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {task.owner_name ?? "unassigned"}
            {task.float_days !== null &&
              !task.is_critical &&
              ` · ${task.float_days}d float`}
            {task.depends_on.length > 0 &&
              ` · after ${task.depends_on.map((d) => d.title).join(", ")}`}
          </p>
          {task.is_blocked && task.blocked_reason && (
            <p className="mt-1 text-xs text-destructive">
              Blocked: {task.blocked_reason}
            </p>
          )}
        </div>

        {/* Baseline and forecast side by side. Showing the forecast alone is
            how a plan quietly becomes fiction. */}
        <div className="grid grid-cols-2 gap-4 text-xs lg:w-72">
          <div>
            <p className="flex items-center gap-1 text-muted-foreground">
              {hasBaseline && <Lock className="size-3" />} Baseline
            </p>
            <p className="tabular-nums">{task.baseline_end ?? "—"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Forecast</p>
            <p className="tabular-nums">
              {task.actual_end ?? task.forecast_end ?? "—"}
              <VarianceBadge days={task.variance_days} />
            </p>
          </div>
        </div>

        <div className="flex gap-2">
          {!task.actual_start && (
            <Button size="sm" variant="outline" onClick={onStart}>
              Start
            </Button>
          )}
          {task.actual_start && !task.actual_end && (
            <Button size="sm" variant="outline" onClick={onComplete}>
              Complete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CreateTaskDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreate: (body: {
    title: string;
    forecast_start?: string;
    forecast_end?: string;
    wbs_code?: string;
  }) => void;
}) {
  const [title, setTitle] = React.useState("");
  const [wbs, setWbs] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a task</DialogTitle>
          <DialogDescription>
            Dates entered here are the forecast. They become a commitment only
            when a baseline is set.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="task-title">
              Title <span className="text-destructive">*</span>
            </Label>
            <Input
              id="task-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Preformulation screening"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-wbs">Reference</Label>
            <Input
              id="task-wbs"
              value={wbs}
              onChange={(e) => setWbs(e.target.value)}
              placeholder="1.2.3"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="task-start">Forecast start</Label>
              <Input
                id="task-start"
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="task-end">Forecast finish</Label>
              <Input
                id="task-end"
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!title.trim()}
            onClick={() => {
              onCreate({
                title: title.trim(),
                wbs_code: wbs.trim() || undefined,
                forecast_start: start || undefined,
                forecast_end: end || undefined,
              });
              onOpenChange(false);
              setTitle("");
              setWbs("");
              setStart("");
              setEnd("");
            }}
          >
            Add task
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BaselineDialog({
  open,
  onOpenChange,
  hasExisting,
  onSet,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  hasExisting: boolean;
  onSet: (body: { name: string; reason: string }) => void;
}) {
  const [name, setName] = React.useState("");
  const [reason, setReason] = React.useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {hasExisting ? "Re-baseline the schedule" : "Set the baseline"}
          </DialogTitle>
          <DialogDescription>
            Freezes today&apos;s forecast as the commitment. After this, baseline
            dates cannot be edited — the slip against them is what the programme
            reports.
            {hasExisting &&
              " The current baseline is kept, so what was promised before stays answerable."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bl-name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="bl-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={hasExisting ? "Baseline 2" : "Baseline 1"}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bl-reason">
              Why the commitment is changing{" "}
              <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="bl-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Scope increased following the Gate 2 review."
            />
            <p className="text-xs text-muted-foreground">
              Required. A commitment that changes without a stated reason is how
              a schedule quietly becomes fiction.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!name.trim() || !reason.trim()}
            onClick={() => {
              onSet({ name: name.trim(), reason: reason.trim() });
              onOpenChange(false);
              setName("");
              setReason("");
            }}
          >
            {hasExisting ? "Re-baseline" : "Set baseline"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
