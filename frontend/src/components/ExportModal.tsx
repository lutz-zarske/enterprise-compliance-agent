"use client";

import React, { useEffect, useState } from "react";
import { api, ApiError, downloadBlob } from "../lib/api";
import type { DocumentDetail, SignOffDecision } from "../types/api";
import { cx, formatDate } from "../lib/format";
import { BookOpen, Check, Copy, Download, Package, Printer, Stamp } from "./icons";
import { HashBadge, Modal, Spinner } from "./ui";

const AUDITOR_STORAGE = "eca-auditor-name";

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
  const [auditor, setAuditor] = useState("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<SignOffDecision>("SEALED_APPROVED");

  useEffect(() => {
    if (!open) return;
    try {
      setAuditor(window.localStorage.getItem(AUDITOR_STORAGE) ?? "");
    } catch {
      /* ignorieren */
    }
    setNote("");
    setDecision(document?.scorecard?.release_blocked ? "SEALED_REJECTED" : "SEALED_APPROVED");
  }, [open, document?.id, document?.scorecard?.release_blocked]);

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

  const seal = document.sign_off;

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
        <div className="mb-3 flex items-center gap-2">
          <Stamp size={16} className="text-accent" />
          <p className="text-sm font-semibold text-fg">Auditor Sign-Off & Siegel</p>
          <span className="font-mono text-[11px] text-subtle">Human Oversight · Art. 14 EU AI Act</span>
        </div>
        {seal && (
          <div
            className={cx(
              "mb-3 rounded-lg border p-3 text-xs",
              seal.status === "SEALED_APPROVED" ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad",
            )}
          >
            <p className="font-semibold">
              {seal.status === "SEALED_APPROVED" ? "Freigegeben" : "Freigabe verweigert"} durch {seal.auditor_name} am {formatDate(seal.sealed_at, true)}
            </p>
            <HashBadge className="mt-2" value={seal.ledger_entry_hash} label="Siegel" verified verifiedLabel="Ed25519-signiert" />
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="label-caps">Name der Prüfperson</span>
            <input
              className="input mt-1"
              name="auditor-name"
              autoComplete="name"
              value={auditor}
              onChange={(e) => setAuditor(e.target.value)}
              placeholder="z. B. Lutz Zarske…"
            />
          </label>
          <div>
            <span className="label-caps">Entscheidung</span>
            <div className="mt-1 flex gap-2">
              {(["SEALED_APPROVED", "SEALED_REJECTED"] as const).map((value) => (
                <button
                  key={value}
                  onClick={() => setDecision(value)}
                  className={cx(
                    "btn flex-1",
                    decision === value && (value === "SEALED_APPROVED" ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad"),
                  )}
                >
                  {decision === value && <Check size={13} />}
                  {value === "SEALED_APPROVED" ? "Freigeben" : "Ablehnen"}
                </button>
              ))}
            </div>
          </div>
        </div>
        <label className="mt-3 block">
          <span className="label-caps">Prüfungsnotiz</span>
          <textarea
            className="input mt-1 min-h-[70px]"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            name="audit-note"
            placeholder="z. B. USt-IdNr. beim Lieferanten nachgefordert…"
          />
        </label>
        <p className="mt-2 text-[11px] text-subtle">
          Das Siegel wird als eigener Eintrag in die Hash-Kette geschrieben. Eine erneute Analyse hebt es auf; die Historie bleibt erhalten.
        </p>
        <div className="mt-3 flex justify-end">
          <button
            className="btn btn-primary"
            disabled={!analyzed || auditor.trim().length < 2 || busy === "seal"}
            onClick={() =>
              run("seal", async () => {
                const updated = await api.signOff(document.id, auditor.trim(), note.trim(), decision);
                try {
                  window.localStorage.setItem(AUDITOR_STORAGE, auditor.trim());
                } catch {
                  /* ignorieren */
                }
                onSealed(updated);
                notify("ok", "Prüfung versiegelt", `${auditor.trim()} · Ledger-Eintrag geschrieben`);
              })
            }
          >
            {busy === "seal" ? <Spinner size={13} /> : <Stamp size={14} />}
            Digital versiegeln
          </button>
        </div>
      </div>
    </Modal>
  );
}
