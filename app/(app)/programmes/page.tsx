"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, GitBranch, Loader2, Plus } from "lucide-react";

import {
  PortfolioHeatmap,
  usePortfolioMatrix,
} from "@/components/charts/portfolio-heatmap";
import { GateStatusBadge, ReadyVerdict } from "@/components/pdp/gate-readiness";
import { PortfolioBriefing } from "@/components/pdp/portfolio-briefing";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
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
import { NativeSelect } from "@/components/ui/native-select";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  ApiError,
  pdp,
  type PdpTemplate,
  type Project,
  type ProgrammeSummary,
} from "@/lib/api";

export default function ProgrammesPage() {
  const [programmes, setProgrammes] = React.useState<ProgrammeSummary[]>([]);
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [templates, setTemplates] = React.useState<PdpTemplate[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [open, setOpen] = React.useState(false);
  const [projectId, setProjectId] = React.useState("");
  const [templateId, setTemplateId] = React.useState("");
  const [startDate, setStartDate] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const matrix = usePortfolioMatrix(programmes);

  const load = React.useCallback(async () => {
    try {
      const [list, allProjects, allTemplates] = await Promise.all([
        pdp.listProgrammes(),
        api.listProjects(),
        pdp.listTemplates(),
      ]);
      setProgrammes(list);
      setProjects(allProjects);
      setTemplates(allTemplates);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Only templates the organisation has approved may be instantiated. Draft
  // ones are shown as disabled so the reason is visible rather than mysterious.
  const activeTemplates = templates.filter((t) => t.status === "active");
  const enrolled = new Set(programmes.map((p) => p.id));
  const available = projects.filter((p) => !enrolled.has(p.id));

  async function handleCreate() {
    if (!projectId || !templateId) return;
    setCreating(true);
    setError(null);
    try {
      await pdp.instantiate(projectId, {
        template_id: templateId,
        start_date: startDate || undefined,
      });
      setOpen(false);
      setProjectId("");
      setTemplateId("");
      setStartDate("");
      setLoading(true);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Programmes"
        description="Product development programmes tracked through their stage gates."
        icon={GitBranch}
        actions={
          <Button onClick={() => setOpen(true)} disabled={available.length === 0}>
            <Plus className="size-4" /> Start a programme
          </Button>
        }
      />

      {error && (
        <Card variant="flush" tone="danger">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-danger"
            />
            <p className="text-sm text-danger">{error}</p>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : programmes.length === 0 ? (
        <EmptyState
          icon={GitBranch}
          title="No programmes yet"
          description="Instantiate a stage-gate template against a project to begin tracking its gates."
          actionLabel={available.length > 0 ? "Start a programme" : undefined}
          onAction={available.length > 0 ? () => setOpen(true) : undefined}
        />
      ) : (
        <>
          <PortfolioBriefing programmeCount={programmes.length} />

          {/* Above the cards: the cards answer "how is this one programme
              doing", the grid answers "where is the portfolio stuck", and the
              second question is the one somebody opens this page with. */}
          <Card>
            <CardContent className="space-y-4 py-5">
              <div>
                <h2 className="type-label text-muted-foreground">
                  Every gate, every programme
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  A gate is green only once it has actually been approved —
                  readiness alone never colours a cell.
                </p>
              </div>
              <PortfolioHeatmap {...matrix} />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            {programmes.map((programme) => (
              <ProgrammeCard key={programme.id} programme={programme} />
            ))}
          </div>
        </>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start a programme</DialogTitle>
            <DialogDescription>
              The template is copied into the project. Later edits to the
              template will not change what this programme&apos;s gates demand.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="programme-project">Project</Label>
              <NativeSelect
                id="programme-project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
              >
                <option value="">Select a project…</option>
                {available.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </NativeSelect>
            </div>

            <div className="space-y-2">
              <Label htmlFor="programme-template">Template</Label>
              <NativeSelect
                id="programme-template"
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
              >
                <option value="">Select a template…</option>
                {activeTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} (v{t.version}) — {t.requirement_count} requirements
                  </option>
                ))}
              </NativeSelect>
              {activeTemplates.length === 0 && (
                <p className="rounded-md border border-warning-border bg-warning-surface px-2.5 py-2 text-xs text-warning">
                  No template has been approved for use yet. Seeded templates are
                  scaffolding, not regulatory advice, and must be reviewed and
                  approved by your scientific, quality and regulatory functions
                  before a programme can be built on them.
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="programme-start">Programme start date</Label>
              <Input
                id="programme-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Optional. Requirement due dates are derived from it. Left blank,
                requirements carry no due date rather than an invented one.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={creating || !projectId || !templateId}
            >
              {creating && <Loader2 className="size-4 animate-spin" />}
              Instantiate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProgrammeCard({ programme }: { programme: ProgrammeSummary }) {
  const pct = programme.readiness_pct ?? 0;
  const isReady = programme.is_ready ?? false;

  return (
    <Card className="transition-colors hover:border-primary/40">
      <CardContent className="space-y-4 py-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{programme.name}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {programme.current_stage_name ?? "No current stage"}
            </p>
          </div>
          {programme.current_gate_status && (
            <GateStatusBadge status={programme.current_gate_status} />
          )}
        </div>

        {programme.current_stage_pk && (
          <div className="space-y-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-lg font-semibold tabular-nums">
                {pct.toFixed(1)}%
              </span>
              {/* The verdict travels with the number, never after it. */}
              <ReadyVerdict
                isReady={isReady}
                blockerCount={programme.blocker_count ?? 0}
              />
            </div>
            <Progress
              value={pct}
              tone={isReady ? "success" : "warning"}
              valueText={`${pct.toFixed(1)} percent, ${
                isReady ? "ready for review" : "not ready"
              }`}
            />
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{programme.stage_count} gates</span>
          <Button asChild size="sm" variant="outline">
            <Link href={`/programmes/${programme.id}`}>Open programme</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
