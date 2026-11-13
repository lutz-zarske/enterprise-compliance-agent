"""End-to-End-Tests der fuenf Endpunkte gegen den gemockten Ollama-Dienst."""

from __future__ import annotations

import copy
from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import DEFAULT_COMPLIANCE, FakeOllama, uploaded_document_id

# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_meldet_datenbank_und_modell(client: TestClient) -> None:
    response = client.get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["database"]["dialect"] == "sqlite"
    assert body["database"]["documents"] == 0
    assert body["ollama"]["status"] == "ok"
    assert body["ollama"]["model"] == "qwen2.5:14b-instruct"
    assert body["ollama"]["model_available"] is True
    assert body["auth_enabled"] is False
    assert response.headers["X-Request-ID"]


def test_health_bleibt_erreichbar_wenn_ollama_ausfaellt(
    client: TestClient, fake_ollama: FakeOllama
) -> None:
    """Monitoring muss "Abhaengigkeit gestoert" von "Anwendung tot" unterscheiden."""
    fake_ollama.offline = True
    body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["database"]["status"] == "ok"
    assert body["ollama"]["status"] == "unavailable"


def test_health_meldet_fehlendes_modell_als_degraded(
    client: TestClient, fake_ollama: FakeOllama
) -> None:
    fake_ollama.models = ["llama3:8b"]
    body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["ollama"]["model_available"] is False
    assert "nicht installiert" in body["ollama"]["detail"]


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------


def test_upload_legt_dokument_mit_metadaten_an(client: TestClient, invoice_pdf: bytes) -> None:
    response = client.post(
        "/documents/upload",
        files={"file": ("Rechnung 03/2024.pdf", invoice_pdf, "application/pdf")},
    )
    body = response.json()

    assert response.status_code == 201
    assert body["status"] == "uploaded"
    assert body["page_count"] == 1
    assert body["char_count"] > 100
    assert len(body["sha256"]) == 64
    assert body["duplicate_of"] is None
    assert "/" not in body["filename"]  # Dateiname wurde entschaerft


def test_upload_erkennt_identische_datei_als_duplikat(
    client: TestClient, invoice_pdf: bytes
) -> None:
    first = uploaded_document_id(client, invoice_pdf)
    second = client.post(
        "/documents/upload", files={"file": ("kopie.pdf", invoice_pdf, "application/pdf")}
    ).json()

    assert second["duplicate_of"] == first
    assert second["id"] != first  # Ablage erfolgt trotzdem, Entscheidung liegt beim Aufrufer


