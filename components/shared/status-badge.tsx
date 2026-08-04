import { Badge } from "@/components/ui/badge";
import type { ProjectPriority, ProjectStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const statusStyles: Record<ProjectStatus, string> = {
  Active: "bg-blue-500/12 text-blue-700 dark:text-blue-400 border-blue-500/25",
  "On Hold": "bg-amber-500/12 text-amber-700 dark:text-amber-400 border-amber-500/25",
  Completed: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-400 border-emerald-500/25",
  Planning: "bg-violet-500/12 text-violet-700 dark:text-violet-400 border-violet-500/25",
};

const priorityStyles: Record<ProjectPriority, string> = {
  Critical: "bg-rose-500/12 text-rose-700 dark:text-rose-400 border-rose-500/25",
  High: "bg-orange-500/12 text-orange-700 dark:text-orange-400 border-orange-500/25",
  Medium: "bg-sky-500/12 text-sky-700 dark:text-sky-400 border-sky-500/25",
  Low: "bg-slate-500/12 text-slate-600 dark:text-slate-300 border-slate-500/25",
};

export function StatusBadge({ status, className }: { status: ProjectStatus; className?: string }) {
  return (
    <Badge variant="outline" className={cn(statusStyles[status], className)}>
      <span className="size-1.5 rounded-full bg-current" />
      {status}
    </Badge>
  );
}

export function PriorityBadge({ priority, className }: { priority: ProjectPriority; className?: string }) {
  return (
    <Badge variant="outline" className={cn(priorityStyles[priority], className)}>
      {priority}
    </Badge>
  );
}
