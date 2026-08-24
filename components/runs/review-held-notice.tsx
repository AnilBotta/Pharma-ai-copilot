import { AlertTriangle } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * "This report did not pass its own verification."
 *
 * A badge reading "Awaiting review" does not tell anyone what happened or what
 * to do, and the report is one click from being exported and circulated.
 *
 * This is rendered TWICE on the run page, which needs justifying: once at page
 * level so it is visible from every tab, and once inside `.print-area`, which
 * the print stylesheet lifts to `position:absolute; inset:0` — so anything
 * outside it does not appear on paper at all. Rendering the component in both
 * places is what stops the screen copy and the printed copy from drifting
 * apart, and a held report reaching an auditor without this sentence is the
 * worst thing this page can produce.
 */
export function ReviewHeldNotice({ className }: { className?: string }) {
  return (
    <Card
      variant="flush"
      tone="warning"
      className={cn("print:break-inside-avoid", className)}
    >
      <CardContent className="flex items-start gap-3 py-4">
        <AlertTriangle
          aria-hidden="true"
          className="mt-0.5 size-5 shrink-0 text-warning"
        />
        <div className="space-y-1">
          <p className="text-sm font-medium">
            This report did not pass its own verification
          </p>
          <p className="text-sm text-muted-foreground">
            High-severity findings were still outstanding after the report was
            revised, so the run is held rather than reported as complete. The
            findings are listed at the top of the{" "}
            <span className="font-medium">Limitations</span> section. Treat
            every affected statement as unverified until someone has checked it.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
