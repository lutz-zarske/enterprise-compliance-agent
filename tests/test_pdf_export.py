"""PDF-Export von Prüfzertifikat und GoBD-Verfahrensdokumentation sowie Druck-CSS."""

from __future__ import annotations

import io
import re

import pypdfium2 as pdfium
from fastapi.testclient import TestClient

from app.demo import HYBRID_INVOICE, build_hybrid_pdf
from app.reporting import render_html
from tests.conftest import FakeOllama, build_pdf, uploaded_document_id


def _extract_pages(pdf_bytes: bytes) -> list[str]:
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        pages: list[str] = []
        for idx in range(len(doc)):
            textpage = doc[idx].get_textpage()
            try:
                pages.append(textpage.get_text_bounded())
            finally:
                textpage.close()
        return pages
    finally:
        doc.close()


def test_pruefzertifikat_pdf_hybride_rechnung_drei_sprachen(client: TestClient) -> None:
    document_id = uploaded_document_id(client, build_hybrid_pdf(HYBRID_INVOICE), filename="Rechnung_ZUGFeRD_Hybrid.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    assert (
        client.post(
            f"/documents/{document_id}/sign-off",
            json={"auditor_name": "Prüfteam A", "note": "Sichtprüfung bestanden.", "decision": "SEALED_APPROVED"},
        ).status_code
        == 200
    )

    for lang, prefix in [
        ("de", "Pruefzertifikat_"),
        ("en", "AuditCertificate_"),
        ("es", "CertificadoAuditoria_"),
    ]:
        response = client.get(f"/documents/{document_id}/report?format=pdf&lang={lang}")
        assert response.status_code == 200, (lang, response.text)
        assert response.headers["content-type"] == "application/pdf"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert re.search(rf'filename="{prefix}Rechnung_ZUGFeRD_Hybrid_\d{{4}}-\d{{2}}-\d{{2}}\.pdf"', disposition)
        assert response.content.startswith(b"%PDF-")

        pages = _extract_pages(response.content)
        assert len(pages) >= 2
        joined = "\n".join(pages)
        assert "Rechnung_ZUGFeRD_Hybrid.pdf" in pages[0]
        assert "100" in pages[0]
        assert "Prüfteam A" in pages[0] or "Prufteam A" in pages[0]
        assert "Sichtprüfung bestanden." in pages[0]
        # Seitenzahlen in den laufenden Fußzeilen
        assert f"1 / {len(pages)}" in pages[0] or f"von {len(pages)}" in pages[0] or f"of {len(pages)}" in pages[0] or f"de {len(pages)}" in pages[0]
        assert "EN 16931" in joined


def test_pruefzertifikat_pdf_unicode_dateiname_ohne_absturz(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction_response = {
        "doc_type": "invoice",
        "sender": "Łódź Sp. z o.o.",
        "total_amount": 1190,
        "currency": "EUR",
    }
    raw = build_pdf(
        [
            "Łódź Sp. z o.o., ul. Piotrkowska 1",
            "Rechnung Nr. 2026-Ł1 vom 01.10.2026",
            "Leistungsdatum: 30.09.2026",
            "Summe netto: 1.000,00 EUR",
            "zzgl. 19 % USt: 190,00 EUR",
            "Gesamtbetrag: 1.190,00 EUR",
        ]
    )
    document_id = uploaded_document_id(client, raw, filename="Rechnung_Łódź_2026.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200

    response = client.get(f"/documents/{document_id}/report?format=pdf&lang=de")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")
    assert "filename*=UTF-8''Pruefzertifikat_Rechnung_%C5%81%C3%B3d%C5%BA_2026_" in response.headers["content-disposition"]

    pages = _extract_pages(response.content)
    assert len(pages) >= 2
    assert "Rechnung_Lódz_2026.pdf" in pages[0] or "Rechnung_Łódź_2026.pdf" in pages[0]


def test_verfahrensdokumentation_pdf_drei_sprachen(client: TestClient) -> None:
    document_id = uploaded_document_id(client, build_hybrid_pdf(HYBRID_INVOICE), filename="Rechnung_Muster.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200

    for lang, prefix, expected in [
        ("de", "Verfahrensdokumentation_", "[vom Unternehmen zu ergänzen]"),
        ("en", "ProceduralDocumentation_", "[to be completed by company]"),
        ("es", "DocumentacionProcedimientos_", "[a completar por la empresa]"),
    ]:
        response = client.get(f"/api/documents/{document_id}/export/procedural-doc?format=pdf&lang={lang}")
        assert response.status_code == 200, (lang, response.text)
        assert response.headers["content-type"] == "application/pdf"
        assert re.search(rf'filename="{prefix}Rechnung_Muster_\d{{4}}-\d{{2}}-\d{{2}}\.pdf"', response.headers["content-disposition"])
        assert response.content.startswith(b"%PDF-")

        pages = _extract_pages(response.content)
        assert len(pages) >= 3
        joined = "\n".join(pages)
        assert "GoBD Rz. 153" in joined
        assert expected in joined


def test_html_zertifikat_kein_wortumbruch_in_normcodes_und_kein_fuehrender_strich(client: TestClient) -> None:
    document_id = uploaded_document_id(client, build_hybrid_pdf(HYBRID_INVOICE), filename="Rechnung_Test.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200

    html_response = client.get(f"/documents/{document_id}/report?format=html&lang=de")
    assert html_response.status_code == 200
    real_html = html_response.text
    assert '.mono { font-family: "JetBrains Mono"' in real_html
    assert ".mono {" in real_html
    mono_rule = real_html.split(".mono {", 1)[1].split("}", 1)[0]
    assert "word-break: break-all" not in mono_rule
    assert "word-break: break-all; overflow-wrap: anywhere;" in real_html
    assert ".keep-next { break-inside: avoid;" in real_html
    assert "<td class='small'>§ 5 Abs. 1 Nr. 1 ERechV; BR-DE-15</td>" in real_html
    assert '<div class="keep-next"><h2>' in real_html
    # Bei der 4. Rechenprüfung (detail=None, note vorhanden) darf kein führendes „–“ erscheinen
    assert "<td>–<div class=small>" not in real_html
    assert "<td><div class=small>Bei Rechnungen" in real_html

    report = client.get(f"/documents/{document_id}/report?format=json&lang=de").json()
    report["ustg_matrix"].append(
        {"label": "Testpunkt", "legal_reference": "BR-DE-15", "status": "pass", "detail": None, "note": "Hinweis ohne Detail"},
    )
    html = render_html(report, lang="de")
    assert "<td><div class=small>Hinweis ohne Detail</div></td>" in html
    assert "<td>–<div class=small>Hinweis ohne Detail</div></td>" not in html
