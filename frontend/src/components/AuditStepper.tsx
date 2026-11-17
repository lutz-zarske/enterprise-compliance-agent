"use client";

import React, { useState } from "react";
import type { JobSnapshot } from "../types/api";
import { cx } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { Check, Square } from "./icons";
import { Eta, ProgressBar, Spinner } from "./ui";

const PHASE_LABELS: Record<string, { de: string; en: string; es: string }> = {
  text_check: { de: "Text-Layer & XML-Vorrang", en: "Text Layer & XML Primacy", es: "Capa de texto y primacía XML" },
  pii_scan: { de: "PII-Scanner & Privacy Vault", en: "PII Scanner & Privacy Vault", es: "Escáner PII y Privacy Vault" },
  ustg_check: { de: "§ 14 UStG Extraktion & Prüfung", en: "§ 14 VAT Extraction & Audit", es: "Extracción § 14 UStG y verificación" },
  ai_act: { de: "EU AI Act, Scorecard & Ledger", en: "EU AI Act, Scorecard & Ledger", es: "Reglamento de IA, Scorecard y Registro" },
};

export function AuditStepper({ job, provider, onCancel }: {
  job: JobSnapshot;
  provider: string;
  onCancel: (jobId: string) => Promise<void>;
}) {
  const { locale, tr, td } = useI18n();
  const [asking, setAsking] = useState(false);
  const rawPhases = job.phases.length
    ? job.phases
    : Object.entries(PHASE_LABELS).map(([key, labels]) => ({ key, label: labels[locale] }));
  const phases = rawPhases.map((p) => ({
    key: p.key,
    label: PHASE_LABELS[p.key]?.[locale] ?? td(p.label),
  }));
  const queued = job.status === "queued";
  const notice = job.events.length && job.message && !rawPhases.some((phase) => phase.label === job.message) ? td(job.message) : null;
  return (
    <section className="card p-4" aria-label={tr("Live-Audit", "Live Audit", "Auditoría en vivo")} aria-live="polite">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-fg">
            {queued ? tr("Prüfung wartet", "Audit queued", "Auditoría en cola") : tr("Prüfung läuft", "Audit running", "Auditoría en curso")}:{" "}
            <span className="font-normal text-muted">{job.title}</span>
          </p>
          <p className="text-xs text-subtle">
            {queued ? tr(`Platz ${job.queue_position} in der Warteschlange`, `Position #${job.queue_position} in queue`, `Puesto ${job.queue_position} en la cola`) : provider}
            {!queued && job.eta_seconds ? <> · <Eta seconds={job.eta_seconds} /></> : null}
          </p>
        </div>
        {!asking && !job.cancel_requested && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(true)}>
            <Square size={10} aria-hidden="true" /> {tr("Abbrechen", "Cancel", "Cancelar")}
          </button>
        )}
        {asking && (
          <span className="flex items-center gap-1.5 rounded-md border border-bad-line bg-bad-soft px-2 py-1" role="alert">
            <span className="text-xs font-medium text-bad">{tr("Wirklich stoppen?", "Stop audit?", "¿Detener?")}</span>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => void onCancel(job.job_id).finally(() => setAsking(false))}>{tr("Ja", "Yes", "Sí")}</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>{tr("Nein", "No", "No")}</button>
          </span>
        )}
      </div>
      <ProgressBar value={queued ? null : job.progress} label={tr("Fortschritt der Prüfung", "Audit progress", "Progreso de auditoría")} />
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
          {tr(
            "Seit Minuten keine Rückmeldung des Modells – die Prüfung abbrechen und neu starten oder in den Einstellungen ein Ausweichmodell hinterlegen.",
            "No model response for minutes – cancel and restart or configure a fallback model in Settings.",
            "Sin respuesta del modelo durante minutos – cancele y reinicie o configure un modelo alternativo en Ajustes.",
          )}
        </p>
      )}
    </section>
  );
}
