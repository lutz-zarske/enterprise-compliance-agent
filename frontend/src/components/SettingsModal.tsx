"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError, getAccessKey, getApiBase, setAccessKey } from "../lib/api";
import type {
  ReleaseStatus,
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
import { cx, formatModel, providerDisplayName } from "../lib/format";
import { LOCALE_TAG, type Locale, useI18n } from "../lib/i18n";
import {
  ArrowUpCircle,
  CheckCircle,
  Eye,
  EyeOff,
  Info,
  KeyRound,
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

type Section = "ai" | "compliance" | "appearance" | "connection" | "about";
type AiPart = "models" | "cascade";
type Notify = (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;

const CLOUD: { value: CloudMode; label: string }[] = [
  { value: "gemini", label: "Google Gemini" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "openai", label: "OpenAI" },
];

const LANGUAGE_OPTIONS: { value: Locale; label: string }[] = [
  { value: "de", label: "Deutsch" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

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
  const { tr, td } = useI18n();
  const names = (catalog?.models ?? []).filter((name) => name !== exclude);
  const all = value && !names.includes(value) ? [value, ...names] : names;
  const options = [
    ...(allowOff ? [{ value: "", label: tr("Aus – direkt zur nächsten Stufe", "Off – skip directly to next stage", "Desactivado – pasar al siguiente nivel") }] : []),
    ...all.map((name, index) => ({
      value: name,
      label: name,
      hint:
        index === 0 && catalog?.source === "api" && !allowOff
          ? tr("neuestes verfügbares Modell", "latest available model", "último modelo disponible")
          : name === catalog?.current
            ? tr("aktuell eingestellt", "currently selected", "seleccionado actualmente")
            : undefined,
    })),
  ];
  return (
    <Field
      label={label}
      hint={
        catalog?.source === "api"
          ? tr("Liste live aus der API des Anbieters, neueste zuerst.", "Live model catalog from provider API, newest first.", "Catálogo en vivo de la API del proveedor.")
          : td(catalog?.message) || tr("Vorschlagsliste – mit hinterlegtem Key kommt die Liste direkt vom Anbieter.", "Suggested list – live catalog loads once an API key is configured.", "Lista sugerida; el catálogo en vivo se carga al añadir clave API.")
      }
    >
      {catalog ? (
        <Select value={value} onChange={onChange} ariaLabel={`${label} (${providerDisplayName(provider)})`} width={320} className="h-9 w-full justify-between" options={options} />
      ) : (
        <div className="flex h-9 items-center gap-2 text-xs text-subtle"><Spinner size={12} /> {tr("Modelle werden geladen…", "Loading models…", "Cargando modelos…")}</div>
      )}
    </Field>
  );
}

function KeyInput({ value, onChange, placeholder, name }: { value: string; onChange: (value: string) => void; placeholder: string; name: string }) {
  const { tr } = useI18n();
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        className="input h-9 pr-10 font-mono"
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
        className="icon-target absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md text-subtle transition-colors duration-150 hover:text-fg"
        onClick={() => setShow((visible) => !visible)}
        aria-label={show ? tr("Key verbergen", "Hide key", "Ocultar clave") : tr("Key anzeigen", "Show key", "Mostrar clave")}
      >
        {show ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
      </button>
    </div>
  );
}

function useSave(onSaved: (settings: RuntimeSettings) => void, notify: Notify) {
  const { tr } = useI18n();
  const [busy, setBusy] = useState(false);
  const save = useCallback(
    async (update: SettingsUpdate) => {
      setBusy(true);
      try {
        const updated = await api.updateSettings(update);
        onSaved(updated);
        return updated;
      } catch (err) {
        notify("bad", tr("Speichern fehlgeschlagen", "Save failed", "Error al guardar"), err instanceof ApiError ? err.message : String(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [onSaved, notify, tr],
  );
  return { busy, save };
}

/**
 * 1-Klick Start/Stopp fuer Ollama (nur direkt am Server; im Container ueber docker compose).
 * ``compact``: nur ein knapper Start-Hinweis, und nur wenn Ollama installiert ist, aber nicht laeuft
 * (Kaskade mit lokalem Fallback - ohne Umweg ueber „KI-Modelle“).
 */
function LocalAiControl({ active, onChanged, notify, compact = false }: { active: boolean; onChanged: () => void; notify: Notify; compact?: boolean }) {
  const { tr, td } = useI18n();
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
      notify(
        result.ok ? "ok" : "warn",
        kind === "start" ? tr("Lokale KI starten", "Start local AI", "Iniciar IA local") : tr("Lokale KI stoppen", "Stop local AI", "Detener IA local"),
        td(result.message),
      );
      onChanged();
    } catch (err) {
      notify(
        "warn",
        kind === "start" ? tr("Lokale KI nicht gestartet", "Local AI failed to start", "No se pudo iniciar IA local") : tr("Lokale KI nicht gestoppt", "Local AI failed to stop", "No se pudo detener IA local"),
        err instanceof ApiError ? `${err.message}${err.hint ? ` – ${err.hint}` : ""}` : String(err),
      );
    } finally {
      setBusy(null);
      load();
    }
  }

  if (compact) {
    if (!status || status.running || !status.startable || !status.control_allowed) return null;
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-xs">
        <span className="flex min-w-0 items-center gap-2 text-fg">
          <span className="h-2 w-2 shrink-0 rounded-full bg-subtle" aria-hidden="true" />
          {tr(
            "Ollama ist installiert, läuft aber nicht – die lokale Stufe würde übersprungen.",
            "Ollama is installed but not running – the local stage will be skipped.",
            "Ollama está instalado pero detenido; se omitirá el nivel local.",
          )}
        </span>
        <button type="button" className="btn btn-sm" onClick={() => void run("start")} disabled={busy !== null}>
          {busy === "start" ? <Spinner size={11} /> : <Play size={11} aria-hidden="true" />} {tr("Lokale KI starten", "Start local AI", "Iniciar IA local")}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2.5">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium text-fg">
          <span className={cx("h-2 w-2 rounded-full", status?.running ? "bg-ok" : "bg-subtle")} aria-hidden="true" />
          {tr("Lokale KI (Ollama)", "Local AI (Ollama)", "IA local (Ollama)")}
        </p>
        <p className="mt-0.5 text-xs text-subtle">
          {status ? td(status.text) : tr("Status wird ermittelt…", "Checking status…", "Comprobando estado…")}
          {status && !status.control_allowed && status.controllable && tr(" Start und Stopp nur direkt am Server (http://127.0.0.1).", " Start and stop only allowed from loopback (http://127.0.0.1).", " Inicio y parada solo permitidos desde el servidor local.")}
        </p>
      </div>
      <div className="flex gap-2">
        {status?.startable && status.control_allowed && (
          <button className="btn btn-sm" onClick={() => void run("start")} disabled={busy !== null}>
            {busy === "start" ? <Spinner size={11} /> : <Play size={11} aria-hidden="true" />} {tr("Starten", "Start", "Iniciar")}
          </button>
        )}
        {status?.stoppable && status.control_allowed && (
          <Tooltip content={tr("Beendet Ollama und gibt den Grafikspeicher frei. Während einer Prüfung gesperrt.", "Stops Ollama and frees GPU memory. Disabled during active audits.", "Detiene Ollama y libera memoria gráfica.")} align="right">
            <button className="btn btn-sm" onClick={() => void run("stop")} disabled={busy !== null}>
              {busy === "stop" ? <Spinner size={11} /> : <Power size={11} aria-hidden="true" />} {tr("Stoppen", "Stop", "Detener")}
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
  const { tr, td } = useI18n();
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
        title={tr("Modelle", "Models", "Modelos")}
        text={tr(
          "Hauptmodell und Ausweichmodell desselben Anbieters. Jeder Modellwechsel wird mit Modell-ID, Prompt-Hash und Zeitstempel signiert im Ledger verankert – nie still.",
          "Primary model and fallback model for the selected provider. Every model change is Ed25519-signed with model ID, prompt hash and timestamp in the ledger.",
          "Modelo principal y alternativo del proveedor. Cada cambio queda firmado en el registro con ID del modelo y hash del prompt.",
        )}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Segmented<"local" | "cloud">
          ariaLabel={tr("Inferenz-Ort", "Inference location", "Ubicación de inferencia")}
          value={location}
          onChange={setLocation}
          options={[
            { value: "local", label: tr("Lokal (Ollama)", "Local (Ollama)", "Local (Ollama)") },
            { value: "cloud", label: tr("Cloud (API)", "Cloud (API)", "Nube (API)") },
          ]}
        />
        {location === "cloud" && <Select<CloudMode> value={provider} onChange={setProvider} options={CLOUD} ariaLabel={tr("Cloud-Anbieter", "Cloud provider", "Proveedor en la nube")} width={220} className="h-8" />}
      </div>

      {catalog?.upgrade && catalog.upgrade !== model && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ok-line bg-ok-soft px-3 py-2 text-xs text-fg">
          <ArrowUpCircle size={14} className="text-ok" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {tr("Neueres Modell derselben Klasse verfügbar:", "Newer model in the same tier available:", "Nuevo modelo equivalente disponible:")}{" "}
            <span className="font-semibold">{catalog.upgrade}</span>. {tr("Die Übernahme wird im Ledger verankert.", "Activation is logged in the ledger.", "El cambio queda registrado.")}
          </span>
          <button className="btn btn-sm" disabled={busy} onClick={() => void save({ models: { [mode]: catalog.upgrade! } })}>
            {tr("Übernehmen", "Apply", "Aplicar")}
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ModelSelect provider={mode} value={model} onChange={setModel} catalog={catalog} label={tr("Hauptmodell", "Primary Model", "Modelo principal")} />
        {mode !== "local" && (
          <ModelSelect
            provider={mode}
            value={fallbackModel}
            onChange={setFallbackModel}
            catalog={catalog}
            label={tr("Ausweichmodell bei Überlast", "Fallback Model on Overload", "Modelo alternativo por sobrecarga")}
            allowOff
            exclude={model}
          />
        )}
        {mode !== "local" && (
          <Field
            label={`API-Key ${providerDisplayName(mode)}${keyStored ? ` · ${tr("hinterlegt", "stored", "guardada")} (${settings.masked_keys?.[mode] ?? "…"})` : ""}`}
            hint={tr(
              "Serverseitig Fernet-verschlüsselt gespeichert und nur maskiert zurückgegeben. Weitere Schlüssel unter „Ausweich-Kaskade“.",
              "Stored Fernet-encrypted on the server and returned masked only. Configure extra keys under “Fallback Cascade”.",
              "Almacenada con cifrado Fernet en el servidor. Claves adicionales en «Cascada de respaldo».",
            )}
          >
            <KeyInput
              value={apiKey}
              onChange={setApiKey}
              name={`${mode}-api-key`}
              placeholder={
                keyStored
                  ? tr("Neuen Key eingeben, um ihn zu ersetzen…", "Enter new key to replace…", "Introducir nueva clave para reemplazar…")
                  : tr("Key eingeben…", "Enter API key…", "Introducir clave API…")
              }
            />
          </Field>
        )}
      </div>

      {mode !== "local" && fallbackModel === "" && settings.suggested_fallback_models?.[mode] && (
        <p className="text-xs text-subtle">
          {tr("Tipp:", "Tip:", "Consejo:")}{" "}
          <button type="button" className="font-medium text-accent hover:underline" onClick={() => setFallbackModel(settings.suggested_fallback_models[mode])}>
            {settings.suggested_fallback_models[mode]}
          </button>{" "}
          {tr(
            "als Ausweichmodell übernimmt bei Überlast des Hauptmodells, bevor die Kaskade den Anbieter wechselt.",
            "can act as same-provider fallback on overload before the cascade switches providers.",
            "actúa como respaldo del mismo proveedor antes de cambiar en la cascada.",
          )}
        </p>
      )}

      {mode !== "local" && (
        <details className="group rounded-lg border border-pii-line bg-pii-soft px-3 py-2 text-xs text-fg">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-pii">
            <Lock size={13} aria-hidden="true" />{" "}
            {tr(
              "Privacy Gateway: vor jedem Cloud-Aufruf lokal pseudonymisiert (Art. 4 Nr. 5 DSGVO)",
              "Privacy Gateway: pseudonymized locally before every cloud call (GDPR Art. 4(5))",
              "Privacy Gateway: seudonimizado localmente antes de cada envío a la nube (RGPD Art. 4(5))",
            )}
            <span className="ml-auto text-subtle transition-transform duration-150 group-open:rotate-90" aria-hidden="true">›</span>
          </summary>
          <p className="mt-2 leading-relaxed text-muted">
            {tr(
              "Erkannte Namen mit Anrede oder Rolle, Firmen, IBANs, Steuer-IDs, Adressen, Kontaktdaten und Beträge gehen nur als Platzhalter an den Anbieter und werden lokal re-identifiziert; das Mapping verlässt den Server nie. Pseudonymisierte Daten bleiben personenbezogen: AV-Vertrag und Transfergrundlage sind für jeden Anbieter der Kaskade nötig.",
              "Detected names, companies, IBANs, tax IDs, addresses, contact info and amounts are sent only as placeholders and re-identified locally; mapping tables never leave your server.",
              "Nombres, empresas, IBAN, NIF, direcciones, contactos e importes se envían solo como marcadores y se reidentifican localmente; las tablas nunca salen del servidor.",
            )}
          </p>
        </details>
      )}

      {result && (
        <div className={cx("flex flex-wrap items-start gap-2 rounded-lg border p-3 text-xs", result.ok ? "border-ok-line bg-ok-soft text-fg" : "border-bad-line bg-bad-soft text-fg")}>
          {result.ok ? <CheckCircle size={14} className="mt-0.5 text-ok" /> : <XCircle size={14} className="mt-0.5 text-bad" />}
          <span className="min-w-0 flex-1">{td(result.message)}</span>
          {result.suggested_model && (
            <button className="btn btn-sm" disabled={busy} onClick={() => void save({ models: { local: result.suggested_model! } }).then(() => setResult(null))}>
              {tr(`Übernehmen: ${formatModel(result.suggested_model)}`, `Apply ${formatModel(result.suggested_model)}`, `Aplicar ${formatModel(result.suggested_model)}`)}
            </button>
          )}
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {mode !== "local" && keyStored && (
          <button className="btn" disabled={busy} onClick={() => void save({ api_keys: { [mode]: "" } }).then((ok) => ok && notify("ok", tr("API-Key gelöscht", "API key removed", "Clave API eliminada")))}>
            {tr("Key löschen", "Delete key", "Eliminar clave")}
          </button>
        )}
        <button className="btn btn-primary" onClick={() => void saveAndTest()} disabled={busy || !model.trim() || (mode !== "local" && !keyStored && !apiKey)}>
          {busy && <Spinner size={13} />} {tr("Speichern & Verbindung testen", "Save & Test Connection", "Guardar y probar conexión")}
        </button>
      </div>

      <div className="border-t border-line pt-4">
        <LocalAiControl active={active} onChanged={onAccessChanged} notify={notify} />
      </div>
    </div>
  );
}

function CascadeSection({ settings, onSaved, onAccessChanged, notify }: {
  settings: RuntimeSettings;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: Notify;
}) {
  const { locale, tr } = useI18n();
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

  const stageLabels: Record<string, string> = {
    primary: tr("Hauptmodell", "Primary model", "Modelo principal"),
    ausweichmodell: tr("Ausweichmodell", "Fallback model", "Modelo alternativo"),
    ausweich_schluessel: tr("Ausweich-Schlüssel", "Backup API key", "Clave de respaldo"),
    fallback: tr("Anbieter-Fallback", "Provider fallback", "Proveedor alternativo"),
  };

  async function addBackup() {
    const ok = await save({
      ausweich_schluessel: [...existing(), { id: `k${Date.now().toString(36)}`, provider, model: model.trim() || undefined, api_key: key.trim() }],
    });
    if (ok) {
      setKey("");
      setModel("");
      setAdding(false);
      notify("ok", tr("Ausweich-Schlüssel hinzugefügt", "Backup key added", "Clave de respaldo añadida"), tr("Verschlüsselt gespeichert; die Kaskade ist im Ledger verankert.", "Stored encrypted; cascade updated in the ledger.", "Guardada cifrada; cascada registrada."));
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title={tr("Ausweich-Kaskade", "Fallback Cascade", "Cascada de respaldo")}
        text={tr(
          `Bei HTTP 408, 429, 5xx, Verbindungsfehler oder Zeitüberschreitung wiederholt jede Stufe zunächst (${(settings.retry_delays ?? []).map((s) => `${s} s`).join(", ") || "ohne Pause"}), dann übernimmt die nächste. Abgelehnte Keys (401/403) und Schemafehler lösen bewusst keinen Wechsel aus. Jeder Wechsel steht als provider_failover im Ledger; alle Cloud-Stufen laufen durch denselben Privacy Vault.`,
          `On HTTP 408, 429, 5xx, network errors or timeouts each stage retries first (${(settings.retry_delays ?? []).map((s) => `${s}s`).join(", ") || "no delay"}), then hands off cleanly. Invalid keys (401/403) and schema errors intentionally fail fast. Every transition is logged as provider_failover in the ledger.`,
          `Ante HTTP 408, 429, 5xx o tiempos agotados, cada nivel reintenta primero (${(settings.retry_delays ?? []).map((s) => `${s} s`).join(", ") || "sin pausa"}) y luego pasa al siguiente. Cada salto queda registrado como provider_failover.`,
        )}
      />

      <ol className="space-y-1.5" aria-label={tr("Effektive Kaskade", "Effective cascade", "Cascada efectiva")}>
        {(settings.chain ?? []).map((stage, index) => (
          <li key={`${stage.stage}-${stage.backup_id ?? stage.provider}-${index}`} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
            <span className="w-6 text-right text-xs tabular-nums text-subtle">{index + 1}</span>
            <span className="w-36 shrink-0 text-xs text-subtle">{stageLabels[stage.stage]}</span>
            <span className="min-w-0 flex-1 truncate text-fg">{providerDisplayName(stage.provider)}</span>
            <span className="truncate text-xs text-muted">{stage.model}</span>
          </li>
        ))}
        <li className="flex items-center gap-3 rounded-lg border border-dashed border-line px-3 py-2 text-sm">
          <span className="w-6 text-right text-xs tabular-nums text-subtle">{(settings.chain?.length ?? 0) + 1}</span>
          <span className="w-36 shrink-0 text-xs text-subtle">{tr("Letzte Stufe", "Final stage", "Último nivel")}</span>
          <span className="min-w-0 flex-1 text-fg">{tr("Deterministisches Regelwerk", "Deterministic ruleset", "Motor determinista de reglas")}</span>
          <span className={cx("text-xs", settings.heuristic_fallback ? "text-ok" : "text-subtle")}>
            {settings.heuristic_fallback ? tr("aktiv · gekennzeichnet", "active · badged", "activo · etiquetado") : tr("aus (HEURISTIC_FALLBACK)", "off (HEURISTIC_FALLBACK)", "desactivado")}
          </span>
        </li>
      </ol>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="label-caps">{tr("Ausweich-Schlüssel", "Backup API Keys", "Claves API de respaldo")} <span className="normal-case tracking-normal tabular-nums">({backups.length}/{settings.max_ausweich_schluessel ?? 6})</span></p>
          {!adding && backups.length < (settings.max_ausweich_schluessel ?? 6) && (
            <button className="btn btn-sm" onClick={() => setAdding(true)} disabled={busy}>
              <Plus size={13} aria-hidden="true" /> {tr("Weiteren API-Schlüssel hinzufügen", "Add another API key", "Añadir otra clave API")}
            </button>
          )}
        </div>
        {!isCloud && (
          <p className="text-xs text-subtle">
            {tr(
              "Gilt nur, wenn ein Cloud-Anbieter aktiv ist – eine lokal eingestellte Prüfung geht nie automatisch in die Cloud.",
              "Only applies when a cloud provider is primary – local mode never leaks documents to cloud APIs.",
              "Solo aplica cuando la nube está activa; el modo local nunca envía documentos fuera.",
            )}
          </p>
        )}
        {backups.length > 0 && (
          <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line">
            {backups.map((backup, index) => (
              <li key={backup.id} className="flex items-center gap-2.5 px-3 py-2 text-xs">
                <span className="w-16 shrink-0 tabular-nums text-subtle">Backup {index + 1}</span>
                <KeyRound size={13} className="shrink-0 text-ok" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-fg">
                  {providerDisplayName(backup.provider)} · {backup.model}
                  <span className="ml-1.5 font-mono text-subtle">{backup.key_hint}</span>
                </span>
                <button
                  type="button"
                  className="icon-target rounded-md p-1 text-subtle transition-colors duration-150 hover:text-bad"
                  disabled={busy}
                  onClick={() => void save({ ausweich_schluessel: existing().filter((item) => item.id !== backup.id) })}
                  aria-label={tr(`Backup ${index + 1} (${providerDisplayName(backup.provider)}) entfernen`, `Remove backup ${index + 1} (${providerDisplayName(backup.provider)})`, `Eliminar respaldo ${index + 1}`)}
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
              <Field label={tr("Anbieter", "Provider", "Proveedor")}>
                <Select<CloudMode> value={provider} onChange={setProvider} options={CLOUD} ariaLabel={tr("Anbieter des Ausweich-Schlüssels", "Backup key provider", "Proveedor de clave de respaldo")} width={240} className="h-9 w-full justify-between" />
              </Field>
              <Field label={tr("Modell (optional)", "Model (optional)", "Modelo (opcional)")} hint={tr("Leer = Hauptmodell dieses Anbieters.", "Blank = primary model for this provider.", "Vacío = modelo principal del proveedor.")}>
                <input className="input h-9" value={model} onChange={(event) => setModel(event.target.value)} placeholder={settings.models[provider]} name="backup-model" autoComplete="off" />
              </Field>
            </div>
            <Field label="API-Key">
              <KeyInput value={key} onChange={setKey} name="backup-api-key" placeholder={tr("Schlüssel eingeben (auch ein zweiter Key desselben Anbieters)…", "Enter key (even a secondary key for the same provider)…", "Introducir clave…")} />
            </Field>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setAdding(false)}>{tr("Abbrechen", "Cancel", "Cancelar")}</button>
              <button className="btn btn-primary" disabled={busy || key.trim().length < 8} onClick={() => void addBackup()}>
                {busy && <Spinner size={13} />} {tr("Zur Kaskade hinzufügen", "Add to cascade", "Añadir a la cascada")}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <p className="label-caps">{tr("Anbieter-Fallbacks", "Provider Fallbacks", "Proveedores alternativos")}</p>
        {isCloud ? (
          <Toggle
            checked={localFallback}
            onChange={(value) => void save({ fallbacks: value ? [...fallbacks.filter((item) => item !== "local"), "local"] : fallbacks.filter((item) => item !== "local") })}
            label={tr("Lokal ausweichen (Ollama)", "Fall back to Local (Ollama)", "Respaldo local (Ollama)")}
            description={tr("Fallen alle Cloud-Stufen aus, prüft das lokale Modell – kein Dokumentinhalt verlässt dann den Rechner.", "If all cloud tiers fail, runs locally so no document leaves your machine.", "Si fallan las etapas en la nube, analiza en local sin salida de datos.")}
          />
        ) : (
          <p className="text-xs text-subtle">
            {tr("Lokal ist das Hauptmodell; fällt es aus, schließt das Regelwerk die Prüfung gekennzeichnet ab.", "Local is active; if unavailable, the deterministic ruleset finishes and badges the audit.", "El modo local es el principal; si no está disponible, concluye el motor de reglas.")}
          </p>
        )}
        {(localFallback || !isCloud) && <LocalAiControl compact active onChanged={onAccessChanged} notify={notify} />}
        {fallbacks.filter((item) => item !== "local").map((item) => (
          <div key={item} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs">
            <span className="min-w-0 flex-1 text-fg">{providerDisplayName(item)} · {settings.models[item]} <span className="text-subtle">{tr("(Hauptschlüssel)", "(primary key)", "(clave principal)")}</span></span>
            <button type="button" className="icon-target rounded-md p-1 text-subtle transition-colors duration-150 hover:text-bad" disabled={busy} onClick={() => void save({ fallbacks: fallbacks.filter((entry) => entry !== item) })} aria-label={tr(`${providerDisplayName(item)} entfernen`, `Remove ${providerDisplayName(item)}`, `Eliminar ${providerDisplayName(item)}`)}>
              <Trash size={13} aria-hidden="true" />
            </button>
          </div>
        ))}
        {keyed.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-subtle">
            {tr("Weiteren Anbieter mit hinterlegtem Hauptschlüssel anhängen:", "Append another configured provider:", "Añadir otro proveedor configurado:")}
            {keyed.map((mode) => (
              <button key={mode} className="btn btn-sm" disabled={busy} onClick={() => void save({ fallbacks: [...fallbacks.filter((item) => item !== "local"), mode, ...(localFallback ? ["local" as const] : [])] })}>
                <Plus size={12} aria-hidden="true" /> {providerDisplayName(mode)}
              </button>
            ))}
          </div>
        )}
      </section>

      {settings.cloud_budget && (
        <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
          {tr("Cloud-Tagesbudget:", "Daily cloud budget:", "Presupuesto diario nube:")}{" "}
          {settings.cloud_budget.enabled ? (
            <>
              <span className="tabular-nums">{settings.cloud_budget.tokens.toLocaleString(LOCALE_TAG[locale])}</span> {tr("von", "of", "de")}{" "}
              <span className="tabular-nums">{settings.cloud_budget.limit.toLocaleString(LOCALE_TAG[locale])}</span> {tr("Tokens heute verbraucht.", "tokens used today.", "tokens consumidos hoy.")}
            </>
          ) : (
            <>{tr("ohne Limit", "unlimited", "sin límite")} (<span className="font-mono">CLOUD_DAILY_TOKEN_LIMIT=-1</span>); {tr("heute", "today", "hoy")} <span className="tabular-nums">{settings.cloud_budget.tokens.toLocaleString(LOCALE_TAG[locale])}</span> tokens.</>
          )}
        </p>
      )}
    </div>
  );
}

function ComplianceSection({ settings, onSaved, notify }: { settings: RuntimeSettings; onSaved: (settings: RuntimeSettings) => void; notify: Notify }) {
  const { tr } = useI18n();
  const { save } = useSave(onSaved, notify);
  const [probe, setProbe] = useState("");
  const [result, setResult] = useState<RedactResult | null>(null);
  const [busy, setBusy] = useState(false);

  const strictnessOptions: { value: PiiStrictness; label: string; text: string }[] = [
    {
      value: "strict",
      label: tr("Strikt", "Strict", "Estricto"),
      text: tr(
        "Schwärzt Namen, Firmen, Adressen, Beträge, Datumsangaben, IBAN, Steuer-IDs, Kontakt- und Art.-9-Daten.",
        "Redacts names, companies, addresses, amounts, dates, IBAN, tax IDs, contact details and Art. 9 sensitive data.",
        "Oculta nombres, empresas, direcciones, importes, fechas, IBAN, NIF, contactos y datos del art. 9.",
      ),
    },
    {
      value: "standard",
      label: "Standard",
      text: tr(
        "Schwärzt IBAN, Steuernummer/USt-IdNr., E-Mail, Telefon, Kennnummern und Art.-9-Daten; Übriges wird markiert.",
        "Redacts IBAN, tax/VAT IDs, email, phone, identifiers and Art. 9 data; flags remaining matches.",
        "Oculta IBAN, NIF/IVA, correo, teléfono e identificadores del art. 9; marca el resto.",
      ),
    },
    {
      value: "audit_only",
      label: "Audit-Only",
      text: tr(
        "Markiert alle Treffer, schwärzt nichts – nur für interne Revisoren mit Berechtigung.",
        "Marks all findings without redaction – strictly for authorized internal auditors.",
        "Marca todos los hallazgos sin ocultar; solo para auditores internos autorizados.",
      ),
    },
  ];

  async function runProbe() {
    setBusy(true);
    try {
      setResult(await api.redact(probe));
    } catch (err) {
      notify("bad", tr("Probe-Schwärzung fehlgeschlagen", "Redaction test failed", "Error en prueba de anonimización"), err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Compliance"
        text={tr(
          "Änderungen gelten für die nächste Analyse; bestehende Prüfergebnisse bleiben unverändert im Ledger.",
          "Changes apply to subsequent audits; existing ledger entries remain immutable.",
          "Los cambios aplican al siguiente análisis; las entradas existentes en el registro son inmutables.",
        )}
      />
      <div>
        <p className="label-caps mb-2">{tr("PII-Maskierungsgrad (Textansicht & Vorschau)", "PII Masking Level (Text View & Preview)", "Nivel de ocultación PII (vista previa)")}</p>
        <Segmented<PiiStrictness>
          ariaLabel={tr("PII-Maskierungsgrad", "PII masking level", "Nivel de ocultación PII")}
          value={settings.pii_strictness}
          onChange={(value) => void save({ pii_strictness: value })}
          options={strictnessOptions.map(({ value, label }) => ({ value, label }))}
        />
        <p className="mt-2 text-xs text-muted">{strictnessOptions.find((s) => s.value === settings.pii_strictness)?.text}</p>
        <p className="mt-1 text-xs text-subtle">
          {tr("PII-Befunde werden unabhängig von dieser Stufe ausschließlich maskiert gespeichert.", "PII findings are always stored strictly masked regardless of preview strictness.", "Los hallazgos PII se guardan siempre enmascarados.")}
        </p>
      </div>
      <Toggle
        checked={settings.enforce_ustg_check}
        onChange={(value) => void save({ enforce_ustg_check: value })}
        label={tr("§ 14 UStG Check erzwingen", "Enforce Sec. 14 UStG Audit", "Exigir control § 14 UStG")}
        description={tr("Prüft bei Rechnungen alle Pflichtangaben nach § 14 Abs. 4 UStG und fließt in den Score ein.", "Audits all mandatory VAT elements under Sec. 14(4) German VAT Act and factors into score.", "Verifica los requisitos de factura según § 14(4) UStG e influye en la puntuación.")}
      />
      <Toggle
        checked={settings.ai_act_escalation}
        onChange={(value) => void save({ ai_act_escalation: value })}
        label={tr("EU AI Act Hochrisiko-Eskalation", "EU AI Act High-Risk Escalation", "Escalada de alto riesgo (Reglamento IA)")}
        description={tr("Stuft automatisch auf „Hochrisiko“, sobald eine Anhang-III-Kategorie belegt ist – auch wenn das Modell niedriger bewertet.", "Automatically escalates to High Risk when any Annex III category triggers, overriding lower LLM ratings.", "Clasifica automáticamente como alto riesgo al detectar Anexo III.")}
      />

      <section className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="label-caps">{tr("Schwärzungs-Gateway (DLP) für andere Anwendungen", "Redaction gateway (DLP) for other applications", "Pasarela de anonimización (DLP) para otras aplicaciones")}</p>
          <span className="text-xs tabular-nums text-subtle">{tr("Regelwerk", "Ruleset", "Reglamento")} {settings.dlp?.ruleset_version ?? "–"}</span>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          <span className="font-mono">POST {settings.dlp?.endpoint ?? "/api/v1/redact"}</span>{" "}
          {tr(
            "schwärzt Texte endgültig, bevor externe Fachanwendungen oder Analyse-Pipelines sie an ein Cloud-LLM senden: Zugangsdaten, vertrauliche Dateinamen, geschützte Parameter, Sperrbegriffe und personenbezogene Daten. Kein Mapping, nichts wird gespeichert oder geloggt.",
            "irreversibly redacts text before external applications or pipelines call cloud LLMs: credentials, confidential filenames, blocklisted terms and personal data. Zero persistence or logging.",
            "anonimiza irreversiblemente textos antes de enviarlos a LLM externos: credenciales, archivos confidenciales y datos personales.",
          )}{" "}
          <span className="tabular-nums">{settings.dlp?.configured_terms ?? 0}</span> {tr("Sperrbegriffe aus", "custom blocked terms from", "términos bloqueados de")} <span className="font-mono">DLP_TERMS</span>.
        </p>
        <AutoTextarea
          minRows={2}
          maxRows={6}
          value={probe}
          onChange={(event) => setProbe(event.target.value)}
          name="dlp-probe"
          aria-label={tr("Text für die Probe-Schwärzung", "Text for redaction test", "Texto para prueba de ocultación")}
          placeholder={tr("Probetext einfügen, z. B. eine Zeile mit IBAN und E-Mail…", "Paste sample text, e.g. a line containing IBAN and email…", "Pegar texto de prueba, p. ej. IBAN y correo…")}
        />
        <div className="flex justify-end">
          <button className="btn btn-sm" onClick={() => void runProbe()} disabled={busy || !probe.trim()}>
            {busy && <Spinner size={11} />} {tr("Probe-Schwärzung", "Test Redaction", "Probar ocultación")}
          </button>
        </div>
        {result && (
          <div className="rounded-lg border border-line bg-surface-2 p-3 text-xs">
            <p className="whitespace-pre-wrap break-words text-fg">{result.redacted_text}</p>
            <p className="mt-2 text-subtle">
              <span className="tabular-nums">{result.total}</span> {tr("Schwärzungen", "redactions", "ocultaciones")}
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
  const { locale, setLocale, tr } = useI18n();
  return (
    <div className="space-y-5">
      <SectionTitle
        title={tr("Darstellung", "Appearance", "Apariencia")}
        text={tr(
          "Farbschema und Arbeitssprache für Navigation, Meldungen, Copilot und Exporte.",
          "Color theme and working language for navigation, status messages, Copilot and exported reports.",
          "Tema de color e idioma de trabajo para navegación, mensajes, Copilot e informes.",
        )}
      />
      <Field label={tr("Sprache / Language / Idioma", "Language / Sprache / Idioma", "Idioma / Language / Sprache")}>
        <Segmented<Locale>
          ariaLabel={tr("Sprache wählen", "Select language", "Seleccionar idioma")}
          value={locale}
          onChange={setLocale}
          options={LANGUAGE_OPTIONS}
        />
      </Field>
      <Field label={tr("Farbschema", "Color Theme", "Tema de color")}>
        <Segmented<ThemeChoice>
          ariaLabel={tr("Farbschema", "Color theme", "Tema de color")}
          value={choice}
          onChange={setChoice}
          options={[
            { value: "dark", label: tr("Dunkel", "Dark", "Oscuro") },
            { value: "light", label: tr("Hell", "Light", "Claro") },
            { value: "system", label: "System" },
          ]}
        />
      </Field>
      <p className="text-xs text-subtle">
        {tr(
          "Beide Einstellungen gelten für diesen Browser (localStorage) und werden vor dem ersten Bildaufbau angewandt.",
          "Both preferences are saved in this browser (localStorage) and applied before first paint.",
          "Ambas preferencias se guardan en este navegador (localStorage) y se aplican antes del primer render.",
        )}
      </p>
    </div>
  );
}

function ConnectionSection({ open, health, onAccessChanged, notify }: {
  open: boolean;
  health: HealthResponse | null;
  onAccessChanged: () => void;
  notify: Notify;
}) {
  const { tr } = useI18n();
  const [accessKey, setAccessKeyState] = useState("");
  const [showKeyForm, setShowKeyForm] = useState(false);
  useEffect(() => {
    if (open) setAccessKeyState(getAccessKey());
  }, [open]);
  const keyRequired = Boolean(health?.auth_enabled);
  return (
    <div className="space-y-5">
      <SectionTitle
        title={tr("Verbindung", "Connection", "Conexión")}
        text={tr(
          "Mit welchem Backend diese Oberfläche spricht. Lokal ist hier nichts einzustellen – relevant nur, wenn das Backend zentral auf einem Server mit Zugangsschutz läuft.",
          "Which backend this interface talks to. Nothing to configure for local use – only relevant when the backend runs centrally on a protected server.",
          "Con qué backend se comunica esta interfaz. En uso local no hay nada que configurar; solo es relevante si el backend se ejecuta en un servidor protegido.",
        )}
      />
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm">
        <dt className="text-subtle">Backend</dt>
        <dd className="font-mono text-fg [overflow-wrap:anywhere]">{getApiBase()}</dd>
        <dt className="text-subtle">{tr("Status", "Status", "Estado")}</dt>
        <dd className={cx("flex items-center gap-1.5", health ? "text-ok" : "text-bad")}>
          {health ? <CheckCircle size={14} aria-hidden="true" /> : <XCircle size={14} aria-hidden="true" />}
          <span className="tabular-nums">
            {health
              ? tr(`Verbunden · v${health.version}`, `Connected · v${health.version}`, `Conectado · v${health.version}`)
              : tr("Nicht erreichbar", "Unreachable", "No disponible")}
          </span>
        </dd>
        <dt className="text-subtle">{tr("Zugangsschutz", "Access control", "Control de acceso")}</dt>
        <dd className="text-fg">
          {keyRequired
            ? tr("aktiv – Zugangsschlüssel nötig", "active – access key required", "activo – se requiere clave")
            : tr("aus – kein Schlüssel nötig", "off – no key required", "desactivado – no se requiere clave")}
        </dd>
      </dl>

      {keyRequired || showKeyForm || accessKey ? (
        <>
          <Field
            label={tr("Zugangsschlüssel (X-API-Key)", "Access Key (X-API-Key)", "Clave de acceso (X-API-Key)")}
            hint={tr("Wert der Variable API_KEY auf dem Server. Wird nur in diesem Browser gespeichert.", "Value of the API_KEY variable on the server. Stored only in this browser.", "Valor de la variable API_KEY del servidor. Solo se guarda en este navegador.")}
          >
            <input
              className="input font-mono"
              type="password"
              value={accessKey}
              onChange={(event) => setAccessKeyState(event.target.value)}
              placeholder={tr("Wert von API_KEY eingeben…", "Enter API_KEY value…", "Introducir valor de API_KEY…")}
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
                notify("ok", tr("Zugangsschlüssel gespeichert", "Access key saved", "Clave de acceso guardada"), tr("Nur in diesem Browser (localStorage).", "Browser localStorage only.", "Solo en este navegador (localStorage)."));
              }}
            >
              {tr("Übernehmen", "Save", "Aplicar")}
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowKeyForm(true)}>
          <KeyRound size={13} aria-hidden="true" /> {tr("Zugangsschlüssel trotzdem hinterlegen", "Enter an access key anyway", "Introducir una clave de todos modos")}
        </button>
      )}

      <p className="flex gap-2 text-xs leading-relaxed text-subtle">
        <Info size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
        {tr(
          "Für einen zentralen Server die Backend-Adresse beim Build setzen (NEXT_PUBLIC_API_BASE_URL bzw. PUBLIC_API_URL im Container). Unter Windows 127.0.0.1 statt localhost – das vermeidet den IPv6-Umweg.",
          "For a central server, set the backend address at build time (NEXT_PUBLIC_API_BASE_URL, or PUBLIC_API_URL in the container). On Windows use 127.0.0.1 instead of localhost to avoid the IPv6 detour.",
          "Para un servidor central, defina la dirección del backend al compilar (NEXT_PUBLIC_API_BASE_URL o PUBLIC_API_URL en el contenedor). En Windows use 127.0.0.1 en lugar de localhost.",
        )}
      </p>
    </div>
  );
}

function AboutSection({ version, release, checking, notify }: {
  version: string;
  release: ReleaseStatus | null;
  checking: boolean;
  notify: Notify;
}) {
  const { tr } = useI18n();
  return (
    <div className="space-y-5">
      <SectionTitle
        title={tr("Über", "About", "Acerca de")}
        text={tr(
          `Enterprise Compliance Agent${version ? ` v${version}` : ""}. Neue Releases per Klick installieren – mit automatischer Datenbanksicherung und Erhalt aller lokalen Daten.`,
          `Enterprise Compliance Agent${version ? ` v${version}` : ""}. Install new releases in one click – with automatic database backups and preserved local data.`,
          `Enterprise Compliance Agent${version ? ` v${version}` : ""}. Instala nuevas versiones en un clic con copia de seguridad automática.`,
        )}
      />
      <ReleasePanel initial={release} installedVersion={version} externalChecking={checking} notify={notify} />
      <div className="border-t border-line pt-4">
        <p className="label-caps">{tr("Regulatorischer Stand", "Regulatory Baseline", "Marco normativo")}</p>
        <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
          <li>{tr("EU AI Act – VO (EU) 2024/1689; Anhang-III-Pflichten ab 02.12.2027 (VO (EU) 2026/1744)", "EU AI Act – Reg. (EU) 2024/1689; Annex III obligations from 02 Dec 2027 (Reg. (EU) 2026/1744)", "Reglamento IA – Reg. (UE) 2024/1689; obligaciones Anexo III desde 02/12/2027")}</li>
          <li>{tr("§ 14 Abs. 4 UStG, E-Rechnung nach EN 16931; XML-Vorrang nach BMF-Schreiben vom 15.10.2024, Rz. 36", "Sec. 14(4) UStG, E-Invoice under EN 16931; XML precedence under BMF 15 Oct 2024", "§ 14(4) UStG, factura electrónica EN 16931; prioridad XML según circular BMF 15/10/2024")}</li>
          <li>{tr("GoBD Rz. 151–155 (Verfahrensdokumentation); Aufbewahrung 8 bzw. 10 Jahre (§ 147 AO, BEG IV)", "GoBD para. 151–155 (Procedural Docs); retention 8 / 10 years (§ 147 AO, BEG IV)", "GoBD Rz. 151–155 (Documentación); conservación 8 / 10 años (§ 147 AO, BEG IV)")}</li>
          <li>{tr("DSGVO Art. 4 Nr. 5, 25, 32 – Pseudonymisierung vor jedem Cloud-Aufruf; DLP-Gateway unter /api/v1/redact", "GDPR Art. 4(5), 25, 32 – Pseudonymization before cloud calls; DLP gateway at /api/v1/redact", "RGPD Art. 4(5), 25, 32 – Seudonimización previa a la nube; DLP Gateway en /api/v1/redact")}</li>
        </ul>
        <p className="mt-2 text-xs text-subtle">
          {tr("Technische Vorprüfung – keine Rechts- oder Steuerberatung.", "Technical pre-audit – not legal or tax advice.", "Pre-auditoría técnica – no constituye asesoramiento legal ni fiscal.")}
        </p>
      </div>
    </div>
  );
}

/** Einstellungen: Kategorien links, ruhige Formulare rechts; feste Hoehe, Inhalte scrollen im Panel. */
export function SettingsModal({ open, settings, health, version, onClose, onSaved, onAccessChanged, notify }: Props) {
  const { tr } = useI18n();
  const [section, setSection] = useState<Section>("ai");
  const [aiPart, setAiPart] = useState<AiPart>("models");
  const [release, setRelease] = useState<ReleaseStatus | null>(null);
  const [releaseChecking, setReleaseChecking] = useState(false);
  const needsSettings = section === "ai" || section === "compliance";

  // Release-Status beim Oeffnen vorab laden: zuerst lokal (sofort), dann mit Abgleich des Servers.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setReleaseChecking(true);
    api.release(false)
      .then((quick) => {
        if (alive) setRelease(quick);
      })
      .catch(() => undefined)
      .then(() => api.release(true))
      .then((full) => {
        if (alive && full) setRelease(full);
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setReleaseChecking(false);
      });
    return () => {
      alive = false;
    };
  }, [open]);

  const sections: { key: Section; label: string; icon: React.ReactNode }[] = [
    { key: "ai", label: tr("KI", "AI", "IA"), icon: <Sliders size={15} aria-hidden="true" /> },
    { key: "compliance", label: "Compliance", icon: <Scale size={15} aria-hidden="true" /> },
    { key: "appearance", label: tr("Darstellung", "Appearance", "Apariencia"), icon: <Palette size={15} aria-hidden="true" /> },
    { key: "connection", label: tr("Verbindung", "Connection", "Conexión"), icon: <Server size={15} aria-hidden="true" /> },
    { key: "about", label: tr("Über", "About", "Acerca de"), icon: <ArrowUpCircle size={15} aria-hidden="true" /> },
  ];
  return (
    <Modal open={open} onClose={onClose} title={tr("Einstellungen", "Settings", "Ajustes")} width="max-w-5xl" padded={false}>
      <div className="grid h-[min(720px,calc(100vh-12rem))] min-h-[420px] grid-cols-1 md:grid-cols-[230px_minmax(0,1fr)]">
        <nav aria-label={tr("Kategorien", "Categories", "Categorías")} className="flex gap-1 overflow-x-auto border-b border-line p-2 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:p-3">
          {sections.map((item) => (
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
            <p className="py-8 text-center text-sm text-subtle">
              {tr("Backend nicht erreichbar – Einstellungen können nicht geladen werden.", "Backend unreachable – settings cannot be loaded.", "Backend no disponible – no se pueden cargar los ajustes.")}
            </p>
          )}
          {section === "ai" && settings && (
            <>
              <div className="mb-5">
                <Segmented<AiPart>
                  ariaLabel={tr("KI-Bereich", "AI area", "Área de IA")}
                  value={aiPart}
                  onChange={setAiPart}
                  options={[
                    { value: "models", label: tr("Modelle", "Models", "Modelos") },
                    { value: "cascade", label: tr("Ausweich-Kaskade", "Fallback cascade", "Cascada de respaldo") },
                  ]}
                />
              </div>
              {aiPart === "models" ? (
                <ModelsSection settings={settings} active={open} onSaved={onSaved} onAccessChanged={onAccessChanged} notify={notify} />
              ) : (
                <CascadeSection settings={settings} onSaved={onSaved} onAccessChanged={onAccessChanged} notify={notify} />
              )}
            </>
          )}
          {section === "compliance" && settings && <ComplianceSection settings={settings} onSaved={onSaved} notify={notify} />}
          {section === "appearance" && <AppearanceSection />}
          {section === "connection" && <ConnectionSection open={open} health={health} onAccessChanged={onAccessChanged} notify={notify} />}
          {section === "about" && <AboutSection version={version} release={release} checking={releaseChecking} notify={notify} />}
        </div>
      </div>
    </Modal>
  );
}
