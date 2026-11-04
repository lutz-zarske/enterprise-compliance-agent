"use client";

import Image from "next/image";
import React, { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Kbd, Modal, useModifierLabel } from "./ui";

export const ONBOARDING_KEY = "eca-onboarding-done";

export function onboardingDone(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDING_KEY) === "1";
  } catch {
    return true; // Ohne Speicher keine wiederkehrende Begruessung.
  }
}

export function markOnboardingDone(): void {
  try {
    window.localStorage.setItem(ONBOARDING_KEY, "1");
  } catch {
    /* privater Modus */
  }
}

export function WelcomeModal({ open, onStartTour, onSkip }: { open: boolean; onStartTour: () => void; onSkip: () => void }) {
  return (
    <Modal open={open} onClose={onSkip} title="Willkommen beim Enterprise Compliance Agent" width="max-w-lg">
      <div className="flex items-start gap-4">
        <Image src="/compliance-logo-transparent.png" alt="" width={48} height={48} unoptimized className="h-12 w-12 shrink-0 object-contain" />
        <div>
          <p className="text-sm font-medium text-fg">Revisionssichere KI-Dokumentenprüfung nach GoBD &amp; EU AI Act</p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            Rechnungen nach § 14 UStG und EN 16931, Verträge nach der VO (EU) 2024/1689, Datenschutz nach DSGVO – mit
            deterministischem Score, Ed25519-Siegel und hash-verkettetem Prüfprotokoll. Lokal oder über das Privacy Gateway.
          </p>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-line pt-4">
        <button className="btn" onClick={onSkip}>Direkt loslegen (Überspringen)</button>
        <button className="btn btn-primary" onClick={onStartTour} autoFocus>Interaktive Tour starten (1 Min.)</button>
      </div>
    </Modal>
  );
}

interface Step {
  target: string;
  title: string;
  text: (mod: string) => React.ReactNode;
}

const STEPS: Step[] = [
  { target: "upload", title: "Belege hochladen", text: () => "Echte PDFs oder ZUGFeRD-Rechnungen per Drag & Drop ablegen – auch mehrere auf einmal." },
  { target: "samples", title: "Musterdaten", text: () => "Standardisierte Testfälle für Demos per 1-Klick laden. Das Auge zeigt vorab die Rechtsfakten." },
  { target: "inspector", title: "Dokumenten-Inspektor", text: () => "Beleg-Fundstellen links und Rechtskriterien rechts bidirektional abgleichen: Zeile anklicken öffnet das Kriterium, Kriterium anklicken markiert die Zeile." },
  {
    target: "actions",
    title: "Action-Leiste & Siegel",
    text: (mod) => (
      <>
        Mit <Kbd>{mod} ↵</Kbd> revisionssicher nach GoBD Ed25519-siegeln &amp; Verfahrensdokumentation exportieren.
      </>
    ),
  },
];

const PAD = 8;
const CARD_WIDTH = 340;

/** Rechteck mit runden Ecken als Loch in einer Vollflaeche (clip-path, evenodd). */
function holePath(rect: DOMRect, radius = 14): string {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const x = rect.left - PAD;
  const y = rect.top - PAD;
  const rw = rect.width + PAD * 2;
  const rh = rect.height + PAD * 2;
  const r = Math.min(radius, rw / 2, rh / 2);
  return (
    `path(evenodd, "M0 0H${w}V${h}H0Z ` +
    `M${x + r} ${y}H${x + rw - r}A${r} ${r} 0 0 1 ${x + rw} ${y + r}V${y + rh - r}A${r} ${r} 0 0 1 ${x + rw - r} ${y + rh}` +
    `H${x + r}A${r} ${r} 0 0 1 ${x} ${y + rh - r}V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z")`
  );
}

/**
 * Spotlight-Tour in vier Schritten: abgedunkelter, weichgezeichneter Hintergrund
 * mit Aussparung um das Ziel. Klick ins Dunkle oder Escape beendet die Tour,
 * Pfeiltasten blaettern.
 */
