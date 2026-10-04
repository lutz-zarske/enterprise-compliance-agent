"""Persistenzschicht - bewusst entkoppelt und austauschbar.

Die Anwendung spricht ausschliesslich ueber das ``DocumentRepository``-Protocol
mit der Datenbank.  Die mitgelieferte Implementierung nutzt SQLAlchemy Core
2.0; das Schema ist portabel definiert (keine SQLite-Spezialitaeten), sodass
der Wechsel auf PostgreSQL/Supabase allein ueber ``DATABASE_URL`` erfolgt:

    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/compliance

Fuer pgvector genuegt es spaeter, der Tabelle eine ``embedding``-Spalte
hinzuzufuegen - das bestehende Schema bleibt unveraendert.

SQLAlchemy Core ist synchron; alle Repository-Methoden sind dennoch ``async``
und lagern die Datenbankarbeit in einen Threadpool aus.  Damit bleibt der
Event-Loop frei und der spaetere Umstieg auf einen echten Async-Treiber
(``asyncpg``) ist ohne Aenderung an den Aufrufern moeglich.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol

import anyio.to_thread
import sqlalchemy as sa
from sqlalchemy import Engine, MetaData, Table
from sqlalchemy.engine import Row

from app.config import Settings

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

metadata = MetaData()

documents_table: Table = Table(
    "documents",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("original_filename", sa.String(500), nullable=False),
    sa.Column("stored_filename", sa.String(500), nullable=False),
    sa.Column("content_type", sa.String(120), nullable=False),
    sa.Column("size_bytes", sa.Integer, nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False, index=True),
    sa.Column("status", sa.String(32), nullable=False, index=True),
    sa.Column("page_count", sa.Integer, nullable=True),
    sa.Column("char_count", sa.Integer, nullable=True),
    # Volltext fuer erneute Extraktion ohne wiederholtes PDF-Parsing.
    sa.Column("raw_text", sa.Text, nullable=True),
    sa.Column("model", sa.String(120), nullable=True),
    # sa.JSON bildet auf SQLite TEXT und auf PostgreSQL JSONB-faehiges JSON ab.
    sa.Column("extraction", sa.JSON, nullable=True),
    sa.Column("compliance", sa.JSON, nullable=True),
    sa.Column("error", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
    # --- seit v2.0 (per _migrate_columns nachgeruestet) ---
    sa.Column("provider", sa.String(32), nullable=True),
    sa.Column("scorecard", sa.JSON, nullable=True),
    sa.Column("sign_off", sa.JSON, nullable=True),
    sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()),
)

#: Append-only-Pruefprotokoll (siehe app/audit_ledger.py).
audit_trails_table: Table = Table(
    "audit_trails",
    metadata,
    sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("entry_id", sa.String(36), nullable=False, unique=True),
    sa.Column("event_type", sa.String(32), nullable=False),
    sa.Column("document_id", sa.String(36), nullable=False, index=True),
    sa.Column("sha256_hash", sa.String(64), nullable=False),
    sa.Column("model_name", sa.String(120), nullable=False),
    sa.Column("prompt_hash", sa.String(64), nullable=False),
    # ISO-8601-String statt DateTime: der Hash muss bitgenau reproduzierbar sein.
    sa.Column("timestamp_utc", sa.String(40), nullable=False),
    sa.Column("result_summary", sa.Text, nullable=False),
    sa.Column("compliance_score", sa.Integer, nullable=True),
    sa.Column("risk_tier", sa.String(32), nullable=False),
    sa.Column("details", sa.JSON, nullable=True),
    sa.Column("previous_hash", sa.String(64), nullable=False),
    sa.Column("entry_hash", sa.String(64), nullable=False, unique=True),
    sqlite_autoincrement=True,
)

#: Laufzeit-Einstellungen (Inferenz-Modus, verschluesselte Provider-Schluessel).
app_settings_table: Table = Table(
    "app_settings",
    metadata,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.Text, nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

#: Spalten, die bestehenden Datenbanken beim Start ergaenzt werden.
_MIGRATED_COLUMNS: dict[str, str] = {
    "provider": "VARCHAR(32)",
    "scorecard": "JSON",
    "sign_off": "JSON",
    "pinned": "BOOLEAN NOT NULL DEFAULT FALSE",
}


def utcnow() -> datetime:
    """Zeitzonenbewusster UTC-Zeitstempel (einheitlich in der ganzen App)."""
    return datetime.now(UTC)


def _ensure_utc(value: datetime | None) -> datetime | None:
    """SQLite liefert naive Zeitstempel zurueck - hier wieder UTC anheften."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Datentransferobjekt
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DocumentRecord:
    """Ein Datenbankdatensatz, losgeloest von SQLAlchemy-Typen."""

    id: str
    original_filename: str
    stored_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    updated_at: datetime
    page_count: int | None = None
    char_count: int | None = None
    raw_text: str | None = None
    model: str | None = None
    extraction: dict[str, Any] | None = None
    compliance: dict[str, Any] | None = None
    error: str | None = None
    extracted_at: datetime | None = None
    provider: str | None = None
    scorecard: dict[str, Any] | None = None
    sign_off: dict[str, Any] | None = None
    pinned: bool = False

    @classmethod
    def from_row(cls, row: Row[Any]) -> DocumentRecord:
        mapping = row._mapping  # noqa: SLF001 - offizieller Zugriffspfad auf Row-Werte
        return cls(
            id=mapping["id"],
            original_filename=mapping["original_filename"],
            stored_filename=mapping["stored_filename"],
            content_type=mapping["content_type"],
            size_bytes=mapping["size_bytes"],
            sha256=mapping["sha256"],
            status=mapping["status"],
            page_count=mapping["page_count"],
            char_count=mapping["char_count"],
            raw_text=mapping["raw_text"],
            model=mapping["model"],
            extraction=mapping["extraction"],
            compliance=mapping["compliance"],
            error=mapping["error"],
            created_at=_ensure_utc(mapping["created_at"]),  # type: ignore[arg-type]
            updated_at=_ensure_utc(mapping["updated_at"]),  # type: ignore[arg-type]
            extracted_at=_ensure_utc(mapping["extracted_at"]),
            provider=mapping["provider"],
            scorecard=mapping["scorecard"],
            sign_off=mapping["sign_off"],
            pinned=bool(mapping["pinned"]),
        )


