"""Regressionstests für alle Sicherheits-, Fachlogik-, Krypto- und Export-Fixes aus v2.8.0."""

from __future__ import annotations

import dataclasses
import io
import os
import subprocess
import sys
import time
import warnings
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.audit_ledger import AuditEventType, AuditLedger, ChainVerification
from app.config import Settings
from app.db import NewDocument, build_repository
from app.extractors.einvoice import _decimal, parse_einvoice_xml, to_extraction
from app.extractors.pdf_attachments import _safe_attachment_name
from app.gobd_export import MANIFEST_FILE, _safe_zip_member, verify_package
from app.pdf_export import render_report_pdf
from app.privacy_vault import PrivacyVault
from app.procedural_doc import build_procedural_doc, render_markdown as render_proc_markdown
from app.redact import redact
from app.redaction import build_text_view, scan_text
from app.release import ReleaseError, ReleaseManager
from app.reporting import build_report, render_html, render_markdown
from app.retention import invoice_retention
from app.runtime_settings import validate_model_id
from app.schemas import (
    AIActAssessment,
    AIActRiskLevel,
    AISystemFinding,
    ComplianceAudit,
    DocType,
    ExtractionResult,
    GDPRAssessment,
    PIICategory,
)
from app.scoring import compute_scorecard, facts_has_positions
from app.signing import SystemSigner


