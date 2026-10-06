"use client";

import React, { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { cx, RISK_LABELS } from "../lib/format";
import type { AIActRiskLevel, DocumentDetail } from "../types/api";
import { Scale } from "./icons";
import { Modal, Spinner } from "./ui";

const AUDITOR_STORAGE = "eca-auditor-name";
const MIN_REASON = 20;

const LEVELS: AIActRiskLevel[] = ["unacceptable", "high", "limited", "minimal", "not_applicable"];

/** Haeufige Normen fuer die Begruendung - frei editierbar. */
const LEGAL_BASES = [
  "Art. 6 Abs. 3 lit. a VO (EU) 2024/1689 (eng begrenzte Verfahrensaufgabe)",
  "Art. 6 Abs. 3 lit. b VO (EU) 2024/1689 (Verbesserung einer abgeschlossenen menschlichen Tätigkeit)",
  "Art. 6 Abs. 3 lit. c VO (EU) 2024/1689 (Erkennung von Entscheidungsmustern ohne Ersetzung der Bewertung)",
  "Art. 6 Abs. 3 lit. d VO (EU) 2024/1689 (vorbereitende Aufgabe)",
  "Art. 6 Abs. 2 i. V. m. Anhang III VO (EU) 2024/1689",
  "Art. 3 Nr. 1 VO (EU) 2024/1689 (kein KI-System)",
  "Art. 50 VO (EU) 2024/1689 (Transparenzpflichten)",
];

interface Props {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  onDone: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad" | "warn", title: string, message?: string) => void;
}

export function OverrideModal({ document, open, onClose, onDone, notify }: Props) {
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
        "Einstufung übersteuert",
        override ? `Score ${override.previous_score ?? "–"} → ${override.new_score} · signierter Ledger-Eintrag geschrieben` : undefined,
      );
      onDone(updated);
      onClose();
    } catch (err) {
      const error = err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown");
      notify("bad", "Übersteuerung abgelehnt", `${error.message}${error.hint ? ` – ${error.hint}` : ""}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="KI-Einstufung übersteuern"
      subtitle="Menschliche Aufsicht nach Art. 14 Abs. 4 lit. d VO (EU) 2024/1689"
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
          Aktuelle Einstufung: <strong className="text-fg">{RISK_LABELS[current]}</strong>. Der Score wird mit der neuen
          Einstufung deterministisch neu berechnet. Person, Begründung, Rechtsnorm und Score vorher/nachher landen als
          Ed25519-signierter Eintrag im Prüfprotokoll; ein bestehendes Siegel wird aufgehoben.
        </p>

        <fieldset>
          <legend className="label-caps">Neue Risikostufe</legend>
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
                {RISK_LABELS[value]}
                {value === current && <span className="ml-auto font-mono text-[10px]">aktuell</span>}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="block">
          <span className="label-caps">Rechtsnorm</span>
          <input
            className="input mt-1"
            name="legal-basis"
            list="override-legal-bases"
            autoComplete="off"
            value={legalBasis}
            onChange={(event) => setLegalBasis(event.target.value)}
            placeholder="z. B. Art. 6 Abs. 3 lit. d VO (EU) 2024/1689…"
            required
          />
          <datalist id="override-legal-bases">
            {LEGAL_BASES.map((basis) => <option key={basis} value={basis} />)}
          </datalist>
        </label>

        <label className="block">
          <span className="flex items-baseline justify-between">
            <span className="label-caps">Begründung</span>
            <span className={cx("font-mono text-[11px] tabular-nums", reason.trim().length >= MIN_REASON ? "text-subtle" : "text-warn")}>
              {reason.trim().length}/{MIN_REASON}
            </span>
          </span>
          <textarea
            className="input mt-1 min-h-[96px]"
            name="override-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Warum trifft die Einstufung der KI nicht zu? Für Dritte nachvollziehbar formulieren…"
            required
            minLength={MIN_REASON}
          />
        </label>

        <label className="block">
          <span className="label-caps">Name der Prüfperson</span>
          <input
            className="input mt-1"
            name="auditor-name"
            autoComplete="name"
            value={auditor}
            onChange={(event) => setAuditor(event.target.value)}
            placeholder="z. B. Lutz Zarske…"
            required
          />
        </label>

        <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-[11px] leading-snug text-subtle">
            Vier-Augen-Prinzip: Die abschließende Freigabe sollte eine andere Person erteilen.
          </p>
          <div className="flex shrink-0 gap-2">
            <button type="button" className="btn" onClick={onClose}>Abbrechen</button>
            <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
              {busy ? <Spinner size={13} /> : <Scale size={14} aria-hidden="true" />}
              Übersteuern
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
