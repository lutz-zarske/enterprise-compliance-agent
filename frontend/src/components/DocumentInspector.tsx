"use client";

import React, { useMemo, useState } from "react";
import type { AIActRiskLevel, DocumentDetail, PIIFinding, ScoreCheck, TextSpan } from "../types/api";
import {
  cx,
  DOC_TYPE_LABELS,
  formatDate,
  formatMoney,
  RISK_LABELS,
  STATUS_LABELS,
  TONE_CLASSES,
  toneForRisk,
  toneForStatus,
} from "../lib/format";
import { FileText, Info, Lock } from "./icons";
import { Chip, EmptyState, StatusIcon, Tabs } from "./ui";

export type InspectorTab = "ustg" | "aiact" | "pii" | "facts";

// --- Farbcodierung der PII-Markierungen --------------------------------------

const SPAN_STYLE: Record<string, string> = {
  iban: "bg-accent-soft text-accent border-accent-line",
  vat_id: "bg-accent-soft text-accent border-accent-line",
  tax_number: "bg-accent-soft text-accent border-accent-line",
  id_number: "bg-accent-soft text-accent border-accent-line",
  address: "bg-warn-soft text-warn border-warn-line",
  person: "bg-bad-soft text-bad border-bad-line",
  date_of_birth: "bg-bad-soft text-bad border-bad-line",
  art9: "bg-bad-soft text-bad border-bad-line font-semibold",
  email: "bg-pii-soft text-pii border-pii-line",
  phone: "bg-pii-soft text-pii border-pii-line",
  org: "bg-surface-2 text-fg border-line-strong",
  amount: "bg-surface-2 text-fg border-line-strong",
  date: "bg-surface-2 text-fg border-line-strong",
};

/** Welche Befund-Kategorien eine Textmarkierung im PII-Ledger hervorhebt. */
const SPAN_TO_FINDINGS: Record<string, (finding: PIIFinding) => boolean> = {
  iban: (f) => f.category === "bank_account",
  email: (f) => f.category === "contact_data",
  phone: (f) => f.category === "contact_data",
  person: (f) => f.category === "name",
  address: (f) => f.category === "address",
  id_number: (f) => ["id_document_number", "social_security_number", "tax_identification_number"].includes(f.category),
  date_of_birth: (f) => f.category === "date_of_birth",
  art9: (f) => f.is_special_category,
};

const SOURCE_LABELS: Record<string, string> = {
  rule_based: "Regelwerk (Regex)",
  llm: "KI-Modell",
  both: "KI-Modell + Regelwerk",
};

function TextViewer({ document, activeSpan, onSpanClick }: {
  document: DocumentDetail;
  activeSpan: string | null;
  onSpanClick: (span: TextSpan) => void;
}) {
  const view = document.text_view;
  const segments = useMemo(() => {
    if (!view) return [];
    const parts: { text: string; span?: TextSpan; key: string }[] = [];
    let cursor = 0;
    view.spans.forEach((span, index) => {
      if (span.start > cursor) parts.push({ text: view.text.slice(cursor, span.start), key: `t${index}` });
      parts.push({ text: view.text.slice(span.start, span.end), span, key: `s${index}` });
      cursor = span.end;
    });
    if (cursor < view.text.length) parts.push({ text: view.text.slice(cursor), key: "tail" });
    return parts;
  }, [view]);

  if (!view) {
    return <EmptyState icon={<FileText size={18} />} title="Kein Textlayer gespeichert" />;
  }

  return (
    <div className="max-h-[620px] overflow-y-auto rounded-lg border border-line bg-surface-2 p-4">
      <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.75] text-muted">
        {segments.map(({ text, span, key }) =>
          span ? (
            <span key={key} className="group relative">
              <button
                type="button"
                onClick={() => onSpanClick(span)}
                className={cx(
                  "rounded border px-0.5 transition-colors duration-150",
                  SPAN_STYLE[span.category] ?? SPAN_STYLE.org,
                  activeSpan === span.category && "ring-1 ring-current",
                )}
              >
                {text}
              </button>
              <span
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-0 z-20 mb-1 hidden w-max max-w-[260px] rounded-md border border-line bg-surface-solid px-2 py-1.5 font-sans text-[11px] leading-snug text-fg shadow-lg group-hover:block"
              >
                <span className="block font-semibold">{span.label}</span>
                <span className="block text-subtle">Quelle: {SOURCE_LABELS[span.source] ?? span.source}</span>
                <span className="block text-subtle">{span.masked ? "Geschwärzt" : "Nur markiert (nicht geschwärzt)"}</span>
              </span>
            </span>
          ) : (
            <React.Fragment key={key}>{text}</React.Fragment>
          ),
        )}
      </pre>
      {view.truncated && <p className="mt-3 text-[11px] text-subtle">Ansicht auf 20.000 Zeichen gekürzt.</p>}
    </div>
  );
}

