"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import { cx, formatModel } from "../lib/format";
import { useAnchoredStyle, useDismiss, usePopoverExclusive } from "../lib/popover";
import type { HealthResponse, LedgerVerification, LocalAiStatus, RuntimeSettings } from "../types/api";
import { AlertTriangle, Bell, ChevronDown, Play, Settings, ShieldAlert } from "./icons";
import { Spinner } from "./ui";

type Tone = "warn" | "bad";

interface Notice {
  key: string;
  tone: Tone;
  title: string;
  text: string;
  action?: React.ReactNode;
}

/**
 * Hinweise zur lokalen KI lassen sich fuer die Browser-Sitzung ausblenden - etwa bei
 * bewusstem Cloud-Betrieb mit Ollama nur als Reserve.  Ledger-, Key- und Budget-Befunde
 * bleiben immer sichtbar.
 */
const HIDDEN_KEY = "eca-hinweise-ausgeblendet";
const MUTABLE = new Set(["ollama", "model"]);

function readHidden(): string[] {
  try {
    const raw = window.sessionStorage.getItem(HIDDEN_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

/**
 * Kontextabhaengige Hinweise in der Kopfzeile - nur sichtbar, wenn es etwas zu tun gibt:
 * lokale KI aus (mit 1-Klick-Start, wenn lokal das Hauptmodell ist), fehlendes lokales
 * Modell (Vorschlag aus der Vorrangliste), Cloud ohne Key, Ledger-Befund, erschoepftes
 * Cloud-Budget.
 */
export function Notifications({ health, settings, ledger, online, onOpenSettings, onChanged, notify }: {
  health: HealthResponse | null;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  online: boolean;
  onOpenSettings: () => void;
  onChanged: () => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [local, setLocal] = useState<LocalAiStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [hidden, setHidden] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "notifications");
  useDismiss(open, close, [ref, menuRef]);
  const style = useAnchoredStyle(open, ref, { width: 352, maxHeight: 520, align: "right" });

  // Erst nach dem Mount lesen (SSR-sicher, keine Hydrationsabweichung).
  useEffect(() => setHidden(readHidden()), []);

  const hideNotice = useCallback((key: string) => {
    setHidden((previous) => {
      const next = Array.from(new Set([...previous, key]));
      try {
        window.sessionStorage.setItem(HIDDEN_KEY, JSON.stringify(next));
      } catch {
        // Ohne Sitzungsspeicher gilt das Ausblenden nur bis zum Neuladen.
      }
      return next;
    });
    setOpen(false);
  }, []);

  // Nur wenn lokal das Hauptmodell ist. Steht Ollama bloß als Reserve hinter einem
  // Cloud-Modell, zeigt Einstellungen › Ausweich-Kaskade den Zustand - kein Störsignal hier.
  const primaryLocal = (settings?.inference_mode ?? health?.inference?.mode) === "local";
  const ollamaDown = online && primaryLocal && health?.ollama.status === "unavailable";
  const modelMissing = online && primaryLocal && health?.ollama.status === "degraded" && !health.ollama.model_available;

  useEffect(() => {
    if (!ollamaDown) return;
    let alive = true;
    api.localAi().then((status) => alive && setLocal(status)).catch(() => alive && setLocal(null));
    return () => {
      alive = false;
    };
  }, [ollamaDown]);

  const startOllama = useCallback(async () => {
    setStarting(true);
    try {
      const result = await api.startOllama();
      notify(result.ok ? "ok" : "warn", result.ok ? "Lokale KI läuft" : "Lokale KI nicht gestartet", result.message);
      if (result.ok) onChanged();
    } catch (err) {
      notify("warn", "Lokale KI nicht gestartet", err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err));
    } finally {
      setStarting(false);
    }
  }, [notify, onChanged]);

  const adoptModel = useCallback(async (model: string) => {
    try {
      await api.updateSettings({ models: { local: model } });
      notify("ok", "Lokales Modell übernommen", `${formatModel(model)} · Modellwechsel im Ledger protokolliert`);
      onChanged();
    } catch (err) {
      notify("bad", "Übernehmen fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    }
  }, [notify, onChanged]);

  const notices: Notice[] = [];
  if (ollamaDown) {
    const canStart = Boolean(local?.startable && local.control_allowed);
    notices.push({
      key: "ollama",
      tone: "warn",
      title: "Lokale KI aus",
      text: canStart
        ? "Ollama ist installiert, läuft aber nicht. Bis zum Start schließt das Regelwerk Prüfungen gekennzeichnet ab."
        : `${local?.text ?? "Ollama antwortet nicht."} Bis dahin schließt das Regelwerk Prüfungen gekennzeichnet ab.`,
      action: canStart ? (
        <button type="button" className="btn btn-sm" onClick={() => void startOllama()} disabled={starting}>
          {starting ? <Spinner size={11} /> : <Play size={11} aria-hidden="true" />} {starting ? "Startet …" : "Lokale KI starten"}
        </button>
      ) : (
        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-muted">ollama serve</code>
      ),
    });
  }
  if (modelMissing && health) {
    const suggestion = health.ollama.suggested_model;
    notices.push({
      key: "model",
      tone: "warn",
      title: "Lokales Modell fehlt",
      text: suggestion
        ? `„${health.ollama.model}“ ist nicht installiert; installiert ist ${formatModel(suggestion)}.`
        : `„${health.ollama.model}“ ist nicht installiert – einmalig „ollama pull ${health.ollama.model}“ ausführen.`,
      action: suggestion ? (
        <button type="button" className="btn btn-sm" onClick={() => void adoptModel(suggestion)}>
          {formatModel(suggestion)} übernehmen
        </button>
      ) : undefined,
    });
  }
  if (online && health?.inference?.is_cloud && !health.inference.configured) {
    notices.push({
      key: "cloud",
      tone: "warn",
      title: "Cloud ohne API-Key",
      text: "Der Cloud-Modus ist aktiv, aber für den Anbieter ist kein Schlüssel hinterlegt.",
      action: (
        <button type="button" className="btn btn-sm" onClick={() => { setOpen(false); onOpenSettings(); }}>
          <Settings size={12} aria-hidden="true" /> Einstellungen
        </button>
      ),
    });
  }
  if (settings?.cloud_budget?.enabled && settings.cloud_budget.remaining === 0) {
    notices.push({
      key: "budget",
      tone: "warn",
      title: "Cloud-Tagesbudget erreicht",
      text: "Bis morgen prüfen lokale Stufen bzw. das Regelwerk; Limit über CLOUD_DAILY_TOKEN_LIMIT.",
    });
  }
  if (ledger && !ledger.valid) {
    notices.push({
      key: "ledger",
      tone: "bad",
      title: "Ledger-Befund",
      text: `Hash-Kette gebrochen${ledger.broken_at_seq != null ? ` bei Eintrag #${ledger.broken_at_seq}` : ""}: ${ledger.reason ?? "Ein Eintrag passt nicht zur Kette."}`,
    });
  }

  const visible = notices.filter((notice) => !(MUTABLE.has(notice.key) && hidden.includes(notice.key)));
  if (!visible.length) return null;
  const lead = visible.find((notice) => notice.tone === "bad") ?? visible[0];
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cx(
          "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium transition-colors duration-150",
          lead.tone === "bad" ? "border-bad-line bg-bad-soft text-bad" : "border-warn-line bg-warn-soft text-warn",
        )}
      >
        {lead.tone === "bad" ? <ShieldAlert size={12} aria-hidden="true" /> : <Bell size={12} aria-hidden="true" />}
        <span className="hidden sm:inline">{lead.title}</span>
        {visible.length > 1 && <span className="tabular-nums opacity-80">+{visible.length - 1}</span>}
        <ChevronDown size={12} aria-hidden="true" className={cx("transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open &&
        createPortal(
          <div ref={menuRef} role="dialog" aria-label="Hinweise" style={style} className="glass-menu scroll-area z-[70] p-2">
            <ul className="flex flex-col gap-1.5">
              {visible.map((notice) => (
                <li key={notice.key} className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
                  <p className={cx("flex items-center gap-1.5 text-[13px] font-semibold", notice.tone === "bad" ? "text-bad" : "text-warn")}>
                    {notice.tone === "bad" ? <ShieldAlert size={13} aria-hidden="true" /> : <AlertTriangle size={13} aria-hidden="true" />}
                    {notice.title}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{notice.text}</p>
                  {(notice.action || MUTABLE.has(notice.key)) && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {notice.action}
                      {MUTABLE.has(notice.key) && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm ml-auto text-subtle"
                          title="Bis zum Schließen des Browser-Tabs ausblenden"
                          onClick={() => hideNotice(notice.key)}
                        >
                          Ausblenden
                        </button>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )}
    </div>
  );
}
