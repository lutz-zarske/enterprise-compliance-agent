"""Deterministische Compliance-Scorecard (0-100).

Der Score entsteht **nicht** im LLM, sondern aus festen, versionierten Regeln
über die validierte Extraktion, das Audit und den Dokumenttext.  Dieselbe
Eingabe ergibt immer denselben Score - Voraussetzung für eine Prüfung, die
ein Wirtschaftsprüfer nachvollziehen und nachrechnen kann.

Jede Pflichtangabe wird doppelt belegt: zuerst aus der LLM-Extraktion, dann
per Regex direkt im Dokumenttext.  ``evidence_source`` weist aus, woher der
Nachweis stammt (``llm``, ``rule_based``, ``both``).

Bewertungsschema (Basis 100, Abzüge je Mangel):

* Formelle Gültigkeit, Paragraf 14 Abs. 4 UStG (nur Rechnungen):
  fehlende Steuernummer/USt-IdNr. -20, jede weitere fehlende Pflichtangabe -10.
  Kleinbetragsrechnungen bis 250 EUR brutto: reduzierter Katalog (Paragraf 33 UStDV).
* E-Rechnung (seit Regelwerk 2026.2): Abweichung zwischen maßgeblichem
  XML-Datensatz und PDF-Bildteil -10 (BMF 15.10.2024, Rz. 36); fehlende oder
  ungültige Leitweg-ID bei öffentlichen Auftraggebern -10 (Paragraf 5 ERechV).
  Profil- und Geschäftsregel-Befunde (EN 16931) sind Hinweise ohne Abzug.
* Mathematische Validität: ungültige IBAN (MOD-97) -15, Netto + USt != Brutto
  -15, USt-Betrag != Netto x Satz -10, unzulässiger Steuersatz -10.
* Regulatorisches Risiko (EU AI Act): Hochrisiko ohne Nachweis einer
  Konformitätsbewertung -25 und Deckelung auf 59; mit Nachweis -10;
  begrenztes Risiko -5; verbotene Praktik (Art. 5) Deckelung auf 20.
* Datenschutz (DSGVO): besondere Kategorien nach Art. 9/10 -10 (Rechtsgrundlage
  nach Art. 9 Abs. 2 nicht belegt), amtliche Kennnummern natürlicher Personen -5.

Bänder: >= 85 grün (verkehrsfähig), 60-84 gelb (Nachbesserung), < 60 rot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db import utcnow
from app.schemas import (
    SPECIAL_CATEGORIES,
    AIActRiskLevel,
    CheckStatus,
    ComplianceAudit,
    DocType,
    EInvoiceData,
    ExtractionResult,
    PIICategory,
    RetentionInfo,
    ScoreBand,
    ScoreCheck,
    Scorecard,
    ScoreTile,
    iban_checksum_valid,
)

RULESET_VERSION = "2026.4"

#: Grenze der Kleinbetragsrechnung nach Paragraf 33 UStDV (seit 01.01.2017).
SMALL_AMOUNT_LIMIT = Decimal("250")

GREEN_THRESHOLD = 85
AMBER_THRESHOLD = 60
HIGH_RISK_CAP = 59
UNACCEPTABLE_CAP = 20

_MONEY_TOLERANCE = Decimal("0.02")

# --- Regex-Belege im Dokumenttext ------------------------------------------
_VAT_ID = re.compile(
    r"\b(?:DE ?\d{9}|ATU\d{8}"
    r"|(?:BE|BG|CY|CZ|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)"
    r"[A-Z0-9]{0,2}\d{6,10}[A-Z0-9]{0,3})\b"
)
_TAX_NUMBER = re.compile(r"\b\d{2,3}/\d{3,4}/\d{4,5}\b")
_SERVICE_DATE = re.compile(
    r"(?:leistungs|liefer)(?:datum|zeitraum|zeitpunkt|tag)|leistung\s+erbracht|zeitraum\s*:",
    re.IGNORECASE,
)
_EXEMPTION = re.compile(
    r"steuerfrei|reverse[\s-]?charge|steuerschuldnerschaft des leistungsempf|§\s?13b|"
    r"§\s?4 nr\.?|kleinunternehmer|§\s?19 ustg|innergemeinschaftliche lieferung",
    re.IGNORECASE,
)
_STREET = re.compile(
    r"[A-ZÄÖÜ][a-zäöüß\-]+(?:straße|strasse|str\.|weg|allee|platz|gasse|ring|damm|ufer)\s+\d+",
)
_ZIP_CITY = re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+")
_AMOUNT = re.compile(r"(?<!\w)-?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}|\d+\.\d{2}(?!\d))")
_PERCENT = re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s?%")
_CONFORMITY = re.compile(
    r"konformit(?:ä|ae)tsbewertung|ce-kennzeichnung|eu-konformit(?:ä|ae)tserkl(?:ä|ae)rung|art\.?\s?43",
    re.IGNORECASE,
)
_CONFORMITY_NEGATION = re.compile(
    r"\b(?:kein\w*|nicht|ohne|fehl\w*|ausstehend\w*|verzicht\w*|unvollst(?:ä|ae)ndig\w*|"
    r"verpflichtet\s+sich|beabsichtigt|geplant\w*|k(?:ü|ue)nftig\w*|zuk(?:ü|ue)nftig\w*|"
    r"wird\s+(?:noch|erst|bis|nachgereicht|durchgef(?:ü|ue)hrt)|"
    r"not|no|without|missing|pending|shall\s+provide|will\s+conduct|planned)\b",
    re.IGNORECASE,
)


_SENTENCE_SEP = re.compile(
    r"(?<!\bArt)(?<!\bAbs)(?<!\bNr)(?<!\blit)(?<!\bbzw)(?<!\bggf)\.\s+|[;]|\n\s*\n|\n(?=\s*[•\-*§])"
)


def _has_conformity_evidence(text: str) -> bool:
    """Erkennt Konformitätshinweise, ignoriert aber verneinte Aussagen („noch nicht vor“)."""
    for clause in _SENTENCE_SEP.split(text):
        match = _CONFORMITY.search(clause)
        if match and not _CONFORMITY_NEGATION.search(clause[max(0, match.start() - 120) : match.end() + 120]):
            return True
    return False
_POSITIONS = re.compile(
    r"\bpos(?:ition)?\.?\s*\d|\bmenge\b|\bstk\.?|\bst(?:ü|ue)ck\b|\banzahl\b|leistungsbeschreibung|\bartikel\b",
    re.IGNORECASE,
)
_EINVOICE_MARKERS = (b"factur-x.xml", b"zugferd-invoice.xml", b"xrechnung.xml", b"ZUGFeRD")

_VALID_RATES = {Decimal("0"), Decimal("7"), Decimal("19")}
#: Befristete Absenkung 01.07.2020 - 31.12.2020 (Zweites Corona-Steuerhilfegesetz).
_COVID_RATES = {Decimal("5"), Decimal("16")}


def _to_decimal(raw: str) -> Decimal | None:
    text = raw.strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


@dataclass(slots=True)
class TextFacts:
    """Regelbasiert aus dem Text gewonnene Belege."""

    vat_id: bool
    tax_number: bool
    service_date: bool
    exemption: bool
    address_count: int
    net_amount: Decimal | None
    tax_amount: Decimal | None
    tax_rate: Decimal | None
    gross_amount: Decimal | None
    conformity_evidence: bool
    positions: bool
    tax_rates: tuple[Decimal, ...] = ()
    #: Befreiung für den ganzen Beleg (Reverse Charge, § 13b, § 19, ig. Lieferung) – nicht nur einzelne Posten.
    full_exemption: bool = False


#: Hinweise, die den ganzen Beleg von der Umsatzsteuer ausnehmen.  Ein bloßes
#: „steuerfrei“ oder „§ 4 Nr.“ betrifft oft nur einzelne Posten (z. B. Porto als
#: durchlaufender Posten) und begründet allein keinen Widerspruch nach § 14c UStG.
_FULL_EXEMPTION = re.compile(
    r"reverse[\s-]?charge|steuerschuldnerschaft des leistungsempf|§\s?13b|kleinunternehmer|§\s?19 ustg|"
    r"innergemeinschaftliche lieferung",
    re.IGNORECASE,
)
#: „Die Kleinunternehmerregelung findet keine Anwendung“ ist kein Befreiungshinweis.
_EXEMPTION_NOT_APPLIED = re.compile(
    r"keine\s+anwendung|nicht\s+(?:anwendbar|angewendet|anzuwenden|einschl(?:ä|ae)gig)|gilt\s+nicht|"
    r"kein(?:e|en)?\s+(?:fall|reverse)",
    re.IGNORECASE,
)


def full_exemption_claim(*texts: str | None) -> bool:
    """Behauptet eine Zeile eine Befreiung des ganzen Belegs (ohne Verneinung)?"""
    for text in texts:
        for line in (text or "").splitlines():
            if _FULL_EXEMPTION.search(line) and not _EXEMPTION_NOT_APPLIED.search(line):
                return True
    return False


#: Datumsangaben (15.12.2024, 15.12.24, 15.12., 2024-12-15) sind nie Beträge.
_DATE_TOKEN = re.compile(r"(?<![\d.,])\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})?(?!\d)|\b\d{4}-\d{2}-\d{2}\b")
#: Zahlungsbedingungen („Zahlbar innerhalb 30 Tagen netto bis …“) tragen keine Summen.
_PAYMENT_TERMS = re.compile(
    r"zahlbar|skonto|zahlungsziel|zahlungsbedingung|f(?:ä|ae)llig|innerhalb\s+\d+\s+tag", re.IGNORECASE
)
_TAX_WORD = re.compile(r"\b(?:ust|mwst|umsatzsteuer|mehrwertsteuer)\b")
_TAX_ID_WORD = re.compile(r"id|nr\.|nummer|identifikation")
_EXCLUDING_TAX = re.compile(r"(?:ohne|exkl\.?|excl\.?|zzgl\.?\s+der)\s*(?:ust|mwst|umsatzsteuer|mehrwertsteuer)")

#: Summen-Bezeichner je Betrag, Rang 1 = eindeutige Summe, Rang 2 = schwächerer Hinweis.
_AMOUNT_LABELS: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "net": (
        re.compile(
            r"summe\s*netto|netto\s*-?\s*summe|nettosumme|gesamt\s*netto|netto\s*gesamt|nettobetrag|"
            r"nettogesamt|rechnungssumme\s+(?:ohne|exkl)|summe\s+(?:ohne|exkl)|entgelt\s+netto"
        ),
        re.compile(r"positionssumme|zwischensumme|warenwert|\bnetto\b"),
    ),
    "tax": (
        re.compile(
            r"(?:umsatzsteuer|mehrwertsteuer|ust\.?|mwst\.?)\s*gesamt|gesamt\s*(?:ust|mwst|umsatzsteuer)|"
            r"summe\s*(?:der\s*)?(?:ust|mwst|umsatzsteuer|mehrwertsteuer|steuer)|steuerbetrag|"
            r"(?:ust|mwst)\.?-?\s*betrag|umsatzsteuerbetrag|mehrwertsteuerbetrag"
        ),
        _TAX_WORD,
    ),
    "gross": (
        re.compile(
            r"gesamtbetrag(?!\s+der\b)|rechnungsbetrag|bruttosumme|bruttobetrag|summe\s*brutto|brutto\s*gesamt|"
            r"gesamt\s*brutto|endbetrag|rechnungssumme(?!\s+(?:ohne|exkl|netto))|rechnungsgesamtbetrag"
        ),
        re.compile(r"zahlbetrag|zu\s+zahlen|\bbrutto\b"),
    ),
}


def labeled_amounts(text: str) -> dict[str, list[tuple[int, Decimal]]]:
    """Beträge hinter Summen-Bezeichnern, je Kategorie mit Rang (1 = eindeutig).

    Datumsangaben und Zeilen mit Zahlungsbedingungen zählen nie als Betrag.  Je
    Zeile gewinnt die Kategorie mit dem besten Rang; bei Gleichstand netto vor
    Steuer vor brutto („Rechnungssumme ohne USt.“ ist netto, nicht Steuer).
    """
    found: dict[str, list[tuple[int, Decimal]]] = {"net": [], "tax": [], "gross": []}
    for raw in text.splitlines():
        if _PAYMENT_TERMS.search(raw):
            continue
        line = _DATE_TOKEN.sub(" ", raw)
        amounts = [value for value in (_to_decimal(m) for m in _AMOUNT.findall(line)) if value is not None]
        if not amounts:
            continue
        low = line.casefold()
        excluding_tax = bool(_EXCLUDING_TAX.search(low))
        best: tuple[int, str] | None = None
        for key, (strong, weak) in _AMOUNT_LABELS.items():
            if key == "tax" and (excluding_tax or _TAX_ID_WORD.search(low)):
                continue
            rank = 1 if strong.search(low) else 2 if weak.search(low) else None
            if key == "net" and rank is None and excluding_tax:
                rank = 1
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, key)
        if best is not None:
            found[best[1]].append((best[0], amounts[-1]))
    return found


def _pick(candidates: list[tuple[int, Decimal]], *, last: bool = False) -> Decimal | None:
    if not candidates:
        return None
    rank = min(r for r, _ in candidates)
    values = [value for r, value in candidates if r == rank]
    return values[-1] if last else values[0]


def analyze_text(text: str) -> TextFacts:
    rate = None
    seen_rates: list[Decimal] = []
    for line in text.splitlines():
        low = line.casefold()
        if _TAX_WORD.search(low) and not _TAX_ID_WORD.search(low):
            percents = [value for value in (_to_decimal(m) for m in _PERCENT.findall(line)) if value is not None]
            for pct in percents:
                if pct not in seen_rates:
                    seen_rates.append(pct)
            if rate is None and percents:
                rate = percents[0]
    labeled = labeled_amounts(text)
    net = _pick(labeled["net"])
    tax = _pick(labeled["tax"])
    gross = _pick(labeled["gross"], last=True)
    return TextFacts(
        vat_id=bool(_VAT_ID.search(text)),
        tax_number=bool(_TAX_NUMBER.search(text)),
        service_date=bool(_SERVICE_DATE.search(text)),
        exemption=bool(_EXEMPTION.search(text)),
        address_count=max(len(_STREET.findall(text)), len(_ZIP_CITY.findall(text))),
        net_amount=net,
        tax_amount=tax,
        tax_rate=rate,
        gross_amount=gross,
        conformity_evidence=_has_conformity_evidence(text),
        positions=bool(_POSITIONS.search(text)),
        tax_rates=tuple(seen_rates),
        full_exemption=full_exemption_claim(text),
    )


def detect_structured_einvoice(pdf_bytes: bytes | None) -> bool:
    """Erkennt eingebettete ZUGFeRD/Factur-X/XRechnung-XML (PDF/A-3-Anhang)."""
    if not pdf_bytes:
        return False
    return any(marker in pdf_bytes for marker in _EINVOICE_MARKERS)


def _source(llm: bool, rule: bool, *, structured: bool = False) -> str | None:
    """Herkunft eines Nachweises; im XML-Pfad ersetzt der Datensatz das Modell."""
    if llm and rule:
        return "xml_rule" if structured else "both"
    if llm:
        return "xml" if structured else "llm"
    if rule:
        return "rule_based"
    return None


def _check(
    check_id: str,
    label: str,
    ref: str,
    present: bool,
    deduction: int,
    *,
    source: str | None,
    required: bool = True,
    missing_detail: str | None = None,
    na_detail: str | None = None,
) -> ScoreCheck:
    if not required:
        return ScoreCheck(
            id=check_id, label=label, legal_reference=ref, status=CheckStatus.NOT_APPLICABLE,
            detail=na_detail,
        )
    if present:
        return ScoreCheck(
            id=check_id, label=label, legal_reference=ref, status=CheckStatus.PASS, evidence_source=source
        )
    return ScoreCheck(
        id=check_id, label=label, legal_reference=ref, status=CheckStatus.FAIL,
        deduction=deduction, detail=missing_detail or "Pflichtangabe fehlt.",
    )


def _tile(key: str, title: str, checks: list[ScoreCheck], headline: str | None = None) -> ScoreTile:
    statuses = {check.status for check in checks}
    if CheckStatus.FAIL in statuses:
        status = CheckStatus.FAIL
    elif CheckStatus.WARN in statuses:
        status = CheckStatus.WARN
    elif CheckStatus.PASS in statuses:
        status = CheckStatus.PASS
    else:
        status = CheckStatus.NOT_APPLICABLE
    return ScoreTile(
        key=key,
        title=title,
        status=status,
        headline=headline or "",
        deduction=sum(check.deduction for check in checks),
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Kacheln
# ---------------------------------------------------------------------------


def _formal_tile(
    extraction: ExtractionResult,
    facts: TextFacts,
    text: str,
    *,
    enforce: bool,
    marker: bool,
    einvoice: EInvoiceData | None,
    structured: bool,
) -> tuple[ScoreTile, int, int, bool]:
    title = "Formelle Gültigkeit (§ 14 UStG & EN 16931)"
    if extraction.doc_type is not DocType.INVOICE or not enforce:
        reason = (
            "Keine Rechnung – Pflichtangaben nach § 14 Abs. 4 UStG nicht einschlägig."
            if enforce
            else "§ 14-UStG-Prüfung in den Einstellungen deaktiviert."
        )
        check = ScoreCheck(
            id="ustg_scope", label="Anwendungsbereich § 14 UStG", legal_reference="§ 14 Abs. 4 UStG",
            status=CheckStatus.NOT_APPLICABLE, detail=reason,
        )
        return _tile("formal", title, [check], "Nicht einschlägig"), 0, 0, False

    gross = extraction.total_amount if extraction.total_amount is not None else facts.gross_amount
    currency_code = (extraction.currency or "EUR").strip().upper()
    small = currency_code == "EUR" and gross is not None and Decimal(0) < gross <= SMALL_AMOUNT_LIMIT
    na_small = "Entbehrlich bei Kleinbetragsrechnungen bis 250 EUR (§ 33 UStDV)."

    addresses_in_text = facts.address_count
    xml_rates = einvoice is not None and any(entry.rate is not None for entry in einvoice.vat_breakdown)
    xml_exemption = einvoice is not None and any(
        ((entry.category or "").strip().upper() in {"O", "AE", "E", "K", "G", "Z"} or bool(entry.exemption_reason))
        for entry in einvoice.vat_breakdown
    )
    rate_known = extraction.tax_rate is not None or facts.tax_rate is not None or xml_rates
    tax_known = extraction.tax_amount is not None or facts.tax_amount is not None
    exemption = bool(extraction.tax_exemption_note) or facts.exemption or xml_exemption

    def src(llm: bool, rule: bool) -> str | None:
        return _source(llm, rule, structured=structured)

    sender_addr_rule = False if structured else addresses_in_text >= 1
    recipient_addr_rule = False if structured else addresses_in_text >= 2
    checks = [
        _check(
            "ustg_1_sender", "Name und Anschrift des leistenden Unternehmers",
            "§ 14 Abs. 4 Satz 1 Nr. 1 UStG",
            bool(extraction.sender) and (bool(extraction.sender_address) or sender_addr_rule),
            10, source=src(bool(extraction.sender_address), sender_addr_rule),
        ),
        _check(
            "ustg_1_recipient", "Name und Anschrift des Leistungsempfängers",
            "§ 14 Abs. 4 Satz 1 Nr. 1 UStG",
            bool(extraction.recipient) and (bool(extraction.recipient_address) or recipient_addr_rule),
            10, source=src(bool(extraction.recipient_address), recipient_addr_rule),
            required=not small, na_detail=na_small,
        ),
        _check(
            "ustg_2_tax_id", "Steuernummer oder USt-IdNr. des Ausstellers",
            "§ 14 Abs. 4 Satz 1 Nr. 2 UStG",
            bool(extraction.sender_tax_number or extraction.sender_vat_id) or facts.vat_id or facts.tax_number,
            20, source=src(
                bool(extraction.sender_tax_number or extraction.sender_vat_id), facts.vat_id or facts.tax_number
            ),
            required=not small, na_detail=na_small,
            missing_detail="Weder Steuernummer noch USt-IdNr. angegeben – kein Vorsteuerabzug (§ 15 UStG).",
        ),
        _check(
            "ustg_3_date", "Ausstellungsdatum", "§ 14 Abs. 4 Satz 1 Nr. 3 UStG",
            extraction.document_date is not None, 10, source=src(extraction.document_date is not None, False),
        ),
        _check(
            "ustg_4_number", "Fortlaufende, einmalige Rechnungsnummer", "§ 14 Abs. 4 Satz 1 Nr. 4 UStG",
            bool(extraction.document_number), 10, source=src(bool(extraction.document_number), False),
            required=not small, na_detail=na_small,
        ),
        _check(
            "ustg_5_items", "Menge und Art der Lieferung / Umfang und Art der Leistung",
            "§ 14 Abs. 4 Satz 1 Nr. 5 UStG",
            bool(extraction.items_description) or facts.positions or facts_has_positions(extraction),
            10, source=src(bool(extraction.items_description), facts.positions),
        ),
        _check(
            "ustg_6_service_date", "Zeitpunkt der Lieferung oder Leistung", "§ 14 Abs. 4 Satz 1 Nr. 6 UStG",
            extraction.service_date is not None or bool(extraction.service_period) or facts.service_date,
            10, source=src(
                extraction.service_date is not None or bool(extraction.service_period), facts.service_date
            ),
            required=not small, na_detail=na_small,
        ),
        _check(
            "ustg_7_net", "Nach Steuersätzen aufgeschlüsseltes Entgelt (netto)", "§ 14 Abs. 4 Satz 1 Nr. 7 UStG",
            extraction.net_amount is not None or facts.net_amount is not None,
            10, source=src(extraction.net_amount is not None, facts.net_amount is not None),
            required=not small, na_detail="Bei Kleinbetragsrechnungen genügt das Entgelt inkl. Steuer (§ 33 UStDV).",
        ),
        _check(
            "ustg_8_rate", "Anzuwendender Steuersatz oder Hinweis auf Steuerbefreiung",
            "§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
            rate_known or exemption,
            10,
            source=src(
                extraction.tax_rate is not None or bool(extraction.tax_exemption_note) or xml_rates or xml_exemption,
                facts.tax_rate is not None or facts.exemption,
            ),
        ),
        _check(
            "ustg_8_amount", "Auf das Entgelt entfallender Steuerbetrag", "§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
            tax_known or exemption,
            10,
            source=src(
                extraction.tax_amount is not None or bool(extraction.tax_exemption_note) or xml_exemption,
                facts.tax_amount is not None or facts.exemption,
            ),
            required=not small, na_detail=na_small,
        ),
    ]
    _service_time_detail(checks, einvoice, structured=structured)
    required = [check for check in checks if check.status is not CheckStatus.NOT_APPLICABLE]
    fulfilled = sum(check.status is CheckStatus.PASS for check in required)

    checks.append(_en16931_check(einvoice, marker=marker, public=_public_reason(extraction, einvoice) is not None))
    extra: list[ScoreCheck] = []
    primacy = _xml_primacy_check(einvoice)
    if primacy is not None:
        extra.append(primacy)
    version = _xrechnung_version_check(einvoice)
    if version is not None:
        extra.append(version)
    leitweg = _leitweg_check(extraction, einvoice, text)
    if leitweg is not None:
        extra.append(leitweg)
    checks.extend(extra)

    deduction = sum(check.deduction for check in checks)
    extra_fail = any(check.status is CheckStatus.FAIL for check in extra)
    headline = (
        f"Vollständig ({fulfilled}/{len(required)})"
        if fulfilled == len(required)
        else f"Mängel ({len(required) - fulfilled} fehlend)"
    )
    if einvoice is not None and not einvoice.error:
        headline += f" · {einvoice.profile}"
    if small:
        headline += " · Kleinbetrag"
    tile = _tile("formal", title, checks, headline)
    tile.deduction = deduction
    # Der E-Rechnungs-Hinweis ist rein informativ.  Den Kachelstatus bestimmen
    # die Pflichtangaben, die Leitweg-ID und der Abgleich XML <-> Bildteil.
    if fulfilled < len(required) or extra_fail:
        tile.status = CheckStatus.FAIL
    elif primacy is not None and primacy.deduction:
        tile.status = CheckStatus.WARN
    else:
        tile.status = CheckStatus.PASS
    return tile, len(required), fulfilled, small


_EN_NOTE = (
    "Empfangspflicht für E-Rechnungen seit 01.01.2025. Bei hybriden Formaten ist der XML-Teil "
    "führend; abweichende Angaben im Bildteil können als eigene Rechnung gelten "
    "(BMF-Schreiben vom 15.10.2024, Rz. 36, präzisiert durch BMF-Schreiben vom 15.10.2025)."
)


def _en16931_check(einvoice: EInvoiceData | None, *, marker: bool, public: bool) -> ScoreCheck:
    label = "Strukturierte E-Rechnung (EN 16931: XRechnung / ZUGFeRD)"
    ref = "§ 14 Abs. 1 UStG i. d. F. des Wachstumschancengesetzes"
    risk_note: str | None = None
    if einvoice is not None and einvoice.error:
        status = CheckStatus.WARN
        detail = (
            f"Eingebetteter Datensatz {einvoice.attachment_name or ''} ist nicht auswertbar: {einvoice.error} "
            "Bewertet wird der Bildteil. Kein Punktabzug."
        )
    elif einvoice is not None:
        container = (
            f"eingebettet als {einvoice.attachment_name}" if einvoice.source == "embedded" else "reines XML"
        )
        if einvoice.is_einvoice:
            status = CheckStatus.WARN if einvoice.rule_violations else CheckStatus.PASS
            detail = (
                f"Profil {einvoice.profile}, Syntax {einvoice.syntax} ({container}). Geprüft: Profilkennung BT-24, "
                "Pflichtfelder und Summenregeln (BR-CO-10/13/14/15, BR-DE-2, BR-DE-15). Keine vollständige Validierung gegen XSD "
                "und Schematron (z. B. KoSIT-Validator)."
            )
            if einvoice.rule_violations:
                detail += " Verstöße: " + " ".join(einvoice.rule_violations) + " Kein Punktabzug."
                risk_note = (
                    XRECHNUNG_RESERVATION_NOTE
                    if einvoice.profile_key == "xrechnung"
                    and any(rule.startswith("BR-DE-") for rule in einvoice.rule_violations)
                    else "Verstöße gegen EN-16931-Geschäftsregeln führen beim Empfänger regelmäßig zur "
                    "Zurückweisung durch den Validator."
                )
        else:
            status = CheckStatus.WARN
            if einvoice.profile_key in {"minimum", "basic_wl"}:
                detail = (
                    f"Profil {einvoice.profile} ({container}) erfüllt nicht die Anforderungen an eine E-Rechnung "
                    "(BMF-Schreiben vom 15.10.2024). Rechnung ist der Bildteil – eine „sonstige Rechnung“, "
                    "zulässig in der Übergangsfrist. Kein Punktabzug."
                )
                risk_note = (
                    "MINIMUM- und BASIC-WL-Datensätze erfüllen die Rechnungspflicht nach Ablauf der Übergangsfrist "
                    "nicht; bis dahin ist der Bildteil die Rechnung."
                )
            else:
                detail = (
                    f"Profil nicht erkennbar (BT-24: {einvoice.specification_id or 'fehlt'}). Die Daten wurden "
                    "gelesen, die Zuordnung zu EN 16931 ist aber nicht belegt. Kein Punktabzug."
                )
    elif marker:
        status = CheckStatus.WARN
        detail = (
            "Hinweis auf eingebettetes XML (ZUGFeRD/Factur-X/XRechnung), der Datensatz ist aber nicht lesbar. "
            "Rechtlich maßgeblich ist bei hybriden Rechnungen der strukturierte XML-Teil; bewertet wird hier der "
            "Bildteil. Kein Punktabzug."
        )
    else:
        status = CheckStatus.WARN
        detail = (
            "Reines PDF ohne eingebettetes XML: im inländischen B2B-Verkehr seit 01.01.2025 eine "
            "„sonstige Rechnung“. Zulässig in der Übergangsfrist bis 31.12.2026 (bei Vorjahresumsatz "
            "bis 800.000 EUR bis 31.12.2027), danach Ausstellungspflicht für E-Rechnungen. Kein Punktabzug."
        )
        if public:
            detail += (
                " Öffentliche Auftraggeber verlangen eine E-Rechnung (für den Bund § 3 ERechV, "
                "für Länder und Kommunen Landesrecht)."
            )
    return ScoreCheck(
        id="en16931", label=label, legal_reference=ref, status=status, detail=detail,
        evidence_source="xml" if einvoice is not None and not einvoice.error else "rule_based",
        risk_note=risk_note, note=_EN_NOTE,
    )


def _service_time_detail(checks: list[ScoreCheck], einvoice: EInvoiceData | None, *, structured: bool) -> None:
    """Nennt bei E-Rechnungen, woher der Leistungszeitpunkt stammt (BT-72, BG-14, BG-26)."""
    if einvoice is None or einvoice.error or not structured:
        return
    from app.extractors.einvoice import _format_date, service_time

    check = next((c for c in checks if c.id == "ustg_6_service_date"), None)
    if check is None or check.status is not CheckStatus.PASS:
        return
    start, end, source, uncovered = service_time(einvoice)
    parts: list[str] = []
    if einvoice.delivery_date:
        parts.append(f"Lieferdatum {_format_date(einvoice.delivery_date)} (BT-72)")
    if source == "BG-14":
        parts.append(f"Rechnungszeitraum {_format_date(start)} – {_format_date(end)} (BG-14)")
    elif source == "BG-26":
        parts.append(f"Positionszeitraum {_format_date(start)} – {_format_date(end)} (BG-26)")
    if not parts:
        return
    check.detail = "Aus dem XML-Datensatz: " + ", ".join(parts) + "."
    if source == "BG-26" and uncovered and not einvoice.delivery_date:
        check.detail += (
            f" {uncovered} von {len(einvoice.lines)} Positionen ohne eigenen Zeitraum – die KoSIT-Regel "
            "BR-DE-TMP-32 empfiehlt ihn in jeder Position oder auf Belegebene. Kein Punktabzug."
        )


XRECHNUNG_RESERVATION = "Freigabe unter Vorbehalt — XRechnung-Standard nicht eingehalten"
XRECHNUNG_RESERVATION_NOTE = (
    "Pflichtangaben nach § 14 UStG erfüllt, aber nicht konform zum angegebenen XRechnung-Standard; "
    "Eingangsplattformen öffentlicher Auftraggeber prüfen gegen diese Regeln. Daher Freigabe unter Vorbehalt, "
    "ohne Punktabzug."
)


def xrechnung_deviation(einvoice: EInvoiceData | None) -> bool:
    """Weist sich der Beleg als XRechnung aus und verletzt BR-DE-Regeln oder nutzt eine ungültige Version?

    Gilt nur bei XRechnung-Kennung (BT-24), nicht für reine EN-16931-/ZUGFeRD-Profile.
    """
    if einvoice is None or einvoice.error or einvoice.profile_key != "xrechnung":
        return False
    from app.extractors.einvoice import xrechnung_version_notice

    if any(rule.startswith("BR-DE-") for rule in einvoice.rule_violations):
        return True
    return xrechnung_version_notice(einvoice) is not None


def _xrechnung_version_check(einvoice: EInvoiceData | None) -> ScoreCheck | None:
    """Hinweis ohne Punktabzug, wenn die XRechnung-Version nicht mehr in Kraft ist."""
    if einvoice is None or einvoice.error:
        return None
    from app.extractors.einvoice import xrechnung_version_notice

    notice = xrechnung_version_notice(einvoice)
    if notice is None:
        return None
    return ScoreCheck(
        id="xrechnung_version", label="XRechnung-Version", legal_reference="KoSIT, Versionen und Bundles",
        status=CheckStatus.WARN, detail=f"{notice} Kein Punktabzug.", evidence_source="xml_rule",
        risk_note=XRECHNUNG_RESERVATION_NOTE,
    )


def _xml_primacy_check(einvoice: EInvoiceData | None) -> ScoreCheck | None:
    """Abgleich XML-Datensatz <-> visueller PDF-Teil (nur hybride Rechnungen)."""
    if einvoice is None or einvoice.error or einvoice.source != "embedded" or not einvoice.visual_check:
        return None
    if not einvoice.is_einvoice:
        return None  # MINIMUM/BASIC WL: Der Bildteil ist die Rechnung, das XML hat keinen Vorrang.
    label = "Abgleich XML-Datensatz ↔ PDF-Bildteil"
    ref = "BMF-Schreiben vom 15.10.2024, Rz. 36"
    mismatches = [c for c in einvoice.visual_check if c.status == "mismatch"]
    missing = [c for c in einvoice.visual_check if c.status == "not_found"]
    if mismatches:
        parts = "; ".join(f"{c.bt} {c.label}: XML {c.xml_value}, PDF {c.visual_value}" for c in mismatches)
        return ScoreCheck(
            id="xml_primacy", label=label, legal_reference=ref, status=CheckStatus.WARN, deduction=10,
            detail=(
                "Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz (BMF 15.10.2024: XML hat "
                f"Vorrang). {parts}."
            ),
            evidence_source="xml_rule",
        )
    if missing:
        names = ", ".join(f"{c.bt} {c.label}" for c in missing)
        return ScoreCheck(
            id="xml_primacy", label=label, legal_reference=ref, status=CheckStatus.WARN,
            detail=(
                f"Im Bildteil nicht eindeutig wiedergefunden: {names}. Maßgeblich ist der XML-Datensatz. "
                "Kein Punktabzug."
            ),
            evidence_source="xml_rule",
        )
    return ScoreCheck(
        id="xml_primacy", label=label, legal_reference=ref, status=CheckStatus.PASS,
        detail=f"Alle {len(einvoice.visual_check)} Kernwerte stimmen im XML und im Bildteil überein.",
        evidence_source="xml_rule",
    )


def _public_reason(extraction: ExtractionResult, einvoice: EInvoiceData | None) -> str | None:
    from app.extractors.einvoice import detect_public_buyer

    if einvoice is not None and not einvoice.error:
        return einvoice.public_buyer_reason
    if extraction.doc_type is not DocType.INVOICE:
        return None
    return detect_public_buyer(extraction.recipient)


def _leitweg_check(extraction: ExtractionResult, einvoice: EInvoiceData | None, text: str) -> ScoreCheck | None:
    """Leitweg-ID nur bei öffentlichen Auftraggebern (B2G) - im B2B-Verkehr nicht erforderlich."""
    from app.extractors.einvoice import find_leitweg_in_text, validate_leitweg_id

    reason = _public_reason(extraction, einvoice)
    if reason is None:
        return None
    label = "Leitweg-ID des öffentlichen Auftraggebers (BT-10)"
    ref = "§ 5 Abs. 1 Nr. 1 ERechV; BR-DE-15"
    if einvoice is not None and not einvoice.error:
        leitweg, source = einvoice.leitweg, "xml"
    else:
        found = find_leitweg_in_text(text)
        leitweg, source = (validate_leitweg_id(found) if found else None), "rule_based"
    if leitweg is not None and leitweg.valid:
        return ScoreCheck(
            id="leitweg_id", label=label, legal_reference=ref, status=CheckStatus.PASS, evidence_source=source,
            detail=f"{leitweg.value}: Aufbau und Prüfziffer (ISO/IEC 7064, MOD 97-10) gültig. {reason}",
        )
    detail = (
        f"{leitweg.value}: {leitweg.reason} {reason}"
        if leitweg is not None
        else f"Öffentlicher Auftraggeber erkannt, aber keine Leitweg-ID angegeben. {reason}"
    )
    return ScoreCheck(
        id="leitweg_id", label=label, legal_reference=ref, status=CheckStatus.FAIL, deduction=10,
        detail=detail, evidence_source=source,
    )


_NEGATED_POSITIONS = re.compile(
    r"\b(?:kein\w*|fehl\w*|ohne)\s+(?:(?:\w+\s+){0,2})(?:leistungsbeschreibung|position\w*|artikel|lieferung|leistung)\b",
    re.IGNORECASE,
)


def facts_has_positions(extraction: ExtractionResult) -> bool:
    """Hilfsregel für Nr. 5: Zusammenfassung beschreibt eine konkrete Leistung (nicht verneint)."""
    summary = (extraction.summary or "").casefold()
    if not summary or _NEGATED_POSITIONS.search(summary):
        return False
    return any(word in summary for word in ("lizenz", "lieferung", "leistung", "beratung", "artikel", "position"))


def _fmt_pct(value: Decimal) -> str:
    """Formatiert Steuersätze ohne wissenschaftliche Notation (``20`` statt ``2E+1``)."""
    return f"{value.normalize():f}"


def _is_foreign_vat_context(extraction: ExtractionResult, einvoice: EInvoiceData | None) -> bool:
    if einvoice is not None and not einvoice.error:
        country = (einvoice.seller.country or "").strip().upper()
        if country and country != "DE":
            return True
    vat_id = (extraction.sender_vat_id or "").strip().upper()
    if len(vat_id) >= 2 and vat_id[:2].isalpha() and not vat_id.startswith("DE"):
        return True
    currency = (extraction.currency or "EUR").strip().upper()
    return currency != "EUR"


def _allowed_rates(doc_date: date | None) -> set[Decimal]:
    allowed = set(_VALID_RATES)
    if doc_date and date(2020, 7, 1) <= doc_date <= date(2020, 12, 31):
        allowed |= _COVID_RATES
    return {value.normalize() for value in allowed}


def _structured_vat_checks(
    einvoice: EInvoiceData, doc_date: date | None, *, foreign: bool = False
) -> list[ScoreCheck]:
    """Steuerprüfung je Steuersatz aus der XML-Aufschlüsselung (BG-23) - auch bei Mischsätzen."""
    checks: list[ScoreCheck] = []
    rates = [entry.rate for entry in einvoice.vat_breakdown if entry.rate is not None]
    if rates:
        invalid = sorted({rate.normalize() for rate in rates} - _allowed_rates(doc_date))
        if invalid and foreign and all(Decimal(0) <= r <= Decimal(30) for r in invalid):
            checks.append(
                ScoreCheck(
                    id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)", legal_reference="§ 12 UStG",
                    status=CheckStatus.WARN, deduction=0,
                    detail=(
                        "Ausländischer Steuersatz "
                        + ", ".join(f"{_fmt_pct(rate)} %" for rate in invalid)
                        + " erkannt – Zulässigkeit im Ausstellerland prüfen."
                    ),
                    evidence_source="xml",
                )
            )
        else:
            checks.append(
                ScoreCheck(
                    id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)", legal_reference="§ 12 UStG",
                    status=CheckStatus.FAIL if invalid else CheckStatus.PASS, deduction=10 if invalid else 0,
                    detail=(
                        "Steuersatz "
                        + ", ".join(f"{_fmt_pct(rate)} %" for rate in invalid)
                        + " ist zum Rechnungsdatum nicht zulässig."
                        if invalid else None
                    ),
                    evidence_source="xml",
                )
            )
    net, tax, gross = einvoice.net_total, einvoice.tax_total, einvoice.grand_total
    if net is not None and tax is not None and gross is not None:
        ok = abs(net + tax - gross) <= _MONEY_TOLERANCE
        checks.append(
            ScoreCheck(
                id="sum_check", label="Netto + Umsatzsteuer = Brutto (BT-109 + BT-110 = BT-112)",
                status=CheckStatus.PASS if ok else CheckStatus.FAIL, deduction=0 if ok else 15,
                detail=None if ok else f"{net} + {tax} ergibt {net + tax}, ausgewiesen sind {gross}.",
                evidence_source="xml",
            )
        )
    deviations = []
    for entry in einvoice.vat_breakdown:
        if entry.rate is None or entry.taxable_amount is None or entry.tax_amount is None:
            continue
        expected = (entry.taxable_amount * entry.rate / Decimal(100)).quantize(Decimal("0.01"))
        if abs(expected - entry.tax_amount) > _MONEY_TOLERANCE:
            deviations.append(f"{_fmt_pct(entry.rate)} %: erwartet {expected}, ausgewiesen {entry.tax_amount}")
    if any(entry.tax_amount is not None for entry in einvoice.vat_breakdown):
        checks.append(
            ScoreCheck(
                id="tax_calc", label="Umsatzsteuer = Bemessungsgrundlage x Steuersatz (je Satz)",
                legal_reference="§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
                status=CheckStatus.FAIL if deviations else CheckStatus.PASS, deduction=10 if deviations else 0,
                detail="; ".join(deviations) + "." if deviations else None,
                evidence_source="xml",
            )
        )
    br_co = [rule for rule in einvoice.rule_violations if rule.startswith("BR-CO-")]
    if br_co:
        checks.append(
            ScoreCheck(
                id="einvoice_math",
                label="EN-16931 Summenregeln (BR-CO)",
                legal_reference="EN 16931-1",
                status=CheckStatus.WARN,
                deduction=0,
                detail="; ".join(br_co[:3]),
                evidence_source="xml_rule",
            )
        )
    return checks


def _math_tile(
    extraction: ExtractionResult, facts: TextFacts, einvoice: EInvoiceData | None = None, *, structured: bool = False
) -> ScoreTile:
    checks: list[ScoreCheck] = []

    if extraction.iban:
        valid = iban_checksum_valid(extraction.iban)
        checks.append(
            ScoreCheck(
                id="iban_mod97", label="IBAN-Prüfziffer (ISO 13616, MOD-97-10)",
                legal_reference="ISO 13616",
                status=CheckStatus.PASS if valid else CheckStatus.FAIL,
                deduction=0 if valid else 15,
                detail=None if valid else "Prüfziffer ungültig – Zahlungsziel nicht verifizierbar (Betrugsrisiko).",
                evidence_source="rule_based",
            )
        )
    else:
        checks.append(
            ScoreCheck(id="iban_mod97", label="IBAN-Prüfziffer (ISO 13616, MOD-97-10)",
                       status=CheckStatus.NOT_APPLICABLE, detail="Keine IBAN im Dokument.")
        )

    foreign = _is_foreign_vat_context(extraction, einvoice)
    if extraction.doc_type is DocType.INVOICE and structured and einvoice is not None:
        checks.extend(_structured_vat_checks(einvoice, extraction.document_date, foreign=foreign))
    elif extraction.doc_type is DocType.INVOICE:
        net = extraction.net_amount if extraction.net_amount is not None else facts.net_amount
        tax = extraction.tax_amount if extraction.tax_amount is not None else facts.tax_amount
        rate = extraction.tax_rate if extraction.tax_rate is not None else facts.tax_rate
        gross = extraction.total_amount if extraction.total_amount is not None else facts.gross_amount

        if rate is not None:
            ok = rate.normalize() in _allowed_rates(extraction.document_date)
            if not ok and foreign and Decimal(0) <= rate <= Decimal(30):
                checks.append(
                    ScoreCheck(
                        id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)",
                        legal_reference="§ 12 UStG",
                        status=CheckStatus.WARN,
                        deduction=0,
                        detail=f"Ausländischer Steuersatz {_fmt_pct(rate)} % erkannt – Zulässigkeit im Ausstellerland prüfen.",
                        evidence_source="rule_based",
                    )
                )
            else:
                checks.append(
                    ScoreCheck(
                        id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)",
                        legal_reference="§ 12 UStG",
                        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                        deduction=0 if ok else 10,
                        detail=None if ok else f"Steuersatz {_fmt_pct(rate)} % ist zum Rechnungsdatum nicht zulässig.",
                        evidence_source="rule_based",
                    )
                )
        if net is not None and tax is not None and gross is not None:
            ok = abs(net + tax - gross) <= _MONEY_TOLERANCE
            checks.append(
                ScoreCheck(
                    id="sum_check", label="Netto + Umsatzsteuer = Brutto",
                    status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                    deduction=0 if ok else 15,
                    detail=None if ok else f"{net} + {tax} ergibt {net + tax}, ausgewiesen sind {gross}.",
                    evidence_source="rule_based",
                )
            )
        if net is not None and tax is not None and rate is not None:
            expected = (net * rate / Decimal(100)).quantize(Decimal("0.01"))
            ok = abs(expected - tax) <= _MONEY_TOLERANCE
            allowed = _allowed_rates(extraction.document_date)
            positive_rates = sorted({r.normalize() for r in facts.tax_rates if r > 0 and r.normalize() in allowed})
            low_bound, high_bound = (
                sorted((net * positive_rates[0] / Decimal(100), net * positive_rates[-1] / Decimal(100)))
                if len(positive_rates) > 1
                else (Decimal(0), Decimal(0))
            )
            mixed_plausible = (
                not ok
                and len(positive_rates) > 1
                and gross is not None
                and abs(net + tax - gross) <= _MONEY_TOLERANCE
                and (low_bound - _MONEY_TOLERANCE) <= tax <= (high_bound + _MONEY_TOLERANCE)
            )
            # Steuerfreie Einzelposten (z. B. Porto als durchlaufender Posten): Die Steuer liegt
            # dann unter Netto x Satz, die Summe stimmt aber - Prüfhinweis statt Mangel.
            partly_exempt_plausible = (
                not ok
                and not mixed_plausible
                and (facts.exemption or bool(extraction.tax_exemption_note))
                and gross is not None
                and abs(net + tax - gross) <= _MONEY_TOLERANCE
                and Decimal(0) <= tax <= expected + _MONEY_TOLERANCE
            )
            if partly_exempt_plausible:
                checks.append(
                    ScoreCheck(
                        id="tax_calc", label="Umsatzsteuer = Netto x Steuersatz",
                        legal_reference="§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
                        status=CheckStatus.WARN,
                        deduction=0,
                        detail=(
                            "Steuerfreie Positionen erkannt – Netto + USt = Brutto stimmt; "
                            "Bemessungsgrundlage je Steuersatz manuell prüfen."
                        ),
                        evidence_source="rule_based",
                    )
                )
            elif mixed_plausible:
                rates_str = " / ".join(f"{_fmt_pct(r)} %" for r in positive_rates)
                checks.append(
                    ScoreCheck(
                        id="tax_calc", label="Umsatzsteuer = Netto x Steuersatz",
                        legal_reference="§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
                        status=CheckStatus.WARN,
                        deduction=0,
                        detail=f"Mischsteuersätze ({rates_str}) erkannt – Netto + USt = Brutto stimmt; Aufschlüsselung im PDF-Text manuell prüfen.",
                        evidence_source="rule_based",
                    )
                )
            else:
                checks.append(
                    ScoreCheck(
                        id="tax_calc", label="Umsatzsteuer = Netto x Steuersatz",
                        legal_reference="§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
                        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                        deduction=0 if ok else 10,
                        detail=None if ok else f"Erwartet {expected}, ausgewiesen {tax}.",
                        evidence_source="rule_based",
                    )
                )
        # § 14c UStG: Widerspruch zwischen Steuerbefreiung/Reverse Charge und ausgewiesener USt.
        exemption_claimed = facts.full_exemption or full_exemption_claim(extraction.tax_exemption_note)
        if exemption_claimed and tax is not None and abs(tax) > _MONEY_TOLERANCE:
            checks.append(
                ScoreCheck(
                    id="ustg_14c_conflict",
                    label="Kein unberechtigter Steuerausweis bei Befreiung/Reverse Charge",
                    legal_reference="§ 14c UStG",
                    status=CheckStatus.FAIL,
                    deduction=10,
                    detail=(
                        f"Widerspruch: Hinweis auf Steuerbefreiung/Reverse Charge, dennoch Umsatzsteuer ({tax}) "
                        "ausgewiesen (§ 14c UStG – Gefährdung des Vorsteuerabzugs)."
                    ),
                    evidence_source="rule_based",
                )
            )

    iban_part = next(c for c in checks if c.id == "iban_mod97")
    parts = []
    if iban_part.status is CheckStatus.PASS:
        parts.append("IBAN valide")
    elif iban_part.status is CheckStatus.FAIL:
        parts.append("IBAN ungültig")
    vat_checks = [c for c in checks if c.id in {"vat_rate", "sum_check", "tax_calc", "ustg_14c_conflict", "einvoice_math"}]
    if vat_checks:
        if any(c.status is CheckStatus.FAIL for c in vat_checks):
            parts.append("MwSt.-Fehler")
        elif any(c.status is CheckStatus.WARN for c in vat_checks):
            parts.append("Prüfhinweis (MwSt. / Summen)")
        else:
            parts.append("MwSt. korrekt berechnet")
    return _tile("math", "Mathematische Validität (MOD-97 & MwSt.)", checks, " · ".join(parts) or "Keine Beträge prüfbar")


def _regulatory_tile(compliance: ComplianceAudit, facts: TextFacts) -> tuple[ScoreTile, int | None, str | None]:
    level = compliance.ai_act.overall_risk_level
    ref = "VO (EU) 2024/1689"
    cap: int | None = None
    cap_reason: str | None = None

    if level is AIActRiskLevel.UNACCEPTABLE:
        check = ScoreCheck(id="ai_act", label="Verbotene KI-Praktik", legal_reference="Art. 5 " + ref,
                           status=CheckStatus.FAIL, deduction=50,
                           detail="Einsatz ist unionsrechtlich untersagt (seit 02.02.2025).")
        cap, cap_reason = UNACCEPTABLE_CAP, "Verbotene Praktik nach Art. 5 EU AI Act"
        headline = "Verbotene Praktik (Art. 5)"
    elif level is AIActRiskLevel.HIGH:
        labels = sorted({label for system in compliance.ai_act.systems for label in system.annex_iii_labels})
        where = ", ".join(labels) or "Anhang III"
        if facts.conformity_evidence:
            check = ScoreCheck(id="ai_act", label="Hochrisiko-KI-System", legal_reference="Art. 6 Abs. 2 " + ref,
                               status=CheckStatus.WARN, deduction=10,
                               detail=f"{where}. Hinweis auf Konformitätsbewertung vorhanden – Nachweis prüfen (Art. 43).")
        else:
            check = ScoreCheck(id="ai_act", label="Hochrisiko-KI-System", legal_reference="Art. 6 Abs. 2 " + ref,
                               status=CheckStatus.FAIL, deduction=25,
                               detail=f"{where}. Kein Nachweis einer Konformitätsbewertung (Art. 43) und "
                                      "CE-Kennzeichnung (Art. 48); Betreiberpflichten nach Art. 26 beachten.")
            cap, cap_reason = HIGH_RISK_CAP, "Hochrisiko-KI (Anhang III) ohne Konformitätsnachweis"
        check.note = (
            "Art. 6 Abs. 3: Ausnahme möglich bei eng begrenzten oder rein vorbereitenden Aufgaben ohne "
            "Profiling – Profiling natürlicher Personen ist immer Hochrisiko. Das System eskaliert "
            "konservativ auf Hochrisiko. Die Pflichten für Anhang-III-Systeme gelten nach der Änderung durch "
            "VO (EU) 2026/1744 ab dem 02.12.2027."
        )
        headline = "Hochrisiko (Anhang III)"
    elif level is AIActRiskLevel.LIMITED:
        check = ScoreCheck(id="ai_act", label="KI mit Transparenzpflichten", legal_reference="Art. 50 " + ref,
                           status=CheckStatus.WARN, deduction=5,
                           detail="Kennzeichnungs- und Informationspflichten nach Art. 50 sicherstellen.")
        headline = "Begrenztes Risiko (Art. 50)"
    elif level is AIActRiskLevel.MINIMAL:
        check = ScoreCheck(id="ai_act", label="KI-System mit minimalem Risiko", legal_reference=ref,
                           status=CheckStatus.PASS,
                           detail="Keine spezifischen Pflichten; Maßnahmen zur KI-Kompetenz nach Art. 4 ergreifen.")
        headline = "Minimales Risiko"
    else:
        check = ScoreCheck(id="ai_act", label="Kein KI-System beschrieben", legal_reference="Art. 3 Nr. 1 " + ref,
                           status=CheckStatus.PASS)
        headline = "Nicht einschlägig"
    return _tile("regulatory", "Regulatorisches Risiko (EU AI Act)", [check], headline), cap, cap_reason


def _records(count: int) -> str:
    return f"{count} Datensatz" if count == 1 else f"{count} Datensätze"


def _privacy_tile(compliance: ComplianceAudit) -> ScoreTile:
    findings = compliance.gdpr.findings
    categories = {finding.category for finding in findings}
    checks: list[ScoreCheck] = []
    special = categories & SPECIAL_CATEGORIES
    if special:
        checks.append(
            ScoreCheck(
                id="gdpr_art9", label="Besondere Kategorien personenbezogener Daten",
                legal_reference="Art. 9 / Art. 10 DSGVO", status=CheckStatus.FAIL, deduction=10,
                detail="Rechtsgrundlage nach Art. 9 Abs. 2 DSGVO ist im Dokument nicht belegt; "
                       "Zugriff beschränken und Erforderlichkeit prüfen.",
            )
        )
    ids = categories & {PIICategory.ID_DOCUMENT_NUMBER, PIICategory.SOCIAL_SECURITY_NUMBER, PIICategory.TAX_ID}
    if ids:
        checks.append(
            ScoreCheck(
                id="gdpr_identifiers", label="Amtliche Kennnummern natürlicher Personen",
                legal_reference="Art. 87 DSGVO i. V. m. § 139b AO", status=CheckStatus.WARN, deduction=5,
                detail="Verarbeitung nur bei gesetzlicher Grundlage; Speicherbegrenzung (Art. 5 Abs. 1 lit. e).",
            )
        )
    if not checks:
        checks.append(
            ScoreCheck(
                id="gdpr_basic", label="Personenbezogene Daten maskiert", legal_reference="Art. 5, 25 DSGVO",
                status=CheckStatus.PASS,
                detail=f"{_records(len(findings))} erkannt und maskiert." if findings else "Keine PII erkannt.",
            )
        )
    headline = f"{_records(len(findings))} maskiert" if findings else "0 PII-Funde"
    if special:
        headline = f"Art. 9/10: {len(special)} Kategorie(n)"
    return _tile("privacy", "Datenschutz-Integrität (DSGVO)", checks, headline)


# ---------------------------------------------------------------------------
# Risikoerklärung je Mangel (ein Satz, für Tooltips und Zertifikat)
# ---------------------------------------------------------------------------

RISK_NOTES: dict[str, str] = {
    "ustg_1_sender": "Ohne vollständige Anschrift des Ausstellers ist die Rechnung nicht ordnungsgemäß und der Vorsteuerabzug nach § 15 UStG gefährdet.",
    "ustg_1_recipient": "Fehlt die Anschrift des Leistungsempfängers, kann das Finanzamt den Vorsteuerabzug nach § 15 UStG versagen.",
    "ustg_2_tax_id": "Ohne Steuernummer oder USt-IdNr. entfällt der Vorsteuerabzug nach § 15 UStG.",
    "ustg_3_date": "Ohne Ausstellungsdatum lässt sich der Zeitpunkt des Vorsteuerabzugs nicht bestimmen.",
    "ustg_4_number": "Ohne eindeutige Rechnungsnummer ist die Rechnung nicht ordnungsgemäß, und Doppelzahlungen bleiben unerkannt.",
    "ustg_5_items": "Ohne hinreichend konkrete Leistungsbeschreibung kann der Vorsteuerabzug versagt werden.",
    "ustg_6_service_date": "Ohne Leistungszeitpunkt lässt sich die Steuerentstehung nicht zuordnen; der Hinweis „Leistungsdatum entspricht Rechnungsdatum“ genügt.",
    "ustg_7_net": "Ohne ausgewiesenes Nettoentgelt ist der Steuerbetrag nicht nachprüfbar.",
    "ustg_8_rate": "Ohne Steuersatz oder Befreiungshinweis bleibt offen, ob die Steuer zutreffend berechnet ist.",
    "ustg_8_amount": "Als Vorsteuer abziehbar ist höchstens die gesondert ausgewiesene Steuer; ohne Steuerbetrag entfällt der Abzug.",
    "en16931": "Ab 2027 bzw. 2028 erfüllt eine reine PDF-Rechnung im inländischen B2B-Verkehr die Rechnungspflicht nicht mehr.",
    "xml_primacy": "Maßgeblich ist der XML-Datensatz; ein abweichender Bildteil kann als weitere Rechnung gewertet werden und bei höherem Steuerausweis eine Steuerschuld nach § 14c UStG auslösen.",
    "leitweg_id": "Ohne gültige Leitweg-ID kann die Eingangsplattform des Auftraggebers die Rechnung nicht zuordnen und weist sie zurück; die Zahlung verzögert sich.",
    "iban_mod97": "Eine IBAN mit falscher Prüfziffer ist ein typisches Merkmal von Zahlungsumleitungsbetrug – vor Zahlung auf bekanntem Weg verifizieren.",
    "vat_rate": "Bei zu niedrigem Steuerausweis schuldet der Lieferant die gesetzliche Steuer, der Empfänger kann aber nur den ausgewiesenen Betrag als Vorsteuer abziehen.",
    "sum_check": "Rechenfehler zwischen Netto, Steuer und Brutto führen zu falsch gebuchter Vorsteuer und Zahlungsdifferenzen.",
    "tax_calc": "Zu hoch ausgewiesene Steuer schuldet der Aussteller nach § 14c Abs. 1 UStG, zu niedrig ausgewiesene ist nur in ausgewiesener Höhe abziehbar.",
    "ai_act_high": "Hochrisiko-KI nach Anhang III darf ab dem 02.12.2027 nur mit Konformitätsbewertung betrieben werden; Verstöße kosten bis zu 15 Mio. € oder 3 % des Jahresumsatzes (Art. 99 Abs. 4).",
    "ai_act_unacceptable": "Verbotene Praktiken sind seit 02.02.2025 untersagt; das Bußgeld reicht bis 35 Mio. € oder 7 % des weltweiten Jahresumsatzes (Art. 99 Abs. 3).",
    "ai_act_limited": "Verstöße gegen die Transparenzpflichten nach Art. 50 können mit bis zu 15 Mio. € oder 3 % des Jahresumsatzes geahndet werden.",
    "gdpr_art9": "Verarbeitung besonderer Kategorien ohne Rechtsgrundlage nach Art. 9 Abs. 2 kann mit bis zu 20 Mio. € oder 4 % des Jahresumsatzes geahndet werden (Art. 83 Abs. 5 DSGVO).",
    "gdpr_identifiers": "Amtliche Kennnummern sind besonders missbrauchsanfällig (Identitätsdiebstahl) und dürfen nur mit Rechtsgrundlage gespeichert werden.",
}

#: Rechtlicher Kontext, der unabhängig vom Ergebnis angezeigt wird.
CHECK_NOTES: dict[str, str] = {
    "tax_calc": (
        "Bei Rechnungen ausschließlich an Endverbraucher entsteht keine Steuerschuld aus § 14c UStG "
        "(EuGH, Urteil vom 08.12.2022, C-378/21; BMF-Schreiben vom 27.02.2024)."
    ),
}


def _annotate(tiles: list[ScoreTile], compliance: ComplianceAudit) -> None:
    level = compliance.ai_act.overall_risk_level.value
    for tile in tiles:
        for check in tile.checks:
            key = f"ai_act_{level}" if check.id == "ai_act" else check.id
            if check.status in (CheckStatus.FAIL, CheckStatus.WARN) and key in RISK_NOTES and not check.risk_note:
                if check.id == "xml_primacy" and not check.deduction:
                    continue  # nur fehlende Werte im Bildteil: kein Risiko, nur Hinweis
                check.risk_note = RISK_NOTES[key]
            if check.id in CHECK_NOTES and check.note is None:
                check.note = CHECK_NOTES[check.id]


# ---------------------------------------------------------------------------
# Gesamtscore
# ---------------------------------------------------------------------------


def band_for(score: int) -> ScoreBand:
    if score >= GREEN_THRESHOLD:
        return ScoreBand.GREEN
    if score >= AMBER_THRESHOLD:
        return ScoreBand.AMBER
    return ScoreBand.RED


BAND_LABELS = {
    ScoreBand.GREEN: "Vollständig verkehrsfähig & konform",
    ScoreBand.AMBER: "Nachbesserung erforderlich",
    ScoreBand.RED: "Revisionssperre / schwerer Rechtsverstoß",
}
RESERVATION_PREFIX = "Freigabe unter Vorbehalt"


def verdict_band(score: int, *, blocked: bool, recommendation: str) -> tuple[ScoreBand, str]:
    """Ampel und Etikett folgen der Freigabeentscheidung, nicht nur dem Score.

    Grün („Vollständig verkehrsfähig & konform“) gibt es nur ohne Mängel und ohne
    Vorbehalt; eine gesperrte Freigabe oder ein Vorbehalt färbt mindestens gelb.
    """
    band = band_for(score)
    if band is ScoreBand.RED:
        return band, BAND_LABELS[band]
    if blocked:
        label = "Nachforderung nötig" if "Nachforderung" in recommendation else "Freigabe gesperrt"
        return ScoreBand.AMBER, label
    if recommendation.startswith(RESERVATION_PREFIX):
        return ScoreBand.AMBER, RESERVATION_PREFIX
    return band, BAND_LABELS[band]


def presented_band(scorecard: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Ampel und Etikett eines gespeicherten Ergebnisses, auch aus älteren Versionen.

    Ältere Scorecards trugen ein reines Score-Band („grün“ neben „Freigabe
    gesperrt“).  Gespeichert bleibt der Stand unverändert; nur die Anzeige folgt
    der Freigabeentscheidung.
    """
    if not scorecard or scorecard.get("score") is None:
        return (scorecard or {}).get("band"), (scorecard or {}).get("band_label")
    band, label = verdict_band(
        int(scorecard["score"]),
        blocked=bool(scorecard.get("release_blocked")),
        recommendation=str(scorecard.get("release_recommendation") or ""),
    )
    if band.value == scorecard.get("band"):
        return band.value, scorecard.get("band_label") or label
    return band.value, label


