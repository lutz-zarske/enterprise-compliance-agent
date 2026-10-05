"""Deterministische Compliance-Scorecard (0-100).

Der Score entsteht **nicht** im LLM, sondern aus festen, versionierten Regeln
ueber die validierte Extraktion, das Audit und den Dokumenttext.  Dieselbe
Eingabe ergibt immer denselben Score - Voraussetzung für eine Prüfung, die
ein Wirtschaftsprüfer nachvollziehen und nachrechnen kann.

Jede Pflichtangabe wird doppelt belegt: zuerst aus der LLM-Extraktion, dann
per Regex direkt im Dokumenttext.  ``evidence_source`` weist aus, woher der
Nachweis stammt (``llm``, ``rule_based``, ``both``).

Bewertungsschema (Basis 100, Abzüge je Mangel):

* Formelle Gültigkeit, Paragraf 14 Abs. 4 UStG (nur Rechnungen):
  fehlende Steuernummer/USt-IdNr. -20, jede weitere fehlende Pflichtangabe -10.
  Kleinbetragsrechnungen bis 250 EUR brutto: reduzierter Katalog (Paragraf 33 UStDV).
* E-Rechnung (seit Regelwerk 2026.2): Abweichung zwischen massgeblichem
  XML-Datensatz und PDF-Bildteil -10 (BMF 15.10.2024, Rz. 36); fehlende oder
  ungueltige Leitweg-ID bei oeffentlichen Auftraggebern -10 (Paragraf 5 ERechV).
  Profil- und Geschaeftsregel-Befunde (EN 16931) sind Hinweise ohne Abzug.
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
    ScoreBand,
    ScoreCheck,
    Scorecard,
    ScoreTile,
    iban_checksum_valid,
)

RULESET_VERSION = "2026.2"

#: Grenze der Kleinbetragsrechnung nach Paragraf 33 UStDV (seit 01.01.2017).
SMALL_AMOUNT_LIMIT = Decimal("250")

GREEN_THRESHOLD = 85
AMBER_THRESHOLD = 60
HIGH_RISK_CAP = 59
UNACCEPTABLE_CAP = 20

_MONEY_TOLERANCE = Decimal("0.02")

# --- Regex-Belege im Dokumenttext ------------------------------------------
_VAT_ID = re.compile(r"\b(?:DE ?\d{9}|ATU\d{8})\b")
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
_AMOUNT = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}|\d+\.\d{2}(?!\d)")
_PERCENT = re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s?%")
_CONFORMITY = re.compile(
    r"konformit(?:ä|ae)tsbewertung|ce-kennzeichnung|eu-konformit(?:ä|ae)tserkl(?:ä|ae)rung|art\.?\s?43",
    re.IGNORECASE,
)
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


def analyze_text(text: str) -> TextFacts:
    net = tax = rate = gross = None
    for line in text.splitlines():
        low = line.casefold()
        amounts = [value for value in (_to_decimal(m) for m in _AMOUNT.findall(line)) if value is not None]
        percents = [value for value in (_to_decimal(m) for m in _PERCENT.findall(line)) if value is not None]
        is_tax_line = re.search(r"\b(ust|mwst|umsatzsteuer|mehrwertsteuer)\b", low) and not re.search(
            r"id|nr\.|nummer|identifikation", low
        )
        if "netto" in low and amounts and net is None:
            net = amounts[-1]
        elif is_tax_line:
            if percents and rate is None:
                rate = percents[0]
            if amounts and tax is None:
                tax = amounts[-1]
        elif re.search(r"brutto|gesamtbetrag|rechnungsbetrag|endbetrag|zu zahlen", low) and amounts:
            gross = amounts[-1]
    return TextFacts(
        vat_id=bool(_VAT_ID.search(text)),
        tax_number=bool(_TAX_NUMBER.search(text)),
        service_date=bool(_SERVICE_DATE.search(text)),
        exemption=bool(_EXEMPTION.search(text)),
        address_count=len(_STREET.findall(text)) + len(_ZIP_CITY.findall(text)),
        net_amount=net,
        tax_amount=tax,
        tax_rate=rate,
        gross_amount=gross,
        conformity_evidence=bool(_CONFORMITY.search(text)),
        positions=bool(_POSITIONS.search(text)),
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
    small = gross is not None and Decimal(0) < gross <= SMALL_AMOUNT_LIMIT
    na_small = "Entbehrlich bei Kleinbetragsrechnungen bis 250 EUR (§ 33 UStDV)."

    addresses_in_text = facts.address_count
    xml_rates = einvoice is not None and any(entry.rate is not None for entry in einvoice.vat_breakdown)
    rate_known = extraction.tax_rate is not None or facts.tax_rate is not None or xml_rates
    tax_known = extraction.tax_amount is not None or facts.tax_amount is not None
    exemption = bool(extraction.tax_exemption_note) or facts.exemption

    def src(llm: bool, rule: bool) -> str | None:
        return _source(llm, rule, structured=structured)

    checks = [
        _check(
            "ustg_1_sender", "Name und Anschrift des leistenden Unternehmers",
            "§ 14 Abs. 4 Satz 1 Nr. 1 UStG",
            bool(extraction.sender) and (bool(extraction.sender_address) or addresses_in_text >= 1),
            10, source=src(bool(extraction.sender_address), addresses_in_text >= 1),
        ),
        _check(
            "ustg_1_recipient", "Name und Anschrift des Leistungsempfängers",
            "§ 14 Abs. 4 Satz 1 Nr. 1 UStG",
            bool(extraction.recipient) and (bool(extraction.recipient_address) or addresses_in_text >= 2),
            10, source=src(bool(extraction.recipient_address), addresses_in_text >= 2),
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
            rate_known or exemption, 10, source=src(extraction.tax_rate is not None, facts.tax_rate is not None),
        ),
        _check(
            "ustg_8_amount", "Auf das Entgelt entfallender Steuerbetrag", "§ 14 Abs. 4 Satz 1 Nr. 8 UStG",
            tax_known or exemption, 10, source=src(extraction.tax_amount is not None, facts.tax_amount is not None),
            required=not small, na_detail=na_small,
        ),
    ]
    required = [check for check in checks if check.status is not CheckStatus.NOT_APPLICABLE]
    fulfilled = sum(check.status is CheckStatus.PASS for check in required)

    checks.append(_en16931_check(einvoice, marker=marker, public=_public_reason(extraction, einvoice) is not None))
    extra: list[ScoreCheck] = []
    primacy = _xml_primacy_check(einvoice)
    if primacy is not None:
        extra.append(primacy)
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
                "Pflichtfelder und Summenregeln (BR-CO-10/13/14/15, BR-DE-15). Keine Validierung gegen XSD "
                "und Schematron (z. B. KoSIT-Validator)."
            )
            if einvoice.rule_violations:
                detail += " Verstöße: " + " ".join(einvoice.rule_violations) + " Kein Punktabzug."
                risk_note = (
                    "Verstöße gegen EN-16931-Geschäftsregeln führen beim Empfänger regelmäßig zur Zurückweisung "
                    "durch den Validator."
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


def _xml_primacy_check(einvoice: EInvoiceData | None) -> ScoreCheck | None:
    """Abgleich XML-Datensatz <-> visueller PDF-Teil (nur hybride Rechnungen)."""
    if einvoice is None or einvoice.error or einvoice.source != "embedded" or not einvoice.visual_check:
        return None
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
            detail=f"Im Bildteil nicht wiedergefunden: {names}. Maßgeblich ist der XML-Datensatz. Kein Punktabzug.",
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
    """Leitweg-ID nur bei oeffentlichen Auftraggebern (B2G) - im B2B-Verkehr nicht erforderlich."""
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


def facts_has_positions(extraction: ExtractionResult) -> bool:
    """Hilfsregel für Nr. 5: Zusammenfassung beschreibt eine konkrete Leistung."""
    summary = (extraction.summary or "").casefold()
    return any(word in summary for word in ("lizenz", "lieferung", "leistung", "beratung", "artikel", "position"))


def _allowed_rates(doc_date: date | None) -> set[Decimal]:
    allowed = set(_VALID_RATES)
    if doc_date and date(2020, 7, 1) <= doc_date <= date(2020, 12, 31):
        allowed |= _COVID_RATES
    return {value.normalize() for value in allowed}


def _structured_vat_checks(einvoice: EInvoiceData, doc_date: date | None) -> list[ScoreCheck]:
    """Steuerpruefung je Steuersatz aus der XML-Aufschluesselung (BG-23) - auch bei Mischsaetzen."""
    checks: list[ScoreCheck] = []
    rates = [entry.rate for entry in einvoice.vat_breakdown if entry.rate is not None]
    if rates:
        invalid = sorted({rate.normalize() for rate in rates} - _allowed_rates(doc_date))
        checks.append(
            ScoreCheck(
                id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)", legal_reference="§ 12 UStG",
                status=CheckStatus.FAIL if invalid else CheckStatus.PASS, deduction=10 if invalid else 0,
                detail=(
                    "Steuersatz " + ", ".join(f"{rate} %" for rate in invalid) + " ist zum Rechnungsdatum nicht zulässig."
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
            deviations.append(f"{entry.rate.normalize()} %: erwartet {expected}, ausgewiesen {entry.tax_amount}")
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

    if extraction.doc_type is DocType.INVOICE and structured and einvoice is not None:
        checks.extend(_structured_vat_checks(einvoice, extraction.document_date))
    elif extraction.doc_type is DocType.INVOICE:
        net = extraction.net_amount if extraction.net_amount is not None else facts.net_amount
        tax = extraction.tax_amount if extraction.tax_amount is not None else facts.tax_amount
        rate = extraction.tax_rate if extraction.tax_rate is not None else facts.tax_rate
        gross = extraction.total_amount if extraction.total_amount is not None else facts.gross_amount

        if rate is not None:
            ok = rate.normalize() in _allowed_rates(extraction.document_date)
            checks.append(
                ScoreCheck(
                    id="vat_rate", label="Zulässiger Umsatzsteuersatz (19 % / 7 % / 0 %)",
                    legal_reference="§ 12 UStG",
                    status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                    deduction=0 if ok else 10,
                    detail=None if ok else f"Steuersatz {rate.normalize()} % ist zum Rechnungsdatum nicht zulässig.",
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

    iban_part = next(c for c in checks if c.id == "iban_mod97")
    parts = []
    if iban_part.status is CheckStatus.PASS:
        parts.append("IBAN valide")
    elif iban_part.status is CheckStatus.FAIL:
        parts.append("IBAN ungültig")
    vat_checks = [c for c in checks if c.id in {"vat_rate", "sum_check", "tax_calc"}]
    if vat_checks:
        parts.append(
            "MwSt. korrekt berechnet"
            if all(c.status is CheckStatus.PASS for c in vat_checks)
            else "MwSt.-Fehler"
        )
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
# Risikoerklaerung je Mangel (ein Satz, fuer Tooltips und Zertifikat)
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

#: Rechtlicher Kontext, der unabhaengig vom Ergebnis angezeigt wird.
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
    is_invoice = extraction.doc_type is DocType.INVOICE
    if regulatory.status is CheckStatus.FAIL:
        recommendation, blocked = "Freigabe gesperrt — Konformitätsbewertung nach Art. 43 EU AI Act nachweisen", True
    elif band is ScoreBand.RED or (has_fail and is_invoice):
        recommendation, blocked = "Freigabe gesperrt — Nachforderung nötig", True
    elif any(check.id == "xml_primacy" and check.deduction for check in formal.checks):
        recommendation, blocked = "Freigabe unter Vorbehalt — Abweichung zwischen XML und PDF klären (XML maßgeblich)", False
    elif has_fail or band is ScoreBand.AMBER:
        recommendation, blocked = "Freigabe unter Vorbehalt — Nachbesserung empfohlen", False
    elif is_invoice:
        recommendation, blocked = "Zur Auszahlung freigegeben", False
    else:
        recommendation, blocked = "Freigabe empfohlen — Prüfung ohne Befund", False

    return Scorecard(
        score=score,
        band=band,
        band_label=BAND_LABELS[band],
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
    )
