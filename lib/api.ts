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

/**
 * Multipart variant: the SAME base URL and the SAME bearer token, minus the
 * JSON content type.
 *
 * `Content-Type` must be absent for a `FormData` body so the browser can set
 * `multipart/form-data` with its own boundary. Setting it by hand produces a
 * body the server cannot parse, which is why this exists rather than a flag on
 * `authHeaders`.
 */
async function authHeadersForForm(): Promise<Record<string, string>> {
  const headers = await authHeaders();
  delete headers["Content-Type"];
  return headers;
}

/**
 * A multipart POST, through the same base URL, token and error handling.
 *
 * Kept beside `request` rather than folded into it: the only differences are
 * the absent content type and the un-serialised body, and a boolean parameter
 * that changed both would be harder to read than two functions.
 */
async function requestForm<T>(path: string, body: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/api${path}`, {
      method: "POST",
      headers: await authHeadersForForm(),
      body,
    });
  } catch (cause) {
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
      0,
      cause
    );
  }

  const parsed = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      extractDetail(parsed) ?? `Request failed (${response.status}).`,
      response.status,
      parsed
    );
  }
  return parsed as T;
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

/**
 * The Manager Agent's chat, streamed.
 *
 * `EventSource` cannot be used here: it only issues GET requests and has no way
 * to attach an Authorization header, and this turn is a POST carrying the
 * message. So the SSE frames are parsed off a `fetch` body reader instead,
 * which is a few more lines and removes the need for a token in the query
 * string - where it would end up in logs.
 */
export async function* streamManagerTurn(
  conversationId: string,
  content: string,
  signal?: AbortSignal
): AsyncGenerator<ManagerEvent> {
  const response = await fetch(
    `${BASE_URL}/api/manager/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify({ content }),
      signal,
    }
  );

  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      extractDetail(body) ?? `The Manager Agent could not be reached (${response.status}).`,
      response.status,
      body
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line. Anything after the last one is a
    // partial frame and stays in the buffer until the rest arrives.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
        // A line starting with ':' is a keepalive comment; ignore it.
      }
      if (!data) continue;

      try {
        yield { type: event, ...JSON.parse(data) } as ManagerEvent;
      } catch {
        // A malformed frame is not worth killing the turn over; the stream
        // carries many and the next one will very likely parse.
      }
    }
  }
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

/* ---------------------------------------------------- SAS validation types -- */

export interface SasPackageSummary {
  package_id: string;
  case_id: string;
  archive_sha256: string;
  archive_bytes: number;
  be_stats_version: string;
  git_sha: string;
  generated_at: string;
}

export interface SasGeneratedPackage {
  package_id: string;
  case_id: string;
  filename: string;
  archive_sha256: string;
  archive_bytes: number;
  dataset_sha256: string;
  program_sha256: string;
  n_observations: number;
  generated_at: string;
  be_stats_version: string;
  note: string;
}

export interface SasUploadResponse {
  run_id: string;
  status: string;
  detail: string;
  duplicate: boolean;
  comparison: unknown;
  evidence_origin?: string;
  is_regulatory_evidence?: boolean;
  note: string;
}

export type SasOptions = Record<string, unknown>;
export type SasReviewContext = Record<string, unknown>;

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

/**
 * States in which the worker has stopped and will do no more.
 *
 * `awaiting_review` belongs here: the run finished and the report exists, it
 * simply did not pass its own verification and is held rather than presented as
 * complete. It is not "still working", and anything that polls for progress
 * must stop on it.
 */
export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = [
  "completed",
  "awaiting_review",
  "failed",
  "cancelled",
];

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

  /**
   * Days of silence before this gate is reported unattended.
   *
   * `unattended_after_days` is the override and is null when none is set;
   * `unattended_effective_days` is what actually applies. Both are sent so the
   * page can distinguish a chosen value from an inherited one — printing only
   * the effective number would make a system default look like somebody's
   * decision. Present on the gate workspace, absent from programme listings.
   */
  unattended_after_days?: number | null;
  unattended_effective_days?: number;
  unattended_is_inherited?: boolean;
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

