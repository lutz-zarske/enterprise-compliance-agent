"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { cx, formatDate, formatModel, providerLabel } from "../lib/format";
import type { DocumentDetail, DocumentSummary, LedgerEntry, LedgerVerification } from "../types/api";
import { BookOpen, Download, Fingerprint, Layers, Lock, Package, RefreshCw, Scale, ShieldAlert, ShieldCheck } from "./icons";
import { Chip, EmptyState, HashBadge, PillTabs, Skeleton, Spinner, Tooltip } from "./ui";

type Filter = "all" | "document" | "system";

export const EVENT_LABELS: Record<string, string> = {
  analysis: "Analyse",
  sign_off: "Prüfer-Siegel",
  human_override: "Übersteuerung (Art. 14)",
  provider_failover: "Stufenwechsel der KI-Kaskade",
  model_change: "Modellwechsel",
  archive: "Archiviert",
  unarchive: "Aus dem Archiv geholt",
  release_update: "Release-Wechsel",
};

const MILESTONES = new Set(["sign_off", "human_override", "model_change", "release_update"]);

/** Regelwerk und Rechtsgrundlagen - dieselben Angaben wie Zertifikat und Verfahrensdokumentation. */
const RULES: { title: string; text: string }[] = [
  { title: "§ 14 Abs. 4 UStG · EN 16931", text: "Pflichtangaben je Rechnung; bei hybriden E-Rechnungen ist der XML-Datensatz maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36)." },
  { title: "EU AI Act – VO (EU) 2024/1689", text: "Anhang-III-Eskalation (Art. 6 Abs. 2), automatisches Logging (Art. 12), menschliche Aufsicht und Übersteuerung (Art. 14 Abs. 4 lit. d); Pflichten ab 02.12.2027 (VO (EU) 2026/1744)." },
  { title: "DSGVO Art. 4 Nr. 5, 9, 25, 32", text: "Pseudonymisierung im Backend vor jedem Cloud-Aufruf (Privacy Vault); Befunde ausschließlich maskiert gespeichert." },
  { title: "GoBD · § 147 AO · BEG IV", text: "Hash-verkettetes, Ed25519-signiertes Prüfprotokoll; Buchungsbelege 8 Jahre, Verfahrensdokumentation und Handelsbücher 10 Jahre." },
];