def compute_scorecard(
    extraction: ExtractionResult,
    compliance: ComplianceAudit,
    text: str,
    *,
    enforce_ustg_check: bool = True,
    pdf_bytes: bytes | None = None,
    einvoice: EInvoiceData | None = None,
    structured: bool = False,
) -> Scorecard:
    """Berechnet Score, Bänder, Kacheln und Freigabeempfehlung deterministisch.

    ``einvoice`` ist der ausgelesene EN-16931-Datensatz; ``structured`` zeigt an,
    dass die Extraktion aus diesem Datensatz stammt (XML-Pfad statt LLM).
    """
    facts = analyze_text(text or "")
    marker = detect_structured_einvoice(pdf_bytes)

    formal, required, fulfilled, small = _formal_tile(
        extraction, facts, text or "", enforce=enforce_ustg_check, marker=marker,
        einvoice=einvoice, structured=structured,
    )
    regulatory, cap, cap_reason = _regulatory_tile(compliance, facts)
    privacy = _privacy_tile(compliance)
    math = _math_tile(extraction, facts, einvoice, structured=structured)
    tiles = [formal, regulatory, privacy, math]
    _annotate(tiles, compliance)

    raw = 100 - sum(tile.deduction for tile in tiles)
    score = max(0, min(100, raw))
    applied: str | None = None
    if cap is not None and score > cap:
        score, applied = cap, f"Gedeckelt auf {cap}: {cap_reason}"
    band = band_for(score)

    has_fail = any(tile.status is CheckStatus.FAIL for tile in tiles)
    has_math_warn = any(check.id == "einvoice_math" and check.status is CheckStatus.WARN for check in math.checks)
    is_invoice = extraction.doc_type is DocType.INVOICE
    if compliance.ai_act.overall_risk_level is AIActRiskLevel.UNACCEPTABLE:
        recommendation, blocked = (
            "Freigabe gesperrt — verbotene KI-Praktik nach Art. 5 EU AI Act (Einsatz untersagt)",
            True,
        )
    elif regulatory.status is CheckStatus.FAIL:
        recommendation, blocked = "Freigabe gesperrt — Konformitätsbewertung nach Art. 43 EU AI Act nachweisen", True
    elif band is ScoreBand.RED or (has_fail and is_invoice):
        recommendation, blocked = "Freigabe gesperrt — Nachforderung nötig", True
    elif any(check.id == "xml_primacy" and check.deduction for check in formal.checks):
        recommendation, blocked = "Freigabe unter Vorbehalt — Abweichung zwischen XML und PDF klären (XML maßgeblich)", False
    elif is_invoice and xrechnung_deviation(einvoice):
        recommendation, blocked = XRECHNUNG_RESERVATION, False
    elif is_invoice and has_math_warn:
        recommendation, blocked = "Freigabe unter Vorbehalt — EN-16931 Summenregel (BR-CO) verletzt", False
    elif has_fail or band is ScoreBand.AMBER:
        recommendation, blocked = "Freigabe unter Vorbehalt — Nachbesserung empfohlen", False
    elif is_invoice:
        recommendation, blocked = "Zur Auszahlung freigegeben", False
    else:
        recommendation, blocked = "Freigabe empfohlen — Prüfung ohne Befund", False
    band, band_label = verdict_band(score, blocked=blocked, recommendation=recommendation)

    retention = None
    if is_invoice and extraction.document_date is not None:
        from app.retention import RETENTION_NOTE, invoice_retention

        period = invoice_retention(extraction.document_date)
        if period is not None:
            retention = RetentionInfo(
                years=period.years,
                until=period.until,
                financial_sector_until=period.financial_sector_until,
                basis=period.basis,
                note=(
                    f"{RETENTION_NOTE} Kreditinstitute, Versicherungen und Wertpapierinstitute: 10 Jahre. "
                    "Die Verfahrensdokumentation ist 10 Jahre aufzubewahren (§ 147 Abs. 1 Nr. 1 AO)."
                ),
            )

    return Scorecard(
        score=score,
        band=band,
        band_label=band_label,
        cap_applied=applied,
        tiles=tiles,
        release_recommendation=recommendation,
        release_blocked=blocked,
        ustg_required_total=required,
        ustg_fulfilled=fulfilled,
        small_amount_invoice=small,
        structured_einvoice_detected=marker or (einvoice is not None and not einvoice.error),
        computed_at=utcnow(),
        ruleset_version=RULESET_VERSION,
        retention=retention,
    )
