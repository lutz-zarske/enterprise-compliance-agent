"""EN-16931-Parser für strukturierte E-Rechnungen (CII und UBL).

Unterstützt
------------
* **UN/CEFACT CII** (``rsm:CrossIndustryInvoice``): ZUGFeRD 2.x, Factur-X 1.x,
  XRechnung in CII-Syntax.
* **OASIS UBL 2.1** (``Invoice`` / ``CreditNote``): XRechnung in UBL-Syntax,
  Peppol BIS Billing 3.0.

Das Profil ergibt sich aus der Spezifikationskennung BT-24.  MINIMUM und
BASIC WL sind nach dem BMF-Schreiben vom 15.10.2024 keine E-Rechnungen im Sinne
von § 14 Abs. 1 UStG; ZUGFeRD 1.0 ist kein EN-16931-Format.

Abgrenzung
----------
Geprüft wird eine Teilmenge der EN-16931-Geschäftsregeln (Pflichtfelder und
Summenregeln BR-CO-10/13/14/15, BR-DE-15).  Das ersetzt keine Validierung gegen
XSD und Schematron (z. B. KoSIT-Validator) - darauf weisen Scorecard und
Zertifikat ausdrücklich hin.

Sicherheit
----------
XML aus Uploads ist nicht vertrauenswürdig.  Geparst wird mit ``defusedxml``
und ``forbid_dtd=True``: keine DTDs, keine Entitäten, keine externen
Referenzen (Schutz vor XXE und "Billion Laughs").
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from app.schemas import (
    DocType,
    EInvoiceData,
    EInvoiceLine,
    EInvoiceParty,
    EInvoiceVat,
    ExtractionResult,
    LeitwegCheck,
    VisualCheck,
)

#: Obergrenze für reine XML-Uploads und eingebettete Datensätze.
MAX_XML_BYTES = 10 * 1024 * 1024

NS_CII = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
NS_UBL = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
_ZUGFERD1_NS = "urn:ferd:CrossIndustryDocument:invoice:1p0"

#: Profile, die nach BMF-Schreiben vom 15.10.2024 keine E-Rechnung sind.
NON_EINVOICE_PROFILES = frozenset({"minimum", "basic_wl"})

_CREDIT_NOTE_CODES = {"381", "389", "396", "532"}
_TWO_PLACES = Decimal("0.01")
_TOLERANCE = Decimal("0.01")
_MAX_ABS_DECIMAL = Decimal("1e15")


class EInvoiceError(Exception):
    """Das XML ist keine auswertbare EN-16931-Rechnung."""

    code = "invalid_einvoice"


class UnsupportedEInvoiceError(EInvoiceError):
    """Erkanntes, aber nicht unterstütztes Format (z. B. ZUGFeRD 1.0)."""

    code = "unsupported_einvoice"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _text(element: Element | None, path: str, ns: dict[str, str]) -> str | None:
    if element is None:
        return None
    found = element.find(path, ns)
    if found is None or found.text is None:
        return None
    value = " ".join(found.text.split())
    return value or None


def _attr(element: Element | None, path: str, attribute: str, ns: dict[str, str]) -> str | None:
    if element is None:
        return None
    found = element.find(path, ns)
    return found.get(attribute) if found is not None else None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not parsed.is_finite() or abs(parsed) > _MAX_ABS_DECIMAL:
        return None
    return parsed


def _date(value: str | None) -> date | None:
    """CII-Format 102 (``YYYYMMDD``) oder ISO-Datum (UBL)."""
    if not value:
        return None
    digits = value.strip()
    try:
        if re.fullmatch(r"\d{8}", digits):
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
        return date.fromisoformat(digits[:10])
    except ValueError:
        return None


def _local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return namespace, local
    return "", tag


def format_money(value: Decimal | None, currency: str | None = "EUR") -> str:
    """Deutsches Betragsformat: 1.234,56 EUR."""
    if value is None:
        return "–"
    text = f"{value.quantize(_TWO_PLACES):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {currency or ''}".strip()


def _format_rate(rate: Decimal | None) -> str:
    if rate is None:
        return "–"
    return f"{rate.normalize():f}".replace(".", ",") + " %"


def _format_date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "–"


# ---------------------------------------------------------------------------
# Profil-Erkennung (BT-24)
# ---------------------------------------------------------------------------


def detect_profile(specification_id: str | None) -> tuple[str, str]:
    """Liefert (profile_key, Anzeigename) zur Spezifikationskennung BT-24."""
    spec = (specification_id or "").strip().casefold()
    if not spec:
        return "unknown", "Unbekannt (BT-24 fehlt)"
    if "xrechnung" in spec:
        match = re.search(r"xrechnung_(\d+(?:\.\d+)*)", spec)
        label = f"XRECHNUNG {match.group(1)}" if match else "XRECHNUNG"
        if "extension" in spec:
            label += " (Extension)"
        return "xrechnung", label
    if "peppol" in spec and "billing" in spec:
        return "peppol", "PEPPOL BIS Billing 3.0"
    if "extended" in spec:
        return "extended", "EXTENDED"
    if "basicwl" in spec:
        return "basic_wl", "BASIC WL"
    if "minimum" in spec:
        return "minimum", "MINIMUM"
    if "basic" in spec:
        return "basic", "BASIC"
    if spec.startswith("urn:cen.eu:en16931:2017"):
        return "en16931", "EN 16931 (COMFORT)"
    return "unknown", "Unbekannt"


# ---------------------------------------------------------------------------
# Leitweg-ID (KoSIT-Formatspezifikation 2.0.2) und öffentliche Auftraggeber
# ---------------------------------------------------------------------------

_LEITWEG = re.compile(r"^(\d{2,12})(?:-([A-Za-z0-9]{1,30}))?-(\d{2})$")


def leitweg_check_digits(coarse: str, fine: str = "") -> str:
    """Prüfziffer nach ISO/IEC 7064 MOD 97-10 (Buchstaben A=10 ... Z=35)."""
    digits = "".join(str(int(char, 36)) for char in (coarse + fine).upper())
    return f"{98 - int(digits + '00') % 97:02d}"


def validate_leitweg_id(value: str) -> LeitwegCheck:
    """Prüft Aufbau (Grob-/Feinadressierung, 5-46 Zeichen) und Prüfziffer."""
    candidate = value.strip()
    match = _LEITWEG.fullmatch(candidate)
    if not match or not 5 <= len(candidate) <= 46:
        return LeitwegCheck(
            value=candidate, valid=False,
            reason="Kein Leitweg-ID-Format (Grobadressierung-[Feinadressierung-]Prüfziffer).",
        )
    coarse, fine, check = match.group(1), match.group(2) or "", match.group(3)
    expected = leitweg_check_digits(coarse, fine)
    if expected != check:
        return LeitwegCheck(
            value=candidate, valid=False, reason=f"Prüfziffer ungültig (erwartet {expected}, angegeben {check})."
        )
    return LeitwegCheck(value=candidate, valid=True)


_PUBLIC_BUYER = re.compile(
    r"\b(?:bundes(?:amt|ministerium|anstalt|agentur|behörde|kanzleramt|verwaltungsamt|polizei|wehr|republik)"
    r"|landes(?:amt|ministerium|verwaltung|behörde|betrieb|hauptkasse)|ministerium|senatsverwaltung|senatskanzlei"
    r"|staatskanzlei|bezirksamt|landratsamt|kreisverwaltung|landkreis|stadtverwaltung|gemeindeverwaltung"
    r"|gemeinde|stadt|magistrat|regierungspräsidium|bezirksregierung|finanzamt|polizeipräsidium|behörde"
    r"|freistaat|hansestadt|amtsgericht|landgericht|oberlandesgericht"
    r"|(?:körperschaft|anstalt) des öffentlichen rechts)\b",
    re.IGNORECASE,
)

#: Peppol-Schema 0204 = Leitweg-ID als elektronische Adresse.
LEITWEG_SCHEME = "0204"


def detect_public_buyer(buyer_name: str | None, invoice: EInvoiceData | None = None) -> str | None:
    """Begründung, warum ein öffentlicher Auftraggeber (B2G) vorliegt, sonst ``None``.

    Heuristik: Behördenbegriff im Käufernamen, Leitweg-ID als elektronische
    Adresse (Peppol-Schema 0204) oder Leitweg-ID-Format in BT-10.
    """
    if invoice is not None:
        if invoice.buyer.electronic_address_scheme == LEITWEG_SCHEME:
            return "Elektronische Adresse des Käufers ist eine Leitweg-ID (Schema 0204)."
        if invoice.buyer_reference and validate_leitweg_id(invoice.buyer_reference).valid:
            return "Käuferreferenz (BT-10) ist eine gültige Leitweg-ID."
    if buyer_name:
        match = _PUBLIC_BUYER.search(buyer_name)
        if match:
            return f"Käufer „{buyer_name}“ ist als öffentliche Stelle erkennbar („{match.group(0)}“)."
    return None


_LEITWEG_IN_TEXT = re.compile(r"leitweg[\w\-]*\s*(?:id|nr\.?|nummer)?\s*[:#]?\s*([0-9A-Za-z\-]{5,46})", re.IGNORECASE)


def find_leitweg_in_text(text: str) -> str | None:
    """Leitweg-ID aus einem PDF-Text (Beschriftung „Leitweg-ID: …“)."""
    match = _LEITWEG_IN_TEXT.search(text or "")
    return match.group(1).strip("-") if match else None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_root(data: bytes) -> Element:
    if not data or not data.strip():
        raise EInvoiceError("Die XML-Datei ist leer.")
    if len(data) > MAX_XML_BYTES:
        raise EInvoiceError(f"Die XML-Datei ist größer als {MAX_XML_BYTES // 1_048_576} MB.")
    try:
        return SafeET.fromstring(data, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise EInvoiceError(
            "Das XML enthält DTD- oder Entitätsdeklarationen und wird aus Sicherheitsgründen abgelehnt."
        ) from exc
    except SafeET.ParseError as exc:
        raise EInvoiceError(f"Das XML ist nicht wohlgeformt: {exc}") from exc


def _cii_party(party: Element | None) -> EInvoiceParty:
    ns = NS_CII
    if party is None:
        return EInvoiceParty()
    vat_id = tax_number = None
    for registration in party.findall("ram:SpecifiedTaxRegistration/ram:ID", ns):
        scheme = (registration.get("schemeID") or "").upper()
        value = " ".join((registration.text or "").split()) or None
        if scheme == "VA":
            vat_id = value
        elif scheme == "FC":
            tax_number = value
    address = party.find("ram:PostalTradeAddress", ns)
    return EInvoiceParty(
        name=_text(party, "ram:Name", ns),
        vat_id=vat_id,
        tax_number=tax_number,
        street=_text(address, "ram:LineOne", ns),
        postcode=_text(address, "ram:PostcodeCode", ns),
        city=_text(address, "ram:CityName", ns),
        country=_text(address, "ram:CountryID", ns),
        electronic_address=_text(party, "ram:URIUniversalCommunication/ram:URIID", ns),
        electronic_address_scheme=_attr(party, "ram:URIUniversalCommunication/ram:URIID", "schemeID", ns),
    )


def _parse_cii(root: Element) -> dict[str, Any]:
    ns = NS_CII
    document = root.find("rsm:ExchangedDocument", ns)
    transaction = root.find("rsm:SupplyChainTradeTransaction", ns)
    agreement = transaction.find("ram:ApplicableHeaderTradeAgreement", ns) if transaction is not None else None
    delivery = transaction.find("ram:ApplicableHeaderTradeDelivery", ns) if transaction is not None else None
    settlement = transaction.find("ram:ApplicableHeaderTradeSettlement", ns) if transaction is not None else None
    totals = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", ns) if settlement is not None else None

    vat = [
        EInvoiceVat(
            category=_text(tax, "ram:CategoryCode", ns),
            rate=_decimal(_text(tax, "ram:RateApplicablePercent", ns)),
            taxable_amount=_decimal(_text(tax, "ram:BasisAmount", ns)),
            tax_amount=_decimal(_text(tax, "ram:CalculatedAmount", ns)),
            exemption_reason=_text(tax, "ram:ExemptionReason", ns) or _text(tax, "ram:ExemptionReasonCode", ns),
        )
        for tax in (settlement.findall("ram:ApplicableTradeTax", ns) if settlement is not None else [])
    ]
    lines = [
        EInvoiceLine(
            line_id=_text(item, "ram:AssociatedDocumentLineDocument/ram:LineID", ns),
            name=_text(item, "ram:SpecifiedTradeProduct/ram:Name", ns),
            quantity=_decimal(_text(item, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", ns)),
            unit=_attr(item, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", "unitCode", ns),
            net_amount=_decimal(
                _text(item, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount", ns)
            ),
            vat_rate=_decimal(
                _text(item, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent", ns)
            ),
            period_start=_date(_text(
                item, "ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString", ns
            )),
            period_end=_date(_text(
                item, "ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString", ns
            )),
        )
        for item in (transaction.findall("ram:IncludedSupplyChainTradeLineItem", ns) if transaction is not None else [])
    ]
    # BT-110 kann zweimal vorkommen (Rechnungs- und Buchungswährung) - die
    # Rechnungswährung ist maßgeblich.
    currency = _text(settlement, "ram:InvoiceCurrencyCode", ns)
    tax_total = None
    if totals is not None:
        for element in totals.findall("ram:TaxTotalAmount", ns):
            if tax_total is None or element.get("currencyID") in (None, currency):
                tax_total = _decimal(element.text)
    terms = settlement.find("ram:SpecifiedTradePaymentTerms", ns) if settlement is not None else None
    return {
        "syntax": "CII",
        "specification_id": _text(
            root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID", ns
        ),
        "invoice_number": _text(document, "ram:ID", ns),
        "type_code": _text(document, "ram:TypeCode", ns),
        "issue_date": _date(_text(document, "ram:IssueDateTime/udt:DateTimeString", ns)),
        "currency": currency,
        "buyer_reference": _text(agreement, "ram:BuyerReference", ns),
        "order_reference": _text(agreement, "ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID", ns),
        "seller": _cii_party(agreement.find("ram:SellerTradeParty", ns) if agreement is not None else None),
        "buyer": _cii_party(agreement.find("ram:BuyerTradeParty", ns) if agreement is not None else None),
        "seller_contact": agreement is not None
        and agreement.find("ram:SellerTradeParty/ram:DefinedTradeContact", ns) is not None,
        "delivery_date": _date(
            _text(delivery, "ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString", ns)
        ),
        "period_start": _date(_text(settlement, "ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString", ns)),
        "period_end": _date(_text(settlement, "ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString", ns)),
        "due_date": _date(_text(terms, "ram:DueDateDateTime/udt:DateTimeString", ns)),
        "payment_terms": _text(terms, "ram:Description", ns),
        "iban": _text(
            settlement, "ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID", ns
        ),
        "line_total": _decimal(_text(totals, "ram:LineTotalAmount", ns)),
        "allowance_total": _decimal(_text(totals, "ram:AllowanceTotalAmount", ns)),
        "charge_total": _decimal(_text(totals, "ram:ChargeTotalAmount", ns)),
        "net_total": _decimal(_text(totals, "ram:TaxBasisTotalAmount", ns)),
        "tax_total": tax_total,
        "grand_total": _decimal(_text(totals, "ram:GrandTotalAmount", ns)),
        "due_payable": _decimal(_text(totals, "ram:DuePayableAmount", ns)),
        "vat_breakdown": vat,
        "lines": lines,
    }


def _ubl_party(party: Element | None) -> EInvoiceParty:
    ns = NS_UBL
    if party is None:
        return EInvoiceParty()
    vat_id = tax_number = None
    for scheme in party.findall("cac:PartyTaxScheme", ns):
        company_id = _text(scheme, "cbc:CompanyID", ns)
        if (_text(scheme, "cac:TaxScheme/cbc:ID", ns) or "").upper() == "VAT":
            vat_id = company_id
        else:
            tax_number = company_id
    address = party.find("cac:PostalAddress", ns)
    return EInvoiceParty(
        name=_text(party, "cac:PartyLegalEntity/cbc:RegistrationName", ns) or _text(party, "cac:PartyName/cbc:Name", ns),
        vat_id=vat_id,
        tax_number=tax_number,
        street=_text(address, "cbc:StreetName", ns),
        postcode=_text(address, "cbc:PostalZone", ns),
        city=_text(address, "cbc:CityName", ns),
        country=_text(address, "cac:Country/cbc:IdentificationCode", ns),
        electronic_address=_text(party, "cbc:EndpointID", ns),
        electronic_address_scheme=_attr(party, "cbc:EndpointID", "schemeID", ns),
    )


def _parse_ubl(root: Element, credit_note: bool) -> dict[str, Any]:
    ns = NS_UBL
    currency = _text(root, "cbc:DocumentCurrencyCode", ns)
    totals = root.find("cac:LegalMonetaryTotal", ns)
    tax_total = None
    vat: list[EInvoiceVat] = []
    for total in root.findall("cac:TaxTotal", ns):
        amount = total.find("cbc:TaxAmount", ns)
        if amount is not None and amount.get("currencyID") in (None, currency):
            tax_total = _decimal(amount.text)
            vat = [
                EInvoiceVat(
                    category=_text(sub, "cac:TaxCategory/cbc:ID", ns),
                    rate=_decimal(_text(sub, "cac:TaxCategory/cbc:Percent", ns)),
                    taxable_amount=_decimal(_text(sub, "cbc:TaxableAmount", ns)),
                    tax_amount=_decimal(_text(sub, "cbc:TaxAmount", ns)),
                    exemption_reason=(
                        _text(sub, "cac:TaxCategory/cbc:TaxExemptionReason", ns)
                        or _text(sub, "cac:TaxCategory/cbc:TaxExemptionReasonCode", ns)
                    ),
                )
                for sub in total.findall("cac:TaxSubtotal", ns)
            ]
    line_tag, quantity_tag = (
        ("cac:CreditNoteLine", "cbc:CreditedQuantity") if credit_note else ("cac:InvoiceLine", "cbc:InvoicedQuantity")
    )
    lines = [
        EInvoiceLine(
            line_id=_text(line, "cbc:ID", ns),
            name=_text(line, "cac:Item/cbc:Name", ns),
            quantity=_decimal(_text(line, quantity_tag, ns)),
            unit=_attr(line, quantity_tag, "unitCode", ns),
            net_amount=_decimal(_text(line, "cbc:LineExtensionAmount", ns)),
            vat_rate=_decimal(_text(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", ns)),
            period_start=_date(_text(line, "cac:InvoicePeriod/cbc:StartDate", ns)),
            period_end=_date(_text(line, "cac:InvoicePeriod/cbc:EndDate", ns)),
        )
        for line in root.findall(line_tag, ns)
    ]
    type_tag = "cbc:CreditNoteTypeCode" if credit_note else "cbc:InvoiceTypeCode"
    return {
        "syntax": "UBL",
        "specification_id": _text(root, "cbc:CustomizationID", ns),
        "invoice_number": _text(root, "cbc:ID", ns),
        "type_code": _text(root, type_tag, ns),
        "issue_date": _date(_text(root, "cbc:IssueDate", ns)),
        "currency": currency,
        "buyer_reference": _text(root, "cbc:BuyerReference", ns),
        "order_reference": _text(root, "cac:OrderReference/cbc:ID", ns),
        "seller": _ubl_party(root.find("cac:AccountingSupplierParty/cac:Party", ns)),
        "buyer": _ubl_party(root.find("cac:AccountingCustomerParty/cac:Party", ns)),
        "seller_contact": root.find("cac:AccountingSupplierParty/cac:Party/cac:Contact", ns) is not None,
        "delivery_date": _date(_text(root, "cac:Delivery/cbc:ActualDeliveryDate", ns)),
        "period_start": _date(_text(root, "cac:InvoicePeriod/cbc:StartDate", ns)),
        "period_end": _date(_text(root, "cac:InvoicePeriod/cbc:EndDate", ns)),
        "due_date": _date(_text(root, "cbc:DueDate", ns)),
        "payment_terms": _text(root, "cac:PaymentTerms/cbc:Note", ns),
        "iban": _text(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID", ns),
        "line_total": _decimal(_text(totals, "cbc:LineExtensionAmount", ns)),
        "allowance_total": _decimal(_text(totals, "cbc:AllowanceTotalAmount", ns)),
        "charge_total": _decimal(_text(totals, "cbc:ChargeTotalAmount", ns)),
        "net_total": _decimal(_text(totals, "cbc:TaxExclusiveAmount", ns)),
        "tax_total": tax_total,
        "grand_total": _decimal(_text(totals, "cbc:TaxInclusiveAmount", ns)),
        "due_payable": _decimal(_text(totals, "cbc:PayableAmount", ns)),
        "vat_breakdown": vat,
        "lines": lines,
    }


def _business_rules(invoice: EInvoiceData) -> list[str]:
    """Teilmenge der EN-16931-Geschäftsregeln (Pflichtfelder und Summen)."""
    violations: list[str] = []
    if invoice.profile_key in NON_EINVOICE_PROFILES:
        return violations
    required = (
        ("BR-02", invoice.invoice_number, "Rechnungsnummer (BT-1)"),
        ("BR-03", invoice.issue_date, "Rechnungsdatum (BT-2)"),
        ("BR-04", invoice.type_code, "Rechnungsart (BT-3)"),
        ("BR-05", invoice.currency, "Rechnungswährung (BT-5)"),
        ("BR-06", invoice.seller.name, "Name des Verkäufers (BT-27)"),
        ("BR-07", invoice.buyer.name, "Name des Käufers (BT-44)"),
        ("BR-09", invoice.seller.country, "Ländercode des Verkäufers (BT-40)"),
        ("BR-11", invoice.buyer.country, "Ländercode des Käufers (BT-55)"),
    )
    for rule, value, label in required:
        if not value:
            violations.append(f"{rule}: {label} fehlt.")
    if not invoice.lines:
        violations.append("BR-16: Die Rechnung enthält keine Position (BG-25).")

    line_amounts = [line.net_amount for line in invoice.lines if line.net_amount is not None]
    if invoice.line_total is not None and line_amounts and len(line_amounts) == len(invoice.lines):
        total = sum(line_amounts, Decimal(0))
        if abs(total - invoice.line_total) > _TOLERANCE:
            violations.append(
                f"BR-CO-10: Summe der Positionen {format_money(total, invoice.currency)} ≠ "
                f"Positionssumme BT-106 {format_money(invoice.line_total, invoice.currency)}."
            )
    if invoice.line_total is not None and invoice.net_total is not None:
        expected = invoice.line_total - (invoice.allowance_total or 0) + (invoice.charge_total or 0)
        if abs(expected - invoice.net_total) > _TOLERANCE:
            violations.append(
                f"BR-CO-13: Netto BT-109 {format_money(invoice.net_total, invoice.currency)} ≠ "
                f"BT-106 − BT-107 + BT-108 = {format_money(expected, invoice.currency)}."
            )
    vat_amounts = [entry.tax_amount for entry in invoice.vat_breakdown if entry.tax_amount is not None]
    if invoice.tax_total is not None and vat_amounts:
        total = sum(vat_amounts, Decimal(0))
        if abs(total - invoice.tax_total) > _TOLERANCE:
            violations.append(
                f"BR-CO-14: Summe der Steuerbeträge BT-117 {format_money(total, invoice.currency)} ≠ "
                f"Umsatzsteuer gesamt BT-110 {format_money(invoice.tax_total, invoice.currency)}."
            )
    if invoice.net_total is not None and invoice.grand_total is not None:
        expected = invoice.net_total + (invoice.tax_total or 0)
        if abs(expected - invoice.grand_total) > _TOLERANCE:
            violations.append(
                f"BR-CO-15: Gesamtbetrag BT-112 {format_money(invoice.grand_total, invoice.currency)} ≠ "
                f"BT-109 + BT-110 = {format_money(expected, invoice.currency)}."
            )
    if invoice.profile_key == "xrechnung" and not invoice.buyer_reference:
        violations.append("BR-DE-15: Käuferreferenz (BT-10) fehlt – in der XRechnung Pflicht.")
    if invoice.profile_key == "xrechnung" and invoice.seller_contact is False:
        violations.append("BR-DE-2: Kontaktangaben des Verkäufers (BG-6) fehlen – in der XRechnung Pflicht.")
    return violations


# ---------------------------------------------------------------------------
# Leistungszeitpunkt (§ 14 Abs. 4 Satz 1 Nr. 6 UStG) aus BT-72, BG-14 oder BG-26
# ---------------------------------------------------------------------------


def service_time(invoice: EInvoiceData) -> tuple[date | None, date | None, str | None, int]:
    """Liefert (Beginn, Ende, Quelle, Positionen ohne Zeitraum) des Leistungszeitraums.

    Reihenfolge wie in der KoSIT-Regel BR-DE-TMP-32: Rechnungszeitraum BG-14 auf
    Belegebene, sonst die Positionszeiträume BG-26 (frühester Beginn bis spätestes
    Ende).  Das Lieferdatum BT-72 liest der Aufrufer getrennt.
    """
    if invoice.period_start or invoice.period_end:
        return invoice.period_start, invoice.period_end, "BG-14", 0
    with_period = [line for line in invoice.lines if line.period_start or line.period_end]
    if not with_period:
        return None, None, None, len(invoice.lines)
    starts = [line.period_start for line in with_period if line.period_start]
    ends = [line.period_end for line in with_period if line.period_end]
    return (
        min(starts) if starts else None,
        max(ends) if ends else None,
        "BG-26",
        len(invoice.lines) - len(with_period),
    )


# ---------------------------------------------------------------------------
# XRechnung-Versionen (Quelle: KoSIT, xeinkauf.de/xrechnung/versionen-und-bundles,
# abgerufen am 18.11.2026).  Die Spezifikationskennung BT-24 nennt nur
# Haupt- und Nebenversion; maßgeblich ist das Ende der letzten Fassung.
# ---------------------------------------------------------------------------

XRECHNUNG_CURRENT = ("3.0", "01.02.2024")
XRECHNUNG_EXPIRED: dict[str, str] = {
    "1.0": "30.11.2017",
    "1.1": "30.06.2019",
    "1.2": "31.12.2020",
    "2.0": "31.01.2022",
    "2.1": "31.07.2022",
    "2.2": "31.07.2023",
    "2.3": "31.01.2024",
}


def xrechnung_version_notice(invoice: EInvoiceData) -> str | None:
    """Hinweis bei einer XRechnung-Version, die nicht mehr in Kraft ist."""
    if invoice.profile_key != "xrechnung":
        return None
    match = re.search(r"xrechnung_(\d+)\.(\d+)", (invoice.specification_id or "").casefold())
    if not match:
        return None
    version = f"{match.group(1)}.{match.group(2)}"
    until = XRECHNUNG_EXPIRED.get(version)
    if until is None:
        return None
    current, since = XRECHNUNG_CURRENT
    return (
        f"XRechnung {version} galt laut KoSIT nur bis {until}; in Kraft ist XRechnung {current} (seit {since}). "
        "Eingangsplattformen prüfen gegen die aktuelle Version und weisen ältere Datensätze in der Regel zurück."
    )


#: Version des Parsers und des XML-↔-PDF-Abgleichs.  Erhöhen, sobald sich die
#: Auswertung eines unveränderten Datensatzes ändert; die Neuprüfung liest das
#: Original dann ohnehin neu ein, das Protokoll vermerkt die Version.
PARSER_VERSION = "2026.4"


def parse_einvoice_xml(
    data: bytes, *, source: str = "standalone", attachment_name: str | None = None
) -> EInvoiceData:
    """Liest einen EN-16931-Datensatz (CII oder UBL).

    Raises:
        EInvoiceError: kein wohlgeformtes XML oder keine Rechnung.
        UnsupportedEInvoiceError: ZUGFeRD 1.0 oder unbekannte Wurzel.
    """
    root = _parse_root(data)
    namespace, local = _local(root.tag)
    if namespace == NS_CII["rsm"] and local == "CrossIndustryInvoice":
        fields = _parse_cii(root)
    elif namespace == NS_UBL["inv"] and local == "Invoice":
        fields = _parse_ubl(root, credit_note=False)
    elif namespace == NS_UBL["cn"] and local == "CreditNote":
        fields = _parse_ubl(root, credit_note=True)
    elif namespace == _ZUGFERD1_NS or local == "CrossIndustryDocument":
        raise UnsupportedEInvoiceError(
            "ZUGFeRD 1.0 erkannt. Das Format entspricht nicht der EN 16931; als E-Rechnung gilt ZUGFeRD "
            "erst ab Version 2.0.1 (BMF-Schreiben vom 15.10.2024)."
        )
    else:
        raise UnsupportedEInvoiceError(
            f"Keine EN-16931-Rechnung: Wurzelelement „{local}“ (erwartet CrossIndustryInvoice, "
            "UBL Invoice oder CreditNote)."
        )

    profile_key, profile = detect_profile(fields["specification_id"])
    invoice = EInvoiceData(
        source=source,  # type: ignore[arg-type]
        attachment_name=attachment_name,
        profile=profile,
        profile_key=profile_key,
        is_einvoice=profile_key not in NON_EINVOICE_PROFILES and profile_key != "unknown",
        xml_sha256=hashlib.sha256(data).hexdigest(),
        xml_size=len(data),
        parser_version=PARSER_VERSION,
        **fields,
    )
    if not (invoice.invoice_number or invoice.grand_total is not None or invoice.seller.name):
        raise EInvoiceError("Das XML enthält weder Rechnungsnummer noch Beträge oder Verkäufer.")

    invoice.rule_violations = _business_rules(invoice)
    if invoice.buyer_reference:
        invoice.leitweg = validate_leitweg_id(invoice.buyer_reference)
    elif invoice.buyer.electronic_address_scheme == LEITWEG_SCHEME and invoice.buyer.electronic_address:
        invoice.leitweg = validate_leitweg_id(invoice.buyer.electronic_address)
    reason = detect_public_buyer(invoice.buyer.name, invoice)
    invoice.public_buyer = reason is not None
    invoice.public_buyer_reason = reason
    return invoice


def looks_like_xml(data: bytes) -> bool:
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<")


# ---------------------------------------------------------------------------
# Abgleich XML <-> visueller PDF-Teil (XML-Primat, BMF 15.10.2024 Rz. 36)
# ---------------------------------------------------------------------------

_AMOUNT_TOKEN = re.compile(
    r"(?<!\w)-?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+,\d{2}|\d+\.\d{2})"
)
_IBAN_TOKEN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_VAT_TOKEN = re.compile(r"\b(?:DE ?\d{9}|ATU ?\d{8}|[A-Z]{2}\d{8,12})\b")
_PERCENT_TOKEN = re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s?%")


def _token_amount(token: str) -> Decimal | None:
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".") if token.rfind(",") > token.rfind(".") else token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _mask(value: str) -> str:
    compact = value.replace(" ", "")
    return f"{compact[:4]}…{compact[-4:]}" if len(compact) > 10 else compact


def compare_with_visual(invoice: EInvoiceData, text: str) -> list[VisualCheck]:
    """Findet die zentralen XML-Werte im Text des PDF-Bildteils wieder.

    ``mismatch``: Der Bildteil zeigt an der beschrifteten Stelle einen anderen
    Wert (z. B. „Gesamtbetrag 1.190,00“ gegenüber 1.290,00 im XML).
    ``not_found``: Der Wert kommt im Bildteil nicht vor.
    """
    # später Import: scoring importiert keine Extraktoren
    from app.scoring import _DATE_TOKEN, analyze_text, labeled_amounts

    facts = analyze_text(text)
    undated = _DATE_TOKEN.sub(" ", text)
    amounts = {value for value in (_token_amount(t) for t in _AMOUNT_TOKEN.findall(undated)) if value is not None}
    compact = re.sub(r"\s+", "", text)
    currency = invoice.currency
    checks: list[VisualCheck] = []

    if invoice.invoice_number:
        found = re.sub(r"\s+", "", invoice.invoice_number) in compact
        checks.append(VisualCheck(bt="BT-1", label="Rechnungsnummer", xml_value=invoice.invoice_number,
                                  status="match" if found else "not_found"))
    if invoice.issue_date:
        variants = {invoice.issue_date.strftime("%d.%m.%Y"), invoice.issue_date.isoformat()}
        found = any(variant in text for variant in variants)
        checks.append(VisualCheck(bt="BT-2", label="Rechnungsdatum", xml_value=_format_date(invoice.issue_date),
                                  status="match" if found else "not_found"))
    if invoice.seller.vat_id:
        wanted = invoice.seller.vat_id.replace(" ", "")
        candidates = {token.replace(" ", "") for token in _VAT_TOKEN.findall(text)}
        if wanted in candidates:
            status, visual = "match", None
        elif any(c[:2] == wanted[:2] for c in candidates):
            status, visual = "mismatch", next(c for c in candidates if c[:2] == wanted[:2])
        else:
            status, visual = "not_found", None
        checks.append(VisualCheck(bt="BT-31", label="USt-IdNr. des Verkäufers", xml_value=wanted,
                                  status=status, visual_value=visual))  # type: ignore[arg-type]
    if invoice.iban:
        wanted = invoice.iban.replace(" ", "")
        candidates = {token.replace(" ", "") for token in _IBAN_TOKEN.findall(text)}
        if wanted in candidates:
            status, visual = "match", None
        elif candidates:
            status, visual = "mismatch", _mask(sorted(candidates)[0])
        else:
            status, visual = "not_found", None
        checks.append(VisualCheck(bt="BT-84", label="IBAN", xml_value=_mask(wanted),
                                  status=status, visual_value=visual))  # type: ignore[arg-type]

    # Beträge nur hinter Summen-Bezeichnern; eine Abweichung mit Punktabzug nur,
    # wenn eine eindeutige Summe (Rang 1) einen anderen Wert zeigt und der
    # XML-Wert im Bildteil nirgends vorkommt.  Im Zweifel „nicht wiedergefunden“.
    labeled = labeled_amounts(text)
    vat_amounts = [entry.tax_amount for entry in invoice.vat_breakdown if entry.tax_amount is not None]
    for bt, label, xml_amount, key in (
        ("BT-109", "Summe netto", invoice.net_total, "net"),
        ("BT-110", "Umsatzsteuer gesamt", invoice.tax_total, "tax"),
        ("BT-112", "Rechnungsgesamtbetrag", invoice.grand_total, "gross"),
    ):
        if xml_amount is None:
            continue
        candidates = labeled[key]
        strong = [value for rank, value in candidates if rank == 1]
        if key == "tax" and not strong and len(vat_amounts) <= 1:
            # Ein Steuersatz: die Steuerzeile („zzgl. 19 % USt: …“) ist die Gesamtsteuer.
            strong = [value for _, value in candidates]
        shown = any(abs(value - xml_amount) <= _TOLERANCE for value in amounts)
        visual = None
        if any(abs(value - xml_amount) <= _TOLERANCE for _, value in candidates):
            status = "match"
        elif key == "tax" and len(vat_amounts) > 1 and all(value in amounts for value in vat_amounts):
            status = "match"  # Steuer je Satz ausgewiesen, ohne eigene Gesamtsumme
        elif strong and not shown:
            status, visual = "mismatch", format_money(strong[0], currency)
        elif shown and not strong:
            status = "match"
        else:
            status = "not_found"
        checks.append(VisualCheck(bt=bt, label=label, xml_value=format_money(xml_amount, currency),
                                  status=status, visual_value=visual))  # type: ignore[arg-type]

    rates = sorted({entry.rate.normalize() for entry in invoice.vat_breakdown if entry.rate}, reverse=True)
    if rates:
        shown = {value.normalize() for value in (_token_amount(t) for t in _PERCENT_TOKEN.findall(text)) if value is not None}
        xml_value = ", ".join(_format_rate(rate) for rate in rates)
        if all(rate in shown for rate in rates):
            status, visual = "match", None
        elif facts.tax_rate is not None and facts.tax_rate.normalize() not in rates:
            status, visual = "mismatch", _format_rate(facts.tax_rate)
        else:
            status, visual = "not_found", None
        checks.append(VisualCheck(bt="BT-119", label="Steuersatz", xml_value=xml_value,
                                  status=status, visual_value=visual))  # type: ignore[arg-type]
    return checks


# ---------------------------------------------------------------------------
# Lesefassung und Übernahme in die Extraktion
# ---------------------------------------------------------------------------


def _party_lines(title: str, bt: str, party: EInvoiceParty) -> list[str]:
    lines = [f"{title} ({bt}): {party.name or '–'}"]
    if party.address:
        lines.append(f"Anschrift: {party.address}")
    if party.vat_id:
        lines.append(f"USt-IdNr.: {party.vat_id}")
    if party.tax_number:
        lines.append(f"Steuernummer: {party.tax_number}")
    if party.electronic_address:
        scheme = f" (Schema {party.electronic_address_scheme})" if party.electronic_address_scheme else ""
        lines.append(f"Elektronische Adresse: {party.electronic_address}{scheme}")
    return lines


def render_reading_text(invoice: EInvoiceData) -> str:
    """Menschenlesbare Fassung des XML-Datensatzes (Textansicht, PII-Scan, Copilot)."""
    currency = invoice.currency
    kind = (
        "GUTSCHRIFT"
        if invoice.type_code == "389"
        else "RECHNUNGSKORREKTUR (GUTSCHRIFT)"
        if invoice.type_code in _CREDIT_NOTE_CODES
        else "RECHNUNG"
    )
    lines = [
        f"E-{kind} · {invoice.profile} · Syntax {invoice.syntax} – Lesefassung des XML-Datensatzes",
        f"Rechnungsnummer (BT-1): {invoice.invoice_number or '–'}",
        f"Rechnungsdatum (BT-2): {_format_date(invoice.issue_date)}",
        f"Rechnungsart (BT-3): {invoice.type_code or '–'}",
    ]
    if invoice.buyer_reference:
        lines.append(f"Käuferreferenz / Leitweg-ID (BT-10): {invoice.buyer_reference}")
    if invoice.order_reference:
        lines.append(f"Bestellnummer (BT-13): {invoice.order_reference}")
    lines.append("")
    lines += _party_lines("Verkäufer", "BT-27", invoice.seller)
    lines.append("")
    lines += _party_lines("Käufer", "BT-44", invoice.buyer)
    lines.append("")
    if invoice.delivery_date:
        lines.append(f"Leistungsdatum (BT-72): {_format_date(invoice.delivery_date)}")
    if invoice.period_start or invoice.period_end:
        lines.append(
            f"Leistungszeitraum (BT-73/74): {_format_date(invoice.period_start)} – {_format_date(invoice.period_end)}"
        )
    if invoice.lines:
        lines.append("Positionen:")
        for line in invoice.lines:
            quantity = f"{line.quantity.normalize():f}".replace(".", ",") if line.quantity is not None else "–"
            period = (
                f" (Zeitraum {_format_date(line.period_start)} – {_format_date(line.period_end)}, BG-26)"
                if line.period_start or line.period_end
                else ""
            )
            lines.append(
                f"Pos. {line.line_id or '–'}: {quantity} {line.unit or ''} {line.name or '–'} – "
                f"{format_money(line.net_amount, currency)}{period}".replace("  ", " ")
            )
    lines.append("")
    lines.append(f"Summe netto (BT-109): {format_money(invoice.net_total, currency)}")
    for entry in invoice.vat_breakdown:
        reason = f" – {entry.exemption_reason}" if entry.exemption_reason else ""
        lines.append(
            f"USt {_format_rate(entry.rate)} auf {format_money(entry.taxable_amount, currency)} "
            f"(Kategorie {entry.category or '–'}): {format_money(entry.tax_amount, currency)}{reason}"
        )
    lines.append(f"Gesamtbetrag (BT-112): {format_money(invoice.grand_total, currency)}")
    if invoice.due_payable is not None:
        lines.append(f"Zahlbetrag (BT-115): {format_money(invoice.due_payable, currency)}")
    if invoice.iban:
        lines.append(f"IBAN (BT-84): {invoice.iban}")
    if invoice.due_date:
        lines.append(f"Fälligkeit (BT-9): {_format_date(invoice.due_date)}")
    if invoice.payment_terms:
        lines.append(f"Zahlungsbedingungen (BT-20): {invoice.payment_terms}")
    return "\n".join(lines)


def to_extraction(invoice: EInvoiceData) -> ExtractionResult:
    """Übernimmt den XML-Datensatz deterministisch in das Extraktionsmodell."""
    rates = {entry.rate for entry in invoice.vat_breakdown if entry.rate is not None}
    period = None
    start, end, _source, _open = service_time(invoice)
    if start or end:
        period = f"{_format_date(start)} - {_format_date(end)}"
    items = "; ".join(
        f"{line.quantity.normalize():f} {line.unit or ''} {line.name}".replace("  ", " ")
        if line.quantity is not None
        else (line.name or "")
        for line in invoice.lines
        if line.name
    )
    exemption = next((entry.exemption_reason for entry in invoice.vat_breakdown if entry.exemption_reason), None)
    kind = (
        "Gutschrift (§ 14 Abs. 2 S. 2 UStG)"
        if invoice.type_code == "389"
        else "Rechnungskorrektur (Gutschrift)"
        if invoice.type_code in _CREDIT_NOTE_CODES
        else "E-Rechnung"
    )
    summary = (
        f"{kind} ({invoice.profile}, {invoice.syntax}) der {invoice.seller.name or 'unbekannten Verkäuferin'} "
        f"an {invoice.buyer.name or 'unbekannten Käufer'} über {format_money(invoice.grand_total, invoice.currency)}. "
        "Die Daten stammen deterministisch aus dem XML-Datensatz."
    )
    return ExtractionResult.model_validate(
        {
            "doc_type": DocType.INVOICE.value,
            "sender": invoice.seller.name,
            "recipient": invoice.buyer.name,
            "document_number": invoice.invoice_number,
            "document_date": invoice.issue_date,
            "due_date": invoice.due_date,
            "total_amount": invoice.grand_total,
            "currency": invoice.currency,
            "iban": invoice.iban,
            "summary": summary,
            "sender_address": invoice.seller.address,
            "recipient_address": invoice.buyer.address,
            "sender_tax_number": invoice.seller.tax_number,
            "sender_vat_id": invoice.seller.vat_id,
            "service_date": invoice.delivery_date,
            "service_period": period,
            "items_description": items[:600] or None,
            "net_amount": invoice.net_total,
            "tax_rate": next(iter(rates)) if len(rates) == 1 else None,
            "tax_amount": invoice.tax_total,
            "tax_exemption_note": exemption,
            "issues": list(invoice.rule_violations),
        }
    )
