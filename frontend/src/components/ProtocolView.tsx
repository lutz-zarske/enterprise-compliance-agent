"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { cx, formatDate, formatModel, providerLabel, TONE_TEXT, toneForScore } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { DocumentDetail, DocumentSummary, LedgerEntry, LedgerVerification } from "../types/api";
import { BookOpen, Download, Fingerprint, Layers, Lock, Package, RefreshCw, Scale, ShieldAlert, ShieldCheck } from "./icons";
import { Chip, EmptyState, HashBadge, PillTabs, Skeleton, Spinner, Tooltip } from "./ui";

type Filter = "all" | "document" | "system";

const MILESTONES = new Set(["sign_off", "human_override", "model_change", "release_update"]);

function IntegrityStrip({ ledger, fingerprint, onRefresh, refreshing }: {
  ledger: LedgerVerification | null;
  fingerprint: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const { tr } = useI18n();
  const state = !ledger ? "unknown" : !ledger.valid ? "broken" : ledger.entries === 0 ? "empty" : "ok";
  return (
    <section className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3" aria-label={tr("Integrität der Hash-Kette", "Hash chain integrity", "Integridad de la cadena de hash")}>
      <div className="flex items-center gap-2.5">
        <span className={cx("rounded-lg border p-2", state === "broken" ? "border-bad-line bg-bad-soft text-bad" : state === "ok" ? "border-ok-line bg-ok-soft text-ok" : "border-line bg-surface-2 text-subtle")}>
          {state === "broken" ? <ShieldAlert size={16} aria-hidden="true" /> : <ShieldCheck size={16} aria-hidden="true" />}
        </span>
        <div>
          <p className="text-sm font-semibold text-fg">
            {state === "ok"
              ? tr("Hash-Kette intakt · Ed25519 verifiziert", "Hash chain intact · Ed25519 verified", "Cadena intacta · Ed25519 verificado")
              : state === "broken"
                ? tr("Manipulation erkannt · Hash-Kette gebrochen", "Tampering detected · Hash chain broken", "Manipulación detectada · Cadena rota")
                : state === "empty"
                  ? tr("Ledger noch leer", "Ledger is still empty", "Registro aún vacío")
                  : tr("Ledger nicht geprüft", "Ledger unverified", "Registro no verificado")}
          </p>
          <p className="text-xs text-subtle">
            {ledger ? (
              <>
                <span className="tabular-nums">{ledger.entries}</span>{" "}
                {tr("Einträge nachgerechnet, davon", "entries recomputed,", "entradas recalculadas,")}{" "}
                <span className="tabular-nums">{ledger.signed_entries}</span>{" "}
                {tr("signiert · geprüft", "signed · verified", "firmadas · verificado")} {formatDate(ledger.verified_at, true)}
                {!ledger.valid && ledger.broken_at_seq != null && <> · {tr("Bruch bei #", "Broken at #", "Ruptura en #")}{ledger.broken_at_seq}</>}
              </>
            ) : (
              tr("Die Prüfung der Kette ist derzeit nicht erreichbar.", "Chain verification is currently unreachable.", "La verificación de la cadena no está disponible ahora.")
            )}
          </p>
        </div>
      </div>
      {ledger && ledger.entries > 0 && (
        <HashBadge
          value={ledger.head_hash}
          label={tr("Kopf-Hash", "Head hash", "Hash raíz")}
          verified={ledger.valid}
          verifiedLabel={tr("intakt", "intact", "intacto")}
        />
      )}
      {fingerprint && (
        <Tooltip
          content={tr(
            "Fingerabdruck des Ed25519-Systemschlüssels – in der Verfahrensdokumentation hinterlegen; damit prüft scripts/verify_pruefpaket.py die Herkunft eines Prüfpakets.",
            "Fingerprint of the Ed25519 system key – document this in your GoBD manual so scripts/verify_pruefpaket.py can verify audit packages offline.",
            "Huella de la clave Ed25519 del sistema – inclúyala en su manual GoBD para verificar paquetes con scripts/verify_pruefpaket.py.",
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            <Fingerprint size={13} className="text-subtle" aria-hidden="true" />
            <HashBadge value={fingerprint} label={tr("Schlüssel", "Key", "Clave")} />
          </span>
        </Tooltip>
      )}
      <button className="btn btn-sm ml-auto" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? <Spinner size={12} /> : <RefreshCw size={13} aria-hidden="true" />} {tr("Kette neu prüfen", "Re-verify chain", "Reverificar cadena")}
      </button>
    </section>
  );
}

function LedgerTable({ entries, names }: { entries: LedgerEntry[]; names: Map<string, string> }) {
  const { tr, td } = useI18n();
  const eventLabels: Record<string, string> = {
    analysis: tr("Analyse", "Analysis", "Análisis"),
    sign_off: tr("Prüfer-Siegel", "Auditor Seal", "Sello del auditor"),
    human_override: tr("Übersteuerung (Art. 14)", "Human Override (Art. 14)", "Anulación humana (Art. 14)"),
    provider_failover: tr("Stufenwechsel der KI-Kaskade", "AI Cascade Failover", "Cambio de nivel en cascada IA"),
    model_change: tr("Modellwechsel", "Model Change", "Cambio de modelo"),
    archive: tr("Archiviert", "Archived", "Archivado"),
    unarchive: tr("Aus dem Archiv geholt", "Unarchived", "Desarchivado"),
    release_update: tr("Release-Wechsel", "Release Update", "Actualización de versión"),
  };
  return (
    <table className="w-full border-separate border-spacing-0 text-left text-xs">
      <thead className="sticky top-0 z-10 bg-surface-solid">
        <tr className="text-subtle">
          <th scope="col" className="border-b border-line px-3 py-2 text-right font-medium">#</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">{tr("Zeitpunkt (UTC)", "Timestamp (UTC)", "Fecha (UTC)")}</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">{tr("Ereignis", "Event", "Evento")}</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">{tr("Beleg", "Document", "Documento")}</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">{tr("Zusammenfassung", "Summary", "Resumen")}</th>
          <th scope="col" className="border-b border-line px-3 py-2 text-right font-medium">Score</th>
          <th scope="col" className="border-b border-line px-3 py-2 font-medium">{tr("Eintrag", "Entry", "Entrada")}</th>
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
                <span className={cx("font-medium", milestone ? "text-fg" : "text-muted")}>{eventLabels[entry.event_type] ?? entry.event_type}</span>
                {entry.signature_status === "valid" && (
                  <span className="mt-1 block"><Chip tone="ok">{tr("Ed25519 gültig", "Ed25519 valid", "Ed25519 válido")}</Chip></span>
                )}
                {entry.signature_status === "invalid" && (
                  <span className="mt-1 block"><Chip tone="bad">{tr("Signatur ungültig", "Signature invalid", "Firma inválida")}</Chip></span>
                )}
              </td>
              <td className="max-w-[14rem] border-b border-line px-3 py-2 text-muted">
                <span className="block truncate" title={system ? tr("Systemereignis", "System event", "Evento del sistema") : names.get(entry.document_id) ?? entry.document_id}>
                  {system ? "System" : names.get(entry.document_id) ?? `${entry.document_id.slice(0, 8)}…`}
                </span>
                {entry.model_name && <span className="block truncate text-subtle">{formatModel(entry.model_name)}</span>}
              </td>
              <td className="border-b border-line px-3 py-2 text-muted [overflow-wrap:anywhere]">{td(entry.result_summary)}</td>
              <td className={cx("border-b border-line px-3 py-2 text-right font-medium tabular-nums", entry.compliance_score == null ? "text-subtle" : TONE_TEXT[toneForScore(entry.compliance_score)])}>{entry.compliance_score ?? "–"}</td>
              <td className="whitespace-nowrap border-b border-line px-3 py-2"><HashBadge value={entry.entry_hash} label="SHA-256" /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Ansicht „Protokoll“: die vollstaendige SHA-256-Hash-Kette (Prueferereignisse zusaetzlich
 * Ed25519-signiert) mit Systemereignissen, Exporte (GoBD-Paket, Verfahrensdokumentation)
 * und das Regelwerk.
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
  const { tr } = useI18n();
  const [filter, setFilter] = useState<Filter>("all");
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fingerprint, setFingerprint] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const names = useMemo(() => new Map(documents.map((doc) => [doc.id, doc.filename])), [documents]);

  const rules: { title: string; text: string }[] = [
    {
      title: "§ 14 Abs. 4 UStG · EN 16931",
      text: tr(
        "Pflichtangaben je Rechnung; bei hybriden E-Rechnungen ist der XML-Datensatz maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36).",
        "Mandatory invoice elements; for hybrid E-Invoices, the structured XML dataset takes precedence (German BMF decree 15 Oct 2024, para. 36).",
        "Requisitos obligatorios por factura; en facturas electrónicas híbridas prevalece el conjunto XML (circular BMF 15/10/2024, Rz. 36).",
      ),
    },
    {
      title: tr("EU AI Act – VO (EU) 2024/1689", "EU AI Act – Reg. (EU) 2024/1689", "Reglamento IA – Reg. (UE) 2024/1689"),
      text: tr(
        "Anhang-III-Eskalation (Art. 6 Abs. 2), automatisches Logging (Art. 12), menschliche Aufsicht und Übersteuerung (Art. 14 Abs. 4 lit. d); Pflichten ab 02.12.2027 (VO (EU) 2026/1744).",
        "Annex III escalation (Art. 6(2)), automatic logging (Art. 12), human oversight & override (Art. 14(4)(d)); obligations effective 02 Dec 2027 (Reg. (EU) 2026/1744).",
        "Escalada Anexo III (Art. 6(2)), registro automático (Art. 12), supervisión humana y anulación (Art. 14(4)(d)); obligaciones desde 02/12/2027.",
      ),
    },
    {
      title: tr("DSGVO Art. 4 Nr. 5, 9, 25, 32", "GDPR Art. 4(5), 9, 25, 32", "RGPD Art. 4(5), 9, 25, 32"),
      text: tr(
        "Pseudonymisierung im Backend vor jedem Cloud-Aufruf (Privacy Vault); Befunde ausschließlich maskiert gespeichert.",
        "Backend pseudonymization prior to every cloud call (Privacy Vault); findings stored strictly masked.",
        "Seudonimización en el backend antes de cualquier llamada en la nube (Privacy Vault); hallazgos almacenados enmascarados.",
      ),
    },
    {
      title: "GoBD · § 147 AO · BEG IV",
      text: tr(
        "SHA-256-hashverkettetes Prüfprotokoll, Prüfer-Einträge zusätzlich Ed25519-signiert; Buchungsbelege 8 Jahre, Verfahrensdokumentation und Handelsbücher 10 Jahre.",
        "SHA-256 hash-chained audit trail with Ed25519 auditor signatures; accounting vouchers retained 8 years, procedural docs and ledgers 10 years.",
        "Registro encadenado por SHA-256 con firmas Ed25519; justificantes 8 años, documentación y libros 10 años.",
      ),
    },
  ];

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
      notify("bad", tr("Export fehlgeschlagen", "Export failed", "Error al exportar"), err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const stem = document?.filename.replace(/\.(pdf|xml)$/i, "") ?? tr("Beleg", "Document", "Documento");
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
        <section className="card flex min-h-0 flex-col p-4" aria-label={tr("Prüfprotokoll", "Audit Trail", "Registro de auditoría")}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-fg">{tr("Prüfprotokoll · neueste zuerst", "Audit Trail · newest first", "Registro de auditoría · más recientes primero")}</h2>
              <p className="text-xs text-subtle">
                {tr(
                  "Jeder Eintrag trägt den Hash seines Vorgängers; Prüfer- und Steuerungsereignisse sind zusätzlich Ed25519-signiert.",
                  "Each entry carries its predecessor's hash; auditor and governance actions carry Ed25519 signatures.",
                  "Cada entrada incluye el hash de su predecesora; las acciones de auditoría llevan firma Ed25519.",
                )}
              </p>
            </div>
            <PillTabs<Filter>
              size="sm"
              ariaLabel="Filter"
              value={filter}
              onChange={setFilter}
              items={[
                { key: "all", label: tr("Alle", "All", "Todos"), badge: <span className="tabular-nums text-subtle">{entries?.length ?? 0}</span> },
                { key: "document", label: tr("Dieser Beleg", "This document", "Este documento"), disabled: !document, badge: <span className="tabular-nums text-subtle">{docCount}</span> },
                { key: "system", label: tr("Systemereignisse", "System events", "Eventos del sistema"), badge: <span className="tabular-nums text-subtle">{systemCount}</span> },
              ]}
            />
          </div>
          <div className="scroll-area h-[max(420px,calc(100vh-17rem))] rounded-lg border border-line pr-0">
            {error && <EmptyState icon={<Layers size={18} aria-hidden="true" />} title={tr("Protokoll nicht abrufbar", "Audit trail unavailable", "Registro no disponible")}>{error}</EmptyState>}
            {!error && !entries && (
              <div className="space-y-2 p-3" aria-busy="true" aria-label={tr("Protokoll wird geladen", "Loading audit trail", "Cargando registro")}>
                {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-10 w-full" />)}
              </div>
            )}
            {!error && entries && shown.length === 0 && (
              <EmptyState icon={<Layers size={18} aria-hidden="true" />} title={tr("Keine Einträge für diesen Filter", "No entries matching filter", "Sin entradas para este filtro")}>
                <p>{tr("Analysen, Siegel, Übersteuerungen, Modell- und Release-Wechsel erscheinen hier automatisch.", "Analyses, seals, overrides, model changes and release updates appear here automatically.", "Análisis, sellos, anulaciones y cambios de modelo o versión aparecen aquí automáticamente.")}</p>
              </EmptyState>
            )}
            {!error && entries && shown.length > 0 && <LedgerTable entries={shown} names={names} />}
          </div>
        </section>

        <aside className="space-y-4">
          <section className="card p-4" aria-label={tr("Exporte", "Exports", "Exportaciones")}>
            <h2 className="text-sm font-semibold text-fg">{tr("Exporte", "Exports", "Exportaciones")}</h2>
            <p className="mt-0.5 truncate text-xs text-subtle" title={document?.filename}>
              {document ? document.filename : tr("Unter „Prüfung“ einen Beleg auswählen.", "Select a document under “Audit”.", "Selecciona un documento en «Auditoría».")}
            </p>
            <div className="mt-3 space-y-2">
              <button
                className="btn w-full justify-start"
                disabled={!document?.scorecard || busy !== null}
                onClick={() =>
                  document &&
                  run("zip", async () => {
                    const { blob, filename } = await api.gobdPackage(document.id);
                    downloadBlob(
                      blob,
                      filename ?? tr(`Pruefdatenpaket_${stem}.zip`, `AuditDataPackage_${stem}.zip`, `PaqueteAuditoria_${stem}.zip`),
                      "application/zip",
                    );
                    notify(
                      "ok",
                      tr("Prüfdatenpaket exportiert", "Audit data package exported", "Paquete de auditoría exportado"),
                      tr("Prüfen mit: python scripts/verify_pruefpaket.py <paket.zip> --fingerprint <Fingerabdruck>", "Verify with: python scripts/verify_pruefpaket.py <package.zip> --fingerprint <fingerprint>", "Verificar con: python scripts/verify_pruefpaket.py <paquete.zip> --fingerprint <huella>"),
                    );
                  })
                }
              >
                {busy === "zip" ? <Spinner size={13} /> : <Package size={14} aria-hidden="true" />} {tr("GoBD-Prüfdatenpaket (ZIP)", "GoBD Audit Package (ZIP)", "Paquete de auditoría GoBD (ZIP)")}
              </button>
              <button
                className="btn w-full justify-start"
                disabled={!document || busy !== null}
                onClick={() =>
                  document &&
                  run("vd", async () => {
                    downloadBlob(
                      await api.proceduralDoc(document.id),
                      tr(`Verfahrensdokumentation_${stem}.html`, `ProceduralDocumentation_${stem}.html`, `DocumentacionProcedimientos_${stem}.html`),
                      "text/html;charset=utf-8",
                    );
                    notify("ok", tr("Verfahrensdokumentation erstellt", "Procedural documentation created", "Documentación de procedimientos creada"), tr("Markierte Stellen ergänzt das Unternehmen vor der Freigabe.", "Fill in marked placeholders prior to sign-off.", "Complete los marcadores antes de la aprobación."));
                  })
                }
              >
                {busy === "vd" ? <Spinner size={13} /> : <BookOpen size={14} aria-hidden="true" />} {tr("Verfahrensdokumentation (GoBD Rz. 153)", "Procedural Docs (GoBD Rz. 153)", "Documentación (GoBD Rz. 153)")}
              </button>
              <button className="btn w-full justify-start" disabled={!document} onClick={onOpenExport}>
                <Download size={14} aria-hidden="true" /> {tr("Zertifikat, JSON, Memo & Siegel …", "Certificate, JSON, Memo & Seal …", "Certificado, JSON, Memo y Sello …")}
              </button>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-subtle">
              {tr("Paket offline prüfen:", "Verify package offline:", "Verificar paquete sin conexión:")}{" "}
              <code className="rounded bg-surface-2 px-1 font-mono text-xs text-muted">python scripts/verify_pruefpaket.py paket.zip --fingerprint …</code>
            </p>
          </section>

          <section className="card p-4" aria-label={tr("Regelwerk", "Ruleset", "Reglamento")}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-fg"><Scale size={14} className="text-subtle" aria-hidden="true" /> {tr("Regelwerk", "Ruleset", "Reglamento")}</h2>
              <span className="text-xs tabular-nums text-subtle">
                Score {rulesetVersion ?? "–"}{dlpRuleset ? ` · DLP ${dlpRuleset}` : ""}
              </span>
            </div>
            <ul className="mt-3 space-y-3">
              {rules.map((rule) => (
                <li key={rule.title}>
                  <p className="text-xs font-semibold text-fg">{rule.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-muted">{rule.text}</p>
                </li>
              ))}
            </ul>
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-subtle">
              <Lock size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
              {tr(
                "Der Score entsteht deterministisch aus versionierten Regeln, nie im Sprachmodell. Prüfer-Übersteuerungen ändern die Eingabe (Risikostufe), der Score wird neu berechnet.",
                "The score is produced deterministically by versioned rules, never by the language model. Auditor overrides modify the risk tier input and trigger deterministic recalculation.",
                "La puntuación se calcula de forma determinista mediante reglas versionadas, nunca en el modelo. Las anulaciones recalculan la puntuación.",
              )}
              {document?.provider ? ` ${tr("Aktueller Beleg:", "Current record:", "Documento actual:")} ${providerLabel(document.provider)}.` : ""}
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
