"""Tests des hash-verketteten Pruefprotokolls (audit_trails)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.audit_ledger import GENESIS_HASH, AuditLedger, compute_entry_hash
from app.config import Settings
from app.db import build_repository
from tests.conftest import uploaded_document_id


@pytest.fixture
def ledger(settings: Settings) -> AuditLedger:
    engine, _ = build_repository(settings)
    return AuditLedger(engine)


async def _append(ledger: AuditLedger, doc: str = "doc-1", score: int | None = 90):
    return await ledger.append(
        event_type="analysis",
        document_id=doc,
        sha256_hash="a" * 64,
        model_name="qwen2.5:14b-instruct",
        prompt_hash="b" * 64,
        result_summary="Keine Compliance-Auffälligkeiten",
        compliance_score=score,
        risk_tier="not_applicable",
    )


async def test_erster_eintrag_verweist_auf_genesis(ledger: AuditLedger) -> None:
    entry = await _append(ledger)

    assert entry.seq == 1
    assert entry.previous_hash == GENESIS_HASH
    assert entry.entry_hash == compute_entry_hash(entry.hashed_content())


async def test_eintraege_sind_verkettet_und_kette_valide(ledger: AuditLedger) -> None:
    first = await _append(ledger, "doc-1")
    second = await _append(ledger, "doc-2")
    third = await _append(ledger, "doc-1")

    assert second.previous_hash == first.entry_hash
    assert third.previous_hash == second.entry_hash

    result = await ledger.verify_chain()
    assert result.valid is True
    assert result.entries == 3
    assert result.head_hash == third.entry_hash
    assert (await ledger.head()) == (third.entry_hash, 3)

    only_doc1 = await ledger.list(document_id="doc-1")
    assert [entry.seq for entry in only_doc1] == [3, 1]


async def test_trigger_verhindern_update_und_delete(ledger: AuditLedger) -> None:
    await _append(ledger)
    engine = ledger._engine  # noqa: SLF001

    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE audit_trails SET compliance_score = 100"))
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM audit_trails"))


async def test_manipulation_wird_mit_sequenz_nachgewiesen(ledger: AuditLedger) -> None:
    """Selbst wer die Trigger entfernt, faellt bei der Kettenpruefung auf."""
    await _append(ledger, score=40)
    await _append(ledger, score=55)
    await _append(ledger, score=61)
    engine = ledger._engine  # noqa: SLF001

    with engine.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER audit_trails_no_update"))
        connection.execute(sa.text("UPDATE audit_trails SET compliance_score = 99 WHERE seq = 2"))

    result = await ledger.verify_chain()
    assert result.valid is False
    assert result.broken_at_seq == 2
    assert "verändert" in (result.reason or "")


async def test_geloeschter_eintrag_wird_erkannt(ledger: AuditLedger) -> None:
    for _ in range(3):
        await _append(ledger)
    engine = ledger._engine  # noqa: SLF001

    with engine.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER audit_trails_no_delete"))
        connection.execute(sa.text("DELETE FROM audit_trails WHERE seq = 2"))

    result = await ledger.verify_chain()
    assert result.valid is False
    assert result.broken_at_seq == 3


def test_extraktion_schreibt_ledger_eintrag_und_api_verifiziert(
    client: TestClient, invoice_pdf: bytes
) -> None:
    document_id = uploaded_document_id(client, invoice_pdf)
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200

    trail = client.get("/api/audit/trail", params={"document_id": document_id}).json()
    assert trail["count"] == 2
    newest, oldest = trail["items"]
    assert newest["previous_hash"] == oldest["entry_hash"]
    assert newest["event_type"] == "analysis"
    assert newest["model_name"] == "qwen2.5:14b-instruct"
    assert len(newest["prompt_hash"]) == 64
    assert newest["risk_tier"] == "high"

    verify = client.get("/api/audit/verify").json()
    assert verify["valid"] is True
    assert verify["entries"] == 2
    assert client.get("/api/audit/head").json()["head_hash"] == newest["entry_hash"]


def test_bestehende_datenbank_wird_additiv_migriert(settings: Settings) -> None:
    """Eine v1-Datenbank ohne neue Spalten startet ohne Datenverlust."""
    db_file = settings.resolved_database_url.removeprefix("sqlite:///")
    settings.ensure_directories()
    legacy = sa.create_engine(f"sqlite:///{db_file}")
    with legacy.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE documents (id VARCHAR(36) PRIMARY KEY, original_filename VARCHAR(500) NOT NULL,"
            " stored_filename VARCHAR(500) NOT NULL, content_type VARCHAR(120) NOT NULL,"
            " size_bytes INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL,"
            " page_count INTEGER, char_count INTEGER, raw_text TEXT, model VARCHAR(120),"
            " extraction JSON, compliance JSON, error TEXT, created_at DATETIME NOT NULL,"
            " updated_at DATETIME NOT NULL, extracted_at DATETIME)"
        ))
        connection.execute(sa.text(
            "INSERT INTO documents (id, original_filename, stored_filename, content_type, size_bytes,"
            " sha256, status, created_at, updated_at) VALUES ('alt', 'alt.pdf', 'alt.pdf',"
            " 'application/pdf', 10, 'x', 'uploaded', '2024-01-01', '2024-01-01')"
        ))
    legacy.dispose()

    engine, _ = build_repository(settings)
    columns = {column["name"] for column in sa.inspect(engine).get_columns("documents")}
    assert {"provider", "scorecard", "sign_off", "pinned"} <= columns
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT pinned FROM documents")).scalar_one() == 0
