"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError, getAccessKey, getApiBase, setAccessKey } from "../lib/api";
import type {
  CloudMode,
  ConnectionTestResult,
  HealthResponse,
  InferenceMode,
  LocalAiStatus,
  ModelCatalog,
  PiiStrictness,
  RedactResult,
  RuntimeSettings,
  SettingsUpdate,
} from "../types/api";
import { cx, formatModel, PROVIDER_NAMES } from "../lib/format";
import {
  ArrowUpCircle,
  CheckCircle,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Layers,
  Lock,
  Palette,
  Play,
  Plus,
  Power,
  Scale,
  Server,
  Sliders,
  Trash,
  XCircle,
} from "./icons";
import { ReleasePanel } from "./ReleaseAssistant";
import { Select } from "./Select";
import { useTheme, type ThemeChoice } from "./ThemeProvider";
import { AutoTextarea, Modal, Segmented, Spinner, Toggle, Tooltip } from "./ui";

type Section = "models" | "cascade" | "compliance" | "appearance" | "system" | "about";
type Notify = (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;

const SECTIONS: { key: Section; label: string; icon: React.ReactNode }[] = [
  { key: "models", label: "KI-Modelle", icon: <Sliders size={15} aria-hidden="true" /> },
  { key: "cascade", label: "Ausweich-Kaskade", icon: <Layers size={15} aria-hidden="true" /> },
  { key: "compliance", label: "Compliance & DLP", icon: <Scale size={15} aria-hidden="true" /> },
  { key: "appearance", label: "Darstellung", icon: <Palette size={15} aria-hidden="true" /> },
  { key: "system", label: "System & Verbindung", icon: <Server size={15} aria-hidden="true" /> },
  { key: "about", label: "Updates & Über", icon: <ArrowUpCircle size={15} aria-hidden="true" /> },
];

const CLOUD: { value: CloudMode; label: string }[] = [
  { value: "gemini", label: "Google Gemini" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "openai", label: "OpenAI" },
];

const STRICTNESS: { value: PiiStrictness; label: string; text: string }[] = [
  { value: "strict", label: "Strikt", text: "Schwärzt Namen, Firmen, Adressen, Beträge, Datumsangaben, IBAN, Steuer-IDs, Kontakt- und Art.-9-Daten." },
  { value: "standard", label: "Standard", text: "Schwärzt IBAN, Steuernummer/USt-IdNr., E-Mail, Telefon, Kennnummern und Art.-9-Daten; Übriges wird markiert." },
  { value: "audit_only", label: "Audit-Only", text: "Markiert alle Treffer, schwärzt nichts – nur für interne Revisoren mit Berechtigung." },
];

const STAGE_LABELS: Record<string, string> = {
  primary: "Hauptmodell",
  ausweichmodell: "Ausweichmodell",
  ausweich_schluessel: "Ausweich-Schlüssel",
  fallback: "Anbieter-Fallback",
};

interface Props {
  open: boolean;
  settings: RuntimeSettings | null;
  health: HealthResponse | null;
  version: string;
  onClose: () => void;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: Notify;
}

const hasKey = (settings: RuntimeSettings | null, mode: InferenceMode) =>
  mode === "local" || Boolean(settings?.[`has_${mode}_key` as keyof RuntimeSettings]);

/** Modell-Katalog des Providers (neueste zuerst, live aus der API); ohne Key die Vorschlagsliste. */
function useCatalog(provider: InferenceMode, enabled: boolean, settings: RuntimeSettings | null) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const keyStored = hasKey(settings, provider);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setCatalog(null);
    api.models(provider).then((result) => alive && setCatalog(result)).catch(() => alive && setCatalog(null));
    return () => {
      alive = false;
    };
  }, [provider, enabled, keyStored]);
  return catalog;
}

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <span className="label-caps flex items-center gap-1.5">
        {label}
        {hint && (
          <Tooltip content={hint}>
            <span tabIndex={0} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
          </Tooltip>
        )}
      </span>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function SectionTitle({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      {text && <p className="mt-0.5 text-xs leading-relaxed text-subtle">{text}</p>}
    </div>
  );
}

