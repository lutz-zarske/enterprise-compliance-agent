"""Laufzeit-Einstellungen: Inferenz-Modus, Modelle, Ausweich-Kaskade, PII-Strenge, Provider-Keys.

Startwerte kommen aus der Umgebung (``Settings``); Änderungen über
``POST /api/settings`` werden in der Tabelle ``app_settings`` gespeichert und
überleben einen Neustart.

Ausweich-Kaskade
----------------------------
1. Hauptmodell des aktiven Providers (Hauptschlüssel)
2. Ausweichmodell desselben Anbieters (``ausweich_modelle``, gleicher Schlüssel)
3. Ausweich-Schlüssel der Reihe nach (``ausweich_schluessel``, höchstens sechs, auch
   mehrere Schlüssel desselben Anbieters, z. B. ein zweiter Gemini-Key)
4. Anbieter-Fallbacks (``fallbacks``: weitere Anbieter mit ihrem Hauptschlüssel,
   ``local`` = lokales Ollama)
5. Deterministisches Regelwerk (``services``), wenn alle KI-Stufen ausfallen

Stufen 2 und 3 gelten nur, wenn der aktive Provider ein Cloud-Anbieter ist: Eine
lokal eingestellte Prüfung geht nie automatisch in die Cloud.

Schlüsselverwaltung
--------------------
Provider-API-Keys und Ausweich-Schlüssel werden mit **Fernet** (AES-128-CBC +
HMAC-SHA256, ``cryptography``) verschlüsselt abgelegt.  Der Fernet-Schlüssel
stammt aus ``SETTINGS_ENCRYPTION_KEY``; fehlt er, wird einmalig
``data/.settings.key`` (Dateirechte 0600) erzeugt.  Ehrliche Einordnung: Liegt
der Schlüssel neben der Datenbank, schützt das vor dem versehentlichen Leak
eines DB-Backups, nicht vor einem Angreifer mit Vollzugriff auf den Server.
Produktiv gehört der Schlüssel in einen Secret-Store (Vault, Azure Key Vault,
AWS KMS).

Nach außen verlassen Keys diese Klasse nur maskiert (``sk-...a1b2``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

import anyio.to_thread
import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine

from app.config import Settings
from app.db import app_settings_table, utcnow

logger = logging.getLogger(__name__)


class InferenceMode(str, Enum):
    LOCAL = "local"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class PIIStrictness(str, Enum):
    STRICT = "strict"
    STANDARD = "standard"
    AUDIT_ONLY = "audit_only"


CLOUD_PROVIDERS: tuple[InferenceMode, ...] = (
    InferenceMode.GEMINI,
    InferenceMode.ANTHROPIC,
    InferenceMode.OPENAI,
)

#: Höchstzahl der Ausweich-Schlüssel.
MAX_BACKUP_KEYS = 6

#: Auswahl im Einstellungsdialog, solange kein Key hinterlegt ist (mit Key liefert die
#: Modell-Liste des Anbieters die tatsächlich verfügbaren Modelle, neueste zuerst).
#: Stand der Anbieter-Dokumentation 11/2026: nur aktive, nicht umgeleitete Modell-IDs.
#: (``gemini-3.7-flash`` leitet Google inzwischen auf ``gemini-3.8-flash`` um - als
#: Ausweichmodell wäre es wirkungslos.)
SUGGESTED_MODELS: dict[str, list[str]] = {
    "local": ["qwen2.5:14b-instruct", "qwen2.5:7b-instruct", "llama3.1:8b-instruct-q8_0"],
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"],
    "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-5-5"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
}

#: Vorschlag für das Ausweichmodell desselben Anbieters (leichter, seltener überlastet).
SUGGESTED_FALLBACK_MODELS: dict[str, str] = {
    "gemini": "gemini-3.5-flash-lite",
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
}

PROVIDER_LABELS: dict[str, str] = {
    "local": "Lokal (Ollama)",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
}

_BACKUP_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class SettingsError(ValueError):
    """Ungültige Einstellung (wird als HTTP 422 gemeldet)."""


def mask_secret(value: str | None) -> str | None:
    """``sk-abcdef...wxyz`` -> ``sk-...wxyz`` (nie mehr als 4 Klartextzeichen am Ende)."""
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    prefix = value[:3] if value[:3] in {"sk-", "AIz"} else ""
    return f"{prefix}...{value[-4:]}"


@dataclass(frozen=True, slots=True)
class BackupKey:
    """Ein Ausweich-Schlüssel (Stufe 3 der Kaskade)."""

    id: str
    provider: InferenceMode
    model: str
    api_key: str = field(repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider.value,
            "model": self.model,
            "has_key": bool(self.api_key),
            "key_hint": mask_secret(self.api_key),
        }


@dataclass(frozen=True, slots=True)
class ChainStage:
    """Eine Stufe der effektiven Kaskade - ohne Schlüssel, für Ledger und Oberfläche."""

    stage: str  # primary | ausweichmodell | ausweich_schluessel | fallback
    provider: InferenceMode
    model: str
    backup_id: str | None = None

    def public(self) -> dict[str, Any]:
        return {"stage": self.stage, "provider": self.provider.value, "model": self.model,
                **({"backup_id": self.backup_id} if self.backup_id else {})}


@dataclass(slots=True)
class RuntimeSnapshot:
    """Unveränderlicher Blick auf die aktuelle Konfiguration."""

    inference_mode: InferenceMode
    models: dict[str, str]
    pii_strictness: PIIStrictness
    enforce_ustg_check: bool
    ai_act_escalation: bool
    keys: dict[str, str | None] = field(repr=False)
    #: Anbieter-Fallbacks in Reihenfolge (ohne den primären), z. B. ``[anthropic, local]``.
    fallbacks: tuple[InferenceMode, ...] = ()
    #: Ausweichmodell desselben Anbieters je Cloud-Provider ("" = aus).
    ausweich_modelle: dict[str, str] = field(default_factory=dict)
    #: Ausweich-Schlüssel in Reihenfolge.
    ausweich_schluessel: tuple[BackupKey, ...] = field(default=(), repr=False)

    @property
    def active_model(self) -> str:
        return self.models[self.inference_mode.value]

    @property
    def is_cloud(self) -> bool:
        return self.inference_mode in CLOUD_PROVIDERS

    @property
    def ausweich_modell(self) -> str:
        """Ausweichmodell des aktiven Anbieters (leer, wenn aus oder gleich dem Hauptmodell)."""
        if not self.is_cloud:
            return ""
        value = self.ausweich_modelle.get(self.inference_mode.value, "")
        return "" if value == self.active_model else value

    @property
    def chain(self) -> tuple[InferenceMode, ...]:
        """Primärer Provider plus Anbieter-Fallbacks, ohne Dubletten."""
        return (self.inference_mode, *(mode for mode in self.fallbacks if mode is not self.inference_mode))

    def effective_chain(self) -> list[ChainStage]:
        """Alle KI-Stufen in der Reihenfolge, in der die Kaskade sie probiert."""
        stages = [ChainStage("primary", self.inference_mode, self.active_model)]
        if self.is_cloud:
            if self.ausweich_modell:
                stages.append(ChainStage("ausweichmodell", self.inference_mode, self.ausweich_modell))
            stages.extend(
                ChainStage("ausweich_schluessel", key.provider, key.model, key.id) for key in self.ausweich_schluessel
            )
        stages.extend(ChainStage("fallback", mode, self.models[mode.value]) for mode in self.chain[1:])
        return stages

    def fingerprint(self) -> dict[str, Any]:
        """Was eine Bewertung beeinflusst: Provider-Kette und Modell je Stufe (für das Ledger)."""
        stages = self.effective_chain()
        return {
            "inference_mode": self.inference_mode.value,
            "model": self.active_model,
            "fallbacks": [{"provider": stage.provider.value, "model": stage.model, "stage": stage.stage}
                          for stage in stages[1:]],
        }

    def key_for(self, provider: str) -> str | None:
        return self.keys.get(provider)


_STAGE_LABELS = {"ausweichmodell": "Ausweichmodell", "ausweich_schluessel": "Ausweich-Schlüssel", "fallback": "Anbieter-Fallback"}


def describe_model_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Lesbare Kurzfassung eines ``model_change``: was sich an Hauptmodell oder Kaskade geändert hat."""
    primary_before = f"{before['inference_mode']}/{before['model']}"
    primary_after = f"{after['inference_mode']}/{after['model']}"
    if primary_before != primary_after:
        return f"Modellwechsel {primary_before} → {primary_after}"

    def stages(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
        return [(_STAGE_LABELS.get(s["stage"], s["stage"]), f"{s['provider']}/{s['model']}")
                for s in snapshot.get("fallbacks", [])]

    old, new = stages(before), stages(after)
    removed = [stage for stage in old if stage not in new]
    added = [stage for stage in new if stage not in old]
    if len(removed) == 1 and len(added) == 1 and removed[0][0] == added[0][0]:
        return f"Ausweich-Kaskade geändert: {added[0][0]} {removed[0][1]} → {added[0][1]}"
    parts = [f"+ {label} {model}" for label, model in added] + [f"− {label} {model}" for label, model in removed]
    return "Ausweich-Kaskade geändert: " + ", ".join(parts) if parts else "Ausweich-Kaskade neu geordnet"


def _load_fernet(settings: Settings) -> Fernet:
    if settings.settings_encryption_key:
        return Fernet(settings.settings_encryption_key.encode())
    key_file: Path = settings.data_dir / ".settings.key"
    if key_file.exists():
        return Fernet(key_file.read_bytes().strip())
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:  # pragma: no cover - z. B. Windows ohne POSIX-Rechte
        pass
    logger.info("Neuer Settings-Schlüssel erzeugt (%s).", key_file.name)
    return Fernet(key)


class RuntimeSettingsStore:
    """Threadsicherer Speicher für Laufzeit-Einstellungen."""

    _SECRET_KEYS = {f"{provider.value}_api_key" for provider in CLOUD_PROVIDERS}

    def __init__(self, settings: Settings, engine: Engine) -> None:
        self._engine = engine
        self._fernet = _load_fernet(settings)
        self._lock = threading.Lock()
        # Ein Tageslimit aus der Serverkonfiguration ist die Obergrenze für den Wert aus der Oberfläche.
        self._server_token_limit = settings.cloud_daily_token_limit
        self._state: dict[str, Any] = {
            "inference_mode": self._coerce_mode(settings.inference_mode),
            "models": {
                "local": settings.ollama_model,
                "gemini": settings.gemini_model,
                "anthropic": settings.anthropic_model,
                "openai": settings.openai_model,
            },
            "pii_strictness": self._coerce_strictness(settings.pii_strictness),
            "enforce_ustg_check": True,
            "ai_act_escalation": True,
            "fallbacks": (),
            "ausweich_modelle": {provider.value: "" for provider in CLOUD_PROVIDERS},
            "ausweich_schluessel": (),
            # Voreinstellung aus CLOUD_DAILY_TOKEN_LIMIT; in den Einstellungen änderbar (-1 = ohne Limit).
            "cloud_daily_token_limit": settings.cloud_daily_token_limit,
            "keys": {
                "gemini": settings.gemini_api_key,
                "anthropic": settings.anthropic_api_key,
                "openai": settings.openai_api_key,
            },
        }
        self._load_persisted()

    # --- Persistenz ---------------------------------------------------------
    def _load_persisted(self) -> None:
        with self._engine.connect() as connection:
            rows = connection.execute(sa.select(app_settings_table)).fetchall()
        for key, value, _updated in rows:
            try:
                if key in self._SECRET_KEYS:
                    provider = key.removesuffix("_api_key")
                    self._state["keys"][provider] = (
                        self._fernet.decrypt(value.encode()).decode() if value else None
                    )
                elif key == "models":
                    loaded_models = json.loads(value)
                    if loaded_models.get("gemini") == "gemini-2.5-pro":
                        loaded_models["gemini"] = "gemini-3.8-flash"
                    self._state["models"].update(loaded_models)
                elif key in {"enforce_ustg_check", "ai_act_escalation"}:
                    self._state[key] = json.loads(value)
                elif key == "cloud_daily_token_limit":
                    self._state[key] = self._cap_token_limit(int(json.loads(value)))
                elif key == "inference_mode":
                    self._state[key] = self._coerce_mode(value)
                elif key == "pii_strictness":
                    self._state[key] = self._coerce_strictness(value)
                elif key == "fallbacks":
                    self._state[key] = self._coerce_fallbacks(json.loads(value))
                elif key == "ausweich_modelle":
                    loaded = json.loads(value)
                    for provider in self._state["ausweich_modelle"]:
                        model = str(loaded.get(provider) or "")
                        if provider == "gemini" and model == "gemini-3.7-flash":
                            model = "gemini-3.5-flash-lite"
                        self._state["ausweich_modelle"][provider] = model
                elif key == "ausweich_schluessel":
                    raw = json.loads(self._fernet.decrypt(value.encode()).decode()) if value else []
                    self._state[key] = tuple(
                        BackupKey(str(item["id"]), InferenceMode(item["provider"]), str(item["model"]),
                                  str(item["api_key"]))
                        for item in raw[:MAX_BACKUP_KEYS]
                    )
            except (InvalidToken, ValueError, TypeError, KeyError):
                logger.warning("Gespeicherte Einstellung '%s' nicht lesbar - Startwert bleibt.", key)

    def _persist(self, values: dict[str, str | None]) -> None:
        now = utcnow()
        with self._engine.begin() as connection:
            for key, value in values.items():
                connection.execute(sa.delete(app_settings_table).where(app_settings_table.c.key == key))
                connection.execute(
                    sa.insert(app_settings_table).values(key=key, value=value, updated_at=now)
                )

    # --- Lesen/Schreiben ----------------------------------------------------
    @staticmethod
    def _coerce_mode(value: str) -> InferenceMode:
        try:
            return InferenceMode(value)
        except ValueError:
            return InferenceMode.LOCAL

    @staticmethod
    def _coerce_fallbacks(values: list[str]) -> tuple[InferenceMode, ...]:
        """Je Provider höchstens einmal; Unbekanntes wird verworfen."""
        seen: list[InferenceMode] = []
        for value in values:
            try:
                mode = InferenceMode(value)
            except ValueError:
                continue
            if mode not in seen:
                seen.append(mode)
        return tuple(seen)

    @staticmethod
    def _coerce_strictness(value: str) -> PIIStrictness:
        try:
            return PIIStrictness(value)
        except ValueError:
            return PIIStrictness.STANDARD

    def _cap_token_limit(self, value: int) -> int:
        """Gespeicherter Wert, höchstens die Server-Vorgabe (``-1`` = ohne Limit)."""
        ceiling = self._server_token_limit
        if ceiling >= 0 and (value < 0 or value > ceiling):
            return ceiling
        return max(-1, value)

    @property
    def cloud_daily_token_limit(self) -> int:
        """Tageslimit für Cloud-Tokens (-1 = ohne Limit)."""
        with self._lock:
            return int(self._state["cloud_daily_token_limit"])

    @property
    def cloud_daily_token_limit_max(self) -> int | None:
        """Obergrenze aus der Serverkonfiguration; ``None`` = frei wählbar."""
        return self._server_token_limit if self._server_token_limit >= 0 else None

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                inference_mode=self._state["inference_mode"],
                models=dict(self._state["models"]),
                pii_strictness=self._state["pii_strictness"],
                enforce_ustg_check=self._state["enforce_ustg_check"],
                ai_act_escalation=self._state["ai_act_escalation"],
                keys=dict(self._state["keys"]),
                fallbacks=self._state["fallbacks"],
                ausweich_modelle=dict(self._state["ausweich_modelle"]),
                ausweich_schluessel=self._state["ausweich_schluessel"],
            )

    def _merge_backup_keys(self, entries: list[dict[str, Any]]) -> tuple[BackupKey, ...]:
        """Ganze Liste übernehmen; Einträge ohne ``api_key`` behalten den Schlüssel gleicher ID."""
        if len(entries) > MAX_BACKUP_KEYS:
            raise SettingsError(f"Höchstens {MAX_BACKUP_KEYS} Ausweich-Schlüssel.")
        known = {key.id: key for key in self._state["ausweich_schluessel"]}
        merged: list[BackupKey] = []
        for entry in entries:
            backup_id = str(entry.get("id") or "").strip()
            if not _BACKUP_ID.fullmatch(backup_id) or any(item.id == backup_id for item in merged):
                raise SettingsError("Ausweich-Schlüssel braucht eine eindeutige ID (Buchstaben, Ziffern, - und _).")
            try:
                provider = InferenceMode(entry.get("provider"))
            except ValueError as exc:
                raise SettingsError("Unbekannter Anbieter für einen Ausweich-Schlüssel.") from exc
            if provider not in CLOUD_PROVIDERS:
                raise SettingsError("Ausweich-Schlüssel gibt es nur für Cloud-Anbieter (Gemini, Claude, OpenAI).")
            secret = (entry.get("api_key") or "").strip()
            previous = known.get(backup_id)
            if not secret and previous is not None and previous.provider is provider:
                secret = previous.api_key
            if not secret:
                raise SettingsError(f"Ausweich-Schlüssel '{backup_id}' ohne API-Key.")
            model = (entry.get("model") or "").strip() or self._state["models"][provider.value]
            merged.append(BackupKey(backup_id, provider, model[:120], secret))
        return tuple(merged)

    def _update(self, changes: dict[str, Any]) -> RuntimeSnapshot:
        # Erst prüfen, dann ändern: Eine abgelehnte Eingabe lässt den Stand unverändert.
        ceiling = self._server_token_limit
        wanted = changes.get("cloud_daily_token_limit")
        if wanted is not None and ceiling >= 0 and (int(wanted) < 0 or int(wanted) > ceiling):
            raise SettingsError(
                f"Das Tageslimit darf höchstens {ceiling:,} Tokens betragen (Vorgabe des Servers).".replace(",", ".")
            )
        persisted: dict[str, str | None] = {}
        with self._lock:
            if changes.get("inference_mode") is not None:
                self._state["inference_mode"] = InferenceMode(changes["inference_mode"])
                persisted["inference_mode"] = self._state["inference_mode"].value
            if changes.get("pii_strictness") is not None:
                self._state["pii_strictness"] = PIIStrictness(changes["pii_strictness"])
                persisted["pii_strictness"] = self._state["pii_strictness"].value
            if changes.get("fallbacks") is not None:
                self._state["fallbacks"] = self._coerce_fallbacks(changes["fallbacks"])
                persisted["fallbacks"] = json.dumps([mode.value for mode in self._state["fallbacks"]])
            if changes.get("cloud_daily_token_limit") is not None:
                self._state["cloud_daily_token_limit"] = max(-1, int(changes["cloud_daily_token_limit"]))
                persisted["cloud_daily_token_limit"] = json.dumps(self._state["cloud_daily_token_limit"])
            for flag in ("enforce_ustg_check", "ai_act_escalation"):
                if changes.get(flag) is not None:
                    self._state[flag] = bool(changes[flag])
                    persisted[flag] = json.dumps(self._state[flag])
            models = changes.get("models") or {}
            for provider, model in models.items():
                if provider in self._state["models"] and model and model.strip():
                    self._state["models"][provider] = model.strip()
            if models:
                persisted["models"] = json.dumps(self._state["models"])
            ausweich = changes.get("ausweich_modelle") or {}
            for provider, model in ausweich.items():
                if provider in self._state["ausweich_modelle"] and model is not None:
                    self._state["ausweich_modelle"][provider] = model.strip()[:120]
            if ausweich:
                persisted["ausweich_modelle"] = json.dumps(self._state["ausweich_modelle"])
            if changes.get("ausweich_schluessel") is not None:
                self._state["ausweich_schluessel"] = self._merge_backup_keys(list(changes["ausweich_schluessel"]))
                payload = json.dumps([
                    {"id": key.id, "provider": key.provider.value, "model": key.model, "api_key": key.api_key}
                    for key in self._state["ausweich_schluessel"]
                ])
                persisted["ausweich_schluessel"] = self._fernet.encrypt(payload.encode()).decode()
            keys = changes.get("api_keys") or {}
            for provider, secret in keys.items():
                if provider not in self._state["keys"] or secret is None:
                    continue
                cleaned = secret.strip()
                # Leerer String = Schlüssel löschen.
                self._state["keys"][provider] = cleaned or None
                persisted[f"{provider}_api_key"] = (
                    self._fernet.encrypt(cleaned.encode()).decode() if cleaned else None
                )
        if persisted:
            self._persist(persisted)
        return self.snapshot()

    async def update(self, changes: dict[str, Any]) -> RuntimeSnapshot:
        return await anyio.to_thread.run_sync(partial(self._update, changes))

    def public_view(self) -> dict[str, Any]:
        """Konfiguration für die API - Keys ausschließlich maskiert."""
        snap = self.snapshot()
        return {
            "inference_mode": snap.inference_mode.value,
            "active_provider_label": PROVIDER_LABELS[snap.inference_mode.value],
            "active_model": snap.active_model,
            "is_cloud": snap.is_cloud,
            "privacy_gateway_active": snap.is_cloud,
            "models": snap.models,
            "suggested_models": SUGGESTED_MODELS,
            "suggested_fallback_models": SUGGESTED_FALLBACK_MODELS,
            "pii_strictness": snap.pii_strictness.value,
            "enforce_ustg_check": snap.enforce_ustg_check,
            "ai_act_escalation": snap.ai_act_escalation,
            "fallbacks": [mode.value for mode in snap.chain[1:]],
            "ausweich_modell": snap.ausweich_modell,
            "ausweich_modelle": snap.ausweich_modelle,
            "ausweich_schluessel": [key.public() for key in snap.ausweich_schluessel],
            "max_ausweich_schluessel": MAX_BACKUP_KEYS,
            "chain": [stage.public() for stage in snap.effective_chain()],
            "has_gemini_key": bool(snap.keys.get("gemini")),
            "has_anthropic_key": bool(snap.keys.get("anthropic")),
            "has_openai_key": bool(snap.keys.get("openai")),
            "masked_keys": {provider: mask_secret(value) for provider, value in snap.keys.items()},
        }
