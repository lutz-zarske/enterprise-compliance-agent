"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useDismiss, usePopoverExclusive } from "../lib/popover";
import { cx } from "../lib/format";
import type { JobSnapshot } from "../types/api";
import { Check, ChevronDown, Square, X } from "./icons";
import { Eta, MiniRing, ProgressBar, Spinner } from "./ui";

/** So lange bleibt "fertig" nach dem Ende in der Kopfzeile stehen. */
export const NACHLAUF_MS = 12_000;

export interface FinishedJob {
  title: string;
  status: JobSnapshot["status"];
  heuristic: boolean;
  until: number;
}

function JobRow({ job, onCancel }: { job: JobSnapshot; onCancel: (jobId: string) => Promise<void> }) {
  const [asking, setAsking] = useState(false);
  const [stopping, setStopping] = useState(false);
  const running = job.status === "running";
  return (
    <li className="rounded-lg border border-line bg-surface-2/60 px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-caps">Belegprüfung</p>
          <p className="truncate text-[13px] font-medium text-fg" title={job.title}>{job.title}</p>
          <p className={cx("mt-0.5 line-clamp-2 text-xs", job.stalled ? "text-warn" : "text-subtle")}>
            {job.stalled
              ? "Keine Rückmeldung seit Minuten – abbrechen und neu starten?"
              : running
                ? job.message || job.phase_label || "Läuft …"
                : `Wartet · Platz ${job.queue_position} in der Warteschlange`}
          </p>
        </div>
        {!asking && !job.cancel_requested && (
          <button type="button" className="btn btn-danger btn-sm shrink-0" onClick={() => setAsking(true)}>
            <Square size={10} aria-hidden="true" /> Abbrechen
          </button>
        )}
      </div>
      {asking && (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-bad-line bg-bad-soft px-2.5 py-1.5" role="alert">
          <span className="text-xs font-medium text-bad">Wirklich stoppen?</span>
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
              {stopping ? <Spinner size={11} /> : "Ja, stoppen"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>Nein</button>
          </span>
        </div>
      )}
      {running && (
        <>
          <div className="mt-2 flex items-center gap-2.5">
            <ProgressBar value={job.progress} className="flex-1" label={`Fortschritt ${job.title}`} />
            <span className="w-10 text-right text-xs tabular-nums text-muted">{Math.floor(job.progress * 100)} %</span>
          </div>
          <ol className="mt-2 grid grid-cols-4 gap-1" aria-label="Phasen">
            {job.phases.map((phase, index) => (
              <li
                key={phase.key}
                title={phase.label}
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

/**
 * Globaler Job-Monitor in der Kopfzeile.
 *
 * Im Leerlauf unsichtbar.  Waehrend einer Pruefung: kompakte Pille (Ring + Prozent);
 * ein Klick oeffnet die Warteschlange mit Phasen, Fortschritt, Restzeit und einem
 * zweistufigen Abbrechen.  Nach dem Ende bleibt der Ausgang 12 s stehen.
 */
export function JobMonitor({ jobs, finished, onCancel }: {
  jobs: JobSnapshot[];
  finished: FinishedJob | null;
  onCancel: (jobId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [, setTick] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "job-monitor");
  useDismiss(open, close, [ref]);

  useEffect(() => {
    if (!jobs.length) setOpen(false);
  }, [jobs.length]);

  // Nachlauf-Pille verschwindet von selbst.
  useEffect(() => {
    if (!finished) return;
    const timer = window.setTimeout(() => setTick((n) => n + 1), Math.max(0, finished.until - Date.now()) + 50);
    return () => window.clearTimeout(timer);
  }, [finished]);

  if (!jobs.length) {
    if (!finished || finished.until < Date.now()) return null;
    const ok = finished.status === "done";
    const text = ok ? (finished.heuristic ? "fertig (Regelwerk)" : "fertig") : finished.status === "cancelled" ? "abgebrochen" : "fehlgeschlagen";
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
        <span className="min-w-0 truncate">Prüfung</span>
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
        aria-label={`${lead.title} · ${percent} % – Hintergrundaufgaben anzeigen`}
        title={lead.title}
        className={cx(
          "inline-flex h-7 items-center gap-2 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium transition-colors duration-150",
          open ? "border-accent bg-accent-soft text-fg" : "border-accent-line bg-accent-soft text-accent hover:border-accent hover:text-fg",
        )}
      >
        {lead.status === "running" ? <MiniRing value={lead.progress} /> : <Spinner size={12} />}
        <span>Prüfung</span>
        <span className="tabular-nums opacity-80">· {lead.status === "running" ? `${percent} %` : "wartet"}</span>
        {more > 0 && (
          <span className="rounded-full bg-accent-soft px-1.5 text-xs tabular-nums" title={`${more} weitere in der Warteschlange`}>
            +{more}
          </span>
        )}
        <ChevronDown size={12} aria-hidden="true" className={cx("transition-transform duration-150", open && "rotate-180")} />
      </button>
      {open && (
        <div role="dialog" aria-label="Hintergrundaufgaben" className="glass-menu absolute right-0 top-full z-[70] mt-2 w-[24rem] p-2">
          <p className="label-caps px-1.5 pb-2 pt-1">
            Hintergrundaufgaben · <span className="tabular-nums">{jobs.length}</span>
          </p>
          <ul className="scroll-area flex max-h-[60vh] flex-col gap-1.5 pr-1">
            {jobs.map((job) => (
              <JobRow key={job.job_id} job={job} onCancel={onCancel} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
