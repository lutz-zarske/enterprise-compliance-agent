"use client";

import React, { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { CopilotTurn, DocumentDetail } from "../types/api";
import { cx, formatModel } from "../lib/format";
import { MessageSquare, Send, X } from "./icons";
import { Spinner } from "./ui";

const SUGGESTIONS = [
  "Welche Pflichtangaben fehlen in dieser Rechnung?",
  "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?",
  "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?",
];

interface Message extends CopilotTurn {
  meta?: string;
  error?: boolean;
  notice?: boolean;
  reference?: boolean;
}

/** Fehler, die nur bedeuten: Es laeuft gerade kein Sprachmodell. */
const NO_MODEL_CODES = new Set(["ollama_unavailable", "model_not_found", "provider_not_configured", "provider_unavailable", "network"]);

/** Hebt Zeilenverweise "[Z. 4]" und Normzitate optisch hervor. */
function renderAnswer(text: string): React.ReactNode[] {
  return text.split(/(\[Z\.\s?\d+\])/g).map((part, index) =>
    /^\[Z\.\s?\d+\]$/.test(part) ? (
      <span key={index} className="mx-0.5 rounded border border-accent-line bg-accent-soft px-1 font-mono text-xs text-accent">
        {part.slice(1, -1)}
      </span>
    ) : (
      <React.Fragment key={index}>{part}</React.Fragment>
    ),
  );
}

export function CopilotDrawer({ document, open, onClose, modelLabel }: {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  modelLabel: string;
}) {
  const [threads, setThreads] = useState<Record<string, Message[]>>({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const messages = document ? threads[document.id] ?? [] : [];
  const isReference = document?.provider === "reference";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, busy]);

  // Escape schliesst den Drawer wie jedes Modal.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function ask(question: string) {
    if (!document || !question.trim() || busy) return;
    const id = document.id;
    const history: CopilotTurn[] = (threads[id] ?? [])
      .filter((m) => !m.error && !m.notice)
      .map(({ role, content }) => ({ role, content }));
    setThreads((all) => ({ ...all, [id]: [...(all[id] ?? []), { role: "user", content: question.trim() }] }));
    setInput("");
    setBusy(true);
    try {
      const response = await api.copilot(id, question.trim(), history);
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), {
          role: "assistant",
          content: response.answer,
          reference: response.reference,
          meta: response.reference
            ? "Musterantwort · ohne KI-Modell"
            : `${formatModel(response.model)} · ${(response.duration_ms / 1000).toFixed(1)} s`,
        }],
      }));
    } catch (err) {
      const message =
        err instanceof ApiError && NO_MODEL_CODES.has(err.code)
          ? "Für freie Fragen wird ein Sprachmodell benötigt: lokal mit „ollama serve“ oder über einen Cloud-Key in den Einstellungen. " +
            (isReference
              ? "Die drei Standardfragen oben beantwortet der Copilot bei Musterdaten auch ohne Modell."
              : `(${err.message})`)
          : err instanceof ApiError
            ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}`
            : String(err);
      const notice = err instanceof ApiError && NO_MODEL_CODES.has(err.code);
      setThreads((all) => ({
        ...all,
        [id]: [...(all[id] ?? []), { role: "assistant", content: message, error: !notice, notice }],
      }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className="anim-fade fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col overscroll-contain border-l border-line bg-surface-solid shadow-2xl no-print"
      aria-label="Compliance Copilot"
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="rounded-lg border border-line bg-surface-2 p-1.5 text-accent"><MessageSquare size={15} aria-hidden="true" /></div>
          <div>
            <p className="text-sm font-semibold text-fg">Compliance Copilot</p>
            <p className="font-mono text-xs text-subtle">{modelLabel}</p>
          </div>
        </div>
        <button className="btn btn-icon" onClick={onClose} aria-label="Copilot schließen"><X size={15} /></button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {!document && <p className="text-sm text-subtle">Bitte zuerst ein Dokument auswählen.</p>}
        {document && messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-xs text-subtle">
              Fragen zu <span className="font-medium text-fg">{document.filename}</span>. Antworten stützen sich ausschließlich auf den
              Dokumenttext und das Prüfergebnis und verweisen auf Zeilen ([Z. n]) und Normen.
              {isReference && " Bei Musterdaten beantwortet der Copilot die drei Standardfragen auch ohne Modell mit hinterlegten, gekennzeichneten Antworten."}
            </p>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => ask(suggestion)}
                className="block w-full rounded-lg border border-line px-3 py-2 text-left text-sm text-fg transition-colors duration-150 hover:border-line-strong hover:bg-surface-2"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className={cx("flex", message.role === "user" ? "justify-end" : "justify-start")}>
            <div
              className={cx(
                "max-w-[90%] rounded-lg border px-3 py-2 text-sm leading-relaxed",
                message.role === "user" && "border-accent-line bg-accent-soft text-fg",
                message.role === "assistant" && !message.error && !message.notice && "border-line bg-surface-2 text-fg",
                message.notice && "border-warn-line bg-warn-soft text-fg",
                message.error && "border-bad-line bg-bad-soft text-bad",
              )}
            >
              <div className="whitespace-pre-wrap break-words">{message.role === "assistant" ? renderAnswer(message.content) : message.content}</div>
              {message.meta && (
                <p className={cx("mt-1.5 text-xs", message.reference ? "font-medium text-muted" : "font-mono text-subtle")}>{message.meta}</p>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-subtle" role="status"><Spinner size={12} /> Copilot analysiert das Dokument…</div>
        )}
        <div ref={endRef} />
      </div>

      {document && isReference && messages.length > 0 && (
        <div className="border-t border-line px-3 pt-2.5" aria-label="Standardfragen">
          <p className="mb-1.5 text-xs text-subtle">Standardfragen – bei Musterdaten auch ohne Modell:</p>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => ask(suggestion)}
                disabled={busy}
                className="rounded-md border border-line px-2 py-1 text-left text-xs text-muted transition-colors duration-150 hover:border-line-strong hover:text-fg disabled:opacity-50"
              >
                {suggestion}
              </button>
            ))}
          </div>
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
          <textarea
            className="input min-h-[44px] flex-1 resize-none"
            rows={2}
            value={input}
            disabled={!document}
            placeholder="Frage zum Dokument…"
            aria-label="Frage an den Copilot"
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
          <button className="btn btn-primary h-[44px]" type="submit" disabled={!document || busy || input.trim().length < 2} aria-label="Senden">
            <Send size={15} />
          </button>
        </div>
        <p className="mt-1.5 flex items-center gap-1 text-xs text-subtle">
          <MessageSquare size={11} /> Keine Rechts- oder Steuerberatung. Cloud-Modelle erhalten den Text nur pseudonymisiert.
        </p>
      </form>
    </aside>
  );
}
