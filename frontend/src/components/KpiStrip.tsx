"use client";

import React from "react";
import type { KpiResponse } from "../types/api";
import { cx, TONE_TEXT, toneForBand, type Tone } from "../lib/format";
import { Skeleton } from "./ui";

type EdgeTone = "pass" | "warn" | "fail" | "neutral";

/**
 * Status als feine Innenkante oben in der Kachel (Muster aus interner Vorlage).
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

function Kpi({ label, value, context, title, edge, valueClass, loading }: {
  label: string;
  value: React.ReactNode;
  context: React.ReactNode;
  title?: string;
  edge: EdgeTone;
  valueClass?: string;
  loading: boolean;
}) {
  return (
    <div className={cx("card px-4 py-3.5 hover:border-line-strong dark:hover:border-white/[0.16] 2xl:px-5 2xl:py-4", EDGE[edge])} title={title}>
      <p className="label-caps">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <p className={cx("mt-1 font-mono text-2xl font-semibold leading-tight tabular-nums text-fg 2xl:text-[28px]", valueClass)}>
          {value}
        </p>
      )}
      <p className="mt-1 truncate text-xs text-subtle">{context}</p>
    </div>
  );
}

const percent = (value: number) => `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;

export function KpiStrip({ kpis, loading }: { kpis: KpiResponse | null; loading: boolean }) {
  const showSkeleton = loading && !kpis;
  const avgTone = toneForBand(kpis?.average_band);
  const highRisk = Boolean(kpis && kpis.high_risk_count > 0);
  const quote = kpis && kpis.documents_total > 0 ? (kpis.documents_analyzed / kpis.documents_total) * 100 : null;

  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 2xl:gap-4" aria-label="Portfolio-Kennzahlen">
      <Kpi
        loading={showSkeleton}
        label="Geprüfte Dokumente"
        value={kpis ? kpis.documents_analyzed : "–"}
        edge={quote === 100 ? "pass" : "neutral"}
        title={
          kpis
            ? `${kpis.documents_total} erfasst · ${kpis.sealed_count} versiegelt${kpis.reference_count ? ` · ${kpis.reference_count} Referenz-Audits` : ""}`
            : undefined
        }
        context={
          kpis ? (
            <>
              <span className="font-mono tabular-nums">{quote != null ? percent(quote) : "–"}</span> Prüfquote ·{" "}
              <span className="font-mono tabular-nums">{kpis.sealed_count}</span> versiegelt · GoBD-verankert
            </>
          ) : (
            "keine Verbindung"
          )
        }
      />
      <Kpi
        loading={showSkeleton}
        label="Ø Compliance-Score"
        value={kpis?.average_score != null ? <>{kpis.average_score}<span className="text-sm font-normal text-subtle"> / 100</span></> : "–"}
        valueClass={kpis?.average_score != null ? TONE_TEXT[avgTone] : undefined}
        edge={EDGE_FOR_TONE[avgTone]}
        context={
          <>
            deterministisches Regelwerk{" "}
            {kpis?.ruleset_version && <span className="font-mono tabular-nums">{kpis.ruleset_version}</span>}
          </>
        }
      />
      <Kpi
        loading={showSkeleton}
        label="Geschützte PII-Elemente"
        value={kpis ? kpis.pii_elements_masked : "–"}
        valueClass="text-pii"
        edge="neutral"
        context="maskiert gespeichert · Art. 25 DSGVO"
      />
      <Kpi
        loading={showSkeleton}
        label="High-Risk-Quote"
        value={kpis ? percent(kpis.high_risk_quota) : "–"}
        valueClass={kpis ? (highRisk ? "text-warn" : "text-ok") : undefined}
        edge={kpis ? (highRisk ? "warn" : "pass") : "neutral"}
        title="Anteil der Dokumente mit Hochrisiko-KI-System nach Art. 6 Abs. 2 i. V. m. Anhang III VO (EU) 2024/1689"
        context={
          kpis ? (
            <>
              <span className="font-mono tabular-nums">{kpis.high_risk_count}</span> × Anhang III · Pflichten ab 02.12.2027
            </>
          ) : (
            "keine Verbindung"
          )
        }
      />
    </section>
  );
}