def _audit(ai_act: AIActAssessment | None = None) -> ComplianceAudit:
    return ComplianceAudit(
        ai_act=ai_act or AIActAssessment(),
        gdpr=GDPRAssessment(),
        model="test-model",
        audited_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# H-1, H-5, H-6: Zip Slip, doppelte ZIP-Einträge & eigenständiges Verify-Skript
# ---------------------------------------------------------------------------


def test_pdf_attachment_und_zip_member_bereinigen_pfad_traversal() -> None:
    assert _safe_attachment_name("../../evil.xml", "attachment.xml") == "evil.xml"
    assert _safe_attachment_name(r"C:\windows\system32\factur-x.xml", "attachment.xml") == "factur-x.xml"
    assert _safe_attachment_name("..", "attachment.xml") == "attachment.xml"

    assert _safe_zip_member("../../evil.xml") == "evil.xml"
    assert _safe_zip_member("manifest.json") == "xml/manifest.json"


def test_verify_package_und_standalone_skript_pruefen_duplikate_und_signatur(
    tmp_path: Path, make_full_client: Callable[..., TestClient]
) -> None:
    client = make_full_client()
    seed = client.post("/api/demo/seed", params={"only": "Rechnung_Gueltig_14UStG.pdf"}).json()
    doc_id = seed["items"][0]["id"]

    resp = client.get(f"/api/documents/{doc_id}/export/gobd")
    assert resp.status_code == 200
    zip_bytes = resp.content
    assert verify_package(zip_bytes)["valid"] is True

    fingerprint = client.get("/api/audit/signing-key").json()["fingerprint"]
    pkg_path = tmp_path / "paket.zip"
    pkg_path.write_bytes(zip_bytes)

    # Eigenständiges Skript ohne Projekt-PYTHONPATH (darf kein app.* importieren).
    script = Path(__file__).resolve().parent.parent / "scripts" / "verify_pruefpaket.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, "-I", str(script), str(pkg_path), "--fingerprint", fingerprint],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout

    # Doppelter ZIP-Eintrag muss sowohl von verify_package als auch vom Skript abgewiesen werden.
    dup_buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as src, zipfile.ZipFile(dup_buf, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                dst.writestr(info.filename, data)
                if info.filename == MANIFEST_FILE:
                    dst.writestr(info.filename, data)
    dup_bytes = dup_buf.getvalue()
    assert verify_package(dup_bytes)["valid"] is False

    dup_path = tmp_path / "dup.zip"
    dup_path.write_bytes(dup_bytes)
    dup_proc = subprocess.run(
        [sys.executable, "-I", str(script), str(dup_path)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert dup_proc.returncode == 1


# ---------------------------------------------------------------------------
# H-2, H-3, M-3: Loopback-CORS, Cross-Site-Guard, Modell-ID-Traversal, Atomicity
# ---------------------------------------------------------------------------


def test_default_cors_loopback_und_cross_site_origin_blockiert(
    make_full_client: Callable[..., TestClient]
) -> None:
    default_settings = Settings(_env_file=None)
    assert "*" not in default_settings.cors_origin_list
    assert "http://127.0.0.1:3001" in default_settings.cors_origin_list

    client = make_full_client()
    blocked = client.post(
        "/api/settings",
        json={"pii_strictness": "audit_only"},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403

    blocked_sec_fetch = client.post(
        "/api/settings",
        json={"pii_strictness": "audit_only"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert blocked_sec_fetch.status_code == 403

    allowed = client.post(
        "/api/settings",
        json={"pii_strictness": "strict"},
        headers={"Origin": "http://127.0.0.1:3001"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["pii_strictness"] == "strict"

    # Browser auf http://localhost:3001 sendet bei Aufruf von http://127.0.0.1:8001
    # Origin: http://localhost:3001 UND Sec-Fetch-Site: cross-site -> muss erlaubt sein!
    allowed_localhost = client.post(
        "http://127.0.0.1:8001/api/settings",  # Browser-Anfragen tragen den echten Loopback-Host
        json={"pii_strictness": "standard"},
        headers={"Origin": "http://localhost:3001", "Sec-Fetch-Site": "cross-site"},
    )
    assert allowed_localhost.status_code == 200
    assert allowed_localhost.json()["pii_strictness"] == "standard"


def test_model_id_path_traversal_abgewiesen_und_settings_update_atomar(
    make_full_client: Callable[..., TestClient]
) -> None:
    with pytest.raises(ValueError):
        validate_model_id("../files?key=1#")
    with pytest.raises(ValueError):
        validate_model_id("gemini-3.8-flash/../../secret")
    assert validate_model_id("qwen2.5:14b-instruct") == "qwen2.5:14b-instruct"

    client = make_full_client()
    before = client.get("/api/settings").json()["pii_strictness"]
    bad = client.post(
        "/api/settings",
        json={
            "pii_strictness": "audit_only",
            "models": {"gemini": "../v1beta/files?alt=media#"},
        },
    )
    assert bad.status_code == 422
    # Atomar: das gültige Feld pii_strictness darf nicht halb übernommen worden sein.
    assert client.get("/api/settings").json()["pii_strictness"] == before


# ---------------------------------------------------------------------------
# H-4, H-7, H-9: PrivacyVault ID-Kategorien, Zeilenumbrüche & lineares DLP
# ---------------------------------------------------------------------------


def test_privacy_vault_maskiert_ausweis_svnr_steuerid_geburtsdatum_und_erhaelt_zeilenumbrueche() -> None:
    text = (
        "Hauptstraße 12\n"
        "10115 Berlin\n"
        "Personalausweis: T220001293\n"
        "SV-Nr.: 65 170839 A 123\n"
        "Steuer-ID: 12345678901\n"
        "Geburtsdatum: 14.05.1984\n"
        "USt-IdNr.: ATU33864707\n"
        "Betrag: 1.250,00 CHF\n"
    )
    vault = PrivacyVault()
    masked = vault.pseudonymize(text)

    assert "T220001293" not in masked
    assert "170839" not in masked
    assert "12345678901" not in masked
    assert "14.05.1984" not in masked
    assert "ATU33864707" not in masked
    assert "1.250,00 CHF" not in masked

    # H-9: Zeilenanzahl bleibt identisch, \n nach "Hauptstraße 12" wird nicht verschluckt.
    assert masked.count("\n") == text.count("\n")
    assert vault.reidentify(masked) == text


def test_dlp_redact_skaliert_linear_bei_vielen_treffern() -> None:
    chunk = "Kontakt: max@firma.example, IBAN DE89370400440532013000, key=sk-ant-123456789012345678901234567890\n"
    payload = chunk * 350  # ~33 KB, >1000 Treffer
    started = time.perf_counter()
    res = redact(payload)
    elapsed = time.perf_counter() - started
    assert res.total >= 1000
    assert "max@firma.example" not in res.text
    assert elapsed < 2.0, f"redact zu langsam ({elapsed:.2f}s)"


# ---------------------------------------------------------------------------
# H-8, H-10, H-11, H-12, M-10, M-11, M-12: Fachlogik & Scoring
# ---------------------------------------------------------------------------


def test_einzelne_absenderadresse_umgeht_nicht_empfaengeradress_pruefung() -> None:
    text = (
        "Nordlicht IT-Services GmbH\n"
        "Hafenstraße 12, 20457 Hamburg\n"
        "USt-IdNr.: DE287654321\n"
        "An: Brandt Maschinenbau AG\n"
        "RECHNUNG Nr. RE-2026-01\n"
        "Rechnungsdatum: 14.03.2026\n"
        "Leistungsdatum: 10.03.2026\n"
        "Pos. 1 Beratung 10 Std. 1.000,00 EUR\n"
        "Nettobetrag: 1.000,00 EUR\n"
        "Umsatzsteuer 19 %: 190,00 EUR\n"
        "Gesamtbetrag: 1.190,00 EUR\n"
    )
    extraction = ExtractionResult(
        doc_type=DocType.INVOICE,
        sender="Nordlicht IT-Services GmbH",
        sender_address="Hafenstraße 12, 20457 Hamburg",
        recipient="Brandt Maschinenbau AG",
        recipient_address=None,
        sender_vat_id="DE287654321",
        document_number="RE-2026-01",
        document_date=date(2026, 3, 14),
        service_date=date(2026, 3, 10),
        items_description="Beratung 10 Std.",
        net_amount=Decimal("1000.00"),
        tax_rate=Decimal("19"),
        tax_amount=Decimal("190.00"),
        total_amount=Decimal("1190.00"),
        currency="EUR",
    )
    card = compute_scorecard(extraction, _audit(), text)
    formal = next(t for t in card.tiles if t.key == "formal")
    recip = next(c for c in formal.checks if c.id == "ustg_1_recipient")
    assert recip.status.value == "fail"
    assert recip.deduction == 10
    assert card.score == 90


def test_art5_unacceptable_zeigt_verbots_empfehlung() -> None:
    audit = _audit(
        AIActAssessment(
            describes_ai_system=True,
            overall_risk_level=AIActRiskLevel.UNACCEPTABLE,
            systems=[AISystemFinding(name="SocialScore", risk_level=AIActRiskLevel.UNACCEPTABLE)],
        )
    )
    card = compute_scorecard(ExtractionResult(doc_type=DocType.CONTRACT), audit, "Social Scoring System")
    assert card.score <= 20
    assert card.release_blocked is True
    assert "Art. 5" in card.release_recommendation
    assert "Art. 43" not in card.release_recommendation


def test_human_override_aktualisiert_is_high_risk_und_headline(
    make_full_client: Callable[..., TestClient]
) -> None:
    client = make_full_client()
    seed = client.post("/api/demo/seed", params={"only": "KI_Recruiting_Dienstleistervertrag.pdf"}).json()
    doc_id = seed["items"][0]["id"]

    res = client.post(
        f"/api/documents/{doc_id}/override",
        json={
            "auditor_name": "Dr. Clara Prüfer",
            "risk_level": "limited",
            "reason": "Rein vorbereitende Textformatierung ohne Bewertung oder Profiling natürlicher Personen.",
            "legal_basis": "Art. 6 Abs. 3 lit. d VO (EU) 2024/1689",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["compliance"]["ai_act"]["overall_risk_level"] == "limited"
    assert body["compliance"]["ai_act"]["is_high_risk"] is False
    reg = next(t for t in body["scorecard"]["tiles"] if t["key"] == "regulatory")
    assert "Hochrisiko" not in reg["headline"]


def test_steuersatz_format_fremdwaehrung_kleinbetrag_und_14c_konflikt() -> None:
    # 1) 20 % darf niemals als "2E+1 %" erscheinen; bei DE-Aussteller -> FAIL, bei AT-Aussteller -> WARN
    de_invoice = ExtractionResult(
        doc_type=DocType.INVOICE,
        sender="Inland GmbH",
        sender_address="Musterstr. 1, 10115 Berlin",
        recipient="Kunde AG",
        recipient_address="Zielweg 2, 20095 Hamburg",
        sender_vat_id="DE287654321",
        document_number="R-1",
        document_date=date(2026, 5, 1),
        service_date=date(2026, 5, 1),
        items_description="Beratung",
        net_amount=Decimal("1000.00"),
        tax_rate=Decimal("20"),
        tax_amount=Decimal("200.00"),
        total_amount=Decimal("1200.00"),
        currency="EUR",
    )
    de_card = compute_scorecard(de_invoice, _audit(), "")
    vat_check = next(c for t in de_card.tiles if t.key == "math" for c in t.checks if c.id == "vat_rate")
    assert vat_check.status.value == "fail"
    assert "20 %" in (vat_check.detail or "")
    assert "2E+1" not in (vat_check.detail or "")

    at_invoice = de_invoice.model_copy(update={"sender_vat_id": "ATU33864707"})
    at_card = compute_scorecard(at_invoice, _audit(), "")
    at_vat = next(c for t in at_card.tiles if t.key == "math" for c in t.checks if c.id == "vat_rate")
    assert at_vat.status.value == "warn"
    assert at_vat.deduction == 0
    assert "20 %" in (at_vat.detail or "")

    # 2) 240 GBP ist KEINE EUR-Kleinbetragsrechnung nach § 33 UStDV
    gbp = de_invoice.model_copy(
        update={
            "currency": "GBP",
            "net_amount": Decimal("200.00"),
            "tax_rate": Decimal("20"),
            "tax_amount": Decimal("40.00"),
            "total_amount": Decimal("240.00"),
        }
    )
    assert compute_scorecard(gbp, _audit(), "").small_amount_invoice is False

    # 3) § 14c UStG Konflikt: Befreiungshinweis + positive USt
    conflict = de_invoice.model_copy(
        update={
            "tax_rate": Decimal("19"),
            "tax_amount": Decimal("190.00"),
            "total_amount": Decimal("1190.00"),
            "tax_exemption_note": "Steuerfrei nach § 19 UStG (Kleinunternehmerregelung)",
        }
    )
    c_card = compute_scorecard(conflict, _audit(), "")
    c14 = next((c for t in c_card.tiles if t.key == "math" for c in t.checks if c.id == "ustg_14c_conflict"), None)
    assert c14 is not None and c14.status.value == "fail" and c14.deduction == 10


def test_negative_gutschrift_mischsaetze_und_verneinte_positionen() -> None:
    assert facts_has_positions(ExtractionResult(summary="Keine Leistungsbeschreibung vorhanden.")) is False
    assert facts_has_positions(ExtractionResult(summary="Wartungsleistung Serverbetrieb Mai 2026")) is True

    # Negative Mischsatz-Gutschrift: -1.000 netto, -150 USt, -1.150 brutto bei 7 % und 19 % im Text
    text = "Gutschrift -1.000,00 EUR netto, Position A 19 %, Position B 7 %, USt -150,00 EUR, Brutto -1.150,00 EUR"
    cn = ExtractionResult(
        doc_type=DocType.INVOICE,
        net_amount=Decimal("-1000.00"),
        tax_rate=Decimal("19"),
        tax_amount=Decimal("-150.00"),
        total_amount=Decimal("-1150.00"),
        currency="EUR",
    )
    card = compute_scorecard(cn, _audit(), text)
    tax_calc = next(c for t in card.tiles if t.key == "math" for c in t.checks if c.id == "tax_calc")
    assert tax_calc.status.value == "warn"
    assert tax_calc.deduction == 0

    # UNTDID 389 (echte umsatzsteuerliche Gutschrift) wird erkannt
    ubl_389 = b"""<?xml version="1.0" encoding="UTF-8"?>
    <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
             xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
             xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
      <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>
      <cbc:ID>GS-389</cbc:ID>
      <cbc:IssueDate>2026-06-01</cbc:IssueDate>
      <cbc:InvoiceTypeCode>389</cbc:InvoiceTypeCode>
      <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
      <cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Lieferant GmbH</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
      <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Kunde AG</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
      <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount><cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
    </Invoice>"""
    parsed = parse_einvoice_xml(ubl_389)
    assert parsed.type_code == "389"
    assert "Gutschrift" in (to_extraction(parsed).summary or "")


def test_art9_false_positives_und_komposita_maskierung() -> None:
    clean_business = "Der Prüfbefund zur steuerlichen Behandlung ergab keine Beanstandung."
    assert not any(f.category is PIICategory.HEALTH_DATA for f in scan_text(clean_business))

    compound = "Patient wurde in der Universitätsklinik behandelt."
    view = build_text_view(compound, level="standard")
    assert "Universitätsklinik" not in view["text"]
    assert "[ART. 9]" in view["text"]


# ---------------------------------------------------------------------------
# H-13, M-1, M-2, M-5, M-6: Heuristik-Banner, XML/Retention-Schutz, PDF, Release, Ledger
# ---------------------------------------------------------------------------


def test_xml_nan_extremwerte_und_retention_jahresgrenze() -> None:
    assert _decimal("NaN") is None
    assert _decimal("Infinity") is None
    assert _decimal("-Infinity") is None
    assert _decimal("1E+50") is None
    assert _decimal("123.45") == Decimal("123.45")

    r = invoice_retention(date(9995, 5, 1))
    assert r is not None
    assert r.until.year == date.max.year
    assert r.financial_sector_until.year == date.max.year


async def test_heuristik_banner_und_ueberlange_pdf_zellen(
    tmp_path: Path, make_full_client: Callable[..., TestClient]
) -> None:
    client = make_full_client()
    seed = client.post("/api/demo/seed", params={"only": "KI_Recruiting_Dienstleistervertrag.pdf"}).json()
    doc_id = seed["items"][0]["id"]
    record = await client.app.state.repository.get(doc_id)  # type: ignore[attr-defined]
    assert record is not None

    # Heuristik-Pfad + 1.950-Zeichen-Text testen (M-2 LayoutError-Schutz + H-13 Banner)
    long_text = ("Ausführliche Prüfbegründung ohne Umbruch " * 50)[:1950]
    compliance = dict(record.compliance or {})
    compliance["ai_act"] = dict(compliance.get("ai_act") or {}, reasoning=long_text)
    heuristic_record = dataclasses.replace(record, provider="heuristic", compliance=compliance)

    verif = ChainVerification(True, 0, "0" * 64)
    report_de = build_report(heuristic_record, [], verif, lang="de")
    report_en = build_report(heuristic_record, [], verif, lang="en")
    md = render_markdown(report_de, lang="de")
    html = render_html(report_en, lang="en")
    pdf = render_report_pdf(report_de, lang="de")

    settings = Settings(_env_file=None)
    signer = SystemSigner(tmp_path / ".signing.key")
    proc_de = build_procedural_doc(
        settings=settings, runtime=None, record=heuristic_record, entries=[],
        verification=verif, signing_key=signer.public_info(), lang="de",
    )
    proc_en = build_procedural_doc(
        settings=settings, runtime=None, record=heuristic_record, entries=[],
        verification=verif, signing_key=signer.public_info(), lang="en",
    )

    assert "Regelbasiertes" in md
    assert "Rule-based" in html or "Rule-Based" in html
    assert pdf.startswith(b"%PDF-") and len(pdf) > 2000
    assert "Regelbasiertes Referenz-Audit" in render_proc_markdown(proc_de)
    assert "Rule-Based Fallback Audit" in render_proc_markdown(proc_en)


def test_release_manager_weist_non_fast_forward_ab(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    other = tmp_path / "other"

    def git(cwd: Path, *args: str) -> str:
        res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
        return res.stdout.strip()

    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)
    git(local, "config", "user.email", "test@example.com")
    git(local, "config", "user.name", "Test")
    (local / "a.txt").write_text("v1\n", encoding="utf-8")
    git(local, "add", "a.txt")
    git(local, "commit", "-m", "v1")
    git(local, "tag", "v1.0.0")
    git(local, "push", "-u", "origin", "HEAD", "--tags")

    # Divergierender Commit auf einem anderen Klon (nicht Fast-Forward).
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    git(other, "config", "user.email", "test@example.com")
    git(other, "config", "user.name", "Test")
    (other / "b.txt").write_text("remote\n", encoding="utf-8")
    git(other, "add", "b.txt")
    git(other, "commit", "-m", "v2")
    git(other, "tag", "v2.0.0")
    target_commit = git(other, "rev-parse", "HEAD")
    git(other, "push", "origin", "HEAD", "--tags")

    # Lokaler, nicht gepushter Commit -> Fast-Forward nach v2.0.0 unmöglich.
    (local / "local.txt").write_text("local-only\n", encoding="utf-8")
    git(local, "add", "local.txt")
    git(local, "commit", "-m", "local diverge")

    manager = ReleaseManager(local, "1.0.0")
    manager.status(fetch=True)
    with pytest.raises(ReleaseError) as exc_info:
        manager.apply_update(
            "v2.0.0",
            target_commit,
            active_analyses=0,
            database_file=None,
            backup_dir=tmp_path / "backups",
        )
    assert exc_info.value.code == "not_fast_forward"


async def test_audit_ledger_zaehlt_unsignierte_pruefer_eintraege(tmp_path: Path) -> None:
    engine, _ = build_repository(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'ledger.db'}"))
    ledger = AuditLedger(engine, signer=SystemSigner(tmp_path / "signing.key"))
    await ledger.append(
        event_type=AuditEventType.SIGN_OFF,
        document_id="doc-1",
        sha256_hash="a" * 64,
        model_name="reference-fixture",
        prompt_hash="p" * 16,
        result_summary="Freigegeben",
        compliance_score=100,
        risk_tier="not_applicable",
    )
    check = await ledger.verify_chain()
    assert check.valid is True
    assert check.signed_entries == 1
    assert check.unsigned_human_entries == 0

    # Simuliert historischen/unsignierten Prüfer-Eintrag über zweiten Ledger ohne Signer.
    unsigned_ledger = AuditLedger(engine, signer=None)
    await unsigned_ledger.append(
        event_type=AuditEventType.HUMAN_OVERRIDE,
        document_id="doc-1",
        sha256_hash="a" * 64,
        model_name="reference-fixture",
        prompt_hash="p" * 16,
        result_summary="Übersteuerung",
        compliance_score=80,
        risk_tier="limited",
    )
    check2 = await ledger.verify_chain()
    assert check2.valid is True
    assert check2.unsigned_human_entries == 1
    engine.dispose()


async def test_repository_ignoriert_verspaetetes_processing_update_nach_abbruch_und_dlp_kombiniert_begriffe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DLP_TERMS", "Projekt Orion")
    dlp_res = redact("Geheim: Projekt Orion und Projekt Pegasus.", extra_terms=["Projekt Pegasus"])
    assert "Projekt Orion" not in dlp_res.text
    assert "Projekt Pegasus" not in dlp_res.text
    assert dlp_res.counts.get("CONFIDENTIAL_TERM") == 2

    engine, repo = build_repository(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'seq.db'}"))
    created = await repo.create(
        NewDocument(
            id="doc-seq-1",
            original_filename="test.pdf",
            stored_filename="test.pdf",
            content_type="application/pdf",
            size_bytes=128,
            sha256="b" * 64,
            status="uploaded",
            page_count=1,
            char_count=10,
            raw_text="Inhalt",
        )
    )
    assert created.status == "uploaded"
    early_seq = repo._next_seq()  # type: ignore[attr-defined]
    await repo.restore_status(created.id, "uploaded")
    # Ein verspäteter Worker-Thread mit älterer Sequenznummer darf den Rollback nicht überschreiben.
    repo._update(created.id, {"status": "processing"}, early_seq)  # type: ignore[attr-defined]
    after = await repo.get(created.id)
    assert after is not None and after.status == "uploaded"
    engine.dispose()
