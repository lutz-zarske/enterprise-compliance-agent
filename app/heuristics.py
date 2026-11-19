"""Regelbasiertes Referenz-Audit: Stufe 5 der Kaskade ("Zero-Failure-Garantie").

Scheitern alle KI-Stufen an Überlast, Ausfall, Zeitüberschreitung oder dem
Tagesbudget, schließt dieses Modul die Prüfung trotzdem regulär ab - mit
denselben deterministischen Kontrollen wie jeder Live-Lauf (Paragraf-14-Katalog,
IBAN-Prüfsumme, Regex-PII-Scanner, Eskalationsregeln, Scorecard, Ledger).

Ehrliche Grenzen: Die Felder werden per Mustererkennung gelesen, nicht
verstanden.  Das Ergebnis ist deshalb in Oberfläche, Zertifikat und Ledger
ausdrücklich als "Regelbasiertes Referenz-Audit - KI nicht verfügbar"
gekennzeichnet; die Einstufung nach dem EU AI Act ist konservativ (lieber ein
Hochrisiko-Hinweis zu viel als einer zu wenig) und durch eine Prüfperson zu
bestätigen oder zu übersteuern (Art. 14).
"""

from __future__ import annotations

import re
from typing import Any

from app.llm import ComplianceAuditPayload
from app.schemas import AnnexIIICategory, DocType, ExtractionResult
from app.scoring import RULESET_VERSION, analyze_text, position_lines

#: Kennung im Ledger, in der Datenbank und in der Oberfläche.
HEURISTIC_PROVIDER = "heuristic"
HEURISTIC_MODEL = f"regelwerk-{RULESET_VERSION}"
HEURISTIC_LABEL = "Regelbasiertes Referenz-Audit – KI nicht verfügbar"

_DOC_NUMBER = re.compile(
    r"(?:rechnungs?|beleg|vertrags?|angebots?|auftrags?|invoice)[\s-]*(?:nr\.?|nummer|no\.?|#)\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9/\-_.]{1,40})",
    re.IGNORECASE,
)
_DATE = r"(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})"
_DOC_DATE = re.compile(
    rf"(?:rechnungsdatum|belegdatum|ausstellungsdatum|datum|vom|von|invoice\s+date|issue\s+date|issued\s+at|"
    rf"date)\s*:?\s*{_DATE}",
    re.IGNORECASE,
)
_DUE_DATE = re.compile(rf"(?:f(?:ä|ae)llig(?:\s+am|keit)?|zahlbar bis|zahlungsziel)\s*:?\s*{_DATE}", re.IGNORECASE)
_SERVICE_DATE = re.compile(
    rf"(?:(?:leistungs|liefer)(?:datum|tag)|date\s+of\s+(?:delivery|supply|service)|delivery\s+date)\s*:?\s*{_DATE}",
    re.IGNORECASE,
)
#: Adresszeilen: Straße mit Hausnummer bzw. Postleitzahl mit Ort (auch ohne Leerzeichen, „88802Spielkreis“).
_STREET_LINE = re.compile(
    r"[A-ZÄÖÜ][a-zäöüß\-]+(?:straße|strasse|str\.|weg|allee|platz|gasse|ring|damm|ufer|chaussee)\s+\d+"
    r"|^\d{5}\s*[A-ZÄÖÜ][a-zäöüß]+"
)
_CONTACT_LINE = re.compile(r"fon|fax|tel|phone|mail|@|http|www\.|kunden|customer|\d{3,}", re.IGNORECASE)
_SERVICE_PERIOD = re.compile(r"(?:(?:leistungs|liefer)zeitraum|aufenthalt)\s*:?\s*(.{4,80})", re.IGNORECASE)
_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?)\b")
_VAT_ID = re.compile(r"\b(DE\s?\d{9}|ATU\d{8})\b")
_TAX_NUMBER = re.compile(r"\b(\d{2,3}/\d{3,4}/\d{4,5})\b")
_RECIPIENT = re.compile(r"^(?:empf(?:ä|ae)nger|an|rechnungsempf(?:ä|ae)nger|kunde)\s*:\s*(.+)$", re.IGNORECASE)

