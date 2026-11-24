"""v2.8.6 – Feinschliff: bedingter AI-Act-Abschnitt im Prüfzertifikat und Scroll-Regression."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pypdfium2 as pdfium
from fastapi.testclient import TestClient

from tests.conftest import FakeOllama, build_pdf, uploaded_document_id

ROOT = Path(__file__).resolve().parents[1]

NO_AI_COMPLIANCE = {
    "ai_act": {
        "describes_ai_system": False,
        "overall_risk_level": "not_applicable",
        "systems": [],
        "reasoning": "Der Beleg betrifft Büromaterial; ein KI-System wird nicht beschrieben.",
        "obligations": [],
    },
    "gdpr": {
        "contains_personal_data": False,
        "findings": [],
        "risk_level": "none",
        "reasoning": "Keine personenbezogenen Daten.",
        "recommendations": [],
    },
}

NOT_APPLICABLE_LINE = {
    "de": "EU AI Act: nicht einschlägig – der Beleg beschreibt kein KI-System im Sinne von Art. 3 Nr. 1 KI-VO.",
    "en": "EU AI Act: not applicable – the document does not describe an AI system within the meaning of Art. 3(1) AI Act.",
    "es": "Reglamento de IA: no aplicable – el documento no describe ningún sistema de IA en el sentido del art. 3.1 del Reglamento de IA.",
}
AI_HEADING = {
    "de": "EU AI Act (VO (EU) 2024/1689)",
    "en": "EU AI Act (Reg. (EU) 2024/1689)",
    "es": "Reglamento de IA (Reg. (UE) 2024/1689)",
}


def _pdf_text(pdf_bytes: bytes) -> list[str]:
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        pages = []
        for index in range(len(doc)):
            textpage = doc[index].get_textpage()
            try:
                pages.append(" ".join(textpage.get_text_bounded().split()))
            finally:
                textpage.close()
        return pages
    finally:
        doc.close()


def _section_numbers(html: str) -> list[int]:
    return [int(n) for n in re.findall(r'<span class="no">(\d+)</span>', html)]


def _invoice(client: TestClient) -> str:
    raw = build_pdf(
        [
            [
                "Bürobedarf Muster GmbH, Hauptstraße 1, 10115 Berlin",
                "USt-IdNr.: DE123456789",
                "Rechnung Nr. 2026-0815 vom 01.11.2026",
                "Leistungsdatum: 31.10.2026",
                "Kopierpapier A4, 10 Pakete",
                "Summe netto: 100,00 EUR",
                "zzgl. 19 % USt: 19,00 EUR",
                "Gesamtbetrag: 119,00 EUR",
            ]
        ]
    )
    document_id = uploaded_document_id(client, raw, filename="Rechnung_Buero.pdf")
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    return document_id


def test_zertifikat_ohne_ki_system_ohne_ai_abschnitt_mit_zeile(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.compliance_response = NO_AI_COMPLIANCE
    document_id = _invoice(client)

    report = client.get(f"/documents/{document_id}/report?format=json&lang=de").json()
    assert report["ai_act"]["applicable"] is False

    for lang in ("de", "en", "es"):
        html = client.get(f"/documents/{document_id}/report?format=html&lang={lang}").text
        assert NOT_APPLICABLE_LINE[lang] in html.replace("&#x27;", "'")
        assert f"{AI_HEADING[lang]}</h2>" not in html
        numbers = _section_numbers(html)
        assert numbers == list(range(1, len(numbers) + 1)), numbers

        markdown = client.get(f"/documents/{document_id}/report?format=markdown&lang={lang}").text
        assert NOT_APPLICABLE_LINE[lang] in markdown
        assert f"## {AI_HEADING[lang]}" not in markdown

        pages = _pdf_text(client.get(f"/documents/{document_id}/report?format=pdf&lang={lang}").content)
        assert NOT_APPLICABLE_LINE[lang] in pages[0], pages[0]
        assert AI_HEADING[lang] not in " ".join(pages[1:])


def test_zertifikat_mit_ki_system_behaelt_ai_abschnitt(client: TestClient) -> None:
    document_id = _invoice(client)  # Standard-Antwort: Hochrisiko-KI (Anhang III)

    report = client.get(f"/documents/{document_id}/report?format=json&lang=de").json()
    assert report["ai_act"]["applicable"] is True

    html = client.get(f"/documents/{document_id}/report?format=html&lang=de").text
    assert f"{AI_HEADING['de']}</h2>" in html
    assert NOT_APPLICABLE_LINE["de"] not in html
    numbers = _section_numbers(html)
    assert numbers == list(range(1, len(numbers) + 1)), numbers

    markdown = client.get(f"/documents/{document_id}/report?format=markdown&lang=de").text
    assert f"## {AI_HEADING['de']}" in markdown

    pages = _pdf_text(client.get(f"/documents/{document_id}/report?format=pdf&lang=de").content)
    assert AI_HEADING["de"] in " ".join(pages[1:])
    assert NOT_APPLICABLE_LINE["de"] not in pages[0]


def test_altbericht_ohne_applicable_feld_richtet_sich_nach_der_stufe(client: TestClient, fake_ollama: FakeOllama) -> None:
    from app.pdf_export import render_report_pdf
    from app.reporting import render_html, render_markdown

    fake_ollama.compliance_response = NO_AI_COMPLIANCE
    document_id = _invoice(client)
    report = client.get(f"/documents/{document_id}/report?format=json&lang=de").json()
    del report["ai_act"]["applicable"]

    assert NOT_APPLICABLE_LINE["de"] in render_markdown(report, lang="de")
    assert f"{AI_HEADING['de']}</h2>" not in render_html(report, lang="de")
    assert NOT_APPLICABLE_LINE["de"] in _pdf_text(render_report_pdf(report, lang="de"))[0]


def test_scrollbereiche_sind_positioniert() -> None:
    """Absolut gesetzte Kinder (sr-only in Kopierknöpfen) dürfen die Seite nicht verlängern."""
    css = (ROOT / "frontend/src/app/globals.css").read_text(encoding="utf-8")
    block = re.search(r"\.scroll-area\s*\{([^}]*)\}", css)
    assert block and "position: relative" in block.group(1)

    ui = (ROOT / "frontend/src/components/ui.tsx").read_text(encoding="utf-8")
    copy_button = ui[ui.index("export function CopyButton"):]
    assert 'className="relative inline-flex' in copy_button[:2500]
