import { Badge, type BadgeVariant } from "@/components/ui/badge";
import type { RunStatus } from "@/lib/api";

const VARIANTS: Record<RunStatus, { label: string; variant: BadgeVariant }> = {
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
      {/* A running badge pulses; a settled one does not. This is the only
          animated status indicator in the product, and it earns it — the dot
          says the number beside it is still moving. */}
      {status === "running" && (
        <span
          aria-hidden="true"
          className="size-1.5 shrink-0 animate-pulse rounded-full bg-current"
        />
      )}
      {config.label}
    </Badge>
  );
}
