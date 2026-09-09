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

APP_VERSION = "1.0.0"
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
