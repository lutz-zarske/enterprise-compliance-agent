"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../lib/i18n";
import { BrandMark } from "./BrandMark";
import { Kbd, Modal, useModalFocusLock, useModifierLabel } from "./ui";

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
  const { tr } = useI18n();
  return (
    <Modal
      open={open}
      onClose={onSkip}
      title={tr(
        "Willkommen beim Enterprise Compliance Agent",
        "Welcome to Enterprise Compliance Agent",
        "Bienvenido a Enterprise Compliance Agent",
      )}
      width="max-w-lg"
    >
      <div className="flex items-start gap-4">
        <BrandMark size={48} className="shrink-0" />
        <div>
          <p className="text-sm font-medium text-fg">
            {tr(
              "Revisionssichere KI-Dokumentenprüfung nach GoBD & EU AI Act",
              "Audit-proof AI document inspection under GoBD & EU AI Act",
              "Auditoría documental con IA conforme a GoBD y Reglamento de IA de la UE",
            )}
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            {tr(
              "Rechnungen nach § 14 UStG und EN 16931, Verträge nach der VO (EU) 2024/1689, Datenschutz nach DSGVO – mit deterministischem Score, Ed25519-Siegel und hash-verkettetem Prüfprotokoll. Lokal oder über das Privacy Gateway.",
              "Invoices under Sec. 14 UStG and EN 16931, contracts under Regulation (EU) 2024/1689, data privacy under GDPR – with deterministic scoring, Ed25519 seal and hash-chained audit trail. Local or via Privacy Gateway.",
              "Facturas según § 14 UStG y EN 16931, contratos según Reglamento (UE) 2024/1689, privacidad según RGPD – con puntuación determinista, sello Ed25519 y registro encadenado por hash. Local o vía Privacy Gateway.",
            )}
          </p>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-line pt-4">
        <button className="btn" onClick={onSkip}>
          {tr("Direkt loslegen (Überspringen)", "Get started right away (Skip)", "Empezar ahora (Omitir)")}
        </button>
        <button className="btn btn-primary" onClick={onStartTour} autoFocus>
          {tr("Interaktive Tour starten (1 Min.)", "Start interactive tour (1 min)", "Iniciar recorrido interactivo (1 min)")}
        </button>
      </div>
    </Modal>
  );
}