function ModelSelect({ provider, value, onChange, catalog, label, allowOff, exclude }: {
  provider: InferenceMode;
  value: string;
  onChange: (model: string) => void;
  catalog: ModelCatalog | null;
  label: string;
  allowOff?: boolean;
  exclude?: string;
}) {
  const names = (catalog?.models ?? []).filter((name) => name !== exclude);
  const all = value && !names.includes(value) ? [value, ...names] : names;
  const options = [
    ...(allowOff ? [{ value: "", label: "Aus – direkt zur nächsten Stufe" }] : []),
    ...all.map((name, index) => ({
      value: name,
      label: name,
      hint: index === 0 && catalog?.source === "api" && !allowOff ? "neuestes verfügbares Modell" : name === catalog?.current ? "aktuell eingestellt" : undefined,
    })),
  ];
  return (
    <Field
      label={label}
      hint={catalog?.source === "api" ? "Liste live aus der API des Anbieters, neueste zuerst." : catalog?.message ?? "Vorschlagsliste – mit hinterlegtem Key kommt die Liste direkt vom Anbieter."}
    >
      {catalog ? (
        <Select value={value} onChange={onChange} ariaLabel={`${label} (${PROVIDER_NAMES[provider]})`} width={320} className="h-9 w-full justify-between" options={options} />
      ) : (
        <div className="flex h-9 items-center gap-2 text-xs text-subtle"><Spinner size={12} /> Modelle werden geladen…</div>
      )}
    </Field>
  );
}

