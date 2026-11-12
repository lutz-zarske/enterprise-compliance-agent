"""Zentrale Anwendungskonfiguration.

Saemtliche Einstellungen werden ueber Umgebungsvariablen bzw. eine ``.env``
Datei gesteuert (siehe ``.env.example``).  Die Anwendung ist bewusst so
gebaut, dass sie ohne jede Konfiguration lauffaehig ist: alle Werte besitzen
produktionstaugliche Defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Projektwurzel (…/enterprise-compliance-agent), unabhaengig vom CWD.
BASE_DIR = Path(__file__).resolve().parent.parent

APP_VERSION = "2.4.1"
APP_TITLE = "Enterprise KI-Compliance- & Dokumenten-Agent"


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

    #: Wenn leer, ist die API-Key-Pruefung deaktiviert (lokaler Betrieb).
    api_key: str | None = Field(default=None)

    #: Kommagetrennte Liste erlaubter Origins ("*" erlaubt alle).
    cors_origins: str = Field(default="*")

    # --- Persistenz --------------------------------------------------------
    database_url: str = Field(default="sqlite:///data/agent.db")
    upload_dir: Path = Field(default=Path("data/uploads"))
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)

    # --- KI-Inferenz -------------------------------------------------------
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen2.5:14b-instruct")
    ollama_timeout_seconds: float = Field(default=300.0, gt=0)
    ollama_num_ctx: int = Field(default=16384, ge=512)
    ollama_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    #: Zeichenlimit fuer den an das LLM uebergebenen Dokumenttext.
    max_prompt_chars: int = Field(default=24_000, ge=1000)

    # --- Datenschutz -------------------------------------------------------
    mask_pii_in_storage: bool = Field(default=True)
    #: strict | standard | audit_only (Laufzeitwert ueber /api/settings aenderbar).
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
    # DLP-Gateway: zusaetzliche Sperrbegriffe (kommagetrennt), auch aus der .env.
    dlp_terms: str = Field(default="")
    # Release-Assistent: Git-Arbeitskopie (leer = Projektwurzel); Update nur von localhost.
    release_repo_dir: str = Field(default="")
    release_update_local_only: bool = Field(default=True)

    # --- USt-IdNr.-Pruefung (VIES, Europaeische Kommission) ----------------
    vies_url: str = Field(
        default="https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
    )
    vies_timeout_seconds: float = Field(default=3.0, gt=0)

    # --- Multi-Provider-Inferenz -------------------------------------------
    #: local | gemini | anthropic | openai (Startwert; zur Laufzeit aenderbar).
    inference_mode: str = Field(default="local")
    gemini_api_key: str | None = Field(default=None)
    gemini_model: str = Field(default="gemini-3.8-flash")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta")
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-sonnet-5-5")
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    cloud_timeout_seconds: float = Field(default=180.0, gt=0)

    #: Fernet-Schluessel fuer die Ablage von Provider-Keys in der Datenbank.
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
        """Ein leerer String in der .env bedeutet ausdruecklich "keine Auth"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    # --- Abgeleitete Werte -------------------------------------------------
    @property
    def auth_enabled(self) -> bool:
        return self.api_key is not None

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

        Damit ist der Serverstart unabhaengig vom Arbeitsverzeichnis.  Fuer
        PostgreSQL/Supabase wird die URL unveraendert durchgereicht.
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
        """Verzeichnis fuer Laufzeitdateien (Settings-Schluessel)."""
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
