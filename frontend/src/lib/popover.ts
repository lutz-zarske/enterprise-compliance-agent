import type React from "react";
import { useEffect, useId, useLayoutEffect, useState } from "react";

/**
 * Lage eines schwebenden Menüs (Portal, position: fixed) zum Auslöser:
 * unter dem Feld, bei zu wenig Platz darüber; links- oder rechtsbündig.
 * Die Höhe ist auf den sichtbaren Bereich begrenzt - auf 1080p ragt nichts
 * unten heraus.
 */
export function popoverStyle(
  anchor: DOMRect,
  { width, maxHeight = 320, align = "left" }: { width: number; maxHeight?: number; align?: "left" | "right" },
): React.CSSProperties {
  const margin = 6;
  const below = window.innerHeight - anchor.bottom - margin - 8;
  const above = anchor.top - margin - 8;
  const openUp = below < Math.min(maxHeight, 200) && above > below;
  const fitted = Math.min(width, window.innerWidth - 16);
  const left = align === "right" ? anchor.right - fitted : anchor.left;
  return {
    position: "fixed",
    width: fitted,
    left: Math.max(8, Math.min(left, window.innerWidth - fitted - 8)),
    maxHeight: Math.max(120, Math.min(maxHeight, openUp ? above : below)),
    ...(openUp ? { bottom: window.innerHeight - anchor.top + margin } : { top: anchor.bottom + margin }),
    ["--origin" as string]: openUp ? "bottom" : "top",
  };
}

/**
 * Lage eines Portal-Popovers am Auslöser, nachgeführt bei Größenänderung.
 * Popovers der Kopfzeile laufen bewusst über ein Portal: Die Kopfzeile trägt
 * ``backdrop-filter``, und verschachtelte Glas-Menüs zeichnet Chromium darin
 * ohne eigenen Blur - sie wirken durchsichtig.
 */
export function useAnchoredStyle(
  open: boolean,
  anchorRef: React.RefObject<HTMLElement | null>,
  { width, maxHeight, align }: { width: number; maxHeight?: number; align?: "left" | "right" },
): React.CSSProperties {
  const [style, setStyle] = useState<React.CSSProperties>({ position: "fixed", visibility: "hidden" });
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = anchorRef.current;
      if (anchor) setStyle(popoverStyle(anchor.getBoundingClientRect(), { width, maxHeight, align }));
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, anchorRef, width, maxHeight, align]);
  return style;
}

const POPOVER_EVENT = "eca-popover-open";

/**
 * Popover-Bus: Höchstens ein Menü oder Popover ist gleichzeitig offen.
 * Öffnet sich eines (Select, Musterdaten, Job-Monitor, Hinweise, Version),
 * meldet es das über ein Fenster-Ereignis; alle anderen schließen sich.
 */
export function usePopoverExclusive(open: boolean, close: () => void, key?: string): void {
  const auto = useId();
  const id = key ?? auto;
  useEffect(() => {
    if (!open) return;
    window.dispatchEvent(new CustomEvent(POPOVER_EVENT, { detail: id }));
    const onOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== id) close();
    };
    window.addEventListener(POPOVER_EVENT, onOther);
    return () => window.removeEventListener(POPOVER_EVENT, onOther);
  }, [open, id, close]);
}

/** Klick daneben und Escape schließen ein Popover (Escape erreicht keinen umgebenden Dialog). */
export function useDismiss(
  open: boolean,
  close: () => void,
  refs: ReadonlyArray<React.RefObject<HTMLElement | null>>,
): void {
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!refs.some((ref) => ref.current?.contains(target))) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
    // refs sind stabile Ref-Objekte.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, close]);
}
