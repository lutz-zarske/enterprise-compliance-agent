"""API: XML-Upload, hybride PDFs, deterministischer XML-Pfad und Pruefdatenpaket (ZIP)."""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal

from fastapi.testclient import TestClient

from app.audit_ledger import compute_entry_hash
from app.demo import HYBRID_INVOICE, build_hybrid_pdf
from app.gobd_export import verify_package
from tests.conftest import FakeOllama, build_pdf, uploaded_document_id
from tests.einvoice_samples import XXE_XML, build_ubl_invoice

PLAIN_INVOICE = [
    "Muster GmbH, Musterweg 1, 12345 Musterstadt",
    "USt-IdNr.: DE123456789",
    "Rechnung Nr. 2026-1 vom 01.09.2026",
    "Leistungsdatum: 31.08.2026",
    "Beratung 10 Stunden",
    "Summe netto: 1.000,00 EUR",
    "zzgl. 19 % USt: 190,00 EUR",
    "Gesamtbetrag: 1.190,00 EUR",
]


def _upload(client: TestClient, data: bytes, filename: str, content_type: str):
    return client.post("/documents/upload", files={"file": (filename, data, content_type)})


def _hybrid_id(client: TestClient, **visual) -> str:
    response = _upload(client, build_hybrid_pdf(HYBRID_INVOICE, **visual), "hybrid.pdf", "application/pdf")
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_xrechnung_xml_upload_und_analyse_ohne_modell(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True  # der XML-Pfad braucht kein Sprachmodell
    response = _upload(client, build_ubl_invoice(), "XRechnung_XR-2026-077.xml", "application/xml")
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]
    assert response.json()["page_count"] == 0

    extracted = client.post(f"/documents/{document_id}/extract?wait=true")
    assert extracted.status_code == 200, extracted.text
    body = extracted.json()
    assert (body["model"], body["provider"]) == ("en16931-parser", "structured")
    assert body["extraction"]["document_number"] == "XR-2026-077"
    assert body["scorecard"]["score"] == 100

    detail = client.get(f"/documents/{document_id}").json()
    assert detail["content_type"] == "application/xml"
    assert detail["einvoice"]["profile"] == "XRECHNUNG 3.0"
    assert detail["einvoice"]["source"] == "standalone"
    assert {term["bt"] for term in detail["einvoice"]["business_terms"]} >= {
        "BT-1", "BT-2", "BT-10", "BT-27", "BT-31", "BT-34", "BT-49", "BT-112"
    }
    assert "Lesefassung des XML-Datensatzes" in detail["text_view"]["text"]
    summary = client.get("/documents").json()["items"][0]
    assert summary["einvoice_profile"] == "XRECHNUNG 3.0"


def test_hybride_pdf_upload(client: TestClient) -> None:
    document_id = _hybrid_id(client)
    detail = client.get(f"/documents/{document_id}").json()
    assert detail["einvoice"]["source"] == "embedded"
    assert detail["einvoice"]["attachment_name"] == "factur-x.xml"
    assert all(check["status"] == "match" for check in detail["einvoice"]["visual_check"])
    assert detail["page_count"] == 1


def test_hybride_pdf_mit_diskrepanz_ueber_api(client: TestClient) -> None:
    document_id = _hybrid_id(client, visual_override={"grand": Decimal("5812.00")})
    card = client.post(f"/documents/{document_id}/extract?wait=true").json()["scorecard"]
    primacy = next(c for t in card["tiles"] for c in t["checks"] if c["id"] == "xml_primacy")
    assert primacy["status"] == "warn" and primacy["deduction"] == 10
    assert card["score"] == 90


def test_xml_mit_dtd_wird_abgelehnt(client: TestClient) -> None:
    response = _upload(client, XXE_XML, "angriff.xml", "application/xml")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_einvoice"
    assert client.get("/documents").json()["total"] == 0


def test_xml_ohne_rechnung_wird_abgelehnt(client: TestClient) -> None:
    response = _upload(client, b"<?xml version='1.0'?><Bestellung xmlns='urn:x'/>", "bestellung.xml", "text/xml")
    assert response.status_code == 422
    assert "Keine EN-16931-Rechnung" in response.json()["error"]["message"]


def test_xml_mit_pdf_content_type_wird_abgelehnt(client: TestClient) -> None:
    response = _upload(client, build_ubl_invoice(), "rechnung.xml", "application/pdf")
    assert response.status_code == 415


