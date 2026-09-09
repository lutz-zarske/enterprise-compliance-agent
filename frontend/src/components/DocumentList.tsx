"use client";

import React, { useState } from "react";
import { DocumentSummary, DocumentStatus, AIActRiskLevel } from "../types/api";
import { FileText, Search, Filter, RefreshCw, Zap, ShieldAlert, ShieldCheck, Clock } from "./icons";

interface DocumentListProps {
  documents: DocumentSummary[];
  selectedDocId: string | null;
  onSelectDocument: (id: string) => void;
  onTriggerExtract: (id: string) => void;
  isExtractingId: string | null;
}

export const DocumentList: React.FC<DocumentListProps> = ({
  documents,
  selectedDocId,
  onSelectDocument,
  onTriggerExtract,
  isExtractingId,
}) => {
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch =
      doc.filename.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (doc.sender && doc.sender.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchesStatus = statusFilter === "all" || doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: DocumentStatus) => {
    switch (status) {
      case "extracted":
        return (
          <span className="inline-flex items-center rounded-md border border-emerald-500/40 bg-emerald-950/40 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase text-emerald-300">
            COMPLETED
          </span>
        );
      case "processing":
        return (
          <span className="inline-flex items-center space-x-1 rounded-md border border-cyan-500/40 bg-cyan-950/40 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase text-cyan-300 animate-pulse">
            <RefreshCw className="h-2.5 w-2.5 animate-spin" />
            <span>EXTRACTING</span>
          </span>
        );
      case "uploaded":
        return (
          <span className="inline-flex items-center rounded-md border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase text-amber-300">
            UPLOADED
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center rounded-md border border-red-500/40 bg-red-950/40 px-2 py-0.5 text-[10px] font-mono font-semibold uppercase text-red-300">
            FAILED
          </span>
        );
    }
  };

  const getRiskBadge = (level: AIActRiskLevel | null | undefined) => {
    if (!level) return null;
    if (level === "high" || level === "unacceptable") {
      return (
        <span className="inline-flex items-center space-x-1 rounded border border-red-500/40 bg-red-950/50 px-1.5 py-0.5 text-[10px] font-mono font-bold text-red-400">
          <ShieldAlert className="h-3 w-3" />
          <span>HIGH RISK</span>
        </span>
      );
    }
    if (level === "limited") {
      return (
        <span className="inline-flex items-center rounded border border-amber-500/40 bg-amber-950/50 px-1.5 py-0.5 text-[10px] font-mono font-medium text-amber-400">
          LIMITED
        </span>
      );
    }
    return (
      <span className="inline-flex items-center space-x-1 rounded border border-emerald-500/30 bg-emerald-950/40 px-1.5 py-0.5 text-[10px] font-mono font-medium text-emerald-400">
        <ShieldCheck className="h-3 w-3" />
        <span>MINIMAL</span>
      </span>
    );
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800/80 shadow-xl flex flex-col h-full">
      {/* Header with Title & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase font-mono">
              Dokumenten-Audit-Bestand
            </h2>
            <span className="px-2 py-0.5 rounded-full text-xs font-mono bg-slate-800 text-slate-300 border border-slate-700">
              {filteredDocs.length} / {documents.length}
            </span>
          </div>
          <p className="text-xs text-slate-400">
            Audit-Verlauf, Risikoprofile und Rohdaten-Status
          </p>
        </div>

        {/* Search & Filter Inputs */}
        <div className="flex items-center space-x-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-48">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Suchen..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-lg border border-slate-850 bg-slate-950/80 pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-850 bg-slate-950/80 px-2.5 py-1.5 text-xs text-slate-300 focus:border-cyan-500 focus:outline-none font-mono"
          >
            <option value="all">Alle Status</option>
            <option value="extracted">Extrahierte</option>
            <option value="uploaded">Uploaded</option>
            <option value="failed">Fehler</option>
          </select>
        </div>
      </div>

      {/* Document Items List */}
      <div className="space-y-2.5 flex-1 overflow-y-auto max-h-[460px] pr-1">
        {filteredDocs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500 border border-dashed border-slate-800 rounded-xl">
            <FileText className="h-8 w-8 mb-2 opacity-40" />
            <p className="text-xs">Keine Dokumente gefunden.</p>
          </div>
        ) : (
          filteredDocs.map((doc) => {
            const isSelected = selectedDocId === doc.id;
            const isCurrentlyExtracting = isExtractingId === doc.id;

            return (
              <div
                key={doc.id}
                onClick={() => onSelectDocument(doc.id)}
                className={`group relative flex flex-col rounded-xl border p-3.5 transition-all cursor-pointer ${
                  isSelected
                    ? "border-cyan-500/60 bg-slate-900/90 shadow-[0_0_20px_rgba(6,182,212,0.15)] ring-1 ring-cyan-500/30"
                    : "border-slate-800/80 bg-slate-950/50 hover:border-slate-700 hover:bg-slate-900/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start space-x-2.5 min-w-0">
                    <div
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                        isSelected
                          ? "border-cyan-500/40 bg-cyan-950/40 text-cyan-400"
                          : "border-slate-800 bg-slate-900 text-slate-400 group-hover:text-slate-200"
                      }`}
                    >
                      <FileText className="h-4 w-4" />
                    </div>

                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-100 truncate group-hover:text-cyan-300 transition-colors">
                        {doc.filename}
                      </p>
                      <p className="text-[11px] text-slate-400 truncate">
                        {doc.sender || "Absender unbestimmt"}
                      </p>
                    </div>
                  </div>

                  {/* Status & Risk Badges */}
                  <div className="flex flex-col items-end space-y-1 shrink-0">
                    {getStatusBadge(doc.status)}
                    {getRiskBadge(doc.ai_act_risk_level)}
                  </div>
                </div>

                {/* Footer Strip with metadata & quick actions */}
                <div className="mt-3 flex items-center justify-between border-t border-slate-800/70 pt-2 text-[10px] font-mono text-slate-400">
                  <div className="flex items-center space-x-3">
                    <span>{formatFileSize(doc.size_bytes)}</span>
                    {doc.page_count !== null && (
                      <span>{doc.page_count} Seiten</span>
                    )}
                    {doc.contains_special_categories && (
                      <span className="text-red-400 font-bold">
                        Art. 9/10 DSGVO
                      </span>
                    )}
                  </div>

                  {/* Action trigger */}
                  <div>
                    {doc.status === "uploaded" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onTriggerExtract(doc.id);
                        }}
                        disabled={isCurrentlyExtracting}
                        className="inline-flex items-center space-x-1 rounded bg-gradient-to-r from-cyan-600 to-emerald-600 hover:from-cyan-500 hover:to-emerald-500 px-2 py-0.5 text-[10px] font-semibold text-white shadow transition-all disabled:opacity-50"
                      >
                        {isCurrentlyExtracting ? (
                          <>
                            <RefreshCw className="h-2.5 w-2.5 animate-spin" />
                            <span>Extrahiere...</span>
                          </>
                        ) : (
                          <>
                            <Zap className="h-2.5 w-2.5" />
                            <span>Audit starten</span>
                          </>
                        )}
                      </button>
                    )}
                    {doc.status === "extracted" && (
                      <span className="text-slate-500 flex items-center space-x-1">
                        <Clock className="h-2.5 w-2.5" />
                        <span>Geprüft</span>
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
