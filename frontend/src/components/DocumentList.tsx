"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DocumentSummary } from "../types/api";
import { cx, DOC_TYPE_LABELS, formatBytes, formatDate, formatMoney, toNumber, TONE_CLASSES, toneForBand } from "../lib/format";
import { AlertTriangle, Archive, ArchiveRestore, FileText, Hourglass, Lock, Pin, Search, XCircle } from "./icons";
import { Select } from "./Select";
import { EmptyState, isTypingTarget, Kbd, Spinner } from "./ui";

type Filter = "all" | "open" | "sealed" | "archived" | "highrisk";
type Sort = "newest" | "oldest" | "score_desc" | "score_asc";

const SORT_OPTIONS = [
  { value: "newest", label: "Neueste zuerst" },
  { value: "oldest", label: "Älteste zuerst" },
  { value: "score_desc", label: "Score (höchste zuerst)" },
  { value: "score_asc", label: "Score (niedrigste zuerst)" },
] as const;

const isHighRisk = (doc: DocumentSummary) =>
  doc.ai_act_risk_level === "high" || doc.ai_act_risk_level === "unacceptable";

function matchesFilter(doc: DocumentSummary, filter: Filter): boolean {
  if (filter === "archived") return doc.archived;
  if (doc.archived) return false; // Archivierte erscheinen nur im Filter „Archiviert“.
  if (filter === "open") return !doc.sealed;
  if (filter === "sealed") return doc.sealed;
  if (filter === "highrisk") return isHighRisk(doc);
  return true;
}

/** Status als klar lesbares Badge statt eines kleinen Schlosses. */
function StatusBadge({ doc }: { doc: DocumentSummary }) {
  if (doc.sealed) {
    return (
      <span className="chip border-ok-line bg-ok-soft text-ok" title="Prüfentscheid als Ed25519-signierter Ledger-Eintrag versiegelt">
        <Lock size={12} aria-hidden="true" /> Versiegelt (Ed25519)
      </span>
    );
  }
  if (doc.status === "failed") {
    return <span className="chip border-bad-line bg-bad-soft text-bad"><XCircle size={12} aria-hidden="true" /> Analyse fehlgeschlagen</span>;
  }
  if (doc.status === "extracted" && doc.doc_type === "invoice" && doc.score_band === "red") {
    return (
      <span className="chip border-bad-line bg-bad-soft text-bad" title="Pflichtangaben nach § 14 Abs. 4 UStG fehlen – der Vorsteuerabzug nach § 15 UStG ist gefährdet">
        <AlertTriangle size={12} aria-hidden="true" /> Vorsteuer gefährdet
      </span>
    );
  }
  if (doc.status === "extracted" && isHighRisk(doc)) {
    return (
      <span className="chip border-warn-line bg-warn-soft text-warn" title="Hochrisiko nach Anhang III VO (EU) 2024/1689 – Konformitätsnachweis offen">
        <AlertTriangle size={12} aria-hidden="true" /> Konformität offen
      </span>
    );
  }
  return (
    <span className="chip border-line bg-surface-2 text-muted">
      <Hourglass size={12} aria-hidden="true" /> In Prüfung
    </span>
  );
}

/** Zweite Zeile: ganze Angaben, die bei Platzmangel als Ganzes umbrechen – nie mitten im Wort. */
function MetaLine({ doc }: { doc: DocumentSummary }) {
  const parts: React.ReactNode[] =
    doc.status === "extracted"
      ? [
          `${doc.provider === "reference" ? "Referenz · " : ""}${DOC_TYPE_LABELS[doc.doc_type ?? "other"]}`,
          doc.sender,
          doc.total_amount != null ? <span className="font-mono tabular-nums">{formatMoney(doc.total_amount, doc.currency)}</span> : null,
          doc.document_date ? <span className="font-mono tabular-nums">{formatDate(doc.document_date)}</span> : null,
        ]
      : doc.status === "processing"
        ? ["Analyse läuft…"]
        : doc.status === "failed"
          ? ["Erneut prüfen oder Modell wechseln"]
          : [`Hochgeladen ${formatDate(doc.created_at)}`, <span key="size" className="font-mono tabular-nums">{formatBytes(doc.size_bytes)}</span>];
  const shown = parts.filter(Boolean);
  return (
    <span className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs text-subtle">
      {/* Trennpunkt gehoert zur folgenden Angabe: bricht die Zeile um, beginnt sie mit dem Punkt. */}
      {shown.map((part, index) => (
        <span key={index} className="[overflow-wrap:break-word]">
          {index > 0 && <span aria-hidden="true" className="mr-1.5">•</span>}
          {part}
        </span>
      ))}
    </span>
  );
}

