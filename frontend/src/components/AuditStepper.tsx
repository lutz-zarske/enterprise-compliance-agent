"use client";

import React, { useState } from "react";
import type { JobSnapshot } from "../types/api";
import { cx } from "../lib/format";
import { Check, Square } from "./icons";
import { Eta, ProgressBar, Spinner } from "./ui";

/** Die vier Phasen der Pruefung (eine Quelle: ``app/jobs.py``); Fallback vor der ersten Antwort. */
export const DEFAULT_PHASES = [
  { key: "text_check", label: "Text-Layer & XML-Vorrang" },
  { key: "pii_scan", label: "PII-Scanner & Privacy Vault" },
  { key: "ustg_check", label: "§ 14 UStG Extraktion & Prüfung" },
  { key: "ai_act", label: "EU AI Act, Scorecard & Ledger" },
];

/**
 * Live-Audit des geoeffneten Belegs: echte Phasen des Hintergrund-Jobs, Fortschritt,
 * geglaettete Restzeit und ruhige Hinweise bei Neuversuch oder Stufenwechsel.
 */
export function AuditStepper({ job, provider, onCancel }: {
  job: JobSnapshot;
  provider: string;
  onCancel: (jobId: string) => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  const phases = job.phases.length ? job.phases : DEFAULT_PHASES;
  const queued = job.status === "queued";
  const notice = job.events.length && job.message && !phases.some((phase) => phase.label === job.message) ? job.message : null;
  return (
    <section className="card p-4" aria-label="Live-Audit" aria-live="polite">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-fg">
            {queued ? "Prüfung wartet" : "Prüfung läuft"}: <span className="font-normal text-muted">{job.title}</span>
          </p>
          <p className="text-xs text-subtle">
            {queued ? `Platz ${job.queue_position} in der Warteschlange` : provider}
            {!queued && job.eta_seconds ? <> · <Eta seconds={job.eta_seconds} /></> : null}
          </p>
        </div>
        {!asking && !job.cancel_requested && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(true)}>
            <Square size={10} aria-hidden="true" /> Abbrechen
          </button>
        )}
        {asking && (
          <span className="flex items-center gap-1.5 rounded-md border border-bad-line bg-bad-soft px-2 py-1" role="alert">
            <span className="text-xs font-medium text-bad">Wirklich stoppen?</span>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => void onCancel(job.job_id).finally(() => setAsking(false))}>Ja</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>Nein</button>
          </span>
        )}
      </div>
      <ProgressBar value={queued ? null : job.progress} label="Fortschritt der Prüfung" />
      <ol className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
        {phases.map((phase, index) => {
          const state = index < job.phase_index ? "done" : index === job.phase_index && !queued ? "active" : "pending";
          return (
            <li key={phase.key} className="flex items-center gap-2">
              <span
                className={cx(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums",
                  state === "done" && "border-ok-line bg-ok-soft text-ok",
                  state === "active" && "border-accent-line bg-accent-soft text-accent",
                  state === "pending" && "border-line bg-surface-2 text-subtle",
                )}
              >
                {state === "done" ? <Check size={12} aria-hidden="true" /> : state === "active" ? <Spinner size={11} /> : index + 1}
              </span>
              <span className={cx("text-xs", state === "pending" ? "text-subtle" : "font-medium text-fg")}>{phase.label}</span>
            </li>
          );
        })}
      </ol>
      {notice && <p className="mt-3 rounded-md border border-warn-line bg-warn-soft px-3 py-1.5 text-xs text-fg">{notice}</p>}
      {job.stalled && (
        <p className="mt-3 rounded-md border border-warn-line bg-warn-soft px-3 py-1.5 text-xs text-fg">
          Seit Minuten keine Rückmeldung des Modells – die Prüfung abbrechen und neu starten oder in den Einstellungen ein Ausweichmodell hinterlegen.
        </p>
      )}
    </section>
  );
}
