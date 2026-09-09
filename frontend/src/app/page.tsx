"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Header } from "../components/Header";
import { DocumentUploader } from "../components/DocumentUploader";
import { DocumentList } from "../components/DocumentList";
import { RiskCard } from "../components/RiskCard";
import { DocumentInspector } from "../components/DocumentInspector";
import { ExtractionCard } from "../components/ExtractionCard";
import { ExportModal } from "../components/ExportModal";
import {
  DocumentDetail,
  DocumentSummary,
  HealthResponse,
  UploadResponse,
} from "../types/api";
import {
  fetchHealth,
  fetchDocuments,
  fetchDocument,
  extractDocument,
} from "../lib/api";
import {
  ShieldAlert,
  ShieldCheck,
  Cpu,
  FileText,
  Download,
  Zap,
  RefreshCw,
  Lock,
} from "../components/icons";

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [isLoadingHealth, setIsLoadingHealth] = useState<boolean>(true);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null);
  const [isLoadingDoc, setIsLoadingDoc] = useState<boolean>(false);
  const [isExtractingId, setIsExtractingId] = useState<string | null>(null);

  const [isExportOpen, setIsExportOpen] = useState<boolean>(false);

  // Load backend health
  const loadHealth = useCallback(async () => {
    setIsLoadingHealth(true);
    try {
      const res = await fetchHealth();
      setHealth(res);
    } catch (err) {
      console.error("Health check error:", err);
    } finally {
      setIsLoadingHealth(false);
    }
  }, []);

  // Load documents list
  const loadDocuments = useCallback(async () => {
    try {
      const res = await fetchDocuments();
      setDocuments(res.items);
      // Auto-select first document if none selected
      if (!selectedDocId && res.items.length > 0) {
        setSelectedDocId(res.items[0].id);
      }
    } catch (err) {
      console.error("Error loading documents:", err);
    }
  }, [selectedDocId]);

  // Load details for selected document
  const loadDocumentDetail = useCallback(async (id: string) => {
    setIsLoadingDoc(true);
    try {
      const doc = await fetchDocument(id);
      setSelectedDocument(doc);
    } catch (err) {
      console.error("Error loading document detail:", err);
    } finally {
      setIsLoadingDoc(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadHealth();
    loadDocuments();
  }, [loadHealth, loadDocuments]);

  // When selectedDocId changes, load its details
  useEffect(() => {
    if (selectedDocId) {
      loadDocumentDetail(selectedDocId);
    }
  }, [selectedDocId, loadDocumentDetail]);

  // Handle successful upload
  const handleUploadSuccess = (upload: UploadResponse) => {
    const newSummary: DocumentSummary = {
      id: upload.id,
      filename: upload.filename,
      status: upload.status,
      size_bytes: upload.size_bytes,
      page_count: upload.page_count,
      doc_type: null,
      sender: null,
      document_date: null,
      total_amount: null,
      currency: null,
      ai_act_risk_level: null,
      gdpr_risk_level: null,
      contains_special_categories: null,
      created_at: upload.created_at,
      updated_at: upload.created_at,
    };

    setDocuments((prev) => [newSummary, ...prev]);
    setSelectedDocId(upload.id);
  };

  // Trigger extraction & compliance audit
  const handleTriggerExtract = async (id: string) => {
    setIsExtractingId(id);

    // Optimistically update document status
    setDocuments((prev) =>
      prev.map((d) => (d.id === id ? { ...d, status: "processing" } : d))
    );

    try {
      const res = await extractDocument(id);

      // Update in documents list
      setDocuments((prev) =>
        prev.map((d) =>
          d.id === id
            ? {
                ...d,
                status: "extracted",
                doc_type: res.extraction.doc_type,
                sender: res.extraction.sender,
                total_amount: res.extraction.total_amount,
                currency: res.extraction.currency,
                ai_act_risk_level: res.compliance.ai_act.overall_risk_level ?? null,
                gdpr_risk_level: res.compliance.gdpr.risk_level ?? null,
                contains_special_categories:
                  res.compliance.gdpr.contains_special_categories ?? null,
              }
            : d
        )
      );

      // If this was the selected document, reload its detail
      if (selectedDocId === id) {
        await loadDocumentDetail(id);
      }
    } catch (err) {
      console.error("Extraction failed:", err);
      setDocuments((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "failed" } : d))
      );
    } finally {
      setIsExtractingId(null);
    }
  };

  // Quick stats calculation
  const totalHighRiskCount = documents.filter(
    (d) => d.ai_act_risk_level === "high" || d.ai_act_risk_level === "unacceptable"
  ).length;

  const totalGdprSpecialCount = documents.filter(
    (d) => d.contains_special_categories === true
  ).length;

  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 flex flex-col selection:bg-cyan-500/30 selection:text-cyan-200">
      {/* Header */}
      <Header
        health={health}
        isLoadingHealth={isLoadingHealth}
        onRefresh={() => {
          loadHealth();
          loadDocuments();
          if (selectedDocId) loadDocumentDetail(selectedDocId);
        }}
      />

      {/* Main Container */}
      <main className="flex-1 mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 space-y-6">
        {/* Executive Compliance KPI Strip */}
        <section className="glass-panel rounded-2xl p-4 border border-slate-800/80 shadow-xl flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-cyan-500/20 to-emerald-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-md">
              <Cpu className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xs font-mono font-bold text-white uppercase tracking-wider">
                  INSTITUTIONAL REGULATORY GOVERNANCE RADAR
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-500/30">
                  VO (EU) 2024/1689
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Lokal gehostetes LLM ({health?.ollama?.model || "qwen2.5:14b-instruct"}) | Zero Cloud Data Exfiltration
              </p>
            </div>
          </div>

          {/* Quick Metrics */}
          <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
            <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-1.5 text-right">
              <span className="text-[10px] text-slate-500 block uppercase">Dokumente</span>
              <span className="font-bold text-slate-200">{documents.length} erfasst</span>
            </div>

            <div className="rounded-xl border border-red-500/30 bg-red-950/20 px-3 py-1.5 text-right">
              <span className="text-[10px] text-red-400 block uppercase">Hochrisiko AI Act</span>
              <span className="font-bold text-red-400">{totalHighRiskCount} Anhang-III</span>
            </div>

            <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 px-3 py-1.5 text-right">
              <span className="text-[10px] text-amber-400 block uppercase">DSGVO Art. 9/10</span>
              <span className="font-bold text-amber-400">{totalGdprSpecialCount} geschützt</span>
            </div>

            <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/20 px-3 py-1.5 text-right">
              <span className="text-[10px] text-emerald-400 block uppercase">Datenschutz</span>
              <span className="font-bold text-emerald-400 flex items-center space-x-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>100% Lokal</span>
              </span>
            </div>
          </div>
        </section>

        {/* 2-Column Responsive Workspace */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Upload & Document Inventory (4 of 12 cols) */}
          <div className="lg:col-span-4 space-y-6">
            <DocumentUploader onUploadSuccess={handleUploadSuccess} />
            <DocumentList
              documents={documents}
              selectedDocId={selectedDocId}
              onSelectDocument={(id) => setSelectedDocId(id)}
              onTriggerExtract={handleTriggerExtract}
              isExtractingId={isExtractingId}
            />
          </div>

          {/* Right Column: In-Depth Audit & Risk Classification (8 of 12 cols) */}
          <div className="lg:col-span-8 space-y-6">
            {/* Action Bar for Currently Selected Document */}
            {selectedDocument && (
              <div className="glass-panel rounded-2xl p-4 border border-slate-800/80 shadow-lg flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-cyan-400 border border-slate-700">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-bold text-white truncate max-w-sm sm:max-w-md">
                        {selectedDocument.filename}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-slate-800 text-slate-300 border border-slate-700">
                        {selectedDocument.status}
                      </span>
                    </div>
                    <p className="text-[11px] font-mono text-slate-400 truncate">
                      SHA256: {selectedDocument.sha256.slice(0, 20)}... | {selectedDocument.char_count || 0} Zeichen
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-2.5">
                  {selectedDocument.status === "uploaded" && (
                    <button
                      onClick={() => handleTriggerExtract(selectedDocument.id)}
                      disabled={isExtractingId === selectedDocument.id}
                      className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-gradient-to-r from-cyan-600 to-emerald-600 hover:from-cyan-500 hover:to-emerald-500 text-xs font-mono font-bold text-white shadow-md shadow-cyan-950/40 disabled:opacity-50"
                    >
                      {isExtractingId === selectedDocument.id ? (
                        <>
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                          <span>Audit läuft...</span>
                        </>
                      ) : (
                        <>
                          <Zap className="h-3.5 w-3.5" />
                          <span>Audit starten</span>
                        </>
                      )}
                    </button>
                  )}

                  {selectedDocument.status === "extracted" && (
                    <button
                      onClick={() => handleTriggerExtract(selectedDocument.id)}
                      disabled={isExtractingId === selectedDocument.id}
                      title="Audit erneut ausführen"
                      className="flex items-center space-x-1 px-2.5 py-1.5 rounded-xl border border-slate-800 bg-slate-900/80 text-xs font-mono text-slate-300 hover:bg-slate-800 hover:text-white"
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 ${isExtractingId === selectedDocument.id ? "animate-spin text-cyan-400" : ""}`}
                      />
                      <span className="hidden sm:inline">Neu prüfen</span>
                    </button>
                  )}

                  <button
                    onClick={() => setIsExportOpen(true)}
                    className="flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl border border-cyan-500/40 bg-cyan-950/40 hover:bg-cyan-900/50 text-xs font-mono font-bold text-cyan-300 shadow"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Audit-Export</span>
                  </button>
                </div>
              </div>
            )}

            {/* 1. EU AI Act Annex III Risk Classification Card */}
            <RiskCard
              assessment={selectedDocument?.compliance?.ai_act || null}
              isLoading={isLoadingDoc}
            />

            {/* 2. Live PII Redaction & Document Inspector */}
            <DocumentInspector document={selectedDocument} />

            {/* 3. Extraction Card (Invoice / Contract core facts) */}
            <ExtractionCard
              extraction={selectedDocument?.extraction || null}
              isLoading={isLoadingDoc}
            />
          </div>
        </div>
      </main>

      {/* Export Modal */}
      <ExportModal
        document={selectedDocument}
        isOpen={isExportOpen}
        onClose={() => setIsExportOpen(false)}
      />

      {/* Footer */}
      <footer className="mt-12 border-t border-slate-850 bg-[#070a11] py-4 text-center text-xs font-mono text-slate-500">
        <div className="mx-auto max-w-7xl px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>Enterprise AI Compliance & Audit Agent v1.0.0</span>
          <span>VO (EU) 2024/1689 & DSGVO (EU 2016/679) Revisionssicherheit</span>
          <span>Privacy-First Architecture • Local On-Premise Ollama</span>
        </div>
      </footer>
    </div>
  );
}
