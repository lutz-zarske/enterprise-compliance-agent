"use client";

import React, { useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { BatchUploadResponse } from "../types/api";
import { cx } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { UploadCloud } from "./icons";
import { Spinner } from "./ui";

interface Props {
  disabled: boolean;
  onUploaded: (result: BatchUploadResponse) => void;
  onError: (error: ApiError) => void;
}

/** Drag & Drop fuer beliebig viele PDFs und XML-E-Rechnungen (POST /documents/upload-batch). */
export function DocumentUploader({ disabled, onUploaded, onError }: Props) {
  const { tr } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragCount, setDragCount] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const dragging = dragCount !== null;

  async function upload(fileList: FileList | null) {
    const files = Array.from(fileList ?? []).filter((file) => file.size > 0);
    if (!files.length) return;
    setBusy(files.length);
    try {
      onUploaded(await api.uploadBatch(files));
    } catch (err) {
      onError(err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown"));
    } finally {
      setBusy(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const fileCount = (count: number) =>
    count === 1
      ? tr("1 Datei", "1 file", "1 archivo")
      : tr(`${count} Dateien`, `${count} files`, `${count} archivos`);

  return (
    <div
      data-tour="upload"
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragCount(event.dataTransfer.items?.length ?? 0);
      }}
      onDragLeave={() => setDragCount(null)}
      onDrop={(event) => {
        event.preventDefault();
        setDragCount(null);
        if (!disabled) void upload(event.dataTransfer.files);
      }}
      className={cx(
        "card flex flex-col items-center gap-2 border-dashed px-4 py-5 text-center transition-colors duration-150",
        dragging ? "border-accent bg-accent-soft" : "",
        disabled && "opacity-60",
      )}
    >
      <div className="rounded-lg border border-line bg-surface-2 p-2 text-accent">
        {busy !== null ? <Spinner size={16} /> : <UploadCloud size={18} />}
      </div>
      <div aria-live="polite">
        <p className="text-sm font-medium text-fg">
          {busy !== null
            ? tr(`${fileCount(busy)} werden geprüft…`, `Checking ${fileCount(busy)}…`, `Analizando ${fileCount(busy)}…`)
            : dragging && dragCount
              ? tr(`Drop ${fileCount(dragCount)}`, `Drop ${fileCount(dragCount)}`, `Soltar ${fileCount(dragCount)}`)
              : tr("PDFs oder E-Rechnungen hier ablegen", "Drop PDFs or E-Invoices here", "Suelta PDF o facturas electrónicas aquí")}
        </p>
        <p className="text-xs text-subtle">
          {tr(
            "PDF, ZUGFeRD/Factur-X oder XRechnung (.xml) · mehrere Dateien gleichzeitig · max. 20 MB je Datei",
            "PDF, ZUGFeRD/Factur-X or XRechnung (.xml) · multi-file upload · max. 20 MB per file",
            "PDF, ZUGFeRD/Factur-X o XRechnung (.xml) · varios archivos · máx. 20 MB por archivo",
          )}
        </p>
      </div>
      <button className="btn" disabled={disabled || busy !== null} onClick={() => inputRef.current?.click()}>
        {tr("Dateien auswählen", "Select files", "Seleccionar archivos")}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf,application/xml,text/xml,.xml"
        multiple
        className="hidden"
        aria-label={tr("PDF- oder XML-Dateien auswählen", "Select PDF or XML files", "Seleccionar archivos PDF o XML")}
        onChange={(event) => void upload(event.target.files)}
      />
    </div>
  );
}
