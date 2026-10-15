"use client";

import React, { useEffect, useState } from "react";
import { api, ApiError, getAccessKey, getApiBase, setAccessKey } from "../lib/api";
import type { ConnectionTestResult, InferenceMode, PiiStrictness, RuntimeSettings } from "../types/api";
import { cx } from "../lib/format";
import { CheckCircle, Eye, EyeOff, Lock, XCircle } from "./icons";
import { useTheme, type Theme } from "./ThemeProvider";
import { Modal, Segmented, Spinner, Tabs, Toggle } from "./ui";

type Tab = "inference" | "compliance" | "connection" | "appearance";

const PROVIDERS: { mode: InferenceMode; title: string; text: string; dot: string }[] = [
  { mode: "local", title: "Lokal (Ollama Engine)", text: "On-Premises Zero-Data-Leakage – Inferenz verlässt die lokale Umgebung nicht.", dot: "bg-ok" },
  { mode: "gemini", title: "Google Gemini API", text: "Enterprise Multimodal-Inferenz & Hochgeschwindigkeits-Extraktion.", dot: "bg-sky-500" },
  { mode: "anthropic", title: "Anthropic Claude API", text: "Inferenz mit hoher juristischer Begründungstiefe.", dot: "bg-violet-500" },
  { mode: "openai", title: "OpenAI GPT API", text: "Strukturierte Extraktion im JSON-Modus.", dot: "bg-orange-500" },
];

const STRICTNESS: { value: PiiStrictness; label: string; text: string }[] = [
  { value: "strict", label: "Strikt", text: "Schwärzt Namen, Firmen, Adressen, Beträge, Datumsangaben, IBAN, Steuer-IDs, Kontakt- und Art.-9-Daten." },
  { value: "standard", label: "Standard", text: "Schwärzt IBAN, Steuernummer/USt-IdNr., E-Mail, Telefon, Kennnummern und Art.-9-Daten; Übriges wird markiert." },
  { value: "audit_only", label: "Audit-Only", text: "Markiert alle Treffer, schwärzt nichts – nur für interne Revisoren mit Berechtigung." },
];

interface Props {
  open: boolean;
  settings: RuntimeSettings | null;
  onClose: () => void;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: (tone: "ok" | "bad", title: string, message?: string) => void;
}

