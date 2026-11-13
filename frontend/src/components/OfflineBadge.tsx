"use client";

import React, { useEffect, useState } from "react";
import { WifiOff } from "./icons";
import { Tooltip } from "./ui";

/** Browser meldet keine Internetverbindung (``navigator.onLine``, Ereignisse online/offline). */
export function useBrowserOffline(): boolean {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(typeof navigator !== "undefined" && navigator.onLine === false);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return offline;
}

/**
 * Ruhiger Hinweis ohne Internet: Lokale Pruefungen, Regelwerk und Ledger laufen
 * weiter; nur Cloud-KI, VIES und der Release-Abgleich pausieren.  Erscheint nur
 * offline und verschwindet, sobald die Verbindung zurueck ist.
 */
export function OfflineBadge() {
  const offline = useBrowserOffline();
  if (!offline) return null;
  return (
    <Tooltip
      side="bottom"
      align="right"
      content="Keine Internetverbindung: Lokale Prüfungen, das Regelwerk und das Ledger laufen weiter. Cloud-KI, VIES-Abfrage und Release-Abgleich pausieren, bis die Verbindung zurück ist."
    >
      <span tabIndex={0} role="status" className="chip cursor-help border-accent-line bg-accent-soft py-1 text-accent">
        <WifiOff size={12} aria-hidden="true" /> Offline · lokal weiter
      </span>
    </Tooltip>
  );
}