/** Somebody the segregation rules would allow to approve a requirement. */
export interface ApproverCandidate {
  user_id: string;
  name: string;
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
  /** Who may approve this now. Empty means nobody can, and the gate is stuck. */
  eligible_approvers: ApproverCandidate[];
  /** Who would still be able to approve if you confirmed the acceptance. */
  approvers_if_i_accept: ApproverCandidate[];
  /** Whether *you* may approve this one — not merely whether you can approve. */
  i_can_approve: boolean;
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

/* -------------------------------------------------------- manager agent --- */

export interface ManagerConversation {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ManagerMessage {
  id: number;
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_name: string | null;
  tool_arguments: Record<string, unknown> | null;
  /** A limit stopped the turn. Stored, so it is still said on a reload. */
  truncated: boolean;
  truncated_reason: string | null;
  created_at: string;
}

export interface ManagerConversationDetail {
  id: string;
  title: string;
  messages: ManagerMessage[];
}

export type ProposalAction =
  | "approve_requirement"
  | "decide_gate"
  | "attach_evidence"
  | "add_document_version"
  | "set_acceptance"
  | "rebaseline";

export interface AgentProposal {
  id: string;
  action_type: ProposalAction;
  params: Record<string, unknown>;
  rationale: string;
  /**
   * The state the agent reasoned from. Used only to say what has MOVED —
   * never to render the current state, which the card fetches itself.
   */
  premise: Record<string, unknown>;
  status: "pending" | "confirmed" | "rejected" | "expired" | "failed";
  project_id: string | null;
  expires_at: string;
  created_at: string;
}

/** One frame of a streamed turn. */
export type ManagerEvent =
  | { type: "token"; text: string }
  | { type: "tool_started"; name: string; arguments: Record<string, unknown> }
  | { type: "tool_finished"; name: string; ok: boolean }
  | { type: "truncated"; reason: string; detail: string }
  | { type: "done"; tokens: number; cost_usd: string }
  | { type: "error"; message: string };

/* --------------------------------------------------------------- agents --- */

export interface BlockerAnalysis {
  ref_code: string;
  /** Eight blockers usually have two causes. This marks the causes. */
  is_root_cause: boolean;
  why_it_is_stuck: string;
  /**
   * True where chasing the obvious person would achieve nothing — an approval
   * outstanding on a requirement whose document has lapsed is not fixed by
   * reminding the approver.
   */
  obvious_action_would_not_help: boolean;
}

export interface RecommendedAction {
  ref_code: string | null;
  action: string;
  who: string;
  urgency: "now" | "this_week" | "when_convenient";
}

export interface GateAssessment {
  session_id: string;
  summary: string;
  blocker_analysis: BlockerAnalysis[];
  recommended_actions: RecommendedAction[];
  /**
   * Scientific judgement is not the operations agent's job. Where the
   * outstanding question is one of evidence adequacy it is handed to the
   * Scientist Agent rather than answered.
   */
  handoff_question: string | null;
}

export interface PortfolioItem {
  programme: string;
  state: string;
  needs_a_decision: boolean;
}

export interface PortfolioSummary {
  session_id: string;
  headline: string;
  items: PortfolioItem[];
}

export type TaskStatus =
  | "not_started"
  | "waiting_on_predecessor"
  | "late_to_start"
  | "in_progress"
  | "overdue"
  | "blocked"
  | "complete"
  | "unknown";

export interface Task {
  id: string;
  project_id: string;
  stage_name: string | null;
  requirement_id: string | null;
  requirement_ref: string | null;
  wbs_code: string | null;
  title: string;
  description: string | null;
  owner_name: string | null;
  /** The commitment. Frozen once a baseline is approved — no endpoint can change it. */
  baseline_start: string | null;
  baseline_end: string | null;
  /** The current plan. Moves freely. */
  forecast_start: string | null;
  forecast_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  /** All derived on read; none stored, so none can be edited. */
  status: TaskStatus;
  variance_days: number | null;
  float_days: number | null;
  is_critical: boolean;
  effort_days: number | null;
  priority: "low" | "medium" | "high" | "critical";
  is_blocked: boolean;
  blocked_reason: string | null;
  depends_on: Array<{
    predecessor_id: string;
    title: string;
    dependency_type: string;
    lag_days: number;
    complete: boolean;
  }>;
  created_at: string;
}

export interface Milestone {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  baseline_date: string | null;
  forecast_date: string | null;
  actual_date: string | null;
  variance_days: number | null;
  is_contractual: boolean;
}

export interface ScheduleBaseline {
  id: string;
  version: number;
  name: string;
  reason: string | null;
  approved_by_name: string | null;
  approved_at: string;
  superseded_at: string | null;
}

export interface Schedule {
  tasks: Task[];
  milestones: Milestone[];
  baselines: ScheduleBaseline[];
  capabilities: PdpCapabilities;
}

export interface Notification {
  id: string;
  rule_key: string;
  rule_name: string;
  project_id: string | null;
  subject_type: string;
  subject_id: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string | null;
  raised_at: string;
  /** Set only when the condition stopped being true — acknowledging does not resolve. */
  resolved_at: string | null;
  resolved_reason: string | null;
  acknowledged_by_name: string | null;
  acknowledged_at: string | null;
  escalation_level: number;
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
 * SAS validation.
 *
 * WHY THIS IS HERE RATHER THAN IN THE COMPONENTS
 *
 * `manual-validation.tsx` (PR #65) and `statistical-review.tsx` (PR #66) each
 * carried a private `call()` helper that did:
 *
 *     fetch(`/api${path}`)
 *
 * A RELATIVE url, so it resolved against the FRONTEND origin rather than
 * `NEXT_PUBLIC_API_BASE_URL`, and with no `Authorization` header. Every SAS
 * request therefore went to the Next.js dev server, which has no `/api` route
 * handler and no rewrite, and came back as a 404 HTML page. Not one of those
 * controls had ever reached the backend.
 *
 * The failure was invisible because it looked like a disabled button: the
 * package listing failed, the component swallowed it, and `Download package`
 * simply stayed grey.
 *
 * Going through `request()` is what fixes it - one place that knows the base
 * URL and the bearer token, and one place to change when either moves.
 */
export const sasValidation = {
  options: () => request<SasOptions>("/sas-validation/options"),

  listPackages: () =>
    request<{ packages: SasPackageSummary[] }>("/sas-validation/packages"),

  generatePackage: (validationCaseId: string) =>
    request<SasGeneratedPackage>("/sas-validation/packages", {
      method: "POST",
      body: JSON.stringify({ validation_case_id: validationCaseId }),
    }),

  downloadUrl: (packageId: string) =>
    request<{
      download_url: string;
      archive_sha256: string;
      archive_bytes: number;
      expires_in_seconds: number;
    }>(`/sas-validation/packages/${packageId}/download`),

  // Generic, defaulting to the shapes above. The review screen and the upload
  // panel each hold a fuller type than this module needs to know about, and
  // duplicating them here would create two definitions to keep in step.
  uploadResult: async <T = SasUploadResponse>(
    packageId: string,
    file: File,
    evidenceOrigin: string,
    runId?: string
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("evidence_origin", evidenceOrigin);
    if (runId) form.append("run_id", runId);
    return requestForm<T>(`/sas-validation/packages/${packageId}/result`, form);
  },

  uploadLog: async <T = SasUploadResponse>(runId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm<T>(`/sas-validation/runs/${runId}/log`, form);
  },

  reviewContext: <T = SasReviewContext>(runId: string) =>
    request<T>(`/sas-validation/runs/${runId}/review`),

  generateAiReview: (runId: string) =>
    request<Record<string, unknown>>(`/sas-validation/runs/${runId}/ai-review`, {
      method: "POST",
    }),

  recordReview: (
    runId: string,
    body: { decision: string; notes: string; acknowledged: boolean }
  ) =>
    request<{ review_id: string; decision: string }>(
      `/sas-validation/runs/${runId}/review`,
      { method: "POST", body: JSON.stringify(body) }
    ),
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

  getRequirement: (requirementId: string) =>
    request<Requirement>(`/pdp/requirements/${requirementId}`),

  /**
   * PDP Operations Agent. Advisory: the readiness engine remains the
   * authority on whether this gate can open, and the database refuses the
   * agent an approval even when it holds a fully authorised session.
   */
  assessGate: (stageId: string) =>
    request<GateAssessment>(`/pdp/stages/${stageId}/assess`, { method: "POST" }),

  /** Manager Agent, scoped to programmes the caller can already see. */
  portfolioSummary: () =>
    request<PortfolioSummary>("/pdp/portfolio/summary", { method: "POST" }),

  // The conversational Manager Agent. The turn itself is not here because it
  // streams - see `streamManagerTurn`.
  listConversations: () =>
    request<ManagerConversation[]>("/manager/conversations"),

  createConversation: (title?: string) =>
    request<ManagerConversation>("/manager/conversations", {
      method: "POST",
      body: JSON.stringify({ title: title ?? null }),
    }),

  getConversation: (id: string) =>
    request<ManagerConversationDetail>(`/manager/conversations/${id}`),

  archiveConversation: (id: string) =>
    request<void>(`/manager/conversations/${id}`, { method: "DELETE" }),

  listProposals: (status = "pending") =>
    request<AgentProposal[]>(`/manager/proposals?status_filter=${status}`),

  confirmProposal: (id: string) =>
    request<{ status: string; proposal_id: string }>(
      `/manager/proposals/${id}/confirm`,
      { method: "POST" }
    ),

  rejectProposal: (id: string, reason?: string) =>
    request<{ status: string; proposal_id: string }>(
      `/manager/proposals/${id}/reject`,
      { method: "POST", body: JSON.stringify({ reason: reason ?? null }) }
    ),

  /** Null clears the override so the gate inherits the system default. */
  setUnattendedThreshold: (
    stageId: string,
    body: { days: number | null; reason?: string }
  ) =>
    request<GateWorkspace>(`/pdp/stages/${stageId}/unattended-threshold`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

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

  listNotifications: (projectId: string, includeResolved = false) =>
    request<Notification[]>(
      `/pdp/projects/${projectId}/notifications?include_resolved=${includeResolved}`
    ),

  /**
   * Take ownership of an alert, stopping it escalating.
   *
   * It does not close the alert. Only the condition ceasing to be true does
   * that — otherwise acknowledging would clear a problem from the list without
   * fixing it.
   */
  acknowledgeNotification: (eventId: string) =>
    request<Notification>(`/pdp/notifications/${eventId}/acknowledge`, {
      method: "POST",
    }),

  getSchedule: (projectId: string) =>
    request<Schedule>(`/pdp/projects/${projectId}/schedule`),

  createTask: (
    projectId: string,
    body: {
      title: string;
      description?: string;
      requirement_id?: string;
      owner_user_id?: string;
      forecast_start?: string;
      forecast_end?: string;
      effort_days?: number;
      priority?: "low" | "medium" | "high" | "critical";
      wbs_code?: string;
    }
  ) =>
    request<Task>(`/pdp/projects/${projectId}/tasks`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Move forecast and actual dates.
   *
   * There is deliberately no baseline field. Baselines are commitments; they
   * change only through `rebaseline`, which needs approval authority and a
   * stated reason.
   */
  updateTask: (
    taskId: string,
    body: {
      forecast_start?: string;
      forecast_end?: string;
      actual_start?: string;
      actual_end?: string;
      owner_user_id?: string;
      priority?: "low" | "medium" | "high" | "critical";
      is_blocked?: boolean;
      blocked_reason?: string;
      reason?: string;
    }
  ) =>
    request<Task>(`/pdp/tasks/${taskId}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  addTaskDependency: (
    taskId: string,
    body: { predecessor_id: string; dependency_type?: string; lag_days?: number }
  ) =>
    request<void>(`/pdp/tasks/${taskId}/dependencies`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  createMilestone: (
    projectId: string,
    body: {
      name: string;
      description?: string;
      forecast_date?: string;
      is_contractual?: boolean;
    }
  ) =>
    request<Milestone>(`/pdp/projects/${projectId}/milestones`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  rebaseline: (projectId: string, body: { name: string; reason: string }) =>
    request<ScheduleBaseline>(`/pdp/projects/${projectId}/baseline`, {
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

      // `awaiting_review` is terminal for the worker: the run is finished and
      // the report is written, it just did not pass verification. Omitting it
      // here would leave the page polling every two seconds forever for work
      // that has already stopped.
      if (TERMINAL_RUN_STATUSES.includes(run.status)) {
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

// --------------------------------------------------------------------------
// Uploaded documents
// --------------------------------------------------------------------------

export interface UploadedDocument {
  id: string;
  project_id: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: "pending" | "extracting" | "embedding" | "ready" | "failed";
  error: string | null;
  page_count: number | null;
  extracted_chars: number | null;
  chunk_count: number;
  pending_chunk_count: number;
  created_at: string;
  updated_at: string;
}

interface UploadTicket {
  document_id: string;
  upload_url: string;
  token: string;
  storage_path: string;
  max_size_bytes: number;
}

export const SUPPORTED_DOCUMENT_TYPES = [
  "application/pdf",
  "text/plain",
  "text/markdown",
] as const;

/**
 * The upload goes to Supabase Storage, not to this API.
 *
 * A serverless function accepts a request body of roughly 4.5 MB, and the
 * documents this feature exists for are routinely larger. So the API only mints
 * a signed URL and the bytes travel directly to storage, which has no such
 * limit. The third call tells the backend the object landed, so a row can never
 * sit claiming a file that was never sent.
 *
 * `onProgress` uses XMLHttpRequest rather than fetch: upload progress events are
 * still the one thing fetch cannot report.
 */
export async function uploadDocument(
  file: File,
  options: { projectId?: string | null; onProgress?: (fraction: number) => void } = {}
): Promise<UploadedDocument> {
  const mimeType = normaliseMimeType(file);

  const ticket = await request<UploadTicket>("/documents/upload-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      mime_type: mimeType,
      size_bytes: file.size,
      project_id: options.projectId ?? null,
    }),
  });

  await putToStorage(ticket.upload_url, file, mimeType, options.onProgress);

  return request<UploadedDocument>(`/documents/${ticket.document_id}/complete`, {
    method: "POST",
  });
}

function putToStorage(
  url: string,
  file: File,
  mimeType: string,
  onProgress?: (fraction: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", mimeType);
    // No Authorization header: the signed URL carries its own token, and
    // attaching the session token would send it to a URL this code did not
    // construct.
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(
            new ApiError(
              `The upload was rejected by storage (${xhr.status}).`,
              xhr.status
            )
          );
    xhr.onerror = () =>
      reject(new ApiError("The upload failed before it finished.", 0));
    xhr.onabort = () => reject(new ApiError("The upload was cancelled.", 0));
    xhr.send(file);
  });
}

/**
 * Browsers disagree about markdown, and some report no type at all for `.md`.
 * The backend accepts exactly three values, so guessing here produces a clear
 * refusal instead of a database constraint violation.
 */
function normaliseMimeType(file: File): string {
  const declared = (file.type || "").split(";")[0].trim().toLowerCase();
  if ((SUPPORTED_DOCUMENT_TYPES as readonly string[]).includes(declared)) {
    return declared;
  }
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "text/markdown";
  if (name.endsWith(".txt")) return "text/plain";
  return declared || "application/octet-stream";
}

// --------------------------------------------------------------------------
// Notification settings
// --------------------------------------------------------------------------

export interface AlertType {
  condition: string;
  name: string;
  description: string | null;
  severity: "info" | "warning" | "critical";
  is_active: boolean;
}

export interface NotificationRecipient {
  id: string;
  email: string;
  name: string | null;
  is_active: boolean;
  /** Empty means every alert type. */
  conditions: string[];
  wants_immediate: boolean;
  wants_digest: boolean;
  /** Evidence the address is really receiving mail, not just configured. */
  sent_count: number;
  last_sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export const notificationSettings = {
  alertTypes: () => request<AlertType[]>("/settings/alert-types"),

  list: () =>
    request<NotificationRecipient[]>("/settings/notification-recipients"),

  add: (body: {
    email: string;
    name?: string | null;
    conditions?: string[];
    wants_immediate?: boolean;
    wants_digest?: boolean;
  }) =>
    request<NotificationRecipient>("/settings/notification-recipients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  update: (
    id: string,
    body: Partial<
      Pick<
        NotificationRecipient,
        "name" | "conditions" | "wants_immediate" | "wants_digest" | "is_active"
      >
    >
  ) =>
    request<NotificationRecipient>(`/settings/notification-recipients/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  remove: (id: string) =>
    request<void>(`/settings/notification-recipients/${id}`, {
      method: "DELETE",
    }),
};

export const documents = {
  list: (projectId?: string) =>
    request<UploadedDocument[]>(
      projectId ? `/documents?project_id=${encodeURIComponent(projectId)}` : "/documents"
    ),

  remove: (documentId: string) =>
    request<void>(`/documents/${documentId}`, { method: "DELETE" }),

  upload: uploadDocument,
};
