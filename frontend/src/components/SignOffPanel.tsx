"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { DocumentDetail, SignOffDecision } from "../types/api";
import { cx, formatDate, TONE_TEXT, verdictTone } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { Check, Stamp } from "./icons";
import { AutoTextarea, HashBadge, isModEnter, Kbd, Modal, Spinner, useModifierLabel } from "./ui";

const AUDITOR_STORAGE = "eca-auditor-name";

interface PanelProps {
  document: DocumentDetail;
  onSealed: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad", title: string, message?: string) => void;
  /** Strg/⌘ + Enter versiegelt (nur solange der umgebende Dialog offen ist). */
  shortcutActive: boolean;
  /** Fokus beim Öffnen: ins Namensfeld, falls noch kein Name bekannt ist. */
  autoFocus?: boolean;
}

/**
 * Auditor Sign-Off (Art. 14 AI Act): Name, Entscheidung und Notiz werden als
 * Ed25519-signierter Eintrag in die Hash-Kette geschrieben.
 */
export function SignOffPanel({ document, onSealed, notify, shortcutActive, autoFocus }: PanelProps) {
  const { tr } = useI18n();
  const [auditor, setAuditor] = useState("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<SignOffDecision>("SEALED_APPROVED");
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const mod = useModifierLabel();
  const blocked = Boolean(document.scorecard?.release_blocked);
  const analyzed = Boolean(document.scorecard);

  useEffect(() => {
    let stored = "";
    try {
      stored = window.localStorage.getItem(AUDITOR_STORAGE) ?? "";
    } catch {
      /* ignorieren */
    }
    setAuditor(stored);
    setNote("");
    setDecision(blocked ? "SEALED_REJECTED" : "SEALED_APPROVED");
    if (autoFocus && !stored) nameRef.current?.focus();
  }, [document.id, blocked, autoFocus]);

  const ready = analyzed && auditor.trim().length >= 2 && !busy;

  const seal = useCallback(async () => {
    if (!ready) return;
    setBusy(true);
    try {
      const updated = await api.signOff(document.id, auditor.trim(), note.trim(), decision);
      try {
        window.localStorage.setItem(AUDITOR_STORAGE, auditor.trim());
      } catch {
        /* ignorieren */
      }
      onSealed(updated);
      const reference = updated.extraction?.document_number ?? updated.filename;
      notify(
        "ok",
        tr(
          `Dokument ${reference} erfolgreich Ed25519-versiegelt & im Ledger verankert`,
          `Document ${reference} Ed25519-sealed & anchored in ledger`,
          `Documento ${reference} sellado con Ed25519 y anclado en el registro`,
        ),
        tr(
          `${decision === "SEALED_APPROVED" ? "Freigabe" : "Ablehnung"} durch ${auditor.trim()}`,
          `${decision === "SEALED_APPROVED" ? "Approved" : "Rejected"} by ${auditor.trim()}`,
          `${decision === "SEALED_APPROVED" ? "Aprobado" : "Rechazado"} por ${auditor.trim()}`,
        ),
      );
    } catch (err) {
      notify("bad", tr("Siegel fehlgeschlagen", "Seal failed", "Error al sellar"), err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [ready, document.id, auditor, note, decision, onSealed, notify, tr]);

  useEffect(() => {
    if (!shortcutActive) return;
    const onKey = (event: KeyboardEvent) => {
      if (!isModEnter(event)) return;
      event.preventDefault();
      void seal();
    };
    window.document.addEventListener("keydown", onKey);
    return () => window.document.removeEventListener("keydown", onKey);
  }, [shortcutActive, seal]);

  const existing = document.sign_off;

  return (
    <div>
      {existing && (
        <div
          className={cx(
            "mb-3 rounded-lg border p-3 text-xs",
            existing.status === "SEALED_APPROVED" ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad",
          )}
        >
          <p className="font-semibold">
            {existing.status === "SEALED_APPROVED"
              ? tr("Freigegeben", "Approved", "Aprobado")
              : tr("Freigabe verweigert", "Approval denied", "Aprobación denegada")}{" "}
            {tr("durch", "by", "por")} {existing.auditor_name} {tr("am", "on", "el")}{" "}
            <span className="tabular-nums">{formatDate(existing.sealed_at, true)}</span>
          </p>
          <HashBadge
            className="mt-2"
            value={existing.ledger_entry_hash}
            label={tr("Siegel", "Seal", "Sello")}
            verified
            verifiedLabel={tr("Ed25519-signiert", "Ed25519-signed", "Firmado con Ed25519")}
          />
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="label-caps">{tr("Name der Prüfperson", "Auditor Name", "Nombre del auditor")}</span>
          <input
            ref={nameRef}
            className="input mt-1"
            name="auditor-name"
            autoComplete="name"
            value={auditor}
            onChange={(e) => setAuditor(e.target.value)}
            placeholder={tr("Prüferkürzel oder Name eingeben…", "Enter auditor initials or name…", "Introducir iniciales o nombre…")}
          />
        </label>
        <div>
          <span className="label-caps">{tr("Entscheidung", "Decision", "Decisión")}</span>
          <div className="mt-1 flex gap-2" role="radiogroup" aria-label={tr("Entscheidung", "Decision", "Decisión")}>
            {(["SEALED_APPROVED", "SEALED_REJECTED"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={decision === value}
                onClick={() => setDecision(value)}
                className={cx(
                  "btn flex-1",
                  decision === value && (value === "SEALED_APPROVED" ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad"),
                )}
              >
                {decision === value && <Check size={13} aria-hidden="true" />}
                {value === "SEALED_APPROVED" ? tr("Freigeben", "Approve", "Aprobar") : tr("Ablehnen", "Reject", "Rechazar")}
              </button>
            ))}
          </div>
        </div>
      </div>
      {blocked && decision === "SEALED_APPROVED" && (
        <p className="mt-2 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-xs leading-relaxed text-warn">
          {tr(
            "Freigabe entgegen der Sperrempfehlung des Regelwerks – die Begründung gehört in die Prüfungsnotiz.",
            "Approval overrides the rule engine's block recommendation – enter justification in the audit note.",
            "Aprobación contraria al bloqueo recomendado por el reglamento; justifíquelo en la nota.",
          )}
        </p>
      )}
      <label className="mt-3 block">
        <span className="label-caps">{tr("Prüfungsnotiz", "Audit Note", "Nota de auditoría")}</span>
        <AutoTextarea
          ref={noteRef}
          className="mt-1 leading-relaxed"
          minRows={3}
          maxRows={7}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          name="audit-note"
          placeholder={tr("Optionale Prüfungsnotiz eingeben…", "Enter optional audit note…", "Introducir nota de auditoría opcional…")}
        />
      </label>
      <p className="mt-2 text-xs leading-relaxed text-subtle">
        {tr(
          "Das Siegel wird als eigener, Ed25519-signierter Eintrag in die Hash-Kette geschrieben. Eine erneute Analyse hebt es auf; die Historie bleibt erhalten.",
          "The seal is recorded as a dedicated Ed25519-signed entry in the hash chain. Re-analyzing voids it, while preserving history.",
          "El sello se registra como una entrada firmada con Ed25519 en la cadena de hash. Reanalizarlo anula el sello pero conserva el historial.",
        )}
      </p>
      <div className="mt-3 flex justify-end">
        <button type="button" className="btn btn-primary" disabled={!ready} onClick={() => void seal()}>
          {busy ? <Spinner size={13} /> : <Stamp size={14} aria-hidden="true" />}
          {existing
            ? tr("Siegel erneuern", "Renew Seal", "Renovar sello")
            : tr("Digital versiegeln", "Seal digitally", "Sellar digitalmente")}
          <Kbd>{mod} ↵</Kbd>
        </button>
      </div>
    </div>
  );
}

/** Kompakter Siegel-Dialog aus der Action-Leiste (Strg/⌘ + Enter, zweites Strg/⌘ + Enter versiegelt). */
export function SealModal({ document, open, onClose, onSealed, notify }: {
  document: DocumentDetail | null;
  open: boolean;
  onClose: () => void;
  onSealed: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad", title: string, message?: string) => void;
}) {
  const { tr, td } = useI18n();
  if (!document) return null;
  const card = document.scorecard;
  return (
    <Modal open={open} onClose={onClose} title={tr("Beleg siegeln", "Seal document", "Sellar documento")} subtitle={document.filename} width="max-w-xl">
      {card && (
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs">
          <span className="text-subtle">
            Score <span className="font-semibold tabular-nums text-fg">{card.score}</span>
            <span className="tabular-nums"> / 100</span>
          </span>
          <span className={TONE_TEXT[verdictTone(card)]}>{td(card.release_recommendation)}</span>
        </div>
      )}
      <SignOffPanel
        document={document}
        shortcutActive={open}
        autoFocus
        notify={notify}
        onSealed={(updated) => {
          onSealed(updated);
          onClose();
        }}
      />
    </Modal>
  );
}
