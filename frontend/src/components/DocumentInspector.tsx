"use client";

import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type {
  AIActRiskLevel,
  DetectionSource,
  DocumentDetail,
  EInvoiceData,
  LedgerEntry,
  PIIFinding,
  ScoreCheck,
  TextSpan,
  VisualCheck,
} from "../types/api";
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
import { AlertTriangle, Check, CheckCircle, FileCode, FileText, Info, Layers, Lock, MinusCircle, Scale } from "./icons";
import { Chip, CopyValue, EmptyState, HashBadge, Skeleton, StatusIcon, Tabs, Tooltip } from "./ui";

export type InspectorTab = "ustg" | "aiact" | "pii" | "facts" | "xml" | "ledger";

/** Scrollhoehe der Inspektor-Spalten: auf grossen Monitoren (1440p/2K) die volle Hoehe nutzen. */
const PANEL_HEIGHT = "max-h-[600px] xl:max-h-[max(600px,calc(100vh-280px))] 2xl:max-h-[max(780px,calc(100vh-280px))]";

// --- Farbcodierung der PII-Markierungen --------------------------------------
// IBAN/Steuer-IDs cyan, Namen bernstein, Betraege smaragd, Kontakt/Adresse indigo,
// Art.-9-Daten rose; Firmen und Datumsangaben neutral.

type MarkTone = "accent" | "warn" | "ok" | "pii" | "bad" | "neutral";

const SPAN_TONE: Record<string, MarkTone> = {
  iban: "accent",
  vat_id: "accent",
  tax_number: "accent",
  id_number: "accent",
  person: "warn",
  date_of_birth: "warn",
  amount: "ok",
  email: "pii",
  phone: "pii",
  address: "pii",
  art9: "bad",
  org: "neutral",
  date: "neutral",
};

const MARK_VARS: Record<MarkTone, React.CSSProperties> = {
  accent: { "--mark-bg": "var(--accent-soft)", "--mark-fg": "var(--accent)", "--mark-line": "var(--accent-line)" } as React.CSSProperties,
  warn: { "--mark-bg": "var(--warn-soft)", "--mark-fg": "var(--warn)", "--mark-line": "var(--warn-line)" } as React.CSSProperties,
  ok: { "--mark-bg": "var(--ok-soft)", "--mark-fg": "var(--ok)", "--mark-line": "var(--ok-line)" } as React.CSSProperties,
  pii: { "--mark-bg": "var(--pii-soft)", "--mark-fg": "var(--pii)", "--mark-line": "var(--pii-line)" } as React.CSSProperties,
  bad: { "--mark-bg": "var(--bad-soft)", "--mark-fg": "var(--bad)", "--mark-line": "var(--bad-line)" } as React.CSSProperties,
  neutral: { "--mark-bg": "var(--surface-2)", "--mark-fg": "var(--fg)", "--mark-line": "var(--line-strong)" } as React.CSSProperties,
};

const LEGEND: { tone: MarkTone; label: string }[] = [
  { tone: "accent", label: "IBAN / Steuer-ID" },
  { tone: "warn", label: "Name" },
  { tone: "ok", label: "Betrag" },
  { tone: "pii", label: "Kontakt / Adresse" },
  { tone: "bad", label: "Art. 9 DSGVO" },
  { tone: "neutral", label: "Firma / Datum" },
];

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
  xml: "XML-Datensatz",
  xml_rule: "XML-Datensatz + Regelwerk",
};

