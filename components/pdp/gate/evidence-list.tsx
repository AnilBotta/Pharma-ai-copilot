"use client";

import Link from "next/link";
import {
  ExternalLink,
  FileText,
  FlaskConical,
  Link2,
  StickyNote,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatRelative } from "@/lib/utils";
import type { Requirement } from "@/lib/api";
export function EvidenceList({
  requirement: req,
  onDetach,
  busy,
}: {
  requirement: Requirement;
  onDetach: (evidenceId: string) => void;
  busy: boolean;
}) {
  if (req.evidence.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No evidence attached. Required type:{" "}
        <code className="font-mono">{req.required_evidence_type}</code>.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">Evidence</p>
      {req.evidence.map((e) => (
        <div
          key={e.id}
          className="flex items-start gap-2 rounded-lg border px-3 py-2 text-xs"
        >
          {e.evidence_type === "document" ? (
            <FileText className="mt-0.5 size-3.5 shrink-0 text-primary" />
          ) : e.evidence_type === "research_run" ? (
            <FlaskConical className="mt-0.5 size-3.5 shrink-0 text-primary" />
          ) : e.evidence_type === "url" ? (
            <Link2 className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <StickyNote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0 flex-1">
            <p className="font-medium">
              {e.title ??
                (e.document_number
                  ? `${e.document_number} — ${e.document_title}`
                  : null) ??
                e.research_run_question ??
                e.external_url ??
                e.note}
            </p>
            <p className="text-muted-foreground">
              {e.evidence_type}
              {e.document_version_label && ` · ${e.document_version_label}`}
              {e.added_by_name && ` · ${e.added_by_name}`} ·{" "}
              {formatRelative(e.created_at)}
            </p>

            {/* A superseded document is the quiet way a gate goes stale. Say it
                where the evidence is, not only in the blocker list. */}
            {e.document_is_usable === false && (
              <p className="mt-1 rounded border border-destructive/30 bg-destructive/5 px-2 py-1 text-destructive">
                This version is {e.document_version_status} and no longer
                satisfies the requirement. Attach the current version.
              </p>
            )}

            {e.document_storage_url && (
              <a
                href={e.document_storage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                Open the document <ExternalLink className="size-3" />
              </a>
            )}
            {e.research_run_id && (
              <Link
                href={`/runs/${e.research_run_id}`}
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                Open the run <ExternalLink className="size-3" />
              </Link>
            )}
            {e.external_url && (
              <a
                href={e.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-primary hover:underline"
              >
                {e.external_url} <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onDetach(e.id)}
            aria-label="Remove evidence"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      ))}
      <p className="text-xs text-muted-foreground">
        Changing evidence supersedes any approval — an approval is a statement
        about one evidence set.
      </p>
    </div>
  );
}
