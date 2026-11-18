"use client";

import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CheckStatus } from "../types/api";
import { cx, formatEta, TONE_CLASSES, type Tone } from "../lib/format";
import { tr, useI18n } from "../lib/i18n";
import { AlertTriangle, Check, CheckCircle, Copy, Info, MinusCircle, X, XCircle } from "./icons";

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

const FOCUSABLE_SELECTOR =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])';

/**
 * Sperrt den Hintergrund (#eca-app-shell via inert), fängt Tab im Dialog,
 * schließt auf Escape und gibt beim Schließen den Fokus zurück.
 */
export function useModalFocusLock(
  open: boolean,
  panelRef: React.RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const shell = document.getElementById("eca-app-shell");
    shell?.setAttribute("inert", "");

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeRef.current();
        return;
      }
      if (event.key === "Tab" && panelRef.current) {
        const focusables = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
          (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden",
        );
        if (!focusables.length) {
          event.preventDefault();
          panelRef.current.focus();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    // Ein Kind (z. B. das Namensfeld) darf den Fokus beim Öffnen selbst setzen.
    if (!panelRef.current?.contains(document.activeElement)) panelRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      shell?.removeAttribute("inert");
      if (previous && document.contains(previous)) previous.focus();
    };
  }, [open, panelRef]);
}

export function Modal({ open, onClose, title, subtitle, children, width = "max-w-2xl", padded = true }: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  width?: string;
  /** false: Inhalt ohne Innenabstand (z. B. zweispaltige Einstellungen). */
  padded?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  useModalFocusLock(open, panelRef, onClose);

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="anim-fade fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto overscroll-contain bg-[var(--backdrop)] p-4 pt-[6vh] backdrop-blur-md no-print">
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cx("anim-panel relative w-full rounded-2xl border border-line bg-surface-solid shadow-2xl outline-none", width)}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-fg">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-subtle">{subtitle}</p>}
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label={tr("Schließen", "Close", "Cerrar")}>
            <X size={16} />
          </button>
        </div>
        <div className={padded ? "px-5 py-4" : undefined}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export interface PillTabItem<T extends string> {
  key: T;
  label: React.ReactNode;
  badge?: React.ReactNode;
  title?: string;
  disabled?: boolean;
  /** Kleiner Statuspunkt am Tab (z. B. laufende Analyse). */
  dot?: "live" | "warn" | null;
}

/**
 * Segmentschalter mit gleitendem Indikator (einzige Bewegung mit Funktion: Sie zeigt,
 * wohin die Auswahl wandert).  Der Indikator wird am aktiven Tab ausgemessen - ohne
 * Animationsbibliothek; bei reduzierter Bewegung springt er.
 */
