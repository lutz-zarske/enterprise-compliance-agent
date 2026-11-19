"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { buildCorrectionRequest, correctionDefects } from "../lib/correction";
import { cx, formatElapsed, formatModel, localizePageMarker } from "../lib/format";
import { type Locale, useI18n } from "../lib/i18n";
import { Markdown } from "../lib/markdown";
import type { CopilotTurn, DocumentDetail, DocumentSummary, ThinkingLevel } from "../types/api";
import { AlertTriangle, ArrowUp, Download, FileText, Mail, MessageSquare, Square } from "./icons";
import { Select } from "./Select";
import { AutoTextarea, CopyButton, EmptyState, Kbd, Segmented, Spinner } from "./ui";

const QUESTIONS: Record<Locale, {
  fields: string;
  fieldsComplete: string;
  aiActRef: string;
  aiActGeneral: string;
  correction: string;
  gdprGeneral: string;
  summaryGeneral: string;
}> = {
  de: {
    fields: "Welche Pflichtangaben fehlen in dieser Rechnung?",
    fieldsComplete: "Sind alle Pflichtangaben nach § 14 UStG vorhanden?",
    aiActRef: "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?",
    aiActGeneral: "Welche Pflichten ergeben sich aus der EU-AI-Act-Einstufung dieses Dokuments?",
    correction: "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?",
    gdprGeneral: "Welche Datenschutz- und DSGVO-Pflichten betreffen dieses Dokument?",
    summaryGeneral: "Welche wesentlichen Compliance-Befunde und Fundstellen liegen vor?",
  },
  en: {
    fields: "Which mandatory fields are missing from this invoice?",
    fieldsComplete: "Are all mandatory fields under Sec. 14 UStG present?",
    aiActRef: "Why does the system classify this PDF as Annex III No. 4?",
    aiActGeneral: "What obligations result from the EU AI Act classification of this document?",
    correction: "How must the invoice be corrected to qualify for input VAT deduction?",
    gdprGeneral: "Which data privacy and GDPR obligations apply to this document?",
    summaryGeneral: "What are the key compliance findings and line references?",
  },
  es: {
    fields: "¿Qué datos obligatorios faltan en esta factura?",
    fieldsComplete: "¿Están presentes todos los datos obligatorios del § 14 UStG?",
    aiActRef: "¿Por qué clasifica el sistema este PDF como Anexo III n.º 4?",
    aiActGeneral: "¿Qué obligaciones derivan de la clasificación del Reglamento de IA para este documento?",
    correction: "¿Cómo debe corregirse la factura para poder deducir el IVA soportado?",
    gdprGeneral: "¿Qué obligaciones de protección de datos y RGPD afectan a este documento?",
    summaryGeneral: "¿Cuáles son los principales hallazgos de cumplimiento y sus líneas?",
  },
};

interface Suggestion {
  label: string;
  prompt: string;
}

/** Nur Fragen, die zum geprüften Beleg passen; ungeprüfte Dokumente zeigen keine irreführenden Vorschlagschips. */
function suggestionsFor(document: DocumentDetail | null, locale: Locale): Suggestion[] {
  if (!document || document.status !== "extracted") return [];
  const invoice = document.extraction?.doc_type === "invoice";
  const ai = Boolean(document.compliance?.ai_act.describes_ai_system || document.compliance?.ai_act.is_high_risk);
  const q = QUESTIONS[locale];
  // Nur passende Fragen: Bei vollständigen Rechnungen nicht nach „fehlenden“ Angaben fragen,
  // eine Korrekturanforderung nur bei echten Mängeln vorschlagen.
  const formalDefects = (document.scorecard?.tiles.find((tile) => tile.key === "formal")?.checks ?? []).some((check) => check.status === "fail");
  const defects = correctionDefects(document).length > 0;
  const fields = formalDefects ? q.fields : q.fieldsComplete;
  const list: Suggestion[] = [
    ...(invoice ? [{ label: fields, prompt: fields }] : []),
    ...(ai
      ? [
          document.provider === "reference"
            ? { label: q.aiActRef, prompt: q.aiActRef }
            : { label: q.aiActGeneral, prompt: q.aiActGeneral },
        ]
      : []),
    ...(invoice && defects ? [{ label: q.correction, prompt: q.correction }] : []),
  ];
  return list.length
    ? list
    : [
        { label: q.gdprGeneral, prompt: q.gdprGeneral },
        { label: q.summaryGeneral, prompt: q.summaryGeneral },
      ];
}

