"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError, fetchHealth } from "../lib/api";
import { cx } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { ReleaseApplyResult, ReleaseStatus } from "../types/api";
import { ArrowUpCircle, CheckCircle, RefreshCw, ShieldAlert, ShieldCheck } from "./icons";
import { HashBadge, Modal, Spinner } from "./ui";

/**
 * Release pruefen und per Klick einspielen. Das Backend prueft laufende Analysen,
 * legt automatisch eine Sicherungskopie von ``data/agent.db`` an und protokolliert
 * den Versionswechsel im Ledger; lokale Daten und Einstellungen bleiben erhalten.
 */
export function ReleasePanel({ initial, onApplied, notify }: {
  initial?: ReleaseStatus | null;
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
    try {
      setStatus(await api.release(true));
    } catch (err) {
      notify("bad", tr("Update-Prüfung fehlgeschlagen", "Update check failed", "Error al buscar actualizaciones"), err instanceof ApiError ? td(err.message) : String(err));
    } finally {
      setChecking(false);
    }
  }, [notify, td, tr]);

  useEffect(() => {
    if (!initial) void check();
  }, [initial, check]);

  async function apply() {
    const latest = status?.latest;
    if (!latest) return;
    setBusy(true);
    try {
      const result = await api.applyRelease(latest.tag, latest.commit, "System");
      setDone(result);
      notify("ok", tr(`Release ${result.to_tag} installiert`, `Release ${result.to_tag} installed`, `Versión ${result.to_tag} instalada`), td(result.message));
      onApplied?.(result);
      if (!result.restart_required) {
        window.setTimeout(() => {
          const poll = window.setInterval(() => {
            fetchHealth().then(() => {
              window.clearInterval(poll);
              window.location.reload();
            }).catch(() => undefined);
          }, 1500);
        }, 2500);
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
  const signatureMap: Record<string, { label: string; tone: string; icon: React.ReactNode }> = {
    valid: { label: tr("Tag-Signatur gültig", "Valid tag signature", "Firma válida"), tone: "border-ok-line bg-ok-soft text-ok", icon: <ShieldCheck size={12} aria-hidden="true" /> },
    invalid: { label: tr("Tag-Signatur ungültig", "Invalid tag signature", "Firma inválida"), tone: "border-bad-line bg-bad-soft text-bad", icon: <ShieldAlert size={12} aria-hidden="true" /> },
  };
  const signature = latest ? signatureMap[latest.signature] : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg">
          {tr("Installiert:", "Installed:", "Instalado:")} <span className="tabular-nums">v{status?.current_version ?? "…"}</span>
          {status?.current_commit && <span className="ml-2 text-xs tabular-nums text-subtle">{status.current_commit.slice(0, 10)}</span>}
        </p>
        <button className="btn" onClick={() => void check()} disabled={checking || busy}>
          {checking ? <Spinner size={13} /> : <RefreshCw size={14} aria-hidden="true" />} {tr("Nach Updates suchen", "Check for updates", "Buscar actualizaciones")}
        </button>
      </div>

      {status?.message && <p className="text-xs text-subtle">{td(status.message)}</p>}
      {status && status.git && !latest && (
        <p className="flex items-center gap-2 text-xs text-ok">
          <CheckCircle size={14} aria-hidden="true" /> {tr("Aktuellste Version installiert.", "Latest version is installed.", "Última versión instalada.")}
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
          {latest.message && <p className="text-xs text-muted">{td(latest.message)}</p>}
          <HashBadge value={latest.commit} label="Commit" />
          {latest.changelog.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-subtle hover:text-fg">
                {tr("Änderungen", "Changelog", "Cambios")} ({latest.changelog.length})
              </summary>
              <ul className="scroll-area mt-2 max-h-40 space-y-1 pr-2 font-mono text-subtle">
                {latest.changelog.map((line) => <li key={line} className="[overflow-wrap:anywhere]">{line}</li>)}
              </ul>
            </details>
          )}
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
              "Lokale Daten, Einstellungen, API-Keys und geprüfte Belege (data/agent.db, .env) bleiben vollständig erhalten. Vor dem Update legt das System automatisch eine Sicherungskopie unter data/backups/ an.",
              "Local data, settings, API keys and audited documents (data/agent.db, .env) are preserved. A backup is automatically created in data/backups/ before updating.",
              "Los datos locales, ajustes, claves API y documentos (data/agent.db, .env) se conservan. Se crea una copia en data/backups/ automáticamente.",
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
        <div className="rounded-lg border border-ok-line bg-ok-soft p-3 text-xs text-ok">
          <p className="font-semibold">
            {tr(`${done.to_tag} installiert`, `${done.to_tag} installed`, `${done.to_tag} instalado`)}
            {done.database_backup ? ` · ${tr("Sicherung", "Backup", "Copia")} ${done.database_backup}` : ""}
          </p>
          <p className="mt-1 text-fg">{td(done.message)}</p>
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
