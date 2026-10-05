"use client";

import React from "react";
import type { HealthResponse, LedgerVerification, RuntimeSettings } from "../types/api";
import { cx, formatModel, PROVIDER_SHORT } from "../lib/format";
import { useTheme } from "./ThemeProvider";
import { Database, FileText, Lock, Moon, RefreshCw, Settings, ShieldAlert, ShieldCheck, Sun } from "./icons";
import { Spinner } from "./ui";

interface HeaderProps {
  health: HealthResponse | null;
  offline: boolean;
  apiBase: string;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  seeding: boolean;
  onSeed: () => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
}

/** Ergebnis von GET /api/audit/verify: Die Kette wird bei jedem Aktualisieren vollständig nachgerechnet. */
function LedgerBadge({ ledger }: { ledger: LedgerVerification }) {
  if (ledger.entries === 0) {
    return (
      <span className="chip border-line bg-surface-2 font-mono text-[10.5px] text-subtle" title="Noch keine Einträge im Prüfprotokoll">
        <ShieldCheck size={11} aria-hidden="true" /> Ledger leer
      </span>
    );
  }
  if (!ledger.valid) {
    return (
      <span
        role="status"
        className="chip border-bad-line bg-bad-soft font-mono text-[10.5px] text-bad"
        title={ledger.reason ?? "Hash-Kette gebrochen"}
      >
        <ShieldAlert size={11} aria-hidden="true" /> Hash-Kette gebrochen
        {ledger.broken_at_seq != null && <span className="opacity-80">· #{ledger.broken_at_seq}</span>}
      </span>
    );
  }
  return (
    <span
      className="chip border-ok-line bg-ok-soft font-mono text-[10.5px] text-ok"
      title={`${ledger.entries} Einträge vollständig nachgerechnet · Kopf-Hash ${ledger.head_hash.slice(0, 16)}…`}
    >
      <ShieldCheck size={11} aria-hidden="true" />
      <span className="md:hidden">Ledger intakt</span>
      <span className="hidden md:inline">Ledger integer · Hash-Kette intakt</span>
    </span>
  );
}

export function Header({ health, offline, apiBase, settings, ledger, seeding, onSeed, onRefresh, onOpenSettings }: HeaderProps) {
  const { theme, toggle } = useTheme();
  let port = "";
  try {
    port = new URL(apiBase).port || "80";
  } catch {
    port = "";
  }

  const mode = settings?.inference_mode ?? health?.inference?.mode ?? "local";
  const model = settings?.active_model ?? health?.inference?.model ?? "";
  const degraded = health?.status === "degraded";
  const pillTone = offline ? "bad" : degraded ? "warn" : "ok";
  const pillLabel = offline ? "API OFFLINE" : degraded ? "API EINGESCHRÄNKT" : "API ONLINE";
  const pillClasses = {
    ok: "border-ok-line bg-ok-soft text-ok",
    warn: "border-warn-line bg-warn-soft text-warn",
    bad: "border-bad-line bg-bad-soft text-bad",
  }[pillTone];
  const dotClasses = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad" }[pillTone];

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md no-print">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-line bg-accent-soft text-accent">
            <ShieldCheck size={18} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[15px] font-semibold tracking-tight text-fg">Enterprise Compliance Agent</h1>
              <span className="chip border-line bg-surface-2 font-mono text-[10.5px] text-muted">
                VO (EU) 2024/1689 · § 14 UStG
              </span>
            </div>
            <p className="truncate text-xs text-subtle">EU AI Act · DSGVO · E-Rechnung — revisionssichere Dokumentenprüfung</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cx("chip font-mono text-[10.5px]", pillClasses)}
            title={offline ? `Keine Verbindung zu ${apiBase}` : health?.ollama.detail ?? apiBase}
          >
            <span className={cx("h-1.5 w-1.5 rounded-full", dotClasses)} />
            {pillLabel}
            {port && <span className="opacity-70">| {port}</span>}
          </span>

          {ledger && !offline && <LedgerBadge ledger={ledger} />}

          {model && (
            <span
              className={cx(
                "chip font-mono text-[10.5px]",
                mode === "local" ? "border-ok-line bg-ok-soft text-ok" : "border-pii-line bg-pii-soft text-pii",
              )}
              title={mode === "local" ? "Lokale Inferenz – kein Dokumentinhalt verlässt den Rechner" : "Cloud-Inferenz über Privacy Gateway (Pseudonymisierung)"}
            >
              {mode === "local" ? <Database size={11} aria-hidden="true" /> : <Lock size={11} aria-hidden="true" />}
              {PROVIDER_SHORT[mode]} ({formatModel(model)})
            </span>
          )}

          <span className="mx-1 hidden h-5 w-px bg-line sm:block" />

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
          <button className="btn btn-icon" onClick={onRefresh} aria-label="Aktualisieren" title="Aktualisieren">
            <RefreshCw size={15} />
          </button>
          <button
            className="btn btn-icon"
            onClick={toggle}
            aria-label={theme === "dark" ? "Helles Design" : "Dunkles Design"}
            title={theme === "dark" ? "Helles Design" : "Dunkles Design"}
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button className="btn btn-icon" onClick={onOpenSettings} aria-label="Einstellungen" title="Einstellungen">
            <Settings size={15} />
          </button>
        </div>
      </div>
    </header>
  );
}
