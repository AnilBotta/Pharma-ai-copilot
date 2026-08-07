"use client";

import { createClient } from "@/lib/supabase/client";

/**
 * Client for the FastAPI backend.
 *
 * Every request carries the Supabase access token. The backend verifies its
 * signature, so the browser cannot assert an identity it does not hold.
 */

/**
 * Where the API lives.
 *
 * Empty means same-origin, which is how the deployment runs: the Python
 * function serves `/api/*` on this very domain, so requests are relative and
 * there is no CORS at all.
 *
 * The default is deliberately the *deployed* shape rather than the local one.
 * It used to default to `http://localhost:8000`, which meant forgetting the
 * variable in production produced a site that silently asked the visitor's own
 * machine for data. Failing that way is much worse than the reverse: local
 * development sets the value explicitly in `.env.local`, and if you forget it
 * there you get an obvious 404 against the Next.js dev server.
 */
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    throw new ApiError("Not signed in.", 401);
  }
  return {
    Authorization: `Bearer ${session.access_token}`,
    "Content-Type": "application/json",
  };
}

async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/api${path}`, {
      ...init,
      headers: { ...(await authHeaders()), ...(init.headers ?? {}) },
    });
  } catch (cause) {
    // Distinguish "backend is not running" from "backend said no", because
    // the remedies are completely different.
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
      0,
      cause
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      extractDetail(body) ?? `Request failed (${response.status}).`,
      response.status,
      body
    );
  }

  return body as T;
}

function extractDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of per-field objects.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: string };
    const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
    return field ? `${field}: ${first.msg}` : (first.msg ?? null);
  }
  return null;
}

/* ------------------------------------------------------------------ types -- */

export interface Project {
  id: string;
  name: string;
  code: string | null;
  description: string | null;
  molecule: string | null;
  indication: string | null;
  is_seed: boolean;
  run_count: number;
  created_at: string;
  updated_at: string;
}

export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_review"
  | "completed"
  | "failed"
  | "cancelled";

export interface RunSummary {
  id: string;
  project_id: string;
  project_name?: string | null;
  status: RunStatus;
  original_question: string;
  current_node: string | null;
  progress_pct: number;
  evidence_count: number;
  error_message: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  estimated_cost_usd: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface RunDetail extends RunSummary {
  molecule: string | null;
  indication: string | null;
  dosage_form: string | null;
  route_of_administration: string | null;
  delivery_technology: string | null;
  development_stage: string | null;
  jurisdictions: string[];
  date_from: number | null;
  date_to: number | null;
  max_results: number;
  additional_instructions: string | null;
  structured_objective: Record<string, unknown> | null;
  research_plan: Record<string, unknown> | null;
  contradictions: string[];
  evidence_gaps: string[];
  warnings: string[];
  section_confidence: Record<string, string>;
  cancel_requested: boolean;
}

export interface RunEvent {
  id: number;
  run_id: string;
  node: string | null;
  agent_id: string | null;
  event_type: string;
  message: string;
  data: Record<string, unknown> | null;
  created_at: string;
}

export interface Evidence {
  id: string;
  marker: string;
  source_type: "literature" | "patent" | "internal_document";
  provider: string;
  title: string;
  authors: string[];
  identifier_type: string | null;
  identifier: string | null;
  publication_date: string | null;
  url: string | null;
  access_level: "full_text" | "abstract_only" | "metadata_only";
  evidence_category: string | null;
  relevance_score: number | null;
  retrieved_by_agent: string;
  cited_in_sections: string[];
  retrieved_at: string;
}

export interface ReportSection {
  id: string;
  section_key: string;
  position: number;
  title: string;
  body_markdown: string;
  confidence: string | null;
  confidence_rationale: string | null;
}

export interface SearchQuery {
  id: string;
  node: string | null;
  provider: string;
  query_text: string;
  result_count: number | null;
  from_cache: boolean;
  duration_ms: number | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface RunError {
  id: string;
  node: string | null;
  provider: string | null;
  error_type: string;
  message: string;
  is_fatal: boolean;
  created_at: string;
}

export interface Integration {
  name: string;
  state: "configured" | "not_configured" | "keyless";
  required: boolean;
  detail: string;
}

export interface Health {
  status: string;
  database: string;
  integrations: Integration[];
}

export interface Dashboard {
  running: number;
  queued: number;
  completed: number;
  failed: number;
  total_runs: number;
  total_cost: number;
  total_tokens: number;
  source_counts: Record<string, number>;
}

export interface CreateRunPayload {
  project_id: string;
  original_question: string;
  molecule?: string;
  indication?: string;
  dosage_form?: string;
  route_of_administration?: string;
  delivery_technology?: string;
  development_stage?: string;
  jurisdictions?: string[];
  date_from?: number;
  date_to?: number;
  max_results?: number;
  additional_instructions?: string;
}

/* ------------------------------------------------------- PDP stage gates -- */

/**
 * Gate readiness.
 *
 * `readiness_pct` and `is_ready` answer different questions and the second is
 * the dispositive one: 93% with a single unsatisfied mandatory requirement is
 * not ready. `blocker_count` is required rather than optional so that having
 * the percentage always means having the count of reasons it is not 100.
 *
 * Render these through <GateReadiness>, which will not display the number
 * without its blockers.
 */
export interface Readiness {
  readiness_pct: number;
  is_ready: boolean;
  blocker_count: number;
  applicable_count: number;
  satisfied_count: number;
  mandatory_count: number;
  mandatory_satisfied: number;
}

export interface Blocker {
  requirement_id: string;
  ref_code: string;
  title: string;
  status: string;
  reason: string;
  owner_user_id: string | null;
  due_date: string | null;
}

export interface PdpCapabilities {
  can_access: boolean;
  can_approve: boolean;
  can_gate: boolean;
  can_administer: boolean;
  is_portfolio_wide: boolean;
  is_project_owner: boolean;
  role_keys: string[];
}

export type GateStatus =
  | "not_started"
  | "in_progress"
  | "at_risk"
  | "ready_for_human_review"
  | "approved"
  | "conditionally_approved"
  | "rejected"
  | "on_hold";

/** Derived on every read. There is no stored counterpart to any of these. */
export type RequirementStatus =
  | "not_started"
  | "in_progress"
  | "overdue"
  | "awaiting_acceptance"
  | "awaiting_approval"
  | "awaiting_dependency"
  | "changes_requested"
  | "blocked"
  | "wrong_evidence_type"
  | "not_applicable"
  | "approved";

export interface PdpTemplate {
  id: string;
  template_key: string;
  version: number;
  name: string;
  description: string | null;
  product_type: string;
  status: "draft" | "active" | "archived";
  is_default: boolean;
  stage_count: number;
  requirement_count: number;
  approved_at: string | null;
}

export interface ProgrammeSummary {
  id: string;
  name: string;
  code: string | null;
  description: string | null;
  product_type: string | null;
  health: string | null;
  stage_count: number;
  current_stage_pk: string | null;
  current_stage_key: string | null;
  current_stage_name: string | null;
  current_gate_status: GateStatus | null;
  readiness_pct: number | null;
  is_ready: boolean | null;
  blocker_count: number | null;
  planned_start_date: string | null;
  planned_end_date: string | null;
}

export interface StageSummary {
  id: string;
  project_id: string;
  position: number;
  key: string;
  name: string;
  description: string | null;
  gate_question: string | null;
  exit_criteria: string | null;
  gate_status: GateStatus;
  gate_decision_at: string | null;
  gate_decision_note: string | null;
  gate_conditions: string | null;
  readiness_pct: number;
  is_ready: boolean;
  blocker_count: number;
  applicable_count: number;
  satisfied_count: number;
  mandatory_count: number;
  mandatory_satisfied: number;
  requirement_count: number;
  overdue_count: number;
}

export interface ProgrammeDetail {
  project: Record<string, unknown> & { id: string; name: string };
  stages: StageSummary[];
  capabilities: PdpCapabilities;
}

export type DocumentVersionStatus =
  | "draft"
  | "in_review"
  | "approved"
  | "effective"
  | "superseded"
  | "obsolete";

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_label: string;
  status: DocumentVersionStatus;
  storage_url: string;
  checksum: string | null;
  effective_date: string | null;
  expiry_date: string | null;
  /** Computed. Only an approved/effective version that is in date may support a requirement. */
  is_usable: boolean | null;
  approved_by_name: string | null;
  approved_at: string | null;
  superseded_at: string | null;
  cited_by_count: number;
  created_at: string;
}

export interface ControlledDocument {
  id: string;
  project_id: string | null;
  document_number: string;
  title: string;
  document_type: string;
  discipline: string | null;
  description: string | null;
  owner_name: string | null;
  is_controlled: boolean;
  version_count: number;
  current_version: {
    id: string;
    version_label: string;
    status: DocumentVersionStatus;
    storage_url: string;
    effective_date: string | null;
    expiry_date: string | null;
    is_usable: boolean;
  } | null;
  created_at: string;
}

export interface ControlledDocumentDetail extends ControlledDocument {
  versions: DocumentVersion[];
}

export interface EvidenceLink {
  id: string;
  requirement_id: string;
  evidence_type: "document" | "research_run" | "data" | "url" | "note";
  research_run_id: string | null;
  research_run_status: string | null;
  research_run_question: string | null;
  document_version_id: string | null;
  document_number: string | null;
  document_title: string | null;
  document_version_label: string | null;
  document_version_status: DocumentVersionStatus | null;
  document_storage_url: string | null;
  /** False means this link no longer satisfies anything — superseded, obsolete or expired. */
  document_is_usable: boolean | null;
  external_url: string | null;
  note: string | null;
  title: string | null;
  description: string | null;
  added_by_name: string | null;
  created_at: string;
}

export interface RequirementApproval {
  id: string;
  requirement_id: string;
  approver_id: string;
  approver_name: string | null;
  approver_role: string;
  decision: "approved" | "rejected";
  comments: string | null;
  approved_at: string;
  superseded_at: string | null;
  superseded_reason: string | null;
}

export interface Requirement {
  id: string;
  project_stage_id: string;
  position: number;
  ref_code: string;
  title: string;
  description: string | null;
  guidance: string | null;
  discipline: string | null;
  is_mandatory: boolean;
  weight: number;
  required_evidence_type: string;
  acceptance_criteria: string | null;
  status: RequirementStatus;
  is_satisfied: boolean;
  evidence_count: number;
  acceptance_confirmed_by: string | null;
  acceptance_confirmed_by_name: string | null;
  acceptance_confirmed_at: string | null;
  owner_user_id: string | null;
  owner_name: string | null;
  approver_role_key: string | null;
  due_date: string | null;
  priority: "low" | "medium" | "high" | "critical";
  is_blocked: boolean;
  blocked_reason: string | null;
  is_not_applicable: boolean;
  not_applicable_reason: string | null;
  depends_on: Array<{
    id: string;
    ref_code: string;
    title: string;
    is_mandatory: boolean;
    is_satisfied: boolean;
  }> | null;
  evidence: EvidenceLink[];
  approvals: RequirementApproval[];
  current_approval: RequirementApproval | null;
}

export interface GateWorkspace {
  project_id: string;
  stage: StageSummary;
  readiness: Readiness;
  blockers: Blocker[];
  requirements: Requirement[];
  capabilities: PdpCapabilities;
}

export interface AttachableRun {
  id: string;
  original_question: string;
  status: string;
  completed_at: string | null;
  evidence_count: number;
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_role: string | null;
  actor_agent: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  previous_value: unknown;
  new_value: unknown;
  reason: string | null;
  source_channel: string;
}

/* -------------------------------------------------------------- endpoints -- */

export const api = {
  health: () =>
    // Public: usable before sign-in, and when the API is the thing that is broken.
    fetch(`${BASE_URL}/api/health`).then((r) => {
      if (!r.ok) throw new ApiError("Health check failed.", r.status);
      return r.json() as Promise<Health>;
    }),

  dashboard: () => request<Dashboard>("/dashboard"),

  listProjects: () => request<Project[]>("/projects"),

  createProject: (body: { name: string; description?: string; code?: string }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),

  createRun: (body: CreateRunPayload) =>
    request<{ run_id: string; status: string; message: string }>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listRuns: (projectId?: string) =>
    request<RunSummary[]>(
      projectId ? `/runs?project_id=${encodeURIComponent(projectId)}` : "/runs"
    ),

  getRun: (runId: string) => request<RunDetail>(`/runs/${runId}`),

  cancelRun: (runId: string) =>
    request<void>(`/runs/${runId}/cancel`, { method: "POST" }),

  retryRun: (runId: string) =>
    request<{ run_id: string; status: string }>(`/runs/${runId}/retry`, {
      method: "POST",
    }),

  getEvidence: (runId: string) => request<Evidence[]>(`/runs/${runId}/evidence`),
  getReport: (runId: string) => request<ReportSection[]>(`/runs/${runId}/report`),
  getQueries: (runId: string) => request<SearchQuery[]>(`/runs/${runId}/queries`),
  getErrors: (runId: string) => request<RunError[]>(`/runs/${runId}/errors`),
};

/**
 * Stage-gate endpoints.
 *
 * Note what is missing: nothing here marks a requirement complete or writes a
 * readiness figure, because the backend exposes no such route and the database
 * has no such column. Progress is made by attaching evidence, confirming
 * acceptance, and obtaining an approval from somebody else.
 */
export const pdp = {
  listTemplates: () => request<PdpTemplate[]>("/pdp/templates"),

  listProgrammes: () => request<ProgrammeSummary[]>("/pdp/programmes"),

  getProgramme: (projectId: string) =>
    request<ProgrammeDetail>(`/pdp/projects/${projectId}`),

  instantiate: (projectId: string, body: { template_id: string; start_date?: string }) =>
    request<{
      project_id: string;
      template_name: string;
      stages_created: number;
      requirements_created: number;
    }>(`/pdp/projects/${projectId}/instantiate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  attachableRuns: (projectId: string) =>
    request<AttachableRun[]>(`/pdp/projects/${projectId}/attachable-runs`),

  audit: (projectId: string, limit = 100) =>
    request<AuditEntry[]>(`/pdp/projects/${projectId}/audit?limit=${limit}`),

  getGate: (stageId: string) => request<GateWorkspace>(`/pdp/stages/${stageId}`),

  decideGate: (
    stageId: string,
    body: {
      decision: "approved" | "conditionally_approved" | "rejected" | "on_hold";
      note?: string;
      conditions?: string;
    }
  ) =>
    request<StageSummary>(`/pdp/stages/${stageId}/gate-decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listDocuments: (projectId: string) =>
    request<ControlledDocument[]>(`/pdp/projects/${projectId}/documents`),

  getDocument: (documentId: string) =>
    request<ControlledDocumentDetail>(`/pdp/documents/${documentId}`),

  createDocument: (
    projectId: string,
    body: {
      document_number: string;
      title: string;
      document_type: string;
      discipline?: string;
      description?: string;
    }
  ) =>
    request<ControlledDocument>(`/pdp/projects/${projectId}/documents`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  addDocumentVersion: (
    documentId: string,
    body: {
      version_label: string;
      storage_url: string;
      status?: DocumentVersionStatus;
      checksum?: string;
      effective_date?: string;
      expiry_date?: string;
      supersedes_version_id?: string;
    }
  ) =>
    request<DocumentVersion>(`/pdp/documents/${documentId}/versions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setVersionStatus: (
    versionId: string,
    body: { status: DocumentVersionStatus; reason?: string }
  ) =>
    request<DocumentVersion>(`/pdp/document-versions/${versionId}/status`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  attachEvidence: (
    requirementId: string,
    body: {
      evidence_type: "research_run" | "url" | "note" | "data" | "document";
      research_run_id?: string;
      document_version_id?: string;
      external_url?: string;
      note?: string;
      title?: string;
    }
  ) =>
    request<EvidenceLink>(`/pdp/requirements/${requirementId}/evidence`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  detachEvidence: (evidenceId: string) =>
    request<void>(`/pdp/evidence/${evidenceId}`, { method: "DELETE" }),

  setAcceptance: (requirementId: string, confirmed: boolean) =>
    request<Requirement>(`/pdp/requirements/${requirementId}/acceptance`, {
      method: "POST",
      body: JSON.stringify({ confirmed }),
    }),

  decideRequirement: (
    requirementId: string,
    body: { decision: "approved" | "rejected"; comments?: string }
  ) =>
    request<RequirementApproval>(`/pdp/requirements/${requirementId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setAssignment: (
    requirementId: string,
    body: {
      owner_user_id?: string;
      due_date?: string;
      priority?: "low" | "medium" | "high" | "critical";
      clear_owner?: boolean;
      clear_due_date?: boolean;
    }
  ) =>
    request<Requirement>(`/pdp/requirements/${requirementId}/assignment`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  setBlocked: (requirementId: string, blocked: boolean, reason?: string) =>
    request<Requirement>(`/pdp/requirements/${requirementId}/block`, {
      method: "POST",
      body: JSON.stringify({ blocked, reason }),
    }),

  setNotApplicable: (requirementId: string, notApplicable: boolean, reason?: string) =>
    request<Requirement>(`/pdp/requirements/${requirementId}/not-applicable`, {
      method: "POST",
      body: JSON.stringify({ not_applicable: notApplicable, reason }),
    }),
};

/**
 * Subscribe to a run's progress.
 *
 * EventSource cannot send an Authorization header, so this polls the events
 * endpoint instead. The tradeoff is deliberate: polling with a bearer token is
 * simpler and safer than putting an access token in a query string, where it
 * would end up in server logs and browser history.
 */
export function subscribeToRun(
  runId: string,
  handlers: {
    onEvent: (event: RunEvent) => void;
    onStatus?: (status: RunStatus) => void;
    onError?: (error: Error) => void;
  },
  intervalMs = 2000
): () => void {
  let lastId = 0;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const poll = async () => {
    if (stopped) return;
    try {
      const [events, run] = await Promise.all([
        request<RunEvent[]>(`/runs/${runId}/events?after_id=${lastId}`),
        api.getRun(runId),
      ]);

      for (const event of events) {
        lastId = Math.max(lastId, event.id);
        handlers.onEvent(event);
      }
      handlers.onStatus?.(run.status);

      if (["completed", "failed", "cancelled"].includes(run.status)) {
        stopped = true;
        return;
      }
    } catch (error) {
      handlers.onError?.(error as Error);
      // Keep polling: a transient network blip should not permanently detach
      // the UI from a run that is still progressing.
    }
    if (!stopped) timer = setTimeout(poll, intervalMs);
  };

  void poll();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

/**
 * Read-only event fetch, for a run that has already finished.
 */
export function getRunEvents(runId: string) {
  return request<RunEvent[]>(`/runs/${runId}/events?after_id=0`);
}
