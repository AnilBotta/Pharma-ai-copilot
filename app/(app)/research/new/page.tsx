"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Plus, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { GENERAL_DISCLAIMER } from "@/lib/agents";
import { api, ApiError, type Project } from "@/lib/api";

const JURISDICTIONS = ["EP", "US", "WO", "JP", "CN", "KR", "GB", "DE", "FR"];

const DEVELOPMENT_STAGES = [
  "Discovery",
  "Preclinical",
  "IND-enabling",
  "Phase I",
  "Phase II",
  "Phase III",
];

export default function NewResearchPage() {
  const router = useRouter();

  const [mode, setMode] = React.useState<"simple" | "advanced">("simple");
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = React.useState(true);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [projectId, setProjectId] = React.useState("");
  const [question, setQuestion] = React.useState("");
  const [molecule, setMolecule] = React.useState("");
  const [indication, setIndication] = React.useState("");
  const [dosageForm, setDosageForm] = React.useState("");
  const [route, setRoute] = React.useState("");
  const [deliveryTech, setDeliveryTech] = React.useState("");
  const [stage, setStage] = React.useState("");
  const [jurisdictions, setJurisdictions] = React.useState<string[]>(["EP", "US"]);
  const [dateFrom, setDateFrom] = React.useState("2015");
  const [dateTo, setDateTo] = React.useState("");
  const [maxResults, setMaxResults] = React.useState("50");
  const [instructions, setInstructions] = React.useState("");

  const [newProjectName, setNewProjectName] = React.useState("");
  const [creatingProject, setCreatingProject] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    api
      .listProjects()
      .then((list) => {
        if (!active) return;
        setProjects(list);
        if (list.length > 0) setProjectId(list[0].id);
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoadingProjects(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleCreateProject() {
    if (!newProjectName.trim()) return;
    setCreatingProject(true);
    setError(null);
    try {
      const project = await api.createProject({ name: newProjectName.trim() });
      setProjects((prev) => [project, ...prev]);
      setProjectId(project.id);
      setNewProjectName("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (!projectId) {
      setError("Select or create a project first.");
      return;
    }

    setSubmitting(true);
    try {
      const { run_id } = await api.createRun({
        project_id: projectId,
        original_question: question.trim(),
        ...(mode === "advanced" && {
          molecule: molecule || undefined,
          indication: indication || undefined,
          dosage_form: dosageForm || undefined,
          route_of_administration: route || undefined,
          delivery_technology: deliveryTech || undefined,
          development_stage: stage || undefined,
          jurisdictions,
          date_from: dateFrom ? Number(dateFrom) : undefined,
          date_to: dateTo ? Number(dateTo) : undefined,
          additional_instructions: instructions || undefined,
        }),
        max_results: Number(maxResults) || 50,
      });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="New research"
        description="Submit a research question. The supervisor plans the work, specialist agents retrieve real sources, and every citation resolves to a stored record."
        icon={Sparkles}
      />

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-[15px]">Project</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loadingProjects ? (
              <p className="text-sm text-muted-foreground">Loading projects…</p>
            ) : projects.length > 0 ? (
              <div className="space-y-2">
                <Label htmlFor="project">Assign this run to</Label>
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger id="project">
                    <SelectValue placeholder="Select a project" />
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((project) => (
                      <SelectItem key={project.id} value={project.id}>
                        {project.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                You have no projects yet. Create one to hold this run.
              </p>
            )}

            <div className="flex items-end gap-2 border-t pt-4">
              <div className="flex-1 space-y-2">
                <Label htmlFor="new-project">Or create a new project</Label>
                <Input
                  id="new-project"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="Peptide Depot Delivery Feasibility Assessment"
                />
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={handleCreateProject}
                disabled={creatingProject || !newProjectName.trim()}
              >
                {creatingProject ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Plus className="size-4" />
                )}
                Create
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-[15px]">Research question</CardTitle>
            <Tabs
              value={mode}
              onValueChange={(v) => setMode(v as "simple" | "advanced")}
            >
              <TabsList>
                <TabsTrigger value="simple">Simple</TabsTrigger>
                <TabsTrigger value="advanced">Advanced</TabsTrigger>
              </TabsList>
            </Tabs>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="question">
                What do you want to find out?{" "}
                <span className="text-destructive">*</span>
              </Label>
              <Textarea
                id="question"
                required
                minLength={10}
                maxLength={4000}
                rows={5}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Evaluate the scientific feasibility, patent landscape, critical quality attributes, formulation-development pathway, analytical strategy, nonclinical risks, and stage-gate development plan for a sustained-release depot injection of a therapeutic peptide using carbon nanotube-based delivery technology."
              />
              <p className="text-xs text-muted-foreground">
                {question.length} / 4000 characters. Be specific: the searches are
                generated from this text.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="max-results">Maximum sources per provider</Label>
              <Input
                id="max-results"
                type="number"
                min={1}
                max={200}
                value={maxResults}
                onChange={(e) => setMaxResults(e.target.value)}
                className="max-w-[200px]"
              />
              <p className="text-xs text-muted-foreground">
                Higher values retrieve more evidence and cost more in API calls
                and tokens.
              </p>
            </div>
          </CardContent>
        </Card>

        {mode === "advanced" && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Product context</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <Field
                  id="molecule"
                  label="Molecule or modality"
                  value={molecule}
                  onChange={setMolecule}
                  placeholder="Therapeutic peptide"
                />
                <Field
                  id="indication"
                  label="Indication"
                  value={indication}
                  onChange={setIndication}
                  placeholder="Type 2 diabetes"
                />
                <Field
                  id="dosage-form"
                  label="Dosage form"
                  value={dosageForm}
                  onChange={setDosageForm}
                  placeholder="Depot injection"
                />
                <Field
                  id="route"
                  label="Route of administration"
                  value={route}
                  onChange={setRoute}
                  placeholder="Subcutaneous"
                />
                <Field
                  id="delivery-tech"
                  label="Delivery technology"
                  value={deliveryTech}
                  onChange={setDeliveryTech}
                  placeholder="Carbon nanotube carrier"
                />
                <div className="space-y-2">
                  <Label htmlFor="stage">Development stage</Label>
                  <Select value={stage} onValueChange={setStage}>
                    <SelectTrigger id="stage">
                      <SelectValue placeholder="Select a stage" />
                    </SelectTrigger>
                    <SelectContent>
                      {DEVELOPMENT_STAGES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-[15px]">Search scope</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Label>Patent jurisdictions</Label>
                  <div className="flex flex-wrap gap-2">
                    {JURISDICTIONS.map((code) => {
                      const active = jurisdictions.includes(code);
                      return (
                        <button
                          key={code}
                          type="button"
                          aria-pressed={active}
                          onClick={() =>
                            setJurisdictions((prev) =>
                              active
                                ? prev.filter((j) => j !== code)
                                : [...prev, code]
                            )
                          }
                          className={
                            active
                              ? "rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                              : "rounded-md border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent"
                          }
                        >
                          {code}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="date-from">Literature from year</Label>
                    <Input
                      id="date-from"
                      type="number"
                      min={1800}
                      max={2200}
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="date-to">To year</Label>
                    <Input
                      id="date-to"
                      type="number"
                      min={1800}
                      max={2200}
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      placeholder="Present"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="instructions">Additional instructions</Label>
                  <Textarea
                    id="instructions"
                    rows={3}
                    maxLength={2000}
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    placeholder="Focus on injection-site tolerability. Exclude oral delivery."
                  />
                </div>
              </CardContent>
            </Card>
          </>
        )}

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-xl text-xs leading-relaxed text-muted-foreground">
            {GENERAL_DISCLAIMER}
          </p>
          <Button
            type="submit"
            size="lg"
            className="gap-2"
            disabled={submitting || question.trim().length < 10 || !projectId}
          >
            {submitting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            {submitting ? "Starting run…" : "Start research"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