/** Kurzform der Nachweisherkunft unter dem Status-Chip. */
const SOURCE_SHORT: Record<DetectionSource, string> = {
  llm: "KI",
  rule_based: "Regex",
  both: "KI + Regex",
  xml: "XML",
  xml_rule: "XML + Regex",
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
    <div className={cx(PANEL_HEIGHT, "overflow-y-auto rounded-lg border border-line bg-surface-2 p-4")}>
      <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-[1.75] text-muted">
        {segments.map(({ text, span, key }) =>
          span ? (
            <span key={key} className="group relative">
              <button
                type="button"
                onClick={() => onSpanClick(span)}
                className="pii-mark"
                style={MARK_VARS[SPAN_TONE[span.category] ?? "neutral"]}
                data-active={activeSpan === span.category}
                aria-label={`${span.label}: ${text}`}
              >
                {text}
              </button>
              <span
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-0 z-20 mb-1 hidden w-max max-w-[260px] rounded-md border border-line bg-surface-solid px-2.5 py-1.5 font-sans text-[11px] leading-snug text-fg shadow-lg group-hover:block group-focus-within:block"
              >
                <span className="block font-semibold">{span.label}</span>
                <span className="block text-subtle">Quelle: {SOURCE_LABELS[span.source] ?? span.source}</span>
                <span className="block text-subtle">{span.masked ? "Geschwärzt" : "Nur markiert, nicht geschwärzt"}</span>
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
    <li className="flex items-start gap-3 py-3">
      <span className="mt-0.5"><StatusIcon status={check.status} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-[13px] font-medium text-fg">{check.label}</span>
          {check.deduction > 0 && (
            <Tooltip content={check.risk_note}>
              <span
                tabIndex={check.risk_note ? 0 : undefined}
                className="cursor-help rounded font-mono text-[11px] text-bad underline decoration-dotted underline-offset-2"
                aria-label={`Abzug ${check.deduction} Punkte${check.risk_note ? `: ${check.risk_note}` : ""}`}
              >
                −{check.deduction}
              </span>
            </Tooltip>
          )}
        </div>
        {check.legal_reference && <p className="font-mono text-[11px] text-subtle">{check.legal_reference}</p>}
        {check.detail && <p className="mt-1 text-xs leading-relaxed text-muted">{check.detail}</p>}
        {/* Bei Abzuegen steht die Risikoerklaerung im Tooltip am Abzug; Hinweise ohne Abzug inline. */}
        {check.risk_note && check.deduction === 0 && check.status !== "pass" && (
          <p className="mt-1 text-xs leading-relaxed text-warn">{check.risk_note}</p>
        )}
        {check.note && <p className="mt-1 text-[11.5px] leading-relaxed text-subtle">{check.note}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <Chip tone={toneForStatus(check.status)}>{STATUS_LABELS[check.status]}</Chip>
        {check.evidence_source && (
          <span className="font-mono text-[10px] text-subtle" title={`Herkunft des Nachweises: ${SOURCE_LABELS[check.evidence_source]}`}>
            {SOURCE_SHORT[check.evidence_source]}
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

function OverrideNotice({ document }: { document: DocumentDetail }) {
  const override = document.scorecard?.human_override;
  if (!override) return null;
  return (
    <div className="rounded-lg border border-accent-line bg-accent-soft p-3 text-xs">
      <p className="flex flex-wrap items-center gap-2 font-semibold text-accent">
        <Scale size={13} aria-hidden="true" /> Einstufung durch Prüfperson übersteuert
        <span className="font-mono font-normal tabular-nums">
          {RISK_LABELS[override.previous_risk_level]} → {RISK_LABELS[override.new_risk_level]} · Score{" "}
          {override.previous_score ?? "–"} → {override.new_score}
        </span>
      </p>
      <p className="mt-1.5 leading-relaxed text-fg">{override.reason}</p>
      <p className="mt-1 text-subtle">
        {override.auditor_name} · {formatDate(override.overridden_at, true)} · {override.legal_basis}
      </p>
      {override.ledger_entry_hash && (
        <HashBadge className="mt-2" value={override.ledger_entry_hash} label="Ledger" verified verifiedLabel="Ed25519-signiert" />
      )}
    </div>
  );
}

function AiActPanel({ document, onOverride }: { document: DocumentDetail; onOverride?: () => void }) {
  const ai = document.compliance?.ai_act;
  if (!ai) return <EmptyState icon={<Info size={18} />} title="Noch keine Risikobewertung" />;
  const regulatory = document.scorecard?.tiles.find((tile) => tile.key === "regulatory");
  return (
    <div className="space-y-4">
      <OverrideNotice document={document} />
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
        <p className="max-w-[70ch] whitespace-pre-line text-[13px] leading-relaxed text-muted">{ai.reasoning || "–"}</p>
      </div>

      {regulatory?.checks.map((check) => (
        <ul key={check.id} className="rounded-lg border border-line px-3"><CheckRow check={check} /></ul>
      ))}

      {onOverride && document.status === "extracted" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-3">
          <p className="max-w-[48ch] text-xs leading-relaxed text-muted">
            Trifft die Einstufung nicht zu? Die Prüfperson kann sie mit Begründung und Rechtsnorm übersteuern
            (Art. 14 Abs. 4 lit. d). Der Score wird neu berechnet und signiert protokolliert.
          </p>
          <button type="button" className="btn" onClick={onOverride}>
            <Scale size={14} aria-hidden="true" /> Einstufung übersteuern
          </button>
        </div>
      )}

      {ai.systems.length > 0 && (
        <div>
          <p className="label-caps mb-1">
            Erkannte KI-Systeme{document.scorecard?.human_override ? " · Einstufung des Modells vor der Übersteuerung" : ""}
          </p>
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

/**
 * Summenblock nach Financial-UI-Muster: Bezeichnung links, Betrag rechtsbuendig in
 * Tabellenziffern, Summenstrich vor dem Gesamtbetrag.
 */
function SumBlock({ rows, total, currency, marks }: {
  rows: { label: string; value: string | number | null; mark?: React.ReactNode }[];
  total: { label: string; value: string | number | null; mark?: React.ReactNode };
  currency: string | null;
  marks?: boolean;
}) {
  const line = (label: string, value: string | number | null, mark: React.ReactNode, strong = false) => (
    <div className={cx("grid items-baseline gap-3 px-3 py-1.5", marks ? "grid-cols-[1fr_auto_1.5rem]" : "grid-cols-[1fr_auto]")}>
      <dt className={cx("text-xs", strong ? "font-semibold text-fg" : "text-muted")}>{label}</dt>
      <dd className={cx("text-right font-mono tabular-nums", strong ? "text-[14px] font-semibold text-fg" : "text-[13px] text-fg")}>
        {typeof value === "string" && /[A-Z]{3}$/.test(value) ? value : formatMoney(value, currency)}
      </dd>
      {marks && <span className="flex justify-center">{mark}</span>}
    </div>
  );
  return (
    <dl className="rounded-lg border border-line bg-surface-2 py-1.5" aria-label="Summen">
      {rows.map((row) => <React.Fragment key={row.label}>{line(row.label, row.value, row.mark)}</React.Fragment>)}
      <div className="mx-3 my-1 border-t-2 border-double border-line-strong" aria-hidden="true" />
      {line(total.label, total.value, total.mark, true)}
    </dl>
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
        <Fact label="Belegnummer" value={<CopyValue value={ex.document_number} label="Belegnummer" />} />
        <Fact label="Aussteller" value={ex.sender} />
        <Fact label="Empfänger" value={ex.recipient} />
        <Fact label="Rechnungsdatum" value={formatDate(ex.document_date)} />
        <Fact label="Leistung" value={ex.service_period || (ex.service_date ? formatDate(ex.service_date) : null)} />
        <Fact label="Steuernr. / USt-IdNr." value={[ex.sender_tax_number, ex.sender_vat_id].filter(Boolean).join(" · ")} mono />
        <Fact label="Fällig" value={formatDate(ex.due_date)} />
        <Fact
          label="IBAN"
          value={
            iban && (
              <span className="inline-flex flex-wrap items-center gap-1.5">
                <CopyValue value={ex.iban} display={iban} label="IBAN" />
                <Chip tone={ex.iban_valid ? "ok" : "bad"}>
                  {ex.iban_valid ? <><Check size={11} aria-hidden="true" /> MOD-97</> : "Prüfziffer ungültig"}
                </Chip>
              </span>
            )
          }
        />
      </dl>
      <SumBlock
        currency={ex.currency}
        rows={[
          { label: "Summe netto", value: ex.net_amount },
          { label: `Umsatzsteuer${ex.tax_rate != null ? ` ${ex.tax_rate} %` : ""}`, value: ex.tax_amount },
        ]}
        total={{ label: "Rechnungsbetrag brutto", value: ex.total_amount }}
      />
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


// --- XML-Datensatz (EN 16931) ------------------------------------------------

/** Namen in Proportionalschrift, Kennungen und Beträge in Monospace. */
const NAME_TERMS = new Set(["BT-27", "BT-44"]);
/** Beträge stehen im Summenblock (rechtsbündig), nicht in der Kennungen-Tabelle. */
const MONEY_TERMS = ["BT-109", "BT-110", "BT-115", "BT-112"];
/** Kennungen mit Kopierbutton. */
const COPY_TERMS = new Set(["BT-1", "BT-10", "BT-31"]);

const VISUAL_LABELS: Record<VisualCheck["status"], string> = {
  match: "Bildteil stimmt überein",
  mismatch: "Abweichung im Bildteil",
  not_found: "Im Bildteil nicht gefunden",
};

function VisualMark({ check }: { check: VisualCheck | undefined }) {
  if (!check) return <span className="text-subtle">–</span>;
  const label = check.status === "mismatch" && check.visual_value
    ? `${VISUAL_LABELS.mismatch}: PDF zeigt ${check.visual_value}`
    : VISUAL_LABELS[check.status];
  return (
    <Tooltip content={label}>
      <span tabIndex={0} aria-label={label} className="inline-flex cursor-help">
        {check.status === "match" ? (
          <CheckCircle size={14} className="text-ok" />
        ) : check.status === "mismatch" ? (
          <AlertTriangle size={14} className="text-bad" />
        ) : (
          <MinusCircle size={14} className="text-subtle" />
        )}
      </span>
    </Tooltip>
  );
}

export function einvoiceLabel(einvoice: EInvoiceData): string {
  return einvoice.syntax ? `${einvoice.profile} · ${einvoice.syntax}` : einvoice.profile;
}

function XmlPanel({ document }: { document: DocumentDetail }) {
  const einvoice = document.einvoice;
  if (!einvoice) return <EmptyState icon={<FileCode size={18} />} title="Kein XML-Datensatz" />;
  if (einvoice.error) {
    return (
      <div className="rounded-lg border border-warn-line bg-warn-soft p-3 text-xs text-warn">
        <p className="font-semibold">Eingebettetes XML ({einvoice.attachment_name ?? "unbenannt"}) nicht auswertbar</p>
        <p className="mt-1 leading-relaxed">{einvoice.error}</p>
        <p className="mt-1 leading-relaxed">Geprüft wird deshalb der Bildteil des PDFs.</p>
      </div>
    );
  }
  const embedded = einvoice.source === "embedded";
  const visual = new Map(einvoice.visual_check.map((check) => [check.bt, check]));
  const extraVisual = einvoice.visual_check.filter(
    (check) => !einvoice.business_terms.some((term) => term.bt === check.bt),
  );
  const mismatches = einvoice.visual_check.filter((check) => check.status === "mismatch").length;
  const identifiers = einvoice.business_terms.filter((term) => !MONEY_TERMS.includes(term.bt));
  const money = MONEY_TERMS.map((bt) => einvoice.business_terms.find((term) => term.bt === bt)).filter(
    (term): term is NonNullable<typeof term> => Boolean(term && term.value),
  );
  const moneyRows = money.filter((term) => term.bt !== "BT-112");
  const total = money.find((term) => term.bt === "BT-112");
  return (
    <div className="space-y-4">
      <h3 className="sr-only">XML-Datensatz (EN 16931)</h3>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone={einvoice.is_einvoice ? "accent" : "warn"}>{einvoiceLabel(einvoice)}</Chip>
        <span className="text-subtle">
          {embedded ? `eingebettet als ${einvoice.attachment_name}` : "reines XML"}
          {embedded && " · maßgeblich vor dem Bildteil (BMF 15.10.2024, Rz. 36)"}
        </span>
      </div>
      {!einvoice.is_einvoice && (
        <p className="rounded-lg border border-warn-line bg-warn-soft p-3 text-xs leading-relaxed text-warn">
          Dieses Profil erfüllt nicht die Anforderungen an eine E-Rechnung. Rechnung im Sinne des § 14 UStG ist der Bildteil.
        </p>
      )}
      {embedded && mismatches > 0 && (
        <p role="status" className="rounded-lg border border-bad-line bg-bad-soft p-3 text-xs leading-relaxed text-bad">
          Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz in {mismatches === 1 ? "einem Wert" : `${mismatches} Werten`}.
          Es gilt das XML.
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Business Terms nach EN 16931</caption>
          <thead className="bg-surface-2 text-subtle">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">BT</th>
              <th scope="col" className="px-3 py-2 font-medium">Business Term</th>
              <th scope="col" className="px-3 py-2 font-medium">Wert (XML)</th>
              {embedded && <th scope="col" className="px-3 py-2 text-center font-medium">PDF</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {identifiers.map((term) => (
              <tr key={term.bt}>
                <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-subtle">{term.bt}</td>
                <td className="px-3 py-2 align-top text-muted">{term.label}</td>
                <td
                  className={cx(
                    "px-3 py-2 align-top text-fg [overflow-wrap:anywhere]",
                    NAME_TERMS.has(term.bt) ? "text-[12.5px]" : "font-mono tabular-nums",
                  )}
                >
                  {COPY_TERMS.has(term.bt) && term.value ? <CopyValue value={term.value} label={term.label} /> : term.value ?? "–"}
                </td>
                {embedded && <td className="px-3 py-2 text-center align-top"><VisualMark check={visual.get(term.bt)} /></td>}
              </tr>
            ))}
            {embedded &&
              extraVisual.map((check) => (
                <tr key={check.bt}>
                  <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-subtle">{check.bt}</td>
                  <td className="px-3 py-2 align-top text-muted">{check.label}</td>
                  <td className="px-3 py-2 align-top font-mono tabular-nums text-fg [overflow-wrap:anywhere]">
                    {check.bt === "BT-84" && einvoice.iban ? (
                      <CopyValue value={einvoice.iban} display={check.xml_value} label="IBAN" />
                    ) : (
                      check.xml_value
                    )}
                  </td>
                  <td className="px-3 py-2 text-center align-top"><VisualMark check={check} /></td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {total && (
        <SumBlock
          currency={einvoice.currency}
          marks={embedded}
          rows={moneyRows.map((term) => ({
            label: `${term.bt} · ${term.label}`,
            value: term.value,
            mark: embedded ? <VisualMark check={visual.get(term.bt)} /> : undefined,
          }))}
          total={{
            label: `${total.bt} · ${total.label}`,
            value: total.value,
            mark: embedded ? <VisualMark check={visual.get(total.bt)} /> : undefined,
          }}
        />
      )}

      {einvoice.public_buyer && (
        <div className="rounded-lg border border-line p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="neutral">Öffentlicher Auftraggeber (B2G)</Chip>
            {einvoice.leitweg ? (
              <Chip tone={einvoice.leitweg.valid ? "ok" : "bad"}>
                Leitweg-ID {einvoice.leitweg.valid ? "gültig" : "ungültig"}
              </Chip>
            ) : (
              <Chip tone="bad">Leitweg-ID fehlt</Chip>
            )}
          </div>
          <p className="mt-2 leading-relaxed text-muted">{einvoice.public_buyer_reason}</p>
          {einvoice.leitweg && (
            <p className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-subtle">Leitweg-ID</span>
              <CopyValue value={einvoice.leitweg.value} label="Leitweg-ID" />
            </p>
          )}
          {einvoice.leitweg && !einvoice.leitweg.valid && (
            <p className="mt-1 leading-relaxed text-bad">{einvoice.leitweg.reason}</p>
          )}
        </div>
      )}

      {einvoice.rule_violations.length > 0 && (
        <div>
          <p className="label-caps mb-1">EN-16931-Geschäftsregeln</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-warn">
            {einvoice.rule_violations.map((rule) => <li key={rule}>{rule}</li>)}
          </ul>
        </div>
      )}

      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-[11px] sm:grid-cols-[auto_1fr]">
        <dt className="text-subtle">Spezifikation (BT-24)</dt>
        <dd className="break-all font-mono text-muted">{einvoice.specification_id ?? "–"}</dd>
        <dt className="text-subtle">SHA-256 XML</dt>
        <dd>{einvoice.xml_sha256 ? <HashBadge value={einvoice.xml_sha256} label="XML" /> : "–"}</dd>
      </dl>
      <p className="text-[11px] leading-relaxed text-subtle">
        Geprüft werden Profilkennung, Pflichtfelder und Summenregeln. Eine Validierung gegen XSD und Schematron
        (KoSIT-Validator) ist nicht Teil dieser Prüfung.
      </p>
    </div>
  );
}

// --- Ledger-Historie ---------------------------------------------------------

const EVENT_LABELS: Record<string, string> = {
  analysis: "Analyse",
  sign_off: "Prüfer-Siegel",
  human_override: "Übersteuerung (Art. 14)",
};

function LedgerPanel({ document }: { document: DocumentDetail }) {
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Neu laden, sobald sich der Pruefstand aendert (Analyse, Siegel, Override).
  const version = `${document.id}|${document.updated_at}|${document.sign_off?.ledger_entry_hash ?? ""}|${document.scorecard?.human_override?.ledger_entry_hash ?? ""}`;

  useEffect(() => {
    let cancelled = false;
    setEntries(null);
    setError(null);
    api
      .trail(document.id)
      .then((result) => !cancelled && setEntries(result.items))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [document.id, version]);

  if (error) return <EmptyState icon={<Layers size={18} />} title="Ledger nicht abrufbar">{error}</EmptyState>;
  if (!entries) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Ledger wird geladen">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (entries.length === 0) return <EmptyState icon={<Layers size={18} />} title="Noch keine Ledger-Einträge" />;

  return (
    <div className="space-y-2">
    <h3 className="label-caps">Ledger-Historie · neueste zuerst</h3>
    <ol className="space-y-2" aria-label="Ledger-Historie, neueste zuerst">
      {entries.map((entry) => {
        const milestone = entry.event_type === "sign_off" || entry.event_type === "human_override";
        const details = entry.details ?? {};
        const actor = typeof details.auditor_name === "string" ? details.auditor_name : entry.model_name;
        return (
          <li
            key={entry.entry_id}
            className={cx(
              "rounded-lg border p-3 text-xs",
              milestone ? "border-accent-line bg-accent-soft/40" : "border-line",
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="font-mono text-[11px] tabular-nums text-subtle">#{entry.seq}</span>
                <span className="font-semibold text-fg">{EVENT_LABELS[entry.event_type] ?? entry.event_type}</span>
                {milestone && <Chip tone="accent">Prüfer-Meilenstein</Chip>}
              </span>
              <span className="font-mono text-[11px] tabular-nums text-subtle">{formatDate(entry.timestamp_utc, true)}</span>
            </div>
            <p className="mt-1 text-muted">{entry.result_summary}</p>
            {entry.event_type === "human_override" && (
              <p className="mt-1 text-subtle">
                {String(details.legal_basis ?? "")} – {String(details.reason ?? "")}
              </p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-subtle">{actor}</span>
              {entry.compliance_score != null && (
                <span className="font-mono tabular-nums text-subtle">Score {entry.compliance_score}</span>
              )}
              <HashBadge value={entry.entry_hash} label="Eintrag" />
              {entry.signature_status === "valid" && <Chip tone="ok">Ed25519 gültig</Chip>}
              {entry.signature_status === "invalid" && <Chip tone="bad">Signatur ungültig</Chip>}
            </div>
          </li>
        );
      })}
    </ol>
    </div>
  );
}

const LEVEL_LABELS = { strict: "Strikt", standard: "Standard", audit_only: "Audit-Only" } as const;

export function DocumentInspector({ document, tab, onTabChange, onOverride }: {
  document: DocumentDetail;
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onOverride?: () => void;
}) {
  const [activeSpan, setActiveSpan] = useState<string | null>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const overrideHash = document.scorecard?.human_override?.ledger_entry_hash;
  // Nach einer Uebersteuerung den Hinweis oben im Panel sichtbar machen.
  useEffect(() => {
    if (overrideHash) panelRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [overrideHash]);
  const formal = document.scorecard?.tiles.find((t) => t.key === "formal");
  const failures = formal?.checks.filter((c) => c.status === "fail").length ?? 0;

  return (
    <section className="card p-4" aria-label="Dokumenten-Inspektor">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-fg">Dokumenten-Inspektor</h2>
          {document.einvoice && !document.einvoice.error && (
            <button
              type="button"
              onClick={() => onTabChange("xml")}
              className={cx("chip transition-colors duration-150 hover:border-accent", TONE_CLASSES[document.einvoice.is_einvoice ? "accent" : "warn"])}
              title="XML-Datensatz anzeigen"
            >
              <FileCode size={12} aria-hidden="true" />
              {einvoiceLabel(document.einvoice)}
            </button>
          )}
        </div>
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
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-subtle" aria-label="Legende der Markierungen">
            {LEGEND.map(({ tone, label }) => (
              <li key={label} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-[3px]"
                  style={{ ...MARK_VARS[tone], background: "var(--mark-fg)", opacity: 0.75 }}
                  aria-hidden="true"
                />
                {label}
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <Tabs<InspectorTab>
            active={tab}
            onChange={onTabChange}
            tabs={[
              { key: "ustg", label: "§ 14 UStG", badge: failures ? <span className="font-mono text-[10px] text-bad">{failures}</span> : undefined },
              { key: "aiact", label: "AI Act", title: "EU AI Act (VO (EU) 2024/1689)" },
              { key: "pii", label: "PII", title: "PII-Befunde (DSGVO)", badge: <span className="font-mono text-[10px] text-subtle">{document.compliance?.gdpr.findings.length ?? 0}</span> },
              { key: "facts", label: "Kerndaten" },
              ...(document.einvoice ? [{ key: "xml" as const, label: "XML-Datensatz", title: "XML-Datensatz (EN 16931)" }] : []),
              { key: "ledger", label: "Ledger", title: "Ledger-Historie (Prüfprotokoll)" },
            ]}
          />
          <div ref={panelRef} key={tab} role="tabpanel" className={cx(PANEL_HEIGHT, "anim-fade overflow-y-auto pt-3")}>
            {tab === "ustg" &&
              (formal ? (
                <ul className="divide-y divide-line">{formal.checks.map((check) => <CheckRow key={check.id} check={check} />)}</ul>
              ) : (
                <EmptyState icon={<Info size={18} />} title="Noch keine § 14-Prüfung" />
              ))}
            {tab === "aiact" && <AiActPanel document={document} onOverride={onOverride} />}
            {tab === "pii" && <PiiPanel document={document} highlight={activeSpan} />}
            {tab === "facts" && <FactsPanel document={document} />}
            {tab === "xml" && <XmlPanel document={document} />}
            {tab === "ledger" && <LedgerPanel document={document} />}
          </div>
        </div>
      </div>
    </section>
  );
}
