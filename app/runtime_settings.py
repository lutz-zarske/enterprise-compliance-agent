"""Laufzeit-Einstellungen: Inferenz-Modus, Modelle, PII-Strenge, Provider-Keys.

Startwerte kommen aus der Umgebung (``Settings``); Aenderungen ueber
``POST /api/settings`` werden in der Tabelle ``app_settings`` gespeichert und
ueberleben einen Neustart.

Schluesselverwaltung
--------------------
Provider-API-Keys werden mit **Fernet** (AES-128-CBC + HMAC-SHA256,
``cryptography``) verschluesselt abgelegt.  Der Fernet-Schluessel stammt aus
``SETTINGS_ENCRYPTION_KEY``; fehlt er, wird einmalig ``data/.settings.key``
(Dateirechte 0600) erzeugt.  Ehrliche Einordnung: Liegt der Schluessel neben
der Datenbank, schuetzt das vor dem versehentlichen Leak eines DB-Backups,
nicht vor einem Angreifer mit Vollzugriff auf den Server.  Produktiv gehoert
der Schluessel in einen Secret-Store (Vault, Azure Key Vault, AWS KMS).

Nach aussen verlassen Keys diese Klasse nur maskiert (``sk-...a1b2``).
"""

from __future__ import annotations

import json
import logging
import os
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

#: Auswahl im Einstellungsdialog (freie Eingabe bleibt moeglich).
SUGGESTED_MODELS: dict[str, list[str]] = {
    "local": ["qwen2.5:14b-instruct", "qwen2.5:7b-instruct", "llama3.1:8b-instruct-q8_0"],
    "gemini": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"],
    "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
}

PROVIDER_LABELS: dict[str, str] = {
    "local": "Lokal (Ollama)",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
}


def mask_secret(value: str | None) -> str | None:
    """``sk-abcdef...wxyz`` -> ``sk-...wxyz`` (nie mehr als 4 Klartextzeichen am Ende)."""
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    prefix = value[:3] if value[:3] in {"sk-", "AIz"} else ""
    return f"{prefix}...{value[-4:]}"


@dataclass(slots=True)
class RuntimeSnapshot:
    """Unveraenderlicher Blick auf die aktuelle Konfiguration."""

    inference_mode: InferenceMode
    models: dict[str, str]
    pii_strictness: PIIStrictness
    enforce_ustg_check: bool
    ai_act_escalation: bool
    keys: dict[str, str | None] = field(repr=False)
    #: Ausweich-Provider in Reihenfolge (ohne den primaeren), z. B. ``[anthropic, local]``.
    fallbacks: tuple[InferenceMode, ...] = ()

    @property
    def active_model(self) -> str:
        return self.models[self.inference_mode.value]

    @property
    def chain(self) -> tuple[InferenceMode, ...]:
        """Primaerer Provider plus Ausweich-Provider, ohne Dubletten."""
        return (self.inference_mode, *(mode for mode in self.fallbacks if mode is not self.inference_mode))

    def fingerprint(self) -> dict[str, Any]:
        """Was eine Bewertung beeinflusst: Provider-Kette und Modell je Stufe (fuer das Ledger)."""
        return {
            "inference_mode": self.inference_mode.value,
            "model": self.active_model,
            "fallbacks": [{"provider": mode.value, "model": self.models[mode.value]} for mode in self.chain[1:]],
        }

    def key_for(self, provider: str) -> str | None:
        return self.keys.get(provider)


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
    logger.info("Neuer Settings-Schluessel erzeugt (%s).", key_file.name)
    return Fernet(key)


class RuntimeSettingsStore:
    """Threadsicherer Speicher fuer Laufzeit-Einstellungen."""

    _SECRET_KEYS = {f"{provider.value}_api_key" for provider in CLOUD_PROVIDERS}

    def __init__(self, settings: Settings, engine: Engine) -> None:
        self._engine = engine
        self._fernet = _load_fernet(settings)
        self._lock = threading.Lock()
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
                elif key == "inference_mode":
                    self._state[key] = self._coerce_mode(value)
                elif key == "pii_strictness":
                    self._state[key] = self._coerce_strictness(value)
                elif key == "fallbacks":
                    self._state[key] = self._coerce_fallbacks(json.loads(value))
            except (InvalidToken, ValueError, TypeError):
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
        """Je Provider hoechstens einmal; Unbekanntes wird verworfen."""
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
            )

    def _update(self, changes: dict[str, Any]) -> RuntimeSnapshot:
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
            keys = changes.get("api_keys") or {}
            for provider, secret in keys.items():
                if provider not in self._state["keys"] or secret is None:
                    continue
                cleaned = secret.strip()
                # Leerer String = Schluessel loeschen.
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
        """Konfiguration fuer die API - Keys ausschliesslich maskiert."""
        snap = self.snapshot()
        return {
            "inference_mode": snap.inference_mode.value,
            "active_provider_label": PROVIDER_LABELS[snap.inference_mode.value],
            "active_model": snap.active_model,
            "is_cloud": snap.inference_mode in CLOUD_PROVIDERS,
            "privacy_gateway_active": snap.inference_mode in CLOUD_PROVIDERS,
            "models": snap.models,
            "suggested_models": SUGGESTED_MODELS,
            "pii_strictness": snap.pii_strictness.value,
            "enforce_ustg_check": snap.enforce_ustg_check,
            "ai_act_escalation": snap.ai_act_escalation,
            "fallbacks": [mode.value for mode in snap.chain[1:]],
            "has_gemini_key": bool(snap.keys.get("gemini")),
            "has_anthropic_key": bool(snap.keys.get("anthropic")),
            "has_openai_key": bool(snap.keys.get("openai")),
            "masked_keys": {provider: mask_secret(value) for provider, value in snap.keys.items()},
        }