// --- Rechte Spalte -----------------------------------------------------------

function CheckRow({ check }: { check: ScoreCheck }) {
  return (
    <li className="flex items-start gap-3 py-2.5">
      <StatusIcon status={check.status} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[13px] font-medium text-fg">{check.label}</span>
          {check.deduction > 0 && <span className="font-mono text-[11px] text-bad">−{check.deduction}</span>}
        </div>
        {check.legal_reference && <p className="font-mono text-[11px] text-subtle">{check.legal_reference}</p>}
        {check.detail && <p className="mt-0.5 text-xs text-muted">{check.detail}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <Chip tone={toneForStatus(check.status)}>{STATUS_LABELS[check.status]}</Chip>
        {check.evidence_source && (
          <span className="font-mono text-[10px] text-subtle" title="Herkunft des Nachweises">
            {check.evidence_source === "both" ? "KI + Regex" : check.evidence_source === "llm" ? "KI" : "Regex"}
          </span>
        )}
      </div>
    </li>
  );
}

const PYRAMID: { level: AIActRiskLevel; label: string; sub: string; width: string }[] = [
  { level: "unacceptable", label: "Unannehmbar", sub: "Art. 5", width: "w-[40%]" },
  { level: "high", label: "Hohes Risiko", sub: "Anhang III", width: "w-[60%]" },
  { level: "limited", label: "Begrenztes Risiko", sub: "Art. 50", width: "w-[80%]" },
  { level: "minimal", label: "Minimales Risiko", sub: "Art. 4 / 95", width: "w-full" },
];

function AiActPanel({ document }: { document: DocumentDetail }) {
  const ai = document.compliance?.ai_act;
  if (!ai) return <EmptyState icon={<Info size={18} />} title="Noch keine Risikobewertung" />;
  const regulatory = document.scorecard?.tiles.find((tile) => tile.key === "regulatory");
  return (
    <div className="space-y-4">
      <div className="flex flex-col items-center gap-1 py-2" aria-label="EU AI Act Risikopyramide">
        {PYRAMID.map((layer) => {
          const active = ai.overall_risk_level === layer.level;
          return (
            <div
              key={layer.level}
              className={cx(
                "flex items-center justify-between rounded-md border px-3 py-1.5 text-xs",
                layer.width,
                active ? TONE_CLASSES[toneForRisk(layer.level)] : "border-line bg-surface-2 text-subtle",
              )}
            >
              <span className={cx("whitespace-nowrap", active && "font-semibold")}>{layer.label}</span>
              <span className="ml-2 hidden whitespace-nowrap font-mono text-[10px] opacity-80 sm:inline">{layer.sub}</span>
            </div>
          );
        })}
        {ai.overall_risk_level === "not_applicable" && (
          <p className="mt-1 text-xs text-ok">Kein KI-System im Sinne von Art. 3 Nr. 1 beschrieben.</p>
        )}
      </div>

      <div>
        <p className="label-caps mb-1">Begründung der KI</p>
        <p className="whitespace-pre-line text-[13px] leading-relaxed text-muted">{ai.reasoning || "–"}</p>
      </div>

      {regulatory?.checks.map((check) => (
        <ul key={check.id} className="rounded-lg border border-line px-3"><CheckRow check={check} /></ul>
      ))}

      {ai.systems.length > 0 && (
        <div>
          <p className="label-caps mb-1">Erkannte KI-Systeme</p>
          <ul className="space-y-2">
            {ai.systems.map((system, index) => (
              <li key={index} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-fg">{system.name || "Unbenanntes System"}</span>
                  <Chip tone={toneForRisk(system.risk_level)}>{RISK_LABELS[system.risk_level]}</Chip>
                </div>
                {system.purpose && <p className="mt-1 text-xs text-muted">{system.purpose}</p>}
                {system.annex_iii_labels.map((label) => (
                  <Chip key={label} tone="bad" className="mr-1 mt-2">{label}</Chip>
                ))}
                {system.evidence && <p className="mt-2 border-l-2 border-line pl-2 text-xs italic text-subtle">„{system.evidence}“</p>}
                <p className="mt-1 font-mono text-[10px] text-subtle">Konfidenz {(system.confidence * 100).toFixed(0)} %</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {ai.obligations.length > 0 && (
        <div>
          <p className="label-caps mb-1">Folgepflichten</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
            {ai.obligations.map((obligation, index) => <li key={index}>{obligation}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function PiiPanel({ document, highlight }: { document: DocumentDetail; highlight: string | null }) {
  const gdpr = document.compliance?.gdpr;
  const gateway = document.compliance?.privacy_gateway;
  if (!gdpr) return <EmptyState icon={<Lock size={18} />} title="Noch kein DSGVO-Audit" />;
  const matcher = highlight ? SPAN_TO_FINDINGS[highlight] : undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone={gdpr.contains_special_categories ? "bad" : gdpr.findings.length ? "pii" : "ok"}>
          DSGVO-Risiko: {gdpr.risk_level}
        </Chip>
        <span className="text-subtle">{gdpr.findings.length} Fundstellen · gespeichert ausschließlich maskiert</span>
      </div>
      {gateway && Object.keys(gateway).length > 0 && (
        <div className="rounded-lg border border-pii-line bg-pii-soft p-3 text-xs text-pii">
          <p className="font-semibold">Privacy Gateway aktiv – vor dem Cloud-Aufruf pseudonymisiert:</p>
          <p className="mt-1 font-mono">
            {Object.entries(gateway).map(([category, count]) => `${category} ×${count}`).join(" · ")}
          </p>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-2 text-subtle">
            <tr>
              <th className="px-3 py-2 font-medium">Kategorie</th>
              <th className="px-3 py-2 font-medium">Wert (maskiert)</th>
              <th className="px-3 py-2 font-medium">Quelle</th>
              <th className="px-3 py-2 font-medium">Konfidenz</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {gdpr.findings.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-subtle">Keine personenbezogenen Daten erkannt.</td></tr>
            )}
            {gdpr.findings.map((finding, index) => {
              const active = matcher?.(finding) ?? false;
              return (
                <tr key={index} className={cx("transition-colors duration-150", active && "bg-accent-soft")}>
                  <td className="px-3 py-2 align-top">
                    <span className="text-fg">{finding.category_label}</span>
                    {finding.is_special_category && <Chip tone="bad" className="ml-1">Art. 9/10</Chip>}
                  </td>
                  <td className="break-all px-3 py-2 align-top font-mono text-muted">{finding.masked_value || "–"}</td>
                  <td className="px-3 py-2 align-top">
                    <Chip tone={finding.source === "both" ? "ok" : finding.source === "llm" ? "pii" : "accent"}>
                      {finding.source === "both" ? "KI + Regex" : finding.source === "llm" ? "KI" : "Regex"}
                    </Chip>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-14 rounded-full bg-line">
                        <div className="h-1.5 rounded-full bg-pii" style={{ width: `${Math.round(finding.confidence * 100)}%` }} />
                      </div>
                      <span className="font-mono text-[11px] text-subtle">{Math.round(finding.confidence * 100)} %</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {gdpr.recommendations.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
          {gdpr.recommendations.map((recommendation, index) => <li key={index}>{recommendation}</li>)}
        </ul>
      )}
    </div>
  );
}

function Fact({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="label-caps">{label}</dt>
      <dd className={cx("mt-0.5 break-words text-[13px] text-fg", mono && "font-mono text-xs")}>{value || "–"}</dd>
    </div>
  );
}

function FactsPanel({ document }: { document: DocumentDetail }) {
  const ex = document.extraction;
  if (!ex) return <EmptyState icon={<FileText size={18} />} title="Noch keine Extraktion" />;
  const math = document.scorecard?.tiles.find((tile) => tile.key === "math");
  const iban = ex.iban ? `${ex.iban.slice(0, 4)} •••• ${ex.iban.slice(-4)}` : null;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Fact label="Dokumenttyp" value={DOC_TYPE_LABELS[ex.doc_type]} />
        <Fact label="Belegnummer" value={ex.document_number} mono />
        <Fact label="Aussteller" value={ex.sender} />
        <Fact label="Empfänger" value={ex.recipient} />
        <Fact label="Rechnungsdatum" value={formatDate(ex.document_date)} />
        <Fact label="Leistung" value={ex.service_period || (ex.service_date ? formatDate(ex.service_date) : null)} />
        <Fact label="Steuernr. / USt-IdNr." value={[ex.sender_tax_number, ex.sender_vat_id].filter(Boolean).join(" · ")} mono />
        <Fact label="Fällig" value={formatDate(ex.due_date)} />
        <Fact label="Netto" value={formatMoney(ex.net_amount, ex.currency)} mono />
        <Fact label="USt" value={ex.tax_amount != null ? `${formatMoney(ex.tax_amount, ex.currency)}${ex.tax_rate != null ? ` (${ex.tax_rate} %)` : ""}` : null} mono />
        <Fact label="Brutto" value={formatMoney(ex.total_amount, ex.currency)} mono />
        <Fact
          label="IBAN"
          value={iban && <span>{iban} <Chip tone={ex.iban_valid ? "ok" : "bad"} className="ml-1">{ex.iban_valid ? "MOD-97 ✓" : "ungültig"}</Chip></span>}
          mono
        />
      </dl>
      {ex.summary && (
        <div>
          <p className="label-caps mb-1">Zusammenfassung</p>
          <p className="text-[13px] leading-relaxed text-muted">{ex.summary}</p>
        </div>
      )}
      {math && (
        <div>
          <p className="label-caps">Mathematische Validität</p>
          <ul className="divide-y divide-line">{math.checks.map((check) => <CheckRow key={check.id} check={check} />)}</ul>
        </div>
      )}
      {ex.issues.length > 0 && (
        <div>
          <p className="label-caps mb-1">Auffälligkeiten</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{ex.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

const LEVEL_LABELS = { strict: "Strikt", standard: "Standard", audit_only: "Audit-Only" } as const;

export function DocumentInspector({ document, tab, onTabChange }: {
  document: DocumentDetail;
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}) {
  const [activeSpan, setActiveSpan] = useState<string | null>(null);
  const formal = document.scorecard?.tiles.find((t) => t.key === "formal");
  const failures = formal?.checks.filter((c) => c.status === "fail").length ?? 0;

  return (
    <section className="card p-4" aria-label="Dokumenten-Inspektor">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-fg">Dokumenten-Inspektor</h2>
        {document.text_view && (
          <span className="chip border-line bg-surface-2 text-subtle">
            Maskierung: {LEVEL_LABELS[document.text_view.level]} · {document.text_view.spans.length} Markierungen
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="min-w-0">
          <TextViewer
            document={document}
            activeSpan={activeSpan}
            onSpanClick={(span) => {
              setActiveSpan(span.category);
              onTabChange("pii");
            }}
          />
          <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px]">
            <span className="chip border-accent-line bg-accent-soft text-accent">IBAN / Steuer-ID</span>
            <span className="chip border-pii-line bg-pii-soft text-pii">Kontakt</span>
            <span className="chip border-warn-line bg-warn-soft text-warn">Adresse</span>
            <span className="chip border-bad-line bg-bad-soft text-bad">Name / Art. 9</span>
            <span className="chip border-line-strong bg-surface-2 text-fg">Firma / Betrag / Datum</span>
          </div>
        </div>
        <div className="min-w-0">
          <Tabs<InspectorTab>
            active={tab}
            onChange={onTabChange}
            tabs={[
              { key: "ustg", label: "§ 14 UStG", badge: failures ? <span className="font-mono text-[10px] text-bad">{failures}</span> : undefined },
              { key: "aiact", label: "EU AI Act" },
              { key: "pii", label: "PII-Ledger", badge: <span className="font-mono text-[10px] text-subtle">{document.compliance?.gdpr.findings.length ?? 0}</span> },
              { key: "facts", label: "Kerndaten" },
            ]}
          />
          <div className="max-h-[600px] overflow-y-auto pt-3">
            {tab === "ustg" &&
              (formal ? (
                <ul className="divide-y divide-line">{formal.checks.map((check) => <CheckRow key={check.id} check={check} />)}</ul>
              ) : (
                <EmptyState icon={<Info size={18} />} title="Noch keine § 14-Prüfung" />
              ))}
            {tab === "aiact" && <AiActPanel document={document} />}
            {tab === "pii" && <PiiPanel document={document} highlight={activeSpan} />}
            {tab === "facts" && <FactsPanel document={document} />}
          </div>
        </div>
      </div>
    </section>
  );
}
