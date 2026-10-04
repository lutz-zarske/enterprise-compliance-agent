"""Referenzdokumente fuer Live-Praesentationen (``POST /api/demo/seed``).

Drei bewusst konstruierte Faelle decken die drei Ampelfarben ab:

1. ``Rechnung_Gueltig_14UStG.pdf`` - alle Pflichtangaben, korrekte Mathematik.
   Erwartung: gruen, Score 100 (keine Abzuege nach Regelwerk 2025.1).
2. ``Rechnung_Fehlerhaft_Steuerfalle.pdf`` - keine Steuernummer/USt-IdNr. (-20),
   unzulaessiger Steuersatz 16 % (-10), kein Leistungsdatum (-10), IBAN mit
   falscher Pruefziffer (-15).  Erwartung: rot, Score 45.
3. ``KI_Recruiting_Dienstleistervertrag.pdf`` - KI-gestuetztes Bewerber-
   Screening (Anhang III Nr. 4) ohne Konformitaetsnachweis.  Erwartung: rot,
   Score gedeckelt auf 59.

Die Erwartungswerte gelten fuer eine vollstaendige Extraktion; da Stufe 3 der
Pipeline ein LLM ist, kann ein schwaecheres Modell einzelne Felder verfehlen.
Die Regex-Gegenprobe in ``app/scoring.py`` faengt die meisten dieser Faelle ab.

Die PDFs entstehen zur Laufzeit ohne Zusatzbibliothek (gleiches Verfahren wie
in ``tests/conftest.py``).
"""

from __future__ import annotations

from app.config import BASE_DIR


def _escape_pdf_text(value: str) -> bytes:
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("cp1252", errors="replace")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Minimales, gueltiges PDF mit echtem Textlayer (Helvetica, WinAnsi)."""
    page_count = len(pages)
    font_obj = 3 + 2 * page_count
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(page_count))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")

    for index, lines in enumerate(pages):
        page_obj = 3 + 2 * index
        content_obj = page_obj + 1
        body = b"BT\n/F1 11 Tf\n50 790 Td\n16 TL\n"
        for line in lines:
            body += b"(" + _escape_pdf_text(line) + b") Tj\nT*\n"
        body += b"ET\n"
        objects[page_obj] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_obj} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        ).encode("ascii")
        objects[content_obj] = f"<< /Length {len(body)} >>\nstream\n".encode("ascii") + body + b"endstream"

    objects[font_obj] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("ascii") + objects[number] + b"\nendobj\n"
    xref_offset = len(out)
    total = max(objects) + 1
    out += f"xref\n0 {total}\n".encode("ascii") + b"0000000000 65535 f \n"
    for number in range(1, total):
        out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    return bytes(out)


VALID_INVOICE_LINES = [
    "Nordlicht IT-Services GmbH",
    "Hafenstraße 12, 20457 Hamburg",
    "Steuernummer: 22/815/08150   USt-IdNr.: DE287654321",
    "",
    "An: Brandt Maschinenbau AG",
    "Industrieweg 7, 70565 Stuttgart",
    "",
    "RECHNUNG Nr. RE-2025-0142",
    "Rechnungsdatum: 14.03.2025",
    "Leistungszeitraum: 01.02.2025 - 28.02.2025",
    "",
    "Pos. 1   Managed-Security-Service Februar 2025, 1 Monat (Pauschale)   4.200,00 EUR",
    "Pos. 2   Incident-Response-Bereitschaft, 12 Stunden zu je 150,00 EUR   1.800,00 EUR",
    "",
    "Nettobetrag: 6.000,00 EUR",
    "Umsatzsteuer 19 %: 1.140,00 EUR",
    "Gesamtbetrag (brutto): 7.140,00 EUR",
    "",
    "Zahlbar bis 13.04.2025 ohne Abzug.",
    "Bankverbindung: DE89 3704 0044 0532 0130 00",
]

FAULTY_INVOICE_LINES = [
    "Schnell & Billig Handels GmbH",
    "Am Markt 3, 04109 Leipzig",
    "",
    "An: Brandt Maschinenbau AG",
    "Industrieweg 7, 70565 Stuttgart",
    "",
    "RECHNUNG Nr. 2025-77",
    "Rechnungsdatum: 02.05.2025",
    "",
    "Pos. 1   Bueromoebel-Set Executive, 3 Stueck   4.500,00 EUR",
    "",
    "Nettobetrag: 4.500,00 EUR",
    "MwSt. 16 %: 720,00 EUR",
    "Gesamtbetrag: 5.220,00 EUR",
    "",
    "Bitte sofort ueberweisen auf: DE12 3456 7890 1234 5678 90",
]

RECRUITING_FALLBACK_LINES = [
    "VERTRAG UEBER KI-GESTUETZTES RECRUITING & BEWERBERMANAGEMENT",
    "Zwischen TalentScreen AI GmbH und Enterprise Corp SE.",
    "Das System TalentAI bewertet Bewerber automatisiert gemaess Anhang III Nr. 4 EU AI Act.",
    "Rechnungsbetrag: 45000 EUR faellig zum 31.12.2024.",
    "Bankverbindung: DE89370400440532013000.",
    "Kontakt: datenschutz@talentscreen-ai.de.",
]

SAMPLE_CONTRACT = BASE_DIR / "data" / "sample_talentai_contract.pdf"


def demo_documents() -> list[tuple[str, bytes]]:
    """Liefert (Dateiname, PDF-Bytes) der drei Referenzdokumente."""
    try:
        recruiting = SAMPLE_CONTRACT.read_bytes()
    except OSError:
        recruiting = build_pdf([RECRUITING_FALLBACK_LINES])
    return [
        ("Rechnung_Gueltig_14UStG.pdf", build_pdf([VALID_INVOICE_LINES])),
        ("Rechnung_Fehlerhaft_Steuerfalle.pdf", build_pdf([FAULTY_INVOICE_LINES])),
        ("KI_Recruiting_Dienstleistervertrag.pdf", recruiting),
    ]