def test_andere_endungen_bleiben_gesperrt(client: TestClient) -> None:
    response = _upload(client, b"irgendwas", "rechnung.docx", "application/octet-stream")
    assert response.status_code == 415
    assert ".xml" in response.json()["error"]["message"]


def test_batch_mit_pdf_und_xml(client: TestClient) -> None:
    response = client.post(
        "/documents/upload-batch",
        files=[
            ("files", ("rechnung.pdf", build_pdf([PLAIN_INVOICE]), "application/pdf")),
            ("files", ("xrechnung.xml", build_ubl_invoice(), "application/xml")),
            ("files", ("hybrid.pdf", build_hybrid_pdf(HYBRID_INVOICE), "application/pdf")),
            ("files", ("kaputt.xml", b"<nicht", "application/xml")),
        ],
    )
    body = response.json()
    assert (body["succeeded"], body["failed"]) == (3, 1)
    profiles = {item["filename"]: item.get("einvoice_profile") for item in body["items"] if item["ok"]}
    assert profiles == {"rechnung.pdf": None, "xrechnung.xml": "XRECHNUNG 3.0", "hybrid.pdf": "EN 16931 (COMFORT)"}


# ---------------------------------------------------------------------------
# Pruefzertifikat
# ---------------------------------------------------------------------------


def test_zertifikat_enthaelt_e_rechnungs_abschnitt(client: TestClient) -> None:
    document_id = _hybrid_id(client)
    client.post(f"/documents/{document_id}/extract?wait=true")
    html = client.get(f"/documents/{document_id}/report").text
    assert "E-Rechnung (EN 16931)" in html and "factur-x.xml" in html
    assert "keine KI-Inferenz" in html
    markdown = client.get(f"/documents/{document_id}/report", params={"format": "markdown"}).text
    assert "| BT-112 | Rechnungsgesamtbetrag (brutto) | 5.712,00 EUR |" in markdown
    report = client.get(f"/documents/{document_id}/report", params={"format": "json"}).json()
    assert report["inference"]["structured"] is True
    assert report["einvoice"]["profile"] == "EN 16931 (COMFORT)"


# ---------------------------------------------------------------------------
# Pruefdatenpaket (ZIP)
# ---------------------------------------------------------------------------


def _zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


def test_paket_erst_nach_analyse(client: TestClient) -> None:
    document_id = uploaded_document_id(client, build_pdf([PLAIN_INVOICE]))
    response = client.get(f"/api/documents/{document_id}/export/gobd")
    assert response.status_code == 409


def test_paket_hybride_rechnung(client: TestClient) -> None:
    document_id = _hybrid_id(client)
    client.post(f"/documents/{document_id}/extract?wait=true")
    response = client.get(f"/api/documents/{document_id}/export/gobd")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="Pruefdatenpaket_hybrid.zip"' in response.headers["content-disposition"]

    archive = _zip(response.content)
    assert archive.namelist() == [
        "original/hybrid.pdf", "factur-x.xml", "ledger_audit_trail.json", "audit_certificate.html",
        "verfahrensdokumentation.html", "manifest.json",
    ]
    assert archive.read("original/hybrid.pdf") == build_hybrid_pdf(HYBRID_INVOICE)
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["document"]["sha256"] == client.get(f"/documents/{document_id}").json()["sha256"]
    assert manifest["audit"]["einvoice_profile"] == "EN 16931 (COMFORT)"
    assert manifest["signature"]["algorithm"] == "Ed25519"
    assert "eIDAS" in manifest["legal_note"]

    ledger = json.loads(archive.read("ledger_audit_trail.json"))
    assert ledger["document_id"] == document_id and ledger["chain_verification"]["valid"] is True
    for entry in ledger["entries"]:
        content = {k: v for k, v in entry.items() if k not in {"seq", "entry_hash", "entry_hash_recomputed_ok"}}
        assert compute_entry_hash(content) == entry["entry_hash"]

    fingerprint = client.get("/api/audit/signing-key").json()["fingerprint"]
    result = verify_package(response.content, expected_fingerprint=fingerprint)
    assert result["valid"] is True, result


