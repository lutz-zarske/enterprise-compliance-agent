"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cx } from "../lib/format";
import { tr, useI18n, type Locale } from "../lib/i18n";
import { popoverStyle, usePopoverExclusive } from "../lib/popover";
import { ChevronDown, Eye, FileText, Package } from "./icons";
import { Spinner } from "./ui";

export interface SampleSpec {
  file: string;
  tone: string;
  score: number;
  title: Record<Locale, string>;
  subtitle: Record<Locale, string>;
  facts: Record<Locale, string[]>;
}

/** Die vier Musterbelege (Dateinamen wie in ``app/demo.py``). */
export const SAMPLES: readonly SampleSpec[] = [
  {
    file: "Rechnung_Gueltig_14UStG.pdf",
    tone: "bg-ok",
    score: 100,
    title: {
      de: "Konforme Rechnung (§ 14 UStG)",
      en: "Compliant Invoice (§ 14 German VAT Act)",
      es: "Factura conforme (§ 14 UStG)",
    },
    subtitle: {
      de: "Vorsteuerabzugsfähig, fehlerfreie Betragsmathematik, Demo-Siegel.",
      en: "Eligible for input VAT deduction, accurate tax math, demo seal.",
      es: "Deducible de IVA soportado, cálculos correctos, sello de demostración.",
    },
    facts: {
      de: [
        "Pflichtangaben § 14 Abs. 4 Nr. 1–8 UStG vollständig",
        "IBAN-Prüfziffer gültig (ISO 13616, MOD 97-10)",
        "Netto + USt = Brutto, Steuersatz 19 % (§ 12 Abs. 1 UStG)",
        "Demo-Siegel als Ed25519-signierter Ledger-Eintrag",
      ],
      en: [
        "All mandatory disclosures under § 14 (4) Nr. 1–8 UStG complete",
        "IBAN check digit valid (ISO 13616, MOD 97-10)",
        "Net + VAT = Gross, statutory 19% rate (§ 12 (1) UStG)",
        "Demo seal stored as Ed25519-signed ledger entry",
      ],
      es: [
        "Todos los requisitos obligatorios del § 14 (4) Nr. 1–8 UStG completos",
        "Dígito de control IBAN válido (ISO 13616, MOD 97-10)",
        "Neto + IVA = Bruto, tipo legal 19 % (§ 12 (1) UStG)",
        "Sello de demostración firmado con Ed25519 en el registro",
      ],
    },
  },
  {
    file: "Rechnung_ZUGFeRD_Hybrid.pdf",
    tone: "bg-ok",
    score: 100,
    title: {
      de: "ZUGFeRD-E-Rechnung (EN 16931)",
      en: "ZUGFeRD E-Invoice (EN 16931)",
      es: "Factura electrónica ZUGFeRD (EN 16931)",
    },
    subtitle: {
      de: "XML-Datensatz maßgeblich, Kommune mit Leitweg-ID, ohne KI geprüft.",
      en: "XML dataset prevails, municipal buyer with Leitweg-ID, verified without AI.",
      es: "Prevalece el XML, municipio con Leitweg-ID, verificada sin IA.",
    },
    facts: {
      de: [
        "XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36)",
        "Profil EN 16931 (COMFORT), Abgleich mit dem PDF-Bildteil",
        "Leitweg-ID mit gültiger Prüfziffer (§ 5 ERechV)",
        "Deterministisch aus dem XML – kein Sprachmodell",
      ],
      en: [
        "XML payload authoritative (BMF guidance Oct 15, 2024, sec. 36)",
        "EN 16931 (COMFORT) profile, cross-checked against visual PDF",
        "Routing ID (Leitweg-ID) with valid check digit (§ 5 ERechV)",
        "Parsed deterministically from XML – zero LLM dependency",
      ],
      es: [
        "Prevalece el XML estructurado (circular BMF 15.10.2024, n.º 36)",
        "Perfil EN 16931 (COMFORT), cotejado con el PDF visual",
        "Leitweg-ID con dígito de control válido (§ 5 ERechV)",
        "Procesada de forma determinista desde XML – sin modelo de IA",
      ],
    },
  },
  {
    file: "Rechnung_Fehlerhaft_Steuerfalle.pdf",
    tone: "bg-bad",
    score: 45,
    title: {
      de: "Steuerfalle & Vorsteuer-Mangel (§ 14 Abs. 4 UStG)",
      en: "Tax Trap & VAT Defect (§ 14 (4) UStG)",
      es: "Trampa fiscal y defecto de IVA (§ 14 (4) UStG)",
    },
    subtitle: {
      de: "Steuersatz 16 % statt 19 %, ungültige IBAN, fehlende Pflichtangaben.",
      en: "Invalid 16% VAT rate, wrong IBAN checksum, missing mandatory disclosures.",
      es: "IVA del 16 % en lugar del 19 %, IBAN inválido y omisiones legales.",
    },
    facts: {
      de: [
        "USt-IdNr. bzw. Steuernummer fehlt (Nr. 2): −20",
        "Leistungsdatum fehlt (Nr. 6): −10",
        "IBAN-Prüfziffer ungültig: −15",
        "Steuersatz 16 % unzulässig (§ 12 UStG): −10",
      ],
      en: [
        "Tax number / VAT ID missing (No. 2): −20",
        "Service / performance date missing (No. 6): −10",
        "IBAN checksum invalid: −15",
        "16% VAT rate invalid (§ 12 UStG): −10",
      ],
      es: [
        "Falta número fiscal o NIF-IVA (n.º 2): −20",
        "Falta fecha de prestación (n.º 6): −10",
        "Dígito de control IBAN inválido: −15",
        "Tipo de IVA 16 % no permitido (§ 12 UStG): −10",
      ],
    },
  },
  {
    file: "KI_Recruiting_Dienstleistervertrag.pdf",
    tone: "bg-warn",
    score: 59,
    title: {
      de: "EU AI Act Hochrisiko-Vertrag (Anhang III Nr. 4)",
      en: "EU AI Act High-Risk Contract (Annex III No. 4)",
      es: "Contrato IA de alto riesgo (Anexo III n.º 4)",
    },
    subtitle: {
      de: "Automatisierte Bewerberbewertung, Score gedeckelt, Übersteuerung möglich.",
      en: "Automated candidate scoring, score capped at 59, human override enabled.",
      es: "Evaluación automatizada de candidatos, puntuación limitada a 59.",
    },
    facts: {
      de: [
        "Beschäftigung, Bewerberauswahl: Anhang III Nr. 4 VO (EU) 2024/1689",
        "Ohne Konformitätsnachweis auf 59 gedeckelt",
        "Pflichten ab 02.12.2027 (VO (EU) 2026/1744)",
        "Übersteuerung durch die Prüfperson nach Art. 14 Abs. 4 lit. d",
      ],
      en: [
        "Employment & candidate screening: Annex III No. 4 EU AI Act",
        "Capped at 59 without conformity assessment",
        "Annex III obligations apply from Dec 2, 2027 (Reg. 2026/1744)",
        "Reasoned human oversight override under Art. 14 (4) lit. d",
      ],
      es: [
        "Empleo y selección de personal: Anexo III n.º 4 Reg. (UE) 2024/1689",
        "Limitado a 59 sin certificado de conformidad",
        "Obligaciones desde el 02.12.2027 (Reg. 2026/1744)",
        "Anulación humana motivada según Art. 14 (4) lit. d",
      ],
    },
  },
] as const;

