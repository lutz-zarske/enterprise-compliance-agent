"use client";

/**
 * Blendet den Kaltstart-Splash aus (Markup steht im Server-HTML von layout.tsx).
 *
 * Der Splash deckt den ersten Paint ab, bis die Seite ihre Startdaten hat -
 * dann meldet page.tsx ``meldeBereit()``. Spaetestens nach SPLASH_MAX_MS geht er
 * auch ohne Meldung (Backend offline); ohne JavaScript nimmt ihn CSS weg.
 * Bewusst DOM statt React-Zustand: das Server-Markup bleibt bei der Hydration unveraendert.
 */
import { useEffect } from "react";

const BEREIT_EREIGNIS = "eca:bereit";
const SPLASH_MAX_MS = 2500;
const SPLASH_MIN_MS = 250;

type BereitFenster = Window & { __ecaBereit?: boolean };

/** Von der Seite aufzurufen, sobald die Startdaten stehen (oder feststeht, dass das Backend fehlt). */
export function meldeBereit(): void {
  if (typeof window === "undefined") return;
  (window as BereitFenster).__ecaBereit = true;
  window.dispatchEvent(new Event(BEREIT_EREIGNIS));
}

export function SplashAbbau() {
  useEffect(() => {
    const splash = document.getElementById("eca-splash");
    if (!splash) return;
    const start = performance.now();
    let fertig = false;
    const weg = () => {
      if (fertig) return;
      fertig = true;
      // Zwei Frames warten: React hat die geladenen Daten dann sicher gezeichnet.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          const rest = Math.max(0, SPLASH_MIN_MS - (performance.now() - start));
          window.setTimeout(() => {
            splash.classList.add("ist-weg");
            // Nicht aus dem DOM nehmen (React verwaltet den Knoten) - nur ganz ausblenden.
            window.setTimeout(() => splash.classList.add("ist-aus"), 400);
          }, rest);
        }),
      );
    };
    if ((window as BereitFenster).__ecaBereit) weg();
    window.addEventListener(BEREIT_EREIGNIS, weg, { once: true });
    const notaus = window.setTimeout(weg, SPLASH_MAX_MS);
    return () => {
      window.removeEventListener(BEREIT_EREIGNIS, weg);
      window.clearTimeout(notaus);
    };
  }, []);
  return null;
}
