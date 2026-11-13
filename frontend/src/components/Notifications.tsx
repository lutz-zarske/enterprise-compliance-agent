"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { cx, formatModel } from "../lib/format";
import { useDismiss, usePopoverExclusive } from "../lib/popover";
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
 * Kontextabhaengige Hinweise in der Kopfzeile - nur sichtbar, wenn es etwas zu tun gibt:
 * lokale KI aus (mit 1-Klick-Start, wenn das lokale Modell in der Kaskade steht),
 * fehlendes lokales Modell (Vorschlag aus der Vorrangliste), Cloud ohne Key,
 * Ledger-Befund, erschoepftes Cloud-Budget.
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
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "notifications");
  useDismiss(open, close, [ref]);

  const usesLocal = Boolean(health?.inference?.uses_local);
  const ollamaDown = online && usesLocal && health?.ollama.status === "unavailable";
  const modelMissing = online && usesLocal && health?.ollama.status === "degraded" && !health.ollama.model_available;

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

  if (!notices.length) return null;
  const lead = notices.find((notice) => notice.tone === "bad") ?? notices[0];
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
        {notices.length > 1 && <span className="tabular-nums opacity-80">+{notices.length - 1}</span>}
        <ChevronDown size={12} aria-hidden="true" className={cx("transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open && (
        <div role="dialog" aria-label="Hinweise" className="glass-menu absolute right-0 top-full z-[70] mt-2 w-[22rem] p-2">
          <ul className="flex flex-col gap-1.5">
            {notices.map((notice) => (
              <li key={notice.key} className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
                <p className={cx("flex items-center gap-1.5 text-[13px] font-semibold", notice.tone === "bad" ? "text-bad" : "text-warn")}>
                  {notice.tone === "bad" ? <ShieldAlert size={13} aria-hidden="true" /> : <AlertTriangle size={13} aria-hidden="true" />}
                  {notice.title}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted">{notice.text}</p>
                {notice.action && <div className="mt-2">{notice.action}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
