"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { buildCorrectionRequest, correctionDefects } from "../lib/correction";
import { cx, formatElapsed, formatModel } from "../lib/format";
import { Markdown } from "../lib/markdown";
import type { CopilotTurn, DocumentDetail, DocumentSummary, ThinkingLevel } from "../types/api";
import { AlertTriangle, Download, FileText, Mail, MessageSquare, Send } from "./icons";
import { Select } from "./Select";
import { AutoTextarea, CopyButton, EmptyState, Segmented, Spinner } from "./ui";

/** Standardfragen (für die Musterdaten liegen dazu Antworten ohne Modell vor, siehe app/demo.py). */
const Q_FIELDS = "Welche Pflichtangaben fehlen in dieser Rechnung?";
const Q_AI_ACT = "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?";
const Q_AI_ACT_GENERAL = "Welche Pflichten ergeben sich aus der EU-AI-Act-Einstufung dieses Dokuments?";
const Q_CORRECTION = "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?";
const Q_GDPR_GENERAL = "Welche Datenschutz- und DSGVO-Pflichten betreffen dieses Dokument?";
const Q_SUMMARY_GENERAL = "Welche wesentlichen Compliance-Befunde und Fundstellen liegen vor?";

/** Nur Fragen, die zum geprüften Beleg passen; ungeprüfte Dokumente zeigen keine irreführenden Vorschlagschips. */
function suggestionsFor(document: DocumentDetail | null): string[] {
  if (!document || document.status !== "extracted") return [];
  const invoice = document.extraction?.doc_type === "invoice";
  const ai = Boolean(document.compliance?.ai_act.describes_ai_system || document.compliance?.ai_act.is_high_risk);
  const aiQuestion = document.provider === "reference" ? Q_AI_ACT : Q_AI_ACT_GENERAL;
  const list = [...(invoice ? [Q_FIELDS] : []), ...(ai ? [aiQuestion] : []), ...(invoice ? [Q_CORRECTION] : [])];
  return list.length ? list : [Q_GDPR_GENERAL, Q_SUMMARY_GENERAL];
}

const THINKING: { value: ThinkingLevel; label: string }[] = [
  { value: "low", label: "Knapp" },
  { value: "medium", label: "Standard" },
  { value: "high", label: "Gründlich" },
];

interface Message extends CopilotTurn {
  meta?: string;
  tone?: "error" | "notice" | "heuristic";
}

/** Beide Spalten fuellen das Fenster exakt (Kopfzeile 57 px + Innenabstand 2 x 16 px), nie unter 560 px. */
const VIEW_HEIGHT = "h-[max(560px,calc(100vh-89px))] 2xl:h-[max(560px,calc(100vh-97px))]";

