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

/**
 * Druckt HTML über ein unsichtbares iframe - funktioniert auch mit X-API-Key. Der Titel des
 * Berichts (Pruefzertifikat_Beleg_Datum) wird kurz zum Seitentitel: Chrome schlägt ihn beim
 * „Als PDF speichern“ als Dateinamen vor.
 */
function printHtml(html: string) {
  const frame = window.document.createElement("iframe");
  frame.style.position = "fixed";
  frame.style.width = "0";
  frame.style.height = "0";
  frame.style.border = "0";
  frame.setAttribute("aria-hidden", "true");
  frame.srcdoc = html;
  frame.onload = () => {
    const previous = window.document.title;
    const restore = () => {
      window.document.title = previous;
    };
    window.document.title = frame.contentDocument?.title || previous;
    frame.contentWindow?.addEventListener("afterprint", restore, { once: true });
    frame.contentWindow?.focus();
    frame.contentWindow?.print();
    window.setTimeout(restore, 1_000);
    window.setTimeout(() => frame.remove(), 60_000);
  };
  window.document.body.appendChild(frame);
}

function Option({ icon, title, text, action, busy, onClick, disabled, secondary }: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action: string;
  busy: boolean;
  disabled?: boolean;
  onClick: () => void;
  /** Zweites Format (z. B. HTML neben Word). */
  secondary?: { action: string; busy: boolean; onClick: () => void };
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line p-3">
      <div className="rounded-lg border border-line bg-surface-2 p-2 text-accent">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-fg">{title}</p>
        <p className="text-xs text-subtle">{text}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        {secondary && (
          <button className="btn" onClick={secondary.onClick} disabled={busy || secondary.busy || disabled}>
            {secondary.busy ? <Spinner size={13} /> : null}
            {secondary.action}
          </button>
        )}
        <button className="btn" onClick={onClick} disabled={busy || Boolean(secondary?.busy) || disabled}>
          {busy ? <Spinner size={13} /> : null}
          {action}
        </button>
      </div>
    </div>
  );
}

export function ExportModal({ document, open, onClose, onSealed, notify }: Props) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);

  if (!document) return null;
  const analyzed = Boolean(document.scorecard);
  const stem = document.filename.replace(/\.(pdf|xml)$/i, "");

  async function downloadProcedural(format: "html" | "docx") {
    if (!document) return;
    const { blob, filename } = await api.proceduralDoc(document.id, format);
    const prefix = tr("Verfahrensdokumentation", "ProceduralDocumentation", "DocumentacionProcedimientos");
    downloadBlob(blob, filename ?? `${prefix}_${stem}.${format}`, blob.type);
    notify(
      "ok",
      tr("Verfahrensdokumentation erstellt", "Procedural documentation created", "Documentación creada"),
      format === "docx"
        ? tr("Gelb markierte Stellen in Word ergänzen, dann freigeben.", "Fill in the yellow placeholders in Word, then sign off.", "Complete en Word los campos marcados en amarillo y apruébela.")
        : tr("Zum Ergänzen der markierten Stellen den Word-Export verwenden.", "Use the Word export to fill in the marked placeholders.", "Para completar los campos marcados, use la exportación a Word."),
    );
  }

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
          title={tr("Prüfzertifikat drucken oder als PDF speichern", "Print certificate or save as PDF", "Imprimir certificado o guardar como PDF")}
          text={tr(
            "Seite 1 mit Ergebnis und Siegel, danach alle Prüfpunkte und der Prüfpfad – im Druckdialog „Als PDF speichern“ wählen.",
            "Page 1 shows the result and seal, followed by every check and the audit trail – choose “Save as PDF” in the print dialog.",
            "La página 1 muestra el resultado y el sello; después, todas las comprobaciones y la pista de auditoría. Elija «Guardar como PDF».",
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
              const { blob, filename } = await api.reportJson(document.id);
              downloadBlob(
                blob,
                filename ?? tr(`Pruefzertifikat_${stem}.json`, `AuditCertificate_${stem}.json`, `CertificadoAuditoria_${stem}.json`),
                "application/json",
              );
            })
          }
        />
        <Option
          icon={<BookOpen size={16} />}
          title={tr("GoBD-Verfahrensdokumentation", "GoBD Procedural Documentation", "Documentación de procedimientos GoBD")}
          text={tr(
            "Vier Säulen nach GoBD Rz. 153 mit Prüfpfad dieses Belegs. In Word die gelb markierten Stellen ergänzen; aufzubewahren 10 Jahre (§ 147 Abs. 1 Nr. 1 AO).",
            "Four pillars per GoBD Rz. 153 with this document’s audit trail. Fill in the yellow placeholders in Word; retain 10 years (§ 147(1) No. 1 AO).",
            "Cuatro pilares según GoBD Rz. 153 con la pista de este documento. Complete en Word los campos amarillos; conservar 10 años (§ 147(1) n.º 1 AO).",
          )}
          action="Word"
          busy={busy === "vd"}
          onClick={() => run("vd", () => downloadProcedural("docx"))}
          secondary={{ action: "HTML", busy: busy === "vd-html", onClick: () => void run("vd-html", () => downloadProcedural("html")) }}
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
