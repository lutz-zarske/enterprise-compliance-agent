"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import { cx, formatModel } from "../lib/format";
import { useI18n } from "../lib/i18n";
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

export function Notifications({ health, settings, ledger, online, onOpenSettings, onChanged, notify }: {
  health: HealthResponse | null;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  online: boolean;
  onOpenSettings: () => void;
  onChanged: () => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const { tr, td } = useI18n();
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

  useEffect(() => setHidden(readHidden()), []);

  const hideNotice = useCallback((key: string) => {
    setHidden((previous) => {
      const next = Array.from(new Set([...previous, key]));
      try {
        window.sessionStorage.setItem(HIDDEN_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
    setOpen(false);
  }, []);

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
      notify(
        result.ok ? "ok" : "warn",
        result.ok ? tr("Lokale KI läuft", "Local AI running", "IA local activa") : tr("Lokale KI nicht gestartet", "Local AI not started", "IA local no iniciada"),
        result.message,
      );
      if (result.ok) onChanged();
    } catch (err) {
      notify(
        "warn",
        tr("Lokale KI nicht gestartet", "Local AI not started", "IA local no iniciada"),
        err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err),
      );
    } finally {
      setStarting(false);
    }
  }, [notify, onChanged, tr]);

  const adoptModel = useCallback(async (model: string) => {
    try {
      await api.updateSettings({ models: { local: model } });
      notify(
        "ok",
        tr("Lokales Modell übernommen", "Local model applied", "Modelo local aplicado"),
        `${formatModel(model)} · ${tr("Modellwechsel im Ledger protokolliert", "Model change recorded in ledger", "Cambio de modelo registrado")}`,
      );
      onChanged();
    } catch (err) {
      notify("bad", tr("Übernehmen fehlgeschlagen", "Failed to apply model", "Error al aplicar modelo"), err instanceof ApiError ? td(err.message) : String(err));
    }
  }, [notify, onChanged, td, tr]);

  const notices: Notice[] = [];
  if (ollamaDown) {
    const canStart = Boolean(local?.startable && local.control_allowed);
    notices.push({
      key: "ollama",
      tone: "warn",
      title: tr("Lokale KI aus", "Local AI off", "IA local apagada"),
      text: canStart
        ? tr(
            "Ollama ist installiert, läuft aber nicht. Bis zum Start schließt das Regelwerk Prüfungen gekennzeichnet ab.",
            "Ollama is installed but stopped. Until started, the rule engine completes audits (labelled).",
            "Ollama está instalado pero detenido. El motor de reglas completará las auditorías.",
          )
        : `${local?.text ? td(local.text) : tr("Ollama antwortet nicht.", "Ollama is unreachable.", "Ollama no responde.")} ${tr("Bis dahin schließt das Regelwerk Prüfungen gekennzeichnet ab.", "Until then, the rule engine completes audits (labelled).", "Hasta entonces el motor de reglas completa las auditorías.")}`,
      action: canStart ? (
        <button type="button" className="btn btn-sm" onClick={() => void startOllama()} disabled={starting}>
          {starting ? <Spinner size={11} /> : <Play size={11} aria-hidden="true" />} {starting ? tr("Startet …", "Starting …", "Iniciando …") : tr("Lokale KI starten", "Start local AI", "Iniciar IA local")}
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
      title: tr("Lokales Modell fehlt", "Local model missing", "Falta modelo local"),
      text: suggestion
        ? tr(
            `„${health.ollama.model}“ ist nicht installiert; installiert ist ${formatModel(suggestion)}.`,
            `"${health.ollama.model}" is not installed; available: ${formatModel(suggestion)}.`,
            `"${health.ollama.model}" no está instalado; disponible: ${formatModel(suggestion)}.`,
          )
        : tr(
            `„${health.ollama.model}“ ist nicht installiert – einmalig „ollama pull ${health.ollama.model}“ ausführen.`,
            `"${health.ollama.model}" is not installed – run "ollama pull ${health.ollama.model}" once.`,
            `"${health.ollama.model}" no está instalado – ejecute "ollama pull ${health.ollama.model}".`,
          ),
      action: suggestion ? (
        <button type="button" className="btn btn-sm" onClick={() => void adoptModel(suggestion)}>
          {tr(`${formatModel(suggestion)} übernehmen`, `Use ${formatModel(suggestion)}`, `Usar ${formatModel(suggestion)}`)}
        </button>
      ) : undefined,
    });
  }
  if (online && health?.inference?.is_cloud && !health.inference.configured) {
    notices.push({
      key: "cloud",
      tone: "warn",
      title: tr("Cloud ohne API-Key", "Cloud key missing", "Nube sin clave API"),
      text: tr(
        "Der Cloud-Modus ist aktiv, aber für den Anbieter ist kein Schlüssel hinterlegt.",
        "Cloud mode is active, but no API key is configured for the selected provider.",
        "El modo nube está activo, pero no hay clave API configurada.",
      ),
      action: (
        <button type="button" className="btn btn-sm" onClick={() => { setOpen(false); onOpenSettings(); }}>
          <Settings size={12} aria-hidden="true" /> {tr("Einstellungen", "Settings", "Ajustes")}
        </button>
      ),
    });
  }
  if (settings?.cloud_budget?.enabled && settings.cloud_budget.remaining === 0) {
    notices.push({
      key: "budget",
      tone: "warn",
      title: tr("Cloud-Tagesbudget erreicht", "Daily cloud budget reached", "Presupuesto diario alcanzado"),
      text: tr(
        "Bis Mitternacht prüfen lokale Stufen bzw. das Regelwerk.",
        "Local stages or the ruleset handle audits until midnight.",
        "Hasta medianoche analizan los niveles locales o el motor de reglas.",
      ),
    });
  }
  if (ledger && !ledger.valid) {
    notices.push({
      key: "ledger",
      tone: "bad",
      title: tr("Ledger-Befund", "Ledger mismatch", "Anomalía en registro"),
      text: tr(
        `Hash-Kette gebrochen${ledger.broken_at_seq != null ? ` bei Eintrag #${ledger.broken_at_seq}` : ""}: ${ledger.reason ?? "Ein Eintrag passt nicht zur Kette."}`,
        `Hash chain broken${ledger.broken_at_seq != null ? ` at entry #${ledger.broken_at_seq}` : ""}: ${ledger.reason ? td(ledger.reason) : "An entry does not match the chain."}`,
        `Cadena de hash rota${ledger.broken_at_seq != null ? ` en la entrada #${ledger.broken_at_seq}` : ""}: ${ledger.reason ? td(ledger.reason) : "Una entrada no coincide."}`,
      ),
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
          <div ref={menuRef} role="dialog" aria-label={tr("Hinweise", "Notifications", "Avisos")} style={style} className="glass-menu scroll-area z-[70] p-2">
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
                          title={tr("Bis zum Schließen des Browser-Tabs ausblenden", "Hide until browser tab closes", "Ocultar hasta cerrar la pestaña")}
                          onClick={() => hideNotice(notice.key)}
                        >
                          {tr("Ausblenden", "Dismiss", "Ocultar")}
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