export function PillTabs<T extends string>({ items, value, onChange, className, ariaLabel, size = "md", role = "tablist", idPrefix }: {
  items: PillTabItem<T>[];
  value: T;
  onChange: (key: T) => void;
  className?: string;
  ariaLabel?: string;
  size?: "sm" | "md";
  role?: "tablist" | "radiogroup";
  idPrefix?: string;
}) {
  const { tr: tl } = useI18n();
  const listRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState<{ left: number; width: number; animate: boolean } | null>(null);
  // Zuletzt sichtbar angezeigte Auswahl: Nur ein echter Wechsel gleitet, ein Wieder-Einblenden
  // (Keep-Alive-Ansichten, Modale) oder eine Größenänderung setzt den Indikator still.
  const shownValue = useRef<T | null>(null);
  const radio = role === "radiogroup";

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((item) => !item.disabled);
    if (enabled.length < 2) return;
    let delta = 0;
    if (event.key === "ArrowRight" || (radio && event.key === "ArrowDown")) delta = 1;
    else if (event.key === "ArrowLeft" || (radio && event.key === "ArrowUp")) delta = -1;
    else if (event.key === "Home") delta = -999;
    else if (event.key === "End") delta = 999;
    else return;
    event.preventDefault();
    const curIndex = Math.max(0, enabled.findIndex((item) => item.key === value));
    const next =
      delta === -999
        ? enabled[0]
        : delta === 999
          ? enabled[enabled.length - 1]
          : enabled[(curIndex + delta + enabled.length) % enabled.length];
    onChange(next.key);
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[data-pill-key]');
    buttons?.forEach((btn) => {
      if (btn.dataset.pillKey === next.key) btn.focus();
    });
  };

  useLayoutEffect(() => {
    const measure = (valueChanged: boolean) => {
      const button = listRef.current?.querySelector<HTMLButtonElement>('[data-active="true"]');
      if (!button) return setIndicator(null);
      // Verborgene Ansicht (display: none): letzten Stand behalten statt auf 0 zu springen.
      if (button.offsetWidth === 0) return;
      const left = button.offsetLeft;
      const width = button.offsetWidth;
      const animate = valueChanged && shownValue.current !== null && shownValue.current !== value;
      shownValue.current = value;
      setIndicator((prev) => (prev && prev.left === left && prev.width === width ? prev : { left, width, animate }));
    };
    measure(true);
    const observer = new ResizeObserver(() => measure(false));
    if (listRef.current) observer.observe(listRef.current);
    return () => observer.disconnect();
  }, [value, items.length]);

  // Bei schmaler Spalte scrollt die Leiste: der aktive Tab bleibt immer sichtbar.
  // Bewusst nur waagerecht in der Leiste selbst - scrollIntoView würde auch die Seite
  // verschieben (auf schmalen Fenstern sprang sie beim Laden zum Inspektor).
  useEffect(() => {
    const list = listRef.current;
    const button = list?.querySelector<HTMLButtonElement>('[data-active="true"]');
    if (!list || !button || list.scrollWidth <= list.clientWidth) return;
    const left = button.offsetLeft;
    const right = left + button.offsetWidth;
    if (left < list.scrollLeft) list.scrollLeft = left;
    else if (right > list.scrollLeft + list.clientWidth) list.scrollLeft = right - list.clientWidth;
  }, [value]);

  return (
    <div
      ref={listRef}
      role={role}
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={cx("pill-tabs max-w-full overflow-x-auto [scrollbar-width:none]", size === "sm" && "pill-tabs-sm", className)}
    >
      {indicator && (
        <span
          className="pill-indikator"
          aria-hidden="true"
          style={{
            width: indicator.width,
            transform: `translateX(${indicator.left}px)`,
            transition: indicator.animate ? undefined : "none",
          }}
        />
      )}
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            id={idPrefix ? `${idPrefix}-tab-${item.key}` : undefined}
            type="button"
            role={radio ? "radio" : "tab"}
            tabIndex={active ? 0 : -1}
            aria-selected={radio ? undefined : active}
            aria-checked={radio ? active : undefined}
            aria-controls={idPrefix && !radio ? `${idPrefix}-panel-${item.key}` : undefined}
            data-pill-key={item.key}
            data-active={active}
            title={item.title}
            disabled={item.disabled}
            onClick={() => onChange(item.key)}
            className="pill-tab"
          >
            {item.label}
            {item.badge}
            {item.dot === "live" && (
              <span className="relative inline-flex h-1.5 w-1.5 text-accent" aria-hidden="true">
                <span className="status-pulse" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
              </span>
            )}
            {item.dot === "warn" && <span className="h-1.5 w-1.5 rounded-full bg-warn" role="img" aria-label={tl("Hinweis", "Notice", "Aviso")} />}
          </button>
        );
      })}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, active, onChange, className, idPrefix }: {
  tabs: { key: T; label: string; badge?: React.ReactNode; title?: string }[];
  active: T;
  onChange: (key: T) => void;
  className?: string;
  idPrefix?: string;
}) {
  return <PillTabs items={tabs} value={active} onChange={onChange} className={className} idPrefix={idPrefix} />;
}

export function Segmented<T extends string>({ options, value, onChange, size = "md", ariaLabel }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  ariaLabel?: string;
}) {
  return (
    <PillTabs
      role="radiogroup"
      size={size}
      ariaLabel={ariaLabel}
      value={value}
      onChange={onChange}
      items={options.map((option) => ({ key: option.value, label: option.label }))}
    />
  );
}