interface Props {
  documents: DocumentSummary[];
  selectedId: string | null;
  extractingId: string | null;
  onSelect: (id: string) => void;
  onTogglePin: (doc: DocumentSummary) => void;
  onToggleArchive: (doc: DocumentSummary) => void;
  /** false, solange ein Dialog oder der Copilot offen ist. */
  shortcutsEnabled: boolean;
}

export function DocumentList({ documents, selectedId, extractingId, onSelect, onTogglePin, onToggleArchive, shortcutsEnabled }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("newest");

  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: 0, open: 0, sealed: 0, archived: 0, highrisk: 0 };
    for (const doc of documents) {
      (Object.keys(result) as Filter[]).forEach((key) => {
        if (matchesFilter(doc, key)) result[key] += 1;
      });
    }
    return result;
  }, [documents]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = documents.filter((doc) => {
      if (!matchesFilter(doc, filter)) return false;
      if (!q) return true;
      const amount = toNumber(doc.total_amount);
      const haystack = [
        doc.filename,
        doc.document_number ?? "",
        doc.sender ?? "",
        doc.einvoice_profile ?? "",
        amount !== null ? amount.toFixed(2) : "",
        amount !== null ? amount.toLocaleString("de-DE", { minimumFractionDigits: 2 }) : "",
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
    const sorted = [...filtered].sort((a, b) => {
      if (sort === "score_desc") return (b.compliance_score ?? -1) - (a.compliance_score ?? -1);
      if (sort === "score_asc") return (a.compliance_score ?? 101) - (b.compliance_score ?? 101);
      if (sort === "oldest") return a.created_at.localeCompare(b.created_at);
      return b.created_at.localeCompare(a.created_at);
    });
    // Angepinnte Dokumente immer zuerst.
    return [...sorted.filter((d) => d.pinned), ...sorted.filter((d) => !d.pinned)];
  }, [documents, query, filter, sort]);

  const listRef = useRef<HTMLUListElement>(null);

  /** Naechstes/vorheriges Dokument in der sichtbaren Reihenfolge (Filter und Sortierung). */
  const move = useCallback(
    (delta: number, focus: boolean) => {
      if (!visible.length) return;
      const index = visible.findIndex((doc) => doc.id === selectedId);
      const next = index === -1 ? (delta > 0 ? 0 : visible.length - 1) : Math.min(visible.length - 1, Math.max(0, index + delta));
      const target = visible[next];
      if (target.id !== selectedId) onSelect(target.id);
      window.requestAnimationFrame(() => {
        const button = listRef.current?.querySelector<HTMLButtonElement>(`[data-doc-id="${target.id}"]`);
        button?.scrollIntoView({ block: "nearest" });
        if (focus) button?.focus({ preventScroll: true });
      });
    },
    [visible, selectedId, onSelect],
  );

  // J/K und Pfeiltasten wie in Linear - ausser beim Tippen und bei offenen Dialogen. Pfeiltasten nur,
  // solange kein anderes Bedienelement den Fokus hat (sonst gehoeren sie diesem Element bzw. dem Scrollen).
  useEffect(() => {
    if (!shortcutsEnabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return;
      const key = event.key.toLowerCase();
      const arrow = event.key === "ArrowDown" || event.key === "ArrowUp";
      if (arrow) {
        const focused = document.activeElement;
        const free = !focused || focused === document.body || listRef.current?.contains(focused);
        if (!free) return;
      } else if (key !== "j" && key !== "k") {
        return;
      }
      event.preventDefault();
      move(key === "j" || event.key === "ArrowDown" ? 1 : -1, arrow);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shortcutsEnabled, move]);

  const FILTERS: { value: Filter; label: string }[] = [
    { value: "all", label: "Alle" },
    { value: "open", label: "Offen" },
    { value: "sealed", label: "Versiegelt" },
    { value: "archived", label: "Archiviert" },
    ...(counts.highrisk ? [{ value: "highrisk" as const, label: "Hochrisiko" }] : []),
  ];

  return (
    <section className="card flex min-h-0 flex-col" aria-label="Dokumente">
      <div className="space-y-3 border-b border-line p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-fg">Dokumente</h2>
          <span className="flex items-center gap-2">
            <span className="hidden items-center gap-1 text-xs text-subtle xl:flex" title="Nächstes / vorheriges Dokument (auch Pfeiltasten)">
              <Kbd>J</Kbd>
              <Kbd>K</Kbd>
            </span>
            <Select<Sort> value={sort} onChange={setSort} options={SORT_OPTIONS} ariaLabel="Sortierung" width={210} />
          </span>
        </div>
        <div className="relative">
          <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
          <input
            className="input pl-8"
            placeholder="Nummer, Absender, Betrag…"
            name="document-search"
            type="search"
            autoComplete="off"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Dokumente durchsuchen"
          />
        </div>
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Status-Filter">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={filter === option.value}
              onClick={() => setFilter(option.value)}
              className={cx(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors duration-150",
                filter === option.value
                  ? "border-accent-line bg-accent-soft text-accent"
                  : "border-line text-subtle hover:border-line-strong hover:text-fg",
              )}
            >
              {option.label}
              <span className="font-mono tabular-nums opacity-80">{counts[option.value]}</span>
            </button>
          ))}
        </div>
      </div>

      <ul
        ref={listRef}
        aria-label="Dokumentliste – Pfeiltasten wechseln das Dokument"
        className="scroll-area max-h-[560px] flex-1 divide-y divide-line 2xl:max-h-[max(560px,calc(100vh-440px))]"
      >
        {visible.length === 0 && (
          <li>
            <EmptyState icon={<FileText size={18} />} title={documents.length ? "Keine Treffer" : "Noch keine Dokumente"}>
              {filter === "archived"
                ? "Archivierte Belege erscheinen hier. Archivieren blendet nur aus – nichts wird gelöscht."
                : documents.length
                  ? "Filter oder Suchbegriff anpassen."
                  : "PDF hochladen oder oben „Musterdaten“ wählen."}
            </EmptyState>
          </li>
        )}
        {visible.map((doc) => {
          const selected = doc.id === selectedId;
          const tone = toneForBand(doc.score_band);
          const title = doc.document_number ? `Nr. ${doc.document_number}` : doc.filename;
          return (
            <li key={doc.id}>
              <div className={cx("group flex items-center gap-0.5 pr-2 transition-colors duration-150", selected ? "bg-accent-soft" : "hover:bg-surface-2")}>
                <button
                  type="button"
                  onClick={() => onSelect(doc.id)}
                  data-doc-id={doc.id}
                  aria-current={selected ? "true" : undefined}
                  className="flex min-w-0 flex-1 items-start gap-3 py-2.5 pl-3 text-left"
                >
                  <span
                    className={cx(
                      "flex h-10 w-11 shrink-0 flex-col items-center justify-center rounded-lg border font-mono",
                      doc.compliance_score != null ? TONE_CLASSES[tone] : "border-line bg-surface-2 text-subtle",
                    )}
                    aria-label={doc.compliance_score != null ? `Compliance-Score ${doc.compliance_score} von 100` : "Noch nicht geprüft"}
                  >
                    {extractingId === doc.id ? <Spinner size={14} /> : <span className="text-sm font-semibold tabular-nums" aria-hidden="true">{doc.compliance_score ?? "–"}</span>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="min-w-0 max-w-full truncate text-sm font-medium text-fg" title={doc.filename}>{title}</span>
                      <StatusBadge doc={doc} />
                    </span>
                    <MetaLine doc={doc} />
                    {(isHighRisk(doc) || doc.einvoice_profile) && (
                      <span className="mt-1 flex flex-wrap gap-1">
                        {isHighRisk(doc) && <span className="chip border-bad-line bg-bad-soft text-bad">EU AI Act Anhang III</span>}
                        {doc.einvoice_profile && (
                          <span className="chip border-accent-line bg-accent-soft font-mono text-accent">E-Rechnung · {doc.einvoice_profile}</span>
                        )}
                      </span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onTogglePin(doc)}
                  className={cx(
                    "rounded-md p-1.5 transition-[color,opacity] duration-150",
                    doc.pinned ? "text-accent" : "text-subtle opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100",
                  )}
                  aria-label={doc.pinned ? `${doc.filename} lösen` : `${doc.filename} anpinnen`}
                  aria-pressed={doc.pinned}
                  title={doc.pinned ? "Lösen" : "Oben anpinnen"}
                >
                  <Pin size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => onToggleArchive(doc)}
                  className={cx(
                    "rounded-md p-1.5 transition-[color,opacity] duration-150",
                    doc.archived ? "text-accent" : "text-subtle opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100",
                  )}
                  aria-label={doc.archived ? `${doc.filename} aus dem Archiv holen` : `${doc.filename} archivieren`}
                  title={doc.archived ? "Aus dem Archiv holen" : "Archivieren (nur ausblenden, nichts wird gelöscht)"}
                >
                  {doc.archived ? <ArchiveRestore size={14} aria-hidden="true" /> : <Archive size={14} aria-hidden="true" />}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
