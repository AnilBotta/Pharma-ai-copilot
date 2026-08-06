"use client";

import { createClient } from "@/lib/supabase/client";

/**
 * Client for the FastAPI backend.
 *
 * Every request carries the Supabase access token. The backend verifies its
 * signature, so the browser cannot assert an identity it does not hold.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
