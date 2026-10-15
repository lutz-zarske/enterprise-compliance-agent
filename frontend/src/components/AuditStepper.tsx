"use client";

import React from "react";
import type { ProgressStage } from "../types/api";
import { cx } from "../lib/format";
import { Check } from "./icons";
import { Spinner } from "./ui";

export const DEFAULT_STAGES: ProgressStage[] = [
  { key: "text_check", label: "Text-Layer & PDF-Check", state: "active" },
  { key: "pii_scan", label: "PII-Scanner & DSGVO-Maskierung", state: "pending" },
  { key: "ustg_check", label: "§ 14 UStG Rechnungsprüfung", state: "pending" },
  { key: "ai_act", label: "EU AI Act Risikobewertung", state: "pending" },
];

/** Zeigt die echten Pipeline-Stufen des Backends (GET /documents/{id}/progress). */
export function AuditStepper({ stages, filename, provider }: { stages: ProgressStage[]; filename: string; provider: string }) {
  return (
    <section className="card p-4" aria-label="Live-Audit" aria-live="polite">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-fg">Live-Audit läuft: <span className="font-normal text-muted">{filename}</span></p>
        <p className="font-mono text-xs text-subtle">{provider}</p>
      </div>
      <ol className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        {stages.map((stage, index) => (
          <li key={stage.key} className="flex items-center gap-2.5 sm:flex-col sm:items-start">
            <div className="flex w-full items-center gap-2">
              <span
                className={cx(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border font-mono text-xs",
                  stage.state === "done" && "border-ok-line bg-ok-soft text-ok",
                  stage.state === "active" && "border-accent-line bg-accent-soft text-accent",
                  stage.state === "pending" && "border-line bg-surface-2 text-subtle",
                )}
              >
                {stage.state === "done" ? <Check size={14} /> : stage.state === "active" ? <Spinner size={12} /> : index + 1}
              </span>
              {index < stages.length - 1 && (
                <span className={cx("hidden h-px flex-1 sm:block", stage.state === "done" ? "bg-ok-line" : "bg-line")} />
              )}
            </div>
            <span className={cx("text-xs", stage.state === "pending" ? "text-subtle" : "font-medium text-fg")}>
              {index + 1}. {stage.label}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