interface Message extends CopilotTurn {
  meta?: string;
  tone?: "error" | "notice" | "heuristic";
  aborted?: boolean;
}

/** Beide Spalten füllen ab xl das Fenster exakt (Kopfzeile 57 px + Innenabstand 2 x 16 px); gestapelt mobil frei scrollbar. */
const VIEW_HEIGHT = "xl:h-[max(560px,calc(100vh-89px))] 2xl:h-[max(560px,calc(100vh-97px))]";

/** Antwort zum Einfügen in E-Mail oder Ticket: Markdown-Hervorhebungen entfernt, Zeilenverweise bleiben. */
function plainAnswer(markdown: string): string {
  return markdown
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .trim();
}

function newProgressId(): string {
  return `cp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Belegtext mit Zeilennummern; ein Zeilenverweis aus der Antwort springt hierher. */
function SourceText({ document, cited }: { document: DocumentDetail; cited: number | null }) {
  const { tr } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => (document.text_view?.text ?? document.text_preview ?? "").split("\n"), [document]);
  useEffect(() => {
    if (cited == null) return;
    const target = containerRef.current?.querySelector<HTMLElement>(`[data-line="${cited}"]`);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [cited]);
  if (!lines.join("").trim()) {
    return <EmptyState icon={<FileText size={18} aria-hidden="true" />} title={tr("Kein Belegtext vorhanden", "No document text available", "No hay texto del documento")} />;
  }
  return (
    <div ref={containerRef} className="scroll-area min-h-0 flex-1 rounded-lg border border-line bg-surface-2 py-3 pl-2 pr-3">
      <ol className="font-mono text-[13px] leading-[1.75] text-muted">
        {lines.map((line, index) => (
          <li key={index} data-line={index + 1} className="grid grid-cols-[2.75rem_minmax(0,1fr)]">
            <span className="select-none pr-3 text-right tabular-nums text-subtle">{index + 1}</span>
            <span className="doc-line whitespace-pre-wrap break-words" data-cited={cited === index + 1 ? "true" : undefined}>
              {localizePageMarker(line) || " "}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Compliance Copilot als ruhiger Arbeitsbereich: links das Gespräch mit Live-Arbeitsschritten,
 * rechts der Beleg (Zeilenverweise springen hinein) oder der Entwurf der Korrekturanforderung.
 */
export function CopilotView({ document, documents, onSelect, modelLabel, modelReady, active, onBusyChange }: {
  document: DocumentDetail | null;
  documents: DocumentSummary[];
  onSelect: (id: string) => void;
  modelLabel: string;
  /** null = noch unbekannt (Kaltstart). */
  modelReady: boolean | null;
  active: boolean;
  onBusyChange: (busy: boolean) => void;
}) {
  const { locale, tr, td } = useI18n();
  const [threads, setThreads] = useState<Record<string, Message[]>>({});
  const [input, setInput] = useState("");
  const [busyDocId, setBusyDocId] = useState<string | null>(null);
  const busy = busyDocId !== null;
  const busyHere = Boolean(document && busyDocId === document.id);
  const [thinking, setThinking] = useState<ThinkingLevel>("medium");
  const [step, setStep] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [cited, setCited] = useState<number | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [bannerReady, setBannerReady] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<{ controller: AbortController; progressId: string } | null>(null);

  const thinkingOptions: { value: ThinkingLevel; label: string }[] = [
    { value: "low", label: tr("Knapp", "Concise", "Breve") },
    { value: "medium", label: tr("Standard", "Standard", "Estándar") },
    { value: "high", label: tr("Gründlich", "Thorough", "Detallado") },
  ];

  const messages = document ? threads[document.id] ?? [] : [];
  const defects = correctionDefects(document);
  // Einheitlich mit der Prüfkarte zählen: fehlende Pflichtangaben (§ 14 UStG) und Rechenfehler getrennt.
  const failedIn = (key: string) =>
    (document?.scorecard?.tiles.find((tile) => tile.key === key)?.checks ?? []).filter((check) => check.status === "fail").length;
  const missingFields = failedIn("formal");
  const mathErrors = failedIn("math");
  const defectParts = [
    missingFields > 0
      ? missingFields === 1
        ? tr("1 fehlende Pflichtangabe nach § 14 UStG", "1 missing mandatory field under Sec. 14 UStG", "1 dato obligatorio ausente según § 14 UStG")
        : tr(`${missingFields} fehlende Pflichtangaben nach § 14 UStG`, `${missingFields} missing mandatory fields under Sec. 14 UStG`, `${missingFields} datos obligatorios ausentes según § 14 UStG`)
      : null,
    mathErrors > 0
      ? mathErrors === 1
        ? tr("1 Rechenfehler", "1 arithmetic error", "1 error de cálculo")
        : tr(`${mathErrors} Rechenfehler`, `${mathErrors} arithmetic errors`, `${mathErrors} errores de cálculo`)
      : null,
  ].filter((part): part is string => Boolean(part));
  const isReference = document?.provider === "reference";
  const suggestions = suggestionsFor(document, locale);

  // Modell-Banner erst nach kurzer Verzögerung - kein Aufblitzen während des Kaltstarts.
  useEffect(() => {
    const timer = window.setTimeout(() => setBannerReady(true), 900);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, busy, step]);

  useEffect(() => {
    setDraft(null);
    setCited(null);
  }, [document?.id]);

  useEffect(() => {
    if (active && !busy) inputRef.current?.focus({ preventScroll: true });
  }, [active, busy, document?.id]);

  useEffect(() => onBusyChange(busy), [busy, onBusyChange]);

  // Laufzeit sekündlich weiterzählen, solange gearbeitet wird.
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const stop = useCallback(() => {
    const current = abortRef.current;
    if (!current) return;
    abortRef.current = null;
    current.controller.abort();
    void api.copilotCancel(current.progressId).catch(() => undefined);
  }, []);

  useEffect(() => () => {
    abortRef.current?.controller.abort();
  }, []);

  useEffect(() => {
    if (!active || !busyHere) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && draft === null && !window.document.querySelector('[role="dialog"]')) {
        event.preventDefault();
        stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, busyHere, draft, stop]);

  const ask = useCallback(async (question: string) => {
    const trimmed = question.trim();
    if (!document || trimmed.length < 2 || busy) return;
    const id = document.id;
    const history: CopilotTurn[] = (threads[id] ?? [])
      .filter((message) => !message.aborted && message.tone !== "error" && message.tone !== "notice")
      .map(({ role, content }) => ({ role, content }));
    setThreads((all) => {
      const current = all[id] ?? [];
      const prevLast = current[current.length - 1];
      const base =
        prevLast?.role === "user" && prevLast.aborted && prevLast.content === trimmed
          ? current.slice(0, -1)
          : current;
      return { ...all, [id]: [...base, { role: "user", content: trimmed }] };
    });
    setInput("");
    setBusyDocId(id);
    setStep(tr("Belegstellen und Prüfergebnis aufbereiten", "Preparing citations and audit result", "Preparando citas y resultado de auditoría"));
    setStartedAt(Date.now());
    setNow(Date.now());
    const progressId = newProgressId();
    const controller = new AbortController();
    abortRef.current = { controller, progressId };
    const poll = window.setInterval(() => {
      if (controller.signal.aborted) return;
      api.copilotProgress(progressId).then((progress) => {
        if (!controller.signal.aborted && progress.current) setStep(progress.current);
      }).catch(() => undefined);
    }, 700);
    try {
      const response = await api.copilot(id, trimmed, history, thinking, progressId, controller.signal);
      const sec = (response.duration_ms / 1000).toFixed(1);
      const secStr = locale === "en" ? `${sec} s` : `${sec.replace(".", ",")} s`;
      const meta = response.reference
        ? tr("Musterantwort · ohne KI-Modell", "Reference answer · offline", "Respuesta de referencia · sin IA")
        : response.heuristic
          ? tr("Regelwerk · KI nicht verfügbar", "Ruleset · AI unavailable", "Reglamento · IA no disponible")
          : `${formatModel(response.model)} · ${secStr}${response.failover?.length ? tr(" · Ausweichmodell", " · Fallback model", " · Modelo alternativo") : ""}`;
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), { role: "assistant", content: response.answer, meta, tone: response.heuristic ? "heuristic" : undefined }],
      }));
    } catch (err) {
      const error = err instanceof ApiError ? err : null;
      if (controller.signal.aborted || error?.code === "aborted") {
        setThreads((all) => {
          const current = all[id] ?? [];
          return {
            ...all,
            [id]: current.map((msg, idx) =>
              idx === current.length - 1 && msg.role === "user" ? { ...msg, aborted: true } : msg,
            ),
          };
        });
        return;
      }
      const content = error
        ? `${td(error.message)}${error.hint ? ` – ${td(error.hint)}` : ""}`
        : tr(
            "Die Frage konnte nicht beantwortet werden. Bitte erneut senden.",
            "The question could not be answered. Please send again.",
            "No se pudo responder a la pregunta. Vuelve a enviarla.",
          );
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), { role: "assistant", content, tone: error?.code === "network" ? "notice" : "error" }],
      }));
    } finally {
      if (abortRef.current?.controller === controller) abortRef.current = null;
      window.clearInterval(poll);
      setBusyDocId(null);
      setStep(null);
      setStartedAt(null);
    }
  }, [document, busy, threads, thinking, locale, tr, td]);

  const analyzed = documents.filter((doc) => doc.status === "extracted" && !doc.archived);
  const choices: { id: string; filename: string }[] =
    document && !analyzed.some((doc) => doc.id === document.id) ? [document, ...analyzed] : analyzed;
  const options = choices.map((doc) => ({ value: doc.id, label: doc.filename }));

  if (!document) {
    return (
      <div className={cx("card flex items-center justify-center", VIEW_HEIGHT)}>
        <EmptyState icon={<MessageSquare size={20} aria-hidden="true" />} title={tr("Noch kein Beleg ausgewählt", "No document selected yet", "Ningún documento seleccionado")}>
          <p>
            {tr(
              "Unter „Prüfung“ einen Beleg auswählen oder Musterdaten laden – der Copilot beantwortet dann Fragen mit Zeilen- und Normverweisen.",
              "Select a document under “Audit” or load Sample Cases – Copilot answers questions with line and statutory references.",
              "Selecciona un documento en «Auditoría» o carga casos de ejemplo; el Copilot responde con referencias de línea y normativa.",
            )}
          </p>
        </EmptyState>
      </div>
    );
  }

  return (
    <div className={cx("grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] 2xl:gap-5", VIEW_HEIGHT)}>
      <section className="card flex min-h-[460px] flex-col xl:min-h-0" aria-label="Compliance Copilot">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="rounded-lg border border-line bg-surface-2 p-1.5 text-accent"><MessageSquare size={15} aria-hidden="true" /></span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-fg">Compliance Copilot</h2>
              <p className="truncate text-xs text-subtle">{td(modelLabel)}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {options.length > 1 && (
              <Select value={document.id} onChange={onSelect} options={options} ariaLabel={tr("Beleg für den Copilot", "Document for Copilot", "Documento para el Copilot")} width={300} className="h-8 max-w-[280px] justify-between" />
            )}
            <Segmented<ThinkingLevel> size="sm" ariaLabel={tr("Denkstufe", "Thinking depth", "Nivel de análisis")} value={thinking} onChange={setThinking} options={thinkingOptions} />
          </div>
        </header>

        {bannerReady && modelReady === false && (
          <div className="anim-fade flex items-start gap-2 border-b border-line bg-warn-soft px-4 py-2 text-xs text-fg" role="status">
            <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            <span>
              {tr(
                "Kein Sprachmodell erreichbar. Freie Fragen beantwortet das Regelwerk aus dem Prüfergebnis (gekennzeichnet)",
                "No language model reachable. Free questions are answered by the rule engine from audit findings (badged)",
                "Ningún modelo de IA disponible. El motor de reglas responde desde los resultados (etiquetado)",
              )}
              {isReference
                ? tr(
                    "; die Standardfragen der Musterdaten beantwortet der Copilot auch ohne Modell.",
                    "; standard sample questions also work offline without a model.",
                    "; las preguntas estándar de ejemplo funcionan sin modelo.",
                  )
                : "."}
            </span>
          </div>
        )}

        {defects.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <p className="text-xs text-muted">
              <span className="font-semibold tabular-nums text-warn">{defects.length}</span>{" "}
              {defects.length === 1 ? tr("Mangel", "defect", "defecto") : tr("Mängel", "defects", "defectos")}
              {defectParts.length > 0 && <>: {defectParts.join(", ")}</>}
              {" – "}
              {tr("Lieferanten um eine berichtigte Rechnung bitten.", "request a corrected invoice from the supplier.", "solicitar una factura rectificada.")}
            </p>
            <button className="btn btn-sm" onClick={() => setDraft(buildCorrectionRequest(document))}>
              <Mail size={13} aria-hidden="true" /> {tr("Korrekturanforderung erstellen", "Draft correction request", "Redactar solicitud de corrección")}
            </button>
          </div>
        )}

        <div className="scroll-area min-h-0 flex-1 space-y-4 px-4 py-4">
          {messages.length === 0 && (
            <div className="flex min-h-full flex-col justify-center !mb-0">
              <div className="mx-auto w-full max-w-xl">
                <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl border border-accent-line bg-accent-soft text-accent" aria-hidden="true">
                  <MessageSquare size={18} />
                </span>
                <h3 className="mt-3 text-center text-sm font-semibold text-fg">
                  {tr("Fragen zum Beleg", "Ask about this document", "Preguntas sobre el documento")}
                </h3>
                <p className="mx-auto mt-1 max-w-[56ch] text-center text-xs leading-relaxed text-subtle">
                  {tr(
                    "Antworten stützen sich nur auf Belegtext und Prüfergebnis und nennen Zeilen und Normen. Ein Klick auf einen Zeilenverweis zeigt die Stelle im Beleg.",
                    "Answers rely only on the document text and audit findings, citing lines and statutes. Click a line reference to see it in the document.",
                    "Las respuestas se basan solo en el documento y los hallazgos, citando líneas y normas. Un clic en una referencia muestra la línea.",
                  )}
                </p>
                {suggestions.length > 0 && (
                  <ul className="mt-5 grid gap-2">
                    {suggestions.map((suggestion) => (
                      <li key={suggestion.label}>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void ask(suggestion.prompt)}
                          className="group flex w-full items-center gap-3 rounded-lg border border-line px-3.5 py-2.5 text-left text-sm text-fg transition-colors duration-150 hover:border-line-strong hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <span className="min-w-0 flex-1">{suggestion.label}</span>
                          <ArrowUp size={13} aria-hidden="true" className="shrink-0 text-subtle transition-colors duration-150 group-hover:text-accent" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
          {messages.map((message, index) =>
            message.role === "user" ? (
              <div key={index} className="flex flex-col items-end">
                <p
                  className={cx(
                    "max-w-[85%] rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm leading-relaxed text-fg transition-opacity",
                    message.aborted && "opacity-75",
                  )}
                >
                  {message.content}
                </p>
                {message.aborted && (
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-subtle">
                    <span>{tr("Abgebrochen", "Cancelled", "Cancelado")}</span>
                    <span aria-hidden="true">·</span>
                    <button
                      type="button"
                      onClick={() => void ask(message.content)}
                      disabled={busy}
                      className="font-medium text-accent hover:underline disabled:opacity-50"
                    >
                      {tr("Erneut senden", "Resend", "Reenviar")}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div key={index} className="max-w-[92%]">
                <div
                  className={cx(
                    "text-sm leading-relaxed",
                    message.tone === "error" ? "rounded-lg border border-bad-line bg-bad-soft px-3 py-2 text-bad" : "text-muted",
                    message.tone === "notice" && "rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-fg",
                    message.tone === "heuristic" && "rounded-lg border border-warn-line px-3 py-2",
                  )}
                >
                  {message.tone === "error" || message.tone === "notice" ? message.content : <Markdown text={message.content} onCite={setCited} />}
                </div>
                {(message.meta || (message.tone !== "error" && message.tone !== "notice")) && (
                  <div className="mt-1 flex items-center gap-1.5 text-xs text-subtle">
                    {message.meta && <span>{message.meta}</span>}
                    {message.tone !== "error" && message.tone !== "notice" && (
                      <CopyButton value={plainAnswer(message.content)} label={tr("Antwort", "Answer", "Respuesta")} className="-ml-0.5" />
                    )}
                  </div>
                )}
              </div>
            ),
          )}
          {busyHere && (
            <div className="flex items-center gap-2.5 text-xs text-subtle" role="status" aria-live="polite">
              <Spinner size={12} />
              <span className="text-muted">{td(step ?? tr("Belegstellen und Rechtsnormen prüfen", "Checking citations and regulations", "Comprobando citas y normativa"))}</span>
              {startedAt && <span className="tabular-nums">· {formatElapsed(now - startedAt)}</span>}
            </div>
          )}
          {/* Sprungmarke ohne eigene Höhe; der leere Zustand trägt keinen space-y-Abstand (kein Scrollbalken). */}
          <div ref={endRef} className="h-0" aria-hidden="true" />
        </div>

        {isReference && messages.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-line px-4 pt-2.5" aria-label={tr("Standardfragen", "Standard questions", "Preguntas estándar")}>
            {suggestions.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                onClick={() => void ask(suggestion.prompt)}
                disabled={busy}
                className="rounded-md border border-line px-2 py-1 text-left text-xs text-muted transition-colors duration-150 hover:border-line-strong hover:text-fg disabled:opacity-50"
              >
                {suggestion.label}
              </button>
            ))}
          </div>
        )}

        <form
          className="border-t border-line p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void ask(input);
          }}
        >
          <div className="composer">
            <AutoTextarea
              ref={inputRef}
              className="px-3 pb-1 pt-2.5"
              minRows={1}
              maxRows={6}
              value={input}
              disabled={busy}
              placeholder={tr("Frage zum Beleg…", "Ask about this document…", "Pregunta sobre el documento…")}
              aria-label={tr("Frage an den Compliance Copilot", "Question for Compliance Copilot", "Pregunta para Compliance Copilot")}
              name="copilot-question"
              autoComplete="off"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (event.nativeEvent.isComposing || event.keyCode === 229) return;
                  void ask(input);
                }
              }}
            />
            <div className="flex items-center gap-3 px-2.5 pb-2">
              <span className="hidden min-w-0 truncate pl-0.5 text-xs text-subtle sm:inline">
                <Kbd>Enter</Kbd> {tr("senden", "send", "enviar")} · <Kbd>{tr("Umschalt", "Shift", "Mayús")}</Kbd> + <Kbd>Enter</Kbd> {tr("neue Zeile", "new line", "nueva línea")}
              </span>
              {busy ? (
                <button
                  className="composer-send ml-auto"
                  type="button"
                  onClick={stop}
                  aria-label={tr("Antwort stoppen", "Stop answer", "Detener respuesta")}
                  title={tr("Antwort stoppen (Esc)", "Stop answer (Esc)", "Detener respuesta (Esc)")}
                >
                  <Square size={11} fill="currentColor" aria-hidden="true" />
                </button>
              ) : (
                <button className="composer-send ml-auto" type="submit" disabled={input.trim().length < 2} aria-label={tr("Senden", "Send", "Enviar")} title={tr("Senden (Enter)", "Send (Enter)", "Enviar (Enter)")}>
                  <ArrowUp size={16} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
          <p className="mt-1.5 text-xs text-subtle">
            {tr(
              "Keine Rechts- oder Steuerberatung; Cloud-Modelle erhalten den Text nur pseudonymisiert.",
              "Not legal or tax advice; cloud models only receive pseudonymized text.",
              "No constituye asesoramiento legal ni fiscal; los modelos en la nube solo reciben texto seudonimizado.",
            )}
          </p>
        </form>
      </section>

      <section className="card flex min-h-0 flex-col p-4" aria-label={draft !== null ? tr("Korrekturanforderung", "Correction request", "Solicitud de corrección") : tr("Belegtext", "Document text", "Texto del documento")}>
        {draft !== null ? (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-fg">{tr("Korrekturanforderung (Entwurf)", "Correction Request (Draft)", "Solicitud de corrección (borrador)")}</h2>
                <p className="text-xs text-subtle">
                  {tr(
                    "Aus dem Prüfergebnis erzeugt, ohne Sprachmodell – vor dem Versand prüfen und ergänzen.",
                    "Generated deterministically from audit findings without an LLM – review and adjust before sending.",
                    "Generado sin IA a partir de los hallazgos; revísalo y complétalo antes de enviar.",
                  )}
                </p>
              </div>
              <span className="flex items-center gap-1">
                <CopyButton value={draft} label={tr("Entwurf", "Draft", "Borrador")} />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() =>
                    downloadBlob(
                      draft,
                      `${tr("Korrekturanforderung", "CorrectionRequest", "SolicitudCorreccion")}_${document.extraction?.document_number ?? document.id.slice(0, 8)}.txt`,
                      "text/plain;charset=utf-8",
                    )
                  }
                >
                  <Download size={13} aria-hidden="true" /> .txt
                </button>
              </span>
            </div>
            <textarea
              className="input scroll-area min-h-0 flex-1 resize-none font-sans leading-relaxed"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-label={tr("Entwurf der Korrekturanforderung bearbeiten", "Edit correction request draft", "Editar borrador de solicitud")}
              name="correction-draft"
              spellCheck
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-xs text-subtle">
                {tr(
                  "Die Entscheidung liegt bei der Prüfperson (menschliche Aufsicht, Art. 14 VO (EU) 2024/1689).",
                  "Final decision rests with the human auditor (Human Oversight, Art. 14 Reg. (EU) 2024/1689).",
                  "La decisión final corresponde al auditor humano (supervisión humana, Art. 14 Reg. (UE) 2024/1689).",
                )}
              </p>
              <button className="btn" onClick={() => setDraft(null)}>{tr("Zurück zum Beleg", "Back to document", "Volver al documento")}</button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="truncate text-sm font-semibold text-fg" title={document.filename}>{document.filename}</h2>
              {cited != null && (
                <button className="btn btn-ghost btn-sm" onClick={() => setCited(null)}>
                  {tr("Zeile", "Line", "Línea")} <span className="tabular-nums">{cited}</span> · {tr("Markierung lösen", "Clear highlight", "Quitar resaltado")}
                </button>
              )}
            </div>
            <SourceText document={document} cited={cited} />
          </>
        )}
      </section>
    </div>
  );
}
