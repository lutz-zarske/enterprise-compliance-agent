"use client";

import React from "react";
import { AIActAssessment } from "../types/api";
import { ShieldAlert, ShieldCheck, Scale, AlertTriangle, CheckCircle2, Cpu, Info, ArrowUpRight } from "./icons";

interface RiskCardProps {
  assessment: AIActAssessment | null;
  isLoading?: boolean;
}

export const RiskCard: React.FC<RiskCardProps> = ({ assessment, isLoading }) => {
  if (isLoading) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 animate-pulse">
        <div className="h-6 w-48 bg-slate-800 rounded mb-4" />
        <div className="h-20 bg-slate-800/50 rounded-xl mb-4" />
        <div className="h-32 bg-slate-800/30 rounded-xl" />
      </div>
    );
  }

  if (!assessment) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 text-center text-slate-400">
        <Scale className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-xs font-mono">Noch keine EU-AI-Act-Einstufung vorhanden. Bitte Extraktion ausführen.</p>
      </div>
    );
  }

  const isHighRisk = assessment.is_high_risk || assessment.overall_risk_level === "high" || assessment.overall_risk_level === "unacceptable";
  const isMinimal = assessment.overall_risk_level === "minimal" || assessment.overall_risk_level === "not_applicable";
  const isLimited = assessment.overall_risk_level === "limited";

  return (
    <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 shadow-2xl relative overflow-hidden space-y-5">
      {/* Background ambient light */}
      <div
        className={`absolute -top-24 -left-24 h-48 w-48 rounded-full blur-3xl pointer-events-none ${
          isHighRisk ? "bg-red-500/10" : "bg-emerald-500/10"
        }`}
      />

      {/* Top Header Strip */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2.5">
          <div
            className={`flex h-8 w-8 items-center justify-center rounded-xl border ${
              isHighRisk
                ? "border-red-500/40 bg-red-950/40 text-red-400"
                : "border-emerald-500/40 bg-emerald-950/40 text-emerald-400"
            }`}
          >
            <Scale className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold tracking-wide text-white uppercase font-mono">
              EU AI Act Klassifizierung (VO (EU) 2024/1689)
            </h3>
            <p className="text-xs text-slate-400">
              Regulatorische Einordnung nach Artikel 6 & Anhang III
            </p>
          </div>
        </div>

        <span className="text-[11px] font-mono text-slate-400">
          Inkrafttreten: 01.08.2024
        </span>
      </div>

      {/* Hero Classification Banner */}
      <div
        className={`rounded-2xl p-5 border flex flex-col md:flex-row items-start md:items-center justify-between gap-4 transition-all ${
          isHighRisk
            ? "border-red-500/50 bg-gradient-to-r from-red-950/50 via-slate-900/80 to-slate-950 shadow-[0_0_30px_rgba(239,68,68,0.2)]"
            : isLimited
            ? "border-amber-500/50 bg-gradient-to-r from-amber-950/50 via-slate-900/80 to-slate-950"
            : "border-emerald-500/50 bg-gradient-to-r from-emerald-950/50 via-slate-900/80 to-slate-950 shadow-[0_0_30px_rgba(16,185,129,0.15)]"
        }`}
      >
        <div className="flex items-center space-x-4">
          <div
            className={`h-14 w-14 rounded-2xl flex items-center justify-center border shrink-0 ${
              isHighRisk
                ? "border-red-500/60 bg-red-900/40 text-red-400 shadow-lg shadow-red-950/60"
                : "border-emerald-500/60 bg-emerald-900/40 text-emerald-400 shadow-lg shadow-emerald-950/60"
            }`}
          >
            {isHighRisk ? (
              <ShieldAlert className="h-8 w-8 text-red-400 animate-pulse" />
            ) : (
              <ShieldCheck className="h-8 w-8 text-emerald-400" />
            )}
          </div>

          <div>
            <div className="flex items-center space-x-2">
              <span className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400">
                Regulatorischer Risikostatus:
              </span>
            </div>
            <div className="flex items-center space-x-3">
              <span
                className={`text-2xl font-extrabold tracking-tight uppercase font-mono ${
                  isHighRisk
                    ? "text-red-400 drop-shadow-[0_0_12px_rgba(239,68,68,0.5)]"
                    : isLimited
                    ? "text-amber-400"
                    : "text-emerald-400 drop-shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                }`}
              >
                {isHighRisk ? "HIGH RISK (HOCHRISIKO)" : isLimited ? "LIMITED RISK" : "MINIMAL RISK"}
              </span>
            </div>
          </div>
        </div>

        {/* Quick Legal Tag */}
        <div className="flex flex-col items-start md:items-end text-xs font-mono">
          <span className="text-slate-400">Rechtsgrundlage:</span>
          <span className="font-semibold text-cyan-300">
            {isHighRisk ? "Art. 6 Abs. 2 i.V.m. Anhang III" : "Art. 2 & Erwägungsgrund 32"}
          </span>
          <span className="text-[10px] text-slate-500">
            {assessment.describes_ai_system ? "KI-System identifiziert" : "Kein KI-System nachgewiesen"}
          </span>
        </div>
      </div>

      {/* Begründung (Reasoning) */}
      {assessment.reasoning && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-1.5">
          <div className="flex items-center space-x-2 text-xs font-mono font-semibold text-slate-300">
            <Info className="h-3.5 w-3.5 text-cyan-400" />
            <span>Juristische Begründung der Einstufung:</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed pl-5">
            {assessment.reasoning}
          </p>
        </div>
      )}

      {/* Identifizierte KI-Systeme & Anhang III Kategorien */}
      {assessment.systems && assessment.systems.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <Cpu className="h-3.5 w-3.5 text-cyan-400" />
            <span>Erfasste KI-Systeme & Anhang-III-Anwendungsbereiche</span>
          </h4>

          <div className="space-y-2.5">
            {assessment.systems.map((system, idx) => (
              <div
                key={idx}
                className="rounded-xl border border-slate-800/90 bg-slate-900/60 p-4 space-y-2.5 hover:border-slate-700 transition-colors"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-white font-mono">
                      {system.name || "Unbenanntes KI-System"}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                        system.risk_level === "high" || system.risk_level === "unacceptable"
                          ? "bg-red-950 text-red-300 border border-red-500/40"
                          : "bg-emerald-950 text-emerald-300 border border-emerald-500/40"
                      }`}
                    >
                      {system.risk_level}
                    </span>
                  </div>

                  <div className="text-[11px] font-mono text-slate-400">
                    Konfidenz:{" "}
                    <span className="text-cyan-300 font-bold">
                      {(system.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                {/* Purpose */}
                <p className="text-xs text-slate-300">
                  <strong className="text-slate-400 font-mono">Zweckbestimmung:</strong> {system.purpose}
                </p>

                {/* Annex III Categories badges */}
                {system.annex_iii_categories && system.annex_iii_categories.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    <span className="text-[10px] font-mono text-slate-500 mr-1">
                      Kategorien:
                    </span>
                    {system.annex_iii_categories.map((cat, catIdx) => (
                      <span
                        key={catIdx}
                        className="inline-flex items-center space-x-1 rounded-md border border-red-500/30 bg-red-950/30 px-2 py-0.5 text-[10px] font-mono font-semibold text-red-300"
                      >
                        <AlertTriangle className="h-2.5 w-2.5" />
                        <span>{cat}</span>
                      </span>
                    ))}
                  </div>
                )}

                {/* Evidence snippet */}
                {system.evidence && (
                  <div className="rounded-lg bg-slate-950/80 border border-slate-850 p-2 text-[11px] font-mono text-slate-400 italic">
                    &ldquo;{system.evidence}&rdquo;
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Gesetzliche Verpflichtungen (Obligations) */}
      {assessment.obligations && assessment.obligations.length > 0 && (
        <div className="space-y-2 pt-1 border-t border-slate-800/80">
          <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            <span>Verbindliche Betreiber- & Herstellerpflichten</span>
          </h4>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {assessment.obligations.map((obligation, idx) => (
              <div
                key={idx}
                className="flex items-start space-x-2 rounded-lg border border-slate-800/70 bg-slate-950/40 p-2.5 text-xs text-slate-300"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 mt-1.5 shrink-0" />
                <span className="leading-snug">{obligation}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