export function SettingsModal({ open, settings, onClose, onSaved, onAccessChanged, notify }: Props) {
  const [tab, setTab] = useState<Tab>("inference");
  const [mode, setMode] = useState<InferenceMode>("local");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const [accessKey, setAccessKeyState] = useState("");
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    if (!open || !settings) return;
    setMode(settings.inference_mode);
    setModel(settings.models[settings.inference_mode]);
    setApiKey("");
    setResult(null);
    setAccessKeyState(getAccessKey());
  }, [open, settings]);

  useEffect(() => {
    if (settings) setModel(settings.models[mode]);
    setApiKey("");
    setResult(null);
  }, [mode, settings]);

  const hasKey = mode !== "local" && Boolean(settings?.[`has_${mode}_key` as keyof RuntimeSettings]);
  const maskedKey = mode !== "local" ? settings?.masked_keys?.[mode] : null;

  async function saveInference() {
    setBusy(true);
    setResult(null);
    try {
      const updated = await api.updateSettings({
        inference_mode: mode,
        models: { [mode]: model },
        ...(apiKey && mode !== "local" ? { api_keys: { [mode]: apiKey } } : {}),
      });
      onSaved(updated);
      setApiKey("");
      setResult(await api.testConnection(mode));
    } catch (err) {
      notify("bad", "Speichern fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function updateCompliance(update: Parameters<typeof api.updateSettings>[0]) {
    try {
      onSaved(await api.updateSettings(update));
    } catch (err) {
      notify("bad", "Speichern fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    }
  }

  async function removeKey() {
    if (mode === "local") return;
    try {
      onSaved(await api.updateSettings({ api_keys: { [mode]: "" } }));
      notify("ok", "API-Key gelöscht");
    } catch (err) {
      notify("bad", "Löschen fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Einstellungen" subtitle="Inferenz-Provider, Prüfstrenge und Verbindung" width="max-w-3xl">
      <Tabs<Tab>
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "inference", label: "Inferenz & KI-Provider" },
          { key: "compliance", label: "Compliance & Audit-Strenge" },
          { key: "connection", label: "Verbindung" },
          { key: "appearance", label: "Darstellung" },
        ]}
      />

      {!settings && (tab === "inference" || tab === "compliance") && (
        <p className="py-8 text-center text-sm text-subtle">Backend nicht erreichbar – Einstellungen können nicht geladen werden.</p>
      )}

      {settings && tab === "inference" && (
        <div className="space-y-4 pt-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Inferenz-Provider">
            {PROVIDERS.map((provider) => (
              <button
                key={provider.mode}
                role="radio"
                aria-checked={mode === provider.mode}
                onClick={() => setMode(provider.mode)}
                className={cx(
                  "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors duration-150",
                  mode === provider.mode ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
                )}
              >
                <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", provider.dot)} />
                <span>
                  <span className="block text-sm font-medium text-fg">{provider.title}</span>
                  <span className="block text-xs text-subtle">{provider.text}</span>
                  {settings.inference_mode === provider.mode && <span className="chip mt-1.5 border-ok-line bg-ok-soft text-ok">aktiv</span>}
                </span>
              </button>
            ))}
          </div>

          {mode !== "local" && (
            <div className="flex gap-2 rounded-lg border border-pii-line bg-pii-soft p-3 text-xs text-pii">
              <Lock size={14} className="mt-0.5 shrink-0" />
              <p>
                <strong>Privacy Gateway:</strong> Die Pseudonymisierung (Art. 4 Nr. 5 DSGVO) läuft lokal im Backend (Python), bevor
                Daten den Server verlassen – ein lokales Ollama ist dafür nicht nötig. Erkannte Namen mit Anrede oder Rolle, Firmen,
                IBANs, Steuer-IDs, Adressen, Kontaktdaten und Beträge gehen nur als Platzhalter an den Anbieter und werden lokal
                re-identifiziert. Pseudonymisierte Daten bleiben personenbezogen: AV-Vertrag und Transfergrundlage bleiben erforderlich.
              </p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label-caps">Modell-ID</span>
              <input
                className="input mt-1 font-mono"
                name="model"
                list={`models-${mode}`}
                value={model}
                autoComplete="off"
                spellCheck={false}
                placeholder="z. B. Modellname manuell eingeben…"
                onChange={(e) => setModel(e.target.value)}
              />
              <datalist id={`models-${mode}`}>
                {settings.suggested_models[mode]?.map((name) => <option key={name} value={name} />)}
              </datalist>
              <span className="mt-1 block text-xs text-subtle">
                Vorschläge im Dropdown verfügbar oder beliebige neue Modell-ID eintragen.
              </span>
            </label>
            {mode !== "local" && (
              <label className="block">
                <span className="label-caps">API-Key {hasKey && <span className="normal-case tracking-normal text-ok">· hinterlegt ({maskedKey})</span>}</span>
                <div className="relative mt-1">
                  <input
                    className="input pr-9 font-mono"
                    type={showKey ? "text" : "password"}
                    name={`${mode}-api-key`}
                    value={apiKey}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={hasKey ? "Neuen Key eingeben, um ihn zu ersetzen…" : "Key eingeben…"}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle hover:text-fg"
                    onClick={() => setShowKey((v) => !v)}
                    aria-label={showKey ? "Key verbergen" : "Key anzeigen"}
                  >
                    {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <span className="mt-1 block text-xs text-subtle">Serverseitig Fernet-verschlüsselt gespeichert, nur maskiert zurückgegeben.</span>
              </label>
            )}
          </div>

          {result && (
            <div className={cx("flex items-start gap-2 rounded-lg border p-3 text-xs", result.ok ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad")}>
              {result.ok ? <CheckCircle size={14} className="mt-0.5" /> : <XCircle size={14} className="mt-0.5" />}
              <span>{result.message}</span>
            </div>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            {hasKey && <button className="btn" onClick={removeKey}>Key löschen</button>}
            <button className="btn btn-primary" onClick={saveInference} disabled={busy || !model.trim() || (mode !== "local" && !hasKey && !apiKey)}>
              {busy && <Spinner size={13} />}
              Speichern & Verbindung testen
            </button>
          </div>
        </div>
      )}

      {settings && tab === "compliance" && (
        <div className="space-y-4 pt-4">
          <div>
            <p className="label-caps mb-2">PII-Maskierungsgrad (Textansicht & Vorschau)</p>
            <Segmented<PiiStrictness>
              value={settings.pii_strictness}
              onChange={(value) => updateCompliance({ pii_strictness: value })}
              options={STRICTNESS.map(({ value, label }) => ({ value, label }))}
            />
            <p className="mt-2 text-xs text-subtle">{STRICTNESS.find((s) => s.value === settings.pii_strictness)?.text}</p>
            <p className="mt-1 text-xs text-subtle">PII-Befunde werden unabhängig von dieser Stufe ausschließlich maskiert gespeichert.</p>
          </div>
          <Toggle
            checked={settings.enforce_ustg_check}
            onChange={(value) => updateCompliance({ enforce_ustg_check: value })}
            label="§ 14 UStG Check erzwingen"
            description="Prüft bei Rechnungen alle Pflichtangaben nach § 14 Abs. 4 UStG und fließt in den Score ein."
          />
          <Toggle
            checked={settings.ai_act_escalation}
            onChange={(value) => updateCompliance({ ai_act_escalation: value })}
            label="EU AI Act Hochrisiko-Eskalation"
            description="Stuft automatisch auf „Hochrisiko“, sobald eine Anhang-III-Kategorie belegt ist – auch wenn das Modell niedriger bewertet."
          />
          <p className="text-xs text-subtle">Änderungen gelten für die nächste Analyse; bestehende Prüfergebnisse bleiben unverändert im Ledger.</p>
        </div>
      )}

      {tab === "connection" && (
        <div className="space-y-4 pt-4">
          <div>
            <p className="label-caps">Backend-Adresse</p>
            <p className="mt-1 font-mono text-sm text-fg">{getApiBase()}</p>
            <p className="mt-1 text-xs text-subtle">Automatisch ermittelt (NEXT_PUBLIC_API_BASE_URL, gleicher Host :8001, 127.0.0.1, localhost).</p>
          </div>
          <label className="block">
            <span className="label-caps">Zugangsschlüssel (X-API-Key)</span>
            <input
              className="input mt-1 font-mono"
              type="password"
              value={accessKey}
              onChange={(e) => setAccessKeyState(e.target.value)}
              placeholder="Nur nötig, wenn API_KEY im Backend gesetzt ist…"
              name="access-key"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <div className="flex justify-end">
            <button
              className="btn btn-primary"
              onClick={() => {
                setAccessKey(accessKey.trim());
                onAccessChanged();
                notify("ok", "Zugangsschlüssel gespeichert", "Nur in diesem Browser (localStorage).");
              }}
            >
              Übernehmen
            </button>
          </div>
        </div>
      )}
      {tab === "appearance" && (
        <div className="space-y-2 pt-4">
          <p className="label-caps">Farbschema</p>
          <Segmented<Theme>
            value={theme}
            onChange={setTheme}
            options={[
              { value: "dark", label: "Dunkel" },
              { value: "light", label: "Hell" },
            ]}
          />
          <p className="text-xs text-subtle">
            Dunkel ist der Standard für lange Prüfsitzungen; Hell eignet sich für Präsentationen und Ausdrucke. Gilt nur in
            diesem Browser.
          </p>
        </div>
      )}
    </Modal>
  );
}
