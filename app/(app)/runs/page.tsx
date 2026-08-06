"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, Clock, ListChecks, Plus } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { RunStatusBadge } from "@/components/runs/run-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type RunSummary } from "@/lib/api";
import { formatRelative, humanNode } from "@/lib/utils";

export default function RunsPage() {
  const router = useRouter();
  const [runs, setRuns] = React.useState<RunSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    api
      .listRuns()
      .then((list) => active && setRuns(list))
      .catch(
        (err) =>
          active && setError(err instanceof ApiError ? err.message : String(err))
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Research runs"
        description="Every run, with the sources it retrieved and the report it produced."
        icon={ListChecks}
        actions={
          <Button asChild>
            <Link href="/research/new">
              <Plus className="size-4" /> New research
            </Link>
          </Button>
        }
      />

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No research runs yet"
          description="Submit a research question to start your first run."
          actionLabel="Start research"
          onAction={() => router.push("/research/new")}
        />
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <Link key={run.id} href={`/runs/${run.id}`} className="block">
              <Card className="transition-colors hover:border-primary/40">
                <CardContent className="flex items-start gap-4 py-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-2 text-sm font-medium">
                        {run.original_question}
                      </p>
                      <RunStatusBadge status={run.status} />
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      {run.project_name && <span>{run.project_name}</span>}
                      <span className="flex items-center gap-1">
                        <Clock className="size-3" />
                        {formatRelative(run.created_at)}
                      </span>
                      <span>{run.evidence_count} sources</span>
                      {run.estimated_cost_usd > 0 && (
                        <span>${run.estimated_cost_usd.toFixed(3)}</span>
                      )}
                    </div>

                    {run.status === "running" && (
                      <div className="mt-3 space-y-1">
                        <div className="h-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-all"
                            style={{ width: `${run.progress_pct}%` }}
                          />
                        </div>
                        {run.current_node && (
                          <p className="text-xs text-muted-foreground">
                            {humanNode(run.current_node)}
                          </p>
                        )}
                      </div>
                    )}

                    {run.status === "failed" && run.error_message && (
                      <p className="mt-2 line-clamp-2 text-xs text-destructive">
                        {run.error_message}
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