_KIND = (
    (DocType.REMINDER, re.compile(r"\bmahnung\b|zahlungserinnerung", re.IGNORECASE)),
    (DocType.INVOICE, re.compile(r"\brechnung\b|\binvoice\b", re.IGNORECASE)),
    (DocType.OFFER, re.compile(r"\bangebot\b", re.IGNORECASE)),
    (DocType.CONTRACT, re.compile(r"\bvertrag\b|vereinbarung|\blizenz", re.IGNORECASE)),
)
#: Belege ohne das Wort „Rechnung“: Quittung, Kassenbon, Bewirtungs- oder Kleinbetragsbeleg, Gutschrift.
_RECEIPT = re.compile(
    r"\bquittung\b|kassen(?:bon|beleg|zettel)|bewirtung|\bgutschrift\b|rechnungskorrektur|\bbeleg\b|\bbon\b",
    re.IGNORECASE,
)
_TAX_HINT = re.compile(r"\b(?:ust|mwst|umsatzsteuer|mehrwertsteuer)\b", re.IGNORECASE)

#: Hinweise auf ein KI-System im Sinne von Art. 3 Nr. 1 VO (EU) 2024/1689.
_AI_SYSTEM = re.compile(
    r"\bKI\b|\bKI-|k(?:ü|ue)nstliche[nr]?\s+intelligenz|machine[\s-]learning|maschinelle[sn]?\s+lernen|"
    r"neuronale[sn]?\s+netz|\bAI\b|sprachmodell|\bLLM\b|chatbot|algorithmisch|automatisierte\s+entscheidung|"
    r"scoring|gesichtserkennung|emotionserkennung|biometrische",
    re.IGNORECASE,
)
_TRANSPARENCY = re.compile(r"chatbot|deepfake|synthetisch|generative", re.IGNORECASE)
#: Anhang-III-Indikatoren (konservativ: ein Treffer genügt für den Hochrisiko-Hinweis).
_ANNEX_III: tuple[tuple[AnnexIIICategory, re.Pattern[str]], ...] = (
    (AnnexIIICategory.EMPLOYMENT, re.compile(
        r"bewerb|recruiting|personalauswahl|vorauswahl|lebensl(?:ä|ae)uf|\bCV\b|leistungsbewertung|"
        r"bef(?:ö|oe)rderung|k(?:ü|ue)ndigung|mitarbeiter(?:ü|ue)berwachung", re.IGNORECASE)),
    (AnnexIIICategory.ESSENTIAL_SERVICES, re.compile(
        r"bonit(?:ä|ae)t|kreditw(?:ü|ue)rdigkeit|kredit-?scoring|versicherungsrisiko|sozialleistung",
        re.IGNORECASE)),
    (AnnexIIICategory.CRITICAL_INFRASTRUCTURE, re.compile(
        r"kritische\s+infrastruktur|stromnetz|wasserversorgung|gasversorgung|verkehrssteuerung",
        re.IGNORECASE)),
    (AnnexIIICategory.BIOMETRICS, re.compile(r"gesichtserkennung|biometrische\s+identifi", re.IGNORECASE)),
    (AnnexIIICategory.EDUCATION, re.compile(r"pr(?:ü|ue)fungsbewertung|zulassung\s+zu\s+bildung", re.IGNORECASE)),
)


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _line_of(text: str, pattern: re.Pattern[str]) -> int | None:
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return number
    return None


_PAGE_MARKER = re.compile(r"^-{2,}\s*Seite\s+\d+\s*-{2,}$", re.IGNORECASE)


def _guess_recipient(lines: list[str], sender: str | None) -> str | None:
    """Empfänger ohne „An:“: Name über dem ersten Adressblock, der nicht zum Absender gehört."""
    sender_key = (sender or "").casefold()
    for index, line in enumerate(lines[1:], start=1):
        if not _STREET_LINE.search(line) or (sender_key and sender_key in line.casefold()) or "●" in line:
            continue
        for back in range(index - 1, max(index - 4, 0), -1):
            candidate = lines[back]
            if _CONTACT_LINE.search(candidate) or _STREET_LINE.search(candidate) or "●" in candidate:
                continue
            if sender_key and sender_key in candidate.casefold():
                break
            if re.search(r"[A-Za-zÄÖÜäöüß]{2,}", candidate):
                return candidate[:300]
            break
    return None


