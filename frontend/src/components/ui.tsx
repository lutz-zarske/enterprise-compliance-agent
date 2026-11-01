"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import type { CheckStatus } from "../types/api";
import { cx, TONE_CLASSES, type Tone } from "../lib/format";
import { AlertTriangle, Check, CheckCircle, Copy, Info, MinusCircle, ShieldAlert, ShieldCheck, X, XCircle } from "./icons";

export function Chip({ tone = "neutral", children, className, title }: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span className={cx("chip", TONE_CLASSES[tone], className)} title={title}>
      {children}
    </span>
  );
}

export function StatusIcon({ status, size = 16 }: { status: CheckStatus; size?: number }) {
  if (status === "pass") return <CheckCircle size={size} className="text-ok shrink-0" />;
  if (status === "warn") return <AlertTriangle size={size} className="text-warn shrink-0" />;
  if (status === "fail") return <XCircle size={size} className="text-bad shrink-0" />;
  return <MinusCircle size={size} className="text-subtle shrink-0" />;
}

export function Modal({ open, onClose, title, subtitle, children, width = "max-w-2xl" }: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  width?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  // onClose ist meist eine Inline-Funktion: ueber eine Ref gelesen, damit ein
  // Neurendern der Seite den Fokus nicht aus einem Eingabefeld zurueckholt.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && closeRef.current();
    document.addEventListener("keydown", onKey);
    // Ein Kind (z. B. das Namensfeld) darf den Fokus beim Oeffnen selbst setzen.
    if (!panelRef.current?.contains(document.activeElement)) panelRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  return (
    <div className="anim-fade fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain bg-[var(--backdrop)] p-4 pt-[8vh] backdrop-blur-md no-print">
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cx("anim-panel relative w-full rounded-xl border border-line bg-surface-solid shadow-2xl outline-none", width)}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-fg">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-subtle">{subtitle}</p>}
          </div>
          <button className="btn btn-icon" onClick={onClose} aria-label="Schließen">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, active, onChange, className }: {
  tabs: { key: T; label: string; badge?: React.ReactNode; title?: string }[];
  active: T;
  onChange: (key: T) => void;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  // Bei schmaler Spalte scrollt die Leiste: der aktive Tab bleibt immer sichtbar.
  useEffect(() => {
    const button = listRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]');
    button?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active]);
  return (
    <div
      ref={listRef}
      role="tablist"
      className={cx("flex max-w-full gap-0.5 overflow-x-auto rounded-lg border border-line bg-surface-2 p-0.5 [scrollbar-width:none]", className)}
    >
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          title={tab.title}
          onClick={() => onChange(tab.key)}
          className={cx(
            "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-150 ease-out",
            active === tab.key
              ? "bg-surface-solid text-fg shadow-[0_1px_2px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(255,255,255,0.06)] ring-1 ring-line"
              : "text-subtle hover:text-fg",
          )}
        >
          {tab.label}
          {tab.badge}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, size = "md" }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5" role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cx(
            "rounded-md font-medium transition-colors duration-150",
            size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-xs",
            value === option.value ? "bg-surface-solid text-fg shadow-sm" : "text-subtle hover:text-fg",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, description }: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border border-line p-3">
      <span>
        <span className="block text-sm font-medium text-fg">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-subtle">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors duration-150",
          checked ? "border-accent bg-accent" : "border-line-strong bg-surface-2",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 h-3.5 w-3.5 rounded-full bg-white shadow transition-[left] duration-150",
            checked ? "left-[18px]" : "left-0.5",
          )}
        />
      </button>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Benachrichtigungen
// ---------------------------------------------------------------------------

export interface Toast {
  id: number;
  tone: "ok" | "warn" | "bad" | "info";
  title: string;
  message?: string;
  leaving?: boolean;
}