def test_upload_lehnt_nicht_pdf_ab(client: TestClient) -> None:
    response = client.post(
        "/documents/upload", files={"file": ("notizen.txt", b"kein pdf", "text/plain")}
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_upload"


def test_upload_lehnt_getarnte_datei_anhand_der_signatur_ab(client: TestClient) -> None:
    """Richtige Endung, richtiger Content-Type - aber kein PDF-Inhalt."""
    response = client.post(
        "/documents/upload",
        files={"file": ("angeblich.pdf", b"PK\x03\x04 in Wahrheit ein ZIP", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pdf"


def test_upload_lehnt_scan_ohne_textlayer_mit_ocr_hinweis_ab(
    client: TestClient, scanned_pdf: bytes
) -> None:
    response = client.post(
        "/documents/upload", files={"file": ("scan.pdf", scanned_pdf, "application/pdf")}
    )
    error = response.json()["error"]

    assert response.status_code == 422
    assert error["code"] == "no_text_layer"
    assert "OCR" in error["hint"]


def test_upload_lehnt_zu_grosse_datei_ab(
    make_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    small_limit_client = make_client(max_upload_bytes=1024)
    response = small_limit_client.post(
        "/documents/upload", files={"file": ("gross.pdf", invoice_pdf, "application/pdf")}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


# ---------------------------------------------------------------------------
# POST /documents/{id}/extract
# ---------------------------------------------------------------------------


def test_extraktion_liefert_strukturierte_daten_und_compliance_audit(
    client: TestClient, invoice_pdf: bytes
) -> None:
    document_id = uploaded_document_id(client, invoice_pdf)
    response = client.post(f"/documents/{document_id}/extract?wait=true")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "extracted"
    assert body["model"] == "qwen2.5:14b-instruct"

    extraction = body["extraction"]
    assert extraction["doc_type"] == "invoice"
    assert extraction["sender"] == "TalentMatch GmbH"
    assert extraction["document_date"] == "2024-03-15"
    assert extraction["total_amount"] == "32725.00"
    assert extraction["currency"] == "EUR"
    assert extraction["iban_valid"] is True

    compliance = body["compliance"]
    # Das Modell hatte "limited" geliefert - die Anhang-III-Regel stuft hoch.
    assert compliance["ai_act"]["overall_risk_level"] == "high"
    assert compliance["ai_act"]["is_high_risk"] is True
    assert "Automatische Korrektur" in compliance["ai_act"]["reasoning"]
    assert compliance["ai_act"]["systems"][0]["annex_iii_categories"] == [
        "employment_and_worker_management"
    ]
    assert "Anhang III Nr. 4" in compliance["ai_act"]["systems"][0]["annex_iii_labels"][0]
    assert compliance["headline"].startswith("EU AI Act: Hochrisiko")


def test_pii_wird_nur_maskiert_persistiert(client: TestClient, invoice_pdf: bytes) -> None:
    """Kernversprechen des Projekts: keine Klartext-PII in der Datenbank."""
    document_id = uploaded_document_id(client, invoice_pdf)
    client.post(f"/documents/{document_id}/extract?wait=true")

    detail = client.get(f"/documents/{document_id}").json()
    gdpr = detail["compliance"]["gdpr"]
    serialized = str(gdpr)

    assert "DE89370400440532013000" not in serialized
    assert "DE89********3000" in serialized
    assert "p.simon@talentmatch.example" not in serialized

    # Gesundheitsdaten heben die Risikostufe an, obwohl das Modell "low" sagte.
    assert gdpr["risk_level"] == "high"
    assert gdpr["contains_special_categories"] is True

    # Regel- und Modellbefund zum selben Konto wurden zusammengefuehrt.
    bank = [f for f in gdpr["findings"] if f["category"] == "bank_account"]
    assert len(bank) == 1
    assert bank[0]["source"] == "both"


def test_extraktion_ergaenzt_fehlende_pflichtangaben(
    client: TestClient, simple_pdf: bytes, fake_ollama: FakeOllama
) -> None:
    """Deterministische Nachkontrolle nach Paragraf 14 UStG."""
    fake_ollama.extraction_response = {
        "doc_type": "invoice",
        "sender": "Bueromarkt Nord GmbH",
        "document_number": None,
        "document_date": None,
        "total_amount": "119,00",
        "currency": "EUR",
        "iban": "DE89370400440532013001",  # falsche Pruefsumme
        "summary": "Rechnung ueber Bueromaterial.",
        "issues": [],
    }
    fake_ollama.compliance_response = {
        "ai_act": {"describes_ai_system": False, "overall_risk_level": "not_applicable"},
        "gdpr": {"contains_personal_data": False, "risk_level": "none"},
    }

    document_id = uploaded_document_id(client, simple_pdf)
    issues = client.post(f"/documents/{document_id}/extract?wait=true").json()["extraction"]["issues"]

    assert any("Rechnungsnummer" in issue for issue in issues)
    assert any("Ausstellungsdatum" in issue for issue in issues)
    assert any("MOD-97" in issue for issue in issues)


def test_extraktion_ohne_ki_bezug_bleibt_bei_not_applicable(
    client: TestClient, simple_pdf: bytes, fake_ollama: FakeOllama
) -> None:
    fake_ollama.compliance_response = {
        "ai_act": {"describes_ai_system": False, "overall_risk_level": "not_applicable"},
        "gdpr": {"contains_personal_data": False, "risk_level": "none"},
    }

    document_id = uploaded_document_id(client, simple_pdf)
    compliance = client.post(f"/documents/{document_id}/extract?wait=true").json()["compliance"]

    assert compliance["ai_act"]["overall_risk_level"] == "not_applicable"
    assert compliance["ai_act"]["is_high_risk"] is False


def test_extraktion_ohne_regelwerk_fallback_meldet_ollama_ausfall_als_503(
    make_client: Callable[..., TestClient], invoice_pdf: bytes, fake_ollama: FakeOllama
) -> None:
    client = make_client(heuristic_fallback=False)
    document_id = uploaded_document_id(client, invoice_pdf)
    fake_ollama.offline = True

    response = client.post(f"/documents/{document_id}/extract?wait=true")
    error = response.json()["error"]

    assert response.status_code == 503
    assert error["code"] == "ollama_unavailable"
    assert "ollama serve" in error["hint"]

    # Der Fehler ist am Dokument dokumentiert - verstaendlich, ohne Klassennamen.
    detail = client.get(f"/documents/{document_id}").json()
    assert detail["status"] == "failed"
    assert "nicht erreichbar" in detail["error"]
    assert "Error" not in detail["error"]


def test_extraktion_ohne_modell_schliesst_mit_regelwerk_ab(
    client: TestClient, invoice_pdf: bytes, fake_ollama: FakeOllama
) -> None:
    """Zero-Failure: Faellt jede KI-Stufe aus, liefert das Regelwerk ein valides, gekennzeichnetes Ergebnis."""
    document_id = uploaded_document_id(client, invoice_pdf)
    fake_ollama.offline = True

    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "heuristic"
    assert body["compliance"]["heuristic"] is True
    assert "nicht erreichbar" in body["compliance"]["fallback_reason"]
    # Recruiting-KI im Beleg: konservativ Hochrisiko (Anhang III Nr. 4), Score gedeckelt.
    assert body["compliance"]["ai_act"]["overall_risk_level"] == "high"
    assert body["scorecard"]["score"] <= 59
    assert body["extraction"]["document_number"] == "RE-2024-0815"
    assert body["extraction"]["iban"] == "DE89370400440532013000"
    assert body["compliance"]["gdpr"]["contains_special_categories"] is True  # Attest -> Art. 9

    entry = client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"][0]
    assert entry["event_type"] == "analysis"
    assert entry["details"]["heuristic_fallback"] is True
    assert entry["result_summary"].startswith("Regelbasiertes Referenz-Audit")


def test_extraktion_ist_wiederholbar(
    client: TestClient, invoice_pdf: bytes, fake_ollama: FakeOllama
) -> None:
    document_id = uploaded_document_id(client, invoice_pdf)
    client.post(f"/documents/{document_id}/extract?wait=true")

    updated = copy.deepcopy(DEFAULT_COMPLIANCE)
    updated["ai_act"]["systems"][0]["annex_iii_categories"] = ["critical_infrastructure"]
    fake_ollama.compliance_response = updated

    second = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert second["compliance"]["ai_act"]["systems"][0]["annex_iii_categories"] == [
        "critical_infrastructure"
    ]


# ---------------------------------------------------------------------------
# GET /documents und GET /documents/{id}
# ---------------------------------------------------------------------------


def test_uebersicht_zeigt_compliance_kennzahlen_je_zeile(
    client: TestClient, invoice_pdf: bytes, simple_pdf: bytes
) -> None:
    extracted_id = uploaded_document_id(client, invoice_pdf)
    client.post(f"/documents/{extracted_id}/extract?wait=true")
    uploaded_document_id(client, simple_pdf, filename="klein.pdf")

    body = client.get("/documents").json()
    rows = {row["id"]: row for row in body["items"]}

    assert body["total"] == 2
    assert body["limit"] == 50 and body["offset"] == 0
    assert rows[extracted_id]["doc_type"] == "invoice"
    assert rows[extracted_id]["ai_act_risk_level"] == "high"
    assert rows[extracted_id]["gdpr_risk_level"] == "high"
    assert rows[extracted_id]["contains_special_categories"] is True

    # Noch nicht ausgewertete Dokumente erscheinen mit leeren Kennzahlen.
    pending = [row for row in body["items"] if row["id"] != extracted_id][0]
    assert pending["status"] == "uploaded"
    assert pending["ai_act_risk_level"] is None


def test_uebersicht_filtert_und_blaettert(client: TestClient, invoice_pdf: bytes) -> None:
    first = uploaded_document_id(client, invoice_pdf)
    client.post(f"/documents/{first}/extract?wait=true")
    uploaded_document_id(client, build_second_pdf(), filename="zweite.pdf")

    filtered = client.get("/documents", params={"status": "extracted"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == first

    paged = client.get("/documents", params={"limit": 1, "offset": 1}).json()
    assert len(paged["items"]) == 1
    assert paged["total"] == 2


def test_detailansicht_enthaelt_textvorschau_und_pruefsumme(
    client: TestClient, invoice_pdf: bytes
) -> None:
    document_id = uploaded_document_id(client, invoice_pdf)
    detail = client.get(f"/documents/{document_id}").json()

    assert detail["id"] == document_id
    assert detail["content_type"] == "application/pdf"
    assert len(detail["sha256"]) == 64
    assert "RE-2024-0815" in detail["text_preview"]
    assert detail["extraction"] is None  # noch nicht ausgewertet
    assert detail["compliance"] is None


def test_unbekannte_id_liefert_404_im_einheitlichen_fehlerformat(client: TestClient) -> None:
    for method, path in (
        ("get", "/documents/gibt-es-nicht"),
        ("post", "/documents/gibt-es-nicht/extract?wait=true"),
    ):
        response = getattr(client, method)(path)
        error = response.json()["error"]

        assert response.status_code == 404
        assert error["code"] == "document_not_found"
        assert "GET /documents" in error["hint"]


def test_ungueltige_parameter_liefern_422_im_einheitlichen_fehlerformat(
    client: TestClient,
) -> None:
    response = client.get("/documents", params={"limit": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Authentifizierung
# ---------------------------------------------------------------------------


def test_api_key_schuetzt_dokumentendpunkte(
    make_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    secured = make_client(api_key="streng-geheim")

    unauthorized = secured.get("/documents")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    assert secured.get("/documents", headers={"X-API-Key": "falsch"}).status_code == 401

    authorized = secured.get("/documents", headers={"X-API-Key": "streng-geheim"})
    assert authorized.status_code == 200

    # /health bleibt bewusst offen, damit Monitoring ohne Secret funktioniert.
    health = secured.get("/health")
    assert health.status_code == 200
    assert health.json()["auth_enabled"] is True


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_openapi_dokumentiert_alle_fuenf_endpunkte(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    # Seit v2.0 kommen weitere Endpunkte hinzu; die fuenf Kernendpunkte
    # muessen unveraendert dokumentiert bleiben.
    assert set(schema["paths"]) >= {
        "/health",
        "/documents/upload",
        "/documents/{document_id}/extract",
        "/documents",
        "/documents/{document_id}",
    }
    upload = schema["paths"]["/documents/upload"]["post"]
    assert "413" in upload["responses"] and "415" in upload["responses"]
    assert schema["components"]["schemas"]["ErrorResponse"]


def build_second_pdf() -> bytes:
    """Zweites, inhaltlich abweichendes PDF (andere Pruefsumme)."""
    from tests.conftest import build_pdf

    return build_pdf([["Mietvertrag Nr. MV-2024-77", "Monatsmiete: 1.450,00 EUR"]])
