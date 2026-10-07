"use client";

import React from "react";
import type { HealthResponse, LedgerVerification, RuntimeSettings } from "../types/api";
import { getApiBase } from "../lib/api";
import { cx, formatModel, PROVIDER_NAMES } from "../lib/format";
import { Database, FileText, Lock, Settings, ShieldCheck } from "./icons";
import { Spinner, Tooltip } from "./ui";

interface HeaderProps {
  health: HealthResponse | null;
  offline: boolean;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  seeding: boolean;
  onSeed: () => void;
  onOpenSettings: () => void;
}

type StatusTone = "ok" | "warn" | "bad" | "neutral";

const DOT: Record<StatusTone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  neutral: "text-subtle",
};

/** Ein ruhiger Betriebszustand statt Telemetrie: Details stehen im Tooltip. */
function systemStatus(health: HealthResponse | null, offline: boolean, ledger: LedgerVerification | null): {
  tone: StatusTone;
  label: string;
  detail: React.ReactNode;
} {
  if (offline) {
    return {
      tone: "bad",
      label: "Offline",
      detail: `Keine Verbindung zu ${getApiBase()} – erneuter Versuch alle 10 s.`,
    };
  }
  if (!health) return { tone: "neutral", label: "Verbinde…", detail: "Backend wird gesucht." };
  if (ledger && !ledger.valid) {
    return {
      tone: "bad",
      label: "Ledger-Befund",
      detail: (
        <>
          <span className="block font-semibold text-bad">Hash-Kette gebrochen{ledger.broken_at_seq != null ? ` bei #${ledger.broken_at_seq}` : ""}</span>
          <span className="mt-0.5 block text-subtle">{ledger.reason ?? "Ein Eintrag passt nicht zur Kette."}</span>
        </>
      ),
    };
  }
  const ledgerLine = !ledger ? (
    "Ledger-Prüfung nicht verfügbar."
  ) : ledger.entries === 0 ? (
    "Prüfprotokoll noch leer."
  ) : (
    <>
      Hash-Kette intakt: <span className="font-mono tabular-nums">{ledger.entries}</span> Einträge vollständig nachgerechnet,
      davon <span className="font-mono tabular-nums">{ledger.signed_entries}</span> Ed25519-signiert.
      <span className="mt-1 block font-mono tabular-nums text-subtle">Kopf-Hash {ledger.head_hash.slice(0, 16)}…</span>
    </>
  );
  if (health.status === "degraded") {
    return {
      tone: "warn",
      label: "Eingeschränkt",
      detail: (
        <>
          <span className="block">{health.ollama.detail ?? health.database.detail ?? "Eine Abhängigkeit antwortet nicht."}</span>
          <span className="mt-1 block text-subtle">{ledgerLine}</span>
        </>
      ),
    };
  }
  return { tone: "ok", label: "Betriebsbereit", detail: ledgerLine };
}

export function Header({ health, offline, settings, ledger, seeding, onSeed, onOpenSettings }: HeaderProps) {
  const mode = settings?.inference_mode ?? health?.inference?.mode ?? "local";
  const model = settings?.active_model ?? health?.inference?.model ?? "";
  const local = mode === "local";
  const status = systemStatus(health, offline, ledger);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-[var(--header-bg)] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-xl no-print">
      <div className="mx-auto grid w-full max-w-[1920px] grid-cols-[1fr_auto] items-center gap-3 px-4 py-2.5 sm:grid-cols-[1fr_auto_1fr] sm:px-6 2xl:max-w-[2400px] 2xl:px-10">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-accent-line bg-accent-soft text-accent">
            <ShieldCheck size={17} aria-hidden="true" />
          </div>
          <h1 className="truncate text-[15px] font-semibold tracking-tight text-fg" title="Enterprise Compliance Agent">
            Compliance Agent
          </h1>
          {health?.version && (
            <span className="chip border-line bg-surface-2 font-mono font-medium tabular-nums text-subtle">v{health.version}</span>
          )}
        </div>

        <div className="hidden justify-center sm:flex">
          <Tooltip content={status.detail} side="bottom" align="center">
            <span
              tabIndex={0}
              role="status"
              className="inline-flex cursor-help items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium text-muted outline-none transition-colors duration-150 hover:bg-surface-2 focus-visible:bg-surface-2"
            >
              <span className={cx("relative inline-flex h-2 w-2", DOT[status.tone])} aria-hidden="true">
                {status.tone === "ok" && <span className="status-pulse" />}
                <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
              </span>
              {status.label}
            </span>
          </Tooltip>
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            className="btn"
            onClick={onSeed}
            disabled={offline || seeding}
            aria-label="Musterdaten laden"
            title="Standardisierte Prüfbelege laden (§ 14 UStG, Steuerfalle, EU AI Act, ZUGFeRD-E-Rechnung) – funktioniert ohne KI-Modell"
          >
            {seeding ? <Spinner size={13} /> : <FileText size={14} aria-hidden="true" />}
            <span className="hidden md:inline">Musterdaten laden</span>
          </button>

          {model && (
            <Tooltip
              side="bottom"
              align="right"
              content={
                <>
                  <span className="block font-semibold">{PROVIDER_NAMES[mode]}</span>
                  <span className="block font-mono text-subtle">{model}</span>
                  <span className="mt-1 block text-subtle">
                    {local
                      ? "Lokale Inferenz – kein Dokumentinhalt verlässt den Rechner."
                      : "Cloud-Inferenz über das Privacy Gateway (Pseudonymisierung nach Art. 4 Nr. 5 DSGVO)."}
                  </span>
                </>
              }
            >
              <span
                tabIndex={0}
                className={cx("chip cursor-help py-1", local ? "border-ok-line bg-ok-soft text-ok" : "border-pii-line bg-pii-soft text-pii")}
              >
                {local ? <Database size={12} aria-hidden="true" /> : <Lock size={12} aria-hidden="true" />}
                {local ? "Lokal" : "Cloud"}
                <span className="hidden font-mono font-medium opacity-80 2xl:inline">· {formatModel(model)}</span>
              </span>
            </Tooltip>
          )}

          <button className="btn btn-icon" onClick={onOpenSettings} aria-label="Einstellungen" title="Einstellungen">
            <Settings size={15} />
          </button>
        </div>
      </div>
    </header>
  );
}
