"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, FolderGit2, Loader2, Plus } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Project } from "@/lib/api";
import { formatRelative } from "@/lib/utils";

export default function ProjectsPage() {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    api
      .listProjects()
      .then((list) => active && setProjects(list))
      .catch(
        (err) =>
          active && setError(err instanceof ApiError ? err.message : String(err))
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setProjects((prev) => [project, ...prev]);
      setName("");
      setDescription("");
      setOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Projects"
        description="Group related research runs into a programme."
        icon={FolderGit2}
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> New project
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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderGit2}
          title="No projects yet"
          description="Create a project to hold your research runs."
          actionLabel="New project"
          onAction={() => setOpen(true)}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Card key={project.id} className="transition-colors hover:border-primary/40">
              <CardContent className="py-5">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-sm font-semibold leading-snug">
                    {project.name}
                  </h2>
                  {project.is_seed && <Badge variant="info">Demo</Badge>}
                </div>

                {project.description && (
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                    {project.description}
                  </p>
                )}

                <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    {project.run_count} run{project.run_count === 1 ? "" : "s"}
                  </span>
                  <span>{formatRelative(project.created_at)}</span>
                </div>

                <div className="mt-4 flex gap-2">
                  <Button asChild size="sm" variant="outline" className="flex-1">
                    <Link href={`/runs?project=${project.id}`}>View runs</Link>
                  </Button>
                  <Button asChild size="sm" className="flex-1">
                    <Link href="/research/new">New research</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Projects group related research runs. You can change these details
              later.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-name">
                Name <span className="text-destructive">*</span>
              </Label>
              <Input
                id="project-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Peptide Depot Delivery Feasibility Assessment"
                maxLength={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-description">Description</Label>
              <Textarea
                id="project-description"
                rows={3}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={creating || !name.trim()}>
              {creating && <Loader2 className="size-4 animate-spin" />}
              Create project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
