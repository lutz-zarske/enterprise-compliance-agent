"use client";

import React, { useState } from "react";
import { DocumentDetail } from "../types/api";
import { exportDocumentAsJson, exportAuditProtocolMarkdown } from "../lib/api";
import { Download, FileText, Check, Copy, X } from "./icons";

interface ExportModalProps {
  document: DocumentDetail | null;
  isOpen: boolean;
  onClose: () => void;
}

export const ExportModal: React.FC<ExportModalProps> = ({
  document,
  isOpen,
  onClose,
}) => {
  const [copied, setCopied] = useState<boolean>(false);
  const [format, setFormat] = useState<"json" | "markdown">("json");

  if (!isOpen || !document) return null;

  const jsonContent = JSON.stringify(document, null, 2);

  const handleDownload = () => {
    if (format === "json") {
      exportDocumentAsJson(document);
    } else {
      exportAuditProtocolMarkdown(document);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4">
      <div className="glass-panel w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900/95 p-6 shadow-2xl space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center space-x-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
              <Download className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white font-mono uppercase">
                Compliance-Audit Export
              </h3>
              <p className="text-xs text-slate-400">
                {document.filename} (ID: {document.id.slice(0, 8)}...)
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Format Selector */}
        <div className="flex items-center space-x-2 border-b border-slate-800/80 pb-3 text-xs font-mono">
          <button
            onClick={() => setFormat("json")}
            className={`px-3 py-1.5 rounded-lg border transition-all ${
              format === "json"
                ? "border-cyan-500/50 bg-cyan-950/40 text-cyan-300 font-bold"
                : "border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"
            }`}
          >
            Maschinenlesbares JSON (.json)
          </button>
          <button
            onClick={() => setFormat("markdown")}
            className={`px-3 py-1.5 rounded-lg border transition-all ${
              format === "markdown"
                ? "border-cyan-500/50 bg-cyan-950/40 text-cyan-300 font-bold"
                : "border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"
            }`}
          >
            Revisionssicheres Audit-Protokoll (.md)
          </button>
        </div>

        {/* Code Preview */}
        <div className="relative rounded-xl border border-slate-800 bg-slate-950 p-3 max-h-72 overflow-y-auto font-mono text-xs text-slate-300">
          <pre>{format === "json" ? jsonContent : "# Vorschau Audit-Protokoll (EU AI Act & DSGVO Art. 9/10)\nKlicken Sie auf 'Herunterladen' für das vollständige Markdown-Zertifikat."}</pre>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={handleCopy}
            className="flex items-center space-x-1.5 text-xs font-mono text-slate-400 hover:text-cyan-300"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-400" />
                <span className="text-emerald-400">In Zwischenablage kopiert!</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                <span>JSON kopieren</span>
              </>
            )}
          </button>

          <div className="flex items-center space-x-2">
            <button
              onClick={onClose}
              className="px-3.5 py-1.5 rounded-xl border border-slate-800 text-xs font-mono text-slate-300 hover:bg-slate-800"
            >
              Schließen
            </button>
            <button
              onClick={handleDownload}
              className="flex items-center space-x-1.5 px-4 py-1.5 rounded-xl bg-gradient-to-r from-cyan-600 to-emerald-600 hover:from-cyan-500 hover:to-emerald-500 text-xs font-mono font-bold text-white shadow-lg shadow-cyan-950/50"
            >
              <Download className="h-3.5 w-3.5" />
              <span>{format === "json" ? "JSON herunterladen" : "Audit-Protokoll herunterladen"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
