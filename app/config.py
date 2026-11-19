"""Zentrale Anwendungskonfiguration.

Sämtliche Einstellungen werden über Umgebungsvariablen bzw. eine ``.env``
Datei gesteuert (siehe ``.env.example``).  Die Anwendung ist bewusst so
gebaut, dass sie ohne jede Konfiguration lauffähig ist: alle Werte besitzen
produktionstaugliche Defaults.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Projektwurzel (…/enterprise-compliance-agent), unabhängig vom CWD.
BASE_DIR = Path(__file__).resolve().parent.parent

APP_VERSION = "2.8.2"
APP_TITLE = "Enterprise Compliance Agent"

_LOOPBACK_HOST = re.compile(r"^(https?://)localhost(?=[:/]|$)", re.IGNORECASE)


def normalize_loopback(url: str) -> str:
    """``http://localhost:11434`` -> ``http://127.0.0.1:11434``.

    Windows löst ``localhost`` bevorzugt nach ``::1`` (IPv6) auf; Ollama lauscht
    auf IPv4.  Der Umweg kostet rund 2 s je Anfrage und reißt damit das
    Health-Timeout von 1,5 s - der Dienst wirkt offline, obwohl er läuft.
    """
    return _LOOPBACK_HOST.sub(r"\g<1>127.0.0.1", url.strip())


class Settings(BaseSettings):
    """Typsichere, validierte Laufzeitkonfiguration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Anwendung ---------------------------------------------------------
    app_env: str = Field(default="development", description="development | staging | production")
    log_level: str = Field(default="INFO")

    #: Wenn leer, ist die API-Key-Prüfung deaktiviert (lokaler Betrieb).
    api_key: str | None = Field(default=None)

    #: Kommagetrennte Liste erlaubter Origins ("*" erlaubt alle - lokal auf Frontend begrenzt).
    cors_origins: str = Field(default="http://127.0.0.1:3001,http://localhost:3001")

    # --- Persistenz --------------------------------------------------------
    database_url: str = Field(default="sqlite:///data/agent.db")
    upload_dir: Path = Field(default=Path("data/uploads"))
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)

    # --- KI-Inferenz -------------------------------------------------------
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen2.5:14b-instruct")
    ollama_timeout_seconds: float = Field(default=300.0, gt=0)
    #: 32k Token: lange Verträge passen samt Prompt in den Kontext (Ollama nimmt sonst 2-4k
    #: und schneidet vorne ab - samt Anweisungen).  Mit OLLAMA_FLASH_ATTENTION=1 und
    #: OLLAMA_KV_CACHE_TYPE=q8_0 passt ein 14B-Modell damit in 16 GB Grafikspeicher.
    ollama_num_ctx: int = Field(default=32_768, ge=512)
    ollama_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # --- Ausfallsicherheit der KI-Kaskade -------------------------------------
    #: Wartezeiten (s) für Wiederholungen derselben Stufe bei 408/429/5xx, Verbindungsfehler
    #: oder Zeitüberschreitung, bevor die nächste Stufe übernimmt ("2,5" = 2 s, dann 5 s).
    llm_retry_delays: str = Field(default="2,5")
    #: Scheitern alle KI-Stufen an Überlast oder Ausfall, schließt das deterministische
    #: Regelwerk die Prüfung ab (markiert in UI und Ledger).  false = Fehler sichtbar lassen.
    heuristic_fallback: bool = Field(default=True)
    #: Optionales Tagesbudget für Cloud-Tokens (eigener Schlüssel); -1 = ohne Limit.
    cloud_daily_token_limit: int = Field(default=-1, ge=-1)

    # --- Hintergrund-Jobs ------------------------------------------------------
    #: Gleichzeitige Analysen (lokales Modell: 1; reine Cloud-Kaskade verträgt mehr).
    analysis_workers: int = Field(default=1, ge=1, le=8)
    #: Beendete Jobs bleiben so lange abrufbar (Sekunden).
    job_retention_seconds: int = Field(default=3600, ge=60)

    # --- Lokale KI aus der Oberfläche steuern -------------------------------------
    #: Start/Stopp von Ollama nur für Anfragen direkt am Server (localhost).
    local_ai_control_local_only: bool = Field(default=True)

    #: Zeichenlimit für den an das LLM übergebenen Dokumenttext.
    max_prompt_chars: int = Field(default=24_000, ge=1000)

    # --- Datenschutz -------------------------------------------------------
    mask_pii_in_storage: bool = Field(default=True)
    #: strict | standard | audit_only (Laufzeitwert über /api/settings änderbar).
    pii_strictness: str = Field(default="standard")

    # --- Logging & Betrieb -------------------------------------------------
    #: JSON-Logs (Produktion) oder lesbare Textzeilen (lokale Entwicklung).
    log_json: bool = Field(default=True)

    # --- Rate-Limiting (Token-Bucket je Client-IP) --------------------------
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_upload_per_minute: int = Field(default=30, ge=0)
    rate_limit_extract_per_minute: int = Field(default=10, ge=0)
    rate_limit_copilot_per_minute: int = Field(default=20, ge=0)
    rate_limit_settings_per_minute: int = Field(default=30, ge=0)
    rate_limit_vies_per_minute: int = Field(default=30, ge=0)
    rate_limit_redact_per_minute: int = Field(default=120, ge=0)
    # DLP-Gateway: zusätzliche Sperrbegriffe (kommagetrennt), auch aus der .env.
    dlp_terms: str = Field(default="")
    # Release-Assistent: Git-Arbeitskopie (leer = Projektwurzel); Update nur von localhost.
    release_repo_dir: str = Field(default="")
    release_update_local_only: bool = Field(default=True)

    # --- USt-IdNr.-Prüfung (VIES, Europäische Kommission) ----------------
    vies_url: str = Field(
        default="https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
    )
    vies_timeout_seconds: float = Field(default=3.0, gt=0)

    # --- Multi-Provider-Inferenz -------------------------------------------
    #: local | gemini | anthropic | openai (Startwert; zur Laufzeit änderbar).
    inference_mode: str = Field(default="local")
    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-3.8-flash")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta")
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-sonnet-5")
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    cloud_timeout_seconds: float = Field(default=45.0, ge=5.0, le=600.0)

    #: Fernet-Schlüssel für die Ablage von Provider-Keys in der Datenbank.
    #: Leer -> wird beim ersten Start unter data/.settings.key erzeugt.
    settings_encryption_key: str | None = Field(default=None)

    # --- Batch-Upload ------------------------------------------------------
    max_batch_files: int = Field(default=20, ge=1, le=100)

    @field_validator(
        "gemini_api_key", "anthropic_api_key", "openai_api_key", "settings_encryption_key",
        mode="before",
    )
    @classmethod
    def _empty_secret_means_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_api_key_means_disabled(cls, value: object) -> object:
        """Ein leerer String in der .env bedeutet ausdrücklich "keine Auth"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _normalize_ollama_url(cls, value: str) -> str:
        return normalize_loopback(value).rstrip("/")

    # --- Abgeleitete Werte -------------------------------------------------
    @property
    def auth_enabled(self) -> bool:
        return self.api_key is not None

    @property
    def retry_delays(self) -> tuple[float, ...]:
        """``"2,5"`` -> ``(2.0, 5.0)``; ungültige Teile werden ignoriert, höchstens fünf."""
        delays: list[float] = []
        for part in self.llm_retry_delays.replace(";", ",").split(","):
            try:
                value = float(part.strip())
            except ValueError:
                continue
            if value >= 0:
                delays.append(min(value, 60.0))
        return tuple(delays[:5])

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def upload_path(self) -> Path:
        """Absoluter Upload-Pfad (relative Angaben gelten ab Projektwurzel)."""
        path = self.upload_dir
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def resolved_database_url(self) -> str:
        """SQLite-Pfade werden gegen die Projektwurzel absolut gemacht.

        Damit ist der Serverstart unabhängig vom Arbeitsverzeichnis.  Für
        PostgreSQL/Supabase wird die URL unverändert durchgereicht.
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url

        raw_path = self.database_url[len(prefix) :]
        if not raw_path or raw_path == ":memory:":
            return self.database_url

        path = Path(raw_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return f"{prefix}{path.as_posix()}"

    @property
    def data_dir(self) -> Path:
        """Verzeichnis für Laufzeitdateien (Settings-Schlüssel)."""
        return self.upload_path.parent

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def ollama_chat_url(self) -> str:
        return f"{self.ollama_base_url}/api/chat"

    @property
    def ollama_tags_url(self) -> str:
        return f"{self.ollama_base_url}/api/tags"

    def ensure_directories(self) -> None:
        """Legt Upload- und Datenbankverzeichnis an (idempotent)."""
        self.upload_path.mkdir(parents=True, exist_ok=True)
        if self.is_sqlite:
            db_file = self.resolved_database_url[len("sqlite:///") :]
            if db_file and db_file != ":memory:":
                Path(db_file).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Prozessweiter Settings-Singleton (per FastAPI-Dependency injizierbar)."""
    return Settings()
