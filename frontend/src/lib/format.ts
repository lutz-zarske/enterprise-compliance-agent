import type { AIActRiskLevel, CheckStatus, InferenceMode, Money, ScoreBand, Scorecard } from "../types/api";
import { getActiveLocale, LOCALE_TAG, tr } from "./i18n";

export function toNumber(value: Money | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: Money | undefined, currency: string | null = "EUR"): string {
  const n = toNumber(value);
  if (n === null) return "–";
  try {
    return new Intl.NumberFormat(LOCALE_TAG[getActiveLocale()], { style: "currency", currency: currency || "EUR" }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency ?? ""}`.trim();
  }
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "–";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(
    LOCALE_TAG[getActiveLocale()],
    withTime
      ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
      : { day: "2-digit", month: "2-digit", year: "numeric" },
  );
}

const PAGE_WORD: Record<string, string> = { de: "Seite", en: "Page", es: "Página" };

/** Seitenmarker des Textlayers („--- Seite 1 ---“) in der Sprache der Oberfläche; Offsets bleiben unberührt. */
export function localizePageMarker(text: string): string {
  return text.replace(/^--- Seite (\d+) ---$/, (_match, page: string) => `--- ${PAGE_WORD[getActiveLocale()] ?? "Seite"} ${page} ---`);
}

/** Uhrzeit (HH:MM) in Ortszeit. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "–";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(LOCALE_TAG[getActiveLocale()], { hour: "2-digit", minute: "2-digit" });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Restzeit: "noch 8 s" / "8s left" / "quedan 8 s". */
export function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const loc = getActiveLocale();
  if (s < 60) return loc === "en" ? `${s}s left` : loc === "es" ? `${s} s rest.` : `noch ${s} s`;
  const m = Math.floor(s / 60);
  const remS = String(s % 60).padStart(2, "0");
  if (m < 60) {
    return loc === "en" ? `${m}m ${remS}s left` : loc === "es" ? `${m} min ${remS} s` : `noch ${m} Min. ${remS} s`;
  }
  const h = Math.floor(m / 60);
  const remM = String(m % 60).padStart(2, "0");
  return loc === "en" ? `${h}h ${remM}m left` : loc === "es" ? `${h} h ${remM} min` : `noch ${h} Std. ${remM} Min.`;
}

/** Laufzeit: "12 s", "3 Min. 05 s". */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const remS = String(s % 60).padStart(2, "0");
  return tr(`${m} Min. ${remS} s`, `${m}m ${remS}s`, `${m} min ${remS} s`);
}

/** "qwen2.5:14b-instruct" -> "QWEN 2.5 14B", "claude-sonnet-5" -> "CLAUDE SONNET 5". */
export function formatModel(model: string): string {
  if (model === "en16931-parser") return tr("EN-16931-Parser (ohne KI)", "EN 16931 Parser (no AI)", "Analizador EN 16931 (sin IA)");
  if (model.startsWith("regelwerk-")) return `${tr("Regelwerk", "Rule Engine", "Motor de reglas")} ${model.slice(10)} (${tr("ohne KI", "no AI", "sin IA")})`;
  if (model === "reference-answer") return tr("Musterantwort", "Reference Answer", "Respuesta de referencia");
  if (model === "reference-fixture") return tr("Referenz-Audit (Musterdaten)", "Reference Audit (Sample Data)", "Auditoría de referencia (Muestras)");
  // Produktschreibweise statt Versalien: "Gemini 3.8 Flash", "Claude Sonnet 5", "GPT-4o", "Qwen 2.5 14B".
  if (/^gpt-/i.test(model)) return `GPT-${model.slice(4)}`;
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
      continue;
    } else {
      merged.push(token);
    }
  }
  return merged.map(displayToken).join(" ");
}

function displayToken(token: string): string {
  if (/^\d+(\.\d+)?[bkm]$/i.test(token)) return token.toUpperCase(); // Parametergroesse: 14B
  if (/^[a-z]+$/i.test(token) && token.length <= 3 && token === token.toUpperCase()) return token; // Kuerzel bleiben
  return token.charAt(0).toUpperCase() + token.slice(1);
}

export const PROVIDER_NAMES: Record<InferenceMode, string> = {
  local: "Lokal · Ollama",
  gemini: "Google Gemini",
  anthropic: "Anthropic Claude",
  openai: "OpenAI",
};

export function providerDisplayName(mode: InferenceMode): string {
  if (mode === "local") return tr("Lokal · Ollama", "Local · Ollama", "Local · Ollama");
  return PROVIDER_NAMES[mode];
}

/** Anzeige eines Provider-Werts aus Ledger oder Ergebnis (inkl. Regelwerk und Musterdaten). */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return "–";
  if (provider === "heuristic") return tr("Regelwerk (ohne KI)", "Rule Engine (no AI)", "Motor de reglas (sin IA)");
  if (provider === "structured") return tr("XML-Datensatz (ohne KI)", "XML Dataset (no AI)", "Datos XML (sin IA)");
  if (provider === "reference") return tr("Referenz-Audit (Musterdaten)", "Reference Audit (Sample Data)", "Auditoría de referencia (Muestras)");
  return provider in PROVIDER_NAMES ? providerDisplayName(provider as InferenceMode) : provider;
}

export function riskLabel(level: AIActRiskLevel): string {
  switch (level) {
    case "unacceptable":
      return tr("Verbotene Praktik (Art. 5)", "Prohibited Practice (Art. 5)", "Práctica prohibida (Art. 5)");
    case "high":
      return tr("Hochrisiko (Anhang III)", "High-Risk (Annex III)", "Alto riesgo (Anexo III)");
    case "limited":
      return tr("Begrenztes Risiko (Art. 50)", "Limited Risk (Art. 50)", "Riesgo limitado (Art. 50)");
    case "minimal":
      return tr("Minimales Risiko", "Minimal Risk", "Riesgo mínimo");
    case "not_applicable":
      return tr("Kein KI-System", "No AI System", "Sin sistema de IA");
  }
}

export function docTypeLabel(docType: string | null | undefined): string {
  switch (docType) {
    case "invoice":
      return tr("Rechnung", "Invoice", "Factura");
    case "contract":
      return tr("Vertrag", "Contract", "Contrato");
    case "offer":
      return tr("Angebot", "Quote", "Presupuesto");
    case "reminder":
      return tr("Mahnung", "Payment Reminder", "Reclamación de pago");
    default:
      return tr("Sonstiges", "Other", "Otro");
  }
}

/** Semantische Tonalitaet fuer Chips, Ringe und Kacheln. */
export type Tone = "ok" | "warn" | "bad" | "pii" | "neutral" | "accent";

export function toneForBand(band: ScoreBand | null | undefined): Tone {
  if (band === "green") return "ok";
  if (band === "amber") return "warn";
  if (band === "red") return "bad";
  return "neutral";
}

/**
 * Ampel und Etikett folgen der Freigabeentscheidung, nicht nur dem Score (wie
 * ``presented_band`` in app/scoring.py) – auch bei älteren gespeicherten
 * Ergebnissen, die noch „grün“ neben „Freigabe gesperrt“ trugen.
 */
export function presentedBand(card: Pick<Scorecard, "band" | "band_label" | "release_blocked" | "release_recommendation">): {
  band: ScoreBand;
  label: string;
} {
  if (card.band !== "green") return { band: card.band, label: card.band_label };
  if (card.release_blocked) {
    return { band: "amber", label: card.release_recommendation.includes("Nachforderung") ? "Nachforderung nötig" : "Freigabe gesperrt" };
  }
  if (card.release_recommendation.startsWith("Freigabe unter Vorbehalt")) return { band: "amber", label: "Freigabe unter Vorbehalt" };
  return { band: card.band, label: card.band_label };
}

/** Farbe der Freigabeempfehlung: gesperrt rot, Vorbehalt gelb, frei grün. */
export function verdictTone(card: Pick<Scorecard, "band" | "band_label" | "release_blocked" | "release_recommendation">): Tone {
  if (card.release_blocked) return "bad";
  return presentedBand(card).band === "green" ? "ok" : "warn";
}

/** Band zu einem Score - dieselben Schwellen wie ``band_for`` in app/scoring.py (85 / 60). */
export function toneForScore(score: number | null | undefined): Tone {
  if (score == null) return "neutral";
  return score >= 85 ? "ok" : score >= 60 ? "warn" : "bad";
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

export function checkStatusLabel(status: CheckStatus): string {
  switch (status) {
    case "pass":
      return tr("Erfüllt", "Passed", "Cumple");
    case "warn":
      return tr("Hinweis", "Warning", "Aviso");
    case "fail":
      return tr("Mangel", "Failed", "Defecto");
    case "not_applicable":
      return tr("n. e.", "N/A", "N/A");
  }
}

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
