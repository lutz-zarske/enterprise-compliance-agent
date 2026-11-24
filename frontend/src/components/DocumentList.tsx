"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DocumentSummary } from "../types/api";
import { cx, docTypeLabel, formatBytes, formatDate, formatMoney, toNumber, TONE_CLASSES, toneForBand } from "../lib/format";
import { LOCALE_TAG, useI18n } from "../lib/i18n";
import { AlertTriangle, Archive, ArchiveRestore, FileText, Hourglass, ListChecks, Lock, Pin, Search, XCircle } from "./icons";
import { Select } from "./Select";
import { einvoiceHint, documentStatusHint, highRiskHint, rulesOnlyHint } from "../lib/hints";
import { Chip, EmptyState, isTypingTarget, Kbd, Spinner } from "./ui";

type Filter = "all" | "open" | "sealed" | "archived" | "highrisk";
type Sort = "newest" | "oldest" | "score_desc" | "score_asc";

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
  const { tr } = useI18n();
  if (doc.sealed) {
    return (
      <Chip tone="ok" focusable={false} hint={documentStatusHint("sealed")}>
        <Lock size={12} aria-hidden="true" /> {tr("Versiegelt", "Sealed", "Sellado")}
      </Chip>
    );
  }
  if (doc.status === "extracted" && doc.compliance_score == null) {
    return <span className="chip border-line bg-surface-2 text-muted">{tr("Noch nicht geprüft", "Not yet audited", "Aún sin auditar")}</span>;
  }
  if (doc.status === "failed") {
    return (
      <Chip tone="bad" focusable={false} hint={documentStatusHint("failed")}>
        <XCircle size={12} aria-hidden="true" /> {tr("Analyse fehlgeschlagen", "Audit failed", "Análisis fallido")}
      </Chip>
    );
  }
  if (doc.status === "extracted" && doc.doc_type === "invoice" && doc.score_band === "red") {
    return (
      <Chip
        tone="bad"
        focusable={false}
        hint={tr(
          "Pflichtangaben fehlen: Ohne korrigierte Rechnung darf der Empfänger die Vorsteuer nicht abziehen (§ 15 UStG).",
          "Mandatory details are missing: without a corrected invoice the recipient may not deduct input VAT (§ 15 UStG).",
          "Faltan datos obligatorios: sin una factura corregida el destinatario no puede deducir el IVA soportado (§ 15 UStG).",
        )}
      >
        <AlertTriangle size={12} aria-hidden="true" /> {tr("Vorsteuer gefährdet", "VAT Deduction Risk", "Riesgo de IVA")}
      </Chip>
    );
  }
  if (doc.status === "extracted" && isHighRisk(doc)) {
    return (
      <Chip tone="warn" focusable={false} hint={highRiskHint()}>
        <AlertTriangle size={12} aria-hidden="true" /> {tr("Konformität offen", "Conformity pending", "Conformidad pendiente")}
      </Chip>
    );
  }
  if (doc.status === "extracted" && doc.provider === "heuristic") {
    return (
      <Chip tone="warn" focusable={false} hint={rulesOnlyHint()}>
        <AlertTriangle size={12} aria-hidden="true" /> {tr("Regelwerk-Audit", "Rules-only audit", "Auditoría por reglas")}
      </Chip>
    );
  }
  return (
    <span className="chip border-line bg-surface-2 text-muted">
      <Hourglass size={12} aria-hidden="true" />
      {doc.status === "uploaded"
        ? tr("Ungeprüft", "Pending", "Pendiente")
        : doc.status === "processing"
          ? tr("Analyse läuft", "Auditing", "Analizando")
          : tr("Siegel offen", "Unsealed", "Sin sello")}
    </span>
  );
}

