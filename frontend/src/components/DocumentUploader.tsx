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

/** Drag & Drop fuer ein oder mehrere PDFs (POST /documents/upload-batch). */
export function DocumentUploader({ disabled, onUploaded, onError }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  async function upload(fileList: FileList | null) {
    const files = Array.from(fileList ?? []).filter((file) => file.size > 0);
    if (!files.length) return;
    setBusy(true);
    try {
      onUploaded(await api.uploadBatch(files));
    } catch (err) {
      onError(err instanceof ApiError ? err : new ApiError(String(err), 0, "unknown"));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) void upload(event.dataTransfer.files);
      }}
      className={cx(
        "card flex flex-col items-center gap-2 border-dashed px-4 py-5 text-center transition-colors duration-150",
        dragging ? "border-accent bg-accent-soft" : "",
        disabled && "opacity-60",
      )}
    >
      <div className="rounded-lg border border-line bg-surface-2 p-2 text-accent">
        {busy ? <Spinner size={16} /> : <UploadCloud size={18} />}
      </div>
      <div>
        <p className="text-sm font-medium text-fg">PDFs hier ablegen</p>
        <p className="text-xs text-subtle">Mehrfachauswahl möglich · max. 20 MB je Datei · Textlayer erforderlich</p>
      </div>
      <button className="btn" disabled={disabled || busy} onClick={() => inputRef.current?.click()}>
        Dateien auswählen
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="hidden"
        onChange={(event) => void upload(event.target.files)}
      />
    </div>
  );
}
