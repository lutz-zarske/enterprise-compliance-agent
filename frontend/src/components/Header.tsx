"use client";

import React from "react";
import { HealthResponse } from "../types/api";
import { ShieldCheck, ShieldAlert, ShieldX, RefreshCw, Cpu, Database, Server } from "./icons";

interface HeaderProps {
  health: HealthResponse | null;
  isLoadingHealth: boolean;
  onRefresh: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  isLoadingHealth,
  onRefresh,
}) => {
  const isConnecting = isLoadingHealth && !health;
  const isOk = health?.status === "ok";
  const isDegraded = health?.status === "degraded";
  const isUnavailable = !isConnecting && (!health || health.status === "unavailable");

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-[#0b0f19]/85 backdrop-blur-xl">
      <div className="mx-auto max-w-7xl px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          {/* Logo & Main Title */}
          <div className="flex items-center space-x-3.5">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 via-cyan-500/20 to-indigo-500/20 border border-cyan-500/30 shadow-lg shadow-cyan-950/40">
              <ShieldCheck className="h-6 w-6 text-cyan-400" />
              <div className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-[#0b0f19]" />
            </div>

            <div>
              <div className="flex items-center space-x-2.5">
                <h1 className="text-base font-bold tracking-tight text-white sm:text-lg">
                  Enterprise AI Compliance & Audit Agent
                </h1>
                <span className="inline-flex items-center rounded-md border border-cyan-500/30 bg-cyan-950/60 px-2 py-0.5 text-[11px] font-mono font-medium text-cyan-300">
                  VO (EU) 2024/1689
                </span>
                <span className="hidden sm:inline-flex items-center rounded-md border border-emerald-500/30 bg-emerald-950/60 px-2 py-0.5 text-[11px] font-mono font-medium text-emerald-300">
                  DSGVO Art. 9/10
                </span>
              </div>
              <p className="text-xs text-slate-400">
                Institutional Regulatory Governance & Automated PII Redaction Engine
              </p>
            </div>
          </div>

          {/* Right Section: Backend Health & System Status */}
          <div className="flex items-center space-x-3">
            {/* Health Status Pill */}
            <div
              className={`flex items-center space-x-2 rounded-xl border px-3 py-1.5 text-xs font-mono transition-all ${
                isOk
                  ? "border-emerald-500/40 bg-emerald-950/30 text-emerald-300"
                  : isDegraded
                  ? "border-amber-500/40 bg-amber-950/30 text-amber-300"
                  : isConnecting
                  ? "border-cyan-500/40 bg-cyan-950/30 text-cyan-300"
                  : "border-red-500/40 bg-red-950/30 text-red-300"
              }`}
            >
              <span className="relative flex h-2 w-2">
                <span
                  className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    isOk
                      ? "animate-ping bg-emerald-400"
                      : isDegraded
                      ? "animate-ping bg-amber-400"
                      : isConnecting
                      ? "animate-ping bg-cyan-400"
                      : "bg-red-400"
                  }`}
                />
                <span
                  className={`relative inline-flex h-2 w-2 rounded-full ${
                    isOk
                      ? "bg-emerald-500"
                      : isDegraded
                      ? "bg-amber-500"
                      : isConnecting
                      ? "bg-cyan-500"
                      : "bg-red-500"
                  }`}
                />
              </span>

              <div className="flex items-center space-x-1.5">
                <span className="font-semibold uppercase tracking-wider">
                  {isOk ? "API ONLINE" : isDegraded ? "DEGRADED" : isConnecting ? "CONNECTING..." : "OFFLINE"}
                </span>
                <span className="text-slate-500">|</span>
                <span className="text-[11px] text-slate-300">
                  :8001
                </span>
              </div>

              {health?.ollama?.model && (
                <div className="hidden md:flex items-center space-x-1 pl-1 border-l border-slate-700/60 text-slate-300">
                  <Cpu className="h-3.5 w-3.5 text-cyan-400" />
                  <span className="text-[10px] text-cyan-300 truncate max-w-[130px]">
                    {health.ollama.model}
                  </span>
                </div>
              )}

              {health?.database?.dialect && (
                <div className="hidden lg:flex items-center space-x-1 pl-1 border-l border-slate-700/60 text-slate-300">
                  <Database className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-[10px] uppercase text-emerald-300">
                    {health.database.dialect}
                  </span>
                </div>
              )}
            </div>

            {/* Refresh Action */}
            <button
              onClick={onRefresh}
              disabled={isLoadingHealth}
              title="System-Status und Dokumente aktualisieren"
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-800 bg-slate-900/80 text-slate-400 transition-all hover:border-slate-700 hover:bg-slate-800 hover:text-white disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${isLoadingHealth ? "animate-spin text-cyan-400" : ""}`}
              />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
