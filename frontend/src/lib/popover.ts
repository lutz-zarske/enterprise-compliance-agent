import type React from "react";
import { useEffect, useId } from "react";

/**
 * Lage eines schwebenden Menues (Portal, position: fixed) zum Ausloeser:
 * unter dem Feld, bei zu wenig Platz darueber; links- oder rechtsbuendig.
 * Die Hoehe ist auf den sichtbaren Bereich begrenzt - auf 1080p ragt nichts
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
  const left = align === "right" ? anchor.right - width : anchor.left;
  return {
    position: "fixed",
    width,
    left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
    maxHeight: Math.max(120, Math.min(maxHeight, openUp ? above : below)),
    ...(openUp ? { bottom: window.innerHeight - anchor.top + margin } : { top: anchor.bottom + margin }),
    ["--origin" as string]: openUp ? "bottom" : "top",
  };
}

const POPOVER_EVENT = "eca-popover-open";

/**
 * Popover-Bus: Hoechstens ein Menue oder Popover ist gleichzeitig offen.
 * Oeffnet sich eines (Select, Musterdaten, Job-Monitor, Hinweise, Version),
 * meldet es das ueber ein Fenster-Ereignis; alle anderen schliessen sich.
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

/** Klick daneben und Escape schliessen ein Popover (Escape erreicht keinen umgebenden Dialog). */
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
