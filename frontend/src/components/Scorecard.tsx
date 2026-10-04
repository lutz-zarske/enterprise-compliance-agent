"use client";

import React from "react";
import type { Scorecard as ScorecardType, ScoreTile } from "../types/api";
import { cx, TONE_CLASSES, TONE_TEXT, toneForBand, toneForStatus } from "../lib/format";
import { Calculator, Fingerprint, Lock, Scale, ShieldAlert } from "./icons";
import { StatusIcon } from "./ui";

const TILE_META: Record<ScoreTile["key"], { label: string; icon: React.ReactNode }> = {
  formal: { label: "§ 14 UStG Status", icon: <Scale size={14} /> },
  regulatory: { label: "EU AI Act Risikostufe", icon: <ShieldAlert size={14} /> },
  privacy: { label: "DSGVO Integrität", icon: <Fingerprint size={14} /> },
  math: { label: "Finanzmathematik", icon: <Calculator size={14} /> },
};

const RING_COLORS = { ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)", neutral: "var(--fg-subtle)" } as const;

function ScoreRing({ score, tone }: { score: number; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - score / 100);
  return (
    <div className="relative h-28 w-28 shrink-0">
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--line)" strokeWidth="7" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={RING_COLORS[tone]}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cx("font-mono text-3xl font-semibold tabular-nums leading-none", TONE_TEXT[tone])}>{score}</span>
        <span className="mt-0.5 font-mono text-[11px] text-subtle">/ 100</span>
      </div>
    </div>
  );
}

interface Props {
  scorecard: ScorecardType;
  sealed: boolean;
  onOpenTile: (key: ScoreTile["key"]) => void;
}

export function Scorecard({ scorecard, sealed, onOpenTile }: Props) {
  const tone = toneForBand(scorecard.band);
  return (
    <section className="card p-4" aria-label="Compliance-Scorecard">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <ScoreRing score={scorecard.score} tone={tone === "pii" || tone === "accent" ? "neutral" : tone} />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="label-caps">Compliance-Score</span>
            <span className={cx("chip", TONE_CLASSES[tone])}>{scorecard.band_label}</span>
            {sealed && (
              <span className="chip border-ok-line bg-ok-soft text-ok">
                <Lock size={11} /> Versiegelt
              </span>
            )}
          </div>
          <p className={cx("text-lg font-semibold leading-snug", scorecard.release_blocked ? "text-bad" : "text-ok")}>
            {scorecard.release_recommendation}
          </p>
          {scorecard.cap_applied && <p className="text-xs text-warn">{scorecard.cap_applied}</p>}
          <p className="font-mono text-[11px] text-subtle">
            Regelwerk {scorecard.ruleset_version}
            {scorecard.small_amount_invoice && " · Kleinbetragsrechnung (§ 33 UStDV)"}
            {scorecard.structured_einvoice_detected && " · E-Rechnung (XML) erkannt"}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {scorecard.tiles.map((tile) => {
          const tileTone = toneForStatus(tile.status);
          const meta = TILE_META[tile.key];
          return (
            <button
              key={tile.key}
              onClick={() => onOpenTile(tile.key)}
              className="rounded-lg border border-line bg-surface-2 p-3 text-left transition-colors duration-150 hover:border-line-strong"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-[11px] font-medium text-subtle">
                  {meta.icon}
                  {meta.label}
                </span>
                <StatusIcon status={tile.status} size={14} />
              </div>
              <p className={cx("mt-1.5 text-[13px] font-semibold", TONE_TEXT[tileTone] === "text-subtle" ? "text-fg" : TONE_TEXT[tileTone])}>
                {tile.headline || "–"}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-subtle">
                {tile.deduction > 0 ? `−${tile.deduction} Punkte` : "keine Abzüge"}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}
