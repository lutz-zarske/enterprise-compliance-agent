"use client";

import React, { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { cx, riskLabel } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { AIActRiskLevel, DocumentDetail } from "../types/api";
import { Scale } from "./icons";
import { AutoTextarea, Modal, Spinner } from "./ui";

const AUDITOR_STORAGE = "eca-auditor-name";
const MIN_REASON = 20;

const LEVELS: AIActRiskLevel[] = ["unacceptable", "high", "limited", "minimal", "not_applicable"];

/** Haeufige Normen fuer die Begruendung - frei editierbar. */
const LEGAL_BASES = {
  de: [
    "Art. 6 Abs. 3 lit. a VO (EU) 2024/1689 (eng begrenzte Verfahrensaufgabe)",
    "Art. 6 Abs. 3 lit. b VO (EU) 2024/1689 (Verbesserung einer abgeschlossenen menschlichen Tätigkeit)",
    "Art. 6 Abs. 3 lit. c VO (EU) 2024/1689 (Erkennung von Entscheidungsmustern ohne Ersetzung der Bewertung)",
    "Art. 6 Abs. 3 lit. d VO (EU) 2024/1689 (vorbereitende Aufgabe)",
    "Art. 6 Abs. 2 i. V. m. Anhang III VO (EU) 2024/1689",
    "Art. 3 Nr. 1 VO (EU) 2024/1689 (kein KI-System)",
    "Art. 50 VO (EU) 2024/1689 (Transparenzpflichten)",
  ],
  en: [
    "Art. 6(3)(a) Regulation (EU) 2024/1689 (narrow procedural task)",
    "Art. 6(3)(b) Regulation (EU) 2024/1689 (improving a completed human activity)",
    "Art. 6(3)(c) Regulation (EU) 2024/1689 (detecting decision-making patterns without replacing assessment)",
    "Art. 6(3)(d) Regulation (EU) 2024/1689 (preparatory task)",
    "Art. 6(2) in conj. with Annex III Regulation (EU) 2024/1689",
    "Art. 3(1) Regulation (EU) 2024/1689 (not an AI system)",
    "Art. 50 Regulation (EU) 2024/1689 (transparency obligations)",
  ],
  es: [
    "Art. 6(3)(a) Reglamento (UE) 2024/1689 (tarea procedimental limitada)",
    "Art. 6(3)(b) Reglamento (UE) 2024/1689 (mejora de actividad humana previa)",
    "Art. 6(3)(c) Reglamento (UE) 2024/1689 (detección de patrones sin sustituir la valoración)",
    "Art. 6(3)(d) Reglamento (UE) 2024/1689 (tarea preparatoria)",
    "Art. 6(2) en rel. con Anexo III Reglamento (UE) 2024/1689",
    "Art. 3(1) Reglamento (UE) 2024/1689 (no es un sistema de IA)",
    "Art. 50 Reglamento (UE) 2024/1689 (obligaciones de transparencia)",
  ],
} as const;

interface Props {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  onDone: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad" | "warn", title: string, message?: string) => void;
}

export function OverrideModal({ document, open, onClose, onDone, notify }: Props) {
  const { locale, tr } = useI18n();
  const current = document?.compliance?.ai_act.overall_risk_level ?? "not_applicable";
  const [auditor, setAuditor] = useState("");
  const [level, setLevel] = useState<AIActRiskLevel>("limited");
  const [legalBasis, setLegalBasis] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    try {
      setAuditor(window.localStorage.getItem(AUDITOR_STORAGE) ?? "");
    } catch {
      /* ignorieren */
    }
    setLevel(LEVELS.find((candidate) => candidate !== current && candidate !== "unacceptable") ?? "limited");
    setLegalBasis("");
    setReason("");
  }, [open, current]);

  if (!document) return null;
  const valid = auditor.trim().length >= 2 && legalBasis.trim().length >= 3 && reason.trim().length >= MIN_REASON && level !== current;

  async function submit() {
    if (!document || !valid) return;
    setBusy(true);
    try {
      const updated = await api.override(document.id, {
        auditor_name: auditor.trim(),
        risk_level: level,
        reason: reason.trim(),
        legal_basis: legalBasis.trim(),
      });
      try {
        window.localStorage.setItem(AUDITOR_STORAGE, auditor.trim());
      } catch {
        /* ignorieren */
      }
      const override = updated.scorecard?.human_override;
      notify(
        "ok",
        tr("Einstufung übersteuert", "Classification overridden", "Clasificación anulada"),
        override
          ? tr(
              `Score ${override.previous_score ?? "–"} → ${override.new_score} · signierter Ledger-Eintrag geschrieben`,
              `Score ${override.previous_score ?? "–"} → ${override.new_score} · signed ledger entry written`,
              `Puntuación ${override.previous_score ?? "–"} → ${override.new_score} · registro firmado escrito`,
            )
          : undefined,
      );
      onDone(updated);
      onClose();
    } catch (err) {
      const error = err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown");
      notify(
        "bad",
        tr("Übersteuerung abgelehnt", "Override rejected", "Anulación rechazada"),
        `${error.message}${error.hint ? ` – ${error.hint}` : ""}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={tr("KI-Einstufung übersteuern", "Override AI Classification", "Anular clasificación de IA")}
      subtitle={tr(
        "Menschliche Aufsicht nach Art. 14 Abs. 4 lit. d VO (EU) 2024/1689",
        "Human oversight under Art. 14(4)(d) Regulation (EU) 2024/1689",
        "Supervisión humana según art. 14(4)(d) Reglamento (UE) 2024/1689",
      )}
      width="max-w-xl"
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <p className="text-xs leading-relaxed text-muted">
          {tr("Aktuelle Einstufung:", "Current classification:", "Clasificación actual:")}{" "}
          <strong className="text-fg">{riskLabel(current)}</strong>.{" "}
          {tr(
            "Der Score wird mit der neuen Einstufung deterministisch neu berechnet. Person, Begründung, Rechtsnorm und Score vorher/nachher landen als Ed25519-signierter Eintrag im Prüfprotokoll; ein bestehendes Siegel wird aufgehoben.",
            "The score is deterministically recalculated with the new classification. Auditor, reason, legal basis and before/after score are recorded as an Ed25519-signed ledger entry; any existing seal is voided.",
            "La puntuación se recalcula de forma determinista. Auditor, motivo, base legal y puntuación anterior/nueva se registran con firma Ed25519; cualquier sello previo queda anulado.",
          )}
        </p>

        <fieldset>
          <legend className="label-caps">{tr("Neue Risikostufe", "New Risk Tier", "Nuevo nivel de riesgo")}</legend>
          <div className="mt-1 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {LEVELS.map((value) => (
              <button
                key={value}
                type="button"
                disabled={value === current}
                onClick={() => setLevel(value)}
                aria-pressed={level === value}
                className={cx(
                  "btn justify-start text-left text-xs",
                  level === value && "border-accent-line bg-accent-soft text-accent",
                  value === current && "opacity-50",
                )}
              >
                {riskLabel(value)}
                {value === current && <span className="ml-auto text-xs">{tr("aktuell", "current", "actual")}</span>}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="block">
          <span className="label-caps">{tr("Rechtsnorm", "Legal Basis", "Base legal")}</span>
          <input
            className="input mt-1"
            name="legal-basis"
            list="override-legal-bases"
            autoComplete="off"
            value={legalBasis}
            onChange={(event) => setLegalBasis(event.target.value)}
            placeholder={tr("z. B. Art. 6 Abs. 3 lit. d VO (EU) 2024/1689…", "e.g. Art. 6(3)(d) Regulation (EU) 2024/1689…", "p. ej. Art. 6(3)(d) Reglamento (UE) 2024/1689…")}
            required
          />
          <datalist id="override-legal-bases">
            {LEGAL_BASES[locale].map((basis) => <option key={basis} value={basis} />)}
          </datalist>
        </label>

        <label className="block">
          <span className="flex items-baseline justify-between">
            <span className="label-caps">{tr("Begründung", "Justification", "Justificación")}</span>
            <span className={cx("text-xs tabular-nums", reason.trim().length >= MIN_REASON ? "text-subtle" : "text-warn")}>
              {reason.trim().length}/{MIN_REASON}
            </span>
          </span>
          <AutoTextarea
            className="mt-1 leading-relaxed"
            minRows={4}
            maxRows={9}
            name="override-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={tr(
              "Warum trifft die Einstufung der KI nicht zu? Für Dritte nachvollziehbar formulieren…",
              "Why does the AI classification not apply? State clearly for third-party audit…",
              "¿Por qué no aplica la clasificación de la IA? Explíquelo claramente para auditoría…",
            )}
            required
            minLength={MIN_REASON}
          />
        </label>

        <label className="block">
          <span className="label-caps">{tr("Name der Prüfperson", "Auditor Name", "Nombre del auditor")}</span>
          <input
            className="input mt-1"
            name="auditor-name"
            autoComplete="name"
            value={auditor}
            onChange={(event) => setAuditor(event.target.value)}
            placeholder={tr("Prüferkürzel oder Name eingeben…", "Enter auditor initials or name…", "Introducir iniciales o nombre…")}
            required
          />
        </label>

        <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-xs leading-snug text-subtle">
            {tr(
              "Vier-Augen-Prinzip: Die abschließende Freigabe sollte eine andere Person erteilen.",
              "Dual control: A different person should grant the final seal.",
              "Principio de doble control: otra persona debería otorgar el sello final.",
            )}
          </p>
          <div className="flex shrink-0 gap-2">
            <button type="button" className="btn" onClick={onClose}>{tr("Abbrechen", "Cancel", "Cancelar")}</button>
            <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
              {busy ? <Spinner size={13} /> : <Scale size={14} aria-hidden="true" />}
              {tr("Übersteuern", "Override", "Anular")}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
