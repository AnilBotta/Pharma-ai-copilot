"use client";

import * as React from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import type {
  AttachableRun,
  ControlledDocument,
  Requirement,
} from "@/lib/api";
export type EvidenceKind = "document" | "research_run" | "url" | "note" | "data";

export function AttachEvidenceDialog({
  open,
  onOpenChange,
  requirement: req,
  runs,
  docs,
  projectId,
  onAttach,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  requirement: Requirement;
  runs: AttachableRun[];
  docs: ControlledDocument[];
  projectId: string;
  onAttach: (body: {
    evidence_type: EvidenceKind;
    research_run_id?: string;
    document_version_id?: string;
    external_url?: string;
    note?: string;
    title?: string;
  }) => void;
}) {
  // Default to whatever this requirement actually demands, so the common case
  // needs no thought and the wrong type is not the path of least resistance.
  const [kind, setKind] = React.useState<EvidenceKind>(
    req.required_evidence_type === "any"
      ? "research_run"
      : (req.required_evidence_type as EvidenceKind)
  );
  const [runId, setRunId] = React.useState("");
  const [versionId, setVersionId] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [note, setNote] = React.useState("");
  const [title, setTitle] = React.useState("");

  // Only versions the engine would accept. Offering a superseded one and
  // rejecting it on submit would be a worse way to learn the same thing.
  const usableVersions = docs
    .filter((d) => d.current_version?.is_usable)
    .map((d) => ({ doc: d, version: d.current_version! }));

  const submit = () => {
    onAttach({
      evidence_type: kind,
      research_run_id: kind === "research_run" ? runId : undefined,
      document_version_id: kind === "document" ? versionId : undefined,
      external_url: kind === "url" ? url.trim() : undefined,
      note: kind === "note" || kind === "data" ? note.trim() : undefined,
      title: title.trim() || undefined,
    });
    onOpenChange(false);
    setRunId("");
    setVersionId("");
    setUrl("");
    setNote("");
    setTitle("");
  };

  const valid =
    (kind === "research_run" && runId) ||
    (kind === "document" && versionId) ||
    (kind === "url" && url.trim()) ||
    (kind === "note" && note.trim()) ||
    (kind === "data" && note.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Attach evidence to {req.ref_code}</DialogTitle>
          <DialogDescription>
            Attaching evidence supersedes any current approval, because an
            approval describes one specific evidence set.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="evidence-kind">Type</Label>
            <NativeSelect
              id="evidence-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as EvidenceKind)}
            >
              <option value="document">Controlled document</option>
              <option value="research_run">Completed research run</option>
              <option value="data">Data</option>
              <option value="url">Link</option>
              <option value="note">Note</option>
            </NativeSelect>
            {req.required_evidence_type !== "any" &&
              kind !== req.required_evidence_type && (
                <p className="rounded-md border border-warning-border bg-warning-surface px-2.5 py-2 text-xs text-warning">
                  This requirement asks for{" "}
                  <code className="font-mono">{req.required_evidence_type}</code>{" "}
                  evidence. Anything else can be attached, but it will not
                  satisfy the requirement.
                </p>
              )}
          </div>

          {kind === "document" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-doc">Document version</Label>
              <NativeSelect
                id="evidence-doc"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
              >
                <option value="">Select a document…</option>
                {usableVersions.map(({ doc, version }) => (
                  <option key={version.id} value={version.id}>
                    {doc.document_number} — {doc.title} ({version.version_label},{" "}
                    {version.status})
                  </option>
                ))}
              </NativeSelect>
              {usableVersions.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No approved or effective document versions are registered for
                  this project yet. Only a version that is approved or
                  effective, and still in date, can satisfy a requirement —{" "}
                  <Link
                    href={`/programmes/${projectId}/documents`}
                    className="text-primary hover:underline"
                  >
                    open the document register
                  </Link>
                  .
                </p>
              )}
            </div>
          )}

          {kind === "research_run" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-run">Research run</Label>
              <NativeSelect
                id="evidence-run"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
              >
                <option value="">Select a run…</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.original_question.slice(0, 70)}
                    {r.original_question.length > 70 ? "…" : ""} ·{" "}
                    {r.evidence_count} sources
                  </option>
                ))}
              </NativeSelect>
              {runs.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No completed research runs on this project yet. Only completed
                  runs may be cited — an unfinished run carries no verified
                  evidence.
                </p>
              )}
            </div>
          )}

          {kind === "data" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-data">Data</Label>
              <Textarea
                id="evidence-data"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What was measured, and the result — a value, a table, or a summary of a dataset held elsewhere."
              />
            </div>
          )}

          {kind === "url" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-url">URL</Label>
              <Input
                id="evidence-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
              />
            </div>
          )}

          {kind === "note" && (
            <div className="space-y-2">
              <Label htmlFor="evidence-note">Note</Label>
              <Textarea
                id="evidence-note"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="evidence-title">Label</Label>
            <Input
              id="evidence-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="How this should appear in the gate pack"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!valid} onClick={submit}>
            Attach
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
