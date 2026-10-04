"use client";

import React, { useMemo, useState } from "react";
import type { DocumentSummary } from "../types/api";
import { cx, DOC_TYPE_LABELS, formatBytes, formatDate, formatMoney, toNumber, TONE_CLASSES, toneForBand } from "../lib/format";
import { FileText, Pin, Search, Stamp } from "./icons";
import { EmptyState, Segmented, Spinner } from "./ui";

type Filter = "all" | "compliant" | "review" | "highrisk";
type Sort = "date" | "score" | "size";

const isHighRisk = (doc: DocumentSummary) =>
  doc.ai_act_risk_level === "high" || doc.ai_act_risk_level === "unacceptable";

function matchesFilter(doc: DocumentSummary, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "highrisk") return isHighRisk(doc);
  if (filter === "compliant") return doc.score_band === "green";
  // "Pruefung noetig": noch nicht analysiert, fehlgeschlagen oder gelb/rot ohne Hochrisiko.
  return !isHighRisk(doc) && doc.score_band !== "green";
}

interface Props {
  documents: DocumentSummary[];
  selectedId: string | null;
  extractingId: string | null;
  onSelect: (id: string) => void;
  onTogglePin: (doc: DocumentSummary) => void;
}

export function DocumentList({ documents, selectedId, extractingId, onSelect, onTogglePin }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("date");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = documents.filter((doc) => {
      if (!matchesFilter(doc, filter)) return false;
      if (!q) return true;
      const amount = toNumber(doc.total_amount);
      const haystack = [
        doc.filename,
        doc.sender ?? "",
        amount !== null ? amount.toFixed(2) : "",
        amount !== null ? amount.toLocaleString("de-DE", { minimumFractionDigits: 2 }) : "",
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
    const sorted = [...filtered].sort((a, b) => {
      if (sort === "score") return (b.compliance_score ?? -1) - (a.compliance_score ?? -1);
      if (sort === "size") return b.size_bytes - a.size_bytes;
      return b.created_at.localeCompare(a.created_at);
    });
    // Angepinnte Dokumente immer zuerst.
    return [...sorted.filter((d) => d.pinned), ...sorted.filter((d) => !d.pinned)];
  }, [documents, query, filter, sort]);

  return (
    <section className="card flex min-h-0 flex-col" aria-label="Dokumente">
      <div className="space-y-3 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Dokumente</h2>
          <span className="font-mono text-[11px] text-subtle">{visible.length} / {documents.length}</span>
        </div>
        <div className="relative">
          <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
          <input
            className="input pl-8"
            placeholder="Dateiname, Absender oder Betrag…"
            name="document-search"
            type="search"
            autoComplete="off"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Dokumente durchsuchen"
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Segmented<Filter>
            size="sm"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "Alle" },
              { value: "compliant", label: "Konform" },
              { value: "review", label: "Prüfung nötig" },
              { value: "highrisk", label: "Hochrisiko" },
            ]}
          />
          <select
            className="input w-auto py-1 text-xs"
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            aria-label="Sortierung"
          >
            <option value="date">Neueste</option>
            <option value="score">Score</option>
            <option value="size">Dateigröße</option>
          </select>
        </div>
      </div>

      <ul className="max-h-[560px] flex-1 divide-y divide-line overflow-y-auto">
        {visible.length === 0 && (
          <li>
            <EmptyState icon={<FileText size={18} />} title={documents.length ? "Keine Treffer" : "Noch keine Dokumente"}>
              {documents.length ? "Filter oder Suchbegriff anpassen." : "PDF hochladen oder oben „Musterdaten laden“ wählen."}
            </EmptyState>
          </li>
        )}
        {visible.map((doc) => {
          const selected = doc.id === selectedId;
          const tone = toneForBand(doc.score_band);
          return (
            <li key={doc.id}>
              <div
                className={cx(
                  "group flex items-center gap-1 pr-2 transition-colors duration-150",
                  selected ? "bg-accent-soft" : "hover:bg-surface-2",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(doc.id)}
                  aria-current={selected ? "true" : undefined}
                  className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pl-3 text-left"
                >
                  <span
                    className={cx(
                      "flex h-10 w-11 shrink-0 flex-col items-center justify-center rounded-lg border font-mono",
                      doc.compliance_score != null ? TONE_CLASSES[tone] : "border-line bg-surface-2 text-subtle",
                    )}
                    aria-label={doc.compliance_score != null ? `Compliance-Score ${doc.compliance_score} von 100` : "Noch nicht geprüft"}
                  >
                    {extractingId === doc.id ? (
                      <Spinner size={14} />
                    ) : (
                      <span className="text-sm font-semibold" aria-hidden="true">{doc.compliance_score ?? "–"}</span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate text-[13px] font-medium text-fg">{doc.filename}</span>
                      {doc.sealed && <Stamp size={12} className="shrink-0 text-ok" aria-label="Versiegelt" />}
                    </span>
                    <span className="block truncate text-[11px] text-subtle">
                      {doc.status === "extracted"
                        ? `${doc.provider === "reference" ? "Referenz · " : ""}${DOC_TYPE_LABELS[doc.doc_type ?? "other"]} · ${doc.sender ?? "–"} · ${formatMoney(doc.total_amount, doc.currency)}`
                        : doc.status === "failed"
                          ? "Analyse fehlgeschlagen"
                          : doc.status === "processing"
                            ? "Analyse läuft…"
                            : `Hochgeladen ${formatDate(doc.created_at)} · ${formatBytes(doc.size_bytes)}`}
                    </span>
                    {isHighRisk(doc) && (
                      <span className="chip mt-1 border-bad-line bg-bad-soft text-[10px] text-bad">EU AI Act Anhang III</span>
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
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
