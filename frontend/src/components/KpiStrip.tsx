"use client";

import React from "react";
import type { KpiResponse } from "../types/api";
import { cx, TONE_TEXT, toneForBand, type Tone } from "../lib/format";
import { LOCALE_TAG, useI18n } from "../lib/i18n";
import { Info } from "./icons";
import { Skeleton, Tooltip } from "./ui";

type EdgeTone = "pass" | "warn" | "fail" | "neutral";

/**
 * Status als feine Innenkante oben in der Kachel.
 * Im hellen Modus trägt nur die Kontur den Ton; die Lichtkante gilt im Dark Mode.
 */
const EDGE: Record<EdgeTone, string> = {
  pass: "dark:border-emerald-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(16,185,129,0.09)]",
  warn: "dark:border-amber-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(245,158,11,0.09)]",
  fail: "dark:border-rose-500/[0.14] dark:shadow-[inset_0_1px_0_0_rgba(244,63,94,0.09)]",
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
  info: React.ReactNode;
  edge: EdgeTone;
  valueClass?: string;
  loading: boolean;
}) {
  const { tr } = useI18n();
  return (
    <div className={cx("card relative flex min-h-16 items-center justify-between gap-3 px-4 py-2.5 2xl:px-5", EDGE[edge])}>
      <p className="label-caps flex min-w-0 items-center gap-1.5 leading-tight">
        <span className="min-w-0 break-words">{label}</span>
        <Tooltip content={info} side="bottom">
          <button
            type="button"
            className="icon-target -my-1 shrink-0 rounded-full text-subtle transition-colors duration-150 hover:text-fg"
            aria-label={tr(`Hinweis zu ${label}`, `Info: ${label}`, `Info: ${label}`)}
          >
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

export function KpiStrip({ kpis, loading }: { kpis: KpiResponse | null; loading: boolean }) {
  const { locale, tr } = useI18n();
  const percent = (value: number) => `${value.toLocaleString(LOCALE_TAG[locale], { maximumFractionDigits: 1 })} %`;
  const showSkeleton = loading && !kpis;
  const avgTone = toneForBand(kpis?.average_band);
  const highRisk = Boolean(kpis && kpis.high_risk_count > 0);
  const hasQuota = Boolean(kpis && kpis.documents_analyzed > 0);
  const quote = kpis && kpis.documents_total > 0 ? (kpis.documents_analyzed / kpis.documents_total) * 100 : null;

  // Ab xl in den Spalten der Workbench darunter: die erste Kachel so breit wie die Belegliste,
  // die drei übrigen teilen sich die Inspektor-Spalte (gleiche Abstände).
  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:gap-4 xl:grid-cols-[340px_repeat(3,minmax(0,1fr))] 2xl:grid-cols-[400px_repeat(3,minmax(0,1fr))] 2xl:gap-5" aria-label={tr("Portfolio-Kennzahlen", "Portfolio KPIs", "Métricas de cartera")}>
      <Kpi
        loading={showSkeleton}
        label={tr("Geprüfte Dokumente", "Audited Documents", "Documentos auditados")}
        value={kpis ? kpis.documents_analyzed : "–"}
        edge={quote === 100 ? "pass" : "neutral"}
        info={
          <>
            <span className="block">
              {tr(
                "Belege mit abgeschlossener Prüfung. Jede Prüfung wird fälschungssicher protokolliert.",
                "Documents with a completed audit. Every audit is logged tamper-proof.",
                "Documentos con auditoría terminada. Cada auditoría queda registrada a prueba de manipulaciones.",
              )}
            </span>
            {kpis && (
              <span className="mt-1 block tabular-nums text-subtle">
                {tr("Prüfquote", "Coverage", "Cobertura")} {quote != null ? percent(quote) : "–"} · {kpis.documents_total} {tr("erfasst", "stored", "registrados")} · {kpis.sealed_count} {tr("versiegelt", "sealed", "sellados")}
                {kpis.reference_count ? ` · ${kpis.reference_count} ${tr("Referenz-Audits", "reference audits", "auditorías de ref.")}` : ""}
              </span>
            )}
          </>
        }
      />
      <Kpi
        loading={showSkeleton}
        label={tr("Ø Compliance-Score", "Avg Compliance Score", "Puntuación media")}
        value={kpis?.average_score != null ? <>{kpis.average_score}<span className="text-sm font-normal text-subtle"> / 100</span></> : "–"}
        valueClass={kpis?.average_score != null ? TONE_TEXT[avgTone] : undefined}
        edge={EDGE_FOR_TONE[avgTone]}
        info={
          <>
            <span className="block">
              {tr(
                "Durchschnitt aller geprüften Belege. Die Punkte vergeben feste Regeln, nicht die KI.",
                "Average across all audited documents. Points are awarded by fixed rules, not by the AI.",
                "Media de todos los documentos auditados. Los puntos los asignan reglas fijas, no la IA.",
              )}
            </span>
            {kpis?.ruleset_version && <span className="mt-1 block tabular-nums text-subtle">{tr("Regelwerk", "Ruleset", "Reglamento")} {kpis.ruleset_version}</span>}
          </>
        }
      />
      <Kpi
        loading={showSkeleton}
        label={tr("Geschützte PII-Elemente", "Protected PII Items", "Elementos PII protegidos")}
        value={kpis ? kpis.pii_elements_masked : "–"}
        valueClass="text-pii"
        edge="neutral"
        info={tr(
          "Erkannte personenbezogene Angaben wie Namen, IBANs und Kontaktdaten. Sie werden nur geschwärzt gespeichert.",
          "Detected personal details such as names, IBANs and contact data. They are stored only in redacted form.",
          "Datos personales detectados, como nombres, IBAN y datos de contacto. Solo se guardan ocultos.",
        )}
      />
      <Kpi
        loading={showSkeleton}
        label={tr("High-Risk-Quote", "High-Risk Ratio", "Tasa de alto riesgo")}
        value={kpis && hasQuota ? percent(kpis.high_risk_quota) : "–"}
        valueClass={hasQuota ? (highRisk ? "text-warn" : "text-ok") : undefined}
        edge={hasQuota ? (highRisk ? "warn" : "pass") : "neutral"}
        info={
          <>
            {tr(
              "Anteil der Belege zu KI-Systemen mit hohem Risiko, etwa zur Bewerberauswahl. Für sie gelten ab 02.12.2027 strenge Pflichten (EU AI Act).",
              "Share of documents about high-risk AI systems, e.g. for screening applicants. Strict duties apply to them from 2 Dec 2027 (EU AI Act).",
              "Porcentaje de documentos sobre sistemas de IA de alto riesgo, p. ej. para seleccionar candidatos. Desde el 02.12.2027 tienen obligaciones estrictas (Reglamento de IA).",
            )}
            {kpis && (
              <span className="mt-1 block text-subtle">
                <span className="tabular-nums">{kpis.high_risk_count}</span> × {tr("Anhang III", "Annex III", "Anexo III")}
              </span>
            )}
          </>
        }
      />
    </section>
  );
}
