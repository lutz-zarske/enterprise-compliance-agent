"use client";

import Image from "next/image";
import React, { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { HealthResponse, JobSnapshot, LedgerVerification, RuntimeSettings } from "../types/api";
import { getApiBase } from "../lib/api";
import { cx, formatModel, PROVIDER_NAMES } from "../lib/format";
import { useAnchoredStyle, useDismiss, usePopoverExclusive } from "../lib/popover";
import { HelpCircle, Moon, Settings, Sun, WifiOff } from "./icons";
import { JobMonitor, type FinishedJob } from "./JobMonitor";
import { Notifications } from "./Notifications";
import { OfflineBadge } from "./OfflineBadge";
import { GitSyncButton } from "./ReleaseAssistant";
import { SampleMenu } from "./SampleMenu";
import { useTheme } from "./ThemeProvider";
import { PillTabs, Tooltip } from "./ui";

/** Drei fokussierte Ansichten statt einer ueberfrachteten Einzelseite. */
export type View = "workspace" | "copilot" | "protocol";

/** Ein Wort je Bereich - in der Kapsel wie in der kompakten Leiste. */
export const VIEW_LABELS: Record<View, string> = {
  workspace: "Prüfung",
  copilot: "Copilot",
  protocol: "Protokoll",
};

type Notify = (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;

interface HeaderProps {
  view: View;
  onViewChange: (view: View) => void;
  health: HealthResponse | null;
  offline: boolean;
  settings: RuntimeSettings | null;
  ledger: LedgerVerification | null;
  ruleset: string | null;
  seeding: boolean;
  jobs: JobSnapshot[];
  finished: FinishedJob | null;
  copilotBusy: boolean;
  onCancelJob: (jobId: string) => Promise<void>;
  onSeed: (file?: string) => void;
  onOpenSettings: () => void;
  onStartTour: () => void;
  onChanged: () => void;
  notify: Notify;
}

/**
 * Kein dauerhaftes Versions-Badge: Ein Klick auf Logo oder Schriftzug zeigt Version
 * und Regelwerk in einem schlanken Popover (Escape oder Klick daneben schliesst es).
 */
function LogoVersion({ version, ruleset }: { version: string | null; ruleset: string | null }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "logo-version");
  useDismiss(open, close, [ref, menuRef]);
  const style = useAnchoredStyle(open, ref, { width: 288, maxHeight: 280 });
  return (
    <div ref={ref} className="relative flex min-w-0 items-center">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Enterprise Compliance Agent – Version anzeigen"
        className="flex min-w-0 items-center gap-2.5 rounded-lg px-1 py-0.5 transition-colors duration-150 hover:bg-surface-hover"
      >
        {/* Freigestellt wie im Kaltstart-Splash; nur im Dark Mode sitzt der Schild auf einer dunklen Kachel. */}
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg p-1 dark:border dark:border-white/10 dark:bg-[#0b0e15]">
          <Image src="/compliance-logo-transparent.png" alt="" width={24} height={24} priority unoptimized className="h-full w-full object-contain" />
        </span>
        <span className="truncate text-[15px] font-semibold tracking-tight text-fg">Enterprise Compliance Agent</span>
      </button>
      {open &&
        createPortal(
          <div ref={menuRef} role="dialog" aria-label="Version" style={style} className="glass-menu z-[70] p-3 text-sm">
            <p className="font-semibold text-fg">Enterprise Compliance Agent</p>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-subtle">Version</dt>
              <dd className="tabular-nums text-fg">{version ? `v${version}` : "–"}</dd>
              <dt className="text-subtle">Regelwerk</dt>
              <dd className="tabular-nums text-fg">{ruleset ?? "–"}</dd>
              <dt className="text-subtle">Backend</dt>
              <dd className="truncate text-fg">{getApiBase()}</dd>
            </dl>
            <p className="mt-2 text-xs leading-relaxed text-subtle">Technische Vorprüfung – keine Rechts- oder Steuerberatung.</p>
          </div>,
          document.body,
        )}
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  return (
    <Tooltip content="Farbschema wechseln (Hell / Dunkel; System unter Einstellungen › Darstellung)" side="bottom" align="right">
      <button type="button" className="btn btn-ghost btn-icon" onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "Helles Farbschema" : "Dunkles Farbschema"}>
        {dark ? <Moon size={15} aria-hidden="true" /> : <Sun size={15} aria-hidden="true" />}
      </button>
    </Tooltip>
  );
}

/** Modellname und Statuspunkt - ohne dauerhafte Pille; die Kaskade steht im Tooltip. */
function ModelStatus({ health, settings }: { health: HealthResponse | null; settings: RuntimeSettings | null }) {
  const mode = settings?.inference_mode ?? health?.inference?.mode;
  const model = settings?.active_model ?? health?.inference?.model;
  if (!mode || !model) return null;
  const local = mode === "local";
  const ready = local ? health?.ollama.status === "ok" : Boolean(health?.inference?.configured);
  // Ein Wort, das zum Statuspunkt passt - nie "Lokal" neben einem Hinweis "Lokale KI aus".
  const state = local
    ? ready ? "Lokal" : health?.ollama.status === "degraded" ? "Modell fehlt" : "Aus"
    : ready ? "Cloud" : "Kein Key";
  const chain = settings?.chain ?? [];
  return (
    <Tooltip
      side="bottom"
      align="right"
      content={
        <>
          <span className="block font-semibold">{PROVIDER_NAMES[mode]} · {formatModel(model)}</span>
          {chain.length > 1 && (
            <span className="mt-1 block text-subtle">
              Kaskade: {chain.map((stage) => formatModel(stage.model)).join(" → ")} → Regelwerk
            </span>
          )}
          <span className="mt-1 block text-subtle">
            {local
              ? "Lokale Inferenz – kein Dokumentinhalt verlässt den Rechner."
              : "Cloud-Inferenz über das Privacy Gateway (Pseudonymisierung nach Art. 4 Nr. 5 DSGVO)."}
          </span>
          {!ready && (
            <span className="mt-1 block text-warn">
              {local
                ? "Nicht bereit – bis zum Start schließt das Regelwerk Prüfungen gekennzeichnet ab."
                : "Kein API-Key hinterlegt – Einstellungen › KI-Modelle."}
            </span>
          )}
        </>
      }
    >
      <span tabIndex={0} className="hidden cursor-help items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-1 text-xs text-muted xl:inline-flex">
        {formatModel(model)}
        <span className="text-subtle">· {state}</span>
        <span className={cx("h-2 w-2 rounded-full", ready ? "bg-ok" : "bg-subtle")} aria-label={ready ? "bereit" : "nicht bereit"} />
      </span>
    </Tooltip>
  );
}

export function Header(props: HeaderProps) {
  const { view, onViewChange, health, offline, settings, ledger, seeding, jobs, finished, copilotBusy } = props;
  const online = !offline && Boolean(health);
  const analysing = jobs.some((job) => job.status === "running" || job.status === "queued");

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-[var(--header-bg)] backdrop-blur-xl backdrop-saturate-150 no-print">
      {/* Die Bereiche bleiben mittig, solange Platz ist; wird die rechte Gruppe breiter (Job-Monitor,
          Hinweise), gibt die linke Spalte nach - die Kapsel ueberdeckt nie ein Bedienelement. */}
      <div className="mx-auto grid h-14 w-full max-w-[1920px] grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto_minmax(max-content,1fr)] 2xl:max-w-[2400px] 2xl:px-10">
        <LogoVersion version={health?.version ?? null} ruleset={props.ruleset} />

        <nav aria-label="Bereiche" className="order-3 col-span-2 hidden min-w-0 justify-center lg:order-none lg:col-span-1 lg:flex">
          <PillTabs<View>
            ariaLabel="Bereiche"
            className="kopf-kapsel"
            value={view}
            onChange={onViewChange}
            items={[
              { key: "workspace", label: VIEW_LABELS.workspace, dot: analysing && view !== "workspace" ? "live" : null },
              { key: "copilot", label: VIEW_LABELS.copilot, dot: copilotBusy && view !== "copilot" ? "live" : null },
              { key: "protocol", label: VIEW_LABELS.protocol, dot: ledger && !ledger.valid ? "warn" : null },
            ]}
          />
        </nav>

        <div className="flex min-w-0 items-center justify-end gap-1.5">
          <JobMonitor jobs={jobs} finished={finished} onCancel={props.onCancelJob} />
          <Notifications
            health={health}
            settings={settings}
            ledger={ledger}
            online={online}
            onOpenSettings={props.onOpenSettings}
            onChanged={props.onChanged}
            notify={props.notify}
          />
          <OfflineBadge />
          {offline && (
            <Tooltip side="bottom" align="right" content={`Keine Verbindung zu ${getApiBase()} – erneuter Versuch alle 10 s.`}>
              <span tabIndex={0} role="status" className="chip cursor-help border-bad-line bg-bad-soft py-1 text-bad">
                <WifiOff size={12} aria-hidden="true" /> Backend offline
              </span>
            </Tooltip>
          )}
          <GitSyncButton online={online} notify={props.notify} />
          <SampleMenu busy={seeding} disabled={offline} onLoad={props.onSeed} />
          <ModelStatus health={health} settings={settings} />
          <Tooltip content="Interaktive Tour erneut starten" side="bottom" align="right">
            <button type="button" className="btn btn-ghost btn-icon" onClick={props.onStartTour} aria-label="Hilfe und Tour">
              <HelpCircle size={15} aria-hidden="true" />
            </button>
          </Tooltip>
          <ThemeToggle />
          <Tooltip content="Einstellungen" side="bottom" align="right">
            <button type="button" className="btn btn-ghost btn-icon" onClick={props.onOpenSettings} aria-label="Einstellungen">
              <Settings size={15} aria-hidden="true" />
            </button>
          </Tooltip>
        </div>
      </div>
      {/* Schmale Fenster: Bereiche als zweite Zeile. */}
      <nav aria-label="Bereiche (kompakt)" className="flex justify-center border-t border-line px-4 py-2 lg:hidden">
        <PillTabs<View>
          size="sm"
          value={view}
          onChange={onViewChange}
          items={[
            { key: "workspace", label: VIEW_LABELS.workspace },
            { key: "copilot", label: VIEW_LABELS.copilot },
            { key: "protocol", label: VIEW_LABELS.protocol },
          ]}
        />
      </nav>
    </header>
  );
}
