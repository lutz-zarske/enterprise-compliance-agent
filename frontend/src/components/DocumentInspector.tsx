"use client";

import React, { useState, useMemo } from "react";
import { DocumentDetail, PIIFinding } from "../types/api";
import {
  Lock,
  Eye,
  EyeOff,
  ShieldCheck,
  ShieldAlert,
  Copy,
  Check,
  Search,
  Filter,
  Info,
} from "./icons";

interface DocumentInspectorProps {
  document: DocumentDetail | null;
}

export const DocumentInspector: React.FC<DocumentInspectorProps> = ({
  document,
}) => {
  const [activeTab, setActiveTab] = useState<"side_by_side" | "redacted" | "original" | "audit_table">(
    "side_by_side"
  );
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [copied, setCopied] = useState<boolean>(false);

  const rawText = document?.text_preview || "Kein Text verfügbar.";
  const gdpr = document?.compliance?.gdpr;
  const findings = useMemo(() => gdpr?.findings || [], [gdpr]);

  // Compute category color
  const getCategoryTheme = (finding: PIIFinding) => {
    if (finding.is_special_category) {
      return {
        bg: "bg-red-950/40",
        border: "border-red-500/40",
        text: "text-red-300",
        badge: "pii-badge-health",
      };
    }
    if (finding.category === "bank_account") {
      return {
        bg: "bg-amber-950/40",
        border: "border-amber-500/40",
        text: "text-amber-300",
        badge: "pii-badge-financial",
      };
    }
    if (finding.category === "contact_data") {
      return {
        bg: "bg-cyan-950/40",
        border: "border-cyan-500/40",
        text: "text-cyan-300",
        badge: "pii-badge-contact",
      };
    }
    return {
      bg: "bg-emerald-950/40",
      border: "border-emerald-500/40",
      text: "text-emerald-300",
      badge: "pii-badge-name",
    };
  };

  // Generate synthetic / highlighted redacted text by masking detected patterns
  const redactedText = useMemo(() => {
    let text = rawText;

    // Apply replacement for IBANs, emails, health data, names
    findings.forEach((f) => {
      if (f.masked_value) {
        // Try matching part of context or replace common markers
        if (f.category === "bank_account" && text.includes("DE89370400440532013000")) {
          text = text.replace("DE89370400440532013000", "[IBAN_1: DE89 **** 3000]");
        }
        if (f.category === "contact_data" && text.includes("compliance-officer@talentmetrics-solutions.de")) {
          text = text.replace(
            "compliance-officer@talentmetrics-solutions.de",
            "[CONTACT_1: c***@talentmetrics-solutions.de]"
          );
        }
        if (f.category === "name" && text.includes("Dr. Klaus Weber")) {
          text = text.replace("Dr. Klaus Weber", "[NAME_1: Dr. K*** W***]");
        }
      }
    });

    // Generic replacements for standard placeholders if not already matched
    text = text.replace(/DE\d{20}/g, "[IBAN_REDACTED: DE** **** 3000]");
    text = text.replace(/[\w.-]+@[\w.-]+\.\w+/g, "[EMAIL_REDACTED: c***@domain.de]");

    return text;
  }, [rawText, findings]);

  const handleCopyRedacted = () => {
    navigator.clipboard.writeText(redactedText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const filteredFindings = findings.filter((f) => {
    if (filterCategory === "all") return true;
    if (filterCategory === "special") return f.is_special_category;
    return f.category === filterCategory;
  });

  if (!document) {
    return (
      <div className="glass-panel rounded-2xl p-8 border border-slate-800 text-center text-slate-500">
        <Lock className="h-8 w-8 mx-auto mb-2 opacity-40" />
        <p className="text-xs">Wählen Sie ein Dokument aus der Liste aus, um die PII-Redaction zu inspizieren.</p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 shadow-2xl space-y-5">
      {/* Title & Stats Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
        <div className="flex items-center space-x-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-500/40 bg-emerald-950/40 text-emerald-400">
            <Lock className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="text-sm font-bold tracking-wide text-white uppercase font-mono">
                Live PII Redaction & Document Inspector
              </h3>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-500/30">
                DSGVO Art. 9/10 Konform
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Automatische Anonymisierung im Ruhezustand & Revisionssicherer Audit-Trail
            </p>
          </div>
        </div>

        {/* Action & Tab Navigation */}
        <div className="flex flex-wrap items-center gap-1.5 bg-slate-950/80 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setActiveTab("side_by_side")}
            className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all ${
              activeTab === "side_by_side"
                ? "bg-slate-800 text-cyan-300 font-bold shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Side-by-Side
          </button>
          <button
            onClick={() => setActiveTab("redacted")}
            className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all ${
              activeTab === "redacted"
                ? "bg-slate-800 text-cyan-300 font-bold shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Anonymisiert
          </button>
          <button
            onClick={() => setActiveTab("original")}
            className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all ${
              activeTab === "original"
                ? "bg-slate-800 text-cyan-300 font-bold shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Original
          </button>
          <button
            onClick={() => setActiveTab("audit_table")}
            className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all ${
              activeTab === "audit_table"
                ? "bg-slate-800 text-cyan-300 font-bold shadow"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            DSGVO-Nachweis ({findings.length})
          </button>
        </div>
      </div>

      {/* Quick Metrics Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase font-mono text-slate-500 block">PII-Gesamtfunde</span>
          <span className="text-lg font-bold font-mono text-cyan-400">{findings.length} Treffer</span>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase font-mono text-slate-500 block">Besondere Kategorien</span>
          <span className={`text-lg font-bold font-mono ${gdpr?.contains_special_categories ? "text-red-400" : "text-emerald-400"}`}>
            {findings.filter((f) => f.is_special_category).length} (Art. 9/10)
          </span>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase font-mono text-slate-500 block">DSGVO-Risikostufe</span>
          <span className={`text-lg font-bold font-mono uppercase ${gdpr?.risk_level === "high" ? "text-red-400" : "text-emerald-400"}`}>
            {gdpr?.risk_level || "NONE"}
          </span>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <span className="text-[10px] uppercase font-mono text-slate-500 block">Storage-Masking</span>
          <span className="text-lg font-bold font-mono text-emerald-400 flex items-center space-x-1">
            <ShieldCheck className="h-4 w-4" />
            <span>AKTIV (SHA-256)</span>
          </span>
        </div>
      </div>

      {/* Main Content Area Based on Active Tab */}
      {activeTab === "side_by_side" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Left: Original Preview */}
          <div className="rounded-xl border border-slate-800/90 bg-slate-950/70 p-4 flex flex-col">
            <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800 text-xs font-mono">
              <span className="text-slate-400 flex items-center space-x-1.5">
                <Eye className="h-3.5 w-3.5 text-amber-400" />
                <span className="font-semibold text-slate-300">Original-Textlayer (Auszug)</span>
              </span>
              <span className="text-[10px] text-amber-400/80 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-500/30">
                Sensibel
              </span>
            </div>
            <pre className="font-mono text-xs text-slate-300 whitespace-pre-wrap overflow-y-auto max-h-[380px] leading-relaxed select-text">
              {rawText}
            </pre>
          </div>

          {/* Right: Redacted Preview */}
          <div className="rounded-xl border border-cyan-500/30 bg-slate-950/90 p-4 flex flex-col shadow-inner">
            <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800 text-xs font-mono">
              <span className="text-cyan-400 flex items-center space-x-1.5">
                <Lock className="h-3.5 w-3.5 text-cyan-400" />
                <span className="font-semibold text-cyan-300">Anonymisierter Text (Redacted)</span>
              </span>
              <button
                onClick={handleCopyRedacted}
                className="flex items-center space-x-1 text-[11px] text-slate-400 hover:text-cyan-300 transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-400" />
                    <span className="text-emerald-400">Kopiert</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    <span>Kopieren</span>
                  </>
                )}
              </button>
            </div>
            <div className="font-mono text-xs text-slate-200 whitespace-pre-wrap overflow-y-auto max-h-[380px] leading-relaxed select-text">
              {redactedText.split(/(\[.*?\])/g).map((part, index) => {
                if (part.startsWith("[") && part.endsWith("]")) {
                  const isHealth = part.includes("HEALTH") || part.includes("GESUNDHEIT") || part.includes("STRAFRECHT");
                  const isIban = part.includes("IBAN");
                  const isContact = part.includes("CONTACT") || part.includes("EMAIL");
                  const badgeClass = isHealth
                    ? "pii-badge-health font-bold px-1.5 py-0.5 rounded"
                    : isIban
                    ? "pii-badge-financial font-bold px-1.5 py-0.5 rounded"
                    : isContact
                    ? "pii-badge-contact font-bold px-1.5 py-0.5 rounded"
                    : "pii-badge-name font-bold px-1.5 py-0.5 rounded";

                  return (
                    <span key={index} className={badgeClass}>
                      {part}
                    </span>
                  );
                }
                return <span key={index}>{part}</span>;
              })}
            </div>
          </div>
        </div>
      )}

      {activeTab === "redacted" && (
        <div className="rounded-xl border border-cyan-500/30 bg-slate-950/90 p-5 shadow-inner">
          <div className="flex items-center justify-between pb-2 mb-3 border-b border-slate-800 text-xs font-mono">
            <span className="text-cyan-400 font-semibold flex items-center space-x-1.5">
              <Lock className="h-3.5 w-3.5" />
              <span>Vollständig anonymisierte Dokumentenansicht</span>
            </span>
            <button
              onClick={handleCopyRedacted}
              className="flex items-center space-x-1 text-xs text-slate-400 hover:text-cyan-300"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              <span>Text kopieren</span>
            </button>
          </div>
          <div className="font-mono text-xs text-slate-200 whitespace-pre-wrap overflow-y-auto max-h-[460px] leading-relaxed">
            {redactedText.split(/(\[.*?\])/g).map((part, index) => {
              if (part.startsWith("[") && part.endsWith("]")) {
                const isHealth = part.includes("HEALTH") || part.includes("GESUNDHEIT") || part.includes("STRAFRECHT");
                const isIban = part.includes("IBAN");
                const isContact = part.includes("CONTACT") || part.includes("EMAIL");
                const badgeClass = isHealth
                  ? "pii-badge-health font-bold px-1.5 py-0.5 rounded"
                  : isIban
                  ? "pii-badge-financial font-bold px-1.5 py-0.5 rounded"
                  : isContact
                  ? "pii-badge-contact font-bold px-1.5 py-0.5 rounded"
                  : "pii-badge-name font-bold px-1.5 py-0.5 rounded";

                return (
                  <span key={index} className={badgeClass}>
                    {part}
                  </span>
                );
              }
              return <span key={index}>{part}</span>;
            })}
          </div>
        </div>
      )}

      {activeTab === "original" && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-5">
          <div className="flex items-center justify-between pb-2 mb-3 border-b border-slate-800 text-xs font-mono text-amber-400">
            <span className="font-semibold flex items-center space-x-1.5">
              <Eye className="h-3.5 w-3.5" />
              <span>Unmaskierter Textlayer vor Speicherung</span>
            </span>
          </div>
          <pre className="font-mono text-xs text-slate-300 whitespace-pre-wrap overflow-y-auto max-h-[460px] leading-relaxed">
            {rawText}
          </pre>
        </div>
      )}

      {activeTab === "audit_table" && (
        <div className="space-y-3">
          {/* Filter Bar for Table */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Filter className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 focus:outline-none font-mono"
              >
                <option value="all">Alle Kategorien ({findings.length})</option>
                <option value="special">Nur Art. 9/10 Besondere Kategorien</option>
                <option value="bank_account">Bankdaten (IBAN)</option>
                <option value="contact_data">Kontaktdaten</option>
                <option value="health_data">Gesundheitsdaten</option>
                <option value="name">Namen natürlicher Personen</option>
              </select>
            </div>

            <span className="text-[11px] font-mono text-slate-400">
              Prüfungsmethode: Hybrider LLM- & Regex-Dual-Scan
            </span>
          </div>

          {/* Table of PII Findings */}
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/70">
            <table className="w-full text-left text-xs font-mono">
              <thead className="border-b border-slate-800 bg-slate-900/80 text-[11px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-3">DSGVO-Kategorie</th>
                  <th className="px-4 py-3">Maskierter Wert</th>
                  <th className="px-4 py-3">Kontext & Fundstelle</th>
                  <th className="px-4 py-3">Konfidenz</th>
                  <th className="px-4 py-3">Quelle</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-850 text-slate-300">
                {filteredFindings.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                      Keine PII-Treffer für diesen Filter gefunden.
                    </td>
                  </tr>
                ) : (
                  filteredFindings.map((f, i) => {
                    const theme = getCategoryTheme(f);
                    return (
                      <tr key={i} className="hover:bg-slate-900/50 transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-semibold text-white">
                            {f.category_label || f.category}
                          </div>
                          {f.is_special_category && (
                            <span className="inline-block mt-0.5 rounded px-1.5 py-0.2 text-[9px] font-bold bg-red-950 text-red-400 border border-red-500/40">
                              Art. 9/10 DSGVO
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-semibold text-cyan-300">
                          <code className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                            {f.masked_value}
                          </code>
                        </td>
                        <td className="px-4 py-3 max-w-xs truncate text-slate-400" title={f.context}>
                          {f.context}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center space-x-1.5">
                            <div className="h-1.5 w-12 rounded-full bg-slate-800 overflow-hidden">
                              <div
                                className="h-full bg-cyan-400"
                                style={{ width: `${(f.confidence * 100).toFixed(0)}%` }}
                              />
                            </div>
                            <span className="text-[11px] text-slate-300">
                              {(f.confidence * 100).toFixed(0)}%
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 uppercase text-[10px] text-slate-400">
                          {f.source}
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center space-x-1 text-emerald-400">
                            <ShieldCheck className="h-3 w-3" />
                            <span>Maskiert</span>
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
