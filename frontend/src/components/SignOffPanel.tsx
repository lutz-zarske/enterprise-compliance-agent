"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { DocumentDetail, SignOffDecision } from "../types/api";
import { cx, formatDate } from "../lib/format";
import { Check, Stamp } from "./icons";
import { HashBadge, isModEnter, Kbd, Modal, Spinner, useModifierLabel } from "./ui";

const AUDITOR_STORAGE = "eca-auditor-name";

interface PanelProps {
  document: DocumentDetail;
  onSealed: (document: DocumentDetail) => void;
  notify: (tone: "ok" | "bad", title: string, message?: string) => void;
  /** Strg/⌘ + Enter versiegelt (nur solange der umgebende Dialog offen ist). */
  shortcutActive: boolean;
  /** Fokus beim Oeffnen: ins Namensfeld, falls noch kein Name bekannt ist. */
  autoFocus?: boolean;
}

/**
 * Auditor Sign-Off (Art. 14 AI Act): Name, Entscheidung und Notiz werden als
 * Ed25519-signierter Eintrag in die Hash-Kette geschrieben.
 */
export function SignOffPanel({ document, onSealed, notify, shortcutActive, autoFocus }: PanelProps) {
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
    if (noteRef.current) noteRef.current.style.height = "auto";
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
        `Dokument ${reference} erfolgreich Ed25519-versiegelt & im Ledger verankert`,
        `${decision === "SEALED_APPROVED" ? "Freigabe" : "Ablehnung"} durch ${auditor.trim()}`,
      );
    } catch (err) {
      notify("bad", "Siegel fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [ready, document.id, auditor, note, decision, onSealed, notify]);

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
            {existing.status === "SEALED_APPROVED" ? "Freigegeben" : "Freigabe verweigert"} durch {existing.auditor_name} am{" "}
            <span className="font-mono tabular-nums">{formatDate(existing.sealed_at, true)}</span>
          </p>
          <HashBadge className="mt-2" value={existing.ledger_entry_hash} label="Siegel" verified verifiedLabel="Ed25519-signiert" />
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="label-caps">Name der Prüfperson</span>
          <input
            ref={nameRef}
            className="input mt-1"
            name="auditor-name"
            autoComplete="name"
            value={auditor}
            onChange={(e) => setAuditor(e.target.value)}
            placeholder="Prüferkürzel oder Name eingeben…"
          />
        </label>
        <div>
          <span className="label-caps">Entscheidung</span>
          <div className="mt-1 flex gap-2" role="radiogroup" aria-label="Entscheidung">
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
                {value === "SEALED_APPROVED" ? "Freigeben" : "Ablehnen"}
              </button>
            ))}
          </div>
        </div>
      </div>
      {blocked && decision === "SEALED_APPROVED" && (
        <p className="mt-2 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-xs leading-relaxed text-warn">
          Freigabe entgegen der Sperrempfehlung des Regelwerks – die Begründung gehört in die Prüfungsnotiz.
        </p>
      )}
      <label className="mt-3 block">
        <span className="label-caps">Prüfungsnotiz</span>
        <textarea
          ref={noteRef}
          className="input mt-1 min-h-[70px] max-h-[160px] resize-none overflow-y-auto leading-relaxed"
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
          }}
          name="audit-note"
          placeholder="Optionale Prüfungsnotiz eingeben…"
        />
      </label>
      <p className="mt-2 text-xs leading-relaxed text-subtle">
        Das Siegel wird als eigener, Ed25519-signierter Eintrag in die Hash-Kette geschrieben. Eine erneute Analyse hebt es auf;
        die Historie bleibt erhalten.
      </p>
      <div className="mt-3 flex justify-end">
        <button type="button" className="btn btn-primary" disabled={!ready} onClick={() => void seal()}>
          {busy ? <Spinner size={13} /> : <Stamp size={14} aria-hidden="true" />}
          Digital versiegeln
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
  if (!document) return null;
  const card = document.scorecard;
  return (
    <Modal open={open} onClose={onClose} title="Beleg siegeln" subtitle={document.filename} width="max-w-xl">
      {card && (
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs">
          <span className="text-subtle">
            Score <span className="font-mono font-semibold tabular-nums text-fg">{card.score}</span>
            <span className="font-mono tabular-nums"> / 100</span>
          </span>
          <span className={card.release_blocked ? "text-bad" : "text-ok"}>{card.release_recommendation}</span>
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
