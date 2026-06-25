// Typed client for the jobcut FastAPI bridge.
// In dev the API runs on :8000 (CORS allows :3000); `jobcut serve` (§8.7) will
// serve both from the same origin, so the base is overridable via env.

// API base: explicit env override wins; in dev (next dev on :3000) hit the
// separate uvicorn on :8000; when served by `jobcut serve` it's same-origin /api.
export function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window !== "undefined" && window.location.port === "3000") {
    return "http://localhost:8000/api";
  }
  return "/api";
}

export type ShortlistItem = {
  job_id: string;
  title: string | null;
  company_name: string | null;
  location: string | null;
  score: number | null;
  match_reasons: string | null;
  linkedin_url: string | null;
  apply_url: string | null;
  easy_apply_url: string | null;
  scored_date: string | null;
  workplace_type: string | null;
  status: string | null;
  backend: string | null;
};

export type Shortlist = {
  today: ShortlistItem[];
  backlog: ShortlistItem[];
  meta: { db_count: number; funnel_count: number; excluded: number };
};

export type Application = {
  job_id: string;
  status: string;
  status_category: string;
  applied_at: string | null;
  updated_at: string | null;
  notes: string;
  source: string;
  // structured tracking fields (v5; nullable)
  priority?: string | null;
  next_action?: string | null;
  next_action_date?: string | null;
  contact?: string | null;
  cv_version?: string | null;
  // present on the list endpoint (server-side join to jobs); absent on detail/PUT
  title?: string | null;
  company_name?: string | null;
  // Phase 3 enrichment (list endpoint only): time-in-stage + activity state
  days_in_stage?: number | null;
  stalled?: boolean; // open & idle 14..90d (needs a nudge)
  dormant?: boolean; // open & idle >= 90d (probably dead)
};

export type ApplicationFields = Partial<
  Pick<Application, "priority" | "next_action" | "next_action_date" | "contact" | "cv_version">
>;

export type JobDetail = {
  job: Record<string, string | null> | null; // null for application-only rows (no jobs row)
  score: {
    match_score: number | null;
    match_reasons: string | null;
    status: string | null;
    scored_date: string | null;
    backend: string | null;
  } | null;
  application: Application | null;
};

export type Funnel = {
  total: number;
  live: number;
  interview: number;
  offers: number;
  rejected: number;
  no_response: number;
  counts: Record<string, number>;
  funnel: [string, number, string][];
  by_week: Record<string, number>;
  // Phase 3 (additive): stalled = idle 14..90d, dormant = idle >= 90d, + mean days-in-stage
  stalled_count?: number;
  dormant_count?: number;
  by_stage_time?: Record<string, number>;
};

export type Health = {
  data_dir: string;
  schema_version: number | null;
  jobs: number;
  applications: number;
  apify_token_set: boolean;
  llm_key_set: boolean;
};