/** Erfolg und Hinweis 3 s, Warnung und Fehler 6 s (laenger lesbar); Ueberfahren pausiert. */
const TOAST_MS: Record<Toast["tone"], number> = { ok: 3000, info: 3000, warn: 6000, bad: 6000 };

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  const timers = useRef(new Map<number, number>());
  const paused = useRef(false);

  const remove = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    // Erst ausblenden (180 ms), dann entfernen.
    setToasts((all) => all.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    window.setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 180);
  }, []);

  const schedule = useCallback(
    (id: number, ms: number) => {
      window.clearTimeout(timers.current.get(id));
      timers.current.set(id, window.setTimeout(() => remove(id), ms));
    },
    [remove],
  );

  const push = useCallback(
    (toast: Omit<Toast, "id" | "leaving">) => {
      const id = ++counter.current;
      setToasts((all) => [...all.slice(-3), { ...toast, id }]);
      if (!paused.current) schedule(id, TOAST_MS[toast.tone]);
    },
    [schedule],
  );

  const pause = useCallback(() => {
    paused.current = true;
    timers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);
  const resume = useCallback(() => {
    paused.current = false;
    setToasts((all) => {
      all.filter((t) => !t.leaving).forEach((t) => schedule(t.id, 1500));
      return all;
    });
  }, [schedule]);

  return { toasts, push, dismiss: remove, pause, resume };
}

const TOAST_TONE: Record<Toast["tone"], string> = {
  ok: "border-ok-line",
  info: "border-accent-line",
  warn: "border-warn-line",
  bad: "border-bad-line",
};

