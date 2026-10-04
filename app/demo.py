"""Referenzdokumente fuer Live-Praesentationen (``POST /api/demo/seed``).

Drei bewusst konstruierte Faelle decken die drei Ampelfarben ab:

1. ``Rechnung_Gueltig_14UStG.pdf`` - alle Pflichtangaben, korrekte Mathematik.
   Erwartung: gruen, Score 100 (keine Abzuege nach Regelwerk 2026.1).
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


# ---------------------------------------------------------------------------
# Referenz-Audits: vorberechnete KI-Antworten fuer den Betrieb ohne Modell
# ---------------------------------------------------------------------------
#
# Ersetzt wird ausschliesslich die *Modellantwort* (Extraktion + AI-Act-/
# DSGVO-Audit).  Maskierungszwang, Regex-Zweitmeinung, Eskalationsregeln,
# Scorecard und Ledger-Eintrag laufen ueber denselben Codepfad wie bei einer
# echten Analyse.  Ergebnisse sind ueberall als Referenz-Audit gekennzeichnet
# (``model="reference-fixture"``, ``provider="reference"``).

#: Kennzeichnung in Datenbank, Ledger, UI und Zertifikat.
REFERENCE_MODEL = "reference-fixture"
REFERENCE_PROVIDER = "reference"

#: Siegel der gueltigen Musterrechnung - ausdruecklich keine echte Pruefung.
DEMO_AUDITOR = "Demo-Prüfer (Musterdaten)"
DEMO_SEAL_NOTE = (
    "Referenz-Siegel der Musterdaten. Es dokumentiert den Ablauf, nicht die "
    "Prüfung durch eine reale Person."
)

_NO_AI = {
    "describes_ai_system": False,
    "overall_risk_level": "not_applicable",
    "systems": [],
    "reasoning": "Das Dokument ist eine Rechnung über Waren bzw. Dienstleistungen und beschreibt kein KI-System im Sinne von Art. 3 Nr. 1.",
    "obligations": [],
}

REFERENCE_AUDITS: dict[str, dict[str, dict]] = {
    "Rechnung_Gueltig_14UStG.pdf": {
        "extraction": {
            "doc_type": "invoice",
            "sender": "Nordlicht IT-Services GmbH",
            "sender_address": "Hafenstraße 12, 20457 Hamburg",
            "recipient": "Brandt Maschinenbau AG",
            "recipient_address": "Industrieweg 7, 70565 Stuttgart",
            "sender_tax_number": "22/815/08150",
            "sender_vat_id": "DE287654321",
            "document_number": "RE-2025-0142",
            "document_date": "2025-03-14",
            "due_date": "2025-04-13",
            "service_period": "01.02.2025 - 28.02.2025",
            "items_description": "Managed-Security-Service (Pauschale Februar 2025) und 12 Stunden Incident-Response-Bereitschaft",
            "net_amount": "6000.00",
            "tax_rate": "19",
            "tax_amount": "1140.00",
            "total_amount": "7140.00",
            "currency": "EUR",
            "iban": "DE89370400440532013000",
            "summary": "Rechnung der Nordlicht IT-Services GmbH über Managed-Security-Leistungen im Februar 2025. Alle Pflichtangaben sind vorhanden, die Beträge sind rechnerisch korrekt.",
            "issues": [],
        },
        "audit": {
            "ai_act": _NO_AI,
            "gdpr": {
                "contains_personal_data": False,
                "findings": [],
                "risk_level": "none",
                "reasoning": "Das Dokument enthält ausschließlich Unternehmensdaten; die IBAN gehört einer juristischen Person.",
                "recommendations": [],
            },
        },
    },
    "Rechnung_Fehlerhaft_Steuerfalle.pdf": {
        "extraction": {
            "doc_type": "invoice",
            "sender": "Schnell & Billig Handels GmbH",
            "sender_address": "Am Markt 3, 04109 Leipzig",
            "recipient": "Brandt Maschinenbau AG",
            "recipient_address": "Industrieweg 7, 70565 Stuttgart",
            "document_number": "2025-77",
            "document_date": "2025-05-02",
            "items_description": "Büromöbel-Set Executive, 3 Stück",
            "net_amount": "4500.00",
            "tax_rate": "16",
            "tax_amount": "720.00",
            "total_amount": "5220.00",
            "currency": "EUR",
            "iban": "DE12345678901234567890",
            "summary": "Rechnung über drei Büromöbel-Sets. Steuernummer bzw. USt-IdNr. und Leistungsdatum fehlen, der Steuersatz von 16 % ist unzulässig und die IBAN besteht die Prüfziffernkontrolle nicht.",
            "issues": [
                "Weder Steuernummer noch USt-IdNr. des Ausstellers angegeben.",
                "Umsatzsteuersatz 16 % ist seit 01.01.2021 nicht mehr zulässig.",
                "Kein Liefer- bzw. Leistungsdatum angegeben.",
            ],
        },
        "audit": {
            "ai_act": _NO_AI,
            "gdpr": {
                "contains_personal_data": False,
                "findings": [],
                "risk_level": "none",
                "reasoning": "Keine personenbezogenen Daten erkannt.",
                "recommendations": [],
            },
        },
    },
    "KI_Recruiting_Dienstleistervertrag.pdf": {
        "extraction": {
            "doc_type": "contract",
            "sender": "TalentScreen AI GmbH",
            "recipient": "Enterprise Corp SE",
            "due_date": "2024-12-31",
            "total_amount": "45000.00",
            "currency": "EUR",
            "iban": "DE89370400440532013000",
            "summary": "Vertrag über das KI-System TalentAI, das Bewerberinnen und Bewerber automatisiert bewertet. Vergütung 45.000 EUR, fällig zum 31.12.2024.",
            "issues": ["Kein Nachweis einer Konformitätsbewertung bzw. CE-Kennzeichnung für das KI-System."],
        },
        "audit": {
            "ai_act": {
                "describes_ai_system": True,
                "overall_risk_level": "high",
                "systems": [
                    {
                        "name": "TalentAI",
                        "purpose": "Automatisierte Bewertung und Vorauswahl von Bewerberinnen und Bewerbern",
                        "risk_level": "high",
                        "annex_iii_categories": ["employment_and_worker_management"],
                        "evidence": "Das System TalentAI bewertet Bewerber automatisiert",
                        "confidence": 0.95,
                    }
                ],
                "reasoning": (
                    "TalentAI bewertet Bewerber automatisiert. Das fällt unter Anhang III Nr. 4 lit. a "
                    "(Einstellung und Auswahl natürlicher Personen) und ist nach Art. 6 Abs. 2 ein "
                    "Hochrisiko-KI-System. Die Ausnahme nach Art. 6 Abs. 3 greift nicht, weil eine "
                    "Bewertung von Bewerbern ein Profiling natürlicher Personen ist."
                ),
                "obligations": [
                    "Betreiberpflichten nach Art. 26: Einsatz gemäß Gebrauchsanweisung, menschliche Aufsicht, Aufbewahrung der Logs mindestens sechs Monate",
                    "Information der Beschäftigtenvertretung vor Inbetriebnahme (Art. 26 Abs. 7)",
                    "Nachweis der Konformitätsbewertung (Art. 43) und CE-Kennzeichnung (Art. 48) durch den Anbieter anfordern",
                    "Datenschutz-Folgenabschätzung nach Art. 35 DSGVO",
                ],
            },
            "gdpr": {
                "contains_personal_data": True,
                "findings": [
                    {
                        "category": "contact_data",
                        "masked_value": "datenschutz@talentscreen-ai.de",
                        "context": "Kontakt: datenschutz@talentscreen-ai.de",
                        "confidence": 0.9,
                    }
                ],
                "risk_level": "low",
                "reasoning": "Im Dokument selbst nur eine Funktionsadresse; das beschriebene System verarbeitet jedoch Bewerberdaten.",
                "recommendations": [
                    "Datenschutz-Folgenabschätzung (Art. 35 DSGVO) vor Einsatz durchführen",
                    "Auftragsverarbeitungsvertrag nach Art. 28 DSGVO mit dem Anbieter abschließen",
                ],
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Musterantworten des Compliance Copilots (ohne Sprachmodell)
# ---------------------------------------------------------------------------

#: Die drei Standardfragen, die das Frontend als Vorschlag anbietet.
STANDARD_QUESTIONS = (
    "Welche Pflichtangaben fehlen in dieser Rechnung?",
    "Warum stuft das System dieses PDF als Anhang III Nr. 4 ein?",
    "Wie muss die Rechnung korrigiert werden, um vorsteuerabzugsberechtigt zu sein?",
)

REFERENCE_ANSWERS: dict[str, tuple[str, str, str]] = {
    "Rechnung_Gueltig_14UStG.pdf": (
        "Keine. Alle Pflichtangaben nach § 14 Abs. 4 Satz 1 UStG sind vorhanden:\n"
        "- Name und Anschrift des Ausstellers [Z. 2] [Z. 3] und des Empfängers [Z. 5] [Z. 6] (Nr. 1)\n"
        "- Steuernummer und USt-IdNr. [Z. 4] (Nr. 2)\n"
        "- Ausstellungsdatum [Z. 8] und Rechnungsnummer [Z. 7] (Nr. 3 und 4)\n"
        "- Art und Umfang der Leistung [Z. 10] [Z. 11] und Leistungszeitraum [Z. 9] (Nr. 5 und 6)\n"
        "- Nettoentgelt, Steuersatz und Steuerbetrag [Z. 12] [Z. 13] (Nr. 7 und 8)\n"
        "Hinweis: Es handelt sich um ein reines PDF. Im inländischen B2B-Verkehr ist das seit 01.01.2025 eine "
        "„sonstige Rechnung“, die nur in der Übergangsfrist zulässig ist.",
        "Gar nicht. Das Dokument ist eine Rechnung über IT-Sicherheitsleistungen und beschreibt kein KI-System "
        "im Sinne von Art. 3 Nr. 1 VO (EU) 2024/1689. Eine Einstufung nach Anhang III Nr. 4 kommt deshalb nicht in Betracht.",
        "Eine Korrektur ist nicht nötig. Die Rechnung erfüllt § 14 Abs. 4 UStG, der Steuerbetrag von 1.140,00 EUR "
        "entspricht 19 % des Nettoentgelts [Z. 12] [Z. 13], und die IBAN besteht die Prüfziffernkontrolle [Z. 16]. "
        "Der Vorsteuerabzug nach § 15 Abs. 1 UStG ist aus formeller Sicht möglich.",
    ),
    "Rechnung_Fehlerhaft_Steuerfalle.pdf": (
        "Es fehlen zwei Pflichtangaben:\n"
        "- Steuernummer oder USt-IdNr. des Ausstellers – im Kopf [Z. 2] [Z. 3] steht keine "
        "(§ 14 Abs. 4 Satz 1 Nr. 2 UStG)\n"
        "- Zeitpunkt der Lieferung bzw. Leistung – nur das Rechnungsdatum [Z. 7] ist angegeben "
        "(§ 14 Abs. 4 Satz 1 Nr. 6 UStG)\n"
        "Zusätzlich fehlerhaft: Der Steuersatz von 16 % [Z. 10] ist seit 01.01.2021 nicht mehr zulässig "
        "(§ 12 Abs. 1 UStG), und die IBAN [Z. 12] besteht die Prüfziffernkontrolle (MOD-97) nicht.",
        "Gar nicht. Das Dokument ist eine Warenrechnung über Büromöbel [Z. 8] und beschreibt kein KI-System. "
        "Anhang III Nr. 4 VO (EU) 2024/1689 ist nicht einschlägig.",
        "Der Lieferant muss eine berichtigte Rechnung ausstellen:\n"
        "1. Steuernummer oder USt-IdNr. ergänzen (§ 14 Abs. 4 Satz 1 Nr. 2 UStG).\n"
        "2. Liefer- bzw. Leistungsdatum ergänzen (Nr. 6); die Angabe „Lieferdatum entspricht Rechnungsdatum“ genügt.\n"
        "3. Den Regelsteuersatz von 19 % ausweisen (§ 12 Abs. 1 UStG).\n"
        "4. Die Bankverbindung korrigieren – die IBAN [Z. 12] ist ungültig; vor Zahlung beim Lieferanten auf "
        "bekanntem Weg verifizieren.\n"
        "Bis zur Berichtigung ist der Vorsteuerabzug nach § 15 Abs. 1 UStG gefährdet. Selbst danach gilt: "
        "Ist zu wenig Steuer ausgewiesen, kann der Empfänger höchstens den ausgewiesenen Betrag (720,00 EUR [Z. 10]) "
        "als Vorsteuer abziehen, während der Lieferant die gesetzliche Steuer aus dem Bruttobetrag schuldet "
        "(19 % aus 5.220,00 EUR = 833,45 EUR). Keine Steuer- oder Rechtsberatung; im Zweifel Rücksprache mit der Steuerabteilung.",
    ),
    "KI_Recruiting_Dienstleistervertrag.pdf": (
        "Das Dokument ist ein Vertrag, keine Rechnung [Z. 2]. Die Pflichtangaben nach § 14 Abs. 4 UStG sind "
        "daher nicht einschlägig. Soll aus dem Vertrag abgerechnet werden, fehlen für eine ordnungsgemäße Rechnung "
        "unter anderem Rechnungsnummer, Ausstellungsdatum, Steuernummer bzw. USt-IdNr., Nettoentgelt, "
        "Steuersatz und Steuerbetrag; die Angabe „45000 EUR“ [Z. 5] ist kein ausreichender Steuerausweis.",
        "Weil das System TalentAI Bewerber automatisiert bewertet [Z. 4]. Das ist ein Anwendungsfall nach "
        "Anhang III Nr. 4 lit. a VO (EU) 2024/1689 (Einstellung und Auswahl natürlicher Personen) und damit "
        "nach Art. 6 Abs. 2 hochriskant. Die Ausnahme nach Art. 6 Abs. 3 greift nicht, weil die Bewertung von "
        "Bewerbern ein Profiling natürlicher Personen ist – solche Systeme gelten immer als hochriskant.\n"
        "Folgen für den Käufer als Betreiber (Art. 26): menschliche Aufsicht, Logs mindestens sechs Monate "
        "aufbewahren, Beschäftigtenvertretung vorab informieren. Vom Anbieter sind Konformitätsbewertung "
        "(Art. 43) und CE-Kennzeichnung (Art. 48) nachzuweisen; im Vertrag fehlt dazu jeder Hinweis. "
        "Nach der Änderung durch VO (EU) 2026/1744 gelten die Hochrisiko-Pflichten für Anhang III ab dem 02.12.2027.",
        "Das Dokument ist keine Rechnung, ein Vorsteuerabzug stützt sich erst auf die spätere Rechnung. Diese "
        "muss alle Angaben nach § 14 Abs. 4 UStG enthalten, insbesondere Rechnungsnummer, Ausstellungsdatum, "
        "Steuernummer bzw. USt-IdNr., Leistungszeitraum sowie Nettoentgelt, Steuersatz und Steuerbetrag "
        "getrennt. Der Betrag „45000 EUR“ [Z. 5] lässt offen, ob es sich um einen Netto- oder Bruttobetrag handelt.",
    ),
}


def normalize_question(question: str) -> str:
    """Toleranter Vergleich: Gross-/Kleinschreibung, Leerzeichen und Satzzeichen egal."""
    return "".join(char for char in question.casefold() if char.isalnum())


_STANDARD_KEYS = {normalize_question(question): index for index, question in enumerate(STANDARD_QUESTIONS)}


def reference_answer(filename: str, question: str) -> str | None:
    """Musterantwort fuer eine Standardfrage zu einem Musterdokument (sonst ``None``)."""
    index = _STANDARD_KEYS.get(normalize_question(question))
    answers = REFERENCE_ANSWERS.get(filename)
    if index is None or answers is None:
        return None
    return answers[index]
