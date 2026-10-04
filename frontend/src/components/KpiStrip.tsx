"use client";

import React from "react";
import type { KpiResponse } from "../types/api";
import { cx, TONE_TEXT, toneForBand } from "../lib/format";
import { FileText, Fingerprint, Scale, ShieldAlert } from "./icons";

function Kpi({ icon, label, value, sub, valueClass }: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub: string;
  valueClass?: string;
}) {
  return (
    <div className="card flex items-center gap-3 px-4 py-3">
      <div className="rounded-lg border border-line bg-surface-2 p-2 text-subtle">{icon}</div>
      <div className="min-w-0">
        <p className="label-caps">{label}</p>
        <p className={cx("font-mono text-xl font-semibold tabular-nums leading-tight text-fg", valueClass)}>{value}</p>
        <p className="truncate text-[11px] text-subtle">{sub}</p>
      </div>
    </div>
  );
}

export function KpiStrip({ kpis }: { kpis: KpiResponse | null }) {
  const avgTone = toneForBand(kpis?.average_band);
  const quotaTone = !kpis || kpis.high_risk_count === 0 ? "ok" : "bad";
  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Portfolio-Kennzahlen">
      <Kpi
        icon={<FileText size={16} />}
        label="Geprüfte Dokumente"
        value={kpis ? kpis.documents_analyzed : "–"}
        sub={kpis ? `${kpis.documents_total} erfasst · ${kpis.sealed_count} versiegelt` : "keine Daten"}
      />
      <Kpi
        icon={<Scale size={16} />}
        label="Ø Compliance-Score"
        value={kpis?.average_score != null ? <>{kpis.average_score}<span className="text-sm text-subtle"> / 100</span></> : "–"}
        valueClass={kpis?.average_score != null ? TONE_TEXT[avgTone] : undefined}
        sub="deterministisches Regelwerk 2025.1"
      />
      <Kpi
        icon={<Fingerprint size={16} />}
        label="Geschützte PII-Elemente"
        value={kpis ? kpis.pii_elements_masked : "–"}
        valueClass="text-pii"
        sub="maskiert gespeichert (DSGVO Art. 25)"
      />
      <Kpi
        icon={<ShieldAlert size={16} />}
        label="High-Risk-Quote"
        value={kpis ? `${kpis.high_risk_quota.toLocaleString("de-DE")} %` : "–"}
        valueClass={kpis ? TONE_TEXT[quotaTone] : undefined}
        sub={kpis ? `${kpis.high_risk_count} × EU AI Act Anhang III` : "keine Daten"}
      />
    </section>
  );
}