export function Toaster({ toasts, onDismiss, onPause, onResume }: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
  onPause?: () => void;
  onResume?: () => void;
}) {
  return (
    <div
      className="fixed right-4 top-16 z-[60] flex w-[min(400px,calc(100vw-2rem))] flex-col gap-2 no-print"
      aria-live="polite"
      onMouseEnter={onPause}
      onMouseLeave={onResume}
    >
      {toasts.map((toast) => {
        const tone = toast.tone === "info" ? "accent" : toast.tone;
        const Icon = toast.tone === "ok" ? CheckCircle : toast.tone === "bad" ? XCircle : toast.tone === "warn" ? AlertTriangle : Info;
        return (
          <div
            key={toast.id}
            data-leaving={toast.leaving ? "true" : undefined}
            role={toast.tone === "bad" ? "alert" : "status"}
            className={cx("toast glass-menu flex items-start gap-3 p-3", TOAST_TONE[toast.tone])}
          >
            <span className={cx("mt-0.5 rounded-md border p-1", TONE_CLASSES[tone])}>
              <Icon size={14} aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{toast.title}</p>
              {toast.message && <p className="mt-0.5 break-words text-xs text-muted">{toast.message}</p>}
            </div>
            <button className="text-subtle transition-colors duration-150 hover:text-fg" onClick={() => onDismiss(toast.id)} aria-label="Ausblenden">
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-xl border border-line bg-surface-2 p-3 text-subtle">{icon}</div>
      <p className="text-sm font-medium text-fg">{title}</p>
      {children && <div className="mt-1 max-w-sm text-xs text-subtle">{children}</div>}
    </div>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      className="inline-block shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

/**
 * Tooltip ohne JavaScript: erscheint bei Hover und bei Tastaturfokus im
 * Ausloeser (WCAG 1.4.13: per Fokus erreichbar, ohne Zeigergeraet bedienbar).
 */
export function Tooltip({ content, children, align = "left", side = "top", className }: {
  content: React.ReactNode;
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  side?: "top" | "bottom";
  className?: string;
}) {
  if (!content) return <>{children}</>;
  return (
    <span className={cx("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cx(
          "pointer-events-none absolute z-30 hidden w-max max-w-[320px] rounded-md border border-line bg-surface-solid px-2.5 py-2 text-left font-sans text-xs font-normal leading-snug text-fg shadow-lg group-hover/tt:block group-focus-within/tt:block",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          align === "left" ? "left-0" : align === "right" ? "right-0" : "left-1/2 -translate-x-1/2",
        )}
      >
        {content}
      </span>
    </span>
  );
}

/** „⌘“ auf Apple-Geraeten, sonst „Strg“ (nach dem ersten Render, SSR-sicher). */
export function useModifierLabel(): string {
  const [label, setLabel] = useState("Strg");
  useEffect(() => {
    if (/Mac|iPhone|iPad/i.test(navigator.userAgent)) setLabel("⌘");
  }, []);
  return label;
}

/** Strg+Enter bzw. ⌘+Enter. */
export function isModEnter(event: KeyboardEvent | React.KeyboardEvent): boolean {
  return event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
}

/** Eingabefelder behalten ihre Tasten (J/K tippen statt navigieren). */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function Kbd({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  return (
    <kbd className={cx("kbd-shortcut", className)} title={title}>
      {children}
    </kbd>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton-shimmer rounded-md", className)} aria-hidden="true" />;
}

/**
 * 1-Klick-Kopieren mit 1,5 s Haken-Feedback. Der Button behaelt seine Breite,
 * damit beim Wechsel auf „Kopiert“ nichts springt.
 */
export function CopyButton({ value, label, className }: { value: string; label: string; className?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1500);
  }, [value]);

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={cx(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-md px-1.5 text-xs transition-colors duration-150 ease-out",
        state === "copied" ? "text-ok" : state === "failed" ? "text-bad" : "text-subtle hover:bg-surface-2 hover:text-fg",
        className,
      )}
      aria-label={state === "copied" ? `${label} kopiert` : `${label} kopieren`}
      title={state === "failed" ? "Zwischenablage nicht verfügbar" : `${label} kopieren`}
    >
      <span className="relative inline-flex h-3.5 w-3.5">
        <Copy
          size={13}
          aria-hidden="true"
          className={cx("absolute inset-0 transition-[opacity,transform] duration-150 ease-out", state === "copied" ? "scale-75 opacity-0" : "opacity-100")}
        />
        <Check
          size={13}
          aria-hidden="true"
          className={cx("absolute inset-0 transition-[opacity,transform] duration-150 ease-out", state === "copied" ? "opacity-100" : "scale-75 opacity-0")}
        />
      </span>
      <span aria-live="polite" className={cx("transition-opacity duration-150", state === "idle" ? "sr-only" : "")}>
        {state === "copied" ? "Kopiert" : state === "failed" ? "Fehler" : ""}
      </span>
    </button>
  );
}

/** Kopierbarer Wert in Monospace (Rechnungsnummer, Leitweg-ID, IBAN). */
export function CopyValue({ value, label, display, className }: {
  value: string | null | undefined;
  label: string;
  display?: React.ReactNode;
  className?: string;
}) {
  if (!value) return <span className="text-subtle">–</span>;
  return (
    <span className={cx("inline-flex max-w-full items-center gap-1", className)}>
      <span className="min-w-0 font-mono tabular-nums [overflow-wrap:anywhere]">{display ?? value}</span>
      <CopyButton value={value} label={label} />
    </span>
  );
}

/**
 * Gekuerzter Hash im Monospace-Badge mit Verifikationsstatus und Kopierbutton.
 * ``verified``: true = nachgerechnet/Signatur gueltig, false = Befund, null = nicht geprueft.
 */
export function HashBadge({ value, label = "SHA-256", verified = null, verifiedLabel, className }: {
  value: string;
  label?: string;
  verified?: boolean | null;
  verifiedLabel?: string;
  className?: string;
}) {
  const short = value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
  const tone = verified === true ? "ok" : verified === false ? "bad" : "neutral";
  const status = verified === true ? verifiedLabel ?? "verifiziert" : verified === false ? "Befund" : null;
  return (
    <span className={cx("inline-flex max-w-full flex-wrap items-center gap-1", className)}>
      <span
        className={cx("chip font-mono text-xs tabular-nums", TONE_CLASSES[tone])}
        title={`${label} ${value}`}
      >
        {verified === true && <ShieldCheck size={11} aria-hidden="true" />}
        {verified === false && <ShieldAlert size={11} aria-hidden="true" />}
        <span className="opacity-70">{label}</span> {short}
        {status && <span className="font-sans opacity-80">· {status}</span>}
      </span>
      <CopyButton value={value} label={label} />
    </span>
  );
}
