"""EU AI Act Art. 14: Uebersteuerung durch die Pruefperson, signierte Ledger-Eintraege."""

from __future__ import annotations

import io
import json
import zipfile

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.audit_ledger import AuditEventType, AuditLedger, compute_entry_hash
from app.db import audit_trails_table, build_repository
from app.signing import SystemSigner

OVERRIDE = {
    "auditor_name": "Lutz Zarske",
    "risk_level": "limited",
    "reason": "Das System sortiert Bewerbungen nur vor; jede Auswahl trifft die Personalabteilung selbst.",
    "legal_basis": "Art. 6 Abs. 3 lit. d VO (EU) 2024/1689",
}


def _seed(client: TestClient) -> dict[str, str]:
    return {item["filename"]: item["id"] for item in client.post("/api/demo/seed").json()["items"]}


def _recruiting(client: TestClient) -> str:
    return _seed(client)["KI_Recruiting_Dienstleistervertrag.pdf"]


def test_override_rechnet_score_neu_und_protokolliert(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    response = full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    assert response.status_code == 200, response.text
    detail = response.json()
    card = detail["scorecard"]
    assert detail["compliance"]["ai_act"]["overall_risk_level"] == "limited"
    assert card["score"] == 95 and card["cap_applied"] is None  # Deckel 59 entfaellt
    override = card["human_override"]
    assert (override["previous_risk_level"], override["new_risk_level"]) == ("high", "limited")
    assert (override["previous_score"], override["new_score"]) == (59, 95)
    assert "Art. 6 Abs. 3" in override["legal_basis"]
    assert "Menschliche Übersteuerung" in detail["compliance"]["ai_act"]["reasoning"]


def test_override_eintrag_im_ledger_mit_vorgaenger_und_signatur(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    head_before = full_client.get("/api/audit/head").json()["head_hash"]
    full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    entry = full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"][0]
    assert entry["event_type"] == AuditEventType.HUMAN_OVERRIDE == "human_override"
    assert entry["previous_hash"] == head_before
    assert entry["signature_status"] == "valid"
    details = entry["details"]
    assert details["auditor_name"] == "Lutz Zarske"
    assert (details["previous_score"], details["new_score"]) == (59, 95)
    assert details["legal_reference"] == "Art. 14 Abs. 4 lit. d VO (EU) 2024/1689"
    assert details["signature"]["algorithm"] == "Ed25519"
    assert details["signature"]["fingerprint"] == full_client.get("/api/audit/signing-key").json()["fingerprint"]
    verification = full_client.get("/api/audit/verify").json()
    assert verification["valid"] is True and verification["signed_entries"] == 2  # Demo-Siegel + Override


def test_override_hebt_siegel_auf(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    sealed = full_client.post(
        f"/documents/{document_id}/sign-off",
        json={"auditor_name": "Erika Muster", "note": "", "decision": "SEALED_REJECTED"},
    ).json()
    assert sealed["sign_off"] is not None
    detail = full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE).json()
    assert detail["sign_off"] is None


def test_neue_analyse_verwirft_override(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    reanalysed = full_client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert reanalysed["scorecard"]["human_override"] is None
    events = [e["event_type"] for e in full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"]]
    assert events[:2] == ["analysis", "human_override"]  # Historie bleibt erhalten


def test_override_ohne_aenderung_wird_abgelehnt(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    response = full_client.post(f"/api/documents/{document_id}/override", json={**OVERRIDE, "risk_level": "high"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "override_without_change"


def test_override_verlangt_begruendung_und_norm(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    short = full_client.post(f"/api/documents/{document_id}/override", json={**OVERRIDE, "reason": "passt so"})
    assert short.status_code == 422
    no_norm = full_client.post(f"/api/documents/{document_id}/override", json={**OVERRIDE, "legal_basis": ""})
    assert no_norm.status_code == 422


def test_override_vor_analyse_nicht_moeglich(client: TestClient) -> None:
    from tests.conftest import build_pdf, uploaded_document_id

    document_id = uploaded_document_id(
        client, build_pdf([["Rechnung Nr. 1 vom 01.01.2026 ueber Beratungsleistungen, netto 100,00 EUR"]])
    )
    response = client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    assert response.status_code == 409


def test_siegel_wird_ebenfalls_signiert(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_Gueltig_14UStG.pdf"]
    seal = full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"][0]
    assert seal["event_type"] == "sign_off" and seal["signature_status"] == "valid"
    analysis = full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"][1]
    assert analysis["signature_status"] == "unsigned"  # Maschinelle Eintraege bleiben unsigniert


def test_zertifikat_zeigt_pruefer_meilenstein(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    html = full_client.get(f"/documents/{document_id}/report").text
    assert "Prüfer-Meilenstein" in html and "Art. 14 Abs. 4 lit. d" in html
    assert "Ed25519-signiert" in html
    report = full_client.get(f"/documents/{document_id}/report", params={"format": "json"}).json()
    assert report["human_override"]["new_score"] == 95
    assert any(item["milestone"] and item["signed"] for item in report["ledger_history"])
    markdown = full_client.get(f"/documents/{document_id}/report", params={"format": "markdown"}).text
    assert "Übersteuerung der KI-Einstufung" in markdown


def test_neu_berechnete_kette_faellt_an_der_signatur_auf(tmp_path, settings) -> None:
    """Wer einen Pruefer-Eintrag aendert und die Hashes neu berechnet, bricht die Ed25519-Signatur."""
    engine, _ = build_repository(settings)
    signer = SystemSigner(tmp_path / "keys" / ".signing.key")
    ledger = AuditLedger(engine, signer=signer)

    import anyio

    async def write() -> None:
        await ledger.append(
            event_type=AuditEventType.HUMAN_OVERRIDE, document_id="d1", sha256_hash="0" * 64, model_name="m",
            prompt_hash="p", result_summary="Override", compliance_score=95, risk_tier="limited",
            details={"auditor_name": "A", "new_score": 95},
        )

    anyio.run(write)
    assert anyio.run(ledger.verify_chain).valid is True

    # Angriff mit Vollzugriff: Trigger entfernen, Score aendern, Hash neu berechnen.
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TRIGGER IF EXISTS audit_trails_no_update"))
        row = connection.execute(sa.select(audit_trails_table)).first()._mapping
        details = dict(row["details"])
        details["new_score"] = 100
        content = {
            key: row[key] for key in (
                "entry_id", "event_type", "document_id", "sha256_hash", "model_name", "prompt_hash",
                "timestamp_utc", "result_summary", "compliance_score", "risk_tier", "previous_hash",
            )
        }
        content["details"] = details
        connection.execute(
            sa.update(audit_trails_table)
            .where(audit_trails_table.c.seq == row["seq"])
            .values(details=details, entry_hash=compute_entry_hash(content))
        )

    result = anyio.run(ledger.verify_chain)
    assert result.valid is False
    assert "Pruefer-Signatur" in (result.reason or "")


def test_fremder_schluessel_wird_erkannt(tmp_path, settings) -> None:
    engine, _ = build_repository(settings)
    writer = AuditLedger(engine, signer=SystemSigner(tmp_path / "a" / ".signing.key"))
    import anyio

    async def write() -> None:
        await writer.append(
            event_type=AuditEventType.SIGN_OFF, document_id="d1", sha256_hash="0" * 64, model_name="m",
            prompt_hash="p", result_summary="Siegel", compliance_score=100, risk_tier="none",
            details={"auditor_name": "A"},
        )

    anyio.run(write)
    reader = AuditLedger(engine, signer=SystemSigner(tmp_path / "b" / ".signing.key"))
    result = anyio.run(reader.verify_chain)
    assert result.valid is False and "fremden Schluessel" in (result.reason or "")


def test_pruefpaket_enthaelt_signierten_override(full_client: TestClient) -> None:
    document_id = _recruiting(full_client)
    full_client.post(f"/api/documents/{document_id}/override", json=OVERRIDE)
    archive = zipfile.ZipFile(io.BytesIO(full_client.get(f"/api/documents/{document_id}/export/gobd").content))
    ledger = json.loads(archive.read("ledger_audit_trail.json"))
    override = next(e for e in ledger["entries"] if e["event_type"] == "human_override")
    assert override["entry_hash_recomputed_ok"] is True and "signature" in override["details"]
    assert ledger["chain_verification"]["signed_entries"] >= 1