/** Zweite Zeile: ganze Angaben, die bei Platzmangel als Ganzes umbrechen – nie mitten im Wort. */
function MetaLine({ doc }: { doc: DocumentSummary }) {
  const { tr } = useI18n();
  const providerPrefix =
    doc.provider === "reference"
      ? tr("Referenz · ", "Reference · ", "Referencia · ")
      : doc.provider === "heuristic"
        ? tr("Regelwerk · ", "Ruleset · ", "Reglas · ")
        : "";
  const parts: React.ReactNode[] =
    doc.status === "extracted"
      ? [
          `${providerPrefix}${docTypeLabel(doc.doc_type ?? "other")}`,
          doc.sender,
          doc.total_amount != null ? <span className="tabular-nums">{formatMoney(doc.total_amount, doc.currency)}</span> : null,
          doc.document_date ? <span className="tabular-nums">{formatDate(doc.document_date)}</span> : null,
        ]
      : doc.status === "processing"
        ? [tr("Analyse läuft…", "Auditing…", "Analizando…")]
        : doc.status === "failed"
          ? [tr("Erneut prüfen oder Modell wechseln", "Retry audit or switch model", "Reintentar o cambiar modelo")]
          : [`${tr("Hochgeladen", "Uploaded", "Subido")} ${formatDate(doc.created_at)}`, <span key="size" className="tabular-nums">{formatBytes(doc.size_bytes)}</span>];
  const shown = parts.filter(Boolean);
  return (
    <span className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs text-subtle">
      {/* Trennpunkt gehört zur folgenden Angabe: bricht die Zeile um, beginnt sie mit dem Punkt. */}
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
  /** Belege mit wartendem oder laufendem Prüf-Job. */
  analysingIds: ReadonlySet<string>;
  /** Batch: alle ungeprüften Belege einreihen (fehlt ohne Backend). */
  onAnalyzeAll?: (ids: string[]) => void;
  onSelect: (id: string) => void;
  onTogglePin: (doc: DocumentSummary) => void;
  onToggleArchive: (doc: DocumentSummary) => void;
  /** false, solange ein Dialog oder der Copilot offen ist. */
  shortcutsEnabled: boolean;
}

export function DocumentList({ documents, selectedId, analysingIds, onAnalyzeAll, onSelect, onTogglePin, onToggleArchive, shortcutsEnabled }: Props) {
  const { locale, tr, td } = useI18n();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("newest");
  const sortOptions = useMemo(
    () =>
      [
        { value: "newest", label: tr("Neueste zuerst", "Newest first", "Más recientes primero") },
        { value: "oldest", label: tr("Älteste zuerst", "Oldest first", "Más antiguos primero") },
        { value: "score_desc", label: tr("Score (höchste zuerst)", "Score (highest first)", "Puntuación (mayor a menor)") },
        { value: "score_asc", label: tr("Score (niedrigste zuerst)", "Score (lowest first)", "Puntuación (menor a mayor)") },
      ] as const,
    [tr],
  );

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
        amount !== null ? amount.toLocaleString(LOCALE_TAG[locale], { minimumFractionDigits: 2 }) : "",
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
  }, [documents, query, filter, sort, locale]);

  const listRef = useRef<HTMLUListElement>(null);
  const pending = useMemo(
    () => documents.filter((doc) => !doc.archived && (doc.status === "uploaded" || doc.status === "failed") && !analysingIds.has(doc.id)),
    [documents, analysingIds],
  );

  /** Nächstes/vorheriges Dokument in der sichtbaren Reihenfolge (Filter und Sortierung). */
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

  // J/K und Pfeiltasten wie in Linear - außer beim Tippen und bei offenen Dialogen. Pfeiltasten nur,
  // solange kein anderes Bedienelement den Fokus hat (sonst gehören sie diesem Element bzw. dem Scrollen).
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

  const filters: { value: Filter; label: string }[] = [
    { value: "all", label: tr("Alle", "All", "Todos") },
    { value: "open", label: tr("Offen", "Open", "Pendientes") },
    { value: "sealed", label: tr("Versiegelt", "Sealed", "Sellados") },
    { value: "archived", label: tr("Archiviert", "Archived", "Archivados") },
    ...(counts.highrisk ? [{ value: "highrisk" as const, label: tr("Hochrisiko", "High Risk", "Alto riesgo") }] : []),
  ];

  return (
    <section className="card flex min-h-0 flex-col" aria-label={tr("Dokumente", "Documents", "Documentos")}>
      <div className="space-y-3 border-b border-line p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-fg">{tr("Dokumente", "Documents", "Documentos")}</h2>
          <span className="flex items-center gap-2">
            {onAnalyzeAll && pending.length > 1 && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => onAnalyzeAll(pending.map((doc) => doc.id))}
                title={tr("Alle ungeprüften Belege nacheinander im Hintergrund prüfen", "Audit all pending documents sequentially in the background", "Analizar todos los documentos pendientes en segundo plano")}
              >
                <ListChecks size={13} aria-hidden="true" /> <span className="tabular-nums">{pending.length}</span> {tr("prüfen", "audit", "analizar")}
              </button>
            )}
            <span className="hidden items-center gap-1 text-xs text-subtle xl:flex" title={tr("Nächstes / vorheriges Dokument (auch Pfeiltasten)", "Next / previous document (or arrow keys)", "Documento siguiente / anterior (o flechas)")}>
              <Kbd>J</Kbd>
              <Kbd>K</Kbd>
            </span>
            <Select<Sort> value={sort} onChange={setSort} options={sortOptions} ariaLabel={tr("Sortierung", "Sort order", "Orden")} width={210} />
          </span>
        </div>
        <div className="relative">
          <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
          <input
            className="input pl-8"
            placeholder={tr("Nummer, Absender, Betrag…", "Number, sender, amount…", "Número, emisor, importe…")}
            name="document-search"
            type="search"
            autoComplete="off"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={tr("Dokumente durchsuchen", "Search documents", "Buscar documentos")}
          />
        </div>
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={tr("Status-Filter", "Status filters", "Filtros de estado")}>
          {filters.map((option) => (
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
              <span className="tabular-nums opacity-80">{counts[option.value]}</span>
            </button>
          ))}
        </div>
      </div>

      <ul
        ref={listRef}
        aria-label={tr("Dokumentliste – Pfeiltasten wechseln das Dokument", "Document list – use arrow keys to switch document", "Lista de documentos – use flechas para cambiar")}
        className="scroll-area max-h-[560px] flex-1 divide-y divide-line 2xl:max-h-[max(560px,calc(100vh-440px))]"
      >
        {visible.length === 0 && (
          <li>
            <EmptyState
              icon={<FileText size={18} />}
              title={
                documents.length
                  ? tr("Keine Treffer", "No matches", "Sin resultados")
                  : tr("Noch keine Dokumente", "No documents yet", "Sin documentos aún")
              }
            >
              {filter === "archived"
                ? tr(
                    "Archivierte Belege erscheinen hier. Archivieren blendet nur aus – nichts wird gelöscht.",
                    "Archived records appear here. Archiving only hides items – nothing is deleted.",
                    "Los registros archivados aparecen aquí. Archivar solo oculta elementos; no elimina nada.",
                  )
                : documents.length
                  ? tr("Filter oder Suchbegriff anpassen.", "Adjust filter or search query.", "Ajusta el filtro o la búsqueda.")
                  : tr("PDF hochladen oder oben „Musterdaten“ wählen.", "Upload a PDF or select “Samples” above.", "Sube un PDF o elige «Casos de ejemplo» arriba.")}
            </EmptyState>
          </li>
        )}
        {visible.map((doc) => {
          const selected = doc.id === selectedId;
          const tone = toneForBand(doc.score_band);
          const title = doc.document_number ? `${tr("Nr.", "No.", "N.º")} ${doc.document_number}` : doc.filename;
          return (
            <li key={doc.id}>
              <div className={cx("group flex items-center gap-0.5 pr-2 transition-colors duration-150", selected ? "bg-accent-soft" : "hover:bg-surface-hover")}>
                <button
                  type="button"
                  onClick={() => onSelect(doc.id)}
                  data-doc-id={doc.id}
                  aria-current={selected ? "true" : undefined}
                  className="flex min-w-0 flex-1 items-start gap-3 py-2.5 pl-3 text-left"
                >
                  <span
                    className={cx(
                      "flex h-10 w-11 shrink-0 flex-col items-center justify-center rounded-lg border",
                      doc.compliance_score != null ? TONE_CLASSES[tone] : "border-line bg-surface-2 text-subtle",
                    )}
                    aria-label={
                      doc.compliance_score != null
                        ? tr(`Compliance-Score ${doc.compliance_score} von 100`, `Compliance score ${doc.compliance_score} of 100`, `Puntuación de cumplimiento ${doc.compliance_score} de 100`)
                        : tr("Noch nicht geprüft", "Not yet audited", "Aún sin analizar")
                    }
                  >
                    {analysingIds.has(doc.id) ? (
                      <Spinner size={14} />
                    ) : doc.compliance_score != null ? (
                      <span className="text-sm font-semibold tabular-nums" aria-hidden="true">{doc.compliance_score}</span>
                    ) : (
                      <span className="text-xs font-medium" aria-hidden="true">{tr("offen", "open", "abierto")}</span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="min-w-0 max-w-full truncate text-sm font-medium text-fg" title={doc.filename}>{title}</span>
                      <StatusBadge doc={doc} />
                    </span>
                    <MetaLine doc={doc} />
                    {(isHighRisk(doc) || doc.einvoice_profile) && (
                      <span className="mt-1 flex flex-wrap gap-1">
                        {isHighRisk(doc) && (
                          <Chip tone="bad" focusable={false} hint={highRiskHint()}>{tr("EU AI Act Anhang III", "EU AI Act Annex III", "Reglamento IA Anexo III")}</Chip>
                        )}
                        {doc.einvoice_profile && (
                          <Chip tone="accent" focusable={false} hint={einvoiceHint()}>{tr("E-Rechnung", "E-Invoice", "Factura electrónica")} · {td(doc.einvoice_profile)}</Chip>
                        )}
                      </span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onTogglePin(doc)}
                  className={cx(
                    "icon-target rounded-md p-1 transition-[color,opacity] duration-150",
                    doc.pinned ? "text-accent" : "text-subtle opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100",
                  )}
                  aria-label={doc.pinned ? tr(`${doc.filename} lösen`, `Unpin ${doc.filename}`, `Desfijar ${doc.filename}`) : tr(`${doc.filename} anpinnen`, `Pin ${doc.filename}`, `Fijar ${doc.filename}`)}
                  aria-pressed={doc.pinned}
                  title={doc.pinned ? tr("Lösen", "Unpin", "Desfijar") : tr("Oben anpinnen", "Pin to top", "Fijar arriba")}
                >
                  <Pin size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => onToggleArchive(doc)}
                  className={cx(
                    "icon-target rounded-md p-1 transition-[color,opacity] duration-150",
                    doc.archived ? "text-accent" : "text-subtle opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100",
                  )}
                  aria-label={doc.archived ? tr(`${doc.filename} aus dem Archiv holen`, `Unarchive ${doc.filename}`, `Desarchivar ${doc.filename}`) : tr(`${doc.filename} archivieren`, `Archive ${doc.filename}`, `Archivar ${doc.filename}`)}
                  title={doc.archived ? tr("Aus dem Archiv holen", "Unarchive", "Desarchivar") : tr("Archivieren (nur ausblenden, nichts wird gelöscht)", "Archive (hides only, nothing deleted)", "Archivar (solo oculta, no borra nada)")}
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
