"use client";

import React, { useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import type { DocumentDetail } from "../types/api";
import { BookOpen, Copy, Download, Package, Printer, Stamp } from "./icons";
import { SignOffPanel } from "./SignOffPanel";
import { Modal, Spinner } from "./ui";

interface Props {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  onSealed: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad", title: string, message?: string) => void;
}

/** Druckt HTML ueber ein unsichtbares iframe - funktioniert auch mit X-API-Key. */
function printHtml(html: string) {
  const frame = window.document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.border = "0";
  frame.setAttribute("aria-hidden", "true");
  frame.srcdoc = html;
  frame.onload = () => {
    frame.contentWindow?.focus();
    frame.contentWindow?.print();
    window.setTimeout(() => frame.remove(), 60_000);
  };
  window.document.body.appendChild(frame);
}

function Option({ icon, title, text, action, busy, onClick, disabled }: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action: string;
  busy: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line p-3">
      <div className="rounded-lg border border-line bg-surface-2 p-2 text-accent">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-fg">{title}</p>
        <p className="text-xs text-subtle">{text}</p>
      </div>
      <button className="btn" onClick={onClick} disabled={busy || disabled}>
        {busy ? <Spinner size={13} /> : null}
        {action}
      </button>
    </div>
  );
}

export function ExportModal({ document, open, onClose, onSealed, notify }: Props) {
  const [busy, setBusy] = useState<string | null>(null);

  if (!document) return null;
  const analyzed = Boolean(document.scorecard);
  const stem = document.filename.replace(/\.(pdf|xml)$/i, "");

  async function run(key: string, task: () => Promise<void>) {
    setBusy(key);
    try {
      await task();
    } catch (err) {
      const error = err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown");
      notify("bad", "Export fehlgeschlagen", error.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Export-Center & Prüfvermerk" subtitle={document.filename}>
      {!analyzed && (
        <p className="mb-3 rounded-lg border border-warn-line bg-warn-soft p-3 text-xs text-warn">
          Das Dokument ist noch nicht analysiert. Bericht und Siegel stehen nach dem Audit zur Verfügung.
        </p>
      )}
      <div className="space-y-2">
        <Option
          icon={<Package size={16} />}
          title="GoBD-Prüfdatenpaket exportieren (ZIP)"
          text={`Originalbeleg${document.einvoice && !document.einvoice.error ? ", XML-Datensatz" : ""}, Ledger-Auszug, A4-Zertifikat und Manifest mit SHA-256 und Ed25519-Systemsignatur.`}
          action="ZIP"
          busy={busy === "zip"}
          disabled={!analyzed}
          onClick={() =>
            run("zip", async () => {
              const { blob, filename } = await api.gobdPackage(document.id);
              downloadBlob(blob, filename ?? `Pruefdatenpaket_${stem}.zip`, "application/zip");
              notify("ok", "Prüfdatenpaket erstellt", "Prüfen mit: python scripts/verify_pruefpaket.py <paket.zip>");
            })
          }
        />
        <Option
          icon={<Printer size={16} />}
          title="Compliance-Zertifikat drucken (PDF)"
          text="A4-Prüfzertifikat mit SHA-256, Ledger-Hash, § 14-Matrix und Siegel – im Druckdialog „Als PDF speichern“."
          action="Drucken"
          busy={busy === "print"}
          disabled={!analyzed}
          onClick={() => run("print", async () => printHtml(await api.reportHtml(document.id)))}
        />
        <Option
          icon={<Download size={16} />}
          title="Audit-JSON herunterladen"
          text="Maschinenlesbarer Bericht inkl. Ledger-Historie für SAP/ERP-Archivierung."
          action="JSON"
          busy={busy === "json"}
          disabled={!analyzed}
          onClick={() =>
            run("json", async () => {
              const report = await api.reportJson(document.id);
              downloadBlob(JSON.stringify(report, null, 2), `Pruefzertifikat_${stem}.json`, "application/json");
            })
          }
        />
        <Option
          icon={<BookOpen size={16} />}
          title="GoBD-Verfahrensdokumentation"
          text="Vier Säulen nach GoBD Rz. 153 mit Prüfpfad dieses Belegs. Entwurf zum Ergänzen; aufzubewahren 10 Jahre (§ 147 Abs. 1 Nr. 1 AO)."
          action="HTML"
          busy={busy === "vd"}
          onClick={() =>
            run("vd", async () => {
              downloadBlob(await api.proceduralDoc(document.id), `Verfahrensdokumentation_${stem}.html`, "text/html;charset=utf-8");
              notify("ok", "Verfahrensdokumentation erstellt", "Markierte Stellen ergänzt das Unternehmen vor der Freigabe.");
            })
          }
        />
        <Option
          icon={<Copy size={16} />}
          title="Compliance-Memo kopieren"
          text="Formatierter Markdown-Text für E-Mails an Lieferanten oder die Buchhaltung."
          action="Kopieren"
          busy={busy === "md"}
          disabled={!analyzed}
          onClick={() =>
            run("md", async () => {
              await navigator.clipboard.writeText(await api.reportMarkdown(document.id));
              notify("ok", "Memo in die Zwischenablage kopiert");
            })
          }
        />
      </div>

      <div className="mt-5 rounded-lg border border-line p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Stamp size={16} className="text-accent" aria-hidden="true" />
          <p className="text-sm font-semibold text-fg">Auditor Sign-Off & Siegel</p>
          <span className="font-mono text-xs text-subtle">Human Oversight · Art. 14 EU AI Act</span>
        </div>
        <SignOffPanel document={document} shortcutActive={open} notify={notify} onSealed={onSealed} />
      </div>
    </Modal>
  );
}
