import type React from "react";

/**
 * Lage eines schwebenden Menues (Portal, position: fixed) zum Ausloeser:
 * unter dem Feld, bei zu wenig Platz darueber; links- oder rechtsbuendig.
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
    maxHeight: Math.min(maxHeight, openUp ? above : below),
    ...(openUp ? { bottom: window.innerHeight - anchor.top + margin } : { top: anchor.bottom + margin }),
    ["--origin" as string]: openUp ? "bottom" : "top",
  };
}
