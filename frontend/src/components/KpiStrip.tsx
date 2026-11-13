"use client";

import React from "react";
import type { KpiResponse } from "../types/api";
import { cx, TONE_TEXT, toneForBand, type Tone } from "../lib/format";
import { Info } from "./icons";
import { Skeleton, Tooltip } from "./ui";

type EdgeTone = "pass" | "warn" | "fail" | "neutral";

/**
 * Status als feine Innenkante oben in der Kachel.
 * Im hellen Modus traegt nur die Kontur den Ton; die Lichtkante gilt im Dark Mode.
 */
const EDGE: Record<EdgeTone, string> = {
  pass: "border-ok-line dark:border-emerald-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(16,185,129,0.09)]",
  warn: "border-warn-line dark:border-amber-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(245,158,11,0.09)]",
  fail: "border-bad-line dark:border-rose-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(244,63,94,0.09)]",
  neutral: "dark:border-white/[0.08] dark:shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]",
};

const EDGE_FOR_TONE: Record<Tone, EdgeTone> = {
  ok: "pass",
  warn: "warn",
  bad: "fail",
  pii: "neutral",
  accent: "neutral",
  neutral: "neutral",
};

function Kpi({ label, value, info, edge, valueClass, loading }: {
  label: string;
  value: React.ReactNode;
  /** Regulatorischer Kontext, im (i)-Tooltip statt als Fliesstext unter der Zahl. */
  info: React.ReactNode;
  edge: EdgeTone;
  valueClass?: string;
  loading: boolean;
}) {
  return (
    <div className={cx("card relative flex h-16 items-center justify-between gap-3 px-4 2xl:px-5", EDGE[edge])}>
      <p className="label-caps flex min-w-0 items-center gap-1.5">
        <span className="truncate">{label}</span>
        <Tooltip content={info} side="bottom">
          <button type="button" className="shrink-0 rounded-full text-subtle transition-colors duration-150 hover:text-fg" aria-label={`Kontext: ${label}`}>
            <Info size={13} aria-hidden="true" />
          </button>
        </Tooltip>
      </p>
      {loading ? (
        <Skeleton className="h-6 w-16" />
      ) : (
        <p className={cx("shrink-0 zahl-display text-xl font-semibold leading-none tabular-nums text-fg 2xl:text-2xl", valueClass)}>{value}</p>
      )}
    </div>
  );
}

const percent = (value: number) => `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;

export function KpiStrip({ kpis, loading }: { kpis: KpiResponse | null; loading: boolean }) {
  const showSkeleton = loading && !kpis;
  const avgTone = toneForBand(kpis?.average_band);
  const highRisk = Boolean(kpis && kpis.high_risk_count > 0);
  // Ohne geprüften Beleg gibt es keine Quote - kein grünes "0 %" als Scheinbefund.
  const hasQuota = Boolean(kpis && kpis.documents_analyzed > 0);
  const quote = kpis && kpis.documents_total > 0 ? (kpis.documents_analyzed / kpis.documents_total) * 100 : null;

  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:gap-4" aria-label="Portfolio-Kennzahlen">
      <Kpi
        loading={showSkeleton}
        label="Geprüfte Dokumente"
        value={kpis ? kpis.documents_analyzed : "–"}
        edge={quote === 100 ? "pass" : "neutral"}
        info={
          <>
            <span className="block">Jede Analyse im SHA-256-Ledger · Siegel Ed25519-signiert · unveränderbare Historie (GoBD).</span>
            {kpis && (
              <span className="mt-1 block tabular-nums text-subtle">
                Prüfquote {quote != null ? percent(quote) : "–"} · {kpis.documents_total} erfasst · {kpis.sealed_count} versiegelt
                {kpis.reference_count ? ` · ${kpis.reference_count} Referenz-Audits` : ""}
              </span>
            )}
          </>
        }
      />
      <Kpi
        loading={showSkeleton}
        label="Ø Compliance-Score"
        value={kpis?.average_score != null ? <>{kpis.average_score}<span className="text-sm font-normal text-subtle"> / 100</span></> : "–"}
        valueClass={kpis?.average_score != null ? TONE_TEXT[avgTone] : undefined}
        edge={EDGE_FOR_TONE[avgTone]}
        info={
          <>
            Deterministisches Regelwerk nach § 14 UStG &amp; ZUGFeRD EN 16931
            {kpis?.ruleset_version && <span className="mt-1 block tabular-nums text-subtle">Regelwerk {kpis.ruleset_version}</span>}
          </>
        }
      />
      <Kpi
        loading={showSkeleton}
        label="Geschützte PII-Elemente"
        value={kpis ? kpis.pii_elements_masked : "–"}
        valueClass="text-pii"
        edge="neutral"
        info="Vertraulichkeits-Gateway: Personen-, IBAN- und Kontaktdaten maskiert gespeichert gem. Art. 25 DSGVO."
      />
      <Kpi
        loading={showSkeleton}
        label="High-Risk-Quote"
        value={kpis && hasQuota ? percent(kpis.high_risk_quota) : "–"}
        valueClass={hasQuota ? (highRisk ? "text-warn" : "text-ok") : undefined}
        edge={hasQuota ? (highRisk ? "warn" : "pass") : "neutral"}
        info={
          <>
            Anteil der Dokumente mit Hochrisiko-Einstufung gem. VO (EU) 2024/1689 Anhang III.
            {kpis && (
              <span className="mt-1 block text-subtle">
                <span className="tabular-nums">{kpis.high_risk_count}</span> × Anhang III · Pflichten ab 02.12.2027
              </span>
            )}
          </>
        }
      />
    </section>
  );
}
