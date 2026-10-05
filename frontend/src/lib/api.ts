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
  CopilotResponse,
  CopilotTurn,
  DocumentDetail,
  DocumentListResponse,
  ExtractionResponse,
  HealthResponse,
  KpiResponse,
  LedgerVerification,
  ProgressResponse,
  RuntimeSettings,
  SeedResponse,
  SettingsUpdate,
  SignOffDecision,
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

async function request<T>(path: string, init: RequestInit = {}, base = activeBase): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { cache: "no-store", ...init, headers: headers(init.headers) });
  } catch {
    throw new ApiError(
      `Backend unter ${base} nicht erreichbar.`,
      0,
      "network",
      "Backend starten: uvicorn app.main:app --port 8001",
    );
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

async function requestBlob(path: string): Promise<{ blob: Blob; filename: string | null }> {
  let response: Response;
  try {
    response = await fetch(`${activeBase}${path}`, { cache: "no-store", headers: headers() });
  } catch {
    throw new ApiError(`Backend unter ${activeBase} nicht erreichbar.`, 0, "network");
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
    throw new ApiError(`Backend unter ${activeBase} nicht erreichbar.`, 0, "network");
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
  throw lastError ?? new ApiError("Backend nicht erreichbar.", 0, "network");
}

export const api = {
  documents: (limit = 200) => request<DocumentListResponse>(`/documents?limit=${limit}`),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  extract: (id: string) => request<ExtractionResponse>(`/documents/${id}/extract`, { method: "POST" }),
  progress: (id: string) => request<ProgressResponse>(`/documents/${id}/progress`),
  pin: (id: string, pinned: boolean) => request<DocumentDetail>(`/documents/${id}/pin`, json({ pinned }, "PUT")),
  signOff: (id: string, auditor_name: string, note: string, decision: SignOffDecision) =>
    request<DocumentDetail>(`/documents/${id}/sign-off`, json({ auditor_name, note, decision })),
  reportJson: (id: string) => request<Record<string, unknown>>(`/documents/${id}/report?format=json`),
  reportMarkdown: (id: string) => requestText(`/documents/${id}/report?format=markdown`),
  reportHtml: (id: string) => requestText(`/documents/${id}/report?format=html`),
  copilot: (id: string, question: string, history: CopilotTurn[]) =>
    request<CopilotResponse>(`/documents/${id}/copilot`, json({ question, history })),
  gobdPackage: (id: string) => requestBlob(`/api/documents/${id}/export/gobd`),
  verifyLedger: () => request<LedgerVerification>("/api/audit/verify"),
  kpis: () => request<KpiResponse>("/api/dashboard/kpis"),
  seed: () => request<SeedResponse>("/api/demo/seed", { method: "POST" }),
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
