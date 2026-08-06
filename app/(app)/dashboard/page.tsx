"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  LayoutDashboard,
  Loader2,
  Plus,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { StatCard } from "@/components/shared/stat-card";
import { EmptyState } from "@/components/shared/empty-state";
import { RunStatusBadge } from "@/components/runs/run-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type Dashboard, type RunSummary } from "@/lib/api";
import { formatRelative } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const [summary, setSummary] = React.useState<Dashboard | null>(null);
  const [runs, setRuns] = React.useState<RunSummary[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    Promise.all([api.dashboard(), api.listRuns()])
      .then(([dashboard, runList]) => {
        if (!active) return;
        setSummary(dashboard);
        setRuns(runList.slice(0, 8));
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Dashboard"
        description="Research activity across your projects."
        icon={LayoutDashboard}
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
            <div className="text-sm">
              <p className="font-medium text-destructive">
                Could not load dashboard data
              </p>
              <p className="mt-1 text-muted-foreground">{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))
        ) : (
          <>
            <StatCard
              label="Running"
              value={String(summary?.running ?? 0)}
              icon={Loader2}
            />
            <StatCard
              label="Completed"
              value={String(summary?.completed ?? 0)}
              icon={CheckCircle2}
            />
            <StatCard
              label="Failed"
              value={String(summary?.failed ?? 0)}
              icon={AlertTriangle}
            />
            <StatCard
              label="Estimated cost"
              value={formatCost(summary?.total_cost)}
              icon={FileText}
            />
          </>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-[15px]">Recent research runs</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 rounded-lg" />
                ))}
              </div>
            ) : runs.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No research runs yet"
                description="Submit a research question to start your first run."
                actionLabel="Start research"
                onAction={() => router.push("/research/new")}
              />
            ) : (
              <ul className="divide-y">
                {runs.map((run) => (
                  <li key={run.id}>
                    <Link
                      href={`/runs/${run.id}`}
                      className="-mx-2 flex items-start gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-accent"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-sm font-medium">
                          {run.original_question}
                        </p>
                        <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <Clock className="size-3" />
                          {formatRelative(run.created_at)}
                          {run.evidence_count > 0 && (
                            <span>· {run.evidence_count} sources</span>
                          )}
                        </p>
                      </div>
                      <RunStatusBadge status={run.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-[15px]">Sources retrieved</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <Skeleton className="h-24 rounded-lg" />
            ) : (
              <>
                <SourceCount
                  label="Publications"
                  value={summary?.source_counts?.literature ?? 0}
                />
                <SourceCount
                  label="Patent families"
                  value={summary?.source_counts?.patents ?? 0}
                />
                <div className="border-t pt-4 text-xs text-muted-foreground">
                  <p>
                    {(summary?.total_tokens ?? 0).toLocaleString()} tokens used
                    across {summary?.total_runs ?? 0} run
                    {summary?.total_runs === 1 ? "" : "s"}.
                  </p>
                  <p className="mt-1">
                    Cost is estimated from configured model pricing and is not a
                    billing figure.
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SourceCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </div>
  );
}

function formatCost(value: number | undefined): string {
  if (!value) return "$0.00";
  return `$${value.toFixed(2)}`;
}
