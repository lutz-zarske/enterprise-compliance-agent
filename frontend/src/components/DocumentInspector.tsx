"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import {
  buildEvidence,
  evidenceLabel,
  evidenceTone,
  TILE_TABS,
  toneLabel,
  worstTone,
  type EvidenceIndex,
  type EvidenceTone,
} from "../lib/evidence";
import { useI18n } from "../lib/i18n";
import type {
  AIActRiskLevel,
  DetectionSource,
  DocumentDetail,
  EInvoiceData,
  LedgerVerification,
  PIIFinding,
  ScoreCheck,
  TextSpan,
  TextView,
  VatVerification,
  VisualCheck,
} from "../types/api";
import {
  checkStatusLabel,
  cx,
  docTypeLabel,
  formatDate,
  formatMoney,
  localizePageMarker,
  riskLabel,
  TONE_CLASSES,
  TONE_TEXT,
  toneForRisk,
  toneForStatus,
} from "../lib/format";
import {
  AlertTriangle,
  Check,
  CheckCircle,
  Crosshair,
  FileCode,
  FileText,
  Info,
  Lock,
  MinusCircle,
  RefreshCw,
  Scale,
  Link,
  Stamp,
} from "./icons";
import { Chip, CopyValue, EmptyState, HashBadge, Kbd, Spinner, StatusIcon, Tabs, Tooltip, useModifierLabel } from "./ui";

export type InspectorTab = "ustg" | "aiact" | "pii" | "facts" | "xml";

/** Scrollhoehe der Inspektor-Spalten: auf grossen Monitoren (1440p/2K) die volle Hoehe nutzen. */
/**
 * Feste Workbench-Hoehe statt max-h: Beim Reiterwechsel bleibt die Spalte gleich hoch,
 * die Action-Leiste darunter springt um keinen Pixel. Inhalte scrollen im Panel.
 */
const PANEL_HEIGHT = "h-[560px] min-h-[480px] xl:h-[max(560px,calc(100vh-320px))] 2xl:h-[max(720px,calc(100vh-320px))]";

function useSourceLabels(): { long: Record<string, string>; short: Record<DetectionSource, string> } {
  const { tr } = useI18n();
  return {
    long: {
      rule_based: tr("Regelwerk (Regex)", "Ruleset (Regex)", "Reglamento (Regex)"),
      llm: tr("KI-Modell", "AI Model", "Modelo IA"),
      both: tr("KI-Modell + Regelwerk", "AI Model + Ruleset", "Modelo IA + Reglamento"),
      xml: tr("XML-Datensatz", "XML Dataset", "Conjunto XML"),
      xml_rule: tr("XML-Datensatz + Regelwerk", "XML Dataset + Ruleset", "Conjunto XML + Reglamento"),
    },
    short: {
      llm: tr("KI", "AI", "IA"),
      rule_based: "Regex",
      both: tr("KI + Regex", "AI + Regex", "IA + Regex"),
      xml: "XML",
      xml_rule: "XML + Regex",
    },
  };
}

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

const SWATCH: Record<EvidenceTone | "pii", string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  pii: "bg-pii",
};

// --- Kopplung Kriterium <-> Fundstelle ----------------------------------------

interface EvidenceApi {
  index: EvidenceIndex;
  active: string[];
  hover: (ids: string[] | null) => void;
  locate: (id: string) => void;
}

const EvidenceContext = createContext<EvidenceApi | null>(null);

