"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  FileText,
  GitBranch,
  LayoutDashboard,
  Plus,
} from "lucide-react";

import {
  awaitingDecision,
  NeedsDecision,
  PortfolioRows,
} from "@/components/pdp/needs-decision";
import { RunStatusBadge } from "@/components/runs/run-status-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import {
  api,
  ApiError,
  pdp,
  type Dashboard,
  type ProgrammeSummary,
  type RunSummary,
} from "@/lib/api";
import { formatRelative } from "@/lib/utils";

/**
 * The dashboard used to be four research-run counters and a list of runs —
 * Running, Completed, Failed, Estimated cost — with no mention of stage gates
 * at all. Somebody with gate authority opened the product and saw telemetry
 * from the research agent rather than the state of their portfolio.
 *
 * It now leads with what is waiting on a person, then the portfolio, and
 * demotes research activity to a strip at the bottom. Research is still the
 * thing you start from here; it is no longer the only thing the page knows.
 */
export default function DashboardPage() {
  const router = useRouter();
  const [summary, setSummary] = React.useState<Dashboard | null>(null);
  const [runs, setRuns] = React.useState<RunSummary[]>([]);
  const [programmes, setProgrammes] = React.useState<ProgrammeSummary[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    // allSettled, not all: a portfolio the account cannot fully read must not
    // blank the research half of the page, and vice versa.
    Promise.allSettled([api.dashboard(), api.listRuns(), pdp.listProgrammes()])
      .then(([dash, runList, progs]) => {
        if (!active) return;
        if (dash.status === "fulfilled") setSummary(dash.value);
        if (runList.status === "fulfilled") setRuns(runList.value.slice(0, 6));
        if (progs.status === "fulfilled") setProgrammes(progs.value);

        const firstFailure = [dash, runList, progs].find(
          (r): r is PromiseRejectedResult => r.status === "rejected"
        );
        if (firstFailure) {
          const reason = firstFailure.reason;
          setError(reason instanceof ApiError ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Shared with the list below, so the headline can never disagree with what
  // is actually rendered under it.
  const waitingCount = awaitingDecision(programmes).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title={
          loading
            ? "Dashboard"
            : waitingCount === 0
              ? "Nothing is waiting on a decision"
              : waitingCount === 1
                ? "One gate needs a decision"
                : `${waitingCount} gates need a decision`
        }
        description="What is waiting on a person, and where every programme stands."
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
        <Card tone="danger">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" />
            <div className="text-sm">
              <p className="font-medium text-danger">
                Some of this page could not be loaded
              </p>
              <p className="mt-1 text-muted-foreground">{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── waiting on a person ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className="type-label text-muted-foreground">Waiting on you</h2>
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 rounded-xl" />
            <Skeleton className="h-20 rounded-xl" />
          </div>
        ) : programmes.length === 0 ? (
          <EmptyState
            icon={GitBranch}
            title="No programmes yet"
            description="Instantiate a stage-gate template against a project to begin tracking its gates."
            actionLabel="Start a programme"
            onAction={() => router.push("/programmes")}
            compact
          />
        ) : (
          <NeedsDecision programmes={programmes} />
        )}
      </section>

      {/* ── the portfolio ───────────────────────────────────────────────── */}
      {(loading || programmes.length > 0) && (
        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="type-label text-muted-foreground">Portfolio</h2>
            <Link
              href="/programmes"
              className="text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              All programmes
            </Link>
          </div>
          <Card>
            <CardContent className="py-1">
              {loading ? (
                <div className="py-4">
                  <SkeletonText lines={4} />
                </div>
              ) : (
                <PortfolioRows programmes={programmes} />
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* ── research, deliberately below the fold ───────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="type-label text-muted-foreground">
            Research activity
          </h2>
          <Link
            href="/runs"
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            All runs
          </Link>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {loading
            ? Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))
            : [
                { label: "Running", value: String(summary?.running ?? 0) },
                { label: "Completed", value: String(summary?.completed ?? 0) },
                { label: "Failed", value: String(summary?.failed ?? 0) },
                {
                  label: "Estimated cost",
                  value: formatCost(summary?.total_cost),
                },
              ].map((stat) => (
                <Card key={stat.label}>
                  <CardContent className="py-4">
                    <p className="type-label text-muted-foreground">
                      {stat.label}
                    </p>
                    <p className="metric mt-1.5 text-2xl">{stat.value}</p>
                  </CardContent>
                </Card>
              ))}
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-md">Recent runs</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <SkeletonText lines={3} />
            ) : runs.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No research runs yet"
                description="Submit a research question to start your first run."
                actionLabel="Start research"
                onAction={() => router.push("/research/new")}
                compact
              />
            ) : (
              <div className="divide-y">
                {runs.map((run) => (
                  <Link
                    key={run.id}
                    href={`/runs/${run.id}`}
                    className="flex items-center gap-4 py-3 outline-none transition-colors hover:bg-accent/40"
                  >
                    <p className="min-w-0 flex-1 truncate text-sm">
                      {run.original_question}
                    </p>
                    <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
                      {formatRelative(run.created_at)}
                    </span>
                    <RunStatusBadge status={run.status} />
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function formatCost(value: number | undefined) {
  if (value === undefined || value === null) return "$0.00";
  return `$${value.toFixed(2)}`;
}
