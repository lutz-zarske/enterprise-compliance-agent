"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cx } from "../lib/format";
import { popoverStyle, usePopoverExclusive } from "../lib/popover";
import { ChevronDown, Eye, FileText, Package } from "./icons";
import { Spinner } from "./ui";

/** Die vier Musterbelege (Dateinamen wie in ``app/demo.py``). */
export const SAMPLES = [
  {
    file: "Rechnung_Gueltig_14UStG.pdf",
    tone: "bg-ok",
    title: "Konforme Rechnung (§ 14 UStG)",
    score: 100,
    subtitle: "Vorsteuerabzugsfähig, fehlerfreie Betragsmathematik, Demo-Siegel.",
    facts: [
      "Pflichtangaben § 14 Abs. 4 Nr. 1–8 UStG vollständig",
      "IBAN-Prüfziffer gültig (ISO 13616, MOD 97-10)",
      "Netto + USt = Brutto, Steuersatz 19 % (§ 12 Abs. 1 UStG)",
      "Demo-Siegel als Ed25519-signierter Ledger-Eintrag",
    ],
  },
  {
    file: "Rechnung_ZUGFeRD_Hybrid.pdf",
    tone: "bg-ok",
    title: "ZUGFeRD-E-Rechnung (EN 16931)",
    score: 100,
    subtitle: "XML-Datensatz maßgeblich, Kommune mit Leitweg-ID, ohne KI geprüft.",
    facts: [
      "XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36)",
      "Profil EN 16931 (COMFORT), Abgleich mit dem PDF-Bildteil",
      "Leitweg-ID mit gültiger Prüfziffer (§ 5 ERechV)",
      "Deterministisch aus dem XML – kein Sprachmodell",
    ],
  },
  {
    file: "Rechnung_Fehlerhaft_Steuerfalle.pdf",
    tone: "bg-bad",
    title: "Steuerfalle & Vorsteuer-Mangel (§ 14 Abs. 4 UStG)",
    score: 45,
    subtitle: "Steuersatz 16 % statt 19 %, ungültige IBAN, fehlende Pflichtangaben.",
    facts: [
      "USt-IdNr. bzw. Steuernummer fehlt (Nr. 2): −20",
      "Leistungsdatum fehlt (Nr. 6): −10",
      "IBAN-Prüfziffer ungültig: −15",
      "Steuersatz 16 % unzulässig (§ 12 UStG): −10",
    ],
  },
  {
    file: "KI_Recruiting_Dienstleistervertrag.pdf",
    tone: "bg-warn",
    title: "EU AI Act Hochrisiko-Vertrag (Anhang III Nr. 4)",
    score: 59,
    subtitle: "Automatisierte Bewerberbewertung, Score gedeckelt, Übersteuerung möglich.",
    facts: [
      "Beschäftigung, Bewerberauswahl: Anhang III Nr. 4 VO (EU) 2024/1689",
      "Ohne Konformitätsnachweis auf 59 gedeckelt",
      "Pflichten ab 02.12.2027 (VO (EU) 2026/1744)",
      "Übersteuerung durch die Prüfperson nach Art. 14 Abs. 4 lit. d",
    ],
  },
] as const;

/**
 * Split-Menue „Musterdaten“: jeder Beleg einzeln oder alle vier. Das Auge zeigt
 * die Rechtsfakten des Belegs, ohne ihn zu laden.
 */
export function SampleMenu({ busy, disabled, onLoad }: {
  busy: boolean;
  disabled: boolean;
  onLoad: (file?: string) => void;
}) {
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
    const close = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
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

  // Pfeiltasten wandern durch die Eintraege.
  function onMenuKey(event: React.KeyboardEvent) {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("[data-sample]") ?? []);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    items[(index + step + items.length) % items.length]?.focus();
  }

  const fact = preview !== null ? SAMPLES[preview] : null;

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
        title="Standardisierte Prüfbelege laden – funktioniert ohne KI-Modell"
      >
        {busy ? <Spinner size={13} /> : <FileText size={14} aria-hidden="true" />}
        <span className="hidden md:inline">Musterdaten</span>
        <ChevronDown size={13} aria-hidden="true" className={cx("text-subtle transition-transform duration-200 ease-out", open && "rotate-180")} />
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label="Musterdaten laden"
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
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-2">
                      <span className="text-[13px] font-medium leading-snug text-fg">{sample.title}</span>
                      <span className="ml-auto shrink-0 text-xs tabular-nums text-subtle">{sample.score} Pkt.</span>
                    </span>
                    <span className="mt-0.5 block text-xs leading-snug text-subtle">{sample.subtitle}</span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Rechtsfakten: ${sample.title}`}
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
              Alle 4 Referenzbelege laden
            </button>
            {fact && (
              <div role="note" className="anim-fade mt-1 rounded-lg border border-line bg-surface-solid px-3 py-2.5">
                <p className="label-caps">Rechtsfakten · {fact.score} Pkt.</p>
                <ul className="mt-1.5 space-y-1 text-xs leading-snug text-muted">
                  {fact.facts.map((line) => (
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
