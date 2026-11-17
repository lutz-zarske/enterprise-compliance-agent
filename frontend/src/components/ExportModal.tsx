"use client";

import React, { useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { DocumentDetail } from "../types/api";
import { BookOpen, Copy, Download, Package, Printer, Stamp } from "./icons";
import { SignOffPanel } from "./SignOffPanel";
import { Modal, Spinner } from "./ui";

interface Props {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  onSealed: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad" | "info", title: string, message?: string) => void;
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
  const { tr } = useI18n();
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
      notify("bad", tr("Export fehlgeschlagen", "Export failed", "Error al exportar"), error.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={tr("Export-Center & Prüfvermerk", "Export Center & Audit Seal", "Centro de exportación y sello de auditoría")}
      subtitle={document.filename}
    >
      {!analyzed && (
        <p className="mb-3 rounded-lg border border-warn-line bg-warn-soft p-3 text-xs text-warn">
          {tr(
            "Das Dokument ist noch nicht analysiert. Bericht und Siegel stehen nach dem Audit zur Verfügung.",
            "The document has not been analyzed yet. Report and seal are available after the audit.",
            "El documento aún no ha sido analizado. El informe y el sello estarán disponibles tras la auditoría.",
          )}
        </p>
      )}
      <div className="space-y-2">
        <Option
          icon={<Package size={16} />}
          title={tr("GoBD-Prüfdatenpaket exportieren (ZIP)", "Export GoBD Audit Data Package (ZIP)", "Exportar paquete de auditoría GoBD (ZIP)")}
          text={tr(
            `Originalbeleg${document.einvoice && !document.einvoice.error ? ", XML-Datensatz" : ""}, Ledger-Auszug, A4-Zertifikat und Manifest mit SHA-256 und Ed25519-Systemsignatur.`,
            `Original document${document.einvoice && !document.einvoice.error ? ", XML dataset" : ""}, ledger excerpt, A4 certificate and manifest with SHA-256 and Ed25519 system signature.`,
            `Documento original${document.einvoice && !document.einvoice.error ? ", conjunto XML" : ""}, extracto del registro, certificado A4 y manifiesto con SHA-256 y firma Ed25519.`,
          )}
          action="ZIP"
          busy={busy === "zip"}
          disabled={!analyzed}
          onClick={() =>
            run("zip", async () => {
              const { blob, filename } = await api.gobdPackage(document.id);
              downloadBlob(
                blob,
                filename ?? tr(`Pruefdatenpaket_${stem}.zip`, `AuditDataPackage_${stem}.zip`, `PaqueteAuditoria_${stem}.zip`),
                "application/zip",
              );
              notify(
                "info",
                tr(
                  "Verfahrensdokumentation & Prüfbericht erfolgreich als ZIP exportiert",
                  "Procedural documentation & audit report exported as ZIP",
                  "Documentación de procedimientos e informe exportados en ZIP",
                ),
                tr(
                  "Prüfen mit: python scripts/verify_pruefpaket.py <paket.zip>",
                  "Verify with: python scripts/verify_pruefpaket.py <package.zip>",
                  "Verificar con: python scripts/verify_pruefpaket.py <paquete.zip>",
                ),
              );
            })
          }
        />
        <Option
          icon={<Printer size={16} />}
          title={tr("Compliance-Zertifikat drucken (PDF)", "Print Compliance Certificate (PDF)", "Imprimir certificado de cumplimiento (PDF)")}
          text={tr(
            "A4-Prüfzertifikat mit SHA-256, Ledger-Hash, § 14-Matrix und Siegel – im Druckdialog „Als PDF speichern“.",
            "A4 audit certificate with SHA-256, ledger hash, Sec. 14 matrix and seal – choose 'Save as PDF' in print dialog.",
            "Certificado A4 con SHA-256, hash de registro, matriz § 14 y sello – elija 'Guardar como PDF' al imprimir.",
          )}
          action={tr("Drucken", "Print", "Imprimir")}
          busy={busy === "print"}
          disabled={!analyzed}
          onClick={() => run("print", async () => printHtml(await api.reportHtml(document.id)))}
        />
        <Option
          icon={<Download size={16} />}
          title={tr("Audit-JSON herunterladen", "Download Audit JSON", "Descargar JSON de auditoría")}
          text={tr(
            "Maschinenlesbarer Bericht inkl. Ledger-Historie für SAP/ERP-Archivierung.",
            "Machine-readable report including ledger history for SAP/ERP archiving.",
            "Informe legible por máquina con historial de registro para archivo SAP/ERP.",
          )}
          action="JSON"
          busy={busy === "json"}
          disabled={!analyzed}
          onClick={() =>
            run("json", async () => {
              const report = await api.reportJson(document.id);
              downloadBlob(
                JSON.stringify(report, null, 2),
                tr(`Pruefzertifikat_${stem}.json`, `AuditCertificate_${stem}.json`, `CertificadoAuditoria_${stem}.json`),
                "application/json",
              );
            })
          }
        />
        <Option
          icon={<BookOpen size={16} />}
          title={tr("GoBD-Verfahrensdokumentation", "GoBD Procedural Documentation", "Documentación de procedimientos GoBD")}
          text={tr(
            "Vier Säulen nach GoBD Rz. 153 mit Prüfpfad dieses Belegs. Entwurf zum Ergänzen; aufzubewahren 10 Jahre (§ 147 Abs. 1 Nr. 1 AO).",
            "Four pillars per GoBD Rz. 153 with audit trail for this document. Draft to complete; retain 10 years (§ 147(1) No. 1 AO).",
            "Cuatro pilares según GoBD Rz. 153 con pista de auditoría de este documento. Borrador; conservar 10 años (§ 147(1) n.º 1 AO).",
          )}
          action="HTML"
          busy={busy === "vd"}
          onClick={() =>
            run("vd", async () => {
              downloadBlob(
                await api.proceduralDoc(document.id),
                tr(`Verfahrensdokumentation_${stem}.html`, `ProceduralDocumentation_${stem}.html`, `DocumentacionProcedimientos_${stem}.html`),
                "text/html;charset=utf-8",
              );
              notify(
                "ok",
                tr("Verfahrensdokumentation erstellt", "Procedural documentation created", "Documentación creada"),
                tr(
                  "Markierte Stellen ergänzt das Unternehmen vor der Freigabe.",
                  "Complete marked placeholders prior to sign-off.",
                  "Complete los campos marcados antes de la aprobación.",
                ),
              );
            })
          }
        />
        <Option
          icon={<Copy size={16} />}
          title={tr("Compliance-Memo kopieren", "Copy Compliance Memo", "Copiar memorando de cumplimiento")}
          text={tr(
            "Formatierter Markdown-Text für E-Mails an Lieferanten oder die Buchhaltung.",
            "Formatted Markdown text for emails to suppliers or accounting.",
            "Texto Markdown formateado para correos a proveedores o contabilidad.",
          )}
          action={tr("Kopieren", "Copy", "Copiar")}
          busy={busy === "md"}
          disabled={!analyzed}
          onClick={() =>
            run("md", async () => {
              await navigator.clipboard.writeText(await api.reportMarkdown(document.id));
              notify("ok", tr("Memo in die Zwischenablage kopiert", "Memo copied to clipboard", "Memorando copiado al portapapeles"));
            })
          }
        />
      </div>

      <div className="mt-5 rounded-lg border border-line p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Stamp size={16} className="text-accent" aria-hidden="true" />
          <p className="text-sm font-semibold text-fg">{tr("Auditor Sign-Off & Siegel", "Auditor Sign-Off & Seal", "Aprobación y sello del auditor")}</p>
          <span className="text-xs tabular-nums text-subtle">Human Oversight · Art. 14 EU AI Act</span>
        </div>
        <SignOffPanel document={document} shortcutActive={open} notify={notify} onSealed={onSealed} />
      </div>
    </Modal>
  );
}