export function SpotlightTour({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const mod = useModifierLabel();
  const current = STEPS[step];

  const measure = useCallback(() => {
    const element = document.querySelector<HTMLElement>(`[data-tour="${current.target}"]`);
    setRect(element ? element.getBoundingClientRect() : null);
  }, [current.target]);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const element = document.querySelector<HTMLElement>(`[data-tour="${current.target}"]`);
    element?.scrollIntoView({ block: "center", behavior: "instant" as ScrollBehavior });
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, current.target, measure]);

  const finish = useCallback(() => {
    markOnboardingDone();
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
      else if (event.key === "ArrowRight") setStep((value) => Math.min(STEPS.length - 1, value + 1));
      else if (event.key === "ArrowLeft") setStep((value) => Math.max(0, value - 1));
      else return;
      event.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, finish]);

  if (!open) return null;

  // Unter dem Ziel, sonst darueber; ist beides zu knapp (grosses Ziel), unten rechts ins Bild.
  const room = 230;
  const left = rect ? Math.max(16, Math.min(rect.left, window.innerWidth - CARD_WIDTH - 16)) : 0;
  const cardStyle: React.CSSProperties = !rect
    ? { left: "50%", top: "50%", transform: "translate(-50%, -50%)" }
    : window.innerHeight - rect.bottom > room
      ? { left, top: rect.bottom + PAD + 12 }
      : rect.top > room
        ? { left, bottom: window.innerHeight - rect.top + PAD + 12 }
        : { right: 24, bottom: 24 };

  return createPortal(
    <>
      <div
        className="anim-fade fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm"
        style={rect ? { clipPath: holePath(rect) } : undefined}
        onClick={finish}
        aria-hidden="true"
      />
      {rect && (
        <div
          className="tour-ring"
          style={{ top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }}
          aria-hidden="true"
        />
      )}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Tour, Schritt ${step + 1} von ${STEPS.length}: ${current.title}`}
        className="anim-panel fixed z-[92] rounded-xl border border-line-strong bg-surface-solid p-4 shadow-2xl"
        style={{ ...cardStyle, width: CARD_WIDTH }}
      >
        <p className="font-mono text-xs tabular-nums text-subtle">Schritt {step + 1} / {STEPS.length}</p>
        <h2 className="mt-1 text-sm font-semibold text-fg">{current.title}</h2>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">{current.text(mod)}</p>
        {!rect && <p className="mt-2 text-xs text-warn">Dieser Bereich erscheint, sobald ein Beleg geöffnet ist – z. B. über die Musterdaten.</p>}
        <div className="mt-4 flex items-center justify-between gap-2">
          <button className="text-xs text-subtle transition-colors duration-150 hover:text-fg" onClick={finish}>Tour beenden</button>
          <div className="flex gap-2">
            <button className="btn" onClick={() => setStep((value) => value - 1)} disabled={step === 0}>Zurück</button>
            {step < STEPS.length - 1 ? (
              <button className="btn btn-primary" onClick={() => setStep((value) => value + 1)} autoFocus>Weiter</button>
            ) : (
              <button className="btn btn-primary" onClick={finish} autoFocus>Fertig</button>
            )}
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}

/** Tastatur-Cheatsheet (``?``). */
export function ShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const mod = useModifierLabel();
  const groups: { title: string; items: [React.ReactNode, string][] }[] = [
    {
      title: "Prüfung",
      items: [
        [<><Kbd>{mod}</Kbd><Kbd>↵</Kbd></>, "Beleg freigeben & Ed25519-siegeln (Dialog öffnen, im Dialog bestätigen)"],
        [<Kbd key="esc">Esc</Kbd>, "Dialog, Menü oder Tour schließen"],
      ],
    },
    {
      title: "Navigation",
      items: [
        [<><Kbd>J</Kbd><Kbd>K</Kbd></>, "Nächstes / vorheriges Dokument"],
        [<><Kbd>↓</Kbd><Kbd>↑</Kbd></>, "Nächstes / vorheriges Dokument (Pfeiltasten)"],
        [<><Kbd>1</Kbd>–<Kbd>6</Kbd></>, "Reiter: § 14 UStG · AI Act · PII · Kerndaten · XML · Ledger"],
        [<Kbd key="q">?</Kbd>, "Diese Übersicht"],
      ],
    },
  ];
  return (
    <Modal open={open} onClose={onClose} title="Tastaturkürzel" subtitle="Greifen nicht, solange ein Eingabefeld den Fokus hat." width="max-w-lg">
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.title}>
            <p className="label-caps">{group.title}</p>
            <ul className="mt-1.5 divide-y divide-line">
              {group.items.map(([keys, text]) => (
                <li key={text} className="flex items-center justify-between gap-4 py-2 text-sm text-fg">
                  <span>{text}</span>
                  <span className="flex shrink-0 items-center gap-1 text-xs text-subtle">{keys}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Modal>
  );
}
