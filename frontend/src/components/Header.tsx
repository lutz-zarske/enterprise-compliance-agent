"use client";

import React, { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { HealthResponse, JobSnapshot, LedgerVerification, RuntimeSettings } from "../types/api";
import { getApiBase } from "../lib/api";
import { cx, formatModel, providerDisplayName } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useAnchoredStyle, useDismiss, usePopoverExclusive } from "../lib/popover";
import { BrandMark } from "./BrandMark";
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
  const { tr } = useI18n();
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
        aria-label={tr("Enterprise Compliance Agent – Version anzeigen", "Enterprise Compliance Agent – show version", "Enterprise Compliance Agent – ver versión")}
        className="flex min-w-0 items-center gap-2.5 rounded-lg px-1 py-0.5 transition-colors duration-150 hover:bg-surface-hover"
      >
        <BrandMark size={30} className="shrink-0" />
        <span className="truncate text-[15px] font-semibold tracking-tight text-fg">Enterprise Compliance Agent</span>
      </button>
      {open &&
        createPortal(
          <div ref={menuRef} role="dialog" aria-label={tr("Version", "Version", "Versión")} style={style} className="glass-menu z-[70] p-3 text-sm">
            <p className="font-semibold text-fg">Enterprise Compliance Agent</p>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-subtle">{tr("Version", "Version", "Versión")}</dt>
              <dd className="tabular-nums text-fg">{version ? `v${version}` : "–"}</dd>
              <dt className="text-subtle">{tr("Regelwerk", "Ruleset", "Reglamento")}</dt>
              <dd className="tabular-nums text-fg">{ruleset ?? "–"}</dd>
              <dt className="text-subtle">Backend</dt>
              <dd className="truncate text-fg">{getApiBase()}</dd>
            </dl>
            <p className="mt-2 text-xs leading-relaxed text-subtle">
              {tr("Technische Vorprüfung – keine Rechts- oder Steuerberatung.", "Technical pre-check only – no legal or tax advice.", "Pre-verificación técnica – no constituye asesoramiento legal ni fiscal.")}
            </p>
          </div>,
          document.body,
        )}
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const { tr } = useI18n();
  const dark = theme === "dark";
  return (
    <Tooltip
      content={tr(
        "Farbschema wechseln (Hell / Dunkel; System unter Einstellungen › Darstellung)",
        "Switch color scheme (Light / Dark; System under Settings › Appearance)",
        "Cambiar tema (Claro / Oscuro; Sistema en Ajustes › Apariencia)",
      )}
      side="bottom"
      align="right"
    >
      <button
        type="button"
        className="btn btn-ghost btn-icon"
        onClick={() => setTheme(dark ? "light" : "dark")}
        aria-label={dark ? tr("Helles Farbschema", "Light color scheme", "Tema claro") : tr("Dunkles Farbschema", "Dark color scheme", "Tema oscuro")}
      >
        {dark ? <Moon size={15} aria-hidden="true" /> : <Sun size={15} aria-hidden="true" />}
      </button>
    </Tooltip>
  );
}

/** Modellname und Statuspunkt - ohne dauerhafte Pille; die Kaskade steht im Tooltip. */
function ModelStatus({ health, settings }: { health: HealthResponse | null; settings: RuntimeSettings | null }) {
  const { tr } = useI18n();
  const mode = settings?.inference_mode ?? health?.inference?.mode;
  const model = settings?.active_model ?? health?.inference?.model;
  if (!mode || !model) return null;
  const local = mode === "local";
  const ready = local ? health?.ollama.status === "ok" : Boolean(health?.inference?.configured);
  const state = local
    ? ready
      ? tr("Lokal", "Local", "Local")
      : health?.ollama.status === "degraded"
        ? tr("Modell fehlt", "Model missing", "Falta modelo")
        : tr("Aus", "Off", "Apagado")
    : ready
      ? "Cloud"
      : tr("Kein Key", "No key", "Sin clave");
  const chain = settings?.chain ?? [];
  return (
    <Tooltip
      side="bottom"
      align="right"
      content={
        <>
          <span className="block font-semibold">{providerDisplayName(mode)} · {formatModel(model)}</span>
          {chain.length > 1 && (
            <span className="mt-1 block text-subtle">
              {tr("Kaskade", "Cascade", "Cascada")}: {chain.map((stage) => formatModel(stage.model)).join(" → ")} → {tr("Regelwerk", "Rules", "Reglas")}
            </span>
          )}
          <span className="mt-1 block text-subtle">
            {local
              ? tr(
                  "Lokale Inferenz – kein Dokumentinhalt verlässt den Rechner.",
                  "Local inference – no document content leaves your machine.",
                  "Inferencia local – ningún contenido sale de este equipo.",
                )
              : tr(
                  "Cloud-Inferenz über das Privacy Gateway (Pseudonymisierung nach Art. 4 Nr. 5 DSGVO).",
                  "Cloud inference via the Privacy Gateway (pseudonymization under Art. 4 (5) GDPR).",
                  "Inferencia en la nube vía Privacy Gateway (seudonimización según Art. 4.5 RGPD).",
                )}
          </span>
          {!ready && (
            <span className="mt-1 block text-warn">
              {local
                ? tr(
                    "Nicht bereit – bis zum Start schließt das Regelwerk Prüfungen gekennzeichnet ab.",
                    "Not ready – rule engine completes audits (marked) until started.",
                    "No disponible – el motor de reglas completa las auditorías (marcado).",
                  )
                : tr(
                    "Kein API-Key hinterlegt – Einstellungen › KI-Einrichtung.",
                    "No API key configured – Settings › AI setup.",
                    "Sin clave API configurada – Ajustes › Configuración IA.",
                  )}
            </span>
          )}
        </>
      }
    >
      <span tabIndex={0} className="hidden cursor-help items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-1 text-xs text-muted xl:inline-flex">
        {formatModel(model)}
        <span className="text-subtle">· {state}</span>
        <span className={cx("h-2 w-2 rounded-full", ready ? "bg-ok" : "bg-subtle")} aria-label={ready ? tr("bereit", "ready", "listo") : tr("nicht bereit", "not ready", "no listo")} />
      </span>
    </Tooltip>
  );
}

