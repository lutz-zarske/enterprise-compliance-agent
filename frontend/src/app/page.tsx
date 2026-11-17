"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AuditStepper } from "../components/AuditStepper";
import { CopilotView } from "../components/CopilotView";
import { DocumentInspector, type InspectorTab } from "../components/DocumentInspector";
import { DocumentList } from "../components/DocumentList";
import { DocumentUploader } from "../components/DocumentUploader";
import { ExportModal } from "../components/ExportModal";
import { Header, type View } from "../components/Header";
import { Download, FileText, Layers, RefreshCw, ShieldCheck, WifiOff, Zap } from "../components/icons";
import { NACHLAUF_MS, type FinishedJob } from "../components/JobMonitor";
import { KpiStrip } from "../components/KpiStrip";
import { markOnboardingDone, onboardingDone, ShortcutsModal, SpotlightTour, WelcomeModal } from "../components/Onboarding";
import { OverrideModal } from "../components/OverrideModal";
import { ProtocolView } from "../components/ProtocolView";
import { Scorecard } from "../components/Scorecard";
import { SettingsModal } from "../components/SettingsModal";
import { SealModal } from "../components/SignOffPanel";
import { meldeBereit } from "../components/SplashAbbau";
import { EmptyState, HashBadge, isModEnter, isTypingTarget, Skeleton, Spinner, Toaster, Tooltip, useToasts } from "../components/ui";
import { api, ApiError, fetchHealth, hasCachedApiBase } from "../lib/api";
import { cx, formatBytes, formatDate, formatModel, providerDisplayName, providerLabel } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useJobs } from "../lib/useJobs";
import type {
  BatchUploadResponse,
  DocumentDetail,
  DocumentSummary,
  HealthResponse,
  JobSnapshot,
  KpiResponse,
  LedgerVerification,
  RuntimeSettings,
  ScoreTile,
} from "../types/api";

const TILE_TO_TAB: Record<ScoreTile["key"], InspectorTab> = {
  formal: "ustg",
  regulatory: "aiact",
  privacy: "pii",
  math: "facts",
};

/** Tasten 1-5 der Reiter (5 = XML nur bei E-Rechnungen). */
const TAB_KEYS: InspectorTab[] = ["ustg", "aiact", "pii", "facts", "xml"];

const VIEW_STORAGE = "eca-view";

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown");
}

