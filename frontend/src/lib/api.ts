/**
 * HTTP-Client fuer das Compliance-Backend.
 *
 * Grundsatz: Keine Fallback- oder Mock-Daten. Ist das Backend nicht erreichbar,
 * wirft jeder Aufruf einen ApiError mit status 0 - die Oberflaeche zeigt dann
 * einen Offline-Hinweis statt erfundener Pruefergebnisse.
 */
import type {
  BatchUploadResponse,
  ConnectionTestResult,
  CopilotProgress,
  CopilotResponse,
  CopilotTurn,
  DocumentDetail,
  DocumentListResponse,
  HealthResponse,
  JobListResponse,
  JobSnapshot,
  KpiResponse,
  LedgerEntry,
  LedgerVerification,
  LocalAiResult,
  LocalAiStatus,
  ModelCatalog,
  OverrideRequest,
  ProgressResponse,
  RedactResult,
  ReleaseApplyResult,
  ReleaseStatus,
  RuntimeSettings,
  SeedResponse,
  SettingsUpdate,
  SignOffDecision,
  ThinkingLevel,
  VatVerification,
} from "../types/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly hint?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isOffline(): boolean {
    return this.status === 0;
  }
}

const ACCESS_KEY_STORAGE = "eca-access-key";
const BATCH_SIZE = 20;
const BASE_STORAGE = "eca-api-base";

function configuredBase(): string | null {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || null;
}

function candidateBases(): string[] {
  const list: string[] = [];
  const env = configuredBase();
  if (env) list.push(env);
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(BASE_STORAGE);
      if (stored) list.push(stored);
    } catch {
      /* ignorieren */
    }
    list.push(`${window.location.protocol}//${window.location.hostname}:8001`);
  }
  list.push("http://127.0.0.1:8001", "http://localhost:8001");
  return Array.from(new Set(list));
}

let activeBase: string = configuredBase() ?? "http://127.0.0.1:8001";

export function getApiBase(): string {
  return activeBase;
}

export function getAccessKey(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ACCESS_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setAccessKey(value: string): void {
  try {
    if (value) window.localStorage.setItem(ACCESS_KEY_STORAGE, value);
    else window.localStorage.removeItem(ACCESS_KEY_STORAGE);
  } catch {
    /* ignorieren */
  }
}

function headers(extra?: HeadersInit): Headers {
  const result = new Headers(extra);
  result.set("Accept", "application/json");
  const key = getAccessKey();
  if (key) result.set("X-API-Key", key);
  return result;
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const err = body?.error;
    if (err?.message) return new ApiError(err.message, response.status, err.code ?? "http_error", err.hint);
  } catch {
    /* kein JSON */
  }
  return new ApiError(`Anfrage fehlgeschlagen (HTTP ${response.status}).`, response.status, "http_error");
}

function portOf(base: string): string {
  return /:(\d+)(?:\/|$)/.exec(base.replace(/^https?:\/\//, ""))?.[1] ?? "8001";
}

/** Ruhige, konkrete Meldung statt "Failed to fetch". */
function offlineError(base: string): ApiError {
  const port = portOf(base);
  return new ApiError(
    `Backend nicht erreichbar (Port ${port}).`,
    0,
    "network",
    `Start_Compliance_Agent.bat ausführen bzw. „uvicorn app.main:app --port ${port}“ starten – die Verbindung wird automatisch neu geprüft.`,
  );
}

async function request<T>(path: string, init: RequestInit = {}, base = activeBase): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { cache: "no-store", ...init, headers: headers(init.headers) });
  } catch {
    throw offlineError(base);
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

async function requestBlob(path: string): Promise<{ blob: Blob; filename: string | null }> {
  let response: Response;
  try {
    response = await fetch(`${activeBase}${path}`, { cache: "no-store", headers: headers() });
  } catch {
    throw offlineError(activeBase);
  }
  if (!response.ok) throw await toApiError(response);
  return { blob: await response.blob(), filename: filenameFrom(response.headers.get("Content-Disposition")) };
}

/** Dateiname aus Content-Disposition (RFC 5987 bevorzugt, sonst ASCII-Fallback). */
function filenameFrom(header: string | null): string | null {
  if (!header) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      /* Fallback unten */
    }
  }
  return /filename="([^"]+)"/i.exec(header)?.[1] ?? null;
}

