"""Bericht, Human-Oversight-Siegel, Batch-Upload, Demo-Daten, KPIs, Copilot, Maskierungsstufen."""

from __future__ import annotations

import copy
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.redaction import build_text_view
from tests.conftest import (
    DEFAULT_EXTRACTION,
    RECRUITING_INVOICE_LINES,
    FakeOllama,
    build_pdf,
    uploaded_document_id,
)


def _analyzed(client: TestClient, pdf: bytes) -> str:
    document_id = uploaded_document_id(client, pdf)
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    return document_id


# ---------------------------------------------------------------------------
# Scorecard in der API
# ---------------------------------------------------------------------------


def test_extraktion_liefert_scorecard_und_detail_traegt_sie(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(full_client, invoice_pdf)
    body = full_client.post(f"/documents/{document_id}/extract?wait=true").json()

    card = body["scorecard"]
    assert 0 <= card["score"] <= 100
    assert [tile["key"] for tile in card["tiles"]] == ["formal", "regulatory", "privacy", "math"]
    # Recruiting-KI ohne Konformitaetsnachweis -> gedeckelt und gesperrt.
    assert card["score"] <= 59 and card["band"] == "red"
    assert card["release_blocked"] is True
    assert body["audit_entry_id"]

    detail = full_client.get(f"/documents/{document_id}").json()
    assert detail["scorecard"]["score"] == card["score"]
    summary = full_client.get("/documents").json()["items"][0]
    assert summary["compliance_score"] == card["score"]
    assert summary["score_band"] == "red"
    assert summary["pii_findings"] >= 2


# ---------------------------------------------------------------------------
# Bericht & Siegel
# ---------------------------------------------------------------------------


def test_bericht_vor_analyse_liefert_409(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(full_client, invoice_pdf)
    response = full_client.get(f"/documents/{document_id}/report")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "document_not_analyzed"
    assert full_client.post(f"/documents/{document_id}/sign-off",
                            json={"auditor_name": "Lutz Zarske"}).status_code == 409


def test_bericht_in_drei_formaten(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = _analyzed(full_client, invoice_pdf)

    report = full_client.get(f"/documents/{document_id}/report", params={"format": "json"}).json()
    assert report["audit_id"]
    assert report["ledger"]["chain_valid"] is True
    assert report["document"]["sha256"]
    assert len(report["ustg_matrix"]) >= 10
    assert "Anhang III Nr. 4" in " ".join(report["ai_act"]["annex_iii"])
    assert "Art. 14 Menschliche Aufsicht" in report["ai_act"]["article_references"]
    assert report["extraction"]["iban_masked"] == "DE89********3000"
    assert "DE89370400440532013000" not in str(report)

    markdown = full_client.get(f"/documents/{document_id}/report", params={"format": "markdown"})
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "# Compliance-Prüfzertifikat" in markdown.text
    assert "§ 14 Abs. 4 UStG" in markdown.text

    html = full_client.get(f"/documents/{document_id}/report")
    assert html.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in html.headers["content-security-policy"]
    assert "@page" in html.text and "ENTWURF" in html.text


def test_bericht_escaped_llm_freitext(
    full_client: TestClient, fake_ollama: FakeOllama, invoice_pdf: bytes
) -> None:
    malicious = copy.deepcopy(fake_ollama.compliance_response)
    malicious["ai_act"]["reasoning"] = "<script>alert('xss')</script>"
    fake_ollama.compliance_response = malicious
    document_id = _analyzed(full_client, invoice_pdf)

    html = full_client.get(f"/documents/{document_id}/report").text
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_sign_off_versiegelt_und_schreibt_ledger(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = _analyzed(full_client, invoice_pdf)

    response = full_client.post(
        f"/documents/{document_id}/sign-off",
        json={"auditor_name": "Lutz Zarske", "note": "Konformitaetsnachweis angefordert.",
              "decision": "SEALED_APPROVED"},
    )
    assert response.status_code == 200
    seal = response.json()["sign_off"]
    assert seal["status"] == "SEALED_APPROVED"
    assert seal["auditor_name"] == "Lutz Zarske"
    assert len(seal["ledger_entry_hash"]) == 64

    trail = full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"]
    assert [entry["event_type"] for entry in trail] == ["sign_off", "analysis"]
    assert trail[0]["details"]["auditor_name"] == "Lutz Zarske"
    assert full_client.get("/api/audit/verify").json()["valid"] is True

    html = full_client.get(f"/documents/{document_id}/report").text
    assert "GEPRÜFT &amp; FREIGEGEBEN" in html and "Lutz Zarske" in html
    assert full_client.get("/documents").json()["items"][0]["sealed"] is True

    # Neue Analyse = neuer Pruefgegenstand -> Siegel faellt, Historie bleibt.
    full_client.post(f"/documents/{document_id}/extract?wait=true")
    assert full_client.get(f"/documents/{document_id}").json()["sign_off"] is None
    assert len(full_client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"]) == 3


def test_sign_off_validiert_namen(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = _analyzed(full_client, invoice_pdf)
    assert full_client.post(f"/documents/{document_id}/sign-off", json={"auditor_name": "X"}).status_code == 422


# ---------------------------------------------------------------------------
# Batch, Demo, KPIs, Pins, Fortschritt
# ---------------------------------------------------------------------------


def test_batch_upload_mit_teilfehlern(full_client: TestClient, invoice_pdf: bytes, scanned_pdf: bytes) -> None:
    response = full_client.post(
        "/documents/upload-batch",
        files=[
            ("files", ("a.pdf", invoice_pdf, "application/pdf")),
            ("files", ("scan.pdf", scanned_pdf, "application/pdf")),
            ("files", ("notiz.txt", b"hallo", "text/plain")),
        ],
    )
    body = response.json()
    assert response.status_code == 200
    assert body["succeeded"] == 1 and body["failed"] == 2
    assert body["items"][0]["ok"] is True
    assert body["items"][1]["error"]["code"] == "no_text_layer"
    assert body["items"][2]["error"]["code"] == "invalid_upload"


def test_batch_limit(make_full_client: Callable[..., TestClient], invoice_pdf: bytes) -> None:
    client = make_full_client(max_batch_files=1)
    response = client.post(
        "/documents/upload-batch",
        files=[("files", ("a.pdf", invoice_pdf, "application/pdf"))] * 2,
    )
    assert response.status_code == 415
    assert "Maximal 1" in response.json()["error"]["message"]


def test_demo_seed_ist_idempotent(full_client: TestClient) -> None:
    first = full_client.post("/api/demo/seed").json()
    assert first["created"] == 4
    names = [item["filename"] for item in first["items"]]
    assert names == ["Rechnung_Gueltig_14UStG.pdf", "Rechnung_Fehlerhaft_Steuerfalle.pdf",
                     "KI_Recruiting_Dienstleistervertrag.pdf", "Rechnung_ZUGFeRD_Hybrid.pdf"]
    second = full_client.post("/api/demo/seed").json()
    assert second["created"] == 0
    assert [item["id"] for item in second["items"]] == [item["id"] for item in first["items"]]
    assert full_client.get("/documents").json()["total"] == 4


def test_demo_rechnungen_scoren_wie_dokumentiert(
    full_client: TestClient, fake_ollama: FakeOllama
) -> None:
    """Mit einer realistischen Extraktion landen die Referenzrechnungen bei 100 bzw. 45."""
    seeded = {item["filename"]: item["id"] for item in full_client.post("/api/demo/seed").json()["items"]}
    no_ai = {"ai_act": {"describes_ai_system": False, "overall_risk_level": "not_applicable"},
             "gdpr": {"findings": []}}
    fake_ollama.compliance_response = no_ai

    fake_ollama.extraction_response = {
        "doc_type": "invoice", "sender": "Nordlicht IT-Services GmbH", "recipient": "Brandt Maschinenbau AG",
        "document_number": "RE-2025-0142", "document_date": "2025-03-14", "total_amount": 7140,
        "iban": "DE89370400440532013000", "summary": "Rechnung ueber Managed-Security-Leistungen.",
    }
    good = full_client.post(f"/documents/{seeded['Rechnung_Gueltig_14UStG.pdf']}/extract?wait=true").json()
    assert good["scorecard"]["score"] == 100
    assert good["scorecard"]["release_recommendation"] == "Zur Auszahlung freigegeben"

    fake_ollama.extraction_response = {
        "doc_type": "invoice", "sender": "Schnell & Billig Handels GmbH", "recipient": "Brandt Maschinenbau AG",
        "document_number": "2025-77", "document_date": "2025-05-02", "total_amount": 5220,
        "iban": "DE12345678901234567890",
    }
    bad = full_client.post(f"/documents/{seeded['Rechnung_Fehlerhaft_Steuerfalle.pdf']}/extract?wait=true").json()
    assert bad["scorecard"]["score"] == 45
    assert bad["scorecard"]["band"] == "red"


def test_kpis_aggregieren_portfolio(full_client: TestClient, invoice_pdf: bytes, simple_pdf: bytes) -> None:
    empty = full_client.get("/api/dashboard/kpis").json()
    assert empty["documents_total"] == 0 and empty["average_score"] is None

    _analyzed(full_client, invoice_pdf)
    uploaded_document_id(full_client, simple_pdf)
    kpis = full_client.get("/api/dashboard/kpis").json()
    assert kpis["documents_total"] == 2
    assert kpis["documents_analyzed"] == 1
    assert kpis["high_risk_count"] == 1
    assert kpis["high_risk_quota"] == 100.0
    assert kpis["pii_elements_masked"] >= 2
    assert kpis["average_band"] == "red"


def test_pin_sortiert_nach_oben(full_client: TestClient, invoice_pdf: bytes, simple_pdf: bytes) -> None:
    older = uploaded_document_id(full_client, invoice_pdf)
    uploaded_document_id(full_client, simple_pdf)
    assert full_client.get("/documents").json()["items"][0]["id"] != older

    assert full_client.put(f"/documents/{older}/pin", json={"pinned": True}).json()["pinned"] is True
    items = full_client.get("/documents").json()["items"]
    assert items[0]["id"] == older and items[0]["pinned"] is True


def test_fortschritt_endpunkt(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(full_client, invoice_pdf)
    before = full_client.get(f"/documents/{document_id}/progress").json()
    assert [stage["state"] for stage in before["stages"]] == ["pending"] * 4
    assert [stage["key"] for stage in before["stages"]] == ["text_check", "pii_scan", "ustg_check", "ai_act"]

    full_client.post(f"/documents/{document_id}/extract?wait=true")
    after = full_client.get(f"/documents/{document_id}/progress").json()
    assert [stage["state"] for stage in after["stages"]] == ["done"] * 4


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def test_copilot_antwortet_geerdet(full_client: TestClient, fake_ollama: FakeOllama, invoice_pdf: bytes) -> None:
    document_id = _analyzed(full_client, invoice_pdf)
    response = full_client.post(
        f"/documents/{document_id}/copilot",
        json={"question": "Welche Pflichtangaben fehlen?",
              "history": [{"role": "user", "content": "Hallo"}, {"role": "assistant", "content": "Hallo!"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "[Z. 1]" in body["answer"]
    assert body["provider"] == "local"

    call = fake_ollama.calls[-1]
    assert "format" not in call  # Freitext, kein JSON-Zwang
    prompt = call["messages"][-1]["content"]
    assert "[Z. 3] RECHNUNG Nr. RE-2024-0815" in prompt
    assert "PRUEFERGEBNIS" in prompt and "compliance_score" in prompt
    assert [m["role"] for m in call["messages"]] == ["system", "user", "assistant", "user"]


def test_copilot_validiert_frage(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(full_client, invoice_pdf)
    assert full_client.post(f"/documents/{document_id}/copilot", json={"question": ""}).status_code == 422


# ---------------------------------------------------------------------------
# Maskierungsstufen
# ---------------------------------------------------------------------------

TEXT = "\n".join(RECRUITING_INVOICE_LINES)


def test_strict_schwaerzt_namen_firmen_betraege_daten() -> None:
    view = build_text_view(TEXT, "strict")
    text = str(view["text"])
    for secret in ("Petra Simon", "TalentMatch GmbH", "32.725,00", "15.03.2024", "DE89370400440532013000",
                   "Innovationsweg 12"):
        assert secret not in text
    assert "[NAME]" in text and "[FIRMA]" in text and "[BETRAG]" in text and "[DATUM]" in text


def test_standard_schwaerzt_identifikatoren_und_art9() -> None:
    view = build_text_view(TEXT, "standard")
    text = str(view["text"])
    assert "DE89370400440532013000" not in text and "DE89********3000" in text
    assert "p.simon@talentmatch.example" not in text
    assert "Attest" not in text and "[ART. 9]" in text
    # Namen und Betraege bleiben lesbar, sind aber markiert.
    assert "Petra Simon" in text and "32.725,00 EUR" in text
    person = next(span for span in view["spans"] if span["category"] == "person")
    assert person["masked"] is False
    assert text[person["start"]:person["end"]] == "Petra Simon"


def test_audit_only_markiert_ohne_schwaerzung() -> None:
    view = build_text_view(TEXT, "audit_only")
    assert view["text"] == TEXT
    assert view["spans"] and all(span["masked"] is False for span in view["spans"])
    iban = next(span for span in view["spans"] if span["category"] == "iban")
    assert TEXT[iban["start"]:iban["end"]] == "DE89370400440532013000"


def test_detailansicht_folgt_der_laufzeitstrenge(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(full_client, invoice_pdf)
    standard = full_client.get(f"/documents/{document_id}").json()
    assert "DE89370400440532013000" not in standard["text_preview"]
    assert standard["text_view"]["level"] == "standard"

    full_client.post("/api/settings", json={"pii_strictness": "audit_only"})
    audit = full_client.get(f"/documents/{document_id}").json()
    assert "DE89370400440532013000" in audit["text_view"]["text"]

    full_client.post("/api/settings", json={"pii_strictness": "strict"})
    strict = full_client.get(f"/documents/{document_id}").json()
    assert "Petra Simon" not in strict["text_view"]["text"]


def test_quelle_both_wenn_llm_und_regel_treffen(full_client: TestClient, invoice_pdf: bytes) -> None:
    document_id = _analyzed(full_client, invoice_pdf)
    view = full_client.get(f"/documents/{document_id}").json()["text_view"]
    iban = next(span for span in view["spans"] if span["category"] == "iban")
    assert iban["source"] == "both"


def test_unbekannte_extraktionsfelder_bleiben_tolerant() -> None:
    """Neue Pflichtfelder sind optional - alte Modellantworten bleiben gueltig."""
    from app.schemas import ExtractionResult

    legacy = ExtractionResult.model_validate(DEFAULT_EXTRACTION)
    assert legacy.sender_vat_id is None and legacy.tax_rate is None
    parsed = ExtractionResult.model_validate({"tax_rate": "0,19", "net_amount": "1.000,00"})
    assert str(parsed.tax_rate) == "19.00" and str(parsed.net_amount) == "1000.00"


def test_pdf_builder_der_demo_ist_lesbar() -> None:
    from app.demo import demo_documents
    from app.pdf_reader import extract_text

    for _name, data in demo_documents():
        assert extract_text(data).char_count > 100
    assert build_pdf([["x"]])