/** Fortschrittsbalken; ``null`` = unbestimmt (laufender Balken). */
export function ProgressBar({ value, className, label }: { value: number | null; className?: string; label?: string }) {
  const indeterminate = value === null || !Number.isFinite(value);
  const pct = indeterminate ? 0 : Math.max(0, Math.min(100, value * 100));
  return (
    <div
      className={cx("progress-track", className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
    >
      <div className="progress-fill" data-indeterminate={indeterminate} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Kleiner Fortschrittsring (16 px) für die Kopfzeile - platzsparender als ein Balken. */
export function MiniRing({ value }: { value: number }) {
  const r = 6;
  const circumference = 2 * Math.PI * r;
  const share = Math.max(0, Math.min(1, value));
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 -rotate-90" aria-hidden="true">
      <circle cx="8" cy="8" r={r} fill="none" stroke="currentColor" strokeWidth="2" className="opacity-25" />
      <circle
        cx="8"
        cy="8"
        r={r}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - share)}
        className="transition-[stroke-dashoffset] duration-500 ease-out"
      />
    </svg>
  );
}

/** Restzeit, die zwischen zwei Meldungen sekündlich weiterzählt und sich weich angleicht. */
export function Eta({ seconds, className }: { seconds: number | null | undefined; className?: string }) {
  const anchor = useRef<{ value: number; at: number } | null>(null);
  const [shown, setShown] = useState<number | null>(null);
  useEffect(() => {
    if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
      anchor.current = null;
      setShown(null);
      return;
    }
    const now = performance.now();
    const previous = anchor.current;
    const local = previous ? Math.max(0, previous.value - (now - previous.at) / 1000) : seconds;
    const value = previous ? local + 0.35 * (seconds - local) : seconds;
    anchor.current = { value, at: now };
    setShown(value);
  }, [seconds]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = anchor.current;
      if (current) setShown(Math.max(1, current.value - (performance.now() - current.at) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (shown === null) return null;
  return <span className={cx("tabular-nums", className)}>{formatEta(shown)}</span>;
}

/**
 * Mehrzeiliges Eingabefeld, das mit dem Inhalt wächst (bis ``maxRows``), danach
 * scrollt - ohne manuelle Zieh-Ecke.
 */
export const AutoTextarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  minRows?: number;
  maxRows?: number;
}>(function AutoTextarea({ minRows = 2, maxRows = 8, className, value, onChange, ...rest }, forwarded) {
  const inner = useRef<HTMLTextAreaElement>(null);
  const setRef = useCallback(
    (node: HTMLTextAreaElement | null) => {
      inner.current = node;
      if (typeof forwarded === "function") forwarded(node);
      else if (forwarded) forwarded.current = node;
    },
    [forwarded],
  );
  useLayoutEffect(() => {
    const node = inner.current;
    if (!node) return;
    const style = window.getComputedStyle(node);
    const line = parseFloat(style.lineHeight) || 20;
    const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    node.style.height = "auto";
    const min = line * minRows + padding + border;
    const max = line * maxRows + padding + border;
    const height = Math.min(max, Math.max(min, node.scrollHeight + border));
    node.style.height = `${height}px`;
    node.style.overflowY = node.scrollHeight + border > max ? "auto" : "hidden";
  }, [value, minRows, maxRows]);
  return (
    <textarea
      ref={setRef}
      rows={minRows}
      value={value}
      onChange={onChange}
      className={cx("input scroll-area resize-none", className)}
      {...rest}
    />
  );
});

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

/** Erfolg und Hinweis 3 s, Warnung und Fehler 6 s (länger lesbar); Überfahren pausiert. */
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
            <button type="button" className="icon-target -mr-1 -mt-1 rounded-md text-subtle transition-colors duration-150 hover:text-fg" onClick={() => onDismiss(toast.id)} aria-label={tr("Ausblenden", "Dismiss", "Ocultar")}>
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

const TIP_MARGIN = 8;
/** Nach dem ersten Tooltip erscheinen weitere sofort (eine Leiste fühlt sich dadurch schneller an). */
let lastTipClosedAt = 0;

/**
 * Tooltip per Portal: hängt mit fester Position an ``<body>`` und wird an das
 * Fenster geklemmt - in Scrollbereichen, Karten mit ``overflow: hidden`` und am
 * Bildschirmrand (1080p) wird nichts abgeschnitten.  Erscheint bei Hover und
 * Tastaturfokus (WCAG 1.4.13), Escape schließt.  ``align``/``side`` sind nur
 * Vorzugsrichtungen.
 */
export function Tooltip({ content, children, align = "left", side = "top", className, inline = false }: {
  content: React.ReactNode;
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  side?: "top" | "bottom";
  className?: string;
  /** Im Fließtext (z. B. Belegzeilen) ``inline`` statt ``inline-flex``, damit der Umbruch erhalten bleibt. */
  inline?: boolean;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const bubbleRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | null>(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  const show = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    const instant = Date.now() - lastTipClosedAt < 400;
    timer.current = window.setTimeout(() => setOpen(true), instant ? 0 : 180);
  }, []);
  const hide = useCallback(() => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen((was) => {
      if (was) lastTipClosedAt = Date.now();
      return false;
    });
    setPosition(null);
  }, []);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && hide();
    const onScroll = () => hide();
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open, hide]);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current || !bubbleRef.current) return;
    const anchor = anchorRef.current.getBoundingClientRect();
    const bubble = bubbleRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left =
      align === "left" ? anchor.left : align === "right" ? anchor.right - bubble.width : anchor.left + anchor.width / 2 - bubble.width / 2;
    left = Math.max(TIP_MARGIN, Math.min(left, vw - bubble.width - TIP_MARGIN));
    const below = anchor.bottom + 6;
    const above = anchor.top - bubble.height - 6;
    let top = side === "bottom" ? below : above;
    if (side === "bottom" && below + bubble.height > vh - TIP_MARGIN && above >= TIP_MARGIN) top = above;
    if (side === "top" && above < TIP_MARGIN) top = below;
    setPosition({ top: Math.max(TIP_MARGIN, top), left });
  }, [open, align, side]);

  if (!content) return <>{children}</>;
  return (
    <span
      ref={anchorRef}
      className={cx(inline ? "inline" : "inline-flex", className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <span
            ref={bubbleRef}
            id={id}
            role="tooltip"
            className="tip-bubble"
            style={{ top: position?.top ?? 0, left: position?.left ?? 0, visibility: position ? "visible" : "hidden" }}
          >
            {content}
          </span>,
          document.body,
        )}
    </span>
  );
}

