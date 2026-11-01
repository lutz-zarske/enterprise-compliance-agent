"use client";

import Image from "next/image";
import React from "react";
import type { HealthResponse, LedgerVerification, RuntimeSettings } from "../types/api";
import { getApiBase } from "../lib/api";
import { cx, formatModel, PROVIDER_NAMES } from "../lib/format";
import { AlertTriangle, Database, HelpCircle, Lock, Moon, Settings, ShieldAlert, Sun, WifiOff } from "./icons";
import { GitSyncButton } from "./ReleaseAssistant";
import { SampleMenu } from "./SampleMenu";
import { useTheme } from "./ThemeProvider";
import { Tooltip } from "./ui";

interface HeaderProps {
  health: HealthResponse | null;
  offline: boolean;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  seeding: boolean;
  /** Analyse laeuft gerade (dezenter Puls statt Dauer-Statuspille). */
  busy: boolean;
  onSeed: (file?: string) => void;
  onOpenSettings: () => void;
  onStartTour: () => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}

/**
 * Status nur, wenn es etwas zu sagen gibt: laufende Analyse, Warnung oder
 * Offline. Im Normalbetrieb bleibt die Kopfzeile ruhig.
 */
function StatusSignal({ health, offline, ledger, busy }: Pick<HeaderProps, "health" | "offline" | "ledger" | "busy">) {
  if (offline) {
    return (
      <Tooltip content={`Keine Verbindung zu ${getApiBase()} – erneuter Versuch alle 10 s.`} side="bottom">
        <span tabIndex={0} role="status" className="chip cursor-help border-bad-line bg-bad-soft text-bad">
          <WifiOff size={12} aria-hidden="true" /> Offline
        </span>
      </Tooltip>
    );
  }
  if (ledger && !ledger.valid) {
    return (
      <Tooltip
        side="bottom"
        content={
          <>
            <span className="block font-semibold text-bad">Hash-Kette gebrochen{ledger.broken_at_seq != null ? ` bei #${ledger.broken_at_seq}` : ""}</span>
            <span className="mt-0.5 block text-subtle">{ledger.reason ?? "Ein Eintrag passt nicht zur Kette."}</span>
          </>
        }
      >
        <span tabIndex={0} role="status" className="chip cursor-help border-bad-line bg-bad-soft text-bad">
          <ShieldAlert size={12} aria-hidden="true" /> Ledger-Befund
        </span>
      </Tooltip>
    );
  }
  if (health?.status === "degraded") {
    return (
      <Tooltip side="bottom" content={health.ollama.detail ?? health.database.detail ?? "Eine Abhängigkeit antwortet nicht."}>
        <span tabIndex={0} role="status" className="chip cursor-help border-warn-line bg-warn-soft text-warn">
          <AlertTriangle size={12} aria-hidden="true" /> Eingeschränkt
        </span>
      </Tooltip>
    );
  }
  if (busy) {
    return (
      <span role="status" className="inline-flex items-center gap-2 text-xs font-medium text-accent">
        <span className="relative inline-flex h-2 w-2" aria-hidden="true">
          <span className="status-pulse" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
        </span>
        <span className="hidden sm:inline">Analyse läuft</span>
      </span>
    );
  }
  return null;
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  return (
    <Tooltip content="Farbschema wechseln: Hell / Dunkel" side="bottom" align="right">
      <button
        type="button"
        className="btn btn-icon"
        onClick={() => setTheme(dark ? "light" : "dark")}
        aria-label={dark ? "Helles Farbschema" : "Dunkles Farbschema"}
      >
        <span className="relative inline-flex h-[15px] w-[15px]">
          <Sun
            size={15}
            aria-hidden="true"
            className={cx("absolute inset-0 transition-[opacity,transform] duration-200 ease-out", dark ? "rotate-90 scale-75 opacity-0" : "opacity-100")}
          />
          <Moon
            size={15}
            aria-hidden="true"
            className={cx("absolute inset-0 transition-[opacity,transform] duration-200 ease-out", dark ? "opacity-100" : "-rotate-90 scale-75 opacity-0")}
          />
        </span>
      </button>
    </Tooltip>
  );
}

export function Header({ health, offline, settings, ledger, seeding, busy, onSeed, onOpenSettings, onStartTour, notify }: HeaderProps) {
  const mode = settings?.inference_mode ?? health?.inference?.mode ?? "local";
  const model = settings?.active_model ?? health?.inference?.model ?? "";
  const local = mode === "local";

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-[var(--header-bg)] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-xl backdrop-saturate-150 no-print">
      <div className="mx-auto flex w-full max-w-[1920px] items-center gap-3 px-4 py-2.5 sm:px-6 2xl:max-w-[2400px] 2xl:px-10">
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <Image src="/compliance-logo.png" alt="" width={32} height={32} priority unoptimized className="h-8 w-8 shrink-0 rounded-lg" />
          <h1 className="truncate text-[15px] font-semibold tracking-tight text-fg" title="Enterprise Compliance Agent">
            Compliance Agent
          </h1>
          <StatusSignal health={health} offline={offline} ledger={ledger} busy={busy} />
        </div>

        <div className="flex items-center justify-end gap-2">
          <GitSyncButton online={!offline && Boolean(health)} notify={notify} />
          <SampleMenu busy={seeding} disabled={offline} onLoad={onSeed} />

          {model && (
            <Tooltip
              side="bottom"
              align="right"
              content={
                <>
                  <span className="block font-semibold">{PROVIDER_NAMES[mode]}</span>
                  <span className="block font-mono text-subtle">{model}</span>
                  {settings?.fallbacks?.length ? (
                    <span className="mt-1 block text-subtle">
                      Ausweich-Kaskade: {settings.fallbacks.map((fallback) => PROVIDER_NAMES[fallback]).join(" → ")}
                    </span>
                  ) : null}
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

          <Tooltip content="Interaktive Tour erneut starten" side="bottom" align="right">
            <button type="button" className="btn btn-icon" onClick={onStartTour} aria-label="Hilfe und Tour">
              <HelpCircle size={15} aria-hidden="true" />
            </button>
          </Tooltip>
          <ThemeToggle />
          <Tooltip content="Einstellungen" side="bottom" align="right">
            <button type="button" className="btn btn-icon" onClick={onOpenSettings} aria-label="Einstellungen">
              <Settings size={15} aria-hidden="true" />
            </button>
          </Tooltip>
        </div>
      </div>
    </header>
  );
}
