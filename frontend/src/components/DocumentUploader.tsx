"use client";

import React, { useState, useRef } from "react";
import { UploadResponse } from "../types/api";
import { uploadDocument } from "../lib/api";
import { UploadCloud, FileText, CheckCircle2, AlertCircle, RefreshCw } from "./icons";

interface DocumentUploaderProps {
  onUploadSuccess: (upload: UploadResponse) => void;
  maxSizeBytes?: number;
}

export const DocumentUploader: React.FC<DocumentUploaderProps> = ({
  onUploadSuccess,
  maxSizeBytes = 20 * 1024 * 1024, // 20 MB default
}) => {
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successInfo, setSuccessInfo] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const validateAndUpload = async (file: File) => {
    setErrorMessage(null);
    setSuccessInfo(null);

    // Validate type
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      setErrorMessage("Nur PDF-Dokumente (.pdf) sind zulässig.");
      return;
    }

    // Validate size
    if (file.size > maxSizeBytes) {
      setErrorMessage(
        `Datei ist zu groß (${(file.size / (1024 * 1024)).toFixed(1)} MB). Das Limit beträgt ${maxSizeBytes / (1024 * 1024)} MB.`
      );
      return;
    }

    setIsUploading(true);
    setUploadProgress(0);

    try {
      const res = await uploadDocument(file, (percent) => {
        setUploadProgress(percent);
      });
      setUploadProgress(100);
      setSuccessInfo(`Erfolgreich hochgeladen: ${res.filename} (${res.page_count} Seiten, ${res.char_count} Zeichen)`);
      onUploadSuccess(res);
      setTimeout(() => {
        setSuccessInfo(null);
        setUploadProgress(0);
        setIsUploading(false);
      }, 3000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload fehlgeschlagen.";
      setErrorMessage(msg);
      setIsUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      validateAndUpload(file);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      validateAndUpload(file);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-5 border border-slate-800/80 shadow-xl relative overflow-hidden">
      {/* Background ambient gradient */}
      <div className="absolute -top-16 -right-16 h-36 w-36 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />

      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <UploadCloud className="h-4 w-4" />
          </div>
          <h2 className="text-sm font-semibold tracking-wide text-white uppercase font-mono">
            Compliance PDF Ingest & Textlayer Validation
          </h2>
        </div>
        <span className="text-[11px] font-mono text-slate-400">
          Max. {(maxSizeBytes / (1024 * 1024)).toFixed(0)} MB | PDF (digitaler Textlayer)
        </span>
      </div>

      {/* Dropzone container */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isUploading && fileInputRef.current?.click()}
        className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-all ${
          isDragging
            ? "border-cyan-400 bg-cyan-950/20 scale-[0.995]"
            : "border-slate-700/70 bg-slate-950/40 hover:border-slate-600 hover:bg-slate-900/40"
        } ${isUploading ? "pointer-events-none opacity-80" : ""}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={handleFileSelect}
        />

        <div className="flex flex-col items-center space-y-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 border border-slate-700 group-hover:border-cyan-500/40 group-hover:text-cyan-400 text-slate-400 transition-colors">
            {isUploading ? (
              <RefreshCw className="h-6 w-6 animate-spin text-cyan-400" />
            ) : (
              <UploadCloud className="h-6 w-6" />
            )}
          </div>

          <div className="text-sm font-medium text-slate-200">
            <span className="text-cyan-400 underline underline-offset-4 group-hover:text-cyan-300">
              PDF auswählen
            </span>{" "}
            oder per Drag & Drop hierher ziehen
          </div>

          <p className="text-xs text-slate-400 max-w-md">
            Verträge, Rechnungen oder Spezifikationen (VO (EU) 2024/1689 Anhang III & DSGVO Art. 9/10 Prüfung)
          </p>
        </div>

        {/* Progress Bar when uploading */}
        {isUploading && (
          <div className="mt-4 w-full max-w-md space-y-1.5">
            <div className="flex justify-between text-xs font-mono text-slate-400">
              <span className="text-cyan-300">Upload & Validierung läuft...</span>
              <span className="text-white font-bold">{uploadProgress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full bg-gradient-to-r from-cyan-500 via-emerald-400 to-indigo-500 transition-all duration-300 shadow-[0_0_12px_rgba(6,182,212,0.6)]"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Success Notification */}
      {successInfo && (
        <div className="mt-3 flex items-center space-x-2 rounded-xl border border-emerald-500/30 bg-emerald-950/30 p-2.5 text-xs text-emerald-300">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
          <span>{successInfo}</span>
        </div>
      )}

      {/* Error Notification */}
      {errorMessage && (
        <div className="mt-3 flex items-center space-x-2 rounded-xl border border-red-500/40 bg-red-950/40 p-2.5 text-xs text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
          <span>{errorMessage}</span>
        </div>
      )}
    </div>
  );
};
