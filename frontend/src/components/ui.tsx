"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import type { CheckStatus } from "../types/api";
import { cx, TONE_CLASSES, type Tone } from "../lib/format";
import { AlertTriangle, CheckCircle, Info, MinusCircle, X, XCircle } from "./icons";

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

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain bg-slate-950/50 p-4 pt-[8vh] no-print">
      <div className="absolute inset-0" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cx("relative w-full rounded-xl border border-line bg-surface-solid shadow-2xl outline-none", width)}
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
  tabs: { key: T; label: string; badge?: React.ReactNode }[];
  active: T;
  onChange: (key: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" className={cx("flex gap-1 overflow-x-auto border-b border-line", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          onClick={() => onChange(tab.key)}
          className={cx(
            "-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors duration-150",
            active === tab.key ? "border-accent text-fg" : "border-transparent text-subtle hover:text-fg",
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
            size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-xs",
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
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = ++counter.current;
      setToasts((all) => [...all.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), toast.tone === "bad" ? 9000 : 5000);
    },
    [dismiss],
  );
  return { toasts, push, dismiss };
}

export function Toaster({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2 no-print" aria-live="polite">
      {toasts.map((toast) => {
        const tone = toast.tone === "info" ? "accent" : toast.tone;
        const Icon = toast.tone === "ok" ? CheckCircle : toast.tone === "bad" ? XCircle : toast.tone === "warn" ? AlertTriangle : Info;
        return (
          <div key={toast.id} className="flex items-start gap-3 rounded-lg border border-line bg-surface-solid p-3 shadow-lg">
            <span className={cx("mt-0.5 rounded-md border p-1", TONE_CLASSES[tone])}>
              <Icon size={14} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{toast.title}</p>
              {toast.message && <p className="mt-0.5 break-words text-xs text-subtle">{toast.message}</p>}
            </div>
            <button className="text-subtle hover:text-fg" onClick={() => onDismiss(toast.id)} aria-label="Ausblenden">
              <X size={14} />
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
export function Tooltip({ content, children, align = "left", className }: {
  content: React.ReactNode;
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  if (!content) return <>{children}</>;
  return (
    <span className={cx("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cx(
          "pointer-events-none absolute bottom-full z-30 mb-1.5 hidden w-max max-w-[300px] rounded-md border border-line bg-surface-solid px-2.5 py-2 text-left font-sans text-[11.5px] font-normal leading-snug text-fg shadow-lg group-hover/tt:block group-focus-within/tt:block",
          align === "left" ? "left-0" : "right-0",
        )}
      >
        {content}
      </span>
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("rounded-md bg-surface-2", className)} aria-hidden="true" />;
}