interface Step {
  target: string;
  title: string;
  text: (mod: string) => React.ReactNode;
}

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
  const { tr } = useI18n();
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const mod = useModifierLabel();
  const steps: Step[] = [
    {
      target: "upload",
      title: tr("Belege hochladen", "Upload Documents", "Subir documentos"),
      text: () => tr(
        "Echte PDFs oder ZUGFeRD-Rechnungen per Drag & Drop ablegen – auch mehrere auf einmal.",
        "Drag & drop real PDFs or ZUGFeRD/XRechnung invoices – multi-file upload supported.",
        "Arrastra PDFs reales o facturas ZUGFeRD/XRechnung; admite subida múltiple.",
      ),
    },
    {
      target: "samples",
      title: tr("Musterdaten", "Sample Cases", "Casos de ejemplo"),
      text: () => tr(
        "Standardisierte Testfälle für Demos per 1-Klick laden. Das Auge zeigt vorab die Rechtsfakten.",
        "Load standardized demo test cases in one click. The eye icon previews statutory facts.",
        "Carga casos de prueba estándar con un clic. El icono del ojo muestra los hechos previos.",
      ),
    },
    {
      target: "inspector",
      title: tr("Dokumenten-Inspektor", "Document Inspector", "Inspector documental"),
      text: () => tr(
        "Beleg-Fundstellen links und Rechtskriterien rechts bidirektional abgleichen: Zeile anklicken öffnet das Kriterium, Kriterium anklicken markiert die Zeile.",
        "Cross-highlight findings left and statutory checks right: click any line or criterion to focus its counterpart.",
        "Sincronización bidireccional: pulsa una línea o criterio para resaltar su correspondencia.",
      ),
    },
    {
      target: "actions",
      title: tr("Action-Leiste & Siegel", "Action Bar & Seal", "Barra de acciones y sello"),
      text: (m) => (
        <>
          {tr("Mit", "With", "Con")} <Kbd>{m} ↵</Kbd>{" "}
          {tr(
            "revisionssicher nach GoBD Ed25519-siegeln & Verfahrensdokumentation exportieren.",
            "seal audit-proof under GoBD (Ed25519) & export procedural documentation.",
            "sella conforme a GoBD con Ed25519 y exporta la documentación de procedimientos.",
          )}
        </>
      ),
    },
  ];
  const current = steps[step];

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

  const panelRef = useRef<HTMLDivElement>(null);
  useModalFocusLock(open, panelRef, finish);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") setStep((value) => Math.min(steps.length - 1, value + 1));
      else if (event.key === "ArrowLeft") setStep((value) => Math.max(0, value - 1));
      else return;
      event.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, steps.length]);

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
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={tr(`Tour, Schritt ${step + 1} von ${steps.length}: ${current.title}`, `Tour, step ${step + 1} of ${steps.length}: ${current.title}`, `Recorrido, paso ${step + 1} de ${steps.length}: ${current.title}`)}
        className="anim-panel fixed z-[92] rounded-xl border border-line-strong bg-surface-solid p-4 shadow-2xl focus:outline-none"
        style={{ ...cardStyle, width: CARD_WIDTH }}
      >
        <p className="text-xs tabular-nums text-subtle">{tr(`Schritt ${step + 1} / ${steps.length}`, `Step ${step + 1} / ${steps.length}`, `Paso ${step + 1} / ${steps.length}`)}</p>
        <h2 className="mt-1 text-sm font-semibold text-fg">{current.title}</h2>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">{current.text(mod)}</p>
        {!rect && (
          <p className="mt-2 text-xs text-warn">
            {tr(
              "Dieser Bereich erscheint, sobald ein Beleg geöffnet ist – z. B. über die Musterdaten.",
              "This area appears once a document is opened – e.g. via Sample Cases.",
              "Esta sección aparece al abrir un documento, p. ej. desde los casos de ejemplo.",
            )}
          </p>
        )}
        <div className="mt-4 flex items-center justify-between gap-2">
          <button className="text-xs text-subtle transition-colors duration-150 hover:text-fg" onClick={finish}>
            {tr("Tour beenden", "End tour", "Finalizar recorrido")}
          </button>
          <div className="flex gap-2">
            <button className="btn" onClick={() => setStep((value) => value - 1)} disabled={step === 0}>
              {tr("Zurück", "Back", "Atrás")}
            </button>
            {step < steps.length - 1 ? (
              <button className="btn btn-primary" onClick={() => setStep((value) => value + 1)} autoFocus>
                {tr("Weiter", "Next", "Siguiente")}
              </button>
            ) : (
              <button className="btn btn-primary" onClick={finish} autoFocus>
                {tr("Fertig", "Done", "Listo")}
              </button>
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
  const { tr } = useI18n();
  const mod = useModifierLabel();
  const groups: { title: string; items: [React.ReactNode, string][] }[] = [
    {
      title: tr("Prüfung", "Review", "Auditoría"),
      items: [
        [<><Kbd>{mod}</Kbd><Kbd>↵</Kbd></>, tr("Beleg freigeben & Ed25519-siegeln (Dialog öffnen, im Dialog bestätigen)", "Approve & Ed25519-seal document (open dialog, confirm inside)", "Aprobar y sellar con Ed25519 (abrir diálogo y confirmar)")],
        [<Kbd key="esc">Esc</Kbd>, tr("Dialog, Menü oder Tour schließen", "Close dialog, menu or tour", "Cerrar diálogo, menú o recorrido")],
      ],
    },
    {
      title: "Navigation",
      items: [
        [<><Kbd>J</Kbd><Kbd>K</Kbd></>, tr("Nächstes / vorheriges Dokument", "Next / previous document", "Documento siguiente / anterior")],
        [<><Kbd>↓</Kbd><Kbd>↑</Kbd></>, tr("Nächstes / vorheriges Dokument (Pfeiltasten)", "Next / previous document (arrow keys)", "Documento siguiente / anterior (flechas)")],
        [<><Kbd>1</Kbd>–<Kbd>5</Kbd></>, tr("Reiter: § 14 UStG · AI Act · PII · Kerndaten · XML", "Tabs: Sec. 14 UStG · AI Act · PII · Core data · XML", "Pestañas: § 14 UStG · IA · PII · Datos clave · XML")],
        [<Kbd key="q">?</Kbd>, tr("Diese Übersicht", "This overview", "Este resumen")],
      ],
    },
  ];
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={tr("Tastaturkürzel", "Keyboard Shortcuts", "Atajos de teclado")}
      subtitle={tr("Greifen nicht, solange ein Eingabefeld den Fokus hat.", "Disabled while typing in an input field.", "Desactivados al escribir en un campo de texto.")}
      width="max-w-lg"
    >
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