export function SampleMenu({ busy, disabled, onLoad }: {
  busy: boolean;
  disabled: boolean;
  onLoad: (file?: string) => void;
}) {
  const { locale, tr: t } = useI18n();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);
  const [style, setStyle] = useState<React.CSSProperties>({ position: "fixed", visibility: "hidden" });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  usePopoverExclusive(open, close, "sample-menu");

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!buttonRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    const closeMenu = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", closeMenu);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", closeMenu);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    setStyle(popoverStyle(buttonRef.current.getBoundingClientRect(), { width: 380, maxHeight: 520, align: "right" }));
    window.requestAnimationFrame(() => menuRef.current?.querySelector<HTMLButtonElement>("[data-sample]")?.focus());
  }, [open]);

  function load(file?: string) {
    setOpen(false);
    onLoad(file);
  }

  function onMenuKey(event: React.KeyboardEvent) {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("[data-sample]") ?? []);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    items[(index + step + items.length) % items.length]?.focus();
  }

  const fact = preview !== null ? SAMPLES[preview] : null;
  const pts = t("Pkt.", "pts", "pts");

  return (
    <>
      <button
        ref={buttonRef}
        className="btn"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled || busy}
        aria-haspopup="menu"
        aria-expanded={open}
        data-tour="samples"
        title={t("Standardisierte Prüfbelege laden – funktioniert ohne KI-Modell", "Load standardized sample documents – works without any AI model", "Cargar documentos de muestra – funciona sin modelo de IA")}
      >
        {busy ? <Spinner size={13} /> : <FileText size={14} aria-hidden="true" />}
        <span className="hidden md:inline">{t("Musterdaten", "Samples", "Muestras")}</span>
        <ChevronDown size={13} aria-hidden="true" className={cx("text-subtle transition-transform duration-200 ease-out", open && "rotate-180")} />
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label={t("Musterdaten laden", "Load sample data", "Cargar muestras")}
            style={style}
            onKeyDown={onMenuKey}
            onMouseLeave={() => setPreview(null)}
            className="glass-menu scroll-area z-[70] p-1"
          >
            {SAMPLES.map((sample, index) => (
              <div key={sample.file} className="group relative flex items-stretch rounded-lg transition-colors duration-100 hover:bg-surface-2 focus-within:bg-surface-2">
                <button
                  type="button"
                  role="menuitem"
                  data-sample
                  onClick={() => load(sample.file)}
                  onFocus={() => setPreview(null)}
                  className="flex min-w-0 flex-1 items-start gap-2.5 rounded-lg px-2.5 py-2 text-left outline-none"
                >
                  <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", sample.tone)} aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className="text-[13px] font-medium leading-snug text-fg">{sample.title[locale]}</span>
                      <span className="ml-auto shrink-0 text-xs tabular-nums text-subtle">{sample.score} {pts}</span>
                    </span>
                    <span className="mt-0.5 block text-xs leading-snug text-subtle">{sample.subtitle[locale]}</span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`${tr("Rechtsfakten", "Legal facts", "Datos legales", locale)}: ${sample.title[locale]}`}
                  onMouseEnter={() => setPreview(index)}
                  onFocus={() => setPreview(index)}
                  onBlur={() => setPreview(null)}
                  className={cx(
                    "mr-1 self-center rounded-md p-1.5 text-subtle transition-colors duration-150 hover:text-fg focus-visible:text-fg",
                    preview === index && "bg-surface-solid text-accent",
                  )}
                >
                  <Eye size={14} aria-hidden="true" />
                </button>
              </div>
            ))}
            <div className="my-1 border-t border-line" />
            <button
              type="button"
              role="menuitem"
              data-sample
              onClick={() => load()}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-fg outline-none transition-colors duration-100 hover:bg-surface-2 focus-visible:bg-surface-2"
            >
              <Package size={14} aria-hidden="true" className="text-accent" />
              {t("Alle 4 Referenzbelege laden", "Load all 4 sample documents", "Cargar los 4 documentos de muestra")}
            </button>
            {fact && (
              <div role="note" className="anim-fade mt-1 rounded-lg border border-line bg-surface-solid px-3 py-2.5">
                <p className="label-caps">{t("Rechtsfakten", "Legal facts", "Datos legales")} · {fact.score} {pts}</p>
                <ul className="mt-1.5 space-y-1 text-xs leading-snug text-muted">
                  {fact.facts[locale].map((line) => (
                    <li key={line} className="flex gap-2">
                      <span className={cx("mt-1.5 h-1 w-1 shrink-0 rounded-full", fact.tone)} aria-hidden="true" />
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
