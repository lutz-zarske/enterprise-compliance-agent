"use client";

import React, { useEffect, useState } from "react";
import { useI18n } from "../lib/i18n";
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
 * weiter; nur Cloud-KI, VIES und der Release-Abgleich pausieren.
 */
export function OfflineBadge() {
  const offline = useBrowserOffline();
  const { tr } = useI18n();
  if (!offline) return null;
  return (
    <Tooltip
      side="bottom"
      align="right"
      content={tr(
        "Keine Internetverbindung: Lokale Prüfungen, das Regelwerk und das Ledger laufen weiter. Cloud-KI, VIES-Abfrage und Release-Abgleich pausieren, bis die Verbindung zurück ist.",
        "No internet connection: Local audits, rule engine, and ledger keep working. Cloud AI, VIES checks, and release sync pause until reconnected.",
        "Sin conexión a internet: Las auditorías locales, reglas y registro siguen activos. IA en la nube, VIES y actualizaciones quedan en pausa.",
      )}
    >
      <span tabIndex={0} role="status" className="chip cursor-help border-accent-line bg-accent-soft py-1 text-accent">
        <WifiOff size={12} aria-hidden="true" /> {tr("Offline · lokal weiter", "Offline · local active", "Sin red · modo local")}
      </span>
    </Tooltip>
  );
}
