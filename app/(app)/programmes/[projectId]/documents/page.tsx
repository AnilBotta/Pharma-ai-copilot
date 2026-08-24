"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ExternalLink,
  FileText,
  Plus,
} from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
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
import {
  ApiError,
  pdp,
  type ControlledDocument,
  type DocumentVersionStatus,
} from "@/lib/api";
import { cn, formatRelative } from "@/lib/utils";

const DOCUMENT_TYPES = [
  "protocol", "report", "specification", "method", "sop", "batch_record",
  "risk_assessment", "plan", "summary", "certificate", "drawing", "other",
];

export default function DocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>();

  const [documents, setDocuments] = React.useState<ControlledDocument[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);
  const [versionFor, setVersionFor] = React.useState<ControlledDocument | null>(null);

  const load = React.useCallback(async () => {
    setDocuments(await pdp.listDocuments(projectId));
  }, [projectId]);

  React.useEffect(() => {
    load()
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href={`/programmes/${projectId}`}>
            <ArrowLeft className="size-4" /> Back to programme
          </Link>
        </Button>
        <PageHeader
          title="Document register"
          description="Controlled documents for this programme. Files stay where your organisation already controls them — each version records a link, never a copy."
          icon={FileText}
          actions={
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" /> Register a document
            </Button>
          }
        />
      </div>

      {error && (
        <Card variant="flush" tone="danger">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" />
            <p className="text-sm text-danger">{error}</p>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : documents.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No documents registered"
          description="A gate requirement asking for document evidence can only be satisfied by a version recorded here."
          actionLabel="Register a document"
          onAction={() => setOpen(true)}
        />
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <DocumentRow
              key={doc.id}
              document={doc}
              onAddVersion={() => setVersionFor(doc)}
            />
          ))}
        </div>
      )}

      <RegisterDialog
        open={open}
        onOpenChange={setOpen}
        onCreate={(body) => act(() => pdp.createDocument(projectId, body))}
      />

      <VersionDialog
        document={versionFor}
        onOpenChange={(v) => !v && setVersionFor(null)}
        onAdd={(documentId, body) =>
          act(() => pdp.addDocumentVersion(documentId, body))
        }
      />
    </div>
  );
}

