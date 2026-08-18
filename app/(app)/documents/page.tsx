"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Loader2,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  documents as documentsApi,
  type Project,
  type UploadedDocument,
  api,
} from "@/lib/api";
import { formatRelative } from "@/lib/utils";

/**
 * Uploaded documents.
 *
 * Two things this page has to get right, both of them about not overstating
 * what happened:
 *
 *   - A document that failed says WHY, in the words the backend recorded. The
 *     common case is a scanned PDF, which contains images of text rather than
 *     text; there is no OCR, and a reader who is not told that will conclude
 *     the system is broken.
 *
 *   - "Processing" is not a spinner that means nothing. While a document is
 *     embedding, its chunk counts are shown, so progress is visible and a
 *     stalled document is distinguishable from a slow one.
 */

/** Statuses that will change on their own, so the list is worth re-fetching. */
const IN_FLIGHT: ReadonlySet<UploadedDocument["status"]> = new Set([
  "pending",
  "extracting",
  "embedding",
]);

const POLL_MS = 4000;

export default function DocumentsPage() {
  const [docs, setDocs] = React.useState<UploadedDocument[]>([]);
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [projectId, setProjectId] = React.useState<string>("");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [uploading, setUploading] = React.useState<string | null>(null);
  const [progress, setProgress] = React.useState(0);
  const [dragging, setDragging] = React.useState(false);

  const inputRef = React.useRef<HTMLInputElement>(null);

  const refresh = React.useCallback(async () => {
    const list = await documentsApi.list();
    setDocs(list);
    return list;
  }, []);

  React.useEffect(() => {
    let active = true;
    Promise.all([documentsApi.list(), api.listProjects()])
      .then(([list, projectList]) => {
        if (!active) return;
        setDocs(list);
        setProjects(projectList);
        if (projectList.length > 0) setProjectId(projectList[0].id);
      })
      .catch((err) => active && setError(describe(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Poll only while something is actually in flight. A page of finished
  // documents makes no requests at all.
  const anyInFlight = docs.some((d) => IN_FLIGHT.has(d.status));
  React.useEffect(() => {
    if (!anyInFlight) return;
    const timer = setInterval(() => {
      refresh().catch(() => {
        // A transient failure should not detach the page from documents that
        // are still progressing; the next tick tries again.
      });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [anyInFlight, refresh]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);

    for (const file of Array.from(files)) {
      setUploading(file.name);
      setProgress(0);
      try {
        await documentsApi.upload(file, {
          projectId: projectId || null,
          onProgress: setProgress,
        });
        await refresh();
      } catch (err) {
        setError(`${file.name}: ${describe(err)}`);
      } finally {
        setUploading(null);
        setProgress(0);
      }
    }
  }

  async function handleDelete(doc: UploadedDocument) {
    setError(null);
    try {
      await documentsApi.remove(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setError(describe(err));
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Documents"
        description="Internal materials you upload become a separate, clearly labelled class of evidence."
        icon={Upload}
      />

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-4 py-6">
          {projects.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <label
                htmlFor="document-project"
                className="text-sm text-muted-foreground"
              >
                Attach to project
              </label>
              <select
                id="document-project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">
                A research run searches the documents on its own project.
              </span>
            </div>
          )}

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              void handleFiles(e.dataTransfer.files);
            }}
            className={`rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
              dragging ? "border-primary bg-primary/5" : "border-muted"
            }`}
          >
            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
              <Upload className="size-6" />
            </div>

            {uploading ? (
              <div className="space-y-2">
                <p className="text-sm font-medium">
                  Uploading {uploading}… {Math.round(progress * 100)}%
                </p>
                <div className="mx-auto h-1.5 w-64 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${Math.round(progress * 100)}%` }}
                  />
                </div>
              </div>
            ) : (
              <>
                <p className="text-sm font-medium">
                  Drop a PDF or text file here
                </p>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                  PDF, plain text and Markdown. Text is extracted, split by page
                  and indexed, so a citation can name the document and the page.
                </p>
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => inputRef.current?.click()}
                >
                  Choose a file
                </Button>
              </>
            )}

            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown"
              className="hidden"
              onChange={(e) => {
                void handleFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <p className="text-xs text-muted-foreground">
            Uploaded content is treated as untrusted input and is never mistaken
            for external scientific or patent evidence. Scanned documents cannot
            be read — there is no OCR, and a scan will be rejected rather than
            silently contributing nothing.
          </p>
        </CardContent>
      </Card>

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : docs.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No documents yet"
          description="Upload internal reports, specifications or prior study summaries to make them searchable alongside published literature."
        />
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

function DocumentRow({
  doc,
  onDelete,
}: {
  doc: UploadedDocument;
  onDelete: (doc: UploadedDocument) => void;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 py-4">
        <FileText className="mt-0.5 size-5 shrink-0 text-muted-foreground" />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium">{doc.filename}</p>
            <StatusBadge doc={doc} />
          </div>

          <p className="mt-1 text-xs text-muted-foreground">
            {formatBytes(doc.size_bytes)}
            {doc.page_count ? ` · ${doc.page_count} pages` : ""}
            {doc.chunk_count ? ` · ${doc.chunk_count} passages` : ""}
            {` · added ${formatRelative(doc.created_at)}`}
          </p>

          {/* The reason, verbatim. A failure without one is the same as a
              silent one. */}
          {doc.status === "failed" && doc.error && (
            <p className="mt-2 text-sm text-destructive">{doc.error}</p>
          )}

          {doc.status === "embedding" && doc.chunk_count > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Indexed {doc.chunk_count - doc.pending_chunk_count} of{" "}
              {doc.chunk_count} passages.
            </p>
          )}
        </div>

        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${doc.filename}`}
          onClick={() => onDelete(doc)}
        >
          <Trash2 className="size-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ doc }: { doc: UploadedDocument }) {
  if (doc.status === "ready") {
    return (
      <Badge variant="secondary" className="gap-1">
        <CheckCircle2 className="size-3" /> Searchable
      </Badge>
    );
  }
  if (doc.status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1">
        <XCircle className="size-3" /> Failed
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1">
      <Loader2 className="size-3 animate-spin" />
      {doc.status === "embedding" ? "Indexing" : "Reading"}
    </Badge>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function describe(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}
