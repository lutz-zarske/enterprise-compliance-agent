"use client";

import React from "react";
import type { KpiResponse } from "../types/api";
import { cx, TONE_TEXT, toneForBand } from "../lib/format";
import { Skeleton } from "./ui";

function Kpi({ label, value, sub, valueClass, loading }: {
  label: string;
  value: React.ReactNode;
  sub: string;
  valueClass?: string;
  loading: boolean;
}) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-[12px] font-medium text-subtle">{label}</p>
      {loading ? (
        <Skeleton className="mt-1.5 h-7 w-20" />
      ) : (
        <p className={cx("mt-0.5 font-mono text-2xl font-semibold leading-tight text-fg", valueClass)}>{value}</p>
      )}
      <p className="mt-0.5 truncate text-[11.5px] text-subtle">{sub}</p>
    </div>
  );
}

export function KpiStrip({ kpis, loading }: { kpis: KpiResponse | null; loading: boolean }) {
  const avgTone = toneForBand(kpis?.average_band);
  const quotaTone = !kpis || kpis.high_risk_count === 0 ? "ok" : "bad";
  const showSkeleton = loading && !kpis;
  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Portfolio-Kennzahlen">
      <Kpi
        loading={showSkeleton}
        label="Geprüfte Dokumente"
        value={kpis ? kpis.documents_analyzed : "–"}
        sub={
          kpis
            ? `${kpis.documents_total} erfasst · ${kpis.sealed_count} versiegelt${kpis.reference_count ? ` · ${kpis.reference_count} Referenz` : ""}`
            : "keine Verbindung"
        }
      />
      <Kpi
        loading={showSkeleton}
        label="Ø Compliance-Score"
        value={kpis?.average_score != null ? <>{kpis.average_score}<span className="text-sm font-normal text-subtle"> / 100</span></> : "–"}
        valueClass={kpis?.average_score != null ? TONE_TEXT[avgTone] : undefined}
        sub={`deterministisches Regelwerk ${kpis?.ruleset_version ?? ""}`.trim()}
      />
      <Kpi
        loading={showSkeleton}
        label="Geschützte PII-Elemente"
        value={kpis ? kpis.pii_elements_masked : "–"}
        valueClass="text-pii"
        sub="maskiert gespeichert (Art. 25 DSGVO)"
      />
      <Kpi
        loading={showSkeleton}
        label="High-Risk-Quote"
        value={kpis ? `${kpis.high_risk_quota.toLocaleString("de-DE")} %` : "–"}
        valueClass={kpis ? TONE_TEXT[quotaTone] : undefined}
        sub={kpis ? `${kpis.high_risk_count} × EU AI Act Anhang III` : "keine Verbindung"}
      />
    </section>
  );
}
