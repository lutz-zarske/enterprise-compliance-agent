"use client";

import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cx } from "../lib/format";
import { popoverStyle, usePopoverExclusive } from "../lib/popover";
import { Check, ChevronDown } from "./icons";

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  hint?: string;
}

/**
 * Dropdown im Glas-Design.
 *
 * Ersetzt das native <select>, das das Betriebssystem zeichnet und das deshalb
 * als eckiger Fremdkoerper im Layout sitzt. Die Liste schwebt als Portal ueber
 * dem Layout (kein Springen der Spalte); Pfeiltasten bewegen, Enter/Leertaste
 * uebernehmen, Escape schliesst, Tab verlaesst. Rollen combobox/listbox/option.
 */
export function Select<T extends string = string>({ value, options, onChange, ariaLabel, className, width = 220 }: {
  value: T;
  options: readonly SelectOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
  width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [style, setStyle] = useState<React.CSSProperties>({ position: "fixed", visibility: "hidden" });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const id = useId();
  const selected = options.find((option) => option.value === value);
  const close = useCallback(() => setOpen(false), []);
  // Hoechstens ein Menue offen: oeffnet sich ein anderes, schliesst dieses.
  usePopoverExclusive(open, close, `select-${id}`);

  useEffect(() => {
    if (open) setActive(Math.max(0, options.findIndex((option) => option.value === value)));
  }, [open, options, value]);

  // Klick nach draussen, Scrollen der Seite und Groessenaenderung schliessen die Liste.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!buttonRef.current?.contains(target) && !listRef.current?.contains(target)) setOpen(false);
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && listRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (open && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      // Mindestens so breit wie das Feld; am Fensterrand geklemmt (popoverStyle).
      setStyle(popoverStyle(rect, { width: Math.max(width, Math.round(rect.width)), align: "right" }));
    }
  }, [open, width]);

  const choose = useCallback(
    (option: SelectOption<T>) => {
      onChange(option.value);
      setOpen(false);
      buttonRef.current?.focus();
    },
    [onChange],
  );

  function onKeyDown(event: React.KeyboardEvent) {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step !== undefined) {
      event.preventDefault();
      if (!open) setOpen(true);
      else setActive((index) => (index + step + options.length) % options.length);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open && options[active]) choose(options[active]);
      else setOpen(true);
    } else if (event.key === "Escape" && open) {
      // Nur die Liste schliessen, nicht zusaetzlich einen umgebenden Dialog.
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={`${id}-list`}
        aria-label={ariaLabel}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onKeyDown}
        className={cx(
          "inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors duration-150",
          open ? "border-accent-line bg-surface-2 text-fg" : "border-line bg-surface-solid text-muted hover:border-line-strong hover:text-fg",
          className,
        )}
      >
        <span className="truncate">{selected?.label ?? "Bitte wählen"}</span>
        <ChevronDown
          size={13}
          aria-hidden="true"
          className={cx("shrink-0 text-subtle transition-transform duration-200 ease-out", open && "rotate-180")}
        />
      </button>
      {open &&
        createPortal(
          <ul
            id={`${id}-list`}
            ref={listRef}
            role="listbox"
            aria-label={ariaLabel}
            style={style}
            className="glass-menu scroll-area z-[70] overscroll-contain p-1"
          >
            {options.map((option, index) => {
              const isSelected = option.value === value;
              return (
                <li
                  key={option.value}
                  role="option"
                  aria-selected={isSelected}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option)}
                  className={cx(
                    "flex cursor-pointer items-start gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors duration-100",
                    index === active && "bg-surface-2",
                  )}
                >
                  <Check size={13} aria-hidden="true" className={cx("mt-0.5 shrink-0 text-accent", !isSelected && "invisible")} />
                  <span className="min-w-0">
                    <span className={cx("block truncate", isSelected ? "font-semibold text-fg" : "text-muted")}>{option.label}</span>
                    {option.hint && <span className="mt-0.5 block leading-snug text-subtle">{option.hint}</span>}
                  </span>
                </li>
              );
            })}
          </ul>,
          document.body,
        )}
    </>
  );
}
