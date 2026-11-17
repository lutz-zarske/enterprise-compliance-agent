"use client";

import { useEffect } from "react";
import { useI18n } from "../lib/i18n";

/**
 * Ruhige Absturz-Abfangseite (Next.js-Fehlergrenze): keine rohen Exceptions, sondern
 * eine verstaendliche Meldung mit Handlungsanweisung.  Pruefergebnisse und Ledger
 * liegen im Backend und bleiben unberuehrt.
 */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { tr } = useI18n();

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-6 text-fg">
      <section className="card max-w-md p-6" role="alert">
        <h1 className="text-base font-semibold">
          {tr(
            "Die Ansicht wurde unerwartet beendet",
            "The view ended unexpectedly",
            "La vista se cerró de forma inesperada",
          )}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          {tr(
            "Prüfergebnisse, Siegel und das Prüfprotokoll liegen sicher im Backend und sind nicht betroffen. Ein Neuladen stellt die Oberfläche wieder her.",
            "Audit results, seals and the audit trail are stored safely in the backend and are unaffected. Reloading restores the interface.",
            "Los resultados, sellos y el registro de auditoría permanecen seguros en el backend. Recargar restaurará la interfaz.",
          )}
        </p>
        {error.digest && (
          <p className="mt-2 text-xs text-subtle">
            {tr("Fehlerkennung:", "Error ID:", "ID de error:")} <span className="font-mono">{error.digest}</span>
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" className="btn btn-primary" onClick={() => reset()}>
            {tr("Ansicht neu aufbauen", "Rebuild view", "Reconstruir vista")}
          </button>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            {tr("Neu laden", "Reload", "Recargar")}
          </button>
        </div>
      </section>
    </main>
  );
}