/** Container-relatives Scrollen: bewegt nur die Spalte, nie die ganze Seite. */
function scrollWithin(container: HTMLElement | null, target: Element | null | undefined) {
  if (!container || !target) return;
  const box = container.getBoundingClientRect();
  const rect = target.getBoundingClientRect();
  const top = container.scrollTop + rect.top - box.top - container.clientHeight / 2 + rect.height / 2;
  container.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

// --- Belegansicht (links) ------------------------------------------------------

interface Row {
  parts: { text: string; spanIndex?: number }[];
}

function TextViewer({ view, evidenceLines, evidenceTone: tone, activeSpans, activeCategory, anchored, scrollNonce, onSpanClick, onLineHover, onLineClick }: {
  view: TextView | null;
  evidenceLines: Set<number>;
  evidenceTone: EvidenceTone | null;
  activeSpans: Set<number>;
  activeCategory: string | null;
  anchored: Map<number, string[]>;
  scrollNonce: number;
  onSpanClick: (span: TextSpan) => void;
  onLineHover: (line: number | null) => void;
  onLineClick: (line: number) => void;
}) {
  const { tr, td } = useI18n();
  const sources = useSourceLabels();
  const containerRef = useRef<HTMLDivElement>(null);

  // Zeilen mit eingebetteten Markierungen; Markierungen ueber Zeilengrenzen werden geteilt.
  const rows = useMemo<Row[]>(() => {
    if (!view) return [];
    const { text, spans } = view;
    const result: Row[] = [];
    let first = 0;
    let start = 0;
    for (let i = 0; i <= text.length; i += 1) {
      if (i < text.length && text[i] !== "\n") continue;
      const end = i;
      const parts: Row["parts"] = [];
      while (first < spans.length && spans[first].end <= start) first += 1;
      let cursor = start;
      for (let k = first; k < spans.length && spans[k].start < end; k += 1) {
        const a = Math.max(spans[k].start, start);
        const b = Math.min(spans[k].end, end);
        if (a > cursor) parts.push({ text: text.slice(cursor, a) });
        if (b > a) parts.push({ text: text.slice(a, b), spanIndex: k });
        cursor = Math.max(cursor, b);
      }
      if (cursor < end) parts.push({ text: text.slice(cursor, end) });
      result.push({ parts });
      start = i + 1;
    }
    return result;
  }, [view]);

  useEffect(() => {
    if (!scrollNonce) return;
    scrollWithin(containerRef.current, containerRef.current?.querySelector("[data-evidence]"));
  }, [scrollNonce]);

  if (!view) {
    return <EmptyState icon={<FileText size={18} />} title={tr("Kein Textlayer gespeichert", "No text layer stored", "No hay capa de texto guardada")} />;
  }

  const lineFrom = (target: EventTarget | null): number | null => {
    const element = target instanceof Element ? target.closest<HTMLElement>("[data-line]") : null;
    return element ? Number(element.dataset.line) : null;
  };

  return (
    <div ref={containerRef} className={cx(PANEL_HEIGHT, "scroll-area relative rounded-lg border border-line bg-surface-2 p-4")}>
      <pre
        className="whitespace-pre-wrap break-words font-mono text-[13px] leading-[1.75] text-muted"
        onMouseOver={(event) => {
          const line = lineFrom(event.target);
          onLineHover(line != null && anchored.has(line) ? line : null);
        }}
        onMouseLeave={() => onLineHover(null)}
        onClick={(event) => {
          if (event.target instanceof Element && event.target.closest(".pii-mark")) return;
          const line = lineFrom(event.target);
          if (line != null && anchored.has(line)) onLineClick(line);
        }}
      >
        {rows.map((row, index) => (
          <span
            key={index}
            className="doc-line"
            data-line={index}
            data-anchor={anchored.has(index) || undefined}
            data-evidence={evidenceLines.has(index) && tone ? tone : undefined}
          >
            {row.parts.map((part, partIndex) => {
              if (part.spanIndex === undefined) return <React.Fragment key={partIndex}>{localizePageMarker(part.text)}</React.Fragment>;
              const span = view.spans[part.spanIndex];
              const label = td(span.label);
              return (
                <Tooltip
                  key={partIndex}
                  inline
                  content={
                    <span className="font-sans">
                      <span className="block font-semibold">{label}</span>
                      <span className="block text-subtle">{tr("Quelle:", "Source:", "Fuente:")} {sources.long[span.source] ?? span.source}</span>
                      <span className="block text-subtle">
                        {span.masked ? tr("Geschwärzt", "Redacted", "Ocultado") : tr("Nur markiert, nicht geschwärzt", "Highlighted only, not redacted", "Solo resaltado, sin ocultar")}
                      </span>
                    </span>
                  }
                >
                  <button
                    type="button"
                    onClick={() => onSpanClick(span)}
                    className="pii-mark"
                    data-art9={span.category === "art9" || undefined}
                    data-active={activeCategory === span.category || activeSpans.has(part.spanIndex)}
                    aria-label={`${label}: ${part.text}`}
                  >
                    {part.text}
                  </button>
                </Tooltip>
              );
            })}
          </span>
        ))}
      </pre>
      {view.truncated && <p className="mt-3 text-xs text-subtle">{tr("Ansicht auf 20.000 Zeichen gekürzt.", "View truncated to 20,000 characters.", "Vista truncada a 20 000 caracteres.")}</p>}
    </div>
  );
}

// --- Rechte Spalte -----------------------------------------------------------

function CheckRow({ check, children }: { check: ScoreCheck; children?: React.ReactNode }) {
  const { tr, td } = useI18n();
  const sources = useSourceLabels();
  const evidence = useContext(EvidenceContext);
  const found = evidence?.index.byCheck.get(check.id);
  const active = evidence?.active.includes(check.id) ?? false;
  const tone = evidenceTone(check.status, check.evidence_source);
  const label = td(check.label);
  const detailText = td(check.detail);
  const riskText = td(check.risk_note);
  const noteText = td(check.note);
  return (
    <li
      data-check-id={check.id}
      onMouseEnter={() => evidence?.hover([check.id])}
      onMouseLeave={() => evidence?.hover(null)}
      className={cx(
        "-mx-2 flex items-start gap-3 rounded-lg px-2 py-3 transition-[background-color,box-shadow] duration-150 ease-out",
        active && "bg-surface-2 ring-1 ring-inset ring-line-strong",
      )}
    >
      <span className="mt-0.5"><StatusIcon status={check.status} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-sm font-medium text-fg">{label}</span>
          {check.deduction > 0 && (
            <Tooltip content={riskText}>
              <span
                tabIndex={riskText ? 0 : undefined}
                className="cursor-help rounded text-xs tabular-nums text-bad underline decoration-dotted underline-offset-2"
                aria-label={tr(`Abzug ${check.deduction} Punkte${riskText ? `: ${riskText}` : ""}`, `Deduction ${check.deduction} pts${riskText ? `: ${riskText}` : ""}`, `Deducción ${check.deduction} pts${riskText ? `: ${riskText}` : ""}`)}
              >
                −{check.deduction}
              </span>
            </Tooltip>
          )}
        </div>
        {check.legal_reference && <p className="text-xs text-subtle">{check.legal_reference}</p>}
        {detailText && <p className="mt-1 text-xs leading-relaxed text-muted">{detailText}</p>}
        {/* Bei Abzuegen steht die Risikoerklaerung im Tooltip am Abzug; Hinweise ohne Abzug inline. */}
        {riskText && check.deduction === 0 && check.status !== "pass" && (
          <p className="mt-1 text-xs leading-relaxed text-warn">{riskText}</p>
        )}
        {noteText && <p className="mt-1 text-xs leading-relaxed text-subtle">{noteText}</p>}
        {children}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <Chip tone={toneForStatus(check.status)}>{checkStatusLabel(check.status)}</Chip>
        {check.evidence_source && (
          <span className="text-xs text-subtle" title={`${tr("Herkunft des Nachweises:", "Evidence source:", "Origen de la evidencia:")} ${sources.long[check.evidence_source]}`}>
            {sources.short[check.evidence_source]}
          </span>
        )}
        {found && tone && (
          <button
            type="button"
            onClick={() => evidence?.locate(check.id)}
            onFocus={() => evidence?.hover([check.id])}
            onBlur={() => evidence?.hover(null)}
            className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-xs text-subtle transition-colors duration-150 ease-out hover:bg-surface-2 hover:text-fg"
            aria-label={`${label}: ${tr("Fundstelle im Beleg zeigen", "Locate evidence in document", "Localizar evidencia en el documento")}`}
            title={`${toneLabel(check)} · ${found.lines.length === 1 ? tr("1 Fundstelle", "1 occurrence", "1 coincidencia") : tr(`${found.lines.length} Fundstellen`, `${found.lines.length} occurrences`, `${found.lines.length} coincidencias`)} ${tr("im Beleg", "in document", "en el documento")}`}
          >
            <Crosshair size={12} aria-hidden="true" />
            <span className="tabular-nums">{found.lines.length}</span>
          </button>
        )}
      </div>
    </li>
  );
}

// --- VIES-Pruefung der USt-IdNr. (BT-31) ---------------------------------------

/** Zerlegt „DE 312 345 678“ in Laendercode und Nummer; geschwaerzte Werte sind nicht abfragbar. */
function parseVatId(raw: string | null | undefined): { country: string; number: string } | null | "masked" {
  if (!raw) return null;
  if (/[*•[\]]/.test(raw)) return "masked";
  const compact = raw.replace(/[\s.\-/]/g, "").toUpperCase();
  const match = /^([A-Z]{2})([0-9A-Z+*]{2,12})$/.exec(compact);
  return match ? { country: match[1], number: match[2] } : null;
}

function ViesCheck({ document }: { document: DocumentDetail }) {
  const { tr } = useI18n();
  const raw = document.einvoice?.seller.vat_id || document.extraction?.sender_vat_id || null;
  const parsed = parseVatId(raw);
  const [state, setState] = useState<{ status: "idle" | "busy" } | { status: "done"; result: VatVerification } | { status: "error"; message: string }>({ status: "idle" });

  useEffect(() => setState({ status: "idle" }), [document.id, raw]);

  if (parsed === null) {
    return document.extraction?.sender_tax_number ? (
      <p className="mt-2 text-xs text-subtle">{tr("Nur Steuernummer angegeben – VIES prüft ausschließlich USt-IdNr.", "Tax ID only – VIES only checks EU VAT IDs.", "Solo NIF local – VIES solo verifica números de IVA intracomunitarios.")}</p>
    ) : null;
  }
  if (parsed === "masked") {
    return <p className="mt-2 text-xs text-subtle">{tr("USt-IdNr. liegt nur geschwärzt vor – keine VIES-Abfrage möglich.", "VAT ID is redacted – cannot query VIES.", "ID de IVA oculto – no se puede consultar VIES.")}</p>;
  }

  async function verify() {
    if (parsed === null || parsed === "masked") return;
    setState({ status: "busy" });
    try {
      setState({ status: "done", result: await api.verifyVat(parsed.country, parsed.number) });
    } catch (err) {
      setState({ status: "error", message: err instanceof ApiError ? err.message : String(err) });
    }
  }

  const disclaimer = tr(
    "Momentaufnahme der EU-Kommission (VIES): nicht gespeichert, ohne Einfluss auf den Score. Übertragen werden nur Ländercode und Nummer. Die qualifizierte Bestätigung nach § 18e UStG erteilt das BZSt.",
    "Live snapshot from European Commission VIES: not stored, does not affect score. Only country code and VAT number are transmitted.",
    "Consulta puntual de la Comisión Europea (VIES): no se almacena ni altera la puntuación. Solo se envía país y número.",
  );

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-2">
      <span className="label-caps">BT-31</span>
      <CopyValue value={`${parsed.country}${parsed.number}`} label={tr("USt-IdNr.", "VAT ID", "IVA")} className="text-xs text-fg" />
      <span className="ml-auto flex flex-wrap items-center gap-2">
        {state.status === "done" && (
          <Tooltip
            align="right"
            content={
              <>
                <span className="block font-semibold">
                  {state.result.valid ? tr("Laut VIES gültig", "Valid in VIES", "Válido en VIES") : tr("Laut VIES nicht gültig", "Invalid in VIES", "No válido en VIES")}
                  {state.result.request_date && (
                    <span className="font-normal tabular-nums"> · {formatDate(state.result.request_date, true)}</span>
                  )}
                </span>
                {state.result.name ? (
                  <span className="block">{state.result.name}</span>
                ) : (
                  <span className="block text-subtle">
                    {tr("Kein Name übermittelt (Deutschland gibt über VIES keine Namen heraus).", "No trader name returned (Germany does not publish company names via VIES).", "Sin nombre (Alemania no devuelve nombres mediante VIES).")}
                  </span>
                )}
                {!state.result.valid && (
                  <span className="mt-1 block text-bad">
                    {tr("Beim Lieferanten verifizieren – eine unzutreffende Angabe kann den Vorsteuerabzug gefährden (§ 15 UStG).", "Verify with supplier – an invalid VAT ID risks input VAT deduction (§ 15 UStG).", "Verificar con proveedor – un número no válido pone en riesgo la deducción de IVA.")}
                  </span>
                )}
                <span className="mt-1 block text-subtle">{disclaimer}</span>
              </>
            }
          >
            <span tabIndex={0} className={cx("chip cursor-help", TONE_CLASSES[state.result.valid ? "ok" : "bad"])}>
              {state.result.valid ? <Check size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
              {state.result.valid ? tr("VIES bestätigt", "VIES confirmed", "VIES confirmado") : tr("VIES: nicht gültig", "VIES: invalid", "VIES: no válido")}
            </span>
          </Tooltip>
        )}
        {state.status === "error" && (
          <Tooltip align="right" content={state.message}>
            <span tabIndex={0} className={cx("chip cursor-help", TONE_CLASSES.warn)}>
              <AlertTriangle size={12} aria-hidden="true" /> {tr("VIES nicht erreichbar", "VIES unreachable", "VIES no disponible")}
            </span>
          </Tooltip>
        )}
        <Tooltip align="right" content={state.status === "idle" ? disclaimer : null}>
          <button type="button" className="btn h-7 px-2 text-xs" onClick={() => void verify()} disabled={state.status === "busy"}>
            {state.status === "busy" ? <Spinner size={12} /> : state.status === "idle" ? <Check size={12} aria-hidden="true" /> : <RefreshCw size={12} aria-hidden="true" />}
            {state.status === "idle" || state.status === "busy" ? tr("Bei VIES prüfen", "Verify via VIES", "Verificar VIES") : tr("Erneut prüfen", "Re-verify", "Reverificar")}
          </button>
        </Tooltip>
      </span>
    </div>
  );
}

function OverrideNotice({ document }: { document: DocumentDetail }) {
  const { tr } = useI18n();
  const override = document.scorecard?.human_override;
  if (!override) return null;
  return (
    <div className="rounded-lg border border-accent-line bg-accent-soft p-3 text-xs">
      <p className="flex flex-wrap items-center gap-2 font-semibold text-accent">
        <Scale size={13} aria-hidden="true" /> {tr("Einstufung durch Prüfperson übersteuert", "Classification overridden by auditor", "Clasificación anulada por auditor")}
        <span className="font-normal tabular-nums">
          {riskLabel(override.previous_risk_level)} → {riskLabel(override.new_risk_level)} · Score{" "}
          {override.previous_score ?? "–"} → {override.new_score}
        </span>
      </p>
      <p className="mt-1.5 leading-relaxed text-fg">{override.reason}</p>
      <p className="mt-1 text-subtle">
        {override.auditor_name} · <span className="tabular-nums">{formatDate(override.overridden_at, true)}</span> · {override.legal_basis}
      </p>
      {override.ledger_entry_hash && (
        <HashBadge className="mt-2" value={override.ledger_entry_hash} label="Ledger" verified verifiedLabel={tr("Ed25519-signiert", "Ed25519-signed", "Firmado Ed25519")} />
      )}
    </div>
  );
}

function AiActPanel({ document, onOverride }: { document: DocumentDetail; onOverride?: () => void }) {
  const { tr, td } = useI18n();
  const ai = document.compliance?.ai_act;
  if (!ai) return <EmptyState icon={<Info size={18} />} title={tr("Noch keine Risikobewertung", "No risk assessment yet", "Sin evaluación de riesgo")} />;
  const pyramid: { level: AIActRiskLevel; label: string; sub: string; width: string }[] = [
    { level: "unacceptable", label: tr("Unannehmbar", "Unacceptable", "Inaceptable"), sub: "Art. 5", width: "w-[40%]" },
    { level: "high", label: tr("Hohes Risiko", "High Risk", "Alto riesgo"), sub: tr("Anhang III", "Annex III", "Anexo III"), width: "w-[60%]" },
    { level: "limited", label: tr("Begrenztes Risiko", "Limited Risk", "Riesgo limitado"), sub: "Art. 50", width: "w-[80%]" },
    { level: "minimal", label: tr("Minimales Risiko", "Minimal Risk", "Riesgo mínimo"), sub: "Art. 4 / 95", width: "w-full" },
  ];
  const regulatory = document.scorecard?.tiles.find((tile) => tile.key === "regulatory");
  return (
    <div className="space-y-4">
      <OverrideNotice document={document} />
      <div className="flex flex-col items-center gap-1 py-2" aria-label={tr("EU AI Act Risikopyramide", "EU AI Act Risk Pyramid", "Pirámide de riesgo IA")}>
        {pyramid.map((layer) => {
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
              <span className="ml-2 hidden whitespace-nowrap text-xs opacity-80 sm:inline">{layer.sub}</span>
            </div>
          );
        })}
        {ai.overall_risk_level === "not_applicable" && (
          <p className="mt-1 text-xs text-ok">{tr("Kein KI-System im Sinne von Art. 3 Nr. 1 beschrieben.", "No AI system within the meaning of Art. 3(1) described.", "Ningún sistema de IA según el art. 3(1).")}</p>
        )}
      </div>

      <div>
        <p className="label-caps mb-1">{tr("Begründung der KI", "AI Reasoning", "Justificación de la IA")}</p>
        <p className="max-w-[70ch] whitespace-pre-line text-sm leading-relaxed text-muted">{ai.reasoning || "–"}</p>
      </div>

      {regulatory && (
        <ul className="rounded-lg border border-line px-3">
          {regulatory.checks.map((check) => <CheckRow key={check.id} check={check} />)}
        </ul>
      )}

      {onOverride && document.status === "extracted" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-3">
          <p className="max-w-[52ch] text-xs leading-relaxed text-muted">
            {tr(
              "Trifft die Einstufung nicht zu? Die Prüfperson kann sie mit Begründung und Rechtsnorm übersteuern (Art. 14 Abs. 4 lit. d). Der Score wird neu berechnet und signiert protokolliert.",
              "Classification incorrect? An auditor can override it with a documented reason and legal basis (Art. 14(4)(d)). Score is recalculated and Ed25519-logged.",
              "¿Clasificación incorrecta? El auditor puede anularla con justificación y base legal (Art. 14(4)(d)).",
            )}
          </p>
          <button type="button" className="btn" onClick={onOverride}>
            <Scale size={14} aria-hidden="true" /> {tr("Einstufung übersteuern", "Override Classification", "Anular clasificación")}
          </button>
        </div>
      )}

      {ai.systems.length > 0 && (
        <div>
          <p className="label-caps mb-1">
            {tr("Erkannte KI-Systeme", "Detected AI Systems", "Sistemas de IA detectados")}
            {document.scorecard?.human_override ? tr(" · Einstufung des Modells vor der Übersteuerung", " · Model rating prior to override", " · Clasificación del modelo previa") : ""}
          </p>
          <ul className="space-y-2">
            {ai.systems.map((system, index) => (
              <li key={index} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-fg">{system.name || tr("Unbenanntes System", "Unnamed system", "Sistema sin nombre")}</span>
                  <Chip tone={toneForRisk(system.risk_level)}>{riskLabel(system.risk_level)}</Chip>
                </div>
                {system.purpose && <p className="mt-1 text-xs text-muted">{system.purpose}</p>}
                {system.annex_iii_labels.map((label) => (
                  <Chip key={label} tone="bad" className="mr-1 mt-2">{td(label)}</Chip>
                ))}
                {system.evidence && <p className="mt-2 border-l-2 border-line pl-2 text-xs italic text-subtle">„{system.evidence}“</p>}
                <p className="mt-1 text-xs tabular-nums text-subtle">{tr("Konfidenz", "Confidence", "Confianza")} {(system.confidence * 100).toFixed(0)} %</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {ai.obligations.length > 0 && (
        <div>
          <p className="label-caps mb-1">{tr("Folgepflichten", "Resulting Obligations", "Obligaciones derivadas")}</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
            {ai.obligations.map((obligation, index) => <li key={index}>{td(obligation)}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function gdprRiskLabel(
  level: string,
  tr: (de: string, en: string, es: string) => string,
  td: (s: string) => string,
): string {
  switch (level.toLowerCase()) {
    case "none":
      return tr("keins", "None", "Ninguno");
    case "low":
      return tr("niedrig", "Low", "Bajo");
    case "medium":
      return tr("mittel", "Medium", "Medio");
    case "high":
      return tr("hoch", "High", "Alto");
    default:
      return td(level);
  }
}

function PiiPanel({ document, highlight }: { document: DocumentDetail; highlight: string | null }) {
  const { tr, td } = useI18n();
  const sources = useSourceLabels();
  const gdpr = document.compliance?.gdpr;
  const gateway = document.compliance?.privacy_gateway;
  if (!gdpr) return <EmptyState icon={<Lock size={18} />} title={tr("Noch kein DSGVO-Audit", "No GDPR audit yet", "Sin auditoría RGPD")} />;
  const matcher = highlight ? SPAN_TO_FINDINGS[highlight] : undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone={gdpr.contains_special_categories ? "bad" : gdpr.findings.length ? "pii" : "ok"}>
          {tr("DSGVO-Risiko:", "GDPR Risk:", "Riesgo RGPD:")} {gdprRiskLabel(gdpr.risk_level, tr, td)}
        </Chip>
        <span className="text-subtle">
          <span className="tabular-nums">{gdpr.findings.length}</span>{" "}
          {tr("Fundstellen · gespeichert ausschließlich maskiert", "findings · stored strictly masked", "hallazgos · almacenados ocultos")}
        </span>
      </div>
      {gateway && Object.keys(gateway).length > 0 && (
        <div className="rounded-lg border border-pii-line bg-pii-soft p-3 text-xs text-pii">
          <p className="font-semibold">{tr("Privacy Gateway aktiv – vor dem Cloud-Aufruf pseudonymisiert:", "Privacy Gateway active – pseudonymized before cloud call:", "Privacy Gateway activo – seudonimizado antes de envío:")}</p>
          <p className="mt-1 tabular-nums">
            {Object.entries(gateway).map(([category, count]) => `${td(category)} ×${count}`).join(" · ")}
          </p>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-2 text-subtle">
            <tr>
              <th className="px-3 py-2 font-medium">{tr("Kategorie", "Category", "Categoría")}</th>
              <th className="px-3 py-2 font-medium">{tr("Wert (maskiert)", "Value (masked)", "Valor (oculto)")}</th>
              <th className="px-3 py-2 font-medium">{tr("Quelle", "Source", "Fuente")}</th>
              <th className="px-3 py-2 text-right font-medium">{tr("Konfidenz", "Confidence", "Confianza")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {gdpr.findings.length === 0 && (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-subtle">{tr("Keine personenbezogenen Daten erkannt.", "No personal data detected.", "No se detectaron datos personales.")}</td></tr>
            )}
            {gdpr.findings.map((finding, index) => {
              const active = matcher?.(finding) ?? false;
              return (
                <tr key={index} className={cx("transition-colors duration-150", active && "bg-pii-soft")}>
                  <td className="px-3 py-2 align-top">
                    <span className="text-fg">{td(finding.category_label)}</span>
                    {finding.is_special_category && <Chip tone="bad" className="ml-1">Art. 9/10</Chip>}
                  </td>
                  <td className="break-all px-3 py-2 align-top tabular-nums text-muted">{finding.masked_value || "–"}</td>
                  <td className="px-3 py-2 align-top">
                    <Chip tone={finding.source === "both" ? "ok" : finding.source === "llm" ? "pii" : "accent"}>
                      {sources.short[finding.source]}
                    </Chip>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <div className="flex items-center justify-end gap-2">
                      <div className="h-1.5 w-14 rounded-full bg-line">
                        <div className="h-1.5 rounded-full bg-pii" style={{ width: `${Math.round(finding.confidence * 100)}%` }} />
                      </div>
                      <span className="w-10 text-right text-xs tabular-nums text-subtle">{Math.round(finding.confidence * 100)} %</span>
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
          {gdpr.recommendations.map((recommendation, index) => <li key={index}>{td(recommendation)}</li>)}
        </ul>
      )}
    </div>
  );
}

/** Feldbezeichner in Versalien, Wert in text-sm semibold; Kennungen in Inter mit tabular-nums. */
function Fact({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="label-caps">{label}</dt>
      <dd className={cx("mt-0.5 break-words text-sm font-semibold text-fg", mono && "tabular-nums")}>{value || "–"}</dd>
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
  const { tr } = useI18n();
  const line = (label: string, value: string | number | null, mark: React.ReactNode, strong = false) => (
    <div className={cx("grid items-baseline gap-3 px-3 py-1.5", marks ? "grid-cols-[1fr_auto_1.5rem]" : "grid-cols-[1fr_auto]")}>
      <dt className={cx("text-left text-xs", strong ? "font-semibold text-fg" : "text-muted")}>{label}</dt>
      <dd className={cx("text-right tabular-nums", strong ? "text-base font-semibold text-fg" : "text-sm text-fg")}>
        {typeof value === "string" && /[A-Z]{3}$/.test(value) ? value : formatMoney(value, currency)}
      </dd>
      {marks && <span className="flex justify-center">{mark}</span>}
    </div>
  );
  return (
    <dl className="rounded-lg border border-line bg-surface-2 py-1.5" aria-label={tr("Summen", "Totals", "Totales")}>
      {rows.map((row) => <React.Fragment key={row.label}>{line(row.label, row.value, row.mark)}</React.Fragment>)}
      <div className="mx-3 my-1 border-t-2 border-double border-line-strong" aria-hidden="true" />
      {line(total.label, total.value, total.mark, true)}
    </dl>
  );
}

function FactsPanel({ document }: { document: DocumentDetail }) {
  const { tr } = useI18n();
  const ex = document.extraction;
  if (!ex) return <EmptyState icon={<FileText size={18} />} title={tr("Noch keine Extraktion", "No extraction yet", "Sin extracción aún")} />;
  const math = document.scorecard?.tiles.find((tile) => tile.key === "math");
  const iban = ex.iban ? `${ex.iban.slice(0, 4)} •••• ${ex.iban.slice(-4)}` : null;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Fact label={tr("Dokumenttyp", "Document Type", "Tipo de documento")} value={docTypeLabel(ex.doc_type)} />
        <Fact label={tr("Belegnummer", "Document No.", "Número de documento")} value={<CopyValue value={ex.document_number} label={tr("Belegnummer", "Document No.", "Número")} />} />
        <Fact label={tr("Aussteller", "Supplier", "Emisor")} value={ex.sender} />
        <Fact label={tr("Empfänger", "Recipient", "Destinatario")} value={ex.recipient} />
        <Fact label={tr("Rechnungsdatum", "Invoice Date", "Fecha de factura")} value={formatDate(ex.document_date)} mono />
        <Fact label={tr("Leistung", "Supply / Period", "Prestación / Período")} value={ex.service_period || (ex.service_date ? formatDate(ex.service_date) : null)} mono />
        <Fact label={tr("Steuernr. / USt-IdNr.", "Tax / VAT ID", "NIF / IVA")} value={[ex.sender_tax_number, ex.sender_vat_id].filter(Boolean).join(" · ")} mono />
        <Fact label={tr("Fällig", "Due Date", "Vencimiento")} value={formatDate(ex.due_date)} mono />
        <Fact
          label="IBAN"
          value={
            iban && (
              <span className="inline-flex flex-wrap items-center gap-1.5">
                <CopyValue value={ex.iban} display={iban} label="IBAN" />
                <Chip tone={ex.iban_valid ? "ok" : "bad"}>
                  {ex.iban_valid ? <><Check size={11} aria-hidden="true" /> MOD-97</> : tr("Prüfziffer ungültig", "Invalid check digit", "Dígito de control no válido")}
                </Chip>
              </span>
            )
          }
        />
      </dl>
      <SumBlock
        currency={ex.currency}
        rows={[
          { label: tr("Summe netto", "Net total", "Importe neto"), value: ex.net_amount },
          { label: `${tr("Umsatzsteuer", "VAT", "IVA")}${ex.tax_rate != null ? ` ${ex.tax_rate} %` : ""}`, value: ex.tax_amount },
        ]}
        total={{ label: tr("Rechnungsbetrag brutto", "Gross invoice total", "Importe bruto"), value: ex.total_amount }}
      />
      {ex.summary && (
        <div>
          <p className="label-caps mb-1">{tr("Zusammenfassung", "Summary", "Resumen")}</p>
          <p className="text-sm leading-relaxed text-muted">{ex.summary}</p>
        </div>
      )}
      {math && (
        <div>
          <p className="label-caps">{tr("Mathematische Validität", "Financial Math Checks", "Validación matemática")}</p>
          <ul className="divide-y divide-line">{math.checks.map((check) => <CheckRow key={check.id} check={check} />)}</ul>
        </div>
      )}
      {ex.issues.length > 0 && (
        <div>
          <p className="label-caps mb-1">{tr("Auffälligkeiten", "Issues", "Observaciones")}</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{ex.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
        </div>
      )}
    </div>
  );
}


// --- XML-Datensatz (EN 16931) ------------------------------------------------

/** Namen ohne Tabellenziffern; Kennungen und Beträge in Inter mit tabular-nums. */
const NAME_TERMS = new Set(["BT-27", "BT-44"]);
/** Beträge stehen im Summenblock (rechtsbündig), nicht in der Kennungen-Tabelle. */
const MONEY_TERMS = ["BT-109", "BT-110", "BT-115", "BT-112"];
/** Kennungen mit Kopierbutton. */
const COPY_TERMS = new Set(["BT-1", "BT-10", "BT-31"]);

function VisualMark({ check }: { check: VisualCheck | undefined }) {
  const { tr } = useI18n();
  if (!check) return <span className="text-subtle">–</span>;
  const visualLabels: Record<VisualCheck["status"], string> = {
    match: tr("Bildteil stimmt überein", "Matches visual PDF", "Coincide con el PDF visual"),
    mismatch: tr("Abweichung im Bildteil", "Differs in visual PDF", "Discrepancia en el PDF visual"),
    not_found: tr("Im Bildteil nicht gefunden", "Not found in visual PDF", "No encontrado en el PDF visual"),
  };
  const label = check.status === "mismatch" && check.visual_value
    ? `${visualLabels.mismatch}: PDF ${tr("zeigt", "shows", "muestra")} ${check.visual_value}`
    : visualLabels[check.status];
  return (
    <Tooltip content={label} align="right">
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
  const { tr, td } = useI18n();
  const einvoice = document.einvoice;
  if (!einvoice) return <EmptyState icon={<FileCode size={18} />} title={tr("Kein XML-Datensatz", "No XML dataset", "Sin conjunto XML")} />;
  if (einvoice.error) {
    return (
      <div className="rounded-lg border border-warn-line bg-warn-soft p-3 text-xs text-warn">
        <p className="font-semibold">{tr(`Eingebettetes XML (${einvoice.attachment_name ?? "unbenannt"}) nicht auswertbar`, `Embedded XML (${einvoice.attachment_name ?? "unnamed"}) unreadable`, `XML incrustado (${einvoice.attachment_name ?? "sin nombre"}) ilegible`)}</p>
        <p className="mt-1 leading-relaxed">{einvoice.error}</p>
        <p className="mt-1 leading-relaxed">{tr("Geprüft wird deshalb der Bildteil des PDFs.", "Falling back to visual PDF inspection.", "Se analiza la representación visual del PDF.")}</p>
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
      <h3 className="sr-only">{tr("XML-Datensatz (EN 16931)", "XML Dataset (EN 16931)", "Conjunto XML (EN 16931)")}</h3>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Chip tone={einvoice.is_einvoice ? "accent" : "warn"}>{einvoiceLabel(einvoice)}</Chip>
        <span className="text-subtle">
          {embedded ? tr(`eingebettet als ${einvoice.attachment_name}`, `embedded as ${einvoice.attachment_name}`, `incrustado como ${einvoice.attachment_name}`) : tr("reines XML", "standalone XML", "XML puro")}
          {embedded && tr(" · maßgeblich vor dem Bildteil (BMF 15.10.2024, Rz. 36)", " · prevails over visual PDF (BMF 15 Oct 2024, para. 36)", " · prevalece sobre el PDF (BMF 15/10/2024)")}
        </span>
      </div>
      {!einvoice.is_einvoice && (
        <p className="rounded-lg border border-warn-line bg-warn-soft p-3 text-xs leading-relaxed text-warn">
          {tr(
            "Dieses Profil erfüllt nicht die Anforderungen an eine E-Rechnung. Rechnung im Sinne des § 14 UStG ist der Bildteil.",
            "This profile does not meet E-Invoice statutory requirements. The visual PDF governs under Sec. 14 UStG.",
            "Este perfil no cumple los requisitos de factura electrónica; prevalece el PDF visual según § 14 UStG.",
          )}
        </p>
      )}
      {embedded && mismatches > 0 && (
        <p role="status" className="rounded-lg border border-bad-line bg-bad-soft p-3 text-xs leading-relaxed text-bad">
          {tr(
            `Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz in ${mismatches === 1 ? "einem Wert" : `${mismatches} Werten`}. Es gilt das XML.`,
            `Mismatch between visual PDF and authoritative XML dataset in ${mismatches === 1 ? "1 value" : `${mismatches} values`}. XML prevails.`,
            `Discrepancia entre el PDF visual y el XML vinculante en ${mismatches === 1 ? "1 valor" : `${mismatches} valores`}. Prevalece el XML.`,
          )}
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">{tr("Business Terms nach EN 16931", "EN 16931 Business Terms", "Términos EN 16931")}</caption>
          <thead className="bg-surface-2 text-subtle">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">BT</th>
              <th scope="col" className="px-3 py-2 font-medium">Business Term</th>
              <th scope="col" className="px-3 py-2 font-medium">{tr("Wert (XML)", "Value (XML)", "Valor (XML)")}</th>
              {embedded && <th scope="col" className="px-3 py-2 text-center font-medium">PDF</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {identifiers.map((term) => (
              <tr key={term.bt}>
                <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-subtle">{term.bt}</td>
                <td className="px-3 py-2 align-top text-muted">{td(term.label)}</td>
                <td
                  className={cx(
                    "px-3 py-2 align-top text-fg [overflow-wrap:anywhere]",
                    NAME_TERMS.has(term.bt) ? "text-sm" : "tabular-nums",
                  )}
                >
                  {COPY_TERMS.has(term.bt) && term.value ? <CopyValue value={term.value} label={td(term.label)} /> : term.value ?? "–"}
                </td>
                {embedded && <td className="px-3 py-2 text-center align-top"><VisualMark check={visual.get(term.bt)} /></td>}
              </tr>
            ))}
            {embedded &&
              extraVisual.map((check) => (
                <tr key={check.bt}>
                  <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-subtle">{check.bt}</td>
                  <td className="px-3 py-2 align-top text-muted">{td(check.label)}</td>
                  <td className="px-3 py-2 align-top tabular-nums text-fg [overflow-wrap:anywhere]">
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
            label: `${term.bt} · ${td(term.label)}`,
            value: term.value,
            mark: embedded ? <VisualMark check={visual.get(term.bt)} /> : undefined,
          }))}
          total={{
            label: `${total.bt} · ${td(total.label)}`,
            value: total.value,
            mark: embedded ? <VisualMark check={visual.get(total.bt)} /> : undefined,
          }}
        />
      )}

      {einvoice.public_buyer && (
        <div className="rounded-lg border border-line p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="neutral">{tr("Öffentlicher Auftraggeber (B2G)", "Public Authority Buyer (B2G)", "Comprador público (B2G)")}</Chip>
            {einvoice.leitweg ? (
              <Chip tone={einvoice.leitweg.valid ? "ok" : "bad"}>
                Leitweg-ID {einvoice.leitweg.valid ? tr("gültig", "valid", "válida") : tr("ungültig", "invalid", "no válida")}
              </Chip>
            ) : (
              <Chip tone="bad">{tr("Leitweg-ID fehlt", "Leitweg-ID missing", "Falta Leitweg-ID")}</Chip>
            )}
          </div>
          <p className="mt-2 leading-relaxed text-muted">{td(einvoice.public_buyer_reason)}</p>
          {einvoice.leitweg && (
            <p className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-subtle">Leitweg-ID</span>
              <CopyValue value={einvoice.leitweg.value} label="Leitweg-ID" />
            </p>
          )}
          {einvoice.leitweg && !einvoice.leitweg.valid && (
            <p className="mt-1 leading-relaxed text-bad">{td(einvoice.leitweg.reason)}</p>
          )}
        </div>
      )}

      {einvoice.rule_violations.length > 0 && (
        <div>
          <p className="label-caps mb-1">{tr("EN-16931-Geschäftsregeln", "EN 16931 Business Rules", "Reglas EN 16931")}</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-warn">
            {einvoice.rule_violations.map((rule) => <li key={rule}>{td(rule)}</li>)}
          </ul>
        </div>
      )}

      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-xs sm:grid-cols-[auto_1fr]">
        <dt className="text-subtle">{tr("Spezifikation (BT-24)", "Specification (BT-24)", "Especificación (BT-24)")}</dt>
        <dd className="break-all font-mono text-muted">{einvoice.specification_id ?? "–"}</dd>
        <dt className="text-subtle">SHA-256 XML</dt>
        <dd>{einvoice.xml_sha256 ? <HashBadge value={einvoice.xml_sha256} label="XML" /> : "–"}</dd>
      </dl>
      <p className="text-xs leading-relaxed text-subtle">
        {tr(
          "Geprüft werden Profilkennung, Pflichtfelder und Summenregeln. Eine Validierung gegen XSD und Schematron (KoSIT-Validator) ist nicht Teil dieser Prüfung.",
          "Profile ID, mandatory elements and sum equations are audited. External XSD / Schematron validation (KoSIT) is not part of this pre-check.",
          "Se auditan perfil, campos obligatorios y sumas. La validación XSD/Schematron (KoSIT) es externa.",
        )}
      </p>
    </div>
  );
}

// --- Action-Leiste -------------------------------------------------------------

/** Revisionssicherheits-Status: Hash-Kette des gesamten Ledgers (GET /api/audit/verify). */
function LedgerSeal({ ledger, onOpen }: { ledger: LedgerVerification | null; onOpen?: () => void }) {
  const { tr } = useI18n();
  const state = !ledger ? "unknown" : !ledger.valid ? "broken" : ledger.entries === 0 ? "empty" : "ok";
  const tone = { ok: "ok", broken: "bad", empty: "neutral", unknown: "neutral" } as const;
  const label = {
    ok: tr("GoBD & Ledger intakt", "GoBD & Ledger intact", "GoBD y registro íntegros"),
    broken: tr("Hash-Kette gebrochen", "Hash chain broken", "Cadena de hash rota"),
    empty: tr("Ledger leer", "Ledger empty", "Registro vacío"),
    unknown: tr("Ledger nicht geprüft", "Ledger unverified", "Registro sin verificar"),
  }[state];
  return (
    <Tooltip
      content={
        !ledger ? (
          tr("Die Ledger-Prüfung ist derzeit nicht erreichbar.", "Ledger verification is currently unreachable.", "Verificación del registro no disponible.")
        ) : !ledger.valid ? (
          <>
            <span className="block font-semibold text-bad">
              {tr("Bruch", "Break", "Ruptura")}{ledger.broken_at_seq != null ? ` ${tr(`bei Eintrag #${ledger.broken_at_seq}`, `at entry #${ledger.broken_at_seq}`, `en entrada #${ledger.broken_at_seq}`)}` : ""}
            </span>
            <span className="block text-subtle">{ledger.reason ?? tr("Ein Eintrag passt nicht zur Kette.", "An entry does not match the hash chain.", "Una entrada no coincide con la cadena.")}</span>
          </>
        ) : (
          <>
            <span className="block">
              <span className="tabular-nums">{ledger.entries}</span>{" "}
              {tr("Einträge vollständig nachgerechnet, davon", "entries fully recomputed,", "entradas recalculadas,")}{" "}
              <span className="tabular-nums">{ledger.signed_entries}</span>{" "}
              {tr("Ed25519-signiert (Art. 12 AI Act, GoBD Rz. 107 ff.).", "Ed25519-signed (Art. 12 AI Act, GoBD Rz. 107 ff.).", "firmadas Ed25519 (Art. 12 IA, GoBD Rz. 107 ss.).")}
            </span>
            {ledger.entries > 0 && (
              <span className="mt-1 block tabular-nums text-subtle">{tr("Kopf-Hash", "Head hash", "Hash raíz")} {ledger.head_hash.slice(0, 16)}…</span>
            )}
          </>
        )
      }
    >
      <button
        type="button"
        onClick={onOpen}
        className={cx("chip py-1 transition-colors duration-150 hover:border-line-strong", TONE_CLASSES[tone[state]])}
        aria-label={`${label} – ${tr("Protokoll öffnen", "Open audit trail", "Abrir registro")}`}
      >
        {state === "broken" ? <AlertTriangle size={12} aria-hidden="true" /> : <Link size={12} aria-hidden="true" />}
        {label}
      </button>
    </Tooltip>
  );
}

function ActionBar({ document, ledger, onSeal, onOpenProtocol }: {
  document: DocumentDetail;
  ledger: LedgerVerification | null;
  onSeal?: () => void;
  onOpenProtocol?: () => void;
}) {
  const { tr } = useI18n();
  const mod = useModifierLabel();
  const seal = document.sign_off;
  const blocked = Boolean(document.scorecard?.release_blocked);
  const label = seal
    ? tr("Siegel erneuern", "Renew Seal", "Renovar sello")
    : blocked
      ? tr("Prüfentscheid siegeln", "Seal Decision", "Sellar decisión")
      : tr("Beleg freigeben & siegeln", "Approve & Seal", "Aprobar y sellar");
  return (
    <div
      data-tour="actions"
      className="sticky bottom-0 z-10 -mx-4 -mb-4 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-b-xl border-t border-line bg-surface-solid px-4 py-3 shadow-[0_-8px_24px_-16px_rgba(0,0,0,0.5)]"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <LedgerSeal ledger={ledger} onOpen={onOpenProtocol} />
        {seal && (
          <span className={cx("chip py-1", TONE_CLASSES[seal.status === "SEALED_APPROVED" ? "ok" : "bad"])}>
            <Stamp size={12} aria-hidden="true" />
            {seal.status === "SEALED_APPROVED" ? tr("Freigegeben", "Approved", "Aprobado") : tr("Abgelehnt", "Rejected", "Rechazado")} · {seal.auditor_name}
            <span className="font-medium tabular-nums opacity-80">{formatDate(seal.sealed_at, true)}</span>
          </span>
        )}
        {document.scorecard?.retention && (
          <span className="hidden text-xs text-subtle 2xl:inline">
            {tr("Aufbewahrung bis", "Retain until", "Conservar hasta")} <span className="tabular-nums">{formatDate(document.scorecard.retention.until)}</span> (§ 147 AO)
          </span>
        )}
      </div>
      <Tooltip
        align="right"
        content={
          onSeal
            ? tr(
                "Öffnet den Siegel-Dialog; ein zweites Strg/⌘ + Enter versiegelt. Das Siegel ist ein Ed25519-signierter Ledger-Eintrag (Art. 14 AI Act).",
                "Opens the sealing dialog; pressing Ctrl/⌘ + Enter again seals. Writes an Ed25519-signed entry (Art. 14 AI Act).",
                "Abre el diálogo de sellado; pulsar Ctrl/⌘ + Enter confirma el sello firmado Ed25519.",
              )
            : tr("Siegeln setzt ein abgeschlossenes Audit und eine Verbindung zum Backend voraus.", "Sealing requires a completed audit and active backend connection.", "Sellar requiere auditoría completada y conexión al backend.")
        }
      >
        <button type="button" className="btn btn-primary" onClick={onSeal} disabled={!onSeal}>
          <Stamp size={14} aria-hidden="true" />
          {label}
          <Kbd>{mod} ↵</Kbd>
        </button>
      </Tooltip>
    </div>
  );
}

// --- Inspektor -----------------------------------------------------------------

const NONE: string[] = [];

export function DocumentInspector({ document, tab, onTabChange, onOverride, ledger, onSeal, onOpenProtocol }: {
  document: DocumentDetail;
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onOverride?: () => void;
  ledger: LedgerVerification | null;
  /** Wechselt in die Ansicht "Protokoll" (vollstaendige Hash-Kette). */
  onOpenProtocol?: () => void;
  /** Oeffnet den Siegel-Dialog; fehlt, solange nicht gesiegelt werden kann. */
  onSeal?: () => void;
}) {
  const { tr } = useI18n();
  const [activeSpan, setActiveSpan] = useState<string | null>(null);
  const [hoverIds, setHoverIds] = useState<string[] | null>(null);
  const [pinnedIds, setPinnedIds] = useState<string[] | null>(null);
  const [textScroll, setTextScroll] = useState(0);
  const [rowScroll, setRowScroll] = useState<{ id: string; nonce: number } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const legend: { tone: EvidenceTone | "pii"; label: string; title: string }[] = [
    { tone: "ok", label: tr("Konform", "Compliant", "Conforme"), title: tr("Fundstelle belegt ein erfülltes Kriterium (Regelwerk oder XML).", "Passage confirms a satisfied requirement (ruleset or XML).", "Pasaje que acredita un criterio cumplido.") },
    { tone: "warn", label: tr("Prüfhinweis / KI-Vorschlag", "Notice / AI suggestion", "Aviso / Sugerencia IA"), title: tr("Hinweis ohne Verstoß oder Nachweis allein durch das KI-Modell – manuell sichten.", "Non-blocking notice or AI-only match – verify manually.", "Aviso o sugerencia de IA – revisar manualmente.") },
    { tone: "bad", label: tr("Verstoß", "Defect", "Incumplimiento"), title: tr("Mangel, z. B. fehlende oder abweichende Pflichtangabe nach § 14 UStG.", "Defect, e.g. missing or invalid mandatory invoice field under Sec. 14 UStG.", "Defecto o dato obligatorio ausente.") },
    { tone: "pii", label: tr("PII-Maskierung (DSGVO)", "PII Masking (GDPR)", "Ocultación PII (RGPD)"), title: tr("Personenbezogene Daten; Art.-9-Fundstellen kräftig umrandet.", "Personal data; GDPR Art. 9 sensitive categories strongly bordered.", "Datos personales; Art. 9 resaltados.") },
  ];
  const levelLabels = { strict: tr("Strikt", "Strict", "Estricto"), standard: "Standard", audit_only: "Audit-Only" } as const;

  const index = useMemo(() => buildEvidence(document), [document]);
  const checks = useMemo(() => {
    const map = new Map<string, { check: ScoreCheck; tab: InspectorTab }>();
    for (const tile of document.scorecard?.tiles ?? []) {
      const target = TILE_TABS[tile.key];
      if (target) tile.checks.forEach((check) => map.set(check.id, { check, tab: target }));
    }
    return map;
  }, [document.scorecard]);

  // Neues Dokument: keine Hervorhebung aus dem vorherigen mitnehmen.
  useEffect(() => {
    setHoverIds(null);
    setPinnedIds(null);
    setActiveSpan(null);
  }, [document.id]);

  // Escape loest eine per Klick gesetzte Hervorhebung (Dialoge schliessen sich ohnehin selbst).
  useEffect(() => {
    if (!pinnedIds) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setPinnedIds(null);
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [pinnedIds]);

  const active = hoverIds ?? pinnedIds ?? NONE;
  const evidenceLines = useMemo(
    () => new Set(active.flatMap((id) => index.byCheck.get(id)?.lines ?? [])),
    [active, index],
  );
  const activeSpans = useMemo(
    () => new Set(active.flatMap((id) => index.byCheck.get(id)?.spans ?? [])),
    [active, index],
  );
  const activeChecks = active.map((id) => checks.get(id)?.check).filter((check): check is ScoreCheck => Boolean(check));
  const tone = worstTone(activeChecks.map((check) => evidenceTone(check.status, check.evidence_source)));

  const hover = useCallback((ids: string[] | null) => setHoverIds(ids), []);
  const locate = useCallback((id: string) => {
    setPinnedIds([id]);
    setTextScroll((n) => n + 1);
  }, []);
  const evidenceApi = useMemo<EvidenceApi>(() => ({ index, active, hover, locate }), [index, active, hover, locate]);

  /** Rueckrichtung: Klick auf eine belegte Zeile oeffnet das Kriterium rechts. */
  const selectLine = useCallback(
    (line: number) => {
      const ids = index.byLine.get(line) ?? [];
      if (!ids.length) return;
      const inTab = ids.filter((id) => checks.get(id)?.tab === tab);
      const target = inTab.length ? tab : checks.get(ids[0])?.tab ?? tab;
      const shown = ids.filter((id) => checks.get(id)?.tab === target);
      setPinnedIds(shown);
      if (target !== tab) onTabChange(target);
      setRowScroll({ id: shown[0], nonce: Date.now() });
    },
    [index, checks, tab, onTabChange],
  );

  useEffect(() => {
    if (!rowScroll) return;
    const frame = window.requestAnimationFrame(() =>
      scrollWithin(panelRef.current, panelRef.current?.querySelector(`[data-check-id="${rowScroll.id}"]`)),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [rowScroll, tab]);

  const overrideHash = document.scorecard?.human_override?.ledger_entry_hash;
  // Nach einer Uebersteuerung den Hinweis oben im Panel sichtbar machen.
  useEffect(() => {
    if (overrideHash) panelRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [overrideHash]);
  const formal = document.scorecard?.tiles.find((t) => t.key === "formal");
  const failures = formal?.checks.filter((c) => c.status === "fail").length ?? 0;
  const focusCheck = activeChecks[0];
  const focusFound = focusCheck ? index.byCheck.get(focusCheck.id) : undefined;

  return (
    <EvidenceContext.Provider value={evidenceApi}>
      <section className="card p-4" aria-label={tr("Dokumenten-Inspektor", "Document Inspector", "Inspector documental")} data-tour="inspector">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-fg">{tr("Dokumenten-Inspektor", "Document Inspector", "Inspector documental")}</h2>
            {document.einvoice && !document.einvoice.error && (
              <button
                type="button"
                onClick={() => onTabChange("xml")}
                className={cx("chip transition-colors duration-150 hover:border-accent", TONE_CLASSES[document.einvoice.is_einvoice ? "accent" : "warn"])}
                title={tr("XML-Datensatz anzeigen", "Show XML dataset", "Ver conjunto XML")}
              >
                <FileCode size={12} aria-hidden="true" />
                {einvoiceLabel(document.einvoice)}
              </button>
            )}
          </div>
          {document.text_view && (
            <span className="chip border-line bg-surface-2 text-subtle">
              {tr("Maskierung:", "Masking:", "Ocultación:")} {levelLabels[document.text_view.level]} ·{" "}
              <span className="tabular-nums">{document.text_view.spans.length}</span> {tr("Markierungen", "annotations", "anotaciones")}
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:gap-6">
          <div className="min-w-0">
            <TextViewer
              view={document.text_view}
              evidenceLines={evidenceLines}
              evidenceTone={tone}
              activeSpans={activeSpans}
              activeCategory={activeSpan}
              anchored={index.byLine}
              scrollNonce={textScroll}
              onSpanClick={(span) => {
                setActiveSpan(span.category);
                onTabChange("pii");
              }}
              onLineHover={(line) => setHoverIds(line == null ? null : index.byLine.get(line) ?? null)}
              onLineClick={selectLine}
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-subtle" aria-label={tr("Legende der Markierungen", "Highlight legend", "Leyenda de resaltado")}>
                {legend.map(({ tone: legendTone, label, title }) => (
                  <li key={label} className="flex items-center gap-1.5" title={title}>
                    <span className={cx("inline-block h-2.5 w-2.5 rounded-[3px] opacity-80", SWATCH[legendTone])} aria-hidden="true" />
                    {label}
                  </li>
                ))}
              </ul>
              <p className="min-h-[1.25rem] truncate text-xs text-subtle" aria-live="polite">
                {focusCheck &&
                  (focusFound ? (
                    <>
                      <span className={cx("font-medium", tone && TONE_TEXT[tone])}>{toneLabel(focusCheck)}</span>
                      {" · "}
                      <span className="tabular-nums">{focusFound.lines.length}</span>{" "}
                      {focusFound.lines.length === 1 ? tr("Fundstelle", "occurrence", "coincidencia") : tr("Fundstellen", "occurrences", "coincidencias")}
                    </>
                  ) : (
                    <span className={focusCheck.status === "fail" ? "text-bad" : undefined}>
                      {focusCheck.status === "fail"
                        ? `${evidenceLabel("bad")} – ${tr("keine Fundstelle im Beleg", "no match in document", "sin coincidencia en el documento")}`
                        : tr("Keine Fundstelle im Beleg", "No match in document", "Sin coincidencia en el documento")}
                    </span>
                  ))}
              </p>
            </div>
          </div>
          <div className="min-w-0">
            <Tabs<InspectorTab>
              idPrefix="inspector"
              active={tab}
              onChange={onTabChange}
              tabs={[
                { key: "ustg", label: "§ 14 UStG", badge: failures ? <span className="text-xs tabular-nums text-bad">{failures}</span> : undefined },
                { key: "aiact", label: "AI Act", title: tr("EU AI Act (VO (EU) 2024/1689)", "EU AI Act (Reg. (EU) 2024/1689)", "Reglamento de IA (Reg. (UE) 2024/1689)") },
                { key: "pii", label: "PII", title: tr("PII-Befunde (DSGVO)", "PII Findings (GDPR)", "Hallazgos PII (RGPD)"), badge: <span className="text-xs tabular-nums text-subtle">{document.compliance?.gdpr.findings.length ?? 0}</span> },
                { key: "facts", label: tr("Kerndaten", "Core Data", "Datos clave") },
                ...(document.einvoice ? [{ key: "xml" as const, label: tr("XML-Datensatz", "XML Dataset", "XML"), title: tr("XML-Datensatz (EN 16931)", "XML Dataset (EN 16931)", "Conjunto XML (EN 16931)") }] : []),
              ]}
            />
            <div
              ref={panelRef}
              key={tab}
              id={`inspector-panel-${tab}`}
              role="tabpanel"
              aria-labelledby={`inspector-tab-${tab}`}
              className={cx(PANEL_HEIGHT, "scroll-area anim-fade relative pr-4 pt-3")}
            >
              {tab === "ustg" &&
                (formal ? (
                  <ul className="divide-y divide-line">
                    {formal.checks.map((check) => (
                      <CheckRow key={check.id} check={check}>
                        {check.id === "ustg_2_tax_id" && <ViesCheck document={document} />}
                      </CheckRow>
                    ))}
                  </ul>
                ) : (
                  <EmptyState icon={<Info size={18} />} title={tr("Noch keine § 14-Prüfung", "No Sec. 14 UStG audit yet", "Sin auditoría § 14 UStG")} />
                ))}
              {tab === "aiact" && <AiActPanel document={document} onOverride={onOverride} />}
              {tab === "pii" && <PiiPanel document={document} highlight={activeSpan} />}
              {tab === "facts" && <FactsPanel document={document} />}
              {tab === "xml" && <XmlPanel document={document} />}
            </div>
          </div>
        </div>
        <ActionBar document={document} ledger={ledger} onSeal={onSeal} onOpenProtocol={onOpenProtocol} />
      </section>
    </EvidenceContext.Provider>
  );
}
