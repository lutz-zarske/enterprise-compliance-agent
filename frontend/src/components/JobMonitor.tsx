"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useAnchoredStyle, useDismiss, usePopoverExclusive } from "../lib/popover";
import { cx } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { createPortal } from "react-dom";
import type { JobSnapshot } from "../types/api";
import { Check, ChevronDown, Square, X } from "./icons";
import { Eta, MiniRing, ProgressBar, Spinner } from "./ui";

export const NACHLAUF_MS = 12_000;

export interface FinishedJob {
  title: string;
  status: JobSnapshot["status"];
  heuristic: boolean;
  until: number;
}

function JobRow({ job, onCancel }: { job: JobSnapshot; onCancel: (jobId: string) => Promise<void> }) {
  const { tr, td } = useI18n();
  const [asking, setAsking] = useState(false);
  const [stopping, setStopping] = useState(false);
  const running = job.status === "running";
  return (
    <li className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-caps">{tr("Belegprüfung", "Document Audit", "Auditoría")}</p>
          <p className="truncate text-[13px] font-medium text-fg" title={job.title}>{job.title}</p>
          <p className={cx("mt-0.5 line-clamp-2 text-xs", job.stalled ? "text-warn" : "text-subtle")}>
            {job.stalled
              ? tr("Keine Rückmeldung seit Minuten – abbrechen und neu starten?", "No response for minutes – cancel and restart?", "Sin respuesta durante minutos – ¿cancelar?")
              : running
                ? td(job.message || job.phase_label) || tr("Läuft …", "Running …", "En curso …")
                : tr(`Wartet · Platz ${job.queue_position} in der Warteschlange`, `Queued · position #${job.queue_position}`, `En cola · puesto ${job.queue_position}`)}
          </p>
        </div>
        {!asking && !job.cancel_requested && (
          <button type="button" className="btn btn-danger btn-sm shrink-0" onClick={() => setAsking(true)}>
            <Square size={10} aria-hidden="true" /> {tr("Abbrechen", "Cancel", "Cancelar")}
          </button>
        )}
      </div>
      {asking && (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-bad-line bg-bad-soft px-2.5 py-1.5" role="alert">
          <span className="text-xs font-medium text-bad">{tr("Wirklich stoppen?", "Stop audit?", "¿Detener auditoría?")}</span>
          <span className="flex items-center gap-1.5">
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={stopping}
              onClick={async () => {
                setStopping(true);
                await onCancel(job.job_id);
                setStopping(false);
                setAsking(false);
              }}
            >
              {stopping ? <Spinner size={11} /> : tr("Ja, stoppen", "Yes, stop", "Sí, detener")}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>{tr("Nein", "No", "No")}</button>
          </span>
        </div>
      )}
      {running && (
        <>
          <div className="mt-2 flex items-center gap-2.5">
            <ProgressBar value={job.progress} className="flex-1" label={`${tr("Fortschritt", "Progress", "Progreso")} ${job.title}`} />
            <span className="w-10 text-right text-xs tabular-nums text-muted">{Math.floor(job.progress * 100)} %</span>
          </div>
          <ol className="mt-2 grid grid-cols-4 gap-1" aria-label={tr("Phasen", "Phases", "Fases")}>
            {job.phases.map((phase, index) => (
              <li
                key={phase.key}
                title={td(phase.label)}
                className={cx(
                  "h-1 rounded-full",
                  index < job.phase_index ? "bg-ok" : index === job.phase_index ? "bg-accent" : "bg-surface-hover",
                )}
              />
            ))}
          </ol>
          {job.eta_seconds ? <p className="mt-1.5 text-xs text-subtle"><Eta seconds={job.eta_seconds} /></p> : null}
        </>
      )}
    </li>
  );
}

export function JobMonitor({ jobs, finished, onCancel }: {
  jobs: JobSnapshot[];
  finished: FinishedJob | null;
  onCancel: (jobId: string) => Promise<void>;
}) {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  const [, setTick] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "job-monitor");
  useDismiss(open, close, [ref, menuRef]);
  const style = useAnchoredStyle(open, ref, { width: 384, maxHeight: 560, align: "right" });

  useEffect(() => {
    if (!jobs.length) setOpen(false);
  }, [jobs.length]);

  useEffect(() => {
    if (!finished) return;
    const timer = window.setTimeout(() => setTick((n) => n + 1), Math.max(0, finished.until - Date.now()) + 50);
    return () => window.clearTimeout(timer);
  }, [finished]);

  if (!jobs.length) {
    if (!finished || finished.until < Date.now()) return null;
    const ok = finished.status === "done";
    const text = ok
      ? (finished.heuristic ? tr("fertig (Regelwerk)", "done (rules)", "listo (reglas)") : tr("fertig", "done", "listo"))
      : finished.status === "cancelled"
        ? tr("abgebrochen", "cancelled", "cancelado")
        : tr("fehlgeschlagen", "failed", "fallido");
    return (
      <span
        role="status"
        title={`${finished.title} – ${text}`}
        className={cx(
          "anim-fade inline-flex h-7 max-w-[16rem] items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium",
          ok ? "border-ok-line bg-ok-soft text-ok" : finished.status === "cancelled" ? "border-warn-line bg-warn-soft text-warn" : "border-bad-line bg-bad-soft text-bad",
        )}
      >
        {ok ? <Check size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />}
        <span className="min-w-0 truncate">{tr("Prüfung", "Audit", "Auditoría")}</span>
        <span className="shrink-0 opacity-80">{text}</span>
      </span>
    );
  }

  const lead = jobs.find((job) => job.status === "running") ?? jobs[0];
  const more = jobs.length - 1;
  const percent = Math.floor(lead.progress * 100);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${lead.title} · ${percent} % – ${tr("Hintergrundaufgaben anzeigen", "Show background jobs", "Ver tareas en segundo plano")}`}
        title={lead.title}
        className={cx(
          "inline-flex h-7 items-center gap-2 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium transition-colors duration-150",
          open ? "border-accent bg-accent-soft text-fg" : "border-accent-line bg-accent-soft text-accent hover:border-accent hover:text-fg",
        )}
      >
        {lead.status === "running" ? <MiniRing value={lead.progress} /> : <Spinner size={12} />}
        <span>{tr("Prüfung", "Audit", "Auditoría")}</span>
        <span className="tabular-nums opacity-80">· {lead.status === "running" ? `${percent} %` : tr("wartet", "queued", "en cola")}</span>
        {more > 0 && (
          <span className="rounded-full bg-accent-soft px-1.5 text-xs tabular-nums" title={tr(`${more} weitere in der Warteschlange`, `${more} more in queue`, `${more} más en cola`)}>
            +{more}
          </span>
        )}
        <ChevronDown size={12} aria-hidden="true" className={cx("transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open &&
        createPortal(
          <div ref={menuRef} role="dialog" aria-label={tr("Hintergrundaufgaben", "Background jobs", "Tareas en segundo plano")} style={style} className="glass-menu z-[70] flex flex-col p-2">
            <p className="label-caps px-1.5 pb-2 pt-1">
              {tr("Hintergrundaufgaben", "Background jobs", "Tareas en segundo plano")} · <span className="tabular-nums">{jobs.length}</span>
            </p>
            <ul className="scroll-area flex min-h-0 flex-1 flex-col gap-1.5 pr-1">
              {jobs.map((job) => (
                <JobRow key={job.job_id} job={job} onCancel={onCancel} />
              ))}
            </ul>
          </div>,
          document.body,
        )}
    </div>
  );
}