function DocumentRow({
  document: doc,
  onAddVersion,
}: {
  document: ControlledDocument;
  onAddVersion: () => void;
}) {
  const current = doc.current_version;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-xs text-muted-foreground">
              {doc.document_number}
            </code>
            <span className="text-sm font-medium">{doc.title}</span>
            <Badge variant="outline">{doc.document_type.replace(/_/g, " ")}</Badge>
            {doc.project_id === null && (
              <Badge variant="info">Organisation-wide</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {doc.version_count} version{doc.version_count === 1 ? "" : "s"}
            {doc.owner_name && ` · ${doc.owner_name}`}
            {` · registered ${formatRelative(doc.created_at)}`}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {current ? (
            <div className="text-right">
              <div className="flex items-center justify-end gap-2">
                <span className="font-mono text-xs">{current.version_label}</span>
                <VersionStatusBadge
                  status={current.status}
                  usable={current.is_usable}
                />
              </div>
              <a
                href={current.storage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-0.5 inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                Open the file <ExternalLink className="size-3" />
              </a>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">No versions yet</span>
          )}
          <Button size="sm" variant="outline" onClick={onAddVersion}>
            Add version
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// Not exported: an App Router page file may only export `default` and a fixed
// set of route options, and anything else fails the build with a type error
// about OmitWithTag rather than anything mentioning exports.
function VersionStatusBadge({
  status,
  usable,
}: {
  status: DocumentVersionStatus;
  usable?: boolean | null;
}) {
  const variant =
    status === "effective" ? "success"
    : status === "approved" ? "success"
    : status === "superseded" || status === "obsolete" ? "destructive"
    : "muted";

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={variant}>{status.replace(/_/g, " ")}</Badge>
      {/* Approved-but-expired is the case a status label alone would hide. */}
      {usable === false && status !== "superseded" && status !== "obsolete" && (
        <Badge variant="warning">not usable</Badge>
      )}
    </span>
  );
}

function RegisterDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (body: {
    document_number: string;
    title: string;
    document_type: string;
    description?: string;
  }) => void;
}) {
  const [number, setNumber] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [type, setType] = React.useState("report");
  const [description, setDescription] = React.useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register a document</DialogTitle>
          <DialogDescription>
            This records the document&apos;s identity. Versions, links and
            approvals come next.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="doc-number">
              Document number <span className="text-danger">*</span>
            </Label>
            <Input
              id="doc-number"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              placeholder="FD-RPT-0001"
            />
            <p className="text-xs text-muted-foreground">
              Must be unique. Two documents sharing a number is how the wrong
              file gets approved.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="doc-title">
              Title <span className="text-danger">*</span>
            </Label>
            <Input
              id="doc-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Formulation development report"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="doc-type">Type</Label>
            <select
              id="doc-type"
              className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="doc-description">Description</Label>
            <Textarea
              id="doc-description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!number.trim() || !title.trim()}
            onClick={() => {
              onCreate({
                document_number: number.trim(),
                title: title.trim(),
                document_type: type,
                description: description.trim() || undefined,
              });
              onOpenChange(false);
              setNumber("");
              setTitle("");
              setDescription("");
            }}
          >
            Register
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function VersionDialog({
  document: doc,
  onOpenChange,
  onAdd,
}: {
  document: ControlledDocument | null;
  onOpenChange: (open: boolean) => void;
  onAdd: (
    documentId: string,
    body: {
      version_label: string;
      storage_url: string;
      status: DocumentVersionStatus;
      effective_date?: string;
      expiry_date?: string;
      supersedes_version_id?: string;
    }
  ) => void;
}) {
  const [label, setLabel] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [status, setStatus] = React.useState<DocumentVersionStatus>("draft");
  const [effective, setEffective] = React.useState("");
  const [expiry, setExpiry] = React.useState("");
  const [supersede, setSupersede] = React.useState(true);

  const current = doc?.current_version;
  const canSupersede = Boolean(current && current.status === "effective");

  return (
    <Dialog open={Boolean(doc)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Add a version{doc ? ` to ${doc.document_number}` : ""}
          </DialogTitle>
          <DialogDescription>
            Record where the file of record lives. Nothing is uploaded — a
            second authoritative copy is the failure this register exists to
            prevent.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="ver-label">
              Version <span className="text-danger">*</span>
            </Label>
            <Input
              id="ver-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="1.0"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ver-url">
              Link to the file <span className="text-danger">*</span>
            </Label>
            <Input
              id="ver-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://yourcompany.sharepoint.com/..."
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ver-status">Status</Label>
            <select
              id="ver-status"
              className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
              value={status}
              onChange={(e) => setStatus(e.target.value as DocumentVersionStatus)}
            >
              <option value="draft">Draft</option>
              <option value="in_review">In review</option>
              <option value="approved">Approved</option>
              <option value="effective">Effective</option>
            </select>
            <p className="text-xs text-muted-foreground">
              Only <strong>approved</strong> or <strong>effective</strong>{" "}
              versions can satisfy a gate requirement, and marking one so
              requires approval authority.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ver-effective">Effective from</Label>
              <Input
                id="ver-effective"
                type="date"
                value={effective}
                onChange={(e) => setEffective(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ver-expiry">Review by</Label>
              <Input
                id="ver-expiry"
                type="date"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
            </div>
          </div>

          {canSupersede && (
            <label
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm",
                supersede && "border-warning-border bg-warning-surface"
              )}
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={supersede}
                onChange={(e) => setSupersede(e.target.checked)}
              />
              <span>
                Supersede <code className="font-mono">{current?.version_label}</code>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Any requirement citing it stops being satisfied, and the
                  approvals that rested on it are invalidated. That is the
                  point: a gate must not stay green on a document nobody uses
                  any more.
                </span>
              </span>
            </label>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!doc || !label.trim() || !url.trim()}
            onClick={() => {
              if (!doc) return;
              onAdd(doc.id, {
                version_label: label.trim(),
                storage_url: url.trim(),
                status,
                effective_date: effective || undefined,
                expiry_date: expiry || undefined,
                supersedes_version_id:
                  canSupersede && supersede ? current?.id : undefined,
              });
              onOpenChange(false);
              setLabel("");
              setUrl("");
              setStatus("draft");
              setEffective("");
              setExpiry("");
            }}
          >
            Add version
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
