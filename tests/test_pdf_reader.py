"""Tests des PDF-Readers - insbesondere die Fehlerfälle."""

from __future__ import annotations

import pytest

from app.pdf_reader import (
    InvalidPdfError,
    NoTextLayerError,
    extract_text,
    looks_like_pdf,
    normalize_text,
)
from tests.conftest import build_pdf


def test_text_und_seitenzahl_werden_korrekt_ermittelt(invoice_pdf: bytes) -> None:
    result = extract_text(invoice_pdf)

    assert result.page_count == 1
    assert result.pages_with_text == 1
    assert result.text_coverage == 1.0
    assert result.char_count > 100
    assert "RE-2024-0815" in result.text
    assert "DE89370400440532013000" in result.text
    assert "--- Seite 1 ---" in result.text  # Seitenmarker fuer den Prompt


def test_mehrseitiges_pdf_behaelt_die_seitenstruktur() -> None:
    pdf = build_pdf([["Seite eins Inhalt", "Zeile zwei"], ["Seite zwei Inhalt"]])
    result = extract_text(pdf)

    assert result.page_count == 2
    assert result.pages_with_text == 2
    assert "--- Seite 1 ---" in result.text
    assert "--- Seite 2 ---" in result.text
    assert result.text.index("Seite eins Inhalt") < result.text.index("Seite zwei Inhalt")


def test_scan_ohne_textlayer_wird_mit_ocr_hinweis_abgelehnt(scanned_pdf: bytes) -> None:
    with pytest.raises(NoTextLayerError) as exc_info:
        extract_text(scanned_pdf)

    assert exc_info.value.code == "no_text_layer"
    assert "OCR" in (exc_info.value.hint or "")


def test_nicht_pdf_wird_anhand_der_signatur_erkannt() -> None:
    with pytest.raises(InvalidPdfError):
        extract_text(b"Das hier ist einfach nur Text und kein PDF.")

    with pytest.raises(InvalidPdfError):
        extract_text(b"")


def test_beschaedigtes_pdf_erzeugt_klaren_fehler() -> None:
    """Korrekte Signatur, danach Datenmüll."""
    with pytest.raises(InvalidPdfError):
        extract_text(b"%PDF-1.4\n" + b"\x00\xff" * 500)


def test_signaturpruefung_toleriert_fuehrenden_whitespace() -> None:
    assert looks_like_pdf(b"%PDF-1.7\n...") is True
    assert looks_like_pdf(b"\n  %PDF-1.4\n...") is True
    assert looks_like_pdf(b"PK\x03\x04") is False


def test_normalisierung_erhaelt_die_zeilenstruktur() -> None:
    """Zeilenumbrüche bleiben - sonst verschmelzen Rechnungspositionen."""
    raw = "Position 1:   100,00 EUR\r\n\r\n\r\n\r\nPosition 2:  50,00 EUR   \n"
    normalized = normalize_text(raw)

    assert normalized == "Position 1: 100,00 EUR\n\nPosition 2: 50,00 EUR"