@dataclass(slots=True)
class NewDocument:
    """Eingabedaten fuer das Anlegen eines Dokuments."""

    original_filename: str
    stored_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int
    char_count: int
    raw_text: str | None
    status: str = "uploaded"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Repository-Vertrag
# ---------------------------------------------------------------------------


class DocumentRepository(Protocol):
    """Alles, was die Anwendung von der Datenbank erwartet.

    Eine PostgreSQL-, Supabase- oder In-Memory-Implementierung muss lediglich
    dieses Protocol erfuellen - ``main.py`` bleibt unveraendert.
    """

    async def create(self, document: NewDocument) -> DocumentRecord: ...

    async def get(self, document_id: str) -> DocumentRecord | None: ...

    async def get_by_sha256(self, sha256: str) -> DocumentRecord | None: ...

    async def list(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> tuple[list[DocumentRecord], int]: ...

    async def mark_processing(self, document_id: str) -> None: ...

    async def save_results(
        self,
        document_id: str,
        *,
        model: str,
        extraction: dict[str, Any],
        compliance: dict[str, Any],
        scorecard: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> DocumentRecord: ...

    async def save_sign_off(self, document_id: str, sign_off: dict[str, Any]) -> DocumentRecord: ...

    async def set_pinned(self, document_id: str, pinned: bool) -> DocumentRecord: ...

    async def list_all(self) -> list[DocumentRecord]: ...

    async def mark_failed(self, document_id: str, error: str) -> None: ...

    async def ping(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# SQLAlchemy-Core-Implementierung
# ---------------------------------------------------------------------------


class SqlDocumentRepository:
    """Repository auf Basis von SQLAlchemy Core (SQLite, PostgreSQL, ...)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # --- interne, synchrone Operationen ------------------------------------
    def _insert(self, document: NewDocument) -> DocumentRecord:
        now = utcnow()
        values: dict[str, Any] = {
            "id": document.id,
            "original_filename": document.original_filename,
            "stored_filename": document.stored_filename,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
            "sha256": document.sha256,
            "status": document.status,
            "page_count": document.page_count,
            "char_count": document.char_count,
            "raw_text": document.raw_text,
            "model": None,
            "extraction": None,
            "compliance": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "extracted_at": None,
            "provider": None,
            "scorecard": None,
            "sign_off": None,
            "pinned": False,
        }
        with self._engine.begin() as connection:
            connection.execute(sa.insert(documents_table).values(**values))
        return self._select_one(document.id)  # type: ignore[return-value]

    def _select_one(self, document_id: str) -> DocumentRecord | None:
        statement = sa.select(documents_table).where(documents_table.c.id == document_id)
        with self._engine.connect() as connection:
            row = connection.execute(statement).first()
        return DocumentRecord.from_row(row) if row is not None else None

    def _select_by_sha256(self, sha256: str) -> DocumentRecord | None:
        statement = (
            sa.select(documents_table)
            .where(documents_table.c.sha256 == sha256)
            .order_by(documents_table.c.created_at.asc())
            .limit(1)
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).first()
        return DocumentRecord.from_row(row) if row is not None else None

    def _select_many(
        self, limit: int, offset: int, status: str | None
    ) -> tuple[list[DocumentRecord], int]:
        statement = sa.select(documents_table)
        count_statement = sa.select(sa.func.count()).select_from(documents_table)
        if status is not None:
            statement = statement.where(documents_table.c.status == status)
            count_statement = count_statement.where(documents_table.c.status == status)

        statement = (
            statement.order_by(documents_table.c.pinned.desc(), documents_table.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).fetchall()
            total = connection.execute(count_statement).scalar_one()
        return [DocumentRecord.from_row(row) for row in rows], int(total)

    def _update(self, document_id: str, values: dict[str, Any]) -> None:
        values = {**values, "updated_at": utcnow()}
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(documents_table)
                .where(documents_table.c.id == document_id)
                .values(**values)
            )

    def _ping(self) -> dict[str, Any]:
        with self._engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
            count = connection.execute(
                sa.select(sa.func.count()).select_from(documents_table)
            ).scalar_one()
        return {"dialect": self._engine.dialect.name, "documents": int(count)}

    # --- oeffentliche, asynchrone API --------------------------------------
    async def create(self, document: NewDocument) -> DocumentRecord:
        return await anyio.to_thread.run_sync(partial(self._insert, document))

    async def get(self, document_id: str) -> DocumentRecord | None:
        return await anyio.to_thread.run_sync(partial(self._select_one, document_id))

    async def get_by_sha256(self, sha256: str) -> DocumentRecord | None:
        return await anyio.to_thread.run_sync(partial(self._select_by_sha256, sha256))

    async def list(
        self, *, limit: int, offset: int, status: str | None = None
    ) -> tuple[list[DocumentRecord], int]:
        return await anyio.to_thread.run_sync(
            partial(self._select_many, limit, offset, status)
        )

    async def mark_processing(self, document_id: str) -> None:
        await anyio.to_thread.run_sync(
            partial(self._update, document_id, {"status": "processing", "error": None})
        )

    async def save_results(
        self,
        document_id: str,
        *,
        model: str,
        extraction: dict[str, Any],
        compliance: dict[str, Any],
        scorecard: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> DocumentRecord:
        values = {
            "status": "extracted",
            "model": model,
            "extraction": extraction,
            "compliance": compliance,
            "scorecard": scorecard,
            "provider": provider,
            # Eine neue Analyse ersetzt den Pruefgegenstand: ein altes Siegel
            # gilt nicht mehr (die Historie bleibt im Audit-Ledger erhalten).
            "sign_off": None,
            "error": None,
            "extracted_at": utcnow(),
        }
        return await self._update_and_get(document_id, values)

    async def save_sign_off(self, document_id: str, sign_off: dict[str, Any]) -> DocumentRecord:
        return await self._update_and_get(document_id, {"sign_off": sign_off})

    async def set_pinned(self, document_id: str, pinned: bool) -> DocumentRecord:
        return await self._update_and_get(document_id, {"pinned": pinned})

    async def list_all(self) -> list[DocumentRecord]:
        records, _ = await anyio.to_thread.run_sync(partial(self._select_many, 100_000, 0, None))
        return records

    async def _update_and_get(self, document_id: str, values: dict[str, Any]) -> DocumentRecord:
        await anyio.to_thread.run_sync(partial(self._update, document_id, values))
        record = await self.get(document_id)
        if record is None:  # pragma: no cover - nur bei parallelem Loeschen erreichbar
            raise LookupError(f"Dokument {document_id} nach dem Speichern nicht auffindbar.")
        return record

    async def mark_failed(self, document_id: str, error: str) -> None:
        await anyio.to_thread.run_sync(
            partial(self._update, document_id, {"status": "failed", "error": error[:2000]})
        )

    async def ping(self) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(self._ping)


# ---------------------------------------------------------------------------
# Engine-Fabrik
# ---------------------------------------------------------------------------


def create_engine_from_settings(settings: Settings) -> Engine:
    """Erzeugt die Engine passend zum konfigurierten Dialekt."""
    url = settings.resolved_database_url
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}

    if url.startswith("sqlite"):
        # FastAPI bedient Requests aus einem Threadpool -> Thread-Bindung loesen.
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = sa.create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @sa.event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
            """WAL + Fremdschluesselpruefung: mehr Nebenlaeufigkeit, mehr Integritaet."""
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine


def _migrate_columns(engine: Engine) -> None:
    """Ergaenzt neue Spalten in bestehenden Datenbanken (additiv, ohne Datenverlust).

    Fuer ein Projekt dieser Groesse genuegt diese idempotente Additiv-Migration;
    bei echten Schemaaenderungen (Umbenennen, Typwechsel) gehoert Alembic dazu.
    """
    existing = {column["name"] for column in sa.inspect(engine).get_columns("documents")}
    missing = {name: ddl for name, ddl in _MIGRATED_COLUMNS.items() if name not in existing}
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing.items():
            connection.execute(sa.text(f"ALTER TABLE documents ADD COLUMN {name} {ddl}"))


_SQLITE_IMMUTABILITY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS audit_trails_no_update BEFORE UPDATE ON audit_trails
    BEGIN SELECT RAISE(ABORT, 'audit_trails ist append-only: UPDATE verboten'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_trails_no_delete BEFORE DELETE ON audit_trails
    BEGIN SELECT RAISE(ABORT, 'audit_trails ist append-only: DELETE verboten'); END""",
)

_POSTGRES_IMMUTABILITY_TRIGGERS = (
    """CREATE OR REPLACE FUNCTION audit_trails_append_only() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'audit_trails ist append-only'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS audit_trails_append_only ON audit_trails",
    """CREATE TRIGGER audit_trails_append_only BEFORE UPDATE OR DELETE ON audit_trails
    FOR EACH ROW EXECUTE FUNCTION audit_trails_append_only()""",
)


def _install_immutability_triggers(engine: Engine) -> None:
    """Verhindert UPDATE/DELETE auf dem Pruefprotokoll bereits auf Datenbankebene."""
    statements = {
        "sqlite": _SQLITE_IMMUTABILITY_TRIGGERS,
        "postgresql": _POSTGRES_IMMUTABILITY_TRIGGERS,
    }.get(engine.dialect.name, ())
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sa.text(statement))


def init_database(engine: Engine) -> None:
    """Legt fehlende Tabellen/Spalten und die Ledger-Trigger an (idempotent)."""
    metadata.create_all(engine)
    _migrate_columns(engine)
    _install_immutability_triggers(engine)


def build_repository(settings: Settings) -> tuple[Engine, SqlDocumentRepository]:
    """Bequemer Einstiegspunkt fuer Anwendung und Tests."""
    settings.ensure_directories()
    engine = create_engine_from_settings(settings)
    init_database(engine)
    return engine, SqlDocumentRepository(engine)