def test_paket_reine_pdf_ohne_xml(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction_response = {"doc_type": "invoice", "sender": "Muster GmbH", "total_amount": 1190}
    document_id = uploaded_document_id(client, build_pdf([PLAIN_INVOICE]), filename="Rechnung_März.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    response = client.get(f"/api/documents/{document_id}/export/gobd")
    names = _zip(response.content).namelist()
    assert names == [
        "original/Rechnung_März.pdf", "ledger_audit_trail.json", "audit_certificate.html",
        "verfahrensdokumentation.html", "manifest.json",
    ]
    # Umlaut im Dateinamen: ASCII-Fallback plus RFC 5987
    assert "filename*=UTF-8''Pruefdatenpaket_Rechnung_M%C3%A4rz.zip" in response.headers["content-disposition"]


def test_manipuliertes_paket_wird_erkannt(client: TestClient) -> None:
    document_id = _hybrid_id(client)
    client.post(f"/documents/{document_id}/extract?wait=true")
    original = client.get(f"/api/documents/{document_id}/export/gobd").content
    fingerprint = client.get("/api/audit/signing-key").json()["fingerprint"]

    def rebuild(change) -> bytes:
        source = _zip(original)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as target:
            for name in source.namelist():
                target.writestr(name, change(name, source.read(name)))
        return buffer.getvalue()

    # 1. XML-Datensatz veraendert -> Hash passt nicht mehr
    tampered = rebuild(lambda name, data: data.replace(b"5712.00", b"5812.00") if name == "factur-x.xml" else data)
    result = verify_package(tampered, expected_fingerprint=fingerprint)
    assert result["valid"] is False
    assert {item["path"]: item["ok"] for item in result["files"]}["factur-x.xml"] is False

    # 2. Manifest angepasst (Hash nachgezogen) -> Signatur bricht
    def forge(name: str, data: bytes) -> bytes:
        if name != "manifest.json":
            return data
        manifest = json.loads(data)
        manifest["audit"]["compliance_score"] = 55
        return json.dumps(manifest).encode()

    assert "Signatur ungueltig" in verify_package(rebuild(forge))["signature"]

    # 3. Fremder Schluessel -> Herkunft nicht belegt
    assert verify_package(original, expected_fingerprint="0000:0000")["valid"] is False


def test_paket_bei_fehlender_originaldatei(client: TestClient, settings) -> None:
    document_id = _hybrid_id(client)
    client.post(f"/documents/{document_id}/extract?wait=true")
    for file in settings.upload_path.glob(f"{document_id}.*"):
        file.unlink()
    response = client.get(f"/api/documents/{document_id}/export/gobd")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "original_missing"


def test_signaturschluessel_ist_stabil(client: TestClient, settings) -> None:
    first = client.get("/api/audit/signing-key").json()
    assert first["algorithm"] == "Ed25519" and len(first["fingerprint"].split(":")) == 8
    assert (settings.data_dir / ".signing.key").exists()
    assert client.get("/api/audit/signing-key").json() == first


# ---------------------------------------------------------------------------
# Musterdaten
# ---------------------------------------------------------------------------


def test_musterdaten_enthalten_zugferd_hybrid(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    items = {item["filename"]: item for item in full_client.post("/api/demo/seed").json()["items"]}
    hybrid = items["Rechnung_ZUGFeRD_Hybrid.pdf"]
    assert hybrid["status"] == "extracted" and hybrid["reference_audit"] is False
    detail = full_client.get(f"/documents/{hybrid['id']}").json()
    assert (detail["scorecard"]["score"], detail["scorecard"]["band"]) == (100, "green")
    assert detail["provider"] == "structured"
    assert detail["einvoice"]["profile"] == "EN 16931 (COMFORT)"


def test_copilot_musterantwort_fuer_hybride_musterrechnung(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    items = {item["filename"]: item for item in full_client.post("/api/demo/seed").json()["items"]}
    document_id = items["Rechnung_ZUGFeRD_Hybrid.pdf"]["id"]
    response = full_client.post(
        f"/documents/{document_id}/copilot", json={"question": "Welche Pflichtangaben fehlen in dieser Rechnung?"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reference"] is True and "factur-x.xml [Z. 18]" in body["answer"]


def test_copilot_ohne_musterantwort_fuer_fremde_e_rechnung(client: TestClient, fake_ollama: FakeOllama) -> None:
    # Gleicher Dateiname, anderer Inhalt: keine Musterantwort, sondern das Modell.
    pdf = build_hybrid_pdf(HYBRID_INVOICE, visual_override={"grand": Decimal("5812.00")})
    response = _upload(client, pdf, "Rechnung_ZUGFeRD_Hybrid.pdf", "application/pdf")
    document_id = response.json()["id"]
    client.post(f"/documents/{document_id}/extract?wait=true")
    answer = client.post(
        f"/documents/{document_id}/copilot", json={"question": "Welche Pflichtangaben fehlen in dieser Rechnung?"}
    ).json()
    assert answer["reference"] is False
