"use client";

import React from "react";
import { ExtractionResult } from "../types/api";
import { FileText, CheckCircle2, AlertTriangle, AlertCircle, Info, Scale } from "./icons";

interface ExtractionCardProps {
  extraction: ExtractionResult | null;
  isLoading?: boolean;
}

export const ExtractionCard: React.FC<ExtractionCardProps> = ({
  extraction,
  isLoading,
}) => {
  if (isLoading) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 animate-pulse space-y-4">
        <div className="h-5 w-44 bg-slate-800 rounded" />
        <div className="grid grid-cols-2 gap-4">
          <div className="h-16 bg-slate-800/40 rounded-xl" />
          <div className="h-16 bg-slate-800/40 rounded-xl" />
        </div>
      </div>
    );
  }

  if (!extraction) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 text-center text-slate-500">
        <FileText className="h-8 w-8 mx-auto mb-2 opacity-40" />
        <p className="text-xs">Keine Kerndaten extrahiert.</p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 shadow-xl space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-950/40 text-cyan-400">
            <FileText className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold tracking-wide text-white uppercase font-mono">
              Fachliche Dokumenten-Extraktion
            </h3>
            <p className="text-xs text-slate-400">
              Extrahierte Vertrags- & Rechnungsmetadaten (Durchlauf 1)
            </p>
          </div>
        </div>

        <span className="inline-flex items-center rounded-md border border-cyan-500/30 bg-cyan-950/60 px-2.5 py-1 text-xs font-mono font-bold uppercase text-cyan-300">
          Typ: {extraction.doc_type}
        </span>
      </div>

      {/* Grid of Key Metadata */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 font-mono text-xs">
        {/* Absender */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Absender / Aussteller</span>
          <span className="font-semibold text-slate-200 truncate block mt-0.5" title={extraction.sender || ""}>
            {extraction.sender || "Nicht angegeben"}
          </span>
        </div>

        {/* Empfaenger */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Empfänger</span>
          <span className="font-semibold text-slate-200 truncate block mt-0.5" title={extraction.recipient || ""}>
            {extraction.recipient || "Nicht angegeben"}
          </span>
        </div>

        {/* Belegnummer */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Beleg- / Vertragsnummer</span>
          <span className="font-semibold text-cyan-300 block mt-0.5">
            {extraction.document_number || "Nicht angegeben"}
          </span>
        </div>

        {/* Belegdatum */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Belegdatum</span>
          <span className="font-semibold text-slate-200 block mt-0.5">
            {extraction.document_date || "Nicht angegeben"}
          </span>
        </div>

        {/* Faelligkeit */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Fälligkeit / Vertragsende</span>
          <span className="font-semibold text-slate-200 block mt-0.5">
            {extraction.due_date || "Nicht angegeben"}
          </span>
        </div>

        {/* Betrag */}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase text-slate-500 block">Gesamtbetrag (Brutto)</span>
          <span className="font-bold text-emerald-400 text-sm block mt-0.5">
            {extraction.total_amount !== null
              ? `${Number(extraction.total_amount).toLocaleString("de-DE", { minimumFractionDigits: 2 })} ${extraction.currency || "EUR"}`
              : "Nicht angegeben"}
          </span>
        </div>
      </div>

      {/* IBAN & Checksum strip */}
      {extraction.iban && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3 flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
          <div className="flex items-center space-x-2">
            <span className="text-slate-500 uppercase text-[10px]">IBAN:</span>
            <code className="text-cyan-300 font-bold bg-slate-900 px-2 py-0.5 rounded border border-slate-850">
              {extraction.iban}
            </code>
          </div>

          <div className="flex items-center space-x-1.5">
            {extraction.iban_valid === true ? (
              <span className="inline-flex items-center space-x-1 text-emerald-400 font-semibold bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-500/30 text-[11px]">
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>MOD-97 Prüfsumme GÜLTIG</span>
              </span>
            ) : extraction.iban_valid === false ? (
              <span className="inline-flex items-center space-x-1 text-red-400 font-semibold bg-red-950/50 px-2 py-0.5 rounded border border-red-500/30 text-[11px]">
                <AlertCircle className="h-3.5 w-3.5" />
                <span>MOD-97 Prüfsumme UNGÜLTIG</span>
              </span>
            ) : null}
          </div>
        </div>
      )}

      {/* Zusammenfassung */}
      {extraction.summary && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 space-y-1.5">
          <span className="text-[11px] font-mono uppercase font-bold text-slate-400 block">
            Synthetische Zusammenfassung
          </span>
          <p className="text-xs text-slate-300 leading-relaxed">
            {extraction.summary}
          </p>
        </div>
      )}

      {/* Auffaelligkeiten (Issues) */}
      {extraction.issues && extraction.issues.length > 0 && (
        <div className="space-y-2">
          <span className="text-[11px] font-mono uppercase font-bold text-amber-400 flex items-center space-x-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            <span>Dokumentierte Auffälligkeiten & Unstimmigkeiten ({extraction.issues.length})</span>
          </span>

          <div className="space-y-1.5">
            {extraction.issues.map((issue, idx) => (
              <div
                key={idx}
                className="flex items-start space-x-2 rounded-lg border border-amber-500/30 bg-amber-950/20 p-2.5 text-xs text-amber-200"
              >
                <span className="font-bold font-mono text-amber-400 mt-0.5">•</span>
                <span className="leading-snug">{issue}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
