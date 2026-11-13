"use client";

import React from "react";
import type { Scorecard as ScorecardType, ScoreTile } from "../types/api";
import { cx, formatDate, TONE_CLASSES, TONE_TEXT, toneForBand, toneForStatus } from "../lib/format";
import { Clock, Lock, Scale } from "./icons";
import { StatusIcon, Tooltip } from "./ui";

const TILE_LABELS: Record<ScoreTile["key"], string> = {
  formal: "§ 14 UStG",
  regulatory: "EU AI Act",
  privacy: "DSGVO",
  math: "Finanzmathematik",
};

const RING_COLORS = { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)", neutral: "var(--fg-subtle)" } as const;

function ScoreRing({ score, tone }: { score: number; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - score / 100);
  return (
    <div className="relative h-28 w-28 shrink-0" role="img" aria-label={`Compliance-Score ${score} von 100`}>
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
  const tone = toneForBand(scorecard.band);
  const ringTone = tone === "pii" || tone === "accent" ? "neutral" : tone;
  return (
    <section className="card p-5" aria-label="Compliance-Scorecard">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <ScoreRing score={scorecard.score} tone={ringTone} />
        <div className="min-w-0 flex-1">
          <h2 className={cx("text-lg font-semibold leading-snug text-balance", scorecard.release_blocked ? "text-bad" : "text-ok")}>
            {scorecard.release_recommendation}
          </h2>
          {scorecard.cap_applied && <p className="mt-1 text-sm text-warn">{scorecard.cap_applied}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className={cx("chip", TONE_CLASSES[tone])}>{scorecard.band_label}</span>
            {sealed && (
              <span className="chip border-ok-line bg-ok-soft text-ok">
                <Lock size={11} aria-hidden="true" /> Versiegelt
              </span>
            )}
            {reference && (
              <span
                className="chip border-line bg-surface-2 text-muted"
                title="Die KI-Antwort ist vorberechnet; Score, Maskierung und Hash-Kette stammen aus dem Regelwerk."
              >
                Referenz-Audit · ohne KI
              </span>
            )}
            {scorecard.human_override && (
              <Tooltip
                content={`${scorecard.human_override.auditor_name}, ${formatDate(scorecard.human_override.overridden_at, true)}: ${scorecard.human_override.legal_basis}. Score ${scorecard.human_override.previous_score ?? "–"} → ${scorecard.human_override.new_score}.`}
              >
                <span tabIndex={0} className="chip cursor-help border-accent-line bg-accent-soft text-accent">
                  <Scale size={11} aria-hidden="true" /> Durch Prüfperson übersteuert
                </span>
              </Tooltip>
            )}
            {scorecard.retention && (
              <Tooltip
                content={
                  <>
                    <span className="block font-semibold">Aufbewahrung nach BEG IV</span>
                    <span className="block">
                      Rechnungen und Buchungsbelege {scorecard.retention.years} Jahre ({scorecard.retention.basis}).
                    </span>
                    <span className="block">
                      Kreditinstitute, Versicherungen, Wertpapierinstitute: 10 Jahre (bis{" "}
                      {formatDate(scorecard.retention.financial_sector_until)}).
                    </span>
                    <span className="block">Handelsbücher, Jahresabschlüsse und Verfahrensdokumentation: 10 Jahre (§ 147 Abs. 1 Nr. 1 AO).</span>
                    <span className="mt-1 block text-subtle">Frist ab Schluss des Belegjahres (§ 147 Abs. 4 AO), Ablaufhemmung nach § 147 Abs. 3 Satz 5 AO.</span>
                  </>
                }
              >
                <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 tabular-nums text-muted">
                  <Clock size={11} aria-hidden="true" /> Aufbewahren bis {formatDate(scorecard.retention.until)}
                </span>
              </Tooltip>
            )}
            <span className="text-xs tabular-nums text-subtle">
              Regelwerk {scorecard.ruleset_version}
              {scorecard.small_amount_invoice && " · Kleinbetragsrechnung (§ 33 UStDV)"}
              {scorecard.structured_einvoice_detected && " · E-Rechnung (XML) erkannt"}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {scorecard.tiles.map((tile) => {
          const tileTone = toneForStatus(tile.status);
          const risks = tile.checks.filter((check) => check.deduction > 0 && check.risk_note);
          return (
            <button
              key={tile.key}
              onClick={() => onOpenTile(tile.key)}
              className="group/tile relative rounded-lg border border-line bg-surface-2 p-3 text-left transition-colors duration-150 hover:border-line-strong"
              aria-describedby={risks.length ? `risk-${tile.key}` : undefined}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-subtle">{TILE_LABELS[tile.key]}</span>
                <StatusIcon status={tile.status} size={14} />
              </div>
              <p className={cx("mt-1.5 text-sm font-semibold", tileTone === "neutral" ? "text-fg" : TONE_TEXT[tileTone])}>
                {tile.headline || "–"}
              </p>
              <p className={cx("mt-0.5 text-xs tabular-nums", tile.deduction > 0 ? "text-bad" : "text-subtle")}>
                {tile.deduction > 0 ? (
                  <span className={cx(risks.length > 0 && "underline decoration-dotted underline-offset-2")}>−{tile.deduction} Punkte</span>
                ) : (
                  "keine Abzüge"
                )}
              </p>
              {risks.length > 0 && (
                <span
                  id={`risk-${tile.key}`}
                  role="tooltip"
                  className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-[min(320px,80vw)] rounded-md border border-line bg-surface-solid p-2.5 text-xs font-normal leading-snug text-fg shadow-lg group-hover/tile:block group-focus-visible/tile:block"
                >
                  {risks.map((check) => (
                    <span key={check.id} className="block py-0.5">
                      <span className="tabular-nums text-bad">−{check.deduction}</span> {check.risk_note}
                    </span>
                  ))}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
