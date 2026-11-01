"use client";

import React, { useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { BatchUploadResponse } from "../types/api";
import { cx } from "../lib/format";
import { UploadCloud } from "./icons";
import { Spinner } from "./ui";

interface Props {
  disabled: boolean;
  onUploaded: (result: BatchUploadResponse) => void;
  onError: (error: ApiError) => void;
}

/** Drag & Drop fuer beliebig viele PDFs und XML-E-Rechnungen (POST /documents/upload-batch). */
export function DocumentUploader({ disabled, onUploaded, onError }: Props) {
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

  const fileCount = (count: number) => (count === 1 ? "1 Datei" : `${count} Dateien`);

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
            ? `${fileCount(busy)} werden geprüft…`
            : dragging && dragCount
              ? `${fileCount(dragCount)} loslassen`
              : "PDFs oder E-Rechnungen hier ablegen"}
        </p>
        <p className="text-xs text-subtle">
          PDF, ZUGFeRD/Factur-X oder XRechnung (.xml) · mehrere Dateien gleichzeitig · max. 20 MB je Datei
        </p>
      </div>
      <button className="btn" disabled={disabled || busy !== null} onClick={() => inputRef.current?.click()}>
        Dateien auswählen
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf,application/xml,text/xml,.xml"
        multiple
        className="hidden"
        aria-label="PDF- oder XML-Dateien auswählen"
        onChange={(event) => void upload(event.target.files)}
      />
    </div>
  );
}
