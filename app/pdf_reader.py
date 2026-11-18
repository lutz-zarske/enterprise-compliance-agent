"""PDF-Textextraktion auf Basis von pdfplumber (MIT-Lizenz).

Der Reader ist defensiv gebaut: Beschädigte, passwortgeschützte und
gescannte PDFs ohne Textlayer erzeugen jeweils eine eigene, klar benannte
Ausnahme.  Die API-Schicht kann daraus präzise HTTP-Antworten mit
Handlungshinweis erzeugen, statt einen generischen 500er zu liefern.

Bewusst *kein* OCR: Das Projekt ist Privacy-First und soll ohne
Systemabhängigkeiten (Tesseract, Poppler) lauffähig bleiben.  Gescannte
Dokumente werden erkannt und mit einem verständlichen Hinweis abgelehnt.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import anyio.to_thread
import pdfplumber

try:  # pdfminer.six wird von pdfplumber mitgeliefert.
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError
except ImportError:  # pragma: no cover - nur bei exotischen Installationen

    class PDFPasswordIncorrect(Exception):  # type: ignore[no-redef]
        """Platzhalter, falls pdfminer die Ausnahme nicht exportiert."""

    class PDFSyntaxError(Exception):  # type: ignore[no-redef]
        """Platzhalter, falls pdfminer die Ausnahme nicht exportiert."""


logger = logging.getLogger(__name__)

#: Magic Bytes eines PDF-Dokuments.
PDF_MAGIC = b"%PDF-"

#: Unterhalb dieser Zeichenzahl gilt ein Dokument als "ohne Textlayer".
MIN_TEXT_CHARS = 40

#: Maximale Seitenzahl, die verarbeitet wird (Schutz vor Ressourcenmissbrauch).
MAX_PAGES = 300


# ---------------------------------------------------------------------------
# Ausnahmen
# ---------------------------------------------------------------------------


class PdfReadError(Exception):
    """Basisklasse aller PDF-Lesefehler."""

    code = "pdf_read_error"
    hint: str | None = None


class InvalidPdfError(PdfReadError):
    """Die Datei ist kein lesbares PDF."""

    code = "invalid_pdf"
    hint = "Bitte eine unbeschädigte PDF-Datei hochladen."


class EncryptedPdfError(PdfReadError):
    """Das PDF ist passwortgeschützt."""

    code = "encrypted_pdf"
    hint = "Bitte den Kopierschutz entfernen und das Dokument erneut hochladen."


class NoTextLayerError(PdfReadError):
    """Das PDF enthält keinen maschinenlesbaren Text (vermutlich ein Scan)."""

    code = "no_text_layer"
    hint = (
        "Das Dokument enthält keinen Textlayer und ist vermutlich ein Scan. "
        "Bitte vorab per OCR (z. B. OCRmyPDF) in ein durchsuchbares PDF wandeln."
    )


# ---------------------------------------------------------------------------
# Ergebnisobjekt
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PdfExtraction:
    """Ergebnis einer erfolgreichen Textextraktion."""

    text: str
    page_count: int
    char_count: int
    pages_with_text: int
    truncated: bool = False

    @property
    def text_coverage(self) -> float:
        """Anteil der Seiten mit erkanntem Text - Indikator für Teilscans."""
        return self.pages_with_text / self.page_count if self.page_count else 0.0


# ---------------------------------------------------------------------------
# Extraktion
# ---------------------------------------------------------------------------

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")
_MULTI_SPACES = re.compile(r"[ \t]{2,}")


def normalize_text(text: str) -> str:
    """Vereinheitlicht Whitespace, ohne die Zeilenstruktur zu zerstören.

    Die Zeilenstruktur bleibt erhalten, weil Rechnungspositionen und
    Vertragsklauseln für das LLM sonst zu einer unlesbaren Textwurst
    verschmelzen.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ").replace("​", "")
    text = _MULTI_SPACES.sub(" ", text)
    text = _TRAILING_SPACES.sub("\n", text)
    text = _MULTI_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def looks_like_pdf(data: bytes) -> bool:
    """Prüft die Magic Bytes - unabhängig vom gemeldeten Content-Type."""
    return data[:1024].lstrip()[: len(PDF_MAGIC)] == PDF_MAGIC


def extract_text(data: bytes, *, max_pages: int = MAX_PAGES) -> PdfExtraction:
    """Extrahiert den Text eines PDFs aus dem Speicher.

    Raises:
        InvalidPdfError: Datei ist kein oder ein beschädigtes PDF.
        EncryptedPdfError: Datei ist passwortgeschützt.
        NoTextLayerError: Datei enthält praktisch keinen Text (Scan).
    """
    if not data:
        raise InvalidPdfError("Die hochgeladene Datei ist leer.")
    if not looks_like_pdf(data):
        raise InvalidPdfError(
            "Die Datei beginnt nicht mit der PDF-Signatur '%PDF-' und ist daher kein PDF."
        )

    pages: list[str] = []
    pages_with_text = 0
    truncated = False

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise InvalidPdfError("Das PDF enthält keine Seiten.")
            if total_pages > max_pages:
                truncated = True

            for index, page in enumerate(pdf.pages[:max_pages], start=1):
                try:
                    page_text = page.extract_text() or ""
                except Exception:  # noqa: BLE001 - eine defekte Seite darf nicht alles kippen
                    logger.warning("Seite %s konnte nicht gelesen werden.", index, exc_info=True)
                    page_text = ""
                finally:
                    # pdfplumber cached Zeichenobjekte je Seite - explizit freigeben.
                    page.flush_cache()

                if page_text.strip():
                    pages_with_text += 1
                pages.append(f"--- Seite {index} ---\n{page_text.strip()}")
    except PDFPasswordIncorrect as exc:
        raise EncryptedPdfError("Das PDF ist passwortgeschützt.") from exc
    except PDFSyntaxError as exc:
        raise InvalidPdfError(f"Das PDF ist strukturell fehlerhaft: {exc}") from exc
    except PdfReadError:
        raise
    except Exception as exc:  # noqa: BLE001 - pdfminer wirft sehr heterogene Fehler
        message = str(exc).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptedPdfError("Das PDF ist passwortgeschützt.") from exc
        raise InvalidPdfError(f"Das PDF konnte nicht gelesen werden: {exc}") from exc

    text = normalize_text("\n\n".join(pages))
    char_count = len(re.sub(r"--- Seite \d+ ---", "", text).strip())

    if char_count < MIN_TEXT_CHARS:
        raise NoTextLayerError(
            f"Es konnten nur {char_count} Zeichen extrahiert werden "
            f"(Mindestanforderung: {MIN_TEXT_CHARS})."
        )

    return PdfExtraction(
        text=text,
        page_count=total_pages,
        char_count=char_count,
        pages_with_text=pages_with_text,
        truncated=truncated,
    )


async def extract_text_async(data: bytes, *, max_pages: int = MAX_PAGES) -> PdfExtraction:
    """Async-Wrapper: pdfplumber ist CPU-gebunden und blockiert den Event-Loop."""
    return await anyio.to_thread.run_sync(lambda: extract_text(data, max_pages=max_pages))
