"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, fetchHealth } from "../lib/api";
import { cx, formatElapsed, formatTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { ReleaseApplyResult, ReleaseStatus } from "../types/api";
import { AlertTriangle, ArrowUpCircle, CheckCircle, RefreshCw } from "./icons";
import { HashBadge, Modal, Spinner } from "./ui";

/** Fensterweites Ereignis: ein Release wurde eingespielt (Detail: ``ReleaseApplyResult``). */
export const RELEASE_APPLIED_EVENT = "eca:release-applied";
/** Ab hier zeigt die Sperre die Anleitung für den manuellen Neustart (weiter mit Abfrage). */
const UPDATE_FALLBACK_MS = 180_000;
const UPDATE_POLL_MS = 1_000;

/**
 * Release prüfen und per Klick einspielen. Das Backend prüft laufende Analysen,
 * legt automatisch eine Sicherungskopie von ``data/agent.db`` an und protokolliert
 * den Versionswechsel im Ledger; lokale Daten und Einstellungen bleiben erhalten.
 */
export function ReleasePanel({ initial, installedVersion, externalChecking = false, onApplied, notify }: {
  initial?: ReleaseStatus | null;
  /** Bekannte Version (aus /health) - sofort sichtbar, bevor der Release-Status da ist. */
  installedVersion?: string;
  /** Der Aufrufer lädt den Status bereits (z. B. Einstellungen beim Öffnen). */
  externalChecking?: boolean;
  onApplied?: (result: ReleaseApplyResult) => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const { tr, td } = useI18n();
  const [status, setStatus] = useState<ReleaseStatus | null>(initial ?? null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ReleaseApplyResult | null>(null);

  const check = useCallback(async () => {
    setChecking(true);
    const started = Date.now();
    try {
      const result = await api.release(true);
      // Kurz sichtbarer Ladezustand, auch wenn der Abgleich sofort fertig ist.
      const rest = 600 - (Date.now() - started);
      if (rest > 0) await new Promise((resolve) => window.setTimeout(resolve, rest));
      setStatus(result);
    } catch (err) {
      notify("bad", tr("Update-Prüfung fehlgeschlagen", "Update check failed", "Error al buscar actualizaciones"), err instanceof ApiError ? td(err.message) : String(err));
    } finally {
      setChecking(false);
    }
  }, [notify, td, tr]);

  useEffect(() => {
    if (initial) setStatus(initial);
  }, [initial]);

  // Nur selbst prüfen, wenn niemand sonst den Status liefert - und nur einmal.
  const autoChecked = useRef(false);
  useEffect(() => {
    if (autoChecked.current || initial || externalChecking) return;
    autoChecked.current = true;
    void check();
  }, [initial, externalChecking, check]);
  const searching = checking || externalChecking;

  async function apply() {
    const latest = status?.latest;
    if (!latest) return;
    setBusy(true);
    try {
      const result = await api.applyRelease(latest.tag, latest.commit, "System");
      setDone(result);
      onApplied?.(result);
      if (result.restart_required) {
        notify(
          "warn",
          tr(`${result.to_tag} installiert – Neustart nötig`, `${result.to_tag} installed – restart required`, `${result.to_tag} instalada – reinicio necesario`),
          tr("Dienste von Hand neu starten, danach lädt die Seite selbst neu.", "Restart the services manually; the page reloads by itself afterwards.", "Reinicie los servicios manualmente; la página se recargará sola."),
        );
      } else {
        // Die Sperre (UpdaterLock) übernimmt: Neustart abwarten, dann neu laden.
        window.dispatchEvent(new CustomEvent<ReleaseApplyResult>(RELEASE_APPLIED_EVENT, { detail: result }));
      }
    } catch (err) {
      const error = err instanceof ApiError ? err : null;
      notify("bad", tr("Update fehlgeschlagen", "Update failed", "Error al actualizar"), error ? td(error.message) : String(err));
    } finally {
      setBusy(false);
    }
  }

  const latest = status?.latest;
  const blocked = Boolean(status?.dirty || (latest && latest.signature === "invalid"));
  // Stichpunkte aus den Commit-Texten; ältere Backends liefern nur die Betreffzeilen.
  const notes = latest?.notes ?? latest?.changelog.map((line) => line.replace(/^[0-9a-f]{7,}\s+/, "")) ?? [];
  const signatureMap: Record<string, { label: string; tone: string; icon: React.ReactNode }> = {
    valid: { label: tr("Tag-Signatur gültig", "Valid tag signature", "Firma válida"), tone: "border-ok-line bg-ok-soft text-ok", icon: <CheckCircle size={12} aria-hidden="true" /> },
    invalid: { label: tr("Tag-Signatur ungültig", "Invalid tag signature", "Firma inválida"), tone: "border-bad-line bg-bad-soft text-bad", icon: <AlertTriangle size={12} aria-hidden="true" /> },
  };
  const signature = latest ? signatureMap[latest.signature] : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg">
          {tr("Version", "Version", "Versión")} <span className="font-medium tabular-nums">{status?.current_version ?? installedVersion ?? "…"}</span>
          {status?.current_commit && <span className="ml-2 font-mono text-xs text-subtle">{status.current_commit.slice(0, 10)}</span>}
        </p>
        <button className="btn" onClick={() => void check()} disabled={searching || busy}>
          {searching ? <Spinner size={13} /> : <RefreshCw size={14} aria-hidden="true" />}{" "}
          {searching ? tr("Wird geprüft …", "Checking …", "Comprobando …") : tr("Nach Updates suchen", "Check for updates", "Buscar actualizaciones")}
        </button>
      </div>

      {status?.message && <p className="text-xs text-subtle">{td(status.message)}</p>}
      {searching && !status?.latest && (
        <p className="text-xs text-subtle" role="status">{tr("Suche nach Updates …", "Checking for updates …", "Buscando actualizaciones …")}</p>
      )}
      {!searching && status && status.git && !latest && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ok" role="status">
          <CheckCircle size={14} aria-hidden="true" /> {tr("Aktuellste Version.", "Latest version.", "Versión más reciente.")}
          {status.checked_at && (
            <span className="text-subtle">
              {tr("Zuletzt geprüft um", "Last checked at", "Última comprobación a las")} {formatTime(status.checked_at)}
            </span>
          )}
        </p>
      )}

      {latest && !done && (
        <div className="space-y-3 rounded-lg border border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <ArrowUpCircle size={16} aria-hidden="true" className="text-ok" />
            <span className="text-sm font-semibold text-fg">
              {tr(`Release ${latest.tag} verfügbar`, `Release ${latest.tag} available`, `Versión ${latest.tag} disponible`)}
            </span>
            {signature && <span className={cx("chip", signature.tone)}>{signature.icon}{signature.label}</span>}
          </div>
          {latest.title ? (
            <p className="text-sm text-fg">{latest.title}</p>
          ) : (
            latest.message && latest.message !== latest.tag && <p className="text-xs text-muted">{td(latest.message)}</p>
          )}
          {notes.length > 0 && (
            <ul className="scroll-area max-h-56 list-disc space-y-1.5 pl-4 pr-2 text-xs leading-relaxed text-muted marker:text-subtle" aria-label={tr("Änderungen", "Changes", "Cambios")}>
              {notes.map((line, index) => <li key={`${index}-${line}`} className="[overflow-wrap:anywhere]">{line}</li>)}
            </ul>
          )}
          <HashBadge value={latest.commit} label="Commit" />
          {status?.dirty && (
            <p className="text-xs text-bad">
              {tr(
                "Lokale Code-Änderungen im Arbeitsverzeichnis – bitte vor dem Update sichern oder zurücksetzen.",
                "Local code modifications in working tree – commit or reset before updating.",
                "Cambios locales en el árbol de trabajo; guárdelos o revértalos antes de actualizar.",
              )}
            </p>
          )}
          <p className="text-xs leading-relaxed text-muted">
            {tr(
              "Belege, Einstellungen und API-Keys bleiben erhalten; vorher wird die Datenbank nach data/backups/ gesichert.",
              "Documents, settings and API keys are kept; the database is backed up to data/backups/ first.",
              "Se conservan documentos, ajustes y claves API; antes se guarda una copia de la base de datos en data/backups/.",
            )}
          </p>
          <div className="flex justify-end">
            <button className="btn btn-primary" onClick={() => void apply()} disabled={busy || blocked}>
              {busy && <Spinner size={13} />} {tr("Update installieren", "Install update", "Instalar actualización")}
            </button>
          </div>
        </div>
      )}

      {done && (
        <div className={cx("rounded-lg border p-3 text-xs", done.restart_required ? "border-warn-line bg-warn-soft text-warn" : "border-ok-line bg-ok-soft text-ok")}>
          <p className="font-semibold">
            {done.restart_required
              ? tr(`${done.to_tag} installiert – Neustart nötig`, `${done.to_tag} installed – restart required`, `${done.to_tag} instalada – reinicio necesario`)
              : tr(`${done.to_tag} installiert`, `${done.to_tag} installed`, `${done.to_tag} instalada`)}
          </p>
          {done.database_backup && (
            <p className="mt-1 text-muted [overflow-wrap:anywhere]">
              {tr("Sicherung", "Backup", "Copia de seguridad")}: data/backups/{done.database_backup}
            </p>
          )}
          <p className="mt-1 leading-relaxed text-fg">
            {done.restart_required
              ? tr(
                  "Der automatische Neustart ist nur über Start_Compliance_Agent.bat unter Windows möglich. Bitte Stop_Compliance_Agent.bat und danach Start_Compliance_Agent.bat ausführen (macOS/Linux: Backend und Frontend neu starten) – der Starter aktualisiert Abhängigkeiten und baut die Oberfläche neu. Sobald beide Dienste wieder laufen, lädt diese Seite von selbst neu.",
                  "Automatic restart is only available via Start_Compliance_Agent.bat on Windows. Run Stop_Compliance_Agent.bat, then Start_Compliance_Agent.bat (macOS/Linux: restart backend and frontend) – the launcher updates dependencies and rebuilds the interface. This page reloads by itself once both services are back.",
                  "El reinicio automático solo está disponible con Start_Compliance_Agent.bat en Windows. Ejecute Stop_Compliance_Agent.bat y después Start_Compliance_Agent.bat (macOS/Linux: reinicie backend y frontend); el lanzador actualiza dependencias y recompila la interfaz. Esta página se recargará sola cuando ambos servicios vuelvan.",
                )
              : tr("Dienste starten im Hintergrund neu.", "Services are restarting in the background.", "Los servicios se reinician en segundo plano.")}
          </p>
        </div>
      )}
    </div>
  );
}

/** Dezente Pille in der Kopfzeile - nur sichtbar, wenn ein neueres Release-Tag vorliegt. */
export function GitSyncButton({ online, notify }: {
  online: boolean;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const { tr } = useI18n();
  const [status, setStatus] = useState<ReleaseStatus | null>(null);
  const [open, setOpen] = useState(false);

  // Einmal im Hintergrund, einige Sekunden nach dem Laden - kein Dauer-Polling.
  useEffect(() => {
    if (!online) return;
    const timer = window.setTimeout(() => {
      api.release(true).then(setStatus).catch(() => undefined);
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [online]);

  if (!status?.update_available || !status.latest) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={tr("Neue Version verfügbar – Änderungen prüfen und installieren", "New version available – review changes and install", "Nueva versión disponible – revisar e instalar")}
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-ok-line bg-ok-soft px-2.5 py-1 text-xs font-medium text-ok transition-colors duration-150 hover:border-ok"
      >
        <ArrowUpCircle size={13} aria-hidden="true" />
        <span className="tabular-nums">{tr(`Release ${status.latest.tag} verfügbar`, `Release ${status.latest.tag} available`, `Versión ${status.latest.tag} disponible`)}</span>
        <span className="hidden text-subtle xl:inline">{tr("(Update verfügbar)", "(Update available)", "(Actualización disponible)")}</span>
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={tr("Update verfügbar", "Update available", "Actualización disponible")}
        subtitle={tr(
          "Automatische Datenbanksicherung · Lokale Daten & Einstellungen bleiben erhalten",
          "Automatic database backup · Local data & settings preserved",
          "Copia de seguridad automática · Datos y ajustes locales conservados",
        )}
      >
        <ReleasePanel initial={status} notify={notify} />
      </Modal>
    </>
  );
}

type StepState = "done" | "active" | "pending";

function UpdateStep({ state, title, detail }: { state: StepState; title: string; detail?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center" aria-hidden="true">
        {state === "done" ? (
          <CheckCircle size={18} className="text-ok" />
        ) : state === "active" ? (
          <span className="text-accent"><Spinner size={15} /></span>
        ) : (
          <span className="h-3.5 w-3.5 rounded-full border-2 border-line-strong" />
        )}
      </span>
      <div className="min-w-0">
        <p className={cx("text-sm", state === "pending" ? "text-subtle" : "font-medium text-fg")}>{title}</p>
        {detail && <div className="mt-0.5 text-xs leading-relaxed text-muted">{detail}</div>}
      </div>
    </li>
  );
}

/**
 * Nicht schließbare Vollbild-Sperre während eines automatischen Release-Neustarts.
 *
 * Wartet, bis das Backend die Zielversion meldet (oder nach einem beobachteten Ausfall
 * wieder antwortet) und die Oberfläche selbst wieder HTTP 200 liefert - erst dann wird
 * neu geladen.  So läuft nie ein altes Client-Bundle gegen ein neues Backend.
 */
export function UpdaterLock() {
  const { tr } = useI18n();
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const [result, setResult] = useState<ReleaseApplyResult | null>(null);
  const [backendReady, setBackendReady] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    const onApplied = (event: Event) => {
      const detail = (event as CustomEvent<ReleaseApplyResult>).detail;
      if (detail && !detail.restart_required) setResult(detail);
    };
    window.addEventListener(RELEASE_APPLIED_EVENT, onApplied);
    return () => window.removeEventListener(RELEASE_APPLIED_EVENT, onApplied);
  }, []);

  // Sperre: alles außer der Sperre wird inert (auch später eingehängte Portale),
  // Escape und App-Kürzel kommen nicht durch, Tab bleibt im Dialog.
  useEffect(() => {
    if (!result) return;
    const panel = panelRef.current;
    const overlay = panel?.closest("[data-updater-lock]") ?? null;
    const lock = (node: Element) => {
      if (node !== overlay && !node.hasAttribute("inert")) node.setAttribute("inert", "");
    };
    Array.from(document.body.children).forEach(lock);
    document.getElementById("eca-app-shell")?.setAttribute("inert", "");
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
        if (node instanceof Element) lock(node);
      }));
    });
    observer.observe(document.body, { childList: true });

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") event.preventDefault();
      if (event.key === "Tab" && panel) {
        const focusables = Array.from(panel.querySelectorAll<HTMLElement>("button:not(:disabled)"));
        if (!focusables.length) {
          event.preventDefault();
          panel.focus();
        } else {
          const first = focusables[0];
          const last = focusables[focusables.length - 1];
          if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          } else if (!panel.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
          }
        }
      }
      event.stopImmediatePropagation();
    };
    window.addEventListener("keydown", onKey, true);
    panel?.focus();
    return () => {
      observer.disconnect();
      window.removeEventListener("keydown", onKey, true);
    };
  }, [result]);

  // Abfrage: zuerst Backend (Zielversion), danach die Oberfläche selbst (HTTP 200).
  useEffect(() => {
    if (!result) return;
    const target = result.to_tag.replace(/^v/, "");
    const started = Date.now();
    let cancelled = false;
    let sawBackendDown = false;
    let ready = false;
    let timer = 0;
    const tick = async () => {
      if (cancelled) return;
      setElapsed(Date.now() - started);
      if (!ready) {
        try {
          const health = await fetchHealth();
          if (health.version === target || sawBackendDown) {
            ready = true;
            setBackendReady(true);
          }
        } catch {
          sawBackendDown = true;
        }
      }
      if (ready) {
        try {
          const response = await fetch(window.location.origin, { cache: "no-store" });
          if (response.ok && !cancelled) {
            window.location.reload();
            return;
          }
        } catch {
          /* Oberfläche wird noch gebaut */
        }
      }
      if (Date.now() - started > UPDATE_FALLBACK_MS) setStalled(true);
      if (!cancelled) timer = window.setTimeout(() => void tick(), UPDATE_POLL_MS);
    };
    timer = window.setTimeout(() => void tick(), UPDATE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [result]);

  if (!result || typeof document === "undefined") return null;
  const version = result.to_tag;
  return createPortal(
    <div
      data-updater-lock=""
      className="anim-fade fixed inset-0 z-[200] flex items-center justify-center overflow-y-auto bg-[var(--backdrop)] p-4 backdrop-blur-md no-print"
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={-1}
        className="anim-panel w-full max-w-lg rounded-2xl border border-line bg-surface-solid shadow-2xl outline-none"
      >
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <ArrowUpCircle size={20} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold text-fg">
              {tr(`Update auf ${version} wird eingespielt`, `Installing update ${version}`, `Instalando la actualización ${version}`)}
            </h2>
            <p id={descId} className="mt-0.5 text-xs text-subtle">
              {tr(
                "Die Oberfläche ist gesperrt und lädt automatisch neu, sobald die neue Version bereit ist.",
                "The interface is locked and reloads automatically once the new version is ready.",
                "La interfaz está bloqueada y se recargará automáticamente cuando la nueva versión esté lista.",
              )}
            </p>
          </div>
        </div>

        <ol className="space-y-4 px-5 py-4" aria-live="polite">
          <UpdateStep
            state="done"
            title={tr(`Datenbank gesichert, Code auf ${version} aktualisiert`, `Database backed up, code updated to ${version}`, `Base de datos respaldada, código actualizado a ${version}`)}
            detail={result.database_backup ? <span className="[overflow-wrap:anywhere]">data/backups/{result.database_backup}</span> : undefined}
          />
          <UpdateStep
            state={backendReady ? "done" : "active"}
            title={tr("Server-Neustart und Production-Build der Oberfläche", "Server restart and production build of the interface", "Reinicio del servidor y compilación de la interfaz")}
            detail={tr(
              "Läuft im Hintergrund – beim ersten Build ca. 20–60 s. Bitte diesen Browser-Tab geöffnet lassen.",
              "Running in the background – the first build takes about 20–60 s. Please keep this browser tab open.",
              "Se ejecuta en segundo plano; la primera compilación tarda unos 20–60 s. Mantenga esta pestaña abierta.",
            )}
          />
          <UpdateStep
            state={backendReady ? "active" : "pending"}
            title={tr("Warten auf die neue Version", "Waiting for the new version", "Esperando la nueva versión")}
            detail={backendReady
              ? tr(`Backend meldet ${version} – Oberfläche wird geprüft …`, `Backend reports ${version} – checking the interface …`, `El backend informa ${version}; comprobando la interfaz …`)
              : tr("Backend (Port 8001) und Oberfläche (Port 3001) müssen beide antworten.", "Backend (port 8001) and interface (port 3001) must both respond.", "El backend (puerto 8001) y la interfaz (puerto 3001) deben responder.")}
          />
        </ol>

        {stalled && (
          <div className="mx-5 mb-4 flex gap-2.5 rounded-lg border border-warn-line bg-warn-soft p-3 text-xs leading-relaxed text-fg" role="status">
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            <div className="min-w-0 space-y-2">
              <p>
                {tr(
                  "Der Neustart dauert länger als erwartet. Falls die Oberfläche nicht zurückkommt: Stop_Compliance_Agent.bat und danach Start_Compliance_Agent.bat ausführen. Diese Seite prüft weiter und lädt von selbst neu.",
                  "The restart is taking longer than expected. If the interface does not come back: run Stop_Compliance_Agent.bat, then Start_Compliance_Agent.bat. This page keeps checking and reloads by itself.",
                  "El reinicio tarda más de lo esperado. Si la interfaz no vuelve: ejecute Stop_Compliance_Agent.bat y después Start_Compliance_Agent.bat. Esta página sigue comprobando y se recargará sola.",
                )}
              </p>
              <button type="button" className="btn" onClick={() => window.location.reload()}>
                <RefreshCw size={14} aria-hidden="true" /> {tr("Jetzt neu laden", "Reload now", "Recargar ahora")}
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3 text-xs text-subtle">
          <span>{tr("Lokale Daten und Einstellungen bleiben erhalten.", "Local data and settings are preserved.", "Los datos y ajustes locales se conservan.")}</span>
          <span className="tabular-nums" aria-label={tr("Vergangene Zeit", "Elapsed time", "Tiempo transcurrido")}>{formatElapsed(elapsed)}</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