export default function DashboardPage() {
  const { tr, td } = useI18n();
  const statusLabels: Record<string, string> = {
    uploaded: tr("Ungeprüft", "Pending", "Pendiente"),
    processing: tr("In Prüfung", "Auditing", "En análisis"),
    extracted: tr("Geprüft", "Audited", "Analizado"),
    failed: tr("Fehlgeschlagen", "Failed", "Fallido"),
  };
  const viewLabels: Record<View, string> = {
    workspace: tr("Prüfung", "Audit", "Auditoría"),
    copilot: tr("Copilot", "Copilot", "Copiloto"),
    protocol: tr("Protokoll", "Audit Trail", "Registro"),
  };
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [offline, setOffline] = useState(false);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [kpis, setKpis] = useState<KpiResponse | null>(null);
  const [ledger, setLedger] = useState<LedgerVerification | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [view, setViewState] = useState<View>("workspace");
  const [tab, setTab] = useState<InspectorTab>("ustg");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [sealOpen, setSealOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [finished, setFinished] = useState<FinishedJob | null>(null);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const { toasts, push, dismiss, pause, resume } = useToasts();
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;

  const notify = useCallback(
    (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => push({ tone, title, message }),
    [push],
  );

  const reportError = useCallback(
    (title: string, err: unknown) => {
      const error = asApiError(err);
      if (error.isOffline) setOffline(true);
      notify("bad", title, `${error.message}${error.hint ? ` – ${error.hint}` : ""}`);
    },
    [notify],
  );

  const setView = useCallback((next: View) => {
    setViewState(next);
    try {
      window.localStorage.setItem(VIEW_STORAGE, next);
    } catch {
      /* privater Modus */
    }
  }, []);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(VIEW_STORAGE);
      if (stored === "workspace" || stored === "copilot" || stored === "protocol") setViewState(stored);
    } catch {
      /* privater Modus */
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    setLoadingDetail(true);
    try {
      const doc = await api.document(id);
      if (selectedRef.current === id) setDetail(doc);
    } catch (err) {
      if (asApiError(err).isOffline) setOffline(true);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const refreshData = useCallback(async () => {
    const [list, kpiData, chain] = await Promise.all([
      api.documents(),
      api.kpis(),
      api.verifyLedger().catch(() => null),
    ]);
    setDocuments(list.items);
    setKpis(kpiData);
    setLedger(chain);
    return list.items;
  }, []);

  const lastLoad = useRef(0);
  const loadAll = useCallback(async () => {
    lastLoad.current = Date.now();
    try {
      const discovered = hasCachedApiBase() ? null : await fetchHealth();
      const [h, items, runtime] = await Promise.all([
        discovered ? Promise.resolve(discovered) : fetchHealth(),
        refreshData(),
        api.settings(),
      ]);
      setHealth(h);
      setOffline(false);
      setSettings(runtime);
      if (!selectedRef.current && items.length) setSelectedId(items[0].id);
      if (selectedRef.current) await loadDetail(selectedRef.current);
    } catch (err) {
      const error = asApiError(err);
      if (error.isOffline) {
        setOffline(true);
        setHealth(null);
      } else if (error.status === 401) {
        notify(
          "warn",
          tr("Zugang verweigert", "Access denied", "Acceso denegado"),
          tr(
            "Das Backend verlangt einen X-API-Key – unter Einstellungen › System & Verbindung hinterlegen.",
            "Backend requires an X-API-Key – configure under Settings › System & Connection.",
            "El backend requiere un X-API-Key – configúrelo en Ajustes › Sistema y conexión.",
          ),
        );
      }
    }
  }, [refreshData, loadDetail, notify, tr]);

  // Erster Ladevorgang: Splash abbauen, Erstbesucher begruessen.
  useEffect(() => {
    void loadAll().finally(() => {
      meldeBereit();
      if (!onboardingDone()) setWelcomeOpen(true);
    });
  }, [loadAll]);

  // Reaktiv statt Aktualisieren-Button: Rueckkehr ins Fenster laedt den Stand neu (hoechstens alle 15 s).
  useEffect(() => {
    const onReturn = () => {
      if (window.document.visibilityState === "visible" && Date.now() - lastLoad.current > 15_000) void loadAll();
    };
    window.addEventListener("focus", onReturn);
    window.document.addEventListener("visibilitychange", onReturn);
    return () => {
      window.removeEventListener("focus", onReturn);
      window.document.removeEventListener("visibilitychange", onReturn);
    };
  }, [loadAll]);

  // Ruhige Wiederverbindung, solange das Backend offline ist.
  useEffect(() => {
    if (!offline) return;
    const timer = window.setInterval(() => void loadAll(), 10_000);
    return () => window.clearInterval(timer);
  }, [offline, loadAll]);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  // --- Hintergrund-Jobs ---------------------------------------------------------
  const onJobFinished = useCallback(
    (job: JobSnapshot) => {
      setFinished({ title: job.title, status: job.status, heuristic: Boolean(job.result?.heuristic), until: Date.now() + NACHLAUF_MS });
      if (job.status === "done" && job.result) {
        job.result.failover?.forEach((switched) =>
          notify(
            "warn",
            tr(`Ausweichstufe übernommen: ${formatModel(switched.to_model)}`, `Fallback activated: ${formatModel(switched.to_model)}`, `Nivel alternativo activado: ${formatModel(switched.to_model)}`),
            `${providerLabel(switched.from_provider)} → ${providerLabel(switched.to_provider)} (${
              switched.reason_code === "provider_timeout"
                ? tr("Zeitüberschreitung", "Timeout", "Tiempo agotado")
                : switched.reason_code === "cloud_budget_exceeded"
                  ? tr("Tagesbudget erreicht", "Daily budget reached", "Presupuesto diario alcanzado")
                  : tr("Überlast", "Overloaded", "Sobrecarga")
            }) · ${tr("im Ledger protokolliert", "recorded in ledger", "registrado en el historial")}`,
          ),
        );
        notify(
          job.result.heuristic ? "warn" : job.result.release_blocked ? "warn" : "ok",
          job.result.heuristic
            ? tr(`Regelbasiertes Referenz-Audit: ${job.title}`, `Rule-based reference audit: ${job.title}`, `Auditoría por reglas: ${job.title}`)
            : tr(`Prüfung abgeschlossen: ${job.title}`, `Audit completed: ${job.title}`, `Auditoría completada: ${job.title}`),
          `Score ${job.result.score ?? "–"}/100 · ${td(job.result.release_recommendation ?? "")}${
            job.result.heuristic
              ? tr(" · KI nicht verfügbar, Ergebnis gekennzeichnet", " · AI unavailable, badged as rules-only", " · IA no disponible, etiquetado")
              : ` · ${formatModel(job.result.model)}`
          }`,
        );
      } else if (job.status === "failed") {
        notify(
          "bad",
          tr(`Prüfung fehlgeschlagen: ${job.title}`, `Audit failed: ${job.title}`, `Auditoría fallida: ${job.title}`),
          `${job.error?.message ?? tr("Unbekannter Fehler", "Unknown error", "Error desconocido")}${job.error?.hint ? ` – ${job.error.hint}` : ""}`,
        );
      } else if (job.status === "cancelled") {
        notify(
          "info",
          tr(`Prüfung abgebrochen: ${job.title}`, `Audit cancelled: ${job.title}`, `Auditoría cancelada: ${job.title}`),
          tr("Der Beleg behält sein vorheriges Ergebnis.", "The document retains its previous result.", "El documento conserva su resultado anterior."),
        );
      }
      void refreshData().catch(() => undefined);
      if (selectedRef.current === job.document_id) void loadDetail(job.document_id);
    },
    [notify, refreshData, loadDetail, tr, td],
  );

  const { jobs, track, cancel } = useJobs(!offline && Boolean(health), onJobFinished);
  const analysingIds = new Set(jobs.map((job) => job.document_id));

  const runExtraction = useCallback(
    async (id: string) => {
      try {
        const job = await api.extract(id);
        track(job);
        setDocuments((all) => all.map((d) => (d.id === id ? { ...d, status: "processing" } : d)));
      } catch (err) {
        reportError(tr("Prüfung konnte nicht gestartet werden", "Could not start audit", "No se pudo iniciar la auditoría"), err);
      }
    },
    [track, reportError, tr],
  );

  const runBatch = useCallback(
    async (ids: string[]) => {
      try {
        const result = await api.submitJobs(ids);
        result.jobs.forEach(track);
        notify(
          "info",
          tr(`${result.jobs.length} Belege eingereiht`, `${result.jobs.length} documents queued`, `${result.jobs.length} documentos en cola`),
          tr(
            "Die Prüfungen laufen nacheinander im Hintergrund – Fortschritt im Job-Monitor oben rechts.",
            "Audits run sequentially in the background – monitor progress at top right.",
            "Las auditorías se ejecutan en segundo plano – progreso arriba a la derecha.",
          ),
        );
      } catch (err) {
        reportError(tr("Batch-Prüfung konnte nicht gestartet werden", "Could not start batch audit", "Error en auditoría por lotes"), err);
      }
    },
    [track, notify, reportError, tr],
  );

  async function handleSeed(file?: string) {
    setSeeding(true);
    try {
      // Die Musterdaten kommen bereits geprueft zurueck (Referenz-Audits) - ohne Inferenz.
      const result = await api.seed(file);
      await refreshData();
      const audited = result.items.filter((item) => item.reference_audit).length;
      const structured = result.items.filter((item) => item.structured_audit).length;
      notify(
        "ok",
        tr("Musterdaten geladen", "Sample cases loaded", "Casos de ejemplo cargados"),
        audited || structured
          ? [
              audited ? tr(`${audited} Referenz-Audits ohne KI-Modell erstellt`, `${audited} reference audits created offline`, `${audited} auditorías de referencia creadas sin IA`) : "",
              structured ? tr(`${structured} E-Rechnung deterministisch aus dem XML geprüft`, `${structured} E-Invoice audited deterministically from XML`, `${structured} factura electrónica analizada desde XML`) : "",
            ].filter(Boolean).join(", ") + "."
          : tr(
              "Die Musterdokumente sind bereits vorhanden; bestehende Prüfergebnisse bleiben unverändert.",
              "Sample documents already exist; existing audit results remain unchanged.",
              "Los documentos de ejemplo ya existen; los resultados previos no cambian.",
            ),
      );
      const preferred =
        (file ? result.items[0] : result.items.find((item) => item.filename.startsWith("Rechnung_Fehlerhaft"))) ?? result.items[0];
      if (preferred) setSelectedId(preferred.id);
      setView("workspace");
    } catch (err) {
      reportError(tr("Musterdaten konnten nicht geladen werden", "Failed to load sample cases", "Error al cargar ejemplos"), err);
    } finally {
      setSeeding(false);
    }
  }

  async function handleUploaded(result: BatchUploadResponse) {
    await refreshData().catch(() => undefined);
    const first = result.items.find((item) => item.ok && item.id);
    if (first?.id) setSelectedId(first.id);
    if (result.succeeded) {
      notify(
        "ok",
        tr(`${result.succeeded} Dokument(e) hochgeladen`, `${result.succeeded} document(s) uploaded`, `${result.succeeded} documento(s) subido(s)`),
        result.succeeded > 1
          ? tr("Über „prüfen“ in der Liste alle auf einmal einreihen.", "Use “audit” in the list to queue all at once.", "Usa «analizar» en la lista para encolar todos.")
          : tr("Prüfung über „Audit starten“ auslösen.", "Trigger review via “Start Audit”.", "Inicia la revisión con «Iniciar auditoría»."),
      );
    }
    result.items
      .filter((item) => !item.ok)
      .forEach((item) => notify("bad", `${tr("Upload abgelehnt:", "Upload rejected:", "Subida rechazada:")} ${item.filename}`, item.error?.message));
  }

  async function handleToggleArchive(doc: DocumentSummary) {
    try {
      await api.archive(doc.id, !doc.archived);
      await refreshData();
      notify(
        "info",
        doc.archived ? tr("Aus dem Archiv geholt", "Unarchived", "Desarchivado") : tr("Archiviert", "Archived", "Archivado"),
        `${doc.filename} · ${tr("nur ausgeblendet, nie gelöscht (GoBD) · im Ledger protokolliert", "hidden only, never deleted (GoBD) · logged in ledger", "solo oculto, nunca eliminado (GoBD) · registrado")}`,
      );
    } catch (err) {
      reportError(tr("Archivieren fehlgeschlagen", "Archive failed", "Error al archivar"), err);
    }
  }

  async function handleTogglePin(doc: DocumentSummary) {
    try {
      await api.pin(doc.id, !doc.pinned);
      await refreshData();
    } catch (err) {
      reportError(tr("Anpinnen fehlgeschlagen", "Pinning failed", "Error al fijar"), err);
    }
  }

  const online = !offline && Boolean(health);
  const cloudUnconfigured = online && Boolean(health?.inference?.is_cloud) && !health?.inference?.configured;
  const modelReady: boolean | null = !health
    ? null
    : health.inference?.mode === "local"
      ? health.ollama.status === "ok"
      : Boolean(health.inference?.configured);
  const modelLabel = settings ? `${providerDisplayName(settings.inference_mode)} · ${formatModel(settings.active_model)}` : "–";
  const activeJob = detail ? jobs.find((job) => job.document_id === detail.id) ?? null : null;
  const isReference = detail?.provider === "reference";
  const isHeuristic = detail?.provider === "heuristic";
  const structuredReady = Boolean(
    detail?.einvoice && !detail.einvoice.error && (detail.einvoice.source === "standalone" || detail.einvoice.is_einvoice),
  );
  // Seit v2.5 bricht keine Pruefung an fehlender KI ab: das Regelwerk schliesst gekennzeichnet ab.
  const canAnalyze = online && (!cloudUnconfigured || structuredReady);
  const isXml = detail?.content_type === "application/xml";
  const overlayOpen = settingsOpen || exportOpen || overrideOpen || sealOpen || welcomeOpen || tourOpen || shortcutsOpen;
  const canSeal = Boolean(detail?.scorecard) && online && !activeJob;

  // Strg/⌘ + Enter oeffnet den Siegel-Dialog; dort versiegelt ein zweites Strg/⌘ + Enter.
  useEffect(() => {
    if (overlayOpen || !canSeal || view !== "workspace") return;
    const onKey = (event: KeyboardEvent) => {
      if (!isModEnter(event)) return;
      event.preventDefault();
      setSealOpen(true);
    };
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [overlayOpen, canSeal, view]);

  // 1-5 wechseln den Reiter, ? oeffnet die Kuerzel-Uebersicht - nie beim Tippen, nie bei offenem Dialog.
  useEffect(() => {
    if (overlayOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return;
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen(true);
        return;
      }
      if (view !== "workspace") return;
      const target = TAB_KEYS[Number(event.key) - 1];
      if (!target || !detail || (target === "xml" && !detail.einvoice)) return;
      event.preventDefault();
      setTab(target);
    };
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [overlayOpen, detail, view]);

  // Den XML-Tab nicht stehen lassen, wenn das neue Dokument keinen Datensatz hat.
  useEffect(() => {
    if (tab === "xml" && detail && !detail.einvoice) setTab("ustg");
  }, [tab, detail]);

  const analyzeHint = !online
    ? tr("Ohne Backend-Verbindung keine Prüfung.", "Cannot audit without backend connection.", "Sin conexión al backend no se puede auditar.")
    : cloudUnconfigured && !structuredReady
      ? tr("Cloud-Modus ohne API-Key – Schlüssel in den Einstellungen hinterlegen.", "Cloud mode without API key – enter key in Settings.", "Modo nube sin clave API – añádela en Ajustes.")
      : structuredReady && modelReady === false
        ? tr("E-Rechnung: Die Prüfung läuft deterministisch über den XML-Datensatz und braucht kein Sprachmodell.", "E-Invoice: audit runs deterministically on the XML dataset without requiring an LLM.", "Factura electrónica: análisis determinista mediante XML sin necesidad de IA.")
        : modelReady === false
          ? tr("Kein Sprachmodell erreichbar – das Regelwerk prüft den Beleg und kennzeichnet das Ergebnis.", "No LLM reachable – ruleset evaluates the document and badges the result.", "Ningún modelo disponible – el motor de reglas evalúa y etiqueta el resultado.")
          : undefined;

  return (
    <>
      <div id="eca-app-shell" className="flex min-h-screen flex-col">
        <a href="#inhalt" className="skip-link">{tr("Zum Inhalt springen", "Skip to content", "Ir al contenido")}</a>
        <Header
          view={view}
          onViewChange={setView}
          health={health}
          offline={offline}
          settings={settings}
          ledger={ledger}
          ruleset={kpis?.ruleset_version ?? null}
          seeding={seeding}
          jobs={jobs}
          finished={finished}
          copilotBusy={copilotBusy}
          onCancelJob={cancel}
          onSeed={(file) => void handleSeed(file)}
          onOpenSettings={() => setSettingsOpen(true)}
          onStartTour={() => {
            setView("workspace");
            setWelcomeOpen(false);
            setTourOpen(true);
          }}
          onChanged={() => void loadAll()}
          notify={notify}
        />

        <main
          id="inhalt"
          tabIndex={-1}
          aria-label={viewLabels[view]}
          className="mx-auto w-full max-w-[1920px] flex-1 px-4 py-4 outline-none sm:px-6 2xl:max-w-[2400px] 2xl:px-10 2xl:py-5"
        >
          <h1 className="sr-only">Enterprise Compliance Agent – {viewLabels[view]}</h1>
          {offline && (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-warn-line bg-warn-soft px-4 py-3 text-sm text-fg" role="status">
              <WifiOff size={16} className="shrink-0 text-warn" aria-hidden="true" />
              <p className="min-w-0 flex-1">
                <strong className="text-warn">{tr("Backend nicht erreichbar.", "Backend unreachable.", "Backend no disponible.")}</strong>{" "}
                {tr("Start_Compliance_Agent.bat ausführen (oder uvicorn app.main:app --port 8001) – die Verbindung wird alle 10 s neu geprüft. Es werden keine Ersatzdaten angezeigt.", "Run Start_Compliance_Agent.bat (or uvicorn app.main:app --port 8001) – reconnecting every 10 s. No mock data is shown.", "Ejecuta Start_Compliance_Agent.bat (o uvicorn app.main:app --port 8001) – reintentando cada 10 s.")}
              </p>
              <button className="btn" onClick={() => void loadAll()}><RefreshCw size={14} aria-hidden="true" /> {tr("Erneut verbinden", "Reconnect", "Reconectar")}</button>
            </div>
          )}

          {/* Keep-Alive: alle Ansichten bleiben eingehaengt - ein Wechsel bricht keine Pruefung und kein Gespraech ab. */}
          <div hidden={view !== "workspace"} className="space-y-4 2xl:space-y-5">
            <KpiStrip kpis={kpis} loading={!health && !offline} />

            {/* Kompakte Queue (340 bzw. 400 px), der Rest gehoert der Workbench. */}
            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)] 2xl:grid-cols-[400px_minmax(0,1fr)] 2xl:gap-5">
              <div className="space-y-4">
                <DocumentUploader disabled={offline} onUploaded={handleUploaded} onError={(err) => reportError(tr("Upload fehlgeschlagen", "Upload failed", "Error al subir"), err)} />
                <DocumentList
                  documents={documents}
                  selectedId={selectedId}
                  analysingIds={analysingIds}
                  onAnalyzeAll={canAnalyze ? (ids) => void runBatch(ids) : undefined}
                  onSelect={setSelectedId}
                  onTogglePin={handleTogglePin}
                  onToggleArchive={handleToggleArchive}
                  shortcutsEnabled={!overlayOpen && view === "workspace"}
                />
              </div>

              <div className="min-w-0 space-y-4 2xl:space-y-5">
                {!detail && !loadingDetail && (
                  <div className="card">
                    <EmptyState icon={<ShieldCheck size={20} aria-hidden="true" />} title={tr("Noch kein Dokument ausgewählt", "No document selected yet", "Ningún documento seleccionado")}>
                      <p>
                        {tr(
                          "Mit den Musterdaten sehen Sie in Sekunden einen vollständigen Prüfdurchlauf – auch ohne KI-Modell: eine gültige Rechnung, eine Steuerfalle, einen KI-Recruiting-Vertrag nach Anhang III und eine hybride ZUGFeRD-E-Rechnung an eine Kommune.",
                          "With Sample Cases you see a complete audit cycle in seconds – even without an LLM: a valid invoice, a tax-trap invoice, an Annex III AI recruiting contract, and a hybrid ZUGFeRD E-Invoice to a public authority.",
                          "Con los casos de ejemplo verás una auditoría completa en segundos, incluso sin IA: factura válida, trampa fiscal, contrato de IA Anexo III y factura electrónica ZUGFeRD.",
                        )}
                      </p>
                      <button className="btn btn-primary mt-3" onClick={() => void handleSeed()} disabled={offline || seeding}>
                        {seeding ? <Spinner size={13} /> : <Layers size={14} aria-hidden="true" />} {tr("Musterdaten laden", "Load sample cases", "Cargar casos de ejemplo")}
                      </button>
                      <p className="mt-3">{tr("Oder eigene PDFs und XRechnungen links hochladen.", "Or upload your own PDFs and XRechnung files on the left.", "O sube tus propios PDF o XRechnung a la izquierda.")}</p>
                    </EmptyState>
                  </div>
                )}
                {!detail && loadingDetail && (
                  <div className="space-y-4" aria-busy="true" aria-label={tr("Dokument wird geladen", "Loading document", "Cargando documento")}>
                    <div className="card flex items-center gap-3 px-4 py-3"><Skeleton className="h-8 w-8" /><Skeleton className="h-4 w-64" /></div>
                    <div className="card flex gap-5 p-5"><Skeleton className="h-28 w-28 rounded-full" /><div className="flex-1 space-y-2"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-1/3" /></div></div>
                    <div className="card p-5"><Skeleton className="h-64 w-full" /></div>
                  </div>
                )}

                {detail && (
                  <>
                    <section className="card flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="rounded-lg border border-line bg-surface-2 p-2 text-subtle"><FileText size={16} aria-hidden="true" /></div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h2 className="truncate text-sm font-semibold text-fg">{detail.filename}</h2>
                            <span className={cx("chip", detail.status === "failed" ? "border-bad-line bg-bad-soft text-bad" : "border-line bg-surface-2 text-muted")}>
                              {activeJob ? statusLabels.processing : statusLabels[detail.status] ?? detail.status}
                            </span>
                            {isReference && (
                              <Tooltip
                                content={tr(
                                  "Musterdaten: Die KI-Antwort ist vorberechnet und gekennzeichnet. Score, Maskierung, Eskalationsregeln und Hash-Kette stammen aus dem regulären Regelwerk.",
                                  "Sample case: AI output is precomputed and badged. Score, PII masking, escalation rules and hash chain come from the regular ruleset.",
                                  "Caso de ejemplo: respuesta de IA precalculada. Puntuación, enmascaramiento y cadena de hash proceden del reglamento.",
                                )}
                              >
                                <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 text-muted">{tr("Referenz-Audit · ohne KI", "Reference audit · offline", "Auditoría de referencia · sin IA")}</span>
                              </Tooltip>
                            )}
                            {detail.provider === "structured" && (
                              <Tooltip
                                content={tr(
                                  "Die Rechnungsdaten stammen deterministisch aus dem EN-16931-Datensatz. Bei hybriden Rechnungen ist der XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36).",
                                  "Invoice data is parsed deterministically from EN 16931 XML. In hybrid invoices the XML dataset prevails (BMF 15 Oct 2024, para. 36).",
                                  "Datos extraídos de forma determinista del XML EN 16931. En facturas híbridas prevalece el XML.",
                                )}
                              >
                                <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 text-muted">{tr("XML-Prüfung · ohne KI", "XML audit · offline", "Auditoría XML · sin IA")}</span>
                              </Tooltip>
                            )}
                            {isHeuristic && (
                              <Tooltip
                                content={tr(
                                  `Regelbasiertes Referenz-Audit – KI nicht verfügbar. ${detail.compliance?.fallback_reason ?? ""} Felder per Mustererkennung, Einstufung konservativ; im Ledger gekennzeichnet. Mit erreichbarem Modell über „Neu prüfen“ wiederholen.`,
                                  `Rule-based audit – AI unavailable. ${detail.compliance?.fallback_reason ?? ""} Fields extracted deterministically, conservative classification; logged in ledger. Re-run once a model is reachable.`,
                                  `Auditoría por reglas – IA no disponible. ${detail.compliance?.fallback_reason ?? ""} Campos extraídos por reglas, clasificación conservadora.`,
                                )}
                              >
                                <span tabIndex={0} className="chip cursor-help border-warn-line bg-warn-soft text-warn">{tr("Regelwerk-Audit · KI überlastet", "Rules audit · AI overloaded", "Auditoría por reglas · IA saturada")}</span>
                              </Tooltip>
                            )}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-subtle">
                            <HashBadge value={detail.sha256} label="SHA-256" />
                            <span className="tabular-nums">
                              {isXml ? "XML" : `${detail.page_count ?? "?"} ${tr("S.", "p.", "pág.")}`} · {formatBytes(detail.size_bytes)}
                              {detail.extracted_at && ` · ${tr("geprüft", "audited", "auditado")} ${formatDate(detail.extracted_at, true)}`}
                              {detail.model && !isReference && ` · ${formatModel(detail.model)}`}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2" data-tour="actions-top">
                        <Tooltip align="right" content={analyzeHint}>
                          <button
                            className={cx("btn", detail.status !== "extracted" && "btn-primary")}
                            onClick={() => void runExtraction(detail.id)}
                            disabled={!canAnalyze || Boolean(activeJob)}
                          >
                            {activeJob ? <Spinner size={13} /> : detail.status === "extracted" ? <RefreshCw size={14} aria-hidden="true" /> : <Zap size={14} aria-hidden="true" />}
                            {detail.status === "extracted"
                              ? isReference
                                ? tr("Live neu prüfen", "Re-audit live", "Reauditar en vivo")
                                : tr("Neu prüfen", "Re-audit", "Reauditar")
                              : tr("Audit starten", "Start audit", "Iniciar auditoría")}
                          </button>
                        </Tooltip>
                        <button className="btn" onClick={() => setExportOpen(true)} disabled={offline}>
                          <Download size={14} aria-hidden="true" /> {tr("Export", "Export", "Exportar")}
                        </button>
                      </div>
                    </section>

                    {detail.status === "failed" && detail.error && !activeJob && (
                      <div className="rounded-lg border border-bad-line bg-bad-soft px-4 py-3 text-xs text-fg">
                        <strong className="text-bad">{tr("Letzte Prüfung fehlgeschlagen:", "Last audit failed:", "Última auditoría fallida:")}</strong> {detail.error}
                      </div>
                    )}

                    {activeJob && <AuditStepper job={activeJob} provider={modelLabel} onCancel={cancel} />}

                    {detail.scorecard && !activeJob && (
                      <Scorecard
                        scorecard={detail.scorecard}
                        sealed={Boolean(detail.sign_off)}
                        reference={isReference}
                        onOpenTile={(key) => setTab(TILE_TO_TAB[key])}
                      />
                    )}

                    <DocumentInspector
                      document={detail}
                      tab={tab}
                      onTabChange={setTab}
                      onOverride={detail.compliance && !offline ? () => setOverrideOpen(true) : undefined}
                      ledger={offline ? null : ledger}
                      onSeal={canSeal ? () => setSealOpen(true) : undefined}
                      onOpenProtocol={() => setView("protocol")}
                    />
                  </>
                )}
              </div>
            </div>
          </div>

          <div hidden={view !== "copilot"}>
            <CopilotView
              document={detail}
              documents={documents}
              onSelect={setSelectedId}
              modelLabel={modelLabel}
              modelReady={modelReady}
              active={view === "copilot"}
              onBusyChange={setCopilotBusy}
            />
          </div>

          <div hidden={view !== "protocol"}>
            <ProtocolView
              document={detail}
              documents={documents}
              ledger={offline ? null : ledger}
              rulesetVersion={kpis?.ruleset_version ?? null}
              dlpRuleset={settings?.dlp?.ruleset_version ?? null}
              active={view === "protocol"}
              onRefreshLedger={async () => {
                setLedger(await api.verifyLedger().catch(() => null));
              }}
              onOpenExport={() => setExportOpen(true)}
              notify={notify}
            />
          </div>
        </main>

        <footer className="border-t border-line py-4 no-print">
          <div className="mx-auto flex w-full max-w-[1920px] flex-col items-center justify-between gap-1 px-4 text-xs text-subtle sm:flex-row sm:px-6 2xl:max-w-[2400px] 2xl:px-10">
            <span>Enterprise Compliance Agent{health?.version ? <span className="tabular-nums"> · v{health.version}</span> : null}</span>
            <span>{tr("VO (EU) 2024/1689 · § 14 UStG · EN 16931 · DSGVO · GoBD", "Reg. (EU) 2024/1689 · Sec. 14 UStG · EN 16931 · GDPR · GoBD", "Reg. (UE) 2024/1689 · § 14 UStG · EN 16931 · RGPD · GoBD")}</span>
            <span>
              {settings?.is_cloud
                ? tr("Cloud-Inferenz über das Privacy Gateway", "Cloud inference via Privacy Gateway", "Inferencia en la nube vía Privacy Gateway")
                : tr("Lokale Inferenz · kein Dokumentinhalt verlässt den Rechner", "Local inference · no document content leaves your machine", "Inferencia local · ningún contenido sale del equipo")}
            </span>
          </div>
        </footer>
      </div>

      <SettingsModal
        open={settingsOpen}
        settings={settings}
        health={health}
        version={health?.version ?? ""}
        onClose={() => setSettingsOpen(false)}
        onSaved={(updated) => {
          setSettings(updated);
          void fetchHealth().then(setHealth).catch(() => undefined);
        }}
        onAccessChanged={() => void loadAll()}
        notify={notify}
      />
      <ExportModal
        document={detail}
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        onSealed={(updated) => {
          setDetail(updated);
          void refreshData().catch(() => undefined);
        }}
        notify={notify}
      />
      <OverrideModal
        document={detail}
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        onDone={(updated) => {
          setDetail(updated);
          void refreshData().catch(() => undefined);
        }}
        notify={notify}
      />
      <SealModal
        document={detail}
        open={sealOpen}
        onClose={() => setSealOpen(false)}
        onSealed={(updated) => {
          setDetail(updated);
          void refreshData().catch(() => undefined);
        }}
        notify={notify}
      />
      <WelcomeModal
        open={welcomeOpen}
        onStartTour={() => {
          setWelcomeOpen(false);
          setTourOpen(true);
        }}
        onSkip={() => {
          markOnboardingDone();
          setWelcomeOpen(false);
        }}
      />
      <SpotlightTour open={tourOpen} onClose={() => setTourOpen(false)} />
      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <Toaster toasts={toasts} onDismiss={dismiss} onPause={pause} onResume={resume} />
    </>
  );
}
