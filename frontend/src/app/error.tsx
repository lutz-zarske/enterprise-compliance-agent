"use client";

import { useEffect } from "react";

/**
 * Ruhige Absturz-Abfangseite (Next.js-Fehlergrenze): keine rohen Exceptions, sondern
 * eine verstaendliche Meldung mit Handlungsanweisung.  Pruefergebnisse und Ledger
 * liegen im Backend und bleiben unberuehrt.
 */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-6 text-fg">
      <section className="card max-w-md p-6" role="alert">
        <h1 className="text-base font-semibold">Die Ansicht wurde unerwartet beendet</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Prüfergebnisse, Siegel und das Prüfprotokoll liegen sicher im Backend und sind nicht betroffen. Ein Neuladen stellt die
          Oberfläche wieder her.
        </p>
        {error.digest && <p className="mt-2 text-xs text-subtle">Fehlerkennung: <span className="font-mono">{error.digest}</span></p>}
        <div className="mt-5 flex flex-wrap gap-2">
          <button type="button" className="btn btn-primary" onClick={() => reset()}>
            Ansicht neu aufbauen
          </button>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Neu laden
          </button>
        </div>
      </section>
    </main>
  );
}