export function Header(props: HeaderProps) {
  const { view, onViewChange, health, offline, settings, ledger, seeding, jobs, finished, copilotBusy } = props;
  const { tr } = useI18n();
  const online = !offline && Boolean(health);
  const analysing = jobs.some((job) => job.status === "running" || job.status === "queued");
  const viewLabels: Record<View, string> = {
    workspace: tr("Prüfung", "Audit", "Auditoría"),
    copilot: tr("Copilot", "Copilot", "Copiloto"),
    protocol: tr("Protokoll", "Audit Trail", "Registro"),
  };

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-[var(--header-bg)] backdrop-blur-xl backdrop-saturate-150 no-print">
      <div className="mx-auto grid h-14 w-full max-w-[1920px] grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto_minmax(max-content,1fr)] 2xl:max-w-[2400px] 2xl:px-10">
        <LogoVersion version={health?.version ?? null} ruleset={props.ruleset} />

        <nav aria-label={tr("Bereiche", "Sections", "Secciones")} className="order-3 col-span-2 hidden min-w-0 justify-center lg:order-none lg:col-span-1 lg:flex">
          <PillTabs<View>
            ariaLabel={tr("Bereiche", "Sections", "Secciones")}
            className="kopf-kapsel"
            value={view}
            onChange={onViewChange}
            items={[
              { key: "workspace", label: viewLabels.workspace, dot: analysing && view !== "workspace" ? "live" : null },
              { key: "copilot", label: viewLabels.copilot, dot: copilotBusy && view !== "copilot" ? "live" : null },
              { key: "protocol", label: viewLabels.protocol, dot: ledger && !ledger.valid ? "warn" : null },
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
            <Tooltip side="bottom" align="right" content={tr(`Keine Verbindung zu ${getApiBase()} – erneuter Versuch alle 10 s.`, `No connection to ${getApiBase()} – retrying every 10 s.`, `Sin conexión con ${getApiBase()} – reintentando cada 10 s.`)}>
              <span tabIndex={0} role="status" className="chip cursor-help border-bad-line bg-bad-soft py-1 text-bad">
                <WifiOff size={12} aria-hidden="true" /> {tr("Backend offline", "Backend offline", "Backend desconectado")}
              </span>
            </Tooltip>
          )}
          <GitSyncButton online={online} notify={props.notify} />
          <SampleMenu busy={seeding} disabled={offline} onLoad={props.onSeed} />
          <ModelStatus health={health} settings={settings} />
          <Tooltip content={tr("Interaktive Tour erneut starten", "Restart interactive tour", "Reiniciar recorrido interactivo")} side="bottom" align="right">
            <button type="button" className="btn btn-ghost btn-icon" onClick={props.onStartTour} aria-label={tr("Hilfe und Tour", "Help and tour", "Ayuda y recorrido")}>
              <HelpCircle size={15} aria-hidden="true" />
            </button>
          </Tooltip>
          <ThemeToggle />
          <Tooltip content={tr("Einstellungen", "Settings", "Ajustes")} side="bottom" align="right">
            <button type="button" className="btn btn-ghost btn-icon" onClick={props.onOpenSettings} aria-label={tr("Einstellungen", "Settings", "Ajustes")}>
              <Settings size={15} aria-hidden="true" />
            </button>
          </Tooltip>
        </div>
      </div>
      <nav aria-label={tr("Bereiche (kompakt)", "Sections (compact)", "Secciones (compacto)")} className="flex justify-center border-t border-line px-4 py-2 lg:hidden">
        <PillTabs<View>
          size="sm"
          value={view}
          onChange={onViewChange}
          items={[
            { key: "workspace", label: viewLabels.workspace },
            { key: "copilot", label: viewLabels.copilot },
            { key: "protocol", label: viewLabels.protocol },
          ]}
        />
      </nav>
    </header>
  );
}