// Tiny in-memory GET cache so re-navigating between screens is instant. Any write
// (non-GET request) clears it, and entries expire quickly, so reads stay fresh after
// a change. Local single-user app, so a short TTL + write-invalidation is plenty.
const _cache = new Map<string, { t: number; data: unknown }>();
const CACHE_TTL_MS = 10_000;
export function clearApiCache(): void {
  _cache.clear();
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method === "GET") {
    const hit = _cache.get(path);
    if (hit && Date.now() - hit.t < CACHE_TTL_MS) return hit.data as T;
  } else {
    _cache.clear(); // a write may affect any cached read — invalidate everything
  }
  const res = await fetch(`${apiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, String(detail));
  }
  const data = res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  if (method === "GET") _cache.set(path, { t: Date.now(), data });
  return data as T;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const getHealth = () => api<Health>("/status");

export const getShortlist = (params: Record<string, string | number | boolean> = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).map(([k, v]) => [k, String(v)])
  ).toString();
  return api<Shortlist>(`/shortlist${qs ? `?${qs}` : ""}`);
};

export const getJob = (id: string) => api<JobDetail>(`/jobs/${id}`);

export const getApplications = () => api<Application[]>("/applications");
export const getFunnel = () => api<Funnel>("/applications/funnel");
export const getStatuses = () =>
  api<{ statuses: string[]; categories: string[] }>("/applications/statuses");

export const setStatus = (jobId: string, status: string, notes?: string) =>
  api<Application>(`/applications/${jobId}`, {
    method: "PUT",
    body: JSON.stringify({ status, notes }),
  });

// Append-only timeline (v5): status history + notes + interview rounds.
export type AppEvent = {
  event_id: number;
  job_id: string;
  ts: string;
  kind: string; // 'status_change' | 'note' | 'interview' | 'next_action'
  from_status: string | null;
  to_status: string | null;
  body: string;
  meta: string;
};
export const patchApplication = (jobId: string, fields: ApplicationFields) =>
  api<Application>(`/applications/${jobId}`, { method: "PATCH", body: JSON.stringify(fields) });

export const getEvents = (jobId: string) => api<AppEvent[]>(`/applications/${jobId}/events`);
export const addEvent = (jobId: string, body: { kind?: string; body?: string; meta?: string }) =>
  api<AppEvent>(`/applications/${jobId}/events`, { method: "POST", body: JSON.stringify(body) });

export const deleteApplication = (jobId: string) =>
  api<{ deleted: string }>(`/applications/${jobId}`, { method: "DELETE" });

// --- onboarding: credentials, profile, config, CV ---------------------------

export type Credentials = { apify_token_set: boolean; llm_key_set: boolean };
export type Validation = {
  apify: { valid: boolean; username?: string; error?: string };
  llm: { valid: boolean };
};
export type Derived = {
  searches: Record<string, { jobTitles?: string[]; workplaceType?: string[] }>;
  config: Record<string, unknown>;
  taxonomy: { skills?: Record<string, unknown>; role_segments?: Record<string, unknown> };
};

export const getCredentials = () => api<Credentials>("/credentials");
export const putCredentials = (body: { apify_token?: string; llm_key?: string }) =>
  api<Credentials>("/credentials", { method: "PUT", body: JSON.stringify(body) });
export const validateCredentials = (body: { apify_token?: string; llm_key?: string }) =>
  api<Validation>("/validate-credentials", { method: "POST", body: JSON.stringify(body) });

export const getProfile = () => api<{ content: string }>("/profile");
export const putProfile = (content: string) =>
  api<{ content: string }>("/profile", { method: "PUT", body: JSON.stringify({ content }) });

// Structured profile (B1) — form-friendly view that round-trips with profile.md.
export type ProfileFields = {
  target_roles: string[];
  locations: string[];
  work_types: string[];
  seniority: string | null;
  must_haves: string[];
  dealbreakers: string[];
  skills: string[];
};
export const getProfileStructured = () => api<ProfileFields>("/profile/structured");
export const putProfileStructured = (fields: ProfileFields) =>
  api<ProfileFields>("/profile/structured", { method: "PUT", body: JSON.stringify(fields) });

export const getDerived = () => api<Derived>("/profile/derived");
export const deriveProfile = (force = false) =>
  api<{ written: string[]; skipped: string[] }>("/profile/derive", {
    method: "POST",
    body: JSON.stringify({ force }),
  });

export const getConfig = () => api<Record<string, unknown>>("/config");
export const putConfig = (config: Record<string, unknown>) =>
  api<Record<string, unknown>>("/config", { method: "PUT", body: JSON.stringify({ config }) });

// --- schedule (automation) --------------------------------------------------
export type Schedule = {
  enabled: boolean;
  frequency: "daily" | "weekdays" | "every_n";
  interval_days: number;
  hour: number;
  minute: number;
  platform: string;
  supported: boolean;
  installed: boolean;
  command: string;
};
export const getSchedule = () => api<Schedule>("/schedule");
export const putSchedule = (body: {
  enabled: boolean;
  frequency: string;
  interval_days: number;
  hour: number;
  minute: number;
}) => api<Schedule>("/schedule", { method: "PUT", body: JSON.stringify(body) });

export const draftProfile = (text: string) =>
  api<{ profile_md: string; source: string }>("/profile/from-cv", {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export async function extractCv(file: File): Promise<{ filename: string; text: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBase()}/cv/extract`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.json();
}

// --- searches, market, export ----------------------------------------------

export type SearchEntry = { name: string; input: Record<string, unknown> | null };

export const listSearches = () => api<SearchEntry[]>("/searches");
export const createSearch = (name: string, input: Record<string, unknown>) =>
  api<SearchEntry>("/searches", { method: "POST", body: JSON.stringify({ name, input }) });
export const updateSearch = (name: string, input: Record<string, unknown>) =>
  api<SearchEntry>(`/searches/${name}`, { method: "PUT", body: JSON.stringify({ input }) });
export const deleteSearch = (name: string) =>
  api<{ deleted: string }>(`/searches/${name}`, { method: "DELETE" });

// Structured searches (B2) — human inputs; geoIds resolved/hidden server-side.
export type StructuredSearch = {
  name: string | null;
  titles: string[];
  locations: string[];
  work_types: string[];
  employment_types: string[];
  max_items: number | null;
  posted_within: string | null;
  geo_ids: string[];
  needs_geoid: boolean;
};
export const listStructuredSearches = () => api<StructuredSearch[]>("/searches/structured");
export const createStructuredSearch = (s: Partial<StructuredSearch>) =>
  api<StructuredSearch>("/searches/structured", { method: "POST", body: JSON.stringify(s) });
export const updateStructuredSearch = (name: string, s: Partial<StructuredSearch>) =>
  api<StructuredSearch>(`/searches/structured/${name}`, { method: "PUT", body: JSON.stringify(s) });

// Scoring backends (B3) — choice-card data (recommended/order/usable/reason).
export type ScoringBackend = {
  id: string;
  label: string;
  description: string;
  available: boolean;
  usable: boolean;
  reason: string;
  order: number;
  recommended: boolean;
};
export const getScoringBackends = () => api<ScoringBackend[]>("/scoring/backends");

export type Market = {
  total: number;
  relevant: number;
  segments: Record<string, number>;
  top_demand: { skill: string; pct: number; status: string }[];
  gaps: string[];
  salary_pct: number;
  empty?: boolean;
};
export const getMarket = () => api<Market>("/market");
export const regenerateMarket = () => api<Market>("/market", { method: "POST" });

export const exportData = () =>
  api<{ out_dir: string; summary: Record<string, unknown> }>("/export", { method: "POST" });

export type RunKind = "pull" | "score";

export const startRun = (kind: RunKind, mode = "read", confirm = false) =>
  api<{ run_id: string; kind: string; status: string }>("/runs", {
    method: "POST",
    body: JSON.stringify({ kind, mode, confirm }),
  });

export const runEventsUrl = (runId: string) => `${apiBase()}/runs/${runId}/events`;