function IntegrityStrip({ ledger, fingerprint, onRefresh, refreshing }: {
  ledger: LedgerVerification | null;
  fingerprint: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const state = !ledger ? "unknown" : !ledger.valid ? "broken" : ledger.entries === 0 ? "empty" : "ok";
  return (
    <section className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3" aria-label="Integrität der Hash-Kette">
      <div className="flex items-center gap-2.5">
        <span className={cx("rounded-lg border p-2", state === "broken" ? "border-bad-line bg-bad-soft text-bad" : state === "ok" ? "border-ok-line bg-ok-soft text-ok" : "border-line bg-surface-2 text-subtle")}>
          {state === "broken" ? <ShieldAlert size={16} aria-hidden="true" /> : <ShieldCheck size={16} aria-hidden="true" />}
        </span>
        <div>
          <p className="text-sm font-semibold text-fg">
            {state === "ok" ? "Hash-Kette intakt · Ed25519 verifiziert" : state === "broken" ? "Manipulation erkannt · Hash-Kette gebrochen" : state === "empty" ? "Ledger noch leer" : "Ledger nicht geprüft"}
          </p>
          <p className="text-xs text-subtle">
            {ledger ? (
              <>
                <span className="tabular-nums">{ledger.entries}</span> Einträge nachgerechnet, davon{" "}
                <span className="tabular-nums">{ledger.signed_entries}</span> signiert · geprüft {formatDate(ledger.verified_at, true)}
                {!ledger.valid && ledger.broken_at_seq != null && <> · Bruch bei #{ledger.broken_at_seq}</>}
              </>
            ) : (
              "Die Prüfung der Kette ist derzeit nicht erreichbar."
            )}
          </p>
        </div>
      </div>
      {ledger && ledger.entries > 0 && <HashBadge value={ledger.head_hash} label="Kopf-Hash" verified={ledger.valid} verifiedLabel="intakt" />}
      {fingerprint && (
        <Tooltip content="Fingerabdruck des Ed25519-Systemschlüssels – in der Verfahrensdokumentation hinterlegen; damit prüft scripts/verify_pruefpaket.py die Herkunft eines Prüfpakets.">
          <span className="inline-flex items-center gap-1.5">
            <Fingerprint size={13} className="text-subtle" aria-hidden="true" />
            <HashBadge value={fingerprint} label="Schlüssel" />
          </span>
        </Tooltip>
      )}
      <button className="btn btn-sm ml-auto" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? <Spinner size={12} /> : <RefreshCw size={13} aria-hidden="true" />} Kette neu prüfen
      </button>
    </section>
  );
}

function LedgerTable({ entries, names }: { entries: LedgerEntry[]; names: Map<string, string> }) {
  return (
    <table className="w-full border-separate border-spacing-0 text-left text-xs">
      <thead className="sticky top-0 z-10 bg-surface-solid">
        <tr className="text-subtle">
          <th scope="col" className="border-b border-line px-3 py-2 text-right font-medium">#</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">Zeitpunkt (UTC)</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">Ereignis</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">Beleg</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">Zusammenfassung</th>
          <th scope="col" className="border-b border-line px-3 py-2 text-right font-medium">Score</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">Eintrag</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const milestone = MILESTONES.has(entry.event_type);
          const system = entry.document_id === "system";
          return (
            <tr key={entry.entry_id} className="align-top transition-colors duration-150 hover:bg-surface-hover">
              <td className="border-b border-line px-3 py-2 text-right tabular-nums text-subtle">{entry.seq}</td>
              <td className="whitespace-nowrap border-b border-line px-3 py-2 tabular-nums text-muted">{formatDate(entry.timestamp_utc, true)}</td>
              <td className="border-b border-line px-3 py-2">
                <span className={cx("font-medium", milestone ? "text-fg" : "text-muted")}>{EVENT_LABELS[entry.event_type] ?? entry.event_type}</span>
                {entry.signature_status === "valid" && <span className="mt-1 block"><Chip tone="ok">Ed25519 gültig</Chip></span>}
                {entry.signature_status === "invalid" && <span className="mt-1 block"><Chip tone="bad">Signatur ungültig</Chip></span>}
              </td>
              <td className="max-w-[14rem] border-b border-line px-3 py-2 text-muted">
                <span className="block truncate" title={system ? "Systemereignis" : names.get(entry.document_id) ?? entry.document_id}>
                  {system ? "System" : names.get(entry.document_id) ?? `${entry.document_id.slice(0, 8)}…`}
                </span>
                {entry.model_name && <span className="block truncate text-subtle">{formatModel(entry.model_name)}</span>}
              </td>
              <td className="border-b border-line px-3 py-2 text-muted [overflow-wrap:anywhere]">{entry.result_summary}</td>
              <td className="border-b border-line px-3 py-2 text-right tabular-nums text-fg">{entry.compliance_score ?? "–"}</td>
              <td className="whitespace-nowrap border-b border-line px-3 py-2"><HashBadge value={entry.entry_hash} label="SHA-256" /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Protokoll & Regelwerk: die vollstaendige Ed25519-signierte Hash-Kette mit
 * Systemereignissen, Exporte (GoBD-Paket, Verfahrensdokumentation) und das Regelwerk.
 */
export function ProtocolView({ document, documents, ledger, rulesetVersion, dlpRuleset, active, onRefreshLedger, onOpenExport, notify }: {
  document: DocumentDetail | null;
  documents: DocumentSummary[];
  ledger: LedgerVerification | null;
  rulesetVersion: string | null;
  dlpRuleset: string | null;
  active: boolean;
  onRefreshLedger: () => Promise<void>;
  onOpenExport: () => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const names = useMemo(() => new Map(documents.map((doc) => [doc.id, doc.filename])), [documents]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setEntries((await api.fullTrail(1000)).items);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err));
    }
  }, []);

  // Beim Oeffnen der Ansicht und nach jeder Aenderung des Kopf-Hashes neu laden.
  useEffect(() => {
    if (active) void load();
  }, [active, load, ledger?.head_hash, ledger?.entries]);

  useEffect(() => {
    if (!active || fingerprint) return;
    api.signingKey().then((key) => setFingerprint(key.fingerprint)).catch(() => undefined);
  }, [active, fingerprint]);

  const shown = (entries ?? []).filter((entry) =>
    filter === "all" ? true : filter === "system" ? entry.document_id === "system" : entry.document_id === document?.id,
  );

  async function run(key: string, task: () => Promise<void>) {
    setBusy(key);
    try {
      await task();
    } catch (err) {
      notify("bad", "Export fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const stem = document?.filename.replace(/\.(pdf|xml)$/i, "") ?? "Beleg";
  const systemCount = (entries ?? []).filter((entry) => entry.document_id === "system").length;
  const docCount = document ? (entries ?? []).filter((entry) => entry.document_id === document.id).length : 0;

  return (
    <div className="space-y-4 2xl:space-y-5">
      <IntegrityStrip
        ledger={ledger}
        fingerprint={fingerprint}
        refreshing={refreshing}
        onRefresh={async () => {
          setRefreshing(true);
          await onRefreshLedger();
          await load();
          setRefreshing(false);
        }}
      />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px] 2xl:grid-cols-[minmax(0,1fr)_440px] 2xl:gap-5">
        <section className="card flex min-h-0 flex-col p-4" aria-label="Prüfprotokoll">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-fg">Prüfprotokoll · neueste zuerst</h2>
              <p className="text-xs text-subtle">Jeder Eintrag trägt den Hash seines Vorgängers; Prüfer- und Systemereignisse sind Ed25519-signiert.</p>
            </div>
            <PillTabs<Filter>
              size="sm"
              ariaLabel="Filter"
              value={filter}
              onChange={setFilter}
              items={[
                { key: "all", label: "Alle", badge: <span className="tabular-nums text-subtle">{entries?.length ?? 0}</span> },
                { key: "document", label: "Dieser Beleg", disabled: !document, badge: <span className="tabular-nums text-subtle">{docCount}</span> },
                { key: "system", label: "Systemereignisse", badge: <span className="tabular-nums text-subtle">{systemCount}</span> },
              ]}
            />
          </div>
          <div className="scroll-area h-[max(420px,calc(100vh-17rem))] rounded-lg border border-line pr-0">
            {error && <EmptyState icon={<Layers size={18} aria-hidden="true" />} title="Protokoll nicht abrufbar">{error}</EmptyState>}
            {!error && !entries && (
              <div className="space-y-2 p-3" aria-busy="true" aria-label="Protokoll wird geladen">
                {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-10 w-full" />)}
              </div>
            )}
            {!error && entries && shown.length === 0 && (
              <EmptyState icon={<Layers size={18} aria-hidden="true" />} title="Keine Einträge für diesen Filter">
                <p>Analysen, Siegel, Übersteuerungen, Modell- und Release-Wechsel erscheinen hier automatisch.</p>
              </EmptyState>
            )}
            {!error && entries && shown.length > 0 && <LedgerTable entries={shown} names={names} />}
          </div>
        </section>

        <aside className="space-y-4">
          <section className="card p-4" aria-label="Exporte">
            <h2 className="text-sm font-semibold text-fg">Exporte</h2>
            <p className="mt-0.5 truncate text-xs text-subtle" title={document?.filename}>
              {document ? document.filename : "Im Prüf-Workspace einen Beleg auswählen."}
            </p>
            <div className="mt-3 space-y-2">
              <button
                className="btn w-full justify-start"
                disabled={!document?.scorecard || busy !== null}
                onClick={() =>
                  document &&
                  run("zip", async () => {
                    const { blob, filename } = await api.gobdPackage(document.id);
                    downloadBlob(blob, filename ?? `Pruefdatenpaket_${stem}.zip`, "application/zip");
                    notify("ok", "Prüfdatenpaket exportiert", "Prüfen mit: python scripts/verify_pruefpaket.py <paket.zip> --fingerprint <Fingerabdruck>");
                  })
                }
              >
                {busy === "zip" ? <Spinner size={13} /> : <Package size={14} aria-hidden="true" />} GoBD-Prüfdatenpaket (ZIP)
              </button>
              <button
                className="btn w-full justify-start"
                disabled={!document || busy !== null}
                onClick={() =>
                  document &&
                  run("vd", async () => {
                    downloadBlob(await api.proceduralDoc(document.id), `Verfahrensdokumentation_${stem}.html`, "text/html;charset=utf-8");
                    notify("ok", "Verfahrensdokumentation erstellt", "Markierte Stellen ergänzt das Unternehmen vor der Freigabe.");
                  })
                }
              >
                {busy === "vd" ? <Spinner size={13} /> : <BookOpen size={14} aria-hidden="true" />} Verfahrensdokumentation (GoBD Rz. 153)
              </button>
              <button className="btn w-full justify-start" disabled={!document} onClick={onOpenExport}>
                <Download size={14} aria-hidden="true" /> Zertifikat, JSON, Memo &amp; Siegel …
              </button>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-subtle">
              Paket offline prüfen:{" "}
              <code className="rounded bg-surface-2 px-1 font-mono text-[12px] text-muted">python scripts/verify_pruefpaket.py paket.zip --fingerprint …</code>
            </p>
          </section>

          <section className="card p-4" aria-label="Regelwerk">
            <div className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-fg"><Scale size={14} className="text-subtle" aria-hidden="true" /> Regelwerk</h2>
              <span className="text-xs tabular-nums text-subtle">
                Score {rulesetVersion ?? "–"}{dlpRuleset ? ` · DLP ${dlpRuleset}` : ""}
              </span>
            </div>
            <ul className="mt-3 space-y-3">
              {RULES.map((rule) => (
                <li key={rule.title}>
                  <p className="text-xs font-semibold text-fg">{rule.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted">{rule.text}</p>
                </li>
              ))}
            </ul>
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-subtle">
              <Lock size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
              Der Score entsteht deterministisch aus versionierten Regeln, nie im Sprachmodell. Prüfer-Übersteuerungen ändern die
              Eingabe (Risikostufe), der Score wird neu berechnet. {document?.provider ? `Aktueller Beleg: ${providerLabel(document.provider)}.` : ""}
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
