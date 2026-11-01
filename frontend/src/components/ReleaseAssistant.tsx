"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { cx } from "../lib/format";
import type { ReleaseApplyResult, ReleaseStatus } from "../types/api";
import { AlertTriangle, ArrowUpCircle, CheckCircle, RefreshCw, ShieldAlert, ShieldCheck } from "./icons";
import { HashBadge, Modal, Spinner } from "./ui";

const SIGNATURE: Record<string, { label: string; tone: string; icon: React.ReactNode }> = {
  valid: { label: "Tag-Signatur gültig", tone: "border-ok-line bg-ok-soft text-ok", icon: <ShieldCheck size={12} aria-hidden="true" /> },
  invalid: { label: "Tag-Signatur ungültig", tone: "border-bad-line bg-bad-soft text-bad", icon: <ShieldAlert size={12} aria-hidden="true" /> },
  unsigned: { label: "Tag unsigniert – Commit-Hash prüfen", tone: "border-warn-line bg-warn-soft text-warn", icon: <AlertTriangle size={12} aria-hidden="true" /> },
};

/**
 * Release pruefen und kontrolliert einspielen. Kein Auto-Pulling: Das Update
 * verlangt Namen und die ausdrueckliche Bestaetigung des angezeigten Commit-Hashes;
 * das Backend prueft Fast-Forward, laufende Analysen und sichert ``data/agent.db``.
 */
export function ReleasePanel({ initial, onApplied, notify }: {
  initial?: ReleaseStatus | null;
  onApplied?: (result: ReleaseApplyResult) => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const [status, setStatus] = useState<ReleaseStatus | null>(initial ?? null);
  const [checking, setChecking] = useState(false);
  const [admin, setAdmin] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ReleaseApplyResult | null>(null);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      setStatus(await api.release(true));
    } catch (err) {
      notify("bad", "Update-Prüfung fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  }, [notify]);

  useEffect(() => {
    if (!initial) void check();
  }, [initial, check]);

  async function apply() {
    const latest = status?.latest;
    if (!latest) return;
    setBusy(true);
    try {
      const result = await api.applyRelease(latest.tag, latest.commit, admin.trim());
      setDone(result);
      notify("ok", `Release ${result.to_tag} eingespielt`, "Datenbank gesichert, Wechsel im Ledger verankert. Bitte neu starten.");
      onApplied?.(result);
    } catch (err) {
      const error = err instanceof ApiError ? err : null;
      notify("bad", "Update abgelehnt", error ? `${error.message}` : String(err));
    } finally {
      setBusy(false);
    }
  }

  const latest = status?.latest;
  const blocked = Boolean(status?.dirty || (latest && (!latest.fast_forward || latest.signature === "invalid")));
  const signature = latest ? SIGNATURE[latest.signature] : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg">
          Installiert: <span className="font-mono tabular-nums">v{status?.current_version ?? "…"}</span>
          {status?.current_commit && <span className="ml-2 font-mono text-xs tabular-nums text-subtle">{status.current_commit.slice(0, 10)}</span>}
        </p>
        <button className="btn" onClick={() => void check()} disabled={checking || busy}>
          {checking ? <Spinner size={13} /> : <RefreshCw size={14} aria-hidden="true" />} Nach Updates suchen
        </button>
      </div>

      {status?.message && <p className="text-xs text-subtle">{status.message}</p>}
      {status && status.git && !latest && <p className="flex items-center gap-2 text-xs text-ok"><CheckCircle size={14} aria-hidden="true" /> Aktuellste Version installiert.</p>}

      {latest && !done && (
        <div className="space-y-3 rounded-lg border border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <ArrowUpCircle size={16} aria-hidden="true" className="text-ok" />
            <span className="text-sm font-semibold text-fg">Release {latest.tag} verfügbar</span>
            {signature && <span className={cx("chip", signature.tone)}>{signature.icon}{signature.label}</span>}
          </div>
          {latest.message && <p className="text-xs text-muted">{latest.message}</p>}
          <HashBadge value={latest.commit} label="Commit" />
          {latest.changelog.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-subtle hover:text-fg">Änderungen ({latest.changelog.length})</summary>
              <ul className="scroll-area mt-2 max-h-40 space-y-1 pr-2 font-mono text-subtle">
                {latest.changelog.map((line) => <li key={line} className="[overflow-wrap:anywhere]">{line}</li>)}
              </ul>
            </details>
          )}
          {status?.dirty && <p className="text-xs text-bad">Lokale Änderungen im Arbeitsverzeichnis – Update gesperrt.</p>}
          {!latest.fast_forward && <p className="text-xs text-bad">Lokaler Stand ist abgezweigt – kein Fast-Forward möglich.</p>}
          <label className="block">
            <span className="label-caps">Freigabe durch</span>
            <input
              className="input mt-1"
              name="release-admin"
              autoComplete="off"
              value={admin}
              onChange={(event) => setAdmin(event.target.value)}
              placeholder="Name oder Kürzel der Administration eingeben…"
            />
          </label>
          <label className="flex items-start gap-2 text-xs text-muted">
            <input type="checkbox" className="mt-0.5 accent-[var(--accent)]" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            Commit-Hash {latest.commit.slice(0, 10)}… mit der Freigabe abgeglichen. Vor dem Wechsel wird data/agent.db gesichert; laufende Analysen sperren das Update.
          </label>
          <div className="flex justify-end">
            <button className="btn btn-primary" onClick={() => void apply()} disabled={busy || blocked || !confirmed || admin.trim().length < 2}>
              {busy && <Spinner size={13} />} Update einspielen
            </button>
          </div>
        </div>
      )}

      {done && (
        <div className="rounded-lg border border-ok-line bg-ok-soft p-3 text-xs text-ok">
          <p className="font-semibold">{done.to_tag} eingespielt{done.database_backup ? ` · Sicherung ${done.database_backup}` : ""}</p>
          <p className="mt-1 text-fg">{done.message}</p>
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
        title="Neue Version verfügbar – Änderungen und Signatur prüfen"
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-ok-line bg-ok-soft px-2.5 py-1 text-xs font-medium text-ok transition-colors duration-150 hover:border-ok"
      >
        <ArrowUpCircle size={13} aria-hidden="true" />
        <span className="tabular-nums">Release {status.latest.tag} verfügbar</span>
        <span className="hidden text-subtle xl:inline">(Changelog prüfen)</span>
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="Release-Assistent" subtitle="Signierte Release-Tags · Fast-Forward · Datenbanksicherung · Ledger-Eintrag">
        <ReleasePanel initial={status} notify={notify} />
      </Modal>
    </>
  );
}
