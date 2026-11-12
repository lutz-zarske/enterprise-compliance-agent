"use client";

import React, { useCallback, useEffect, useState } from "react";
import { api, ApiError, getAccessKey, getApiBase, setAccessKey } from "../lib/api";
import type { ConnectionTestResult, InferenceMode, ModelCatalog, PiiStrictness, RuntimeSettings } from "../types/api";
import { cx, PROVIDER_NAMES } from "../lib/format";
import { ArrowUpCircle, CheckCircle, Eye, EyeOff, Info, Lock, Plus, Trash, XCircle } from "./icons";
import { ReleasePanel } from "./ReleaseAssistant";
import { Select } from "./Select";
import { Modal, Segmented, Spinner, Tabs, Toggle, Tooltip } from "./ui";

type Tab = "inference" | "compliance" | "system" | "about";
type CloudMode = Exclude<InferenceMode, "local">;

const CLOUD: { value: CloudMode; label: string }[] = [
  { value: "gemini", label: "Google Gemini" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "openai", label: "OpenAI GPT" },
];

const STRICTNESS: { value: PiiStrictness; label: string; text: string }[] = [
  { value: "strict", label: "Strikt", text: "Schwärzt Namen, Firmen, Adressen, Beträge, Datumsangaben, IBAN, Steuer-IDs, Kontakt- und Art.-9-Daten." },
  { value: "standard", label: "Standard", text: "Schwärzt IBAN, Steuernummer/USt-IdNr., E-Mail, Telefon, Kennnummern und Art.-9-Daten; Übriges wird markiert." },
  { value: "audit_only", label: "Audit-Only", text: "Markiert alle Treffer, schwärzt nichts – nur für interne Revisoren mit Berechtigung." },
];

const KEY_HINT = "Serverseitig Fernet-verschlüsselt gespeichert und nur maskiert zurückgegeben. Pro Anbieter genau ein Schlüssel.";

interface Props {
  open: boolean;
  settings: RuntimeSettings | null;
  version: string;
  onClose: () => void;
  onSaved: (settings: RuntimeSettings) => void;
  onAccessChanged: () => void;
  notify: (tone: "ok" | "bad" | "warn" | "info", title: string, message?: string) => void;
}

const hasKey = (settings: RuntimeSettings | null, mode: InferenceMode) =>
  mode === "local" || Boolean(settings?.[`has_${mode}_key` as keyof RuntimeSettings]);

/** Modell-Katalog des Providers (neueste zuerst); ohne Key die eingebaute Vorschlagsliste. */
function useCatalog(provider: InferenceMode, open: boolean, settings: RuntimeSettings | null) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const keyStored = hasKey(settings, provider);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setCatalog(null);
    api.models(provider).then((result) => alive && setCatalog(result)).catch(() => alive && setCatalog(null));
    return () => {
      alive = false;
    };
  }, [provider, open, keyStored]);
  return catalog;
}

function ModelSelect({ provider, value, onChange, catalog, label }: {
  provider: InferenceMode;
  value: string;
  onChange: (model: string) => void;
  catalog: ModelCatalog | null;
  label: string;
}) {
  const names = catalog?.models.length ? catalog.models : [];
  const all = value && !names.includes(value) ? [value, ...names] : names;
  return (
    <div>
      <span className="label-caps flex items-center gap-1.5">
        {label}
        <Tooltip content={catalog?.source === "api" ? "Liste aus der API des Anbieters, neueste zuerst." : catalog?.message ?? "Vorschlagsliste – mit hinterlegtem Key kommt die Liste direkt vom Anbieter."}>
          <span tabIndex={0} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
        </Tooltip>
      </span>
      <div className="mt-1">
        {all.length ? (
          <Select
            value={value}
            onChange={onChange}
            ariaLabel={`${label} (${PROVIDER_NAMES[provider]})`}
            width={300}
            className="h-9 w-full justify-between font-mono"
            options={all.map((name, index) => ({
              value: name,
              label: name,
              hint: index === 0 && catalog?.source === "api" ? "neuestes verfügbares Modell" : name === catalog?.current ? "aktuell eingestellt" : undefined,
            }))}
          />
        ) : (
          <div className="flex h-9 items-center gap-2 text-xs text-subtle"><Spinner size={12} /> Modelle werden geladen…</div>
        )}
      </div>
    </div>
  );
}

