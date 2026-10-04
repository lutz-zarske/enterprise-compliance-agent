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
import { Scorecard } from "../components/Scorecard";
import { SettingsModal } from "../components/SettingsModal";
import { EmptyState, Skeleton, Spinner, Toaster, Tooltip, useToasts } from "../components/ui";
import { api, ApiError, fetchHealth, getApiBase } from "../lib/api";
import { cx, formatBytes, formatDate, formatModel, PROVIDER_NAMES } from "../lib/format";
import type {
  BatchUploadResponse,
  DocumentDetail,
  DocumentSummary,
  HealthResponse,
  KpiResponse,
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
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [extractingId, setExtractingId] = useState<string | null>(null);
  const [stages, setStages] = useState<ProgressStage[]>(DEFAULT_STAGES);
  const [tab, setTab] = useState<InspectorTab>("ustg");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const { toasts, push, dismiss } = useToasts();
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
    const [list, kpiData] = await Promise.all([api.documents(), api.kpis()]);
    setDocuments(list.items);
    setKpis(kpiData);
    return list.items;
  }, []);

  const loadAll = useCallback(async () => {
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
        notify("warn", "Zugang verweigert", "Backend verlangt einen X-API-Key – unter Einstellungen › Verbindung hinterlegen.");
      }
    }
  }, [refreshData, loadDetail, notify]);

  useEffect(() => {
    void loadAll();
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

  async function handleSeed() {
    setSeeding(true);
    try {
      // Die Musterdaten kommen bereits geprueft zurueck (Referenz-Audits) -
      // es ist keine Inferenz noetig, das Dashboard ist sofort vollstaendig.
      const result = await api.seed();
      await refreshData();
      const audited = result.items.filter((item) => item.reference_audit).length;
      notify(
        "ok",
        "Musterdaten geladen",
        audited
          ? `${audited} Referenz-Audits ohne KI-Modell erstellt. Mit laufendem Modell lassen sie sich über „Neu prüfen“ live berechnen.`
          : "Die Musterdokumente sind bereits vorhanden; bestehende Prüfergebnisse bleiben unverändert.",
      );
      const preferred =
        result.items.find((item) => item.filename.startsWith("Rechnung_Fehlerhaft")) ?? result.items[0];
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

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#inhalt" className="skip-link">Zum Inhalt springen</a>
      <Header
        health={health}
        offline={offline}
        apiBase={getApiBase()}
        settings={settings}
        seeding={seeding}
        onSeed={handleSeed}
        onRefresh={() => void loadAll()}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main id="inhalt" tabIndex={-1} className="mx-auto w-full max-w-[1440px] flex-1 space-y-4 px-4 py-5 outline-none sm:px-6">
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

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-4 xl:col-span-3">
            <DocumentUploader disabled={offline} onUploaded={handleUploaded} onError={(err) => reportError("Upload fehlgeschlagen", err)} />
            <DocumentList
              documents={documents}
              selectedId={selectedId}
              extractingId={extractingId}
              onSelect={setSelectedId}
              onTogglePin={handleTogglePin}
            />
          </div>

          <div className="min-w-0 space-y-4 lg:col-span-8 xl:col-span-9">
            {!detail && !loadingDetail && (
              <div className="card">
                <EmptyState icon={<ShieldCheck size={20} aria-hidden="true" />} title="Noch kein Dokument ausgewählt">
                  <p>
                    Mit den Musterdaten sehen Sie in Sekunden einen vollständigen Prüfdurchlauf – auch ohne KI-Modell:
                    eine gültige Rechnung, eine Steuerfalle und einen KI-Recruiting-Vertrag nach Anhang III.
                  </p>
                  <button className="btn btn-primary mt-3" onClick={handleSeed} disabled={offline || seeding}>
                    {seeding ? <Spinner size={13} /> : <Layers size={14} aria-hidden="true" />} Musterdaten laden
                  </button>
                  <p className="mt-3">Oder eigene PDFs links hochladen.</p>
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
                      </div>
                      <p className="truncate font-mono text-[11px] text-subtle" title={detail.sha256}>
                        SHA-256 {detail.sha256.slice(0, 16)}… · {detail.page_count ?? "?"} S. · {formatBytes(detail.size_bytes)}
                        {detail.extracted_at && ` · geprüft ${formatDate(detail.extracted_at, true)}`}
                        {detail.model && !isReference && ` · ${formatModel(detail.model)}`}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Tooltip
                      align="right"
                      content={
                        inferenceAvailable
                          ? undefined
                          : "Für eine Live-Analyse wird ein Sprachmodell benötigt – Ollama starten oder einen Cloud-Provider in den Einstellungen wählen."
                      }
                    >
                      <button
                        className={cx("btn", detail.status !== "extracted" && "btn-primary")}
                        onClick={() => void runExtraction(detail.id, detail.filename)}
                        disabled={!inferenceAvailable || extractingId !== null}
                      >
                        {isExtracting ? <Spinner size={13} /> : detail.status === "extracted" ? <RefreshCw size={14} aria-hidden="true" /> : <Zap size={14} aria-hidden="true" />}
                        {detail.status === "extracted" ? (isReference ? "Live neu prüfen" : "Neu prüfen") : "Audit starten"}
                      </button>
                    </Tooltip>
                    <button className="btn" onClick={() => setCopilotOpen(true)} disabled={offline}>
                      <MessageSquare size={14} aria-hidden="true" /> Copilot
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

                <DocumentInspector document={detail} tab={tab} onTabChange={setTab} />
              </>
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-line py-4 no-print">
        <div className="mx-auto flex max-w-[1440px] flex-col items-center justify-between gap-1 px-4 text-[11px] text-subtle sm:flex-row sm:px-6">
          <span>Enterprise Compliance Agent v{health?.version ?? "2.0.0"}</span>
          <span>VO (EU) 2024/1689 · § 14 UStG · DSGVO · GoBD-Hash-Kette</span>
          <span>{settings?.is_cloud ? "Cloud-Inferenz über Privacy Gateway" : "Lokale Inferenz · Zero Data Leakage"}</span>
        </div>
      </footer>

      <SettingsModal
        open={settingsOpen}
        settings={settings}
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
      <CopilotDrawer document={detail} open={copilotOpen} onClose={() => setCopilotOpen(false)} modelLabel={modelLabel} />
      <Toaster toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
