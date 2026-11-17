"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { buildCorrectionRequest, correctionDefects } from "../lib/correction";
import { cx, formatElapsed, formatModel } from "../lib/format";
import { type Locale, useI18n } from "../lib/i18n";
import { Markdown } from "../lib/markdown";
import type { CopilotTurn, DocumentDetail, DocumentSummary, ThinkingLevel } from "../types/api";
import { AlertTriangle, Download, FileText, Mail, MessageSquare, Send, Square } from "./icons";
import { Select } from "./Select";
import { AutoTextarea, CopyButton, EmptyState, Segmented, Spinner } from "./ui";

const QUESTIONS: Record<Locale, {
  fields: string;
  aiActRef: string;
  aiActGeneral: string;
  correction: string;
  gdprGeneral: string;
  summaryGeneral: string;
}> = {
  de: {
    fields: "Welche Pflichtangaben fehlen in dieser Rechnung?",
    aiActRef: "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?",
    aiActGeneral: "Welche Pflichten ergeben sich aus der EU-AI-Act-Einstufung dieses Dokuments?",
    correction: "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?",
    gdprGeneral: "Welche Datenschutz- und DSGVO-Pflichten betreffen dieses Dokument?",
    summaryGeneral: "Welche wesentlichen Compliance-Befunde und Fundstellen liegen vor?",
  },
  en: {
    fields: "Which mandatory fields are missing from this invoice?",
    aiActRef: "Why does the system classify this PDF as Annex III No. 4?",
    aiActGeneral: "What obligations result from the EU AI Act classification of this document?",
    correction: "How must the invoice be corrected to qualify for input VAT deduction?",
    gdprGeneral: "Which data privacy and GDPR obligations apply to this document?",
    summaryGeneral: "What are the key compliance findings and line references?",
  },
  es: {
    fields: "¿Qué datos obligatorios faltan en esta factura?",
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
  const list: Suggestion[] = [
    ...(invoice ? [{ label: q.fields, prompt: q.fields }] : []),
    ...(ai
      ? [
          document.provider === "reference"
            ? { label: q.aiActRef, prompt: q.aiActRef }
            : { label: q.aiActGeneral, prompt: q.aiActGeneral },
        ]
      : []),
    ...(invoice ? [{ label: q.correction, prompt: q.correction }] : []),
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

/** Beide Spalten fuellen das Fenster exakt (Kopfzeile 57 px + Innenabstand 2 x 16 px), nie unter 560 px. */
const VIEW_HEIGHT = "h-[max(560px,calc(100vh-89px))] 2xl:h-[max(560px,calc(100vh-97px))]";

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
              {line || " "}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Compliance Copilot als ruhiger Arbeitsbereich: links das Gespraech mit Live-Arbeitsschritten,
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
  const [busy, setBusy] = useState(false);
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
  const isReference = document?.provider === "reference";
  const suggestions = suggestionsFor(document, locale);

  // Modell-Banner erst nach kurzer Verzoegerung - kein Aufblitzen waehrend des Kaltstarts.
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

  // Laufzeit sekuendlich weiterzaehlen, solange gearbeitet wird.
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
    if (!busy) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && draft === null) {
        event.preventDefault();
        stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, draft, stop]);

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
    setBusy(true);
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
      const secStr = locale === "de" ? `${sec.replace(".", ",")} s` : `${sec} s`;
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
        ? `${error.message}${error.hint ? ` – ${error.hint}` : ""}`
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
      setBusy(false);
      setStep(null);
      setStartedAt(null);
    }
  }, [document, busy, threads, thinking, locale, tr]);

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
      <section className="card flex min-h-0 flex-col" aria-label="Compliance Copilot">
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
              {defects.length === 1 ? tr("Mangel", "defect", "defecto") : tr("Mängel", "defects", "defectos")}{" "}
              {tr("nach § 14 UStG – Lieferanten um eine berichtigte Rechnung bitten.", "under Sec. 14 UStG – request a corrected invoice from the supplier.", "según § 14 UStG – solicitar una factura rectificada.")}
            </p>
            <button className="btn btn-sm" onClick={() => setDraft(buildCorrectionRequest(document))}>
              <Mail size={13} aria-hidden="true" /> {tr("Korrekturanforderung erstellen", "Draft correction request", "Redactar solicitud de corrección")}
            </button>
          </div>
        )}

        <div className="scroll-area min-h-0 flex-1 space-y-4 px-4 py-4">
          {messages.length === 0 && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-subtle">
                {tr(
                  `Fragen zu ${document.filename}. Antworten stützen sich ausschließlich auf den Belegtext und das Prüfergebnis und verweisen auf Zeilen ([Z. n]) und Normen. Ein Klick auf einen Zeilenverweis zeigt die Stelle im Beleg.`,
                  `Questions about ${document.filename}. Answers rely strictly on the document text and audit findings, citing lines ([Z. n]) and statutes. Click any citation to jump to the source line.`,
                  `Preguntas sobre ${document.filename}. Las respuestas se basan exclusivamente en el documento y los hallazgos, citando líneas ([Z. n]) y normativa.`,
                )}
              </p>
              {suggestions.length > 0 && (
                <div className="grid grid-cols-1 gap-2">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion.label}
                      onClick={() => void ask(suggestion.prompt)}
                      className="rounded-lg border border-line px-3 py-2 text-left text-sm text-fg transition-colors duration-150 hover:border-line-strong hover:bg-surface-hover"
                    >
                      {suggestion.label}
                    </button>
                  ))}
                </div>
              )}
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
                {message.meta && <p className="mt-1.5 text-xs text-subtle">{message.meta}</p>}
              </div>
            ),
          )}
          {busy && (
            <div className="flex items-center gap-2.5 text-xs text-subtle" role="status" aria-live="polite">
              <Spinner size={12} />
              <span className="text-muted">{td(step ?? tr("Belegstellen und Rechtsnormen prüfen", "Checking citations and regulations", "Comprobando citas y normativa"))}</span>
              {startedAt && <span className="tabular-nums">· {formatElapsed(now - startedAt)}</span>}
            </div>
          )}
          <div ref={endRef} />
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
          <div className="flex items-end gap-2">
            <AutoTextarea
              ref={inputRef}
              className="flex-1"
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
                  void ask(input);
                }
              }}
            />
            {busy ? (
              <button
                className="btn btn-primary h-[38px] w-[38px] shrink-0 rounded-full p-0"
                type="button"
                onClick={stop}
                aria-label={tr("Antwort stoppen", "Stop answer", "Detener respuesta")}
                title={tr("Antwort stoppen (Esc)", "Stop answer (Esc)", "Detener respuesta (Esc)")}
              >
                <Square size={13} fill="currentColor" aria-hidden="true" />
              </button>
            ) : (
              <button className="btn btn-primary h-[38px] w-[38px] shrink-0 rounded-full p-0" type="submit" disabled={input.trim().length < 2} aria-label={tr("Senden", "Send", "Enviar")}>
                <Send size={15} aria-hidden="true" />
              </button>
            )}
          </div>
          <p className="mt-1.5 text-xs text-subtle">
            {tr(
              "Enter sendet, Umschalt + Enter für eine neue Zeile. Keine Rechts- oder Steuerberatung; Cloud-Modelle erhalten den Text nur pseudonymisiert.",
              "Enter sends, Shift + Enter adds a newline. Not legal or tax advice; cloud models only receive pseudonymized text.",
              "Enter envía, Mayús + Enter añade línea. No constituye asesoramiento legal ni fiscal; los modelos en la nube solo reciben texto seudonimizado.",
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