/** „⌘“ auf Apple-Geräten, sonst „Strg“ / „Ctrl“ (nach dem ersten Render, SSR-sicher). */
export function useModifierLabel(): string {
  const { tr: tl } = useI18n();
  const [apple, setApple] = useState(false);
  useEffect(() => {
    if (/Mac|iPhone|iPad/i.test(navigator.userAgent)) setApple(true);
  }, []);
  return apple ? "⌘" : tl("Strg", "Ctrl", "Ctrl");
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
 * 1-Klick-Kopieren mit 1,5 s Haken-Feedback. Der Button behält seine Breite,
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
      aria-label={state === "copied" ? `${label} ${tr("kopiert", "copied", "copiado")}` : `${label} ${tr("kopieren", "copy", "copiar")}`}
      title={state === "failed" ? tr("Zwischenablage nicht verfügbar", "Clipboard unavailable", "Portapapeles no disponible") : `${label} ${tr("kopieren", "copy", "copiar")}`}
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
        {state === "copied" ? tr("Kopiert", "Copied", "Copiado") : state === "failed" ? tr("Fehler", "Error", "Error") : ""}
      </span>
    </button>
  );
}

/** Kopierbarer Wert mit Tabellenziffern (Rechnungsnummer, Leitweg-ID, IBAN); ``mono`` nur für Hashes/IDs. */
export function CopyValue({ value, label, display, className, mono = false }: {
  value: string | null | undefined;
  label: string;
  display?: React.ReactNode;
  className?: string;
  mono?: boolean;
}) {
  if (!value) return <span className="text-subtle">–</span>;
  return (
    <span className={cx("inline-flex max-w-full items-center gap-1", className)}>
      <span className={cx("min-w-0 tabular-nums [overflow-wrap:anywhere]", mono && "font-mono")}>{display ?? value}</span>
      <CopyButton value={value} label={label} />
    </span>
  );
}

/**
 * Gekürzter Hash im Monospace-Badge mit Verifikationsstatus und Kopierbutton.
 * ``verified``: true = nachgerechnet/Signatur gültig, false = Befund, null = nicht geprüft.
 */
export function HashBadge({ value, label = "SHA-256", verified = null, verifiedLabel, className, statusIcon = true }: {
  value: string;
  label?: string;
  verified?: boolean | null;
  verifiedLabel?: string;
  className?: string;
  /** Schild im Chip; aus, wenn daneben schon ein eigenes Symbol steht. */
  statusIcon?: boolean;
}) {
  const { tr: tl } = useI18n();
  const short = value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
  const tone = verified === true ? "ok" : verified === false ? "bad" : "neutral";
  const status =
    verified === true
      ? verifiedLabel ?? tl("verifiziert", "verified", "verificado")
      : verified === false
        ? tl("Befund", "Mismatch", "Anomalía")
        : null;
  return (
    <span className={cx("inline-flex max-w-full items-center gap-1", className)}>
      <span
        className={cx("chip min-w-0 font-mono text-xs tabular-nums", TONE_CLASSES[tone])}
        title={`${label} ${value}`}
      >
        {statusIcon && verified === true && <CheckCircle size={11} aria-hidden="true" />}
        {statusIcon && verified === false && <AlertTriangle size={11} aria-hidden="true" />}
        <span className="opacity-70">{label}</span> {short}
        {status && <span className="font-sans opacity-80">· {status}</span>}
      </span>
      <CopyButton value={value} label={label} />
    </span>
  );
}
