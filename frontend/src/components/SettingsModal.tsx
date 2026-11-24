"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
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
  Bot,
  Check,
  CheckCircle,
  ExternalLink,
  Eye,
  EyeOff,
  FileCode,
  FileText,
  Info,
  KeyRound,
  Lock,
  MessageSquare,
  Package,
  Palette,
  Play,
  Plus,
  Power,
  Scale,
  Server,
  Trash,
  XCircle,
} from "./icons";
import { ReleasePanel } from "./ReleaseAssistant";
import { Select } from "./Select";
import { useTheme, type ThemeChoice } from "./ThemeProvider";
import { AutoTextarea, Modal, ProgressBar, Segmented, Spinner, Toggle, Tooltip } from "./ui";

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
  initialSection?: Section;
  authRequired?: boolean;
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

const keyStamp = (settings: RuntimeSettings | null, mode: InferenceMode) =>
  mode === "local"
    ? "local"
    : hasKey(settings, mode)
      ? `key:${settings?.masked_keys?.[mode] ?? "1"}`
      : "-";

/** Geladene Kataloge je Anbieter und Key-Stand: Die Einstellungen öffnen ohne Ladezustand. */
const catalogCache = new Map<string, { at: number; catalog: ModelCatalog }>();
const CATALOG_TTL_MS = 5 * 60_000;
const catalogKey = (provider: InferenceMode, stamp: string) => `${provider}|${stamp}`;

function loadCatalog(provider: InferenceMode, stamp: string): Promise<ModelCatalog> {
  return api.models(provider).then((catalog) => {
    catalogCache.set(catalogKey(provider, stamp), { at: Date.now(), catalog });
    return catalog;
  });
}

/** Lädt die Modell-Liste des eingestellten Anbieters im Hintergrund vor (beim Start der Oberfläche). */
export function prefetchModelCatalog(settings: RuntimeSettings) {
  const providers = new Set<InferenceMode>([settings.inference_mode]);
  const cloud = initialProvider(settings);
  if (cloud) providers.add(cloud);
  for (const provider of providers) {
    if (!hasKey(settings, provider)) continue;
    const stamp = keyStamp(settings, provider);
    const entry = catalogCache.get(catalogKey(provider, stamp));
    if (entry && Date.now() - entry.at < CATALOG_TTL_MS) continue;
    loadCatalog(provider, stamp).catch(() => undefined);
  }
}

/** Modell-Katalog des Providers (neueste zuerst, live aus der API); ohne Key die Vorschlagsliste. */
function useCatalog(provider: InferenceMode, enabled: boolean, settings: RuntimeSettings | null) {
  const [, rerender] = useState(0);
  const stamp = keyStamp(settings, provider);
  useEffect(() => {
    if (!enabled) return;
    const entry = catalogCache.get(catalogKey(provider, stamp));
    if (entry && Date.now() - entry.at < CATALOG_TTL_MS) return;
    let alive = true;
    loadCatalog(provider, stamp)
      .then(() => alive && rerender((n) => n + 1))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [provider, enabled, stamp]);
  return enabled ? catalogCache.get(catalogKey(provider, stamp))?.catalog ?? null : null;
}

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  const { tr } = useI18n();
  return (
    <div>
      <span className="label-caps flex items-center gap-1.5">
        {label}
        {hint && (
          <Tooltip content={hint}>
            <span tabIndex={0} role="button" aria-label={tr(`Hinweis zu ${label}`, `Info: ${label}`, `Información: ${label}`)} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
          </Tooltip>
        )}
      </span>
      <div className="mt-1">{children}</div>
    </div>
  );
}

/** Überschrift eines Bereichs; ``quiet``: Titel nur für Screenreader (der Reiter darüber nennt ihn schon). */
function SectionTitle({ title, text, hint, quiet = false }: { title: string; text?: string; hint?: React.ReactNode; quiet?: boolean }) {
  const { tr } = useI18n();
  const info = hint && (
    <Tooltip content={hint}>
      <span tabIndex={0} role="button" aria-label={tr(`Hinweis zu ${title}`, `Info: ${title}`, `Información: ${title}`)} className="inline-flex align-[-2px] text-subtle"><Info size={13} aria-hidden="true" /></span>
    </Tooltip>
  );
  return (
    <div className="mb-4">
      <h3 className={quiet ? "sr-only" : "flex items-center gap-1.5 text-base font-semibold text-fg"}>
        {title}
        {!quiet && info}
      </h3>
      {text && (
        <p className={cx("max-w-[65ch] text-xs leading-relaxed", quiet ? "text-muted" : "mt-0.5 text-subtle")}>
          {text}
          {quiet && info && <> {info}</>}
        </p>
      )}
    </div>
  );
}

