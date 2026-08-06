import { Badge } from "@/components/ui/badge";
import type { RunStatus } from "@/lib/api";

const VARIANTS: Record<
  RunStatus,
  { label: string; variant: "default" | "success" | "warning" | "info" | "destructive" }
> = {
  queued: { label: "Queued", variant: "default" },
  running: { label: "Running", variant: "info" },
  awaiting_review: { label: "Awaiting review", variant: "warning" },
  completed: { label: "Completed", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
  cancelled: { label: "Cancelled", variant: "default" },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const config = VARIANTS[status] ?? VARIANTS.queued;
  return (
    <Badge variant={config.variant} className="shrink-0 gap-1.5">
      {status === "running" && (
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
      )}
      {config.label}
    </Badge>
  );
}
