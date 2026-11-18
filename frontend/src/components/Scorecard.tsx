"use client";

import React from "react";
import type { Scorecard as ScorecardType, ScoreTile } from "../types/api";
import { cx, formatDate, presentedBand, TONE_CLASSES, TONE_TEXT, toneForBand, toneForStatus, verdictTone } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { Clock, Lock, Scale } from "./icons";
import { StatusIcon, Tooltip } from "./ui";

const RING_COLORS = { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)", neutral: "var(--fg-subtle)" } as const;

function ScoreRing({ score, tone, ariaLabel }: { score: number; tone: "ok" | "warn" | "bad" | "neutral"; ariaLabel: string }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - score / 100);
  return (
    <div className="relative h-28 w-28 shrink-0" role="img" aria-label={ariaLabel}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--line)" strokeWidth="6" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={RING_COLORS[tone]}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cx("zahl-display text-[32px] font-semibold leading-none tabular-nums", TONE_TEXT[tone])}>{score}</span>
        <span className="mt-1 text-xs tabular-nums text-subtle">/ 100</span>
      </div>
    </div>
  );
}

interface Props {
  scorecard: ScorecardType;
  sealed: boolean;
  reference: boolean;
  onOpenTile: (key: ScoreTile["key"]) => void;
}

export function Scorecard({ scorecard, sealed, reference, onOpenTile }: Props) {
  const { tr, td } = useI18n();
  const verdict = presentedBand(scorecard);
  const tone = toneForBand(verdict.band);
  const ringTone = tone === "pii" || tone === "accent" ? "neutral" : tone;
  const tileLabels: Record<ScoreTile["key"], string> = {
    formal: "§ 14 UStG",
    regulatory: "EU AI Act",
    privacy: tr("DSGVO", "GDPR", "RGPD"),
    math: tr("Finanzmathematik", "Financial Math", "Matemática financiera"),
  };

  return (
    <section className="card p-5" aria-label={tr("Compliance-Scorecard", "Compliance Scorecard", "Cuadro de mando de cumplimiento")}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <ScoreRing
          score={scorecard.score}
          tone={ringTone}
          ariaLabel={tr(`Compliance-Score ${scorecard.score} von 100`, `Compliance score ${scorecard.score} of 100`, `Puntuación de cumplimiento ${scorecard.score} de 100`)}
        />
        <div className="min-w-0 flex-1">
          <h2 className={cx("text-lg font-semibold leading-snug text-balance", TONE_TEXT[verdictTone(scorecard)])}>
            {td(scorecard.release_recommendation)}
          </h2>
          {scorecard.cap_applied && <p className="mt-1 text-sm text-warn">{td(scorecard.cap_applied)}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className={cx("chip", TONE_CLASSES[tone])}>{td(verdict.label)}</span>
            {sealed && (
              <span className="chip border-ok-line bg-ok-soft text-ok">
                <Lock size={11} aria-hidden="true" /> {tr("Versiegelt", "Sealed", "Sellado")}
              </span>
            )}
            {reference && (
              <span
                className="chip border-line bg-surface-2 text-muted"
                title={tr(
                  "Die KI-Antwort ist vorberechnet; Score, Maskierung und Hash-Kette stammen aus dem Regelwerk.",
                  "AI response is precomputed; score, redaction and hash chain come from the deterministic rule engine.",
                  "La respuesta de IA está precalculada; puntuación, anonimización y cadena de hash proceden del motor de reglas.",
                )}
              >
                {tr("Referenz-Audit · ohne KI", "Reference audit · offline rules", "Auditoría de referencia · sin IA")}
              </span>
            )}
            {scorecard.human_override && (
              <Tooltip
                content={`${scorecard.human_override.auditor_name}, ${formatDate(scorecard.human_override.overridden_at, true)}: ${scorecard.human_override.legal_basis}. Score ${scorecard.human_override.previous_score ?? "–"} → ${scorecard.human_override.new_score}.`}
              >
                <span tabIndex={0} className="chip cursor-help border-accent-line bg-accent-soft text-accent">
                  <Scale size={11} aria-hidden="true" /> {tr("Durch Prüfperson übersteuert", "Overridden by auditor", "Anulado por auditor")}
                </span>
              </Tooltip>
            )}
            {scorecard.retention && (
              <Tooltip
                content={
                  <>
                    <span className="block font-semibold">{tr("Aufbewahrung nach BEG IV", "Retention under BEG IV", "Conservación según BEG IV")}</span>
                    <span className="block">
                      {tr(
                        `Rechnungen und Buchungsbelege ${scorecard.retention.years} Jahre (${scorecard.retention.basis}).`,
                        `Invoices and accounting records: ${scorecard.retention.years} years (${scorecard.retention.basis}).`,
                        `Facturas y justificantes contables: ${scorecard.retention.years} años (${scorecard.retention.basis}).`,
                      )}
                    </span>
                    <span className="block">
                      {tr(
                        `Kreditinstitute, Versicherungen, Wertpapierinstitute: 10 Jahre (bis ${formatDate(scorecard.retention.financial_sector_until)}).`,
                        `Banks, insurers, investment firms: 10 years (until ${formatDate(scorecard.retention.financial_sector_until)}).`,
                        `Bancos, aseguradoras y empresas de inversión: 10 años (hasta el ${formatDate(scorecard.retention.financial_sector_until)}).`,
                      )}
                    </span>
                    <span className="block">
                      {tr(
                        "Handelsbücher, Jahresabschlüsse und Verfahrensdokumentation: 10 Jahre (§ 147 Abs. 1 Nr. 1 AO).",
                        "Ledgers, annual accounts and procedural documentation: 10 years (§ 147(1) No. 1 AO).",
                        "Libros contables, cuentas anuales y documentación de procedimientos: 10 años (§ 147(1) n.º 1 AO).",
                      )}
                    </span>
                    <span className="mt-1 block text-subtle">
                      {tr(
                        "Frist ab Schluss des Belegjahres (§ 147 Abs. 4 AO), Ablaufhemmung nach § 147 Abs. 3 Satz 5 AO.",
                        "Starts at end of invoice fiscal year (§ 147(4) AO); suspension rules under § 147(3) sentence 5 AO apply.",
                        "Plazo desde el cierre del ejercicio (§ 147(4) AO); se aplica suspensión según § 147(3) frase 5 AO.",
                      )}
                    </span>
                  </>
                }
              >
                <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 tabular-nums text-muted">
                  <Clock size={11} aria-hidden="true" /> {tr("Aufbewahren bis", "Retain until", "Conservar hasta")} {formatDate(scorecard.retention.until)}
                </span>
              </Tooltip>
            )}
            <span className="text-xs tabular-nums text-subtle">
              {tr("Regelwerk", "Ruleset", "Reglamento")} {scorecard.ruleset_version}
              {scorecard.small_amount_invoice && tr(" · Kleinbetragsrechnung (§ 33 UStDV)", " · Small-amount invoice (§ 33 UStDV)", " · Factura simplificada (§ 33 UStDV)")}
              {scorecard.structured_einvoice_detected && tr(" · E-Rechnung (XML) erkannt", " · E-Invoice (XML) detected", " · Factura electrónica (XML) detectada")}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {scorecard.tiles.map((tile) => {
          const tileTone = toneForStatus(tile.status);
          const risks = tile.checks.filter((check) => check.deduction > 0 && check.risk_note);
          const riskList = risks.map((check) => (
            <span key={check.id} className="block py-0.5">
              <span className="tabular-nums text-bad">−{check.deduction}</span> {td(check.risk_note)}
            </span>
          ));
          return (
            <Tooltip key={tile.key} content={risks.length ? riskList : null} className="w-full">
              <button
                type="button"
                onClick={() => onOpenTile(tile.key)}
                className="w-full rounded-lg border border-line bg-surface-2 p-3 text-left transition-colors duration-150 hover:border-line-strong"
                aria-describedby={risks.length ? `risk-${tile.key}` : undefined}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-subtle">{tileLabels[tile.key]}</span>
                  <StatusIcon status={tile.status} size={14} />
                </div>
                <p className={cx("mt-1.5 text-sm font-semibold", tileTone === "neutral" ? "text-fg" : TONE_TEXT[tileTone])}>
                  {td(tile.headline) || "–"}
                </p>
                <p className={cx("mt-0.5 text-xs tabular-nums", tile.deduction > 0 ? "text-bad" : "text-subtle")}>
                  {tile.deduction > 0 ? (
                    <span className={cx(risks.length > 0 && "underline decoration-dotted underline-offset-2")}>
                      −{tile.deduction} {tr(tile.deduction === 1 ? "Punkt" : "Punkte", tile.deduction === 1 ? "pt" : "pts", tile.deduction === 1 ? "punto" : "puntos")}
                    </span>
                  ) : (
                    tr("keine Abzüge", "no deductions", "sin deducciones")
                  )}
                </p>
              </button>
              {/* Rechtsfolgen für Screenreader dauerhaft verknüpft; sichtbar im Portal-Tooltip. */}
              {risks.length > 0 && (
                <span id={`risk-${tile.key}`} className="sr-only">
                  {risks.map((check) => `−${check.deduction}: ${td(check.risk_note)}`).join(" ")}
                </span>
              )}
            </Tooltip>
          );
        })}
      </div>
    </section>
  );
}