function KeyInput({ value, onChange, placeholder, name }: { value: string; onChange: (value: string) => void; placeholder: string; name: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        className="input h-9 pr-9 font-mono"
        type={show ? "text" : "password"}
        name={name}
        value={value}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <button
        type="button"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle transition-colors duration-150 hover:text-fg"
        onClick={() => setShow((visible) => !visible)}
        aria-label={show ? "Key verbergen" : "Key anzeigen"}
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

function useSave(onSaved: (settings: RuntimeSettings) => void, notify: Notify) {
  const [busy, setBusy] = useState(false);
  const save = useCallback(
    async (update: SettingsUpdate) => {
      setBusy(true);
      try {
        const updated = await api.updateSettings(update);
        onSaved(updated);
        return updated;
      } catch (err) {
        notify("bad", "Speichern fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [onSaved, notify],
  );
  return { busy, save };
}

/** 1-Klick Start/Stopp fuer Ollama (nur direkt am Server; im Container ueber docker compose). */
function LocalAiControl({ active, onChanged, notify }: { active: boolean; onChanged: () => void; notify: Notify }) {
  const [status, setStatus] = useState<LocalAiStatus | null>(null);
  const [busy, setBusy] = useState<"start" | "stop" | null>(null);
  const load = useCallback(() => {
    api.localAi().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  async function run(kind: "start" | "stop") {
    setBusy(kind);
    try {
      const result = kind === "start" ? await api.startOllama() : await api.stopLocalAi();
      notify(result.ok ? "ok" : "warn", kind === "start" ? "Lokale KI starten" : "Lokale KI stoppen", result.message);
      onChanged();
    } catch (err) {
      notify("warn", kind === "start" ? "Lokale KI nicht gestartet" : "Lokale KI nicht gestoppt", err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err));
    } finally {
      setBusy(null);
      load();
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium text-fg">
          <span className={cx("h-2 w-2 rounded-full", status?.running ? "bg-ok" : "bg-subtle")} aria-hidden="true" />
          Lokale KI (Ollama)
        </p>
        <p className="mt-0.5 text-xs text-subtle">
          {status ? status.text : "Status wird ermittelt…"}
          {status && !status.control_allowed && status.controllable && " Start und Stopp nur direkt am Server (http://127.0.0.1)."}
        </p>
      </div>
      <div className="flex gap-2">
        {status?.startable && status.control_allowed && (
          <button className="btn btn-sm" onClick={() => void run("start")} disabled={busy !== null}>
            {busy === "start" ? <Spinner size={11} /> : <Play size={11} aria-hidden="true" />} Starten
          </button>
        )}
        {status?.stoppable && status.control_allowed && (
          <Tooltip content="Beendet Ollama und gibt den Grafikspeicher frei. Während einer Prüfung gesperrt." align="right">
            <button className="btn btn-sm" onClick={() => void run("stop")} disabled={busy !== null}>
              {busy === "stop" ? <Spinner size={11} /> : <Power size={11} aria-hidden="true" />} Stoppen
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  );
}

function ModelsSection({ settings, active, onSaved, onAccessChanged, notify }: {
  settings: RuntimeSettings;
  active: boolean;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: Notify;
}) {
  const [location, setLocation] = useState<"local" | "cloud">(settings.inference_mode === "local" ? "local" : "cloud");
  const [provider, setProvider] = useState<CloudMode>(settings.inference_mode === "local" ? "gemini" : settings.inference_mode);
  const [model, setModel] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const { busy, save } = useSave(onSaved, notify);
  const mode: InferenceMode = location === "local" ? "local" : provider;
  const catalog = useCatalog(mode, active, settings);
  const keyStored = hasKey(settings, mode);

  useEffect(() => {
    if (!active) return;
    setLocation(settings.inference_mode === "local" ? "local" : "cloud");
    if (settings.inference_mode !== "local") setProvider(settings.inference_mode);
    setResult(null);
    // Nur beim Oeffnen synchronisieren - nicht bei jedem Speichern.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // Modell je Provider: das gespeicherte; ist noch kein Key hinterlegt, das neueste aus dem Katalog.
  useEffect(() => {
    const fresh = mode !== "local" && !hasKey(settings, mode) && catalog?.source === "api";
    setModel(fresh && catalog?.models[0] ? catalog.models[0] : settings.models[mode]);
    setFallbackModel(mode === "local" ? "" : settings.ausweich_modelle?.[mode] ?? "");
    setApiKey("");
  }, [mode, settings, catalog]);

  async function saveAndTest() {
    const update: SettingsUpdate = { inference_mode: mode, models: { [mode]: model } };
    if (mode !== "local") {
      update.ausweich_modelle = { [mode]: fallbackModel };
      if (apiKey) update.api_keys = { [mode]: apiKey };
    }
    setResult(null);
    const updated = await save(update);
    if (!updated) return;
    setApiKey("");
    try {
      setResult(await api.testConnection(mode));
    } catch (err) {
      setResult({ ok: false, provider: mode, model, message: err instanceof ApiError ? err.message : String(err) });
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title="KI-Modelle"
        text="Hauptmodell und Ausweichmodell desselben Anbieters. Jeder Modellwechsel wird mit Modell-ID, Prompt-Hash und Zeitstempel signiert im Ledger verankert – nie still."
      />
      <div className="flex flex-wrap items-center gap-3">
        <Segmented<"local" | "cloud">
          ariaLabel="Inferenz-Ort"
          value={location}
          onChange={setLocation}
          options={[
            { value: "local", label: "Lokal (Ollama)" },
            { value: "cloud", label: "Cloud (API)" },
          ]}
        />
        {location === "cloud" && <Select<CloudMode> value={provider} onChange={setProvider} options={CLOUD} ariaLabel="Cloud-Anbieter" width={220} className="h-8" />}
      </div>

      {catalog?.upgrade && catalog.upgrade !== model && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ok-line bg-ok-soft px-3 py-2 text-xs text-fg">
          <ArrowUpCircle size={14} className="text-ok" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            Neueres Modell derselben Klasse verfügbar: <span className="font-semibold">{catalog.upgrade}</span>. Die Übernahme wird im Ledger verankert.
          </span>
          <button className="btn btn-sm" disabled={busy} onClick={() => void save({ models: { [mode]: catalog.upgrade! } })}>Übernehmen</button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ModelSelect provider={mode} value={model} onChange={setModel} catalog={catalog} label="Hauptmodell" />
        {mode !== "local" && (
          <ModelSelect
            provider={mode}
            value={fallbackModel}
            onChange={setFallbackModel}
            catalog={catalog}
            label="Ausweichmodell bei Überlast"
            allowOff
            exclude={model}
          />
        )}
        {mode !== "local" && (
          <Field
            label={`API-Key ${PROVIDER_NAMES[mode]}${keyStored ? ` · hinterlegt (${settings.masked_keys?.[mode] ?? "…"})` : ""}`}
            hint="Serverseitig Fernet-verschlüsselt gespeichert und nur maskiert zurückgegeben. Weitere Schlüssel unter „Ausweich-Kaskade“."
          >
            <KeyInput
              value={apiKey}
              onChange={setApiKey}
              name={`${mode}-api-key`}
              placeholder={keyStored ? "Neuen Key eingeben, um ihn zu ersetzen…" : "Key eingeben…"}
            />
          </Field>
        )}
      </div>

      {mode !== "local" && fallbackModel === "" && settings.suggested_fallback_models?.[mode] && (
        <p className="text-xs text-subtle">
          Tipp: <button type="button" className="font-medium text-accent hover:underline" onClick={() => setFallbackModel(settings.suggested_fallback_models[mode])}>
            {settings.suggested_fallback_models[mode]}
          </button>{" "}
          als Ausweichmodell übernimmt bei Überlast des Hauptmodells, bevor die Kaskade den Anbieter wechselt.
        </p>
      )}

      {mode !== "local" && (
        <details className="group rounded-lg border border-pii-line bg-pii-soft px-3 py-2 text-xs text-fg">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-pii">
            <Lock size={13} aria-hidden="true" /> Privacy Gateway: vor jedem Cloud-Aufruf lokal pseudonymisiert (Art. 4 Nr. 5 DSGVO)
            <span className="ml-auto text-subtle transition-transform duration-150 group-open:rotate-90" aria-hidden="true">›</span>
          </summary>
          <p className="mt-2 leading-relaxed text-muted">
            Erkannte Namen mit Anrede oder Rolle, Firmen, IBANs, Steuer-IDs, Adressen, Kontaktdaten und Beträge gehen nur als
            Platzhalter an den Anbieter und werden lokal re-identifiziert; das Mapping verlässt den Server nie. Pseudonymisierte
            Daten bleiben personenbezogen: AV-Vertrag und Transfergrundlage sind für jeden Anbieter der Kaskade nötig.
          </p>
        </details>
      )}

      {result && (
        <div className={cx("flex flex-wrap items-start gap-2 rounded-lg border p-3 text-xs", result.ok ? "border-ok-line bg-ok-soft text-fg" : "border-bad-line bg-bad-soft text-fg")}>
          {result.ok ? <CheckCircle size={14} className="mt-0.5 text-ok" /> : <XCircle size={14} className="mt-0.5 text-bad" />}
          <span className="min-w-0 flex-1">{result.message}</span>
          {result.suggested_model && (
            <button className="btn btn-sm" disabled={busy} onClick={() => void save({ models: { local: result.suggested_model! } }).then(() => setResult(null))}>
              {formatModel(result.suggested_model)} übernehmen
            </button>
          )}
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {mode !== "local" && keyStored && (
          <button className="btn" disabled={busy} onClick={() => void save({ api_keys: { [mode]: "" } }).then((ok) => ok && notify("ok", "API-Key gelöscht"))}>
            Key löschen
          </button>
        )}
        <button className="btn btn-primary" onClick={() => void saveAndTest()} disabled={busy || !model.trim() || (mode !== "local" && !keyStored && !apiKey)}>
          {busy && <Spinner size={13} />} Speichern &amp; Verbindung testen
        </button>
      </div>

      <div className="border-t border-line pt-4">
        <LocalAiControl active={active} onChanged={onAccessChanged} notify={notify} />
      </div>
    </div>
  );
}

function CascadeSection({ settings, onSaved, notify }: { settings: RuntimeSettings; onSaved: (settings: RuntimeSettings) => void; notify: Notify }) {
  const { busy, save } = useSave(onSaved, notify);
  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState<CloudMode>("gemini");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const backups = settings.ausweich_schluessel ?? [];
  const fallbacks = settings.fallbacks ?? [];
  const localFallback = fallbacks.includes("local");
  const keyed = (["gemini", "anthropic", "openai"] as CloudMode[]).filter(
    (mode) => mode !== settings.inference_mode && hasKey(settings, mode) && !fallbacks.includes(mode),
  );
  const isCloud = settings.inference_mode !== "local";
  const existing = () => backups.map(({ id, provider: p, model: m }) => ({ id, provider: p, model: m }));

  async function addBackup() {
    const ok = await save({
      ausweich_schluessel: [...existing(), { id: `k${Date.now().toString(36)}`, provider, model: model.trim() || undefined, api_key: key.trim() }],
    });
    if (ok) {
      setKey("");
      setModel("");
      setAdding(false);
      notify("ok", "Ausweich-Schlüssel hinzugefügt", "Verschlüsselt gespeichert; die Kaskade ist im Ledger verankert.");
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Ausweich-Kaskade"
        text={`Bei HTTP 408, 429, 5xx, Verbindungsfehler oder Zeitüberschreitung wiederholt jede Stufe zunächst (${(settings.retry_delays ?? []).map((s) => `${s} s`).join(", ") || "ohne Pause"}), dann übernimmt die nächste. Abgelehnte Keys (401/403) und Schemafehler lösen bewusst keinen Wechsel aus. Jeder Wechsel steht als provider_failover im Ledger; alle Cloud-Stufen laufen durch denselben Privacy Vault.`}
      />

      <ol className="space-y-1.5" aria-label="Effektive Kaskade">
        {(settings.chain ?? []).map((stage, index) => (
          <li key={`${stage.stage}-${stage.backup_id ?? stage.provider}-${index}`} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
            <span className="w-6 text-right text-xs tabular-nums text-subtle">{index + 1}</span>
            <span className="w-36 shrink-0 text-xs text-subtle">{STAGE_LABELS[stage.stage]}</span>
            <span className="min-w-0 flex-1 truncate text-fg">{PROVIDER_NAMES[stage.provider]}</span>
            <span className="truncate text-xs text-muted">{stage.model}</span>
          </li>
        ))}
        <li className="flex items-center gap-3 rounded-lg border border-dashed border-line px-3 py-2 text-sm">
          <span className="w-6 text-right text-xs tabular-nums text-subtle">{(settings.chain?.length ?? 0) + 1}</span>
          <span className="w-36 shrink-0 text-xs text-subtle">Letzte Stufe</span>
          <span className="min-w-0 flex-1 text-fg">Deterministisches Regelwerk</span>
          <span className={cx("text-xs", settings.heuristic_fallback ? "text-ok" : "text-subtle")}>
            {settings.heuristic_fallback ? "aktiv · gekennzeichnet" : "aus (HEURISTIC_FALLBACK)"}
          </span>
        </li>
      </ol>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="label-caps">Ausweich-Schlüssel <span className="normal-case tracking-normal tabular-nums">({backups.length}/{settings.max_ausweich_schluessel ?? 6})</span></p>
          {!adding && backups.length < (settings.max_ausweich_schluessel ?? 6) && (
            <button className="btn btn-sm" onClick={() => setAdding(true)} disabled={busy}>
              <Plus size={13} aria-hidden="true" /> Weiteren API-Schlüssel hinzufügen
            </button>
          )}
        </div>
        {!isCloud && (
          <p className="text-xs text-subtle">Gilt nur, wenn ein Cloud-Anbieter aktiv ist – eine lokal eingestellte Prüfung geht nie automatisch in die Cloud.</p>
        )}
        {backups.length > 0 && (
          <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line">
            {backups.map((backup, index) => (
              <li key={backup.id} className="flex items-center gap-2.5 px-3 py-2 text-xs">
                <span className="w-16 shrink-0 tabular-nums text-subtle">Backup {index + 1}</span>
                <KeyRound size={13} className="shrink-0 text-ok" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-fg">
                  {PROVIDER_NAMES[backup.provider]} · {backup.model}
                  <span className="ml-1.5 font-mono text-subtle">{backup.key_hint}</span>
                </span>
                <button
                  type="button"
                  className="rounded-md p-1 text-subtle transition-colors duration-150 hover:text-bad"
                  disabled={busy}
                  onClick={() => void save({ ausweich_schluessel: existing().filter((item) => item.id !== backup.id) })}
                  aria-label={`Backup ${index + 1} (${PROVIDER_NAMES[backup.provider]}) entfernen`}
                >
                  <Trash size={13} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ol>
        )}
        {adding && (
          <div className="space-y-3 rounded-lg border border-line bg-surface-2 p-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Anbieter">
                <Select<CloudMode> value={provider} onChange={setProvider} options={CLOUD} ariaLabel="Anbieter des Ausweich-Schlüssels" width={240} className="h-9 w-full justify-between" />
              </Field>
              <Field label="Modell (optional)" hint="Leer = Hauptmodell dieses Anbieters.">
                <input className="input h-9" value={model} onChange={(event) => setModel(event.target.value)} placeholder={settings.models[provider]} name="backup-model" autoComplete="off" />
              </Field>
            </div>
            <Field label="API-Key">
              <KeyInput value={key} onChange={setKey} name="backup-api-key" placeholder="Schlüssel eingeben (auch ein zweiter Key desselben Anbieters)…" />
            </Field>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setAdding(false)}>Abbrechen</button>
              <button className="btn btn-primary" disabled={busy || key.trim().length < 8} onClick={() => void addBackup()}>
                {busy && <Spinner size={13} />} Zur Kaskade hinzufügen
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <p className="label-caps">Anbieter-Fallbacks</p>
        {isCloud ? (
          <Toggle
            checked={localFallback}
            onChange={(value) => void save({ fallbacks: value ? [...fallbacks.filter((item) => item !== "local"), "local"] : fallbacks.filter((item) => item !== "local") })}
            label="Lokal ausweichen (Ollama)"
            description="Fallen alle Cloud-Stufen aus, prüft das lokale Modell – kein Dokumentinhalt verlässt dann den Rechner."
          />
        ) : (
          <p className="text-xs text-subtle">Lokal ist das Hauptmodell; fällt es aus, schließt das Regelwerk die Prüfung gekennzeichnet ab.</p>
        )}
        {fallbacks.filter((item) => item !== "local").map((item) => (
          <div key={item} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs">
            <span className="min-w-0 flex-1 text-fg">{PROVIDER_NAMES[item]} · {settings.models[item]} <span className="text-subtle">(Hauptschlüssel)</span></span>
            <button type="button" className="rounded-md p-1 text-subtle transition-colors duration-150 hover:text-bad" disabled={busy} onClick={() => void save({ fallbacks: fallbacks.filter((entry) => entry !== item) })} aria-label={`${PROVIDER_NAMES[item]} entfernen`}>
              <Trash size={13} aria-hidden="true" />
            </button>
          </div>
        ))}
        {keyed.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-subtle">
            Weiteren Anbieter mit hinterlegtem Hauptschlüssel anhängen:
            {keyed.map((mode) => (
              <button key={mode} className="btn btn-sm" disabled={busy} onClick={() => void save({ fallbacks: [...fallbacks.filter((item) => item !== "local"), mode, ...(localFallback ? ["local" as const] : [])] })}>
                <Plus size={12} aria-hidden="true" /> {PROVIDER_NAMES[mode]}
              </button>
            ))}
          </div>
        )}
      </section>

      {settings.cloud_budget && (
        <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
          Cloud-Tagesbudget:{" "}
          {settings.cloud_budget.enabled ? (
            <>
              <span className="tabular-nums">{settings.cloud_budget.tokens.toLocaleString("de-DE")}</span> von{" "}
              <span className="tabular-nums">{settings.cloud_budget.limit.toLocaleString("de-DE")}</span> Tokens heute verbraucht.
            </>
          ) : (
            <>ohne Limit (<span className="font-mono">CLOUD_DAILY_TOKEN_LIMIT=-1</span>); heute <span className="tabular-nums">{settings.cloud_budget.tokens.toLocaleString("de-DE")}</span> Tokens.</>
          )}
        </p>
      )}
    </div>
  );
}

function ComplianceSection({ settings, onSaved, notify }: { settings: RuntimeSettings; onSaved: (settings: RuntimeSettings) => void; notify: Notify }) {
  const { save } = useSave(onSaved, notify);
  const [probe, setProbe] = useState("");
  const [result, setResult] = useState<RedactResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function runProbe() {
    setBusy(true);
    try {
      setResult(await api.redact(probe));
    } catch (err) {
      notify("bad", "Probe-Schwärzung fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle title="Compliance & DLP" text="Änderungen gelten für die nächste Analyse; bestehende Prüfergebnisse bleiben unverändert im Ledger." />
      <div>
        <p className="label-caps mb-2">PII-Maskierungsgrad (Textansicht & Vorschau)</p>
        <Segmented<PiiStrictness>
          ariaLabel="PII-Maskierungsgrad"
          value={settings.pii_strictness}
          onChange={(value) => void save({ pii_strictness: value })}
          options={STRICTNESS.map(({ value, label }) => ({ value, label }))}
        />
        <p className="mt-2 text-xs text-muted">{STRICTNESS.find((s) => s.value === settings.pii_strictness)?.text}</p>
        <p className="mt-1 text-xs text-subtle">PII-Befunde werden unabhängig von dieser Stufe ausschließlich maskiert gespeichert.</p>
      </div>
      <Toggle
        checked={settings.enforce_ustg_check}
        onChange={(value) => void save({ enforce_ustg_check: value })}
        label="§ 14 UStG Check erzwingen"
        description="Prüft bei Rechnungen alle Pflichtangaben nach § 14 Abs. 4 UStG und fließt in den Score ein."
      />
      <Toggle
        checked={settings.ai_act_escalation}
        onChange={(value) => void save({ ai_act_escalation: value })}
        label="EU AI Act Hochrisiko-Eskalation"
        description="Stuft automatisch auf „Hochrisiko“, sobald eine Anhang-III-Kategorie belegt ist – auch wenn das Modell niedriger bewertet."
      />

      <section className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="label-caps">DLP-Gateway für andere Anwendungen</p>
          <span className="text-xs tabular-nums text-subtle">Regelwerk {settings.dlp?.ruleset_version ?? "–"}</span>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          <span className="font-mono">POST {settings.dlp?.endpoint ?? "/api/v1/redact"}</span> schwärzt Texte endgültig, bevor externe Fachanwendungen oder
          Analyse-Pipelines sie an ein Cloud-LLM senden: Zugangsdaten, vertrauliche Dateinamen, geschützte Parameter, Sperrbegriffe und
          personenbezogene Daten. Kein Mapping, nichts wird gespeichert oder geloggt.{" "}
          <span className="tabular-nums">{settings.dlp?.configured_terms ?? 0}</span> Sperrbegriffe aus <span className="font-mono">DLP_TERMS</span>.
        </p>
        <AutoTextarea
          minRows={2}
          maxRows={6}
          value={probe}
          onChange={(event) => setProbe(event.target.value)}
          name="dlp-probe"
          aria-label="Text für die Probe-Schwärzung"
          placeholder="Probetext einfügen, z. B. eine Zeile mit IBAN und E-Mail…"
        />
        <div className="flex justify-end">
          <button className="btn btn-sm" onClick={() => void runProbe()} disabled={busy || !probe.trim()}>
            {busy && <Spinner size={11} />} Probe-Schwärzung
          </button>
        </div>
        {result && (
          <div className="rounded-lg border border-line bg-surface-2 p-3 text-xs">
            <p className="whitespace-pre-wrap break-words text-fg">{result.redacted_text}</p>
            <p className="mt-2 text-subtle">
              <span className="tabular-nums">{result.total}</span> Schwärzungen
              {Object.keys(result.counts).length > 0 && ` · ${Object.entries(result.counts).map(([category, count]) => `${category} ${count}`).join(" · ")}`}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

function AppearanceSection() {
  const { choice, setChoice } = useTheme();
  return (
    <div className="space-y-5">
      <SectionTitle title="Darstellung" text="Dunkler Arbeitsmodus für lange Prüfsitzungen, heller Modus für Ausdrucke und helle Räume; System folgt dem Betriebssystem." />
      <Segmented<ThemeChoice>
        ariaLabel="Farbschema"
        value={choice}
        onChange={setChoice}
        options={[
          { value: "dark", label: "Dunkel" },
          { value: "light", label: "Hell" },
          { value: "system", label: "System" },
        ]}
      />
      <p className="text-xs text-subtle">Die Wahl gilt für diesen Browser (localStorage) und wird vor dem ersten Bildaufbau angewandt.</p>
    </div>
  );
}

function SystemSection({ open, onAccessChanged, notify }: { open: boolean; onAccessChanged: () => void; notify: Notify }) {
  const [accessKey, setAccessKeyState] = useState("");
  useEffect(() => {
    if (open) setAccessKeyState(getAccessKey());
  }, [open]);
  return (
    <div className="space-y-5">
      <SectionTitle title="System & Verbindung" />
      <Field label="Backend-Adresse">
        <p className="font-mono text-sm text-fg">{getApiBase()}</p>
        <p className="mt-1.5 flex gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-muted">
          <Info size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
          Lokal http://127.0.0.1:8001 (unter Windows 127.0.0.1 statt localhost: vermeidet den IPv6-Umweg). Im Firmennetz oder Container die
          Adresse des zentralen Servers beim Build setzen (NEXT_PUBLIC_API_BASE_URL bzw. PUBLIC_API_URL).
        </p>
      </Field>
      <Field label="Zugangsschlüssel (X-API-Key)" hint="Nur nötig, wenn API_KEY im Backend gesetzt ist. Wird nur in diesem Browser gespeichert.">
        <input
          className="input font-mono"
          type="password"
          value={accessKey}
          onChange={(event) => setAccessKeyState(event.target.value)}
          placeholder="Wert von API_KEY eingeben…"
          name="access-key"
          autoComplete="off"
          spellCheck={false}
        />
      </Field>
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
  );
}

function AboutSection({ open, version, notify }: { open: boolean; version: string; notify: Notify }) {
  return (
    <div className="space-y-5">
      <SectionTitle
        title="Updates & Über"
        text={`Enterprise Compliance Agent${version ? ` v${version}` : ""}. Updates nur nach Bestätigung des Commit-Hashes, als Fast-Forward und mit Datenbanksicherung – kein Auto-Pulling.`}
      />
      {open && <ReleasePanel notify={notify} />}
      <div className="border-t border-line pt-4">
        <p className="label-caps">Regulatorischer Stand</p>
        <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
          <li>EU AI Act – VO (EU) 2024/1689; Anhang-III-Pflichten ab 02.12.2027 (VO (EU) 2026/1744)</li>
          <li>§ 14 Abs. 4 UStG, E-Rechnung nach EN 16931; XML-Vorrang nach BMF-Schreiben vom 15.10.2024, Rz. 36</li>
          <li>GoBD Rz. 151–155 (Verfahrensdokumentation); Aufbewahrung 8 bzw. 10 Jahre (§ 147 AO, BEG IV)</li>
          <li>DSGVO Art. 4 Nr. 5, 25, 32 – Pseudonymisierung vor jedem Cloud-Aufruf; DLP-Gateway unter /api/v1/redact</li>
        </ul>
        <p className="mt-2 text-xs text-subtle">Technische Vorprüfung – keine Rechts- oder Steuerberatung.</p>
      </div>
    </div>
  );
}

/** Einstellungen: Kategorien links, ruhige Formulare rechts; feste Hoehe, Inhalte scrollen im Panel. */
export function SettingsModal({ open, settings, version, onClose, onSaved, onAccessChanged, notify }: Props) {
  const [section, setSection] = useState<Section>("models");
  const needsSettings = section === "models" || section === "cascade" || section === "compliance";
  return (
    <Modal open={open} onClose={onClose} title="Einstellungen" width="max-w-5xl" padded={false}>
      <div className="grid h-[min(720px,calc(100vh-12rem))] min-h-[420px] grid-cols-1 md:grid-cols-[230px_minmax(0,1fr)]">
        <nav aria-label="Kategorien" className="flex gap-1 overflow-x-auto border-b border-line p-2 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:p-3">
          {SECTIONS.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-current={section === item.key ? "page" : undefined}
              onClick={() => setSection(item.key)}
              className={cx(
                "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors duration-150",
                section === item.key ? "bg-surface-2 font-medium text-fg ring-1 ring-line" : "text-muted hover:bg-surface-hover hover:text-fg",
              )}
            >
              <span className={section === item.key ? "text-accent" : "text-subtle"}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div key={section} className="scroll-area anim-fade min-h-0 px-5 py-5 pr-4 md:px-6">
          {needsSettings && !settings && (
            <p className="py-8 text-center text-sm text-subtle">Backend nicht erreichbar – Einstellungen können nicht geladen werden.</p>
          )}
          {section === "models" && settings && (
            <ModelsSection settings={settings} active={open} onSaved={onSaved} onAccessChanged={onAccessChanged} notify={notify} />
          )}
          {section === "cascade" && settings && <CascadeSection settings={settings} onSaved={onSaved} notify={notify} />}
          {section === "compliance" && settings && <ComplianceSection settings={settings} onSaved={onSaved} notify={notify} />}
          {section === "appearance" && <AppearanceSection />}
          {section === "system" && <SystemSection open={open} onAccessChanged={onAccessChanged} notify={notify} />}
          {section === "about" && <AboutSection open={open} version={version} notify={notify} />}
        </div>
      </div>
    </Modal>
  );
}