function newProgressId(): string {
  return `cp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Belegtext mit Zeilennummern; ein Zeilenverweis aus der Antwort springt hierher. */
function SourceText({ document, cited }: { document: DocumentDetail; cited: number | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => (document.text_view?.text ?? document.text_preview ?? "").split("\n"), [document]);
  useEffect(() => {
    if (cited == null) return;
    const target = containerRef.current?.querySelector<HTMLElement>(`[data-line="${cited}"]`);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [cited]);
  if (!lines.join("").trim()) {
    return <EmptyState icon={<FileText size={18} aria-hidden="true" />} title="Kein Belegtext vorhanden" />;
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

  const messages = document ? threads[document.id] ?? [] : [];
  const defects = correctionDefects(document);
  const isReference = document?.provider === "reference";
  const suggestions = suggestionsFor(document);

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

  const ask = useCallback(async (question: string) => {
    if (!document || question.trim().length < 2 || busy) return;
    const id = document.id;
    const history: CopilotTurn[] = (threads[id] ?? [])
      .filter((message) => message.tone !== "error" && message.tone !== "notice")
      .map(({ role, content }) => ({ role, content }));
    setThreads((all) => ({ ...all, [id]: [...(all[id] ?? []), { role: "user", content: question.trim() }] }));
    setInput("");
    setBusy(true);
    setStep("Frage verstehen");
    setStartedAt(Date.now());
    setNow(Date.now());
    const progressId = newProgressId();
    const poll = window.setInterval(() => {
      api.copilotProgress(progressId).then((progress) => progress.current && setStep(progress.current)).catch(() => undefined);
    }, 700);
    try {
      const response = await api.copilot(id, question.trim(), history, thinking, progressId);
      const meta = response.reference
        ? "Musterantwort · ohne KI-Modell"
        : response.heuristic
          ? "Regelwerk · KI nicht verfügbar"
          : `${formatModel(response.model)} · ${(response.duration_ms / 1000).toFixed(1).replace(".", ",")} s${response.failover?.length ? " · Ausweichmodell" : ""}`;
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), { role: "assistant", content: response.answer, meta, tone: response.heuristic ? "heuristic" : undefined }],
      }));
    } catch (err) {
      const error = err instanceof ApiError ? err : null;
      const content = error
        ? `${error.message}${error.hint ? ` – ${error.hint}` : ""}`
        : "Die Frage konnte nicht beantwortet werden. Bitte erneut senden.";
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), { role: "assistant", content, tone: error?.code === "network" ? "notice" : "error" }],
      }));
    } finally {
      window.clearInterval(poll);
      setBusy(false);
      setStep(null);
      setStartedAt(null);
    }
  }, [document, busy, threads, thinking]);

  const analyzed = documents.filter((doc) => doc.status === "extracted" && !doc.archived);
  const choices: { id: string; filename: string }[] =
    document && !analyzed.some((doc) => doc.id === document.id) ? [document, ...analyzed] : analyzed;
  const options = choices.map((doc) => ({ value: doc.id, label: doc.filename }));

  if (!document) {
    return (
      <div className={cx("card flex items-center justify-center", VIEW_HEIGHT)}>
        <EmptyState icon={<MessageSquare size={20} aria-hidden="true" />} title="Noch kein Beleg ausgewählt">
          <p>Unter „Prüfung“ einen Beleg auswählen oder Musterdaten laden – der Copilot beantwortet dann Fragen mit Zeilen- und Normverweisen.</p>
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
              <p className="truncate text-xs text-subtle">{modelLabel}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {options.length > 1 && (
              <Select value={document.id} onChange={onSelect} options={options} ariaLabel="Beleg für den Copilot" width={300} className="h-8 max-w-[280px] justify-between" />
            )}
            <Segmented<ThinkingLevel> size="sm" ariaLabel="Denkstufe" value={thinking} onChange={setThinking} options={THINKING} />
          </div>
        </header>

        {bannerReady && modelReady === false && (
          <div className="anim-fade flex items-start gap-2 border-b border-line bg-warn-soft px-4 py-2 text-xs text-fg" role="status">
            <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            <span>
              Kein Sprachmodell erreichbar. Freie Fragen beantwortet das Regelwerk aus dem Prüfergebnis (gekennzeichnet)
              {isReference ? "; die Standardfragen der Musterdaten beantwortet der Copilot auch ohne Modell." : "."}
            </span>
          </div>
        )}

        {defects.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <p className="text-xs text-muted">
              <span className="font-semibold tabular-nums text-warn">{defects.length}</span>{" "}
              {defects.length === 1 ? "Mangel" : "Mängel"} nach § 14 UStG – Lieferanten um eine berichtigte Rechnung bitten.
            </p>
            <button className="btn btn-sm" onClick={() => setDraft(buildCorrectionRequest(document))}>
              <Mail size={13} aria-hidden="true" /> Korrekturanforderung erstellen
            </button>
          </div>
        )}

        <div className="scroll-area min-h-0 flex-1 space-y-4 px-4 py-4">
          {messages.length === 0 && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-subtle">
                Fragen zu <span className="font-medium text-fg">{document.filename}</span>. Antworten stützen sich ausschließlich auf
                den Belegtext und das Prüfergebnis und verweisen auf Zeilen ([Z. n]) und Normen. Ein Klick auf einen Zeilenverweis
                zeigt die Stelle im Beleg.
              </p>
              {suggestions.length > 0 && (
                <div className="grid grid-cols-1 gap-2">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => void ask(suggestion)}
                      className="rounded-lg border border-line px-3 py-2 text-left text-sm text-fg transition-colors duration-150 hover:border-line-strong hover:bg-surface-hover"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((message, index) =>
            message.role === "user" ? (
              <div key={index} className="flex justify-end">
                <p className="max-w-[85%] rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm leading-relaxed text-fg">{message.content}</p>
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
              <span className="text-muted">{step ?? "Modell denkt nach"}</span>
              {startedAt && <span className="tabular-nums">· {formatElapsed(now - startedAt)}</span>}
            </div>
          )}
          <div ref={endRef} />
        </div>

        {isReference && messages.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-line px-4 pt-2.5" aria-label="Standardfragen">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => void ask(suggestion)}
                disabled={busy}
                className="rounded-md border border-line px-2 py-1 text-left text-xs text-muted transition-colors duration-150 hover:border-line-strong hover:text-fg disabled:opacity-50"
              >
                {suggestion}
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
              placeholder="Frage zum Beleg…"
              aria-label="Frage an den Compliance Copilot"
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
            <button className="btn btn-primary h-[38px] w-[38px] shrink-0 rounded-full p-0" type="submit" disabled={busy || input.trim().length < 2} aria-label="Senden">
              <Send size={15} aria-hidden="true" />
            </button>
          </div>
          <p className="mt-1.5 text-xs text-subtle">
            Enter sendet, Umschalt + Enter für eine neue Zeile. Keine Rechts- oder Steuerberatung; Cloud-Modelle erhalten den Text nur pseudonymisiert.
          </p>
        </form>
      </section>

      <section className="card flex min-h-0 flex-col p-4" aria-label={draft !== null ? "Korrekturanforderung" : "Belegtext"}>
        {draft !== null ? (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-fg">Korrekturanforderung (Entwurf)</h2>
                <p className="text-xs text-subtle">Aus dem Prüfergebnis erzeugt, ohne Sprachmodell – vor dem Versand prüfen und ergänzen.</p>
              </div>
              <span className="flex items-center gap-1">
                <CopyButton value={draft} label="Entwurf" />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => downloadBlob(draft, `Korrekturanforderung_${document.extraction?.document_number ?? document.id.slice(0, 8)}.txt`, "text/plain;charset=utf-8")}
                >
                  <Download size={13} aria-hidden="true" /> .txt
                </button>
              </span>
            </div>
            <textarea
              className="input scroll-area min-h-0 flex-1 resize-none font-sans leading-relaxed"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-label="Entwurf der Korrekturanforderung bearbeiten"
              name="correction-draft"
              spellCheck
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-xs text-subtle">Die Entscheidung liegt bei der Prüfperson (menschliche Aufsicht, Art. 14 VO (EU) 2024/1689).</p>
              <button className="btn" onClick={() => setDraft(null)}>Zurück zum Beleg</button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="truncate text-sm font-semibold text-fg" title={document.filename}>{document.filename}</h2>
              {cited != null && (
                <button className="btn btn-ghost btn-sm" onClick={() => setCited(null)}>
                  Zeile <span className="tabular-nums">{cited}</span> · Markierung lösen
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