function InferenceTab({ settings, open, onSaved, notify }: Pick<Props, "settings" | "open" | "onSaved" | "notify">) {
  const [location, setLocation] = useState<"local" | "cloud">("local");
  const [provider, setProvider] = useState<CloudMode>("gemini");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const [adding, setAdding] = useState(false);
  const [fbProvider, setFbProvider] = useState<InferenceMode>("local");
  const [fbModel, setFbModel] = useState("");
  const [fbKey, setFbKey] = useState("");

  const mode: InferenceMode = location === "local" ? "local" : provider;
  const catalog = useCatalog(mode, open, settings);
  const fbCatalog = useCatalog(fbProvider, open && adding, settings);
  const keyStored = hasKey(settings, mode);

  useEffect(() => {
    if (!open || !settings) return;
    setLocation(settings.inference_mode === "local" ? "local" : "cloud");
    if (settings.inference_mode !== "local") setProvider(settings.inference_mode);
    setAdding(false);
    setResult(null);
  }, [open, settings]);

  // Modell je Provider: das gespeicherte; ist noch kein Key hinterlegt, das neueste aus dem Katalog.
  useEffect(() => {
    if (!settings) return;
    const fresh = mode !== "local" && !hasKey(settings, mode) && catalog?.source === "api";
    setModel(fresh && catalog?.models[0] ? catalog.models[0] : settings.models[mode]);
    setApiKey("");
    setResult(null);
  }, [mode, settings, catalog]);

  useEffect(() => {
    if (settings) setFbModel(fbCatalog?.models[0] && !hasKey(settings, fbProvider) ? fbCatalog.models[0] : settings.models[fbProvider]);
  }, [fbProvider, fbCatalog, settings]);

  const fallbacks = settings?.fallbacks ?? [];
  const available: InferenceMode[] = (["anthropic", "openai", "gemini", "local"] as InferenceMode[]).filter(
    (candidate) => candidate !== settings?.inference_mode && !fallbacks.includes(candidate),
  );

  async function save(update: Parameters<typeof api.updateSettings>[0], test?: InferenceMode) {
    setBusy(true);
    setResult(null);
    try {
      const updated = await api.updateSettings(update);
      onSaved(updated);
      if (test) setResult(await api.testConnection(test));
      return true;
    } catch (err) {
      notify("bad", "Speichern fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return null;
  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented<"local" | "cloud">
          value={location}
          onChange={setLocation}
          options={[
            { value: "local", label: "Lokal (Ollama)" },
            { value: "cloud", label: "Cloud (API)" },
          ]}
        />
        {location === "cloud" && (
          <Select<CloudMode> value={provider} onChange={setProvider} options={CLOUD} ariaLabel="Cloud-Anbieter" width={220} className="h-8" />
        )}
      </div>

      {catalog?.upgrade && catalog.upgrade !== model && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ok-line bg-ok-soft px-3 py-2 text-xs text-ok">
          <ArrowUpCircle size={14} aria-hidden="true" />
          <span className="min-w-0 flex-1">
            Neueres Modell verfügbar: <span className="font-mono font-semibold">{catalog.upgrade}</span> – Wechsel wird mit Modell-ID,
            Prompt-Hash und Zeitstempel im Ledger verankert.
          </span>
          <button className="btn" onClick={() => void save({ models: { [mode]: catalog.upgrade! } }, mode)} disabled={busy}>
            Übernehmen
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <ModelSelect provider={mode} value={model} onChange={setModel} catalog={catalog} label="Hauptmodell" />
        {mode !== "local" && (
          <label className="block">
            <span className="label-caps flex items-center gap-1.5">
              API-Key {keyStored && <span className="normal-case tracking-normal text-ok">· hinterlegt ({settings.masked_keys?.[mode]})</span>}
              <Tooltip content={KEY_HINT}>
                <span tabIndex={0} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
              </Tooltip>
            </span>
            <div className="relative mt-1">
              <input
                className="input h-9 pr-9 font-mono"
                type={showKey ? "text" : "password"}
                name={`${mode}-api-key`}
                value={apiKey}
                autoComplete="off"
                spellCheck={false}
                placeholder={keyStored ? "Neuen Key eingeben, um ihn zu ersetzen…" : "Key eingeben…"}
                onChange={(event) => setApiKey(event.target.value)}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-subtle hover:text-fg"
                onClick={() => setShowKey((value) => !value)}
                aria-label={showKey ? "Key verbergen" : "Key anzeigen"}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </label>
        )}
      </div>

      {mode !== "local" && (
        <details className="group rounded-lg border border-pii-line bg-pii-soft px-3 py-2 text-xs text-pii">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-medium">
            <Lock size={13} aria-hidden="true" /> Privacy Gateway: Vor Cloud-Aufruf lokal nach Art. 4 Nr. 5 DSGVO pseudonymisiert.
            <span className="ml-auto text-subtle transition-transform duration-150 group-open:rotate-90" aria-hidden="true">›</span>
          </summary>
          <p className="mt-2 leading-relaxed text-fg">
            Erkannte Namen mit Anrede oder Rolle, Firmen, IBANs, Steuer-IDs, Adressen, Kontaktdaten und Beträge gehen nur als
            Platzhalter an den Anbieter und werden lokal re-identifiziert. Pseudonymisierte Daten bleiben personenbezogen:
            AV-Vertrag und Transfergrundlage sind für jeden Anbieter der Kaskade nötig.
          </p>
        </details>
      )}

      {result && (
        <div className={cx("flex items-start gap-2 rounded-lg border p-3 text-xs", result.ok ? "border-ok-line bg-ok-soft text-ok" : "border-bad-line bg-bad-soft text-bad")}>
          {result.ok ? <CheckCircle size={14} className="mt-0.5" /> : <XCircle size={14} className="mt-0.5" />}
          <span>{result.message}</span>
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {mode !== "local" && keyStored && (
          <button className="btn" onClick={() => void save({ api_keys: { [mode as CloudMode]: "" } }).then((ok) => ok && notify("ok", "API-Key gelöscht"))}>
            Key löschen
          </button>
        )}
        <button
          className="btn btn-primary"
          onClick={() =>
            void save(
              { inference_mode: mode, models: { [mode]: model }, ...(apiKey && mode !== "local" ? { api_keys: { [mode]: apiKey } } : {}) },
              mode,
            ).then((ok) => ok && setApiKey(""))
          }
          disabled={busy || !model.trim() || (mode !== "local" && !keyStored && !apiKey)}
        >
          {busy && <Spinner size={13} />} Speichern &amp; Verbindung testen
        </button>
      </div>

      <section className="space-y-2 border-t border-line pt-4">
        <div className="flex items-center justify-between gap-2">
          <p className="label-caps flex items-center gap-1.5">
            Ausweich-Kaskade
            <Tooltip content="Bei HTTP 429 (Kontingent), Serverfehlern oder Zeitüberschreitung übernimmt die nächste Stufe. Jeder Wechsel steht im Ledger; abgelehnte Keys lösen bewusst keinen Wechsel aus.">
              <span tabIndex={0} className="text-subtle"><Info size={12} aria-hidden="true" /></span>
            </Tooltip>
          </p>
          {!adding && available.length > 0 && (
            <button className="btn" onClick={() => { setFbProvider(available[0]); setFbKey(""); setAdding(true); }}>
              <Plus size={14} aria-hidden="true" /> Weiteren Schlüssel / Fallback hinzufügen
            </button>
          )}
        </div>
        <ol className="space-y-1.5 text-sm">
          <li className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2">
            <span className="w-16 shrink-0 text-xs text-subtle">Primär</span>
            <span className="text-fg">{PROVIDER_NAMES[settings.inference_mode]}</span>
            <span className="ml-auto font-mono text-xs text-subtle">{settings.active_model}</span>
          </li>
          {fallbacks.map((fallback, index) => (
            <li key={fallback} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2">
              <span className="w-16 shrink-0 text-xs text-subtle">{fallback === "local" ? "Lokal" : `Backup ${index + 1}`}</span>
              <span className="text-fg">{PROVIDER_NAMES[fallback]}</span>
              {!hasKey(settings, fallback) && <span className="chip border-warn-line bg-warn-soft text-warn">Key fehlt – wird übersprungen</span>}
              <span className="ml-auto font-mono text-xs text-subtle">{settings.models[fallback]}</span>
              <button
                className="rounded-md p-1 text-subtle transition-colors duration-150 hover:text-bad"
                aria-label={`${PROVIDER_NAMES[fallback]} aus der Kaskade entfernen`}
                onClick={() => void save({ fallbacks: fallbacks.filter((item) => item !== fallback) })}
              >
                <Trash size={13} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
        {adding && (
          <div className="space-y-3 rounded-lg border border-accent-line p-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <span className="label-caps">Anbieter</span>
                <div className="mt-1">
                  <Select<InferenceMode>
                    value={fbProvider}
                    onChange={setFbProvider}
                    ariaLabel="Ausweich-Anbieter"
                    width={260}
                    className="h-9 w-full justify-between"
                    options={available.map((value) => ({ value, label: PROVIDER_NAMES[value] }))}
                  />
                </div>
              </div>
              <ModelSelect provider={fbProvider} value={fbModel} onChange={setFbModel} catalog={fbCatalog} label="Fallback-Modell" />
            </div>
            {fbProvider !== "local" && !hasKey(settings, fbProvider) && (
              <label className="block">
                <span className="label-caps">API-Key {PROVIDER_NAMES[fbProvider]}</span>
                <input
                  className="input mt-1 h-9 font-mono"
                  type="password"
                  name={`${fbProvider}-fallback-key`}
                  value={fbKey}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="Key eingeben…"
                  onChange={(event) => setFbKey(event.target.value)}
                />
              </label>
            )}
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setAdding(false)}>Abbrechen</button>
              <button
                className="btn btn-primary"
                disabled={busy || !fbModel || (fbProvider !== "local" && !hasKey(settings, fbProvider) && !fbKey)}
                onClick={() =>
                  void save({
                    fallbacks: [...fallbacks, fbProvider],
                    models: { [fbProvider]: fbModel },
                    ...(fbKey && fbProvider !== "local" ? { api_keys: { [fbProvider]: fbKey } } : {}),
                  }).then((ok) => ok && setAdding(false))
                }
              >
                Zur Kaskade hinzufügen
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export function SettingsModal({ open, settings, version, onClose, onSaved, onAccessChanged, notify }: Props) {
  const [tab, setTab] = useState<Tab>("inference");
  const [accessKey, setAccessKeyState] = useState("");

  useEffect(() => {
    if (open) setAccessKeyState(getAccessKey());
  }, [open]);

  const updateCompliance = useCallback(
    async (update: Parameters<typeof api.updateSettings>[0]) => {
      try {
        onSaved(await api.updateSettings(update));
      } catch (err) {
        notify("bad", "Speichern fehlgeschlagen", err instanceof ApiError ? err.message : String(err));
      }
    },
    [onSaved, notify],
  );

  return (
    <Modal open={open} onClose={onClose} title="Einstellungen" width="max-w-3xl">
      <Tabs<Tab>
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "inference", label: "Inferenz & KI-Provider" },
          { key: "compliance", label: "Compliance & Audit-Strenge" },
          { key: "system", label: "System & Verbindung" },
          { key: "about", label: "Über & Regulatorik" },
        ]}
      />

      {!settings && (tab === "inference" || tab === "compliance") && (
        <p className="py-8 text-center text-sm text-subtle">Backend nicht erreichbar – Einstellungen können nicht geladen werden.</p>
      )}

      {tab === "inference" && <InferenceTab settings={settings} open={open} onSaved={onSaved} notify={notify} />}

      {settings && tab === "compliance" && (
        <div className="space-y-4 pt-4">
          <div>
            <p className="label-caps mb-2">PII-Maskierungsgrad (Textansicht & Vorschau)</p>
            <Segmented<PiiStrictness>
              value={settings.pii_strictness}
              onChange={(value) => void updateCompliance({ pii_strictness: value })}
              options={STRICTNESS.map(({ value, label }) => ({ value, label }))}
            />
            <p className="mt-2 text-xs text-subtle">{STRICTNESS.find((s) => s.value === settings.pii_strictness)?.text}</p>
            <p className="mt-1 text-xs text-subtle">PII-Befunde werden unabhängig von dieser Stufe ausschließlich maskiert gespeichert.</p>
          </div>
          <Toggle
            checked={settings.enforce_ustg_check}
            onChange={(value) => void updateCompliance({ enforce_ustg_check: value })}
            label="§ 14 UStG Check erzwingen"
            description="Prüft bei Rechnungen alle Pflichtangaben nach § 14 Abs. 4 UStG und fließt in den Score ein."
          />
          <Toggle
            checked={settings.ai_act_escalation}
            onChange={(value) => void updateCompliance({ ai_act_escalation: value })}
            label="EU AI Act Hochrisiko-Eskalation"
            description="Stuft automatisch auf „Hochrisiko“, sobald eine Anhang-III-Kategorie belegt ist – auch wenn das Modell niedriger bewertet."
          />
          <p className="text-xs text-subtle">Änderungen gelten für die nächste Analyse; bestehende Prüfergebnisse bleiben unverändert im Ledger.</p>
        </div>
      )}

      {tab === "system" && (
        <div className="space-y-4 pt-4">
          <div>
            <p className="label-caps">Backend-Adresse</p>
            <p className="mt-1 font-mono text-sm text-fg">{getApiBase()}</p>
            <p className="mt-1.5 flex gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-muted">
              <Info size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
              Für lokalen Betrieb http://localhost:8001. Bei Einsatz im Firmennetzwerk oder Docker-Container die IP oder Domain des
              zentralen Compliance-Servers eintragen (NEXT_PUBLIC_API_BASE_URL bzw. PUBLIC_API_URL beim Build).
            </p>
          </div>
          <label className="block">
            <span className="label-caps">Zugangsschlüssel (X-API-Key)</span>
            <input
              className="input mt-1 font-mono"
              type="password"
              value={accessKey}
              onChange={(event) => setAccessKeyState(event.target.value)}
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

      {tab === "about" && (
        <div className="space-y-5 pt-4">
          <div>
            <p className="label-caps">Version &amp; Release-Assistent</p>
            <p className="mb-2 mt-1 text-xs text-subtle">
              Enterprise Compliance Agent <span className="font-mono tabular-nums">v{version}</span>. Updates nur nach Bestätigung
              des Commit-Hashes, als Fast-Forward und mit Datenbanksicherung.
            </p>
            {open && <ReleasePanel notify={notify} />}
          </div>
          <div>
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
      )}
    </Modal>
  );
}