def heuristic_extraction(text: str) -> ExtractionResult:
    """Kerndaten per Mustererkennung; Zweifelsfälle bleiben leer statt geraten."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not _PAGE_MARKER.match(line.strip())]
    doc_type = next((kind for kind, pattern in _KIND if pattern.search(text)), DocType.OTHER)
    facts = analyze_text(text)
    if doc_type is DocType.OTHER and _RECEIPT.search(text) and _TAX_HINT.search(text) and facts.gross_amount is not None:
        doc_type = DocType.INVOICE  # Kleinbetrags- oder Bewirtungsbeleg mit Umsatzsteuer
    positions = position_lines(text)
    items = "; ".join(line[:80] for line in positions[:4]) or None
    recipient = next((m.group(1).strip() for line in lines if (m := _RECIPIENT.match(line))), None)
    sender = lines[0].split(",")[0].strip()[:300] if lines else None
    if lines and re.fullmatch(r"[\d.\-/ ]+", sender or ""):
        sender = lines[1].split(",")[0].strip()[:300] if len(lines) > 1 else None  # erste Zeile nur ein Datum
    recipient = recipient or _guess_recipient(lines, sender)
    iban = _first(_IBAN, text)
    gross = facts.gross_amount
    currency = "EUR" if re.search(r"\bEUR\b|€", text) else None
    number = _first(_DOC_NUMBER, text)
    data: dict[str, Any] = {
        "doc_type": doc_type,
        "sender": sender,
        "recipient": recipient[:300] if recipient else None,
        "document_number": number,
        "document_date": _first(_DOC_DATE, text),
        "due_date": _first(_DUE_DATE, text),
        "total_amount": gross,
        "currency": currency if gross is not None else None,
        "iban": iban.replace(" ", "") if iban else None,
        "sender_vat_id": (_first(_VAT_ID, text) or "").replace(" ", "") or None,
        "sender_tax_number": _first(_TAX_NUMBER, text),
        "service_date": _first(_SERVICE_DATE, text),
        "service_period": _first(_SERVICE_PERIOD, text),
        "items_description": items[:600] if items else None,
        "net_amount": facts.net_amount,
        "tax_rate": facts.tax_rate,
        "tax_amount": facts.tax_amount,
        "summary": (
            f"{HEURISTIC_LABEL}: Die Felder wurden per Mustererkennung aus dem Belegtext gelesen"
            f"{f' (Nr. {number})' if number else ''}. Ergebnis bitte durch eine Prüfperson bestätigen."
        ),
        "issues": [
            "Regelbasiertes Referenz-Audit: Kein Sprachmodell verfügbar - Pflichtangaben per Mustererkennung "
            "geprüft; Einordnung durch eine Prüfperson bestätigen."
        ],
    }
    return ExtractionResult.model_validate(data)


def heuristic_audit(text: str) -> ComplianceAuditPayload:
    """EU-AI-Act- und DSGVO-Teil ohne Sprachmodell (konservativ, gekennzeichnet)."""
    ai_match = _AI_SYSTEM.search(text)
    categories = [category for category, pattern in _ANNEX_III if pattern.search(text)]
    if not ai_match:
        ai_act: dict[str, Any] = {
            "describes_ai_system": False,
            "overall_risk_level": "not_applicable",
            "systems": [],
            "reasoning": (
                f"{HEURISTIC_LABEL}. Im Belegtext wurden keine Hinweise auf ein KI-System (Art. 3 Nr. 1 "
                "VO (EU) 2024/1689) gefunden. Die Einstufung beruht auf Schlagwörtern und ist durch eine "
                "Prüfperson zu bestätigen."
            ),
            "obligations": [],
        }
    else:
        line = _line_of(text, _AI_SYSTEM)
        if categories:
            level = "high"
            reasoning = (
                f"{HEURISTIC_LABEL}. Der Beleg nennt ein KI-System{f' [Z. {line}]' if line else ''} und Begriffe "
                "aus Anhang III; konservativ als Hochrisiko eingestuft (Art. 6 Abs. 2). Bitte durch eine "
                "Prüfperson bestätigen oder übersteuern (Art. 14 Abs. 4 lit. d)."
            )
            obligations = [
                "Risikomanagementsystem nach Art. 9 prüfen.",
                "Menschliche Aufsicht nach Art. 14 sicherstellen.",
                "Konformitätsbewertung nach Art. 43 nachweisen lassen.",
            ]
        else:
            level = "limited" if _TRANSPARENCY.search(text) else "minimal"
            reasoning = (
                f"{HEURISTIC_LABEL}. Der Beleg nennt ein KI-System{f' [Z. {line}]' if line else ''}, aber keine "
                "Anhang-III-Begriffe. Einstufung durch eine Prüfperson bestätigen."
            )
            obligations = ["Transparenzpflichten nach Art. 50 prüfen."] if level == "limited" else []
        ai_act = {
            "describes_ai_system": True,
            "overall_risk_level": level,
            "systems": [{
                "name": "Im Beleg genanntes KI-System",
                "purpose": "Per Schlagwort erkannt - Zweckbestimmung manuell prüfen.",
                "risk_level": level,
                "annex_iii_categories": [category.value for category in categories],
                "evidence": (text.splitlines()[line - 1].strip()[:400] if line else ai_match.group(0)),
                "confidence": 0.4,
            }],
            "reasoning": reasoning,
            "obligations": obligations,
        }
    return ComplianceAuditPayload.model_validate({
        "ai_act": ai_act,
        "gdpr": {
            "contains_personal_data": False,
            "findings": [],
            "risk_level": "none",
            "reasoning": f"{HEURISTIC_LABEL}. Regelbasierter PII-Scan über den vollständigen Belegtext.",
            "recommendations": [],
        },
    })


_HEURISTIC_COPY: dict[str, dict[str, str]] = {
    "de": {
        "heading": HEURISTIC_LABEL,
        "intro": (
            "Alle Stufen der Ausweich-Kaskade sind gerade nicht verfügbar ({reason}). "
            "Diese Antwort stützt sich ausschließlich auf das gespeicherte Prüfergebnis – ohne Sprachmodell."
        ),
        "pending": "Der Beleg ist noch nicht geprüft. Bitte zuerst die Prüfung starten.",
        "summary": "**Einordnung:** Score {score}/100 · {rec}",
        "open_title": "**Offene Prüfpunkte:**",
        "fallback_detail": "siehe Scorecard",
        "no_open": "Keine offenen Prüfpunkte – alle Kriterien der Scorecard sind erfüllt.",
        "doc_no": "Beleg-Nr. {number}.",
        "retry": "Für eine KI-gestützte Antwort auf die konkrete Frage bitte in Kürze erneut senden.",
    },
    "en": {
        "heading": "Rule-Based Reference Audit – AI Unavailable",
        "intro": (
            "All stages of the failover cascade are currently unavailable ({reason}). "
            "This response relies solely on the stored audit result — without a language model."
        ),
        "pending": "The document has not been audited yet. Please start the audit first.",
        "summary": "**Assessment:** Score {score}/100 · {rec}",
        "open_title": "**Open checks:**",
        "fallback_detail": "see scorecard",
        "no_open": "No open checks — all scorecard criteria are met.",
        "doc_no": "Document No. {number}.",
        "retry": "Please resend shortly for an AI-assisted answer to your specific question.",
    },
    "es": {
        "heading": "Auditoría de referencia basada en reglas – IA no disponible",
        "intro": (
            "Todas las etapas de la cascada de respaldo no están disponibles en este momento ({reason}). "
            "Esta respuesta se basa únicamente en el resultado de auditoría almacenado, sin modelo de lenguaje."
        ),
        "pending": "El documento aún no se ha auditado. Inicie primero la auditoría.",
        "summary": "**Valoración:** Puntuación {score}/100 · {rec}",
        "open_title": "**Puntos abiertos:**",
        "fallback_detail": "ver tabla de puntuación",
        "no_open": "Sin puntos abiertos: se cumplen todos los criterios de la tabla de puntuación.",
        "doc_no": "Documento n.º {number}.",
        "retry": "Reenvíe en breve para obtener una respuesta asistida por IA a su pregunta.",
    },
}


def heuristic_copilot_answer(record: Any, question: str, reason: str, *, lang: str = "de") -> str:
    """Deterministische Antwort aus Prüfergebnis und Belegtext (Copilot-Rückfall)."""
    c = _HEURISTIC_COPY.get(lang, _HEURISTIC_COPY["de"])
    scorecard = record.scorecard or {}
    extraction = record.extraction or {}
    open_points = [
        check
        for tile in scorecard.get("tiles", [])
        for check in tile.get("checks", [])
        if check.get("status") in {"fail", "warn"}
    ]
    parts = [
        f"**{c['heading']}.** {c['intro'].format(reason=reason)}",
    ]
    if not scorecard:
        parts.append(c["pending"])
    else:
        parts.append(
            c["summary"].format(
                score=scorecard.get("score", "–"),
                rec=scorecard.get("release_recommendation", ""),
            )
        )
        if open_points:
            parts.append(c["open_title"])
            parts.extend(
                f"- {check.get('label')}: {check.get('detail') or c['fallback_detail']}"
                f"{f' ({ref})' if (ref := check.get('legal_reference')) else ''}"
                for check in open_points[:8]
            )
        else:
            parts.append(c["no_open"])
    number = extraction.get("document_number")
    if number:
        parts.append(c["doc_no"].format(number=number))
    parts.append(c["retry"])
    return "\n\n".join(parts[:2]) + "\n\n" + "\n".join(parts[2:])
