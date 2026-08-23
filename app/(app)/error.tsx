"use client";

import * as React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/**
 * The shell had no error boundary at all, so a render error anywhere inside
 * it — a payload shaped differently from what a page expected, a null where
 * a name was assumed — took out the whole application and left a blank page.
 *
 * This keeps the sidebar and topbar alive and confines the damage to the
 * route, which is the point of the boundary.
 *
 * The message is deliberately not dressed up. This is a regulated-industry
 * tool: "something went wrong" tells somebody nothing, and the digest is what
 * makes a report actionable.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error("Route error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="max-w-lg border-danger-border bg-danger-surface">
        <CardContent className="flex flex-col gap-4 py-6">
          <div className="flex items-start gap-3">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-danger"
            />
            <div className="min-w-0">
              <h2 className="text-md font-semibold text-danger">
                This page could not be displayed
              </h2>
              <p className="mt-1.5 text-sm text-muted-foreground">
                The rest of the application is unaffected — the sidebar and
                your other programmes still work. Nothing was saved or changed
                by this failure.
              </p>
            </div>
          </div>

          {error.message && (
            <p className="rounded-lg border bg-card px-3 py-2 font-mono text-2xs break-words text-muted-foreground">
              {error.message}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={reset}>
              <RotateCcw className="size-3.5" /> Try again
            </Button>
            {error.digest && (
              <span className="text-2xs text-muted-foreground">
                Reference <span className="font-mono">{error.digest}</span> —
                quote this if you report it.
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
