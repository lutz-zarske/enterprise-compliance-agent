"""Eingebettete Dateien aus PDF/A-3-Containern (ZUGFeRD, Factur-X, XRechnung).

Hybride Rechnungen tragen ihren XML-Datensatz als Dateianhang im PDF
(``/EmbeddedFiles``-Namensbaum, ``/AF``-Verweis).  Gelesen wird über
pypdfium2 (Apache-2.0/BSD, ohnehin Abhängigkeit von pdfplumber).

Der Reader ist defensiv: Ein defekter Anhang darf den Upload des PDFs nicht
verhindern - das Dokument fällt dann auf die reine Textanalyse zurück.
"""

from __future__ import annotations

import ctypes
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Dateinamen, unter denen die Standards ihren Datensatz einbetten.
#: factur-x.xml: Factur-X 1.0 / ZUGFeRD ab 2.1; zugferd-invoice.xml: ZUGFeRD 2.0;
#: xrechnung.xml: ZUGFeRD-Profil XRECHNUNG; ZUGFeRD-invoice.xml: ZUGFeRD 1.0.
EINVOICE_ATTACHMENT_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml")

#: Obergrenzen gegen Ressourcenmissbrauch durch präparierte PDFs.
MAX_ATTACHMENTS = 50
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

_XML_ROOT_HINT = re.compile(
    rb"CrossIndustryInvoice|CrossIndustryDocument|urn:oasis:names:specification:ubl:schema:xsd:(?:Invoice|CreditNote)-2"
)
_UNSAFE_ATTACHMENT_CHARS = re.compile(r"[^\w.\- ]+", re.UNICODE)


def _safe_attachment_name(raw_name: str | None, fallback: str) -> str:
    """Entfernt Pfadanteile und Traversal-Sequenzen aus eingebetteten Dateinamen."""
    cleaned = unicodedata.normalize("NFKC", raw_name or "").strip()
    cleaned = Path(cleaned.replace("\\", "/")).name
    cleaned = _UNSAFE_ATTACHMENT_CHARS.sub("_", cleaned).lstrip(".")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:160]


def _attachment_byte_length(attachment: object) -> int | None:
    """Liest die dekomprimierte Anhangsgröße, bevor pypdfium2 RAM allokiert."""
    try:
        import pypdfium2.raw as pdfium_c
    except ImportError:  # pragma: no cover
        return None
    n_bytes = ctypes.c_ulong()
    ok = pdfium_c.FPDFAttachment_GetFile(attachment, None, 0, ctypes.byref(n_bytes))
    return int(n_bytes.value) if ok else None


@dataclass(slots=True, frozen=True)
class EmbeddedFile:
    """Ein Dateianhang des PDFs."""

    name: str
    data: bytes


def list_embedded_files(pdf_bytes: bytes) -> list[EmbeddedFile]:
    """Liest alle Dateianhänge; zu große oder defekte Anhänge werden übersprungen."""
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover - pypdfium2 kommt mit pdfplumber
        logger.warning("pypdfium2 fehlt - eingebettete Dateien werden nicht gelesen.")
        return []

    files: list[EmbeddedFile] = []
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception:  # noqa: BLE001 - verschlüsselte/defekte PDFs behandelt pdf_reader
        return []
    try:
        count = min(document.count_attachments(), MAX_ATTACHMENTS)
        for index in range(count):
            try:
                attachment = document.get_attachment(index)
                name = _safe_attachment_name(attachment.get_name(), f"anhang_{index + 1}")
                declared_size = _attachment_byte_length(attachment)
                if declared_size is not None and declared_size > MAX_ATTACHMENT_BYTES:
                    logger.warning("PDF-Anhang %s vor Extraktion ignoriert (%s Bytes).", name, declared_size)
                    continue
                data = bytes(attachment.get_data())
            except Exception:  # noqa: BLE001 - einzelner defekter Anhang
                logger.warning("PDF-Anhang %s nicht lesbar.", index, exc_info=True)
                continue
            if len(data) > MAX_ATTACHMENT_BYTES:
                logger.warning("PDF-Anhang %s ignoriert (%s Bytes).", name, len(data))
                continue
            files.append(EmbeddedFile(name=name, data=data))
    finally:
        document.close()
    return files


def find_einvoice_attachment(pdf_bytes: bytes) -> EmbeddedFile | None:
    """Liefert den E-Rechnungs-Anhang: bekannter Dateiname zuerst, sonst XML mit passender Wurzel."""
    files = list_embedded_files(pdf_bytes)
    by_name = {file.name.casefold(): file for file in files}
    for name in EINVOICE_ATTACHMENT_NAMES:
        if name in by_name:
            return by_name[name]
    for file in files:
        if file.name.casefold().endswith(".xml") and _XML_ROOT_HINT.search(file.data[:4096]):
            return file
    return None
