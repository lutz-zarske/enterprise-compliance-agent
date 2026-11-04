"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AuditStepper, DEFAULT_STAGES } from "../components/AuditStepper";
import { CopilotDrawer } from "../components/CopilotDrawer";
import { DocumentInspector, type InspectorTab } from "../components/DocumentInspector";
import { DocumentList } from "../components/DocumentList";
import { DocumentUploader } from "../components/DocumentUploader";
import { ExportModal } from "../components/ExportModal";
import { Header } from "../components/Header";
import {
  AlertTriangle,
  Download,
  FileText,
  Layers,
  MessageSquare,
  RefreshCw,
  Settings,
  ShieldCheck,
  Terminal,
  WifiOff,
  Zap,
} from "../components/icons";
import { KpiStrip } from "../components/KpiStrip";
import { markOnboardingDone, onboardingDone, ShortcutsModal, SpotlightTour, WelcomeModal } from "../components/Onboarding";
import { OverrideModal } from "../components/OverrideModal";
import { Scorecard } from "../components/Scorecard";
import { SettingsModal } from "../components/SettingsModal";
import { SealModal } from "../components/SignOffPanel";
import { meldeBereit } from "../components/SplashAbbau";
import { EmptyState, HashBadge, isModEnter, isTypingTarget, Skeleton, Spinner, Toaster, Tooltip, useToasts } from "../components/ui";
import { api, ApiError, fetchHealth, getApiBase } from "../lib/api";
import { cx, formatBytes, formatDate, formatModel, PROVIDER_NAMES } from "../lib/format";
import type {
  BatchUploadResponse,
  DocumentDetail,
  DocumentSummary,
  HealthResponse,
  InferenceMode,
  KpiResponse,
  LedgerVerification,
  ProgressStage,
  RuntimeSettings,
  ScoreTile,
} from "../types/api";

const TILE_TO_TAB: Record<ScoreTile["key"], InspectorTab> = {
  formal: "ustg",
  regulatory: "aiact",
  privacy: "pii",
  math: "facts",
};

/** Tasten 1-6 der Reiter (5 = XML nur bei E-Rechnungen). */
const TAB_KEYS: InspectorTab[] = ["ustg", "aiact", "pii", "facts", "xml", "ledger"];