function ModelSelect({ provider, value, current, onChange, catalog, label, allowOff, exclude, disabled = false }: {
  provider: InferenceMode;
  value: string;
  /** Gespeicherter Wert (Hinweis „aktuell eingestellt“). */
  current?: string;
  onChange: (model: string) => void;
  catalog: ModelCatalog | null;
  label: string;
  allowOff?: boolean;
  exclude?: string;
  /** Gesperrt, solange kein Key hinterlegt ist - ohne Key liefert der Anbieter keine Liste. */
  disabled?: boolean;
}) {
  const { tr, td } = useI18n();
  if (disabled) {
    const offLabel = tr("Aus", "Off", "Desactivado");
    return (
      <Field label={label}>
        <Select value={value} onChange={onChange} ariaLabel={label} width={320} className="h-9 w-full justify-between" options={[{ value, label: value || offLabel }]} disabled />
      </Field>
    );
  }
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
          : name === (current ?? catalog?.current)
            ? tr("aktuell eingestellt", "currently selected", "seleccionado actualmente")
            : undefined,
    })),
  ];
  return (
    <Field
      label={label}
      hint={
        catalog?.source === "api"
          ? tr("Direkt vom Anbieter, neueste zuerst.", "Straight from the provider, newest first.", "Directamente del proveedor, los más recientes primero.")
          : td(catalog?.message) || tr("Vorschlagsliste – der Anbieter war nicht erreichbar.", "Suggested list – the provider could not be reached.", "Lista sugerida: no se pudo contactar con el proveedor.")
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

/** Verstecktes Benutzerfeld: Chrome erwartet es in Formularen mit Passwortfeld (Barrierefreiheit). */
function HiddenUsername() {
  return <input type="text" name="username" autoComplete="username" value="" readOnly hidden tabIndex={-1} aria-hidden="true" />;
}

function KeyInput({ value, onChange, placeholder, name, label, disabled = false }: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  name: string;
  label: string;
  disabled?: boolean;
}) {
  const { tr } = useI18n();
  const [show, setShow] = useState(false);
  // Eigenes <form> ohne Autovervollständigung: Browser behandeln den Key nicht als zu speicherndes Passwort.
  return (
    <form className="relative" autoComplete="off" onSubmit={(event) => event.preventDefault()}>
      <HiddenUsername />
      <input
        className="input h-9 pr-10 font-mono placeholder:font-sans disabled:cursor-not-allowed disabled:opacity-50"
        type={show ? "text" : "password"}
        name={name}
        value={value}
        aria-label={label}
        autoComplete="new-password"
        data-1p-ignore
        data-lpignore="true"
        spellCheck={false}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <button
        type="button"
        disabled={disabled}
        className="icon-target absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md text-subtle transition-colors duration-150 enabled:hover:text-fg disabled:opacity-50"
        onClick={() => setShow((visible) => !visible)}
        aria-label={show ? tr("Key verbergen", "Hide key", "Ocultar clave") : tr("Key anzeigen", "Show key", "Mostrar clave")}
      >
        {show ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
      </button>
    </form>
  );
}

function useSave(onSaved: (settings: RuntimeSettings) => void, notify: Notify) {
  const { tr, td } = useI18n();
  const [busy, setBusy] = useState(false);
  const save = useCallback(
    async (update: SettingsUpdate) => {
      setBusy(true);
      try {
        const updated = await api.updateSettings(update);
        onSaved(updated);
        return updated;
      } catch (err) {
        notify("bad", tr("Speichern fehlgeschlagen", "Save failed", "Error al guardar"), err instanceof ApiError ? td(err.message) : String(err));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [onSaved, notify, tr, td],
  );
  return { busy, save };
}

/**
 * 1-Klick Start/Stopp für Ollama (nur direkt am Server; im Container über docker compose).
 * ``compact``: nur ein knapper Start-Hinweis, und nur wenn Ollama installiert ist, aber nicht läuft
 * (Kaskade mit lokalem Fallback - ohne Umweg über „KI-Modelle“).
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

/** Letzter Verbindungstest je Konfiguration - bleibt beim Schließen und erneuten Öffnen sichtbar. */
const lastTests = new Map<string, ConnectionTestResult>();
const testKey = (settings: RuntimeSettings, mode: InferenceMode) =>
  `${mode}|${settings.models[mode]}|${mode === "local" ? "" : settings.masked_keys?.[mode] ?? ""}`;

/** Vorauswahl: der aktive Cloud-Anbieter, sonst der erste mit Key, sonst keiner. */
function initialProvider(settings: RuntimeSettings): CloudMode | "" {
  if (settings.inference_mode !== "local") return settings.inference_mode;
  return CLOUD.find(({ value }) => hasKey(settings, value))?.value ?? "";
}

/**
 * Anbieter → Key → Modelle, in dieser Reihenfolge freigeschaltet: Ohne Anbieter kein Key,
 * ohne hinterlegten Key keine Modell-Liste (der Anbieter liefert sie erst mit Key).
 * Ein Klick auf „Speichern“ speichert und prüft danach die Verbindung; währenddessen ist
 * der Knopf gesperrt, das Ergebnis steht als Haken daneben.
 */
function ModelsSection({ settings, active, onSaved, onAccessChanged, notify }: {
  settings: RuntimeSettings;
  active: boolean;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: Notify;
}) {
  const { tr, td } = useI18n();
  const [location, setLocation] = useState<"local" | "cloud">(settings.inference_mode === "local" ? "local" : "cloud");
  const [provider, setProvider] = useState<CloudMode | "">(() => initialProvider(settings));
  const [model, setModel] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [phase, setPhase] = useState<"idle" | "saving" | "testing">("idle");
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const running = useRef(false);
  const { busy: saving, save } = useSave(onSaved, notify);

  const mode: InferenceMode | null = location === "local" ? "local" : provider || null;
  const modeRef = useRef<InferenceMode | null>(mode);
  modeRef.current = mode;
  const cloud = mode !== null && mode !== "local";
  const keyStored = mode !== null && hasKey(settings, mode);
  const modelsReady = mode === "local" || keyStored;
  const catalog = useCatalog(mode ?? "local", active && mode !== null && modelsReady, settings);
  const savedFallback = cloud ? settings.ausweich_modelle?.[mode as CloudMode] ?? "" : "";
  const typedKey = apiKey.trim();
  const dirty =
    mode !== null &&
    (mode !== settings.inference_mode || model !== settings.models[mode] || fallbackModel !== savedFallback || typedKey !== "");
  const verified = Boolean(result?.ok) && !dirty;
  const busy = phase !== "idle" || saving;
  const canSave = mode !== null && !busy && !verified && Boolean(model.trim()) && (!cloud || keyStored || typedKey.length >= 8);

  useEffect(() => {
    if (!active) return;
    setLocation(settings.inference_mode === "local" ? "local" : "cloud");
    setProvider(initialProvider(settings));
    // Nur beim Öffnen synchronisieren - nicht bei jedem Speichern.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // Formular je Anbieter aus den gespeicherten Werten; der letzte Test dieser Konfiguration bleibt stehen.
  useEffect(() => {
    if (!mode) return;
    setModel(settings.models[mode]);
    setFallbackModel(mode === "local" ? "" : settings.ausweich_modelle?.[mode] ?? "");
    setApiKey("");
    setResult(lastTests.get(testKey(settings, mode)) ?? null);
  }, [mode, settings]);

  async function saveAndTest() {
    if (!mode || running.current) return;
    running.current = true;
    setResult(null);
    try {
      let current = settings;
      if (dirty) {
        setPhase("saving");
        const update: SettingsUpdate = { inference_mode: mode, models: { [mode]: model.trim() } };
        if (mode !== "local") {
          update.ausweich_modelle = { [mode]: fallbackModel };
          if (typedKey) update.api_keys = { [mode]: typedKey };
        }
        const updated = await save(update);
        if (!updated) return;
        current = updated;
        setApiKey("");
      }
      setPhase("testing");
      let outcome: ConnectionTestResult;
      try {
        outcome = await api.testConnection(mode);
      } catch (err) {
        outcome = { ok: false, provider: mode, model, message: err instanceof ApiError ? td(err.message) : String(err) };
      }
      lastTests.set(testKey(current, mode), outcome);
      if (modeRef.current === mode) setResult(outcome);
    } finally {
      running.current = false;
      setPhase("idle");
    }
  }

  async function removeKey() {
    if (!mode || mode === "local") return;
    const updated = await save({ api_keys: { [mode]: "" } });
    if (updated) notify("ok", tr("API-Key entfernt", "API key removed", "Clave API eliminada"));
  }

  const status =
    phase === "saving"
      ? { tone: "text-subtle", icon: <Spinner size={12} />, text: tr("Speichert …", "Saving …", "Guardando …") }
      : phase === "testing"
        ? { tone: "text-subtle", icon: <Spinner size={12} />, text: tr("Verbindung wird geprüft …", "Checking connection …", "Comprobando conexión …") }
        : result && !dirty
          ? result.ok
            ? { tone: "text-ok", icon: <span className="anim-check inline-flex"><Check size={15} aria-hidden="true" /></span>, text: tr("Verbunden", "Connected", "Conectado") }
            : { tone: "text-bad", icon: <XCircle size={14} aria-hidden="true" />, text: tr("Keine Verbindung", "No connection", "Sin conexión") }
          : null;

  return (
    <div className="space-y-5">
      <SectionTitle
        quiet
        title={tr("Modelle", "Models", "Modelos")}
        text={tr(
          "Jeder Modellwechsel wird signiert im Protokoll vermerkt.",
          "Every model change is signed and recorded in the audit trail.",
          "Cada cambio de modelo queda firmado en el registro.",
        )}
      />
      <Segmented<"local" | "cloud">
        ariaLabel={tr("Wo geprüft wird", "Where audits run", "Dónde se analiza")}
        value={location}
        onChange={setLocation}
        disabled={busy}
        options={[
          { value: "local", label: tr("Lokal (Ollama)", "Local (Ollama)", "Local (Ollama)") },
          { value: "cloud", label: tr("Cloud (API)", "Cloud (API)", "Nube (API)") },
        ]}
      />

      {catalog?.upgrade && catalog.upgrade !== model && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ok-line bg-ok-soft px-3 py-2 text-xs text-fg">
          <ArrowUpCircle size={14} className="text-ok" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {tr("Neueres Modell verfügbar:", "Newer model available:", "Modelo más reciente disponible:")} <span className="font-semibold">{catalog.upgrade}</span>
          </span>
          <button className="btn btn-sm" disabled={busy} onClick={() => setModel(catalog.upgrade!)}>
            {tr("Auswählen", "Select", "Seleccionar")}
          </button>
        </div>
      )}

      {location === "cloud" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label={tr("Anbieter", "Provider", "Proveedor")}>
            <Select<CloudMode | "">
              value={provider}
              onChange={setProvider}
              options={CLOUD}
              disabled={busy}
              placeholder={tr("Anbieter wählen …", "Choose a provider …", "Elegir proveedor …")}
              ariaLabel={tr("Cloud-Anbieter", "Cloud provider", "Proveedor en la nube")}
              width={320}
              className="h-9 w-full justify-between"
            />
          </Field>
          <div>
            <span className="label-caps flex items-center gap-1.5">
              API-Key
              <Tooltip
                content={tr(
                  "Wird verschlüsselt auf dem Server gespeichert und nie im Klartext angezeigt. Weitere Keys unter „Ausweich-Kaskade“.",
                  "Stored encrypted on the server and never shown in plain text. More keys under “Fallback cascade”.",
                  "Se guarda cifrada en el servidor y nunca se muestra en claro. Más claves en «Cascada de respaldo».",
                )}
              >
                <span tabIndex={0} role="button" aria-label={tr("Hinweis zu API-Key", "Info: API key", "Información: Clave API")} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
              </Tooltip>
              {keyStored && (
                <span className="ml-auto flex items-center gap-1.5 normal-case tracking-normal text-subtle">
                  <KeyRound size={12} className="text-ok" aria-hidden="true" />
                  <span className="font-mono">{settings.masked_keys?.[mode as CloudMode] ?? "…"}</span>
                  <button type="button" className="font-medium text-subtle underline-offset-2 transition-colors duration-150 hover:text-bad hover:underline disabled:opacity-50" disabled={busy} onClick={() => void removeKey()}>
                    {tr("Entfernen", "Remove", "Eliminar")}
                  </button>
                </span>
              )}
            </span>
            <div className="mt-1">
              <KeyInput
                value={apiKey}
                onChange={setApiKey}
                name={`${mode ?? "cloud"}-api-key`}
                label={tr("API-Key", "API key", "Clave API")}
                disabled={!cloud || busy}
                placeholder={
                  !cloud
                    ? tr("Zuerst Anbieter wählen", "Choose a provider first", "Elija primero un proveedor")
                    : keyStored
                      ? tr("Zum Ersetzen neuen Key einfügen", "Paste a new key to replace it", "Pegue una clave nueva para reemplazarla")
                      : tr("Key einfügen …", "Paste API key …", "Pegar clave API …")
                }
              />
            </div>
          </div>
        </div>
      )}

      {mode !== null && (
        <div className="space-y-2">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <ModelSelect provider={mode} value={model} current={settings.models[mode]} onChange={setModel} catalog={catalog} label={tr("Hauptmodell", "Primary model", "Modelo principal")} disabled={!modelsReady || busy} />
            {cloud && (
              <div>
                <ModelSelect
                  provider={mode}
                  value={fallbackModel}
                  current={savedFallback}
                  onChange={setFallbackModel}
                  catalog={catalog}
                  label={tr("Ausweichmodell bei Überlast", "Fallback model on overload", "Modelo alternativo por sobrecarga")}
                  allowOff
                  exclude={model}
                  disabled={!modelsReady || busy}
                />
                {modelsReady && fallbackModel === "" && settings.suggested_fallback_models?.[mode] && (
                  <p className="mt-1.5 text-xs text-subtle">
                    {tr("Empfohlen:", "Recommended:", "Recomendado:")}{" "}
                    <button type="button" disabled={busy} className="font-medium text-accent underline-offset-2 hover:underline disabled:opacity-50" onClick={() => setFallbackModel(settings.suggested_fallback_models[mode])}>
                      {settings.suggested_fallback_models[mode]}
                    </button>
                  </p>
                )}
              </div>
            )}
          </div>
          {!modelsReady && (
            <p className="text-xs text-subtle">
              {tr(
                "Die Modell-Liste lädt, sobald der Key gespeichert ist.",
                "The model list loads once the key is saved.",
                "La lista de modelos se carga en cuanto se guarda la clave.",
              )}
            </p>
          )}
        </div>
      )}

      {cloud && (
        <details className="group rounded-lg border border-pii-line bg-pii-soft px-3 py-2 text-xs text-fg">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-pii">
            <Lock size={13} aria-hidden="true" />{" "}
            {tr(
              "Privacy Gateway: Belege gehen nur pseudonymisiert in die Cloud",
              "Privacy Gateway: documents reach the cloud only pseudonymized",
              "Privacy Gateway: los documentos llegan a la nube solo seudonimizados",
            )}
            <span className="ml-auto text-subtle transition-transform duration-150 group-open:rotate-90" aria-hidden="true">›</span>
          </summary>
          <p className="mt-2 max-w-[65ch] leading-relaxed text-muted">
            {tr(
              "Namen, Firmen, IBANs, Steuer-IDs, Adressen, Kontaktdaten und Beträge gehen nur als Platzhalter an den Anbieter und werden lokal wieder eingesetzt; die Zuordnung verlässt den Server nie (Art. 4 Nr. 5 DSGVO). Pseudonymisierte Daten bleiben personenbezogen – für jeden Anbieter der Kaskade sind AV-Vertrag und Transfergrundlage nötig.",
              "Names, companies, IBANs, tax IDs, addresses, contact details and amounts reach the provider only as placeholders and are restored locally; the mapping never leaves the server (GDPR Art. 4(5)). Pseudonymized data is still personal data – every provider in the cascade needs a DPA and a transfer basis.",
              "Nombres, empresas, IBAN, NIF, direcciones, contactos e importes llegan al proveedor solo como marcadores y se restauran en local; la asignación nunca sale del servidor (RGPD art. 4(5)). Los datos seudonimizados siguen siendo personales: cada proveedor necesita contrato de encargo y base de transferencia.",
            )}
          </p>
        </details>
      )}

      {result && !result.ok && !dirty && phase === "idle" && (
        <div className="anim-fade flex flex-wrap items-start gap-2 rounded-lg border border-bad-line bg-bad-soft p-3 text-xs text-fg" role="alert">
          <XCircle size={14} className="mt-0.5 shrink-0 text-bad" aria-hidden="true" />
          <span className="min-w-0 flex-1">{td(result.message)}</span>
          {result.suggested_model && (
            <button className="btn btn-sm" disabled={busy} onClick={() => setModel(result.suggested_model!)}>
              {tr(`${formatModel(result.suggested_model)} auswählen`, `Select ${formatModel(result.suggested_model)}`, `Seleccionar ${formatModel(result.suggested_model)}`)}
            </button>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-end gap-3">
        <span role="status" aria-live="polite" className="min-h-5">
          {status && (
            <span key={`${phase}-${result?.ok}`} className={cx("anim-fade flex items-center gap-1.5 text-xs font-medium", status.tone)}>
              {status.icon}
              {result?.ok && phase === "idle" ? (
                <Tooltip content={td(result.message)} align="right" inline>
                  <span tabIndex={0}>{status.text}</span>
                </Tooltip>
              ) : (
                status.text
              )}
            </span>
          )}
        </span>
        <button className="btn btn-primary min-w-[7.5rem] justify-center" onClick={() => void saveAndTest()} disabled={!canSave}>
          {tr("Speichern", "Save", "Guardar")}
        </button>
      </div>

      {location === "local" && (
        <div className="border-t border-line pt-4">
          <LocalAiControl active={active} onChanged={onAccessChanged} notify={notify} />
        </div>
      )}
    </div>
  );
}

/** Stufen des Cloud-Tageslimits; ein abweichender Wert (z. B. aus der Serverkonfiguration) bleibt wählbar. */
const BUDGET_STEPS = [-1, 100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000];
/** Wählbare Stufen; gibt der Server ein Limit vor, ist es die Obergrenze (kein „Ohne Limit“). */
function budgetOptions(current: number, max: number | null | undefined): number[] {
  const steps = max == null ? BUDGET_STEPS : [...BUDGET_STEPS.filter((step) => step >= 0 && step < max), max];
  return (steps.includes(current) ? steps : [...steps, current]).sort((a, b) => (a < 0 ? -1 : b < 0 ? 1 : a - b));
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
  const [provider, setProvider] = useState<CloudMode | "">("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  // Anbieter → Key → Modell: Die Modell-Liste kommt vom Anbieter (mit dessen Hauptschlüssel,
  // sonst die Vorschlagsliste); auswählbar erst, wenn ein Key eingefügt ist.
  const keyReady = key.trim().length >= 8;
  const backupCatalog = useCatalog(provider || "gemini", adding && Boolean(provider) && keyReady, settings);
  const backups = settings.ausweich_schluessel ?? [];
  const fallbacks = settings.fallbacks ?? [];
  const localFallback = fallbacks.includes("local");
  const keyed = (["gemini", "anthropic", "openai"] as CloudMode[]).filter(
    (mode) => mode !== settings.inference_mode && hasKey(settings, mode) && !fallbacks.includes(mode),
  );
  const isCloud = settings.inference_mode !== "local";
  const existing = () => backups.map(({ id, provider: p, model: m }) => ({ id, provider: p, model: m }));

  const retries = (settings.retry_delays ?? []).map((seconds) => `${seconds.toLocaleString(LOCALE_TAG[locale])} s`).join(", ");
  const stageLabels: Record<string, string> = {
    primary: tr("Hauptmodell", "Primary model", "Modelo principal"),
    ausweichmodell: tr("Ausweichmodell", "Fallback model", "Modelo alternativo"),
    ausweich_schluessel: tr("Ausweich-Schlüssel", "Backup API key", "Clave de respaldo"),
    fallback: tr("Anbieter-Fallback", "Provider fallback", "Proveedor alternativo"),
  };

  async function addBackup() {
    if (!provider) return;
    const ok = await save({
      ausweich_schluessel: [...existing(), { id: `k${Date.now().toString(36)}`, provider, model: model.trim() || undefined, api_key: key.trim() }],
    });
    if (ok) {
      setKey("");
      setModel("");
      setProvider("");
      setAdding(false);
      notify("ok", tr("Ausweich-Schlüssel hinzugefügt", "Backup key added", "Clave de respaldo añadida"), tr("Verschlüsselt gespeichert.", "Stored encrypted.", "Guardada cifrada."));
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        quiet
        title={tr("Ausweich-Kaskade", "Fallback cascade", "Cascada de respaldo")}
        text={tr(
          "Antwortet eine Stufe nicht, versucht sie es kurz erneut und gibt dann an die nächste ab. Ein abgelehnter Key löst keinen Wechsel aus.",
          "If a stage does not respond, it retries briefly and then hands over to the next. A rejected key never triggers a switch.",
          "Si un nivel no responde, reintenta brevemente y pasa al siguiente. Una clave rechazada nunca provoca un cambio.",
        )}
        hint={tr(
          `Wechsel bei HTTP 408, 429, 5xx, Verbindungsfehler, Zeitüberschreitung oder erreichtem Tageslimit; Wiederholung nach ${retries || "–"}. Kein Wechsel bei 401/403 oder Schemafehlern. Jeder Wechsel steht signiert im Protokoll; alle Cloud-Stufen laufen durch dasselbe Privacy Gateway.`,
          `Switches on HTTP 408, 429, 5xx, connection errors, timeouts or a reached daily limit; retries after ${retries || "–"}. No switch on 401/403 or schema errors. Every switch is signed in the audit trail; all cloud stages share the same Privacy Gateway.`,
          `Cambia ante HTTP 408, 429, 5xx, errores de conexión, tiempo agotado o límite diario alcanzado; reintenta tras ${retries || "–"}. Sin cambio ante 401/403 o errores de esquema. Cada cambio queda firmado en el registro.`,
        )}
      />

      <ol className="cascade-steps" aria-label={tr("Reihenfolge der Kaskade", "Cascade order", "Orden de la cascada")}>
        {(settings.chain ?? []).map((stage, index) => (
          <li key={`${stage.stage}-${stage.backup_id ?? stage.provider}-${index}`} className="cascade-step">
            <span className="cascade-dot" aria-hidden="true">{index + 1}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-fg">{providerDisplayName(stage.provider)} <span className="text-muted">· {stage.model}</span></span>
              <span className="block text-xs text-subtle">{stageLabels[stage.stage]}</span>
            </span>
          </li>
        ))}
        <li className="cascade-step">
          <span className="cascade-dot cascade-dot-final" aria-hidden="true">{(settings.chain?.length ?? 0) + 1}</span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm text-fg">{tr("Regelwerk", "Ruleset", "Motor de reglas")} <span className="text-muted">· {tr("deterministisch", "deterministic", "determinista")}</span></span>
            <span className={cx("block text-xs", settings.heuristic_fallback ? "text-subtle" : "text-warn")}>
              {settings.heuristic_fallback
                ? tr("Letzte Stufe – Ergebnis wird als Regelwerk-Audit gekennzeichnet", "Final stage – result is badged as a rules audit", "Último nivel: el resultado se marca como auditoría por reglas")
                : tr("Ausgeschaltet – fällt alles aus, bricht die Prüfung mit Fehler ab", "Off – if everything fails, the audit stops with an error", "Desactivado: si todo falla, el análisis termina con error")}
            </span>
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
              "Nur mit Cloud-Hauptmodell – lokal eingestellte Prüfungen gehen nie automatisch in die Cloud.",
              "Only with a cloud primary model – local audits never move to the cloud automatically.",
              "Solo con modelo principal en la nube: los análisis locales nunca pasan a la nube automáticamente.",
            )}
          </p>
        )}
        {backups.length > 0 && (
          <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line">
            {backups.map((backup, index) => (
              <li key={backup.id} className="flex items-center gap-2.5 px-3 py-2 text-xs">
                <span className="w-20 shrink-0 tabular-nums text-subtle">{tr("Backup", "Backup", "Respaldo")} {index + 1}</span>
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
                <Select<CloudMode | "">
                  value={provider}
                  onChange={(value) => {
                    setProvider(value);
                    setModel("");
                  }}
                  options={CLOUD}
                  placeholder={tr("Anbieter wählen …", "Choose a provider …", "Elegir proveedor …")}
                  ariaLabel={tr("Anbieter des Ausweich-Schlüssels", "Backup key provider", "Proveedor de clave de respaldo")}
                  width={240}
                  className="h-9 w-full justify-between"
                />
              </Field>
              <Field label="API-Key" hint={tr("Auch ein zweiter Key desselben Anbieters, etwa aus einem anderen Projekt.", "A second key from the same provider works too, e.g. from another project.", "También sirve una segunda clave del mismo proveedor.")}>
                <KeyInput
                  value={key}
                  onChange={setKey}
                  name="backup-api-key"
                  label="API-Key"
                  disabled={!provider || busy}
                  placeholder={provider ? tr("Key einfügen …", "Paste API key …", "Pegar clave API …") : tr("Zuerst Anbieter wählen", "Choose a provider first", "Elija primero un proveedor")}
                />
              </Field>
            </div>
            <Field label={tr("Modell", "Model", "Modelo")}>
              <Select
                value={model}
                onChange={setModel}
                disabled={!provider || !keyReady}
                ariaLabel={tr("Modell des Ausweich-Schlüssels", "Backup key model", "Modelo de la clave de respaldo")}
                width={320}
                className="h-9 w-full justify-between"
                placeholder={!provider || !keyReady ? tr("Zuerst Key einfügen", "Paste a key first", "Pegue primero una clave") : undefined}
                options={
                  provider && keyReady
                    ? [
                        { value: "", label: tr(`Hauptmodell (${settings.models[provider]})`, `Primary model (${settings.models[provider]})`, `Modelo principal (${settings.models[provider]})`) },
                        ...(backupCatalog?.models ?? []).filter((name) => name !== settings.models[provider]).map((name) => ({ value: name, label: name })),
                      ]
                    : []
                }
              />
            </Field>
            <div className="flex justify-end gap-2">
              <button
                className="btn"
                onClick={() => {
                  setAdding(false);
                  setProvider("");
                  setKey("");
                  setModel("");
                }}
              >
                {tr("Abbrechen", "Cancel", "Cancelar")}
              </button>
              <button className="btn btn-primary" disabled={busy || !provider || !keyReady} onClick={() => void addBackup()}>
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
            description={tr("Wenn alle Cloud-Stufen ausfallen – der Beleg bleibt dann auf diesem Rechner.", "When all cloud stages fail – the document then stays on this machine.", "Si fallan todos los niveles en la nube; el documento se queda en este equipo.")}
          />
        ) : (
          <p className="text-xs text-subtle">
            {tr("Lokal ist das Hauptmodell; fällt es aus, übernimmt das Regelwerk.", "Local is the primary model; if it fails, the ruleset takes over.", "El modelo principal es local; si falla, actúa el motor de reglas.")}
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
            {tr("Anbieter anhängen:", "Append provider:", "Añadir proveedor:")}
            {keyed.map((mode) => (
              <button key={mode} className="btn btn-sm" disabled={busy} onClick={() => void save({ fallbacks: [...fallbacks.filter((item) => item !== "local"), mode, ...(localFallback ? ["local" as const] : [])] })}>
                <Plus size={12} aria-hidden="true" /> {providerDisplayName(mode)}
              </button>
            ))}
          </div>
        )}
      </section>

      {settings.cloud_budget && (
        <section className="space-y-2 border-t border-line pt-4">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-xs">
            <span className="label-caps flex items-center gap-1.5">
              {tr("Cloud-Tageslimit", "Daily cloud limit", "Límite diario de la nube")}
              <Tooltip
                content={tr(
                  "Schützt den eigenen API-Key vor unerwarteten Kosten. Gezählt werden die Tokens aller Cloud-Aufrufe seit Mitternacht (UTC); lokale Modelle zählen nicht. Ist das Limit erreicht, prüfen bis zum nächsten Tag lokale Stufen bzw. das Regelwerk – keine Prüfung bricht ab. Gibt der Server ein Limit vor, ist es die Obergrenze.",
                  "Protects your own API key from unexpected costs. Counts the tokens of all cloud calls since midnight (UTC); local models do not count. Once reached, local stages or the ruleset take over until the next day – no audit is aborted. A limit set on the server is the maximum.",
                  "Protege su clave API de costes inesperados. Cuenta los tokens de todas las llamadas a la nube desde medianoche (UTC); los modelos locales no cuentan. Al alcanzarlo, actúan los niveles locales o el motor de reglas hasta el día siguiente. Un límite del servidor es el máximo.",
                )}
              >
                <span tabIndex={0} role="button" aria-label={tr("Hinweis zum Cloud-Tageslimit", "Info: Daily cloud limit", "Información: Límite diario de la nube")} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
              </Tooltip>
            </span>
            <span className="flex items-center gap-3">
              <span className="tabular-nums text-muted">
                {tr("Heute", "Today", "Hoy")} <span className="font-medium text-fg">{settings.cloud_budget.tokens.toLocaleString(LOCALE_TAG[locale])}</span> {tr("Tokens", "tokens", "tokens")}
              </span>
              <Select<string>
                value={String(settings.cloud_budget.enabled ? settings.cloud_budget.limit : -1)}
                onChange={(value) => void save({ cloud_daily_token_limit: Number(value) })}
                disabled={busy}
                ariaLabel={tr("Cloud-Tageslimit", "Daily cloud limit", "Límite diario de la nube")}
                width={200}
                className="h-8 min-w-[9.5rem] justify-between"
                options={budgetOptions(settings.cloud_budget.enabled ? settings.cloud_budget.limit : -1, settings.cloud_budget.max).map((limit) => ({
                  value: String(limit),
                  label: limit < 0 ? tr("Ohne Limit", "No limit", "Sin límite") : `${limit.toLocaleString(LOCALE_TAG[locale])} ${tr("Tokens", "tokens", "tokens")}`,
                  hint:
                    limit === settings.cloud_budget?.max
                      ? tr("Obergrenze des Servers", "Server maximum", "Máximo del servidor")
                      : undefined,
                }))}
              />
            </span>
          </div>
          {settings.cloud_budget.enabled && (
            <ProgressBar
              value={settings.cloud_budget.limit > 0 ? Math.min(1, settings.cloud_budget.tokens / settings.cloud_budget.limit) : 0}
              label={tr("Cloud-Tageslimit", "Daily cloud limit", "Límite diario de la nube")}
            />
          )}
        </section>
      )}
    </div>
  );
}

function ComplianceSection({ settings, onSaved, notify }: { settings: RuntimeSettings; onSaved: (settings: RuntimeSettings) => void; notify: Notify }) {
  const { tr, td } = useI18n();
  const { busy: saving, save } = useSave(onSaved, notify);
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
      label: tr("Standard", "Standard", "Estándar"),
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
      notify("bad", tr("Testschwärzung fehlgeschlagen", "Redaction test failed", "Error en la prueba de anonimización"), err instanceof ApiError ? td(err.message) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Compliance"
        text={tr(
          "Gilt ab der nächsten Prüfung; bisherige Ergebnisse bleiben unverändert.",
          "Applies from the next audit; existing results stay unchanged.",
          "Se aplica desde el próximo análisis; los resultados anteriores no cambian.",
        )}
      />
      <div>
        <p className="label-caps mb-2">{tr("Maskierung in der Belegansicht", "Masking in the document view", "Ocultación en la vista del documento")}</p>
        <Segmented<PiiStrictness>
          ariaLabel={tr("PII-Maskierungsgrad", "PII masking level", "Nivel de ocultación PII")}
          value={settings.pii_strictness}
          onChange={(value) => void save({ pii_strictness: value })}
          disabled={saving}
          options={strictnessOptions.map(({ value, label, text }) => ({ value, label, tooltip: text }))}
        />
        <p className="mt-2 text-xs text-muted">{strictnessOptions.find((s) => s.value === settings.pii_strictness)?.text}</p>
        <p className="mt-1 text-xs text-subtle">
          {tr("Gespeichert wird unabhängig davon immer maskiert.", "Findings are always stored masked, regardless of this setting.", "Los hallazgos se guardan siempre enmascarados.")}
        </p>
      </div>
      <Toggle
        checked={settings.enforce_ustg_check}
        onChange={(value) => void save({ enforce_ustg_check: value })}
        disabled={saving}
        label={tr("Pflichtangaben nach § 14 UStG prüfen", "Check mandatory details under Sec. 14 UStG", "Comprobar datos obligatorios (§ 14 UStG)")}
        description={tr("Bei Rechnungen alle Angaben nach § 14 Abs. 4 UStG; fließt in den Score ein.", "All details under Sec. 14(4) UStG for invoices; counts towards the score.", "Todos los datos del § 14(4) UStG en facturas; cuenta para la puntuación.")}
      />
      <Toggle
        checked={settings.ai_act_escalation}
        onChange={(value) => void save({ ai_act_escalation: value })}
        disabled={saving}
        label={tr("Hochrisiko nach EU AI Act automatisch einstufen", "Auto-classify high risk under the EU AI Act", "Clasificar alto riesgo (Reglamento IA) automáticamente")}
        description={tr("Sobald eine Anhang-III-Kategorie belegt ist – auch wenn das Modell niedriger bewertet.", "As soon as an Annex III category applies – even if the model rates lower.", "En cuanto aplica una categoría del Anexo III, aunque el modelo valore más bajo.")}
      />

      <section className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="label-caps">{tr("Schwärzungs-Schnittstelle (DLP)", "Redaction interface (DLP)", "Interfaz de anonimización (DLP)")}</p>
          <span className="text-xs tabular-nums text-subtle">{tr("Regelwerk", "Ruleset", "Reglamento")} {settings.dlp?.ruleset_version ?? "–"}</span>
        </div>
        <p className="max-w-[65ch] text-xs leading-relaxed text-muted">
          {tr(
            "Andere Anwendungen schicken Texte an diese Schnittstelle und erhalten sie endgültig geschwärzt zurück, bevor sie an ein Cloud-LLM gehen: Zugangsdaten, vertrauliche Begriffe und personenbezogene Daten. Nichts wird gespeichert.",
            "Other applications send text to this interface and get it back permanently redacted before it reaches a cloud LLM: credentials, confidential terms and personal data. Nothing is stored.",
            "Otras aplicaciones envían textos a esta interfaz y los reciben anonimizados de forma definitiva antes de llegar a un LLM en la nube. No se guarda nada.",
          )}
        </p>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-subtle">
          <code className="font-mono text-muted">POST {settings.dlp?.endpoint ?? "/api/v1/redact"}</code>
          <Tooltip content={tr("Festgelegt in der Serverkonfiguration (DLP_TERMS).", "Set in the server configuration (DLP_TERMS).", "Definidos en la configuración del servidor (DLP_TERMS).")}>
            <span tabIndex={0} className="tabular-nums">
              {tr(
                `${settings.dlp?.configured_terms ?? 0} eigene Sperrbegriffe`,
                `${settings.dlp?.configured_terms ?? 0} custom blocked terms`,
                `${settings.dlp?.configured_terms ?? 0} términos bloqueados propios`,
              )}
            </span>
          </Tooltip>
        </p>
        <AutoTextarea
          minRows={2}
          maxRows={6}
          value={probe}
          onChange={(event) => setProbe(event.target.value)}
          name="dlp-probe"
          aria-label={tr("Text für die Testschwärzung", "Text for the redaction test", "Texto para la prueba de anonimización")}
          placeholder={tr("Testtext einfügen, z. B. eine Zeile mit IBAN und E-Mail …", "Paste sample text, e.g. a line with an IBAN and an email …", "Pegar texto de prueba, p. ej. una línea con IBAN y correo …")}
        />
        <div className="flex justify-end">
          <button className="btn btn-sm" onClick={() => void runProbe()} disabled={busy || !probe.trim()}>
            {busy && <Spinner size={11} />} {tr("Schwärzung testen", "Test redaction", "Probar anonimización")}
          </button>
        </div>
        {result && (
          <div className="rounded-lg border border-line bg-surface-2 p-3 text-xs">
            <p className="whitespace-pre-wrap break-words text-fg">{result.redacted_text}</p>
            <p className="mt-2 text-subtle">
              <span className="tabular-nums">{result.total}</span> {tr("Schwärzungen", "redactions", "ocultaciones")}
              {Object.keys(result.counts).length > 0 && ` · ${Object.entries(result.counts).map(([category, count]) => `${td(category)} ${count}`).join(" · ")}`}
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
          "Sprache der Oberfläche, des Copilot und der Exporte; beides gilt für diesen Browser.",
          "Language of the interface, Copilot and exports; both apply to this browser.",
          "Idioma de la interfaz, del Copilot y de las exportaciones; ambos se aplican a este navegador.",
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
      <Field label={tr("Farbschema", "Color theme", "Tema de color")}>
        <Segmented<ThemeChoice>
          ariaLabel={tr("Farbschema", "Color theme", "Tema de color")}
          value={choice}
          onChange={setChoice}
          options={[
            { value: "dark", label: tr("Dunkel", "Dark", "Oscuro") },
            { value: "light", label: tr("Hell", "Light", "Claro") },
            { value: "system", label: tr("System", "System", "Sistema") },
          ]}
        />
      </Field>
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
          "Lokal ist hier nichts einzustellen. Ein Zugangsschlüssel ist nur nötig, wenn das Backend zentral mit Zugangsschutz läuft.",
          "Nothing to configure for local use. An access key is only needed when the backend runs centrally with access control.",
          "En uso local no hay nada que configurar. Solo se necesita una clave si el backend central tiene control de acceso.",
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
            label={tr("Zugangsschlüssel", "Access key", "Clave de acceso")}
            hint={tr("Vom Administrator des Servers (API_KEY). Wird nur in diesem Browser gespeichert und als X-API-Key mitgesendet.", "From the server administrator (API_KEY). Stored only in this browser and sent as X-API-Key.", "Del administrador del servidor (API_KEY). Solo se guarda en este navegador y se envía como X-API-Key.")}
          >
            <form autoComplete="off" onSubmit={(event) => event.preventDefault()}>
              <HiddenUsername />
              <input
                className="input font-mono placeholder:font-sans"
                type="password"
                value={accessKey}
                onChange={(event) => setAccessKeyState(event.target.value)}
                placeholder={tr("Zugangsschlüssel einfügen …", "Paste access key …", "Pegar clave de acceso …")}
                name="access-key"
                aria-label={tr("Zugangsschlüssel", "Access key", "Clave de acceso")}
                autoComplete="new-password"
                data-1p-ignore
                data-lpignore="true"
                spellCheck={false}
              />
            </form>
          </Field>
          <div className="flex justify-end">
            <button
              className="btn btn-primary"
              onClick={() => {
                setAccessKey(accessKey.trim());
                onAccessChanged();
                notify("ok", tr("Zugangsschlüssel gespeichert", "Access key saved", "Clave de acceso guardada"), tr("Nur in diesem Browser.", "In this browser only.", "Solo en este navegador."));
              }}
            >
              {tr("Übernehmen", "Save", "Aplicar")}
            </button>
          </div>
        </>
      ) : (
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowKeyForm(true)}>
          <KeyRound size={13} aria-hidden="true" /> {tr("Zugangsschlüssel eingeben", "Enter access key", "Introducir clave de acceso")}
        </button>
      )}

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
  const uses: { icon: React.ReactNode; title: string; text: string }[] = [
    {
      icon: <FileText size={15} aria-hidden="true" />,
      title: tr("Rechnungen vorprüfen", "Pre-check invoices", "Revisar facturas"),
      text: tr("Pflichtangaben, Rechenwerte, Steuersatz, IBAN; USt-IdNr. auf Klick über VIES.", "Mandatory details, arithmetic, tax rate, IBAN; VAT ID via VIES on click.", "Datos obligatorios, cálculos, tipo impositivo, IBAN; NIF-IVA vía VIES con un clic."),
    },
    {
      icon: <FileCode size={15} aria-hidden="true" />,
      title: tr("E-Rechnungen lesen", "Read e-invoices", "Leer facturas electrónicas"),
      text: tr("ZUGFeRD, Factur-X und XRechnung; bei hybriden Rechnungen gilt das XML.", "ZUGFeRD, Factur-X and XRechnung; for hybrid invoices the XML prevails.", "ZUGFeRD, Factur-X y XRechnung; en facturas híbridas prevalece el XML."),
    },
    {
      icon: <Scale size={15} aria-hidden="true" />,
      title: tr("Verträge einstufen", "Classify contracts", "Clasificar contratos"),
      text: tr("Risikoklasse nach EU AI Act und sensible Daten nach DSGVO, mit Fundstellen.", "EU AI Act risk class and sensitive data under the GDPR, with evidence.", "Clase de riesgo del Reglamento IA y datos sensibles según el RGPD, con evidencias."),
    },
    {
      icon: <MessageSquare size={15} aria-hidden="true" />,
      title: tr("Fragen zum Beleg", "Ask about a document", "Preguntar sobre el documento"),
      text: tr("Der Copilot antwortet aus dem Beleg und nennt die Stelle.", "The copilot answers from the document and cites the passage.", "El copiloto responde a partir del documento y cita el pasaje."),
    },
    {
      icon: <Package size={15} aria-hidden="true" />,
      title: tr("Prüfung nachweisen", "Prove the audit", "Acreditar la revisión"),
      text: tr("Prüfbericht, signiertes GoBD-Prüfdatenpaket und Verfahrensdokumentation.", "Audit report, signed GoBD data package and procedural documentation.", "Informe, paquete de datos GoBD firmado y documentación del procedimiento."),
    },
    {
      icon: <Lock size={15} aria-hidden="true" />,
      title: tr("Texte schwärzen", "Redact text", "Anonimizar textos"),
      text: tr("Andere Anwendungen schwärzen über die DLP-Schnittstelle, bevor sie eine Cloud-KI nutzen.", "Other applications redact via the DLP interface before using a cloud AI.", "Otras aplicaciones anonimizan mediante la interfaz DLP antes de usar una IA en la nube."),
    },
  ];
  const steps: { title: string; text: string }[] = [
    {
      title: tr("Lesen", "Read", "Leer"),
      text: tr("Textebene des PDFs bzw. XML der E-Rechnung.", "Text layer of the PDF or the e-invoice XML.", "Capa de texto del PDF o XML de la factura electrónica."),
    },
    {
      title: tr("Schützen", "Protect", "Proteger"),
      text: tr("Personenbezogene Daten und Beträge werden erkannt und vor jedem Cloud-Aufruf pseudonymisiert; Beträge, Steuern und Summen ermittelt das Regelwerk aus dem Belegtext.", "Personal data and amounts are detected and pseudonymized before every cloud call; amounts, taxes and totals are determined by the rule engine from the document text.", "Los datos personales y los importes se detectan y se seudonimizan antes de cada llamada a la nube; importes, impuestos y totales los determina el motor de reglas a partir del texto."),
    },
    {
      title: tr("Prüfen", "Check", "Comprobar"),
      text: tr("Das Sprachmodell liefert Fundstellen; feste Regeln prüfen sie nach, Pflichtangaben zusätzlich direkt im Text.", "The language model supplies evidence; fixed rules verify it, mandatory details also directly in the text.", "El modelo aporta evidencias; reglas fijas las verifican, los datos obligatorios también en el texto."),
    },
    {
      title: tr("Bewerten", "Score", "Puntuar"),
      text: tr("Der Score startet bei 100, jeder Mangel kostet einen festen Abzug. Gleiche Eingabe, gleicher Score – die KI vergibt keine Punkte. Ab 85 grün, ab 60 gelb, darunter rot; mit Mangel oder Vorbehalt höchstens gelb.", "The score starts at 100 and every defect costs a fixed deduction. Same input, same score – the AI awards no points. Green from 85, amber from 60, red below; with a defect or reservation at most amber.", "La puntuación parte de 100 y cada defecto resta una cantidad fija. Misma entrada, misma puntuación: la IA no otorga puntos. Verde desde 85, ámbar desde 60, rojo por debajo; con un defecto o reserva, como máximo ámbar."),
    },
    {
      title: tr("Belegen", "Record", "Registrar"),
      text: tr("Jeder Schritt steht hash-verkettet im Protokoll; die Prüfperson bestätigt mit einem signierten Siegel.", "Every step is hash-chained in the audit trail; the reviewer confirms with a signed seal.", "Cada paso queda encadenado por hash en el registro; el revisor confirma con un sello firmado."),
    },
  ];
  return (
    <div className="space-y-6">
      <SectionTitle
        title="Enterprise Compliance Agent"
        text={tr(
          "Prüft Rechnungen und Verträge vor, bevor sie gebucht oder unterschrieben werden – nach UStG, E-Rechnungs-Norm, DSGVO und EU AI Act. Jede Prüfung steht signiert im Protokoll und ist für Buchhaltung, Revision und Betriebsprüfung nachvollziehbar.",
          "Pre-audits invoices and contracts before they are booked or signed – against German VAT law, the e-invoicing standard, the GDPR and the EU AI Act. Every audit is signed in the audit trail and traceable for accounting, internal audit and tax audits.",
          "Revisa facturas y contratos antes de contabilizarlos o firmarlos, según la ley del IVA alemana, la norma de factura electrónica, el RGPD y el Reglamento de IA. Cada revisión queda firmada en el registro y es trazable.",
        )}
      />
      <ReleasePanel initial={release} installedVersion={version} externalChecking={checking} notify={notify} />

      <section>
        <p className="label-caps">{tr("Wofür", "What it does", "Para qué sirve")}</p>
        <ul className="mt-2.5 grid grid-cols-1 gap-x-5 gap-y-3 sm:grid-cols-2">
          {uses.map((use) => (
            <li key={use.title} className="flex gap-2.5">
              <span className="mt-0.5 shrink-0 text-subtle">{use.icon}</span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-fg">{use.title}</span>
                <span className="block text-xs leading-relaxed text-muted">{use.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="border-t border-line pt-4">
        <p className="label-caps">{tr("So entsteht das Ergebnis", "How the result comes about", "Cómo se obtiene el resultado")}</p>
        <ol className="cascade-steps mt-2.5">
          {steps.map((step, index) => (
            <li key={step.title} className="cascade-step">
              <span className="cascade-dot" aria-hidden="true">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-fg">{step.title}</span>
                <span className="block max-w-[70ch] text-xs leading-relaxed text-muted">{step.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-t border-line pt-4">
        <p className="label-caps">{tr("Prüfumfang", "Scope", "Alcance")}</p>
        <p className="mt-2 max-w-[70ch] text-xs leading-relaxed text-muted">
          {tr(
            "Prüft Pflichtangaben nach § 14 UStG und Rechenwerte, bei E-Rechnungen zusätzlich Profil, XRechnung-Version und ausgewählte Geschäftsregeln (BR-CO, BR-DE). Eine vollständige Schematron-Validierung nach EN 16931 bzw. XRechnung ersetzt das nicht – dafür z. B. den KoSIT-Validator nutzen.",
            "Checks mandatory details under Sec. 14 UStG and arithmetic; for e-invoices also the profile, XRechnung version and selected business rules (BR-CO, BR-DE). This does not replace full Schematron validation under EN 16931 or XRechnung – use e.g. the KoSIT validator for that.",
            "Comprueba los datos obligatorios del § 14 UStG y los cálculos; en facturas electrónicas también el perfil, la versión XRechnung y reglas de negocio seleccionadas (BR-CO, BR-DE). No sustituye una validación Schematron completa según EN 16931 o XRechnung; para ello, use p. ej. el validador KoSIT.",
          )}
        </p>
      </section>

      <div className="border-t border-line pt-4">
        <p className="label-caps">{tr("Regulatorischer Stand", "Regulatory baseline", "Marco normativo")}</p>
        <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-muted">
          <li>{tr("EU AI Act – VO (EU) 2024/1689; Anhang-III-Pflichten ab 02.12.2027 (VO (EU) 2026/1744)", "EU AI Act – Reg. (EU) 2024/1689; Annex III obligations from 02 Dec 2027 (Reg. (EU) 2026/1744)", "Reglamento IA – Reg. (UE) 2024/1689; obligaciones Anexo III desde 02/12/2027")}</li>
          <li>{tr("§ 14 Abs. 4 UStG, E-Rechnung nach EN 16931; XML-Vorrang nach BMF-Schreiben vom 15.10.2024, Rz. 36", "Sec. 14(4) UStG, E-Invoice under EN 16931; XML precedence under BMF 15 Oct 2024", "§ 14(4) UStG, factura electrónica EN 16931; prioridad XML según circular BMF 15/10/2024")}</li>
          <li>{tr("GoBD Rz. 151–155 (Verfahrensdokumentation); Aufbewahrung 8 bzw. 10 Jahre (§ 147 AO, BEG IV)", "GoBD para. 151–155 (Procedural Docs); retention 8 / 10 years (§ 147 AO, BEG IV)", "GoBD Rz. 151–155 (Documentación); conservación 8 / 10 años (§ 147 AO, BEG IV)")}</li>
          <li>{tr("DSGVO Art. 4 Nr. 5, 25, 32 – Pseudonymisierung vor jedem Cloud-Aufruf; DLP-Gateway unter /api/v1/redact", "GDPR Art. 4(5), 25, 32 – Pseudonymization before cloud calls; DLP gateway at /api/v1/redact", "RGPD Art. 4(5), 25, 32 – Seudonimización previa a la nube; DLP Gateway en /api/v1/redact")}</li>
        </ul>
        <p className="mt-2 text-xs text-subtle">
          {tr(
            "Technische Vorprüfung – keine Rechts- oder Steuerberatung. Die Entscheidung trifft immer die Prüfperson.",
            "Technical pre-audit – not legal or tax advice. The decision always rests with the reviewer.",
            "Pre-auditoría técnica: no constituye asesoramiento legal ni fiscal. La decisión siempre es del revisor.",
          )}
        </p>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line pt-4 text-xs text-subtle">
        <span>
          {tr("Entwickelt von", "Built by", "Desarrollado por")} <span className="font-medium text-fg">Lutz Zarske</span> · {tr("MIT-Lizenz", "MIT licence", "Licencia MIT")}
        </span>
        <a
          href={SOURCE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 font-medium text-accent underline-offset-2 hover:underline"
        >
          {tr("Quellcode auf GitHub", "Source on GitHub", "Código en GitHub")} <ExternalLink size={12} aria-hidden="true" />
        </a>
      </footer>
    </div>
  );
}

const SOURCE_URL = "https://github.com/lutz-zarske/enterprise-compliance-agent";

/** Einstellungen: Kategorien links, ruhige Formulare rechts; feste Höhe, Inhalte scrollen im Panel. */
export function SettingsModal({ open, initialSection, authRequired = false, settings, health, version, onClose, onSaved, onAccessChanged, notify }: Props) {
  const { tr } = useI18n();
  const [section, setSection] = useState<Section>(initialSection ?? "ai");
  const [aiPart, setAiPart] = useState<AiPart>("models");
  const [release, setRelease] = useState<ReleaseStatus | null>(null);
  const [releaseChecking, setReleaseChecking] = useState(false);
  const needsSettings = section === "ai" || section === "compliance";

  useEffect(() => {
    if (open && initialSection) setSection(initialSection);
  }, [open, initialSection]);

  // Release-Status beim Öffnen vorab laden: zuerst lokal (sofort), dann mit Abgleich des Servers.
  useEffect(() => {
    if (!open || !health || authRequired) return;
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
  }, [open, health, authRequired]);

  const sections: { key: Section; label: string; icon: React.ReactNode }[] = [
    { key: "ai", label: tr("KI-Einrichtung", "AI setup", "Configuración IA"), icon: <Bot size={16} aria-hidden="true" /> },
    { key: "compliance", label: "Compliance", icon: <Scale size={15} aria-hidden="true" /> },
    { key: "appearance", label: tr("Darstellung", "Appearance", "Apariencia"), icon: <Palette size={15} aria-hidden="true" /> },
    { key: "connection", label: tr("Verbindung", "Connection", "Conexión"), icon: <Server size={15} aria-hidden="true" /> },
    { key: "about", label: tr("Über", "About", "Acerca de"), icon: <Info size={15} aria-hidden="true" /> },
  ];
  return (
    <Modal open={open} onClose={onClose} title={tr("Einstellungen", "Settings", "Ajustes")} width="max-w-5xl" padded={false}>
      <div className="grid h-[min(720px,calc(100vh-12rem))] min-h-[420px] grid-cols-1 grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[230px_minmax(0,1fr)] md:grid-rows-1">
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
            <div className="py-8 text-center text-sm text-subtle">
              <p>
                {authRequired
                  ? tr("Zugangsschlüssel erforderlich – bitte unter Verbindung hinterlegen.", "Access key required – please configure it under Connection.", "Se requiere clave de acceso – configúrela en Conexión.")
                  : tr("Backend nicht erreichbar – Einstellungen können nicht geladen werden.", "Backend unreachable – settings cannot be loaded.", "Backend no disponible – no se pueden cargar los ajustes.")}
              </p>
              {authRequired && (
                <button type="button" className="btn btn-sm mt-3" onClick={() => setSection("connection")}>
                  {tr("Zu Verbindung wechseln", "Open Connection", "Ir a Conexión")}
                </button>
              )}
            </div>
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