async function requestText(path: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${activeBase}${path}`, { cache: "no-store", headers: headers() });
  } catch {
    throw offlineError(activeBase);
  }
  if (!response.ok) throw await toApiError(response);
  return response.text();
}

function json(body: unknown, method = "POST"): RequestInit {
  return { method, body: JSON.stringify(body), headers: { "Content-Type": "application/json" } };
}

/**
 * Ermittelt die erreichbare Backend-Adresse (Env, zuletzt genutzt, gleicher
 * Host, 127.0.0.1, localhost) und merkt sie sich.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  let lastError: ApiError | null = null;
  for (const base of candidateBases()) {
    try {
      const health = await request<HealthResponse>("/health", {}, base);
      activeBase = base;
      try {
        window.localStorage.setItem(BASE_STORAGE, base);
      } catch {
        /* ignorieren */
      }
      return health;
    } catch (err) {
      lastError = err instanceof ApiError ? err : new ApiError(String(err), 0, "network");
      if (!lastError.isOffline) throw lastError;
    }
  }
  throw lastError ?? offlineError(activeBase);
}

export const api = {
  documents: (limit = 200) => request<DocumentListResponse>(`/documents?limit=${limit}`),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  /** Startet die Pruefung als Hintergrund-Job (HTTP 202) - kein Request wartet auf das Modell. */
  extract: (id: string) => request<JobSnapshot>(`/documents/${id}/extract`, { method: "POST" }),
  submitJobs: (documentIds: string[]) =>
    request<{ jobs: JobSnapshot[]; rejected: { document_id: string; code: string; message: string }[] }>(
      "/api/v1/jobs",
      json({ document_ids: documentIds }),
    ),
  jobs: (active = false) => request<JobListResponse>(`/api/v1/jobs?active=${active}`),
  job: (jobId: string) => request<JobSnapshot>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),
  cancelJob: (jobId: string) => request<JobSnapshot>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  progress: (id: string) => request<ProgressResponse>(`/documents/${id}/progress`),
  pin: (id: string, pinned: boolean) => request<DocumentDetail>(`/documents/${id}/pin`, json({ pinned }, "PUT")),
  archive: (id: string, archived: boolean) =>
    request<DocumentDetail>(`/documents/${id}/archive`, json({ archived }, "PUT")),
  signOff: (id: string, auditor_name: string, note: string, decision: SignOffDecision) =>
    request<DocumentDetail>(`/documents/${id}/sign-off`, json({ auditor_name, note, decision })),
  reportJson: (id: string) => request<Record<string, unknown>>(`/documents/${id}/report?format=json`),
  reportMarkdown: (id: string) => requestText(`/documents/${id}/report?format=markdown`),
  reportHtml: (id: string) => requestText(`/documents/${id}/report?format=html`),
  copilot: (id: string, question: string, history: CopilotTurn[], thinking: ThinkingLevel = "medium", progressId?: string) =>
    request<CopilotResponse>(
      `/documents/${id}/copilot`,
      json({ question, history, thinking, ...(progressId ? { progress_id: progressId } : {}) }),
    ),
  copilotProgress: (progressId: string) =>
    request<CopilotProgress>(`/api/v1/copilot/progress/${encodeURIComponent(progressId)}`),
  localAi: () => request<LocalAiStatus>("/api/v1/ai/local"),
  startOllama: () => request<LocalAiResult>("/api/v1/ai/start-ollama", { method: "POST" }),
  stopLocalAi: () => request<LocalAiResult>("/api/v1/ai/stop-local", { method: "POST" }),
  redact: (text: string) => request<RedactResult>("/api/v1/redact", json({ text })),
  gobdPackage: (id: string) => requestBlob(`/api/documents/${id}/export/gobd`),
  proceduralDoc: (id: string) => requestText(`/api/documents/${id}/export/procedural-doc?format=html`),
  override: (id: string, body: OverrideRequest) =>
    request<DocumentDetail>(`/api/documents/${id}/override`, json(body)),
  trail: (id: string) =>
    request<{ items: LedgerEntry[]; count: number }>(`/api/audit/trail?document_id=${encodeURIComponent(id)}&limit=200`),
  /** Gesamte Hash-Kette (neueste zuerst), inklusive Systemereignisse. */
  fullTrail: (limit = 500) => request<{ items: LedgerEntry[]; count: number }>(`/api/audit/trail?limit=${limit}`),
  signingKey: () => request<{ algorithm?: string; fingerprint: string; public_key?: string; [key: string]: unknown }>("/api/audit/signing-key"),
  verifyLedger: () => request<LedgerVerification>("/api/audit/verify"),
  verifyVat: (country_code: string, vat_number: string) =>
    request<VatVerification>("/api/vat/verify", json({ country_code, vat_number })),
  kpis: () => request<KpiResponse>("/api/dashboard/kpis"),
  seed: (only?: string) =>
    request<SeedResponse>(`/api/demo/seed${only ? `?only=${encodeURIComponent(only)}` : ""}`, { method: "POST" }),
  models: (provider: string) => request<ModelCatalog>(`/api/settings/models?provider=${encodeURIComponent(provider)}`),
  release: (fetchRemote = true) => request<ReleaseStatus>(`/api/system/release?fetch=${fetchRemote}`),
  applyRelease: (tag: string, commit: string, admin_name: string) =>
    request<ReleaseApplyResult>("/api/system/release/apply", json({ tag, commit, admin_name })),
  settings: () => request<RuntimeSettings>("/api/settings"),
  updateSettings: (update: SettingsUpdate) => request<RuntimeSettings>("/api/settings", json(update)),
  testConnection: (provider?: string) =>
    request<ConnectionTestResult>("/api/settings/test-connection", json({ provider: provider ?? null })),
  /** Laedt beliebig viele Dateien in Paketen zu je 20 (Backend-Limit MAX_BATCH_FILES). */
  uploadBatch: async (files: File[]): Promise<BatchUploadResponse> => {
    const result: BatchUploadResponse = { items: [], succeeded: 0, failed: 0 };
    for (let start = 0; start < files.length; start += BATCH_SIZE) {
      const form = new FormData();
      files.slice(start, start + BATCH_SIZE).forEach((file) => form.append("files", file));
      const part = await request<BatchUploadResponse>("/documents/upload-batch", { method: "POST", body: form });
      result.items.push(...part.items);
      result.succeeded += part.succeeded;
      result.failed += part.failed;
    }
    return result;
  },
};

export function downloadBlob(content: BlobPart, filename: string, type: string): void {
  const url = URL.createObjectURL(content instanceof Blob ? content : new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