const STATUS_LABELS: Record<string, string> = {
  uploaded: "Hochgeladen",
  processing: "In Prüfung",
  extracted: "Geprüft",
  failed: "Fehlgeschlagen",
};

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown");
}

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [offline, setOffline] = useState(false);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [kpis, setKpis] = useState<KpiResponse | null>(null);
  const [ledger, setLedger] = useState<LedgerVerification | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [extractingId, setExtractingId] = useState<string | null>(null);
  const [stages, setStages] = useState<ProgressStage[]>(DEFAULT_STAGES);
  const [tab, setTab] = useState<InspectorTab>("ustg");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [sealOpen, setSealOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
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
      const h = await fetchHealth();
      setHealth(h);
      setOffline(false);
      const [items, runtime] = await Promise.all([refreshData(), api.settings()]);
      setSettings(runtime);
      if (!selectedRef.current && items.length) setSelectedId(items[0].id);
      if (selectedRef.current) await loadDetail(selectedRef.current);
    } catch (err) {
      const error = asApiError(err);
      if (error.isOffline) {
        setOffline(true);
        setHealth(null);
      } else if (error.status === 401) {
        notify("warn", "Zugang verweigert", "Backend verlangt einen X-API-Key – unter Einstellungen › System & Verbindung hinterlegen.");
      }
    }
  }, [refreshData, loadDetail, notify]);

  // Erster Ladevorgang: Splash abbauen, Erstbesucher begruessen.
  useEffect(() => {
    void loadAll().finally(() => {
      meldeBereit();
      if (!onboardingDone()) setWelcomeOpen(true);
    });
  }, [loadAll]);

  // Reaktiv statt Aktualisieren-Button: Rueckkehr ins Fenster laedt den Stand neu
  // (z. B. nach einem Upload aus einem zweiten Tab), hoechstens alle 15 s.
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

  const runExtraction = useCallback(
    async (id: string, filename: string): Promise<boolean> => {
      setExtractingId(id);
      setStages(DEFAULT_STAGES);
      setDocuments((all) => all.map((d) => (d.id === id ? { ...d, status: "processing" } : d)));
      const poll = window.setInterval(async () => {
        try {
          const progress = await api.progress(id);
          if (progress.current_stage) setStages(progress.stages);
        } catch {
          /* Fortschritt ist optional */
        }
      }, 500);
      let ok = false;
      try {
        const result = await api.extract(id);
        ok = true;
        result.compliance.failover?.forEach((switched) =>
          notify(
            "warn",
            `Fallback auf Modell ${formatModel(switched.to_model)} ausgelöst: ${switched.reason_code === "provider_timeout" ? "Zeitüberschreitung" : "Anbieter nicht verfügbar"}`,
            `${PROVIDER_NAMES[switched.from_provider as InferenceMode] ?? switched.from_provider} → ${PROVIDER_NAMES[switched.to_provider as InferenceMode] ?? switched.to_provider} · im Ledger protokolliert`,
          ),
        );
        notify(
          result.scorecard?.release_blocked ? "warn" : "ok",
          `Audit abgeschlossen: ${filename}`,
          `Score ${result.scorecard?.score ?? "–"}/100 · ${result.scorecard?.release_recommendation ?? ""} · ${formatModel(result.model)}`,
        );
      } catch (err) {
        reportError(`Analyse fehlgeschlagen: ${filename}`, err);
      } finally {
        window.clearInterval(poll);
        setExtractingId(null);
        try {
          await refreshData();
        } catch {
          /* Offline-Zustand wird separat erkannt */
        }
        if (selectedRef.current === id) await loadDetail(id);
      }
      return ok;
    },
    [notify, reportError, refreshData, loadDetail],
  );

  async function handleSeed(file?: string) {
    setSeeding(true);
    try {
      // Die Musterdaten kommen bereits geprueft zurueck (Referenz-Audits) -
      // es ist keine Inferenz noetig, das Dashboard ist sofort vollstaendig.
      const result = await api.seed(file);
      await refreshData();
      const audited = result.items.filter((item) => item.reference_audit).length;
      const structured = result.items.filter((item) => item.structured_audit).length;
      notify(
        "ok",
        "Musterdaten geladen",
        audited || structured
          ? [
              audited ? `${audited} Referenz-Audits ohne KI-Modell erstellt` : "",
              structured ? `${structured} E-Rechnung deterministisch aus dem XML geprüft` : "",
            ].filter(Boolean).join(", ") + ". Mit laufendem Modell lassen sich die Referenz-Audits über „Live neu prüfen“ berechnen."
          : "Die Musterdokumente sind bereits vorhanden; bestehende Prüfergebnisse bleiben unverändert.",
      );
      const preferred =
        (file ? result.items[0] : result.items.find((item) => item.filename.startsWith("Rechnung_Fehlerhaft"))) ?? result.items[0];
      if (preferred) setSelectedId(preferred.id);
    } catch (err) {
      reportError("Musterdaten konnten nicht geladen werden", err);
    } finally {
      setSeeding(false);
    }
  }

  async function copyOllamaCommand() {
    try {
      await navigator.clipboard.writeText("ollama serve");
      notify("info", "Befehl kopiert", "„ollama serve“ im Terminal ausführen; das Dashboard erkennt das Modell beim nächsten Aktualisieren.");
    } catch {
      notify("info", "Im Terminal ausführen: ollama serve", "Die Zwischenablage ist in diesem Browser nicht verfügbar.");
    }
  }

  async function handleUploaded(result: BatchUploadResponse) {
    await refreshData().catch(() => undefined);
    const first = result.items.find((item) => item.ok && item.id);
    if (first?.id) setSelectedId(first.id);
    if (result.succeeded) notify("ok", `${result.succeeded} Dokument(e) hochgeladen`, "Audit über „Audit starten“ auslösen.");
    result.items
      .filter((item) => !item.ok)
      .forEach((item) => notify("bad", `Upload abgelehnt: ${item.filename}`, item.error?.message));
  }

  async function handleToggleArchive(doc: DocumentSummary) {
    try {
      await api.archive(doc.id, !doc.archived);
      await refreshData();
      notify("info", doc.archived ? "Aus dem Archiv geholt" : "Archiviert", `${doc.filename} · nur ausgeblendet, nie gelöscht (GoBD) · im Ledger protokolliert`);
    } catch (err) {
      reportError("Archivieren fehlgeschlagen", err);
    }
  }

  async function handleTogglePin(doc: DocumentSummary) {
    try {
      await api.pin(doc.id, !doc.pinned);
      await refreshData();
    } catch (err) {
      reportError("Anpinnen fehlgeschlagen", err);
    }
  }

  const ollamaDown = !offline && health?.inference?.mode === "local" && health.ollama.status !== "ok";
  const cloudUnconfigured = !offline && health?.inference?.is_cloud && !health.inference.configured;
  const modelLabel = settings ? `${PROVIDER_NAMES[settings.inference_mode]} · ${formatModel(settings.active_model)}` : "–";
  const isExtracting = detail !== null && extractingId === detail.id;
  const inferenceAvailable = !offline && !ollamaDown && !cloudUnconfigured;
  const isReference = detail?.provider === "reference";
  // E-Rechnungen mit auswertbarem XML laufen deterministisch - ohne Sprachmodell.
  const structuredReady = Boolean(
    detail?.einvoice && !detail.einvoice.error && (detail.einvoice.source === "standalone" || detail.einvoice.is_einvoice),
  );
  const canAnalyze = !offline && (inferenceAvailable || structuredReady);
  const isXml = detail?.content_type === "application/xml";
  const overlayOpen =
    settingsOpen || exportOpen || overrideOpen || copilotOpen || sealOpen || welcomeOpen || tourOpen || shortcutsOpen;
  const canSeal = Boolean(detail?.scorecard) && !offline && extractingId === null;

  // Strg/⌘ + Enter oeffnet den Siegel-Dialog; dort versiegelt ein zweites Strg/⌘ + Enter.
  useEffect(() => {
    if (overlayOpen || !canSeal) return;
    const onKey = (event: KeyboardEvent) => {
      if (!isModEnter(event)) return;
      event.preventDefault();
      setSealOpen(true);
    };
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [overlayOpen, canSeal]);

  // 1-6 wechseln den Reiter, ? oeffnet die Kuerzel-Uebersicht - nie beim Tippen, nie bei offenem Dialog.
  useEffect(() => {
    if (overlayOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return;
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen(true);
        return;
      }
      const target = TAB_KEYS[Number(event.key) - 1];
      if (!target || !detail || (target === "xml" && !detail.einvoice)) return;
      event.preventDefault();
      setTab(target);
    };
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [overlayOpen, detail]);

  // Den XML-Tab nicht stehen lassen, wenn das neue Dokument keinen Datensatz hat.
  useEffect(() => {
    if (tab === "xml" && detail && !detail.einvoice) setTab("ustg");
  }, [tab, detail]);

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#inhalt" className="skip-link">Zum Inhalt springen</a>
      <Header
        health={health}
        offline={offline}
        settings={settings}
        ledger={ledger}
        seeding={seeding}
        busy={extractingId !== null}
        onSeed={(file) => void handleSeed(file)}
        onOpenSettings={() => setSettingsOpen(true)}
        onStartTour={() => {
          setWelcomeOpen(false);
          setTourOpen(true);
        }}
        notify={notify}
      />

      <main
        id="inhalt"
        tabIndex={-1}
        className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-4 py-5 outline-none sm:px-6 2xl:max-w-[2400px] 2xl:space-y-5 2xl:px-10"
      >
        {offline && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warn-line bg-warn-soft px-4 py-3 text-sm text-warn" role="status">
            <WifiOff size={16} className="shrink-0" aria-hidden="true" />
            <p className="min-w-0 flex-1">
              <strong>Backend nicht erreichbar</strong> ({getApiBase()}). Starten mit{" "}
              <code className="rounded bg-surface-solid px-1 font-mono text-xs text-fg">uvicorn app.main:app --port 8001</code> – die
              Verbindung wird alle 10 s automatisch neu geprüft. Es werden keine Ersatzdaten angezeigt.
            </p>
            <button className="btn" onClick={() => void loadAll()}><RefreshCw size={14} aria-hidden="true" /> Erneut verbinden</button>
          </div>
        )}
        {(ollamaDown || cloudUnconfigured) && (
          <div className="rounded-lg border border-warn-line bg-warn-soft px-4 py-3" role="status">
            <div className="flex flex-wrap items-start gap-3">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
              <div className="min-w-0 flex-1 text-sm text-fg">
                <p>
                  <strong className="text-warn">
                    {ollamaDown ? "Kein lokales Sprachmodell erreichbar." : "Cloud-Modus ohne API-Key."}
                  </strong>{" "}
                  Musterdaten, Prüfergebnisse, Zertifikate und Siegel funktionieren weiter. Für neue Analysen
                  {ollamaDown ? " Ollama starten oder" : ""} einen Cloud-Provider in den Einstellungen wählen.
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  Datenschutz: Die Pseudonymisierung (Art. 4 Nr. 5 DSGVO) läuft lokal im Backend (Privacy Vault, Python),
                  bevor Daten den Server verlassen. Cloud-Modelle erhalten erkannte Identifikatoren – Namen mit Anrede oder Rolle,
                  Firmen, IBAN, Steuer-IDs, Kontaktdaten, Adressen, Beträge – nur als Platzhalter; dafür ist kein lokales Ollama nötig.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn" onClick={() => setSettingsOpen(true)}>
                  <Settings size={14} aria-hidden="true" /> Inferenz-Einstellungen
                </button>
                {ollamaDown && (
                  <button className="btn" onClick={() => void copyOllamaCommand()} title="Kopiert den Befehl „ollama serve“">
                    <Terminal size={14} aria-hidden="true" /> Lokale KI starten
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        <KpiStrip kpis={kpis} loading={!health && !offline} />

        {/* Kompakte Queue (340 bzw. 400 px), der Rest gehoert der Workbench. */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)] 2xl:grid-cols-[400px_minmax(0,1fr)] 2xl:gap-5">
          <div className="space-y-4">
            <DocumentUploader disabled={offline} onUploaded={handleUploaded} onError={(err) => reportError("Upload fehlgeschlagen", err)} />
            <DocumentList
              documents={documents}
              selectedId={selectedId}
              extractingId={extractingId}
              onSelect={setSelectedId}
              onTogglePin={handleTogglePin}
              onToggleArchive={handleToggleArchive}
              shortcutsEnabled={!overlayOpen}
            />
          </div>

          <div className="min-w-0 space-y-4 2xl:space-y-5">
            {!detail && !loadingDetail && (
              <div className="card">
                <EmptyState icon={<ShieldCheck size={20} aria-hidden="true" />} title="Noch kein Dokument ausgewählt">
                  <p>
                    Mit den Musterdaten sehen Sie in Sekunden einen vollständigen Prüfdurchlauf – auch ohne KI-Modell:
                    eine gültige Rechnung, eine Steuerfalle, einen KI-Recruiting-Vertrag nach Anhang III und eine hybride
                    ZUGFeRD-E-Rechnung an eine Kommune.
                  </p>
                  <button className="btn btn-primary mt-3" onClick={() => void handleSeed()} disabled={offline || seeding}>
                    {seeding ? <Spinner size={13} /> : <Layers size={14} aria-hidden="true" />} Musterdaten laden
                  </button>
                  <p className="mt-3">Oder eigene PDFs und XRechnungen links hochladen.</p>
                </EmptyState>
              </div>
            )}
            {!detail && loadingDetail && (
              <div className="space-y-4" aria-busy="true" aria-label="Dokument wird geladen">
                <div className="card flex items-center gap-3 px-4 py-3"><Skeleton className="h-8 w-8" /><Skeleton className="h-4 w-64" /></div>
                <div className="card flex gap-5 p-5"><Skeleton className="h-28 w-28 rounded-full" /><div className="flex-1 space-y-2"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-1/3" /></div></div>
                <div className="card p-5"><Skeleton className="h-64 w-full" /></div>
              </div>
            )}

            {detail && (
              <>
                <section className="card flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="rounded-lg border border-line bg-surface-2 p-2 text-accent"><FileText size={16} aria-hidden="true" /></div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="truncate text-sm font-semibold text-fg">{detail.filename}</h2>
                        <span className={cx("chip", detail.status === "failed" ? "border-bad-line bg-bad-soft text-bad" : "border-line bg-surface-2 text-muted")}>
                          {STATUS_LABELS[detail.status] ?? detail.status}
                        </span>
                        {isReference && (
                          <Tooltip content="Musterdaten: Die KI-Antwort ist vorberechnet und gekennzeichnet. Score, Maskierung, Eskalationsregeln und Hash-Kette stammen aus dem regulären Regelwerk.">
                            <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 text-muted">Referenz-Audit · ohne KI</span>
                          </Tooltip>
                        )}
                        {detail.provider === "structured" && (
                          <Tooltip content="Die Rechnungsdaten stammen deterministisch aus dem EN-16931-Datensatz. Bei hybriden Rechnungen ist der XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36).">
                            <span tabIndex={0} className="chip cursor-help border-line bg-surface-2 text-muted">XML-Prüfung · ohne KI</span>
                          </Tooltip>
                        )}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-subtle">
                        <HashBadge value={detail.sha256} label="SHA-256" />
                        <span className="font-mono tabular-nums">
                          {isXml ? "XML" : `${detail.page_count ?? "?"} S.`} · {formatBytes(detail.size_bytes)}
                          {detail.extracted_at && ` · geprüft ${formatDate(detail.extracted_at, true)}`}
                          {detail.model && !isReference && ` · ${formatModel(detail.model)}`}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Tooltip
                      align="right"
                      content={
                        canAnalyze
                          ? structuredReady && !inferenceAvailable
                            ? "E-Rechnung: Die Prüfung läuft deterministisch über den XML-Datensatz und braucht kein Sprachmodell."
                            : undefined
                          : "Für eine Live-Analyse wird ein Sprachmodell benötigt – Ollama starten oder einen Cloud-Provider in den Einstellungen wählen."
                      }
                    >
                      <button
                        className={cx("btn", detail.status !== "extracted" && "btn-primary")}
                        onClick={() => void runExtraction(detail.id, detail.filename)}
                        disabled={!canAnalyze || extractingId !== null}
                      >
                        {isExtracting ? <Spinner size={13} /> : detail.status === "extracted" ? <RefreshCw size={14} aria-hidden="true" /> : <Zap size={14} aria-hidden="true" />}
                        {detail.status === "extracted" ? (isReference ? "Live neu prüfen" : "Neu prüfen") : "Audit starten"}
                      </button>
                    </Tooltip>
                    <button className="btn" onClick={() => setCopilotOpen(true)} disabled={offline}>
                      <MessageSquare size={14} aria-hidden="true" /> Compliance-Copilot
                    </button>
                    <button className="btn" onClick={() => setExportOpen(true)} disabled={offline}>
                      <Download size={14} aria-hidden="true" /> Prüfbericht exportieren
                    </button>
                  </div>
                </section>

                {detail.status === "failed" && detail.error && !isExtracting && (
                  <div className="rounded-lg border border-bad-line bg-bad-soft px-4 py-3 text-xs text-bad">
                    <strong>Letzte Analyse fehlgeschlagen:</strong> {detail.error}
                  </div>
                )}

                {isExtracting && (
                  <AuditStepper stages={stages} filename={detail.filename} provider={modelLabel} />
                )}

                {detail.scorecard && !isExtracting && (
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
                />
              </>
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-line py-4 no-print">
        <div className="mx-auto flex w-full max-w-[1920px] flex-col items-center justify-between gap-1 px-4 text-xs text-subtle sm:flex-row sm:px-6 2xl:max-w-[2400px] 2xl:px-10">
          <span>Enterprise Compliance Agent <span className="font-mono tabular-nums">v{health?.version ?? "2.4.0"}</span></span>
          <span>VO (EU) 2024/1689 · § 14 UStG · DSGVO · GoBD-Hash-Kette</span>
          <span>{settings?.is_cloud ? "Cloud-Inferenz über Privacy Gateway" : "Lokale Inferenz · Zero Data Leakage"}</span>
        </div>
      </footer>

      <SettingsModal
        open={settingsOpen}
        settings={settings}
        version={health?.version ?? "2.4.0"}
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
      <CopilotDrawer document={detail} open={copilotOpen} onClose={() => setCopilotOpen(false)} modelLabel={modelLabel} />
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
    </div>
  );
}
