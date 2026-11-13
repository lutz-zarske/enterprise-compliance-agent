import type { AIActRiskLevel, CheckStatus, InferenceMode, Money, ScoreBand } from "../types/api";

export function toNumber(value: Money | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: Money | undefined, currency: string | null = "EUR"): string {
  const n = toNumber(value);
  if (n === null) return "–";
  try {
    return new Intl.NumberFormat("de-DE", { style: "currency", currency: currency || "EUR" }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency ?? ""}`.trim();
  }
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "–";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("de-DE", withTime
    ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Restzeit: "8 s", "1 Min. 05 s", "1 Std. 02 Min.". */
export function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `noch ${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `noch ${m} Min. ${String(s % 60).padStart(2, "0")} s`;
  return `noch ${Math.floor(m / 60)} Std. ${String(m % 60).padStart(2, "0")} Min.`;
}

/** Laufzeit: "12 s", "3 Min. 05 s". */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} Min. ${String(s % 60).padStart(2, "0")} s`;
}

/** "qwen2.5:14b-instruct" -> "QWEN 2.5 14B", "claude-sonnet-5" -> "CLAUDE SONNET 5". */
export function formatModel(model: string): string {
  if (model === "en16931-parser") return "EN-16931-Parser (ohne KI)";
  if (model.startsWith("regelwerk-")) return `Regelwerk ${model.slice(10)} (ohne KI)`;
  if (model === "reference-answer") return "Musterantwort";
  if (model === "reference-fixture") return "Referenz-Audit (Musterdaten)";
  if (/^gpt-/i.test(model)) return model.toUpperCase();
  const tokens = model
    .split(/[-:_]/)
    .filter((token) => token && !/^(instruct|latest|chat)$/i.test(token))
    .map((token) => token.replace(/^([a-z]+)(\d)/i, "$1 $2"));
  const merged: string[] = [];
  for (const token of tokens) {
    const prev = merged[merged.length - 1];
    if (prev && /^\d+$/.test(token) && /\d$/.test(prev) && !/\d{6,}/.test(token)) {
      merged[merged.length - 1] = `${prev}.${token}`;
    } else if (/^\d{8}$/.test(token)) {
      continue; // Datums-Suffix (z. B. 20251001) weglassen
    } else {
      merged.push(token);
    }
  }
  return merged.join(" ").toUpperCase();
}

export const PROVIDER_SHORT: Record<InferenceMode, string> = {
  local: "LOCAL",
  gemini: "CLOUD",
  anthropic: "CLOUD",
  openai: "CLOUD",
};

export const PROVIDER_NAMES: Record<InferenceMode, string> = {
  local: "Lokal · Ollama",
  gemini: "Google Gemini",
  anthropic: "Anthropic Claude",
  openai: "OpenAI",
};

/** Anzeige eines Provider-Werts aus Ledger oder Ergebnis (inkl. Regelwerk und Musterdaten). */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return "–";
  if (provider === "heuristic") return "Regelwerk (ohne KI)";
  if (provider === "structured") return "XML-Datensatz (ohne KI)";
  if (provider === "reference") return "Referenz-Audit (Musterdaten)";
  return PROVIDER_NAMES[provider as InferenceMode] ?? provider;
}

/** Verstaendliche Meldung zu einem Fehlercode - nie ein Klassenname oder "Failed to fetch". */
export function friendlyError(code: string, message: string, apiBase: string): string {
  if (code === "network") {
    const port = /:(\d+)/.exec(apiBase.replace(/^https?:\/\//, ""))?.[1] ?? "8001";
    return `Backend nicht erreichbar (Port ${port}) – Start_Compliance_Agent.bat ausführen bzw. „uvicorn app.main:app --port ${port}“ starten.`;
  }
  return message;
}

export const RISK_LABELS: Record<AIActRiskLevel, string> = {
  unacceptable: "Verbotene Praktik (Art. 5)",
  high: "Hochrisiko (Anhang III)",
  limited: "Begrenztes Risiko (Art. 50)",
  minimal: "Minimales Risiko",
  not_applicable: "Kein KI-System",
};

export const DOC_TYPE_LABELS: Record<string, string> = {
  invoice: "Rechnung",
  contract: "Vertrag",
  offer: "Angebot",
  reminder: "Mahnung",
  other: "Sonstiges",
};

/** Semantische Tonalitaet fuer Chips, Ringe und Kacheln. */
export type Tone = "ok" | "warn" | "bad" | "pii" | "neutral" | "accent";

export function toneForBand(band: ScoreBand | null | undefined): Tone {
  if (band === "green") return "ok";
  if (band === "amber") return "warn";
  if (band === "red") return "bad";
  return "neutral";
}

export function toneForStatus(status: CheckStatus): Tone {
  return status === "pass" ? "ok" : status === "warn" ? "warn" : status === "fail" ? "bad" : "neutral";
}

export function toneForRisk(level: AIActRiskLevel | null | undefined): Tone {
  if (level === "high" || level === "unacceptable") return "bad";
  if (level === "limited") return "warn";
  if (level === "minimal" || level === "not_applicable") return "ok";
  return "neutral";
}

export const TONE_CLASSES: Record<Tone, string> = {
  ok: "text-ok bg-ok-soft border-ok-line",
  warn: "text-warn bg-warn-soft border-warn-line",
  bad: "text-bad bg-bad-soft border-bad-line",
  pii: "text-pii bg-pii-soft border-pii-line",
  accent: "text-accent bg-accent-soft border-accent-line",
  neutral: "text-subtle bg-surface-2 border-line",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  pii: "text-pii",
  accent: "text-accent",
  neutral: "text-subtle",
};

export const STATUS_LABELS: Record<CheckStatus, string> = {
  pass: "Erfüllt",
  warn: "Hinweis",
  fail: "Mangel",
  not_applicable: "n. e.",
};

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
