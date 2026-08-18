"use client";

import * as React from "react";
import { ExternalLink, FileText, ShieldCheck, Upload } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { INTERNAL_DOCUMENT_DISCLAIMER, PATENT_DISCLAIMER } from "@/lib/agents";
import type { Evidence } from "@/lib/api";

const ACCESS_LABELS: Record<string, { label: string; variant: "success" | "warning" | "muted" }> = {
  full_text: { label: "Full text", variant: "success" },
  abstract_only: { label: "Abstract only", variant: "warning" },
  metadata_only: { label: "Metadata only", variant: "muted" },
};

export function SourceExplorer({ evidence }: { evidence: Evidence[] }) {
  const literature = evidence.filter((e) => e.source_type === "literature");
  const patents = evidence.filter((e) => e.source_type === "patent");
  const documents = evidence.filter((e) => e.source_type === "internal_document");

  return (
    <Tabs defaultValue="literature">
      <TabsList>
        <TabsTrigger value="literature">
          Literature {literature.length > 0 && `(${literature.length})`}
        </TabsTrigger>
        <TabsTrigger value="patents">
          Patents {patents.length > 0 && `(${patents.length})`}
        </TabsTrigger>
        <TabsTrigger value="documents">
          Internal {documents.length > 0 && `(${documents.length})`}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="literature" className="mt-4">
        {literature.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No publications retrieved"
            description="Either no results matched, or the literature providers were unavailable. This is not evidence that no relevant literature exists."
            compact
          />
        ) : (
          <div className="space-y-3">
            {literature.map((item) => (
              <SourceCard key={item.id} evidence={item} />
            ))}
          </div>
        )}
      </TabsContent>

      <TabsContent value="patents" className="mt-4 space-y-3">
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed">
          <ShieldCheck className="mb-1 inline size-3.5 text-amber-600 dark:text-amber-400" />{" "}
          {PATENT_DISCLAIMER}
        </div>
        {patents.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No patent families retrieved"
            description="Either no results matched, or the patent provider was unavailable. This is not evidence that no relevant patents exist."
            compact
          />
        ) : (
          patents.map((item) => <SourceCard key={item.id} evidence={item} />)
        )}
      </TabsContent>

      <TabsContent value="documents" className="mt-4 space-y-3">
        {documents.length > 0 && (
          <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 text-xs leading-relaxed">
            <Upload className="mb-1 inline size-3.5 text-sky-600 dark:text-sky-400" />{" "}
            {INTERNAL_DOCUMENT_DISCLAIMER}
          </div>
        )}
        {documents.length === 0 ? (
          <EmptyState
            icon={Upload}
            title="No internal documents used"
            description="Documents you upload and attach to a run appear here, cited with page references."
            compact
          />
        ) : (
          <div className="space-y-3">
            {documents.map((item) => (
              <SourceCard key={item.id} evidence={item} />
            ))}
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}

function SourceCard({ evidence }: { evidence: Evidence }) {
  // For an uploaded document the access level is always `full_text` - the
  // passage was read in full - and rendering that as a green "Full text" badge
  // borrows the visual language of a peer-reviewed paper we obtained in full.
  // Accurate, and misleading. It says what the source is instead.
  const access =
    evidence.source_type === "internal_document"
      ? { label: "Uploaded", variant: "muted" as const }
      : ACCESS_LABELS[evidence.access_level] ?? ACCESS_LABELS.metadata_only;

  return (
    <article className="rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono">
              {evidence.marker}
            </Badge>
            <Badge variant={access.variant}>{access.label}</Badge>
            {evidence.evidence_category && (
              <Badge variant="muted">
                {evidence.evidence_category.replace(/_/g, " ")}
              </Badge>
            )}
          </div>
          <h3 className="mt-2 text-sm font-medium leading-snug">{evidence.title}</h3>
        </div>
        {evidence.relevance_score !== null && (
          <div className="shrink-0 text-right">
            <p className="text-lg font-semibold tabular-nums">
              {(evidence.relevance_score * 100).toFixed(0)}
            </p>
            <p className="text-[10px] text-muted-foreground">relevance</p>
          </div>
        )}
      </div>

      {evidence.authors.length > 0 && (
        <p className="mt-2 line-clamp-1 text-xs text-muted-foreground">
          {evidence.authors.slice(0, 4).join(", ")}
          {evidence.authors.length > 4 && " et al."}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{evidence.provider}</span>
        {evidence.publication_date && (
          <span>{String(evidence.publication_date).slice(0, 10)}</span>
        )}
        {evidence.identifier && (
          <span className="font-mono">
            {evidence.identifier_type?.toUpperCase()}: {evidence.identifier}
          </span>
        )}
        {evidence.url && (
          <a
            href={evidence.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            Open <ExternalLink className="size-3" />
          </a>
        )}
      </div>

      {evidence.cited_in_sections.length > 0 && (
        <div className="mt-3 border-t pt-2">
          <p className="text-[11px] text-muted-foreground">
            Cited in:{" "}
            {evidence.cited_in_sections
              .map((s) => s.replace(/_/g, " "))
              .join(", ")}
          </p>
        </div>
      )}
    </article>
  );
}
