"use client";

import React, { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { CopilotTurn, DocumentDetail } from "../types/api";
import { cx, formatModel } from "../lib/format";
import { MessageSquare, Send, Sparkles, X } from "./icons";
import { Spinner } from "./ui";

const SUGGESTIONS = [
  "Welche Pflichtangaben fehlen in dieser Rechnung?",
  "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?",
  "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?",
];

interface Message extends CopilotTurn {
  meta?: string;
  error?: boolean;
}

/** Hebt Zeilenverweise "[Z. 4]" und Normzitate optisch hervor. */
function renderAnswer(text: string): React.ReactNode[] {
  return text.split(/(\[Z\.\s?\d+\])/g).map((part, index) =>
    /^\[Z\.\s?\d+\]$/.test(part) ? (
      <span key={index} className="mx-0.5 rounded border border-accent-line bg-accent-soft px-1 font-mono text-[11px] text-accent">
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

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, busy]);

  if (!open) return null;

  async function ask(question: string) {
    if (!document || !question.trim() || busy) return;
    const id = document.id;
    const history: CopilotTurn[] = (threads[id] ?? []).filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
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
          meta: `${formatModel(response.model)} · ${(response.duration_ms / 1000).toFixed(1)} s`,
        }],
      }));
    } catch (err) {
      const message = err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err);
      setThreads((all) => ({ ...all, [id]: [...(all[id] ?? []), { role: "assistant", content: message, error: true }] }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-line bg-surface-solid shadow-2xl no-print"
      aria-label="Compliance Copilot"
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="rounded-lg border border-accent-line bg-accent-soft p-1.5 text-accent"><Sparkles size={15} /></div>
          <div>
            <p className="text-sm font-semibold text-fg">Compliance Copilot</p>
            <p className="font-mono text-[10.5px] text-subtle">{modelLabel}</p>
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
            </p>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => ask(suggestion)}
                className="block w-full rounded-lg border border-line px-3 py-2 text-left text-[13px] text-fg transition-colors duration-150 hover:border-line-strong hover:bg-surface-2"
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
                "max-w-[90%] rounded-lg border px-3 py-2 text-[13px] leading-relaxed",
                message.role === "user" && "border-accent-line bg-accent-soft text-fg",
                message.role === "assistant" && !message.error && "border-line bg-surface-2 text-fg",
                message.error && "border-bad-line bg-bad-soft text-bad",
              )}
            >
              <div className="whitespace-pre-wrap break-words">{message.role === "assistant" ? renderAnswer(message.content) : message.content}</div>
              {message.meta && <p className="mt-1.5 font-mono text-[10px] text-subtle">{message.meta}</p>}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-subtle"><Spinner size={12} /> Copilot analysiert das Dokument …</div>
        )}
        <div ref={endRef} />
      </div>

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
            placeholder="Frage zum Dokument …"
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
        <p className="mt-1.5 flex items-center gap-1 text-[10.5px] text-subtle">
          <MessageSquare size={11} /> Keine Rechts- oder Steuerberatung. Cloud-Modelle erhalten den Text nur pseudonymisiert.
        </p>
      </form>
    </aside>
  );
}
