"""Prüfmatrix typischer deutscher Rechnungen (Erwartungen: docs/PRUEFMATRIX.md).

Jeder PDF-Fall läuft als Text-PDF mit fest vorgegebener KI-Antwort – einmal mit
gefüllten Beträgen und einmal mit leeren Beträgen (wie im Cloud-Betrieb, wenn
das Privacy Gateway Beträge durch Platzhalter ersetzt und das Modell ``null``
liefert).  Einzelne Fälle haben zusätzlich eine typische Fehlextraktion
(nur die erste USt-Zeile, Restforderung statt Gesamtbetrag).  Die E-Rechnungs-
Fälle laufen als UBL-Datensatz (EN 16931) über den deterministischen XML-Pfad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeOllama, build_pdf

NEUTRAL_AUDIT: dict[str, Any] = {
    "ai_act": {
        "describes_ai_system": False,
        "overall_risk_level": "not_applicable",
        "systems": [],
        "reasoning": "Rechnung ohne KI-Bezug.",
        "obligations": [],
    },
    "gdpr": {
        "contains_personal_data": False,
        "findings": [],
        "risk_level": "none",
        "reasoning": "Nur Unternehmensdaten.",
        "recommendations": [],
    },
}

SELLER = "Muster Handel GmbH"
SELLER_ADDRESS = "Musterweg 1, 12345 Musterstadt"
BUYER = "Beispiel AG"
BUYER_ADDRESS = "Hauptstraße 2, 54321 Beispielstadt"
RELEASED = "Zur Auszahlung freigegeben"
BLOCKED = "Freigabe gesperrt — Nachforderung nötig"


def _head(number: str, *, service: str = "Leistungsdatum: 09.11.2026") -> list[str]:
    return [
        f"{SELLER}, {SELLER_ADDRESS}",
        "USt-IdNr.: DE123456789",
        f"An: {BUYER}, {BUYER_ADDRESS}",
        f"Rechnung Nr. {number} vom 10.11.2026",
        service,
    ]


@dataclass(frozen=True)
class Case:
    key: str
    lines: list[str]
    amounts: dict[str, Any]
    score: int
    recommendation: str
    checks: dict[str, str] = field(default_factory=dict)
    absent: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)
    small: bool = False
    #: Zusätzliche Fehlextraktionen: Name -> abweichende Beträge der KI-Antwort.
    misreads: dict[str, dict[str, Any]] = field(default_factory=dict)


def _amounts(net: str | None, tax: str | None, total: str | None, rate: Any = None) -> dict[str, Any]:
    return {"net_amount": net, "tax_amount": tax, "total_amount": total, "tax_rate": rate}


CASES: list[Case] = [
    Case(
        "hotel_7_19",
        [
            *_head("H-2026-118", service="Aufenthalt: 06.11.2026 - 09.11.2026"),
            "Übernachtung 3 Nächte à 90,00 EUR (7 %) 270,00 EUR",
            "Frühstück 3 x 15,00 EUR (19 %) 45,00 EUR",
            "Summe netto: 315,00 EUR",
            "zzgl. 7 % USt auf 270,00 EUR: 18,90 EUR",
            "zzgl. 19 % USt auf 45,00 EUR: 8,55 EUR",
            "Gesamtbetrag: 342,45 EUR",
        ],
        _amounts("315.00", "27.45", "342.45"),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass", "vat_rate": "pass"},
        extra={"service_date": None, "service_period": "06.11.2026 - 09.11.2026"},
        misreads={"nur_erste_ust_zeile": _amounts("315.00", "18.90", "342.45", 7)},
    ),
    Case(
        "bewirtung_7_19",
        [
            *_head("B-2026-55"),
            "Speisen (7 %) 240,00 EUR",
            "Getränke (19 %) 95,00 EUR",
            "Summe netto: 335,00 EUR",
            "zzgl. 7 % USt auf 240,00 EUR: 16,80 EUR",
            "zzgl. 19 % USt auf 95,00 EUR: 18,05 EUR",
            "Gesamtbetrag: 369,85 EUR",
        ],
        _amounts("335.00", "34.85", "369.85"),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"},
        misreads={"nur_erste_ust_zeile": _amounts("335.00", "16.80", "369.85", 7)},
    ),
    Case(
        "mischsatz_mit_porto",
        [
            *_head("M-2026-7"),
            "Pos. 1 Fachbuch (7 %) 80,00 EUR",
            "Pos. 2 Schreibtischlampe (19 %) 50,00 EUR",
            "Pos. 3 Porto (steuerfrei) 6,90 EUR",
            "Summe netto: 136,90 EUR",
            "zzgl. 7 % USt auf 80,00 EUR: 5,60 EUR",
            "zzgl. 19 % USt auf 50,00 EUR: 9,50 EUR",
            "Gesamtbetrag: 152,00 EUR",
        ],
        _amounts("136.90", "15.10", "152.00"),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"}, absent=("ustg_14c_conflict",), small=True,
        misreads={"nur_erste_ust_zeile": _amounts("136.90", "5.60", "152.00", 7)},
    ),
    Case(
        "kleinbetrag_33_ustdv",
        [
            f"Schreibwaren Müller, {SELLER_ADDRESS}",
            "Quittung vom 10.11.2026",
            "2 Ordner, 1 Locher",
            "Gesamtbetrag inkl. 19 % USt: 23,80 EUR",
            "darin enthalten 19 % USt: 3,80 EUR",
        ],
        _amounts(None, "3.80", "23.80", 19),
        100, RELEASED, small=True,
        extra={
            "sender": "Schreibwaren Müller", "recipient": None, "recipient_address": None, "document_number": None,
            "service_date": None, "sender_vat_id": None, "items_description": "2 Ordner, 1 Locher",
        },
    ),
    Case(
        "kleinunternehmer_19_ustg",
        [
            f"Grafikdesign Lehmann, {SELLER_ADDRESS}",
            "Steuernummer: 21/815/08150",
            f"An: {BUYER}, {BUYER_ADDRESS}",
            "Rechnung Nr. 2026-14 vom 10.11.2026",
            "Leistungsdatum: 09.11.2026",
            "Pos. 1 Logo-Entwurf 600,00 EUR",
            "Gesamtbetrag: 600,00 EUR",
            "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
        ],
        _amounts("600.00", None, "600.00"),
        100, RELEASED, {"sum_check": "pass"}, absent=("ustg_14c_conflict",),
        extra={
            "sender": "Grafikdesign Lehmann", "sender_vat_id": None, "sender_tax_number": "21/815/08150",
            "tax_exemption_note": "Kleinunternehmer gemäß § 19 UStG",
        },
    ),
    Case(
        "reverse_charge_13b_korrekt",
        [
            *_head("RC-2026-3"),
            "USt-IdNr. des Leistungsempfängers: DE987654321",
            "Pos. 1 Trockenbauarbeiten 4.000,00 EUR",
            "Summe netto: 4.000,00 EUR",
            "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)",
            "Gesamtbetrag: 4.000,00 EUR",
        ],
        _amounts("4000.00", "0", "4000.00", 0),
        100, RELEASED, {"sum_check": "pass"}, absent=("ustg_14c_conflict",),
        extra={"tax_exemption_note": "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)"},
    ),
    Case(
        "ig_lieferung_korrekt",
        [
            *_head("EU-2026-21")[:2],
            "An: Alpen Technik GmbH, Industriestraße 5, 4020 Linz, Österreich, UID: ATU12345678",
            "Rechnung Nr. EU-2026-21 vom 10.11.2026",
            "Lieferdatum: 09.11.2026",
            "Pos. 1 Fräsmaschine FM-200 12.500,00 EUR",
            "Summe netto: 12.500,00 EUR",
            "Steuerfreie innergemeinschaftliche Lieferung nach § 4 Nr. 1b i. V. m. § 6a UStG",
            "Gesamtbetrag: 12.500,00 EUR",
        ],
        _amounts("12500.00", "0", "12500.00", 0),
        100, RELEASED, {"sum_check": "pass"}, absent=("ustg_14c_conflict",),
        extra={
            "recipient": "Alpen Technik GmbH", "recipient_address": "Industriestraße 5, 4020 Linz, Österreich",
            "tax_exemption_note": "Steuerfreie innergemeinschaftliche Lieferung (§ 4 Nr. 1b UStG)",
        },
    ),
    Case(
        "skonto_hinweis",
        [
            *_head("S-2026-40"),
            "Pos. 1 Wartungsvertrag November 2.000,00 EUR",
            "Summe netto: 2.000,00 EUR",
            "zzgl. 19 % USt: 380,00 EUR",
            "Gesamtbetrag: 2.380,00 EUR",
            "Zahlbar innerhalb von 30 Tagen netto; bei Zahlung bis 20.11.2026 2 % Skonto (47,60 EUR).",
        ],
        _amounts("2000.00", "380.00", "2380.00", 19),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"},
    ),
    Case(
        "rechnungskorrektur_negativ",
        [
            *_head("RK-2026-5"),
            "Rechnungskorrektur zu Rechnung Nr. 2026-100 vom 01.10.2026",
            "Pos. 1 Gutschrift für Rücksendung -100,00 EUR",
            "Summe netto: -100,00 EUR",
            "zzgl. 19 % USt: -19,00 EUR",
            "Gesamtbetrag: -119,00 EUR",
        ],
        _amounts("-100.00", "-19.00", "-119.00", 19),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"},
    ),
    Case(
        "abschlagsrechnung",
        [
            *_head("A-2026-1", service="Leistungszeitraum: Oktober 2026 (Baufortschritt 50 %)"),
            "Abschlagsrechnung Nr. 1 zum Auftrag A-77",
            "Pos. 1 Abschlag 50 % der Auftragssumme 5.000,00 EUR",
            "Summe netto: 5.000,00 EUR",
            "zzgl. 19 % USt: 950,00 EUR",
            "Gesamtbetrag: 5.950,00 EUR",
        ],
        _amounts("5000.00", "950.00", "5950.00", 19),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"},
        extra={"service_date": None, "service_period": "Oktober 2026"},
    ),
    Case(
        "schlussrechnung",
        [
            *_head("A-2026-2"),
            "Schlussrechnung zum Auftrag A-77",
            "Pos. 1 Gesamtleistung laut Auftrag 10.000,00 EUR",
            "Summe netto: 10.000,00 EUR",
            "zzgl. 19 % USt: 1.900,00 EUR",
            "Gesamtbetrag: 11.900,00 EUR",
            "abzüglich Abschlagsrechnung Nr. 1 vom 10.10.2026: netto 5.000,00 EUR, USt 950,00 EUR, brutto 5.950,00 EUR",
            "Restforderung (zu zahlen): 5.950,00 EUR",
        ],
        _amounts("10000.00", "1900.00", "11900.00", 19),
        100, RELEASED, {"sum_check": "pass", "tax_calc": "pass"},
        misreads={"restforderung_als_brutto": _amounts("10000.00", "1900.00", "5950.00", 19)},
    ),
    Case(
        "echter_summenfehler",
        [
            *_head("F-2026-1"),
            "Pos. 1 Beratung 10 Stunden 1.000,00 EUR",
            "Summe netto: 1.000,00 EUR",
            "zzgl. 19 % USt: 190,00 EUR",
            "Gesamtbetrag: 1.290,00 EUR",
        ],
        _amounts("1000.00", "190.00", "1290.00", 19),
        85, BLOCKED, {"sum_check": "fail", "tax_calc": "pass"},
    ),
    Case(
        "echter_steuerfehler",
        [
            *_head("F-2026-2"),
            "Pos. 1 Beratung 10 Stunden 1.000,00 EUR",
            "Summe netto: 1.000,00 EUR",
            "zzgl. 19 % USt: 180,00 EUR",
            "Gesamtbetrag: 1.180,00 EUR",
        ],
        _amounts("1000.00", "180.00", "1180.00", 19),
        90, BLOCKED, {"sum_check": "pass", "tax_calc": "fail"},
    ),
]


def _llm_answer(case: Case, amounts: dict[str, Any]) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "doc_type": "Rechnung",
        "sender": SELLER,
        "recipient": BUYER,
        "sender_address": SELLER_ADDRESS,
        "recipient_address": BUYER_ADDRESS,
        "document_number": case.key.upper(),
        "document_date": "2026-11-10",
        "service_date": "2026-11-09",
        "sender_vat_id": "DE123456789",
        "items_description": "Lieferungen und Leistungen laut Positionen",
        "currency": "EUR",
        "summary": f"Testbeleg {case.key}.",
        "issues": [],
    }
    answer.update(case.extra)
    answer.update(amounts)
    return answer


def _run(client: TestClient, fake_ollama: FakeOllama, case: Case, amounts: dict[str, Any]) -> tuple[dict, dict]:
    fake_ollama.extraction_response = _llm_answer(case, amounts)
    fake_ollama.compliance_response = NEUTRAL_AUDIT
    pdf = build_pdf([case.lines])
    response = client.post("/documents/upload", files={"file": (f"{case.key}.pdf", pdf, "application/pdf")})
    assert response.status_code == 201, response.text
    body = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()
    return body["scorecard"], body["extraction"]


def _variants() -> list[Any]:
    params = []
    for case in CASES:
        params.append(pytest.param(case, case.amounts, id=f"{case.key}-gefuellt"))
        params.append(pytest.param(case, _amounts(None, None, None), id=f"{case.key}-leer"))
        for name, misread in case.misreads.items():
            params.append(pytest.param(case, misread, id=f"{case.key}-{name}"))
    return params


@pytest.mark.parametrize(("case", "amounts"), _variants())
def test_pruefmatrix_pdf(client: TestClient, fake_ollama: FakeOllama, case: Case, amounts: dict[str, Any]) -> None:
    card, extraction = _run(client, fake_ollama, case, amounts)
    checks = {c["id"]: c for tile in card["tiles"] for c in tile["checks"]}
    failed = {key: (c["status"], c["deduction"], c.get("detail")) for key, c in checks.items() if c["deduction"]}
    assert card["score"] == case.score, failed
    assert card["release_recommendation"] == case.recommendation, failed
    assert card["small_amount_invoice"] is case.small
    for check_id, status in case.checks.items():
        assert checks[check_id]["status"] == status, (check_id, checks[check_id])
    for check_id in case.absent:
        assert check_id not in checks, (check_id, checks.get(check_id))
    # Beträge in den Kerndaten: aus der KI-Antwort oder abgesichert aus dem Belegtext.
    expected_total = Decimal(case.amounts["total_amount"])
    assert Decimal(str(extraction["total_amount"])) == expected_total


def _ubl(
    lines: list[tuple[str, str, str, str]],
    *,
    exemption: str | None = None,
    credit_note: bool = False,
    buyer_vat: str = "DE987654321",
    buyer_country: str = "DE",
) -> bytes:
    """Minimaler UBL-Datensatz (EN 16931): Positionen als (Name, Netto, Kategorie, Satz)."""
    root, type_tag, line_tag, qty_tag = (
        ("CreditNote", "CreditNoteTypeCode", "CreditNoteLine", "CreditedQuantity")
        if credit_note
        else ("Invoice", "InvoiceTypeCode", "InvoiceLine", "InvoicedQuantity")
    )
    groups: dict[tuple[str, str], Decimal] = {}
    for _, net, category, rate in lines:
        groups[(category, rate)] = groups.get((category, rate), Decimal(0)) + Decimal(net)
    taxes = {key: (base * Decimal(key[1]) / 100).quantize(Decimal("0.01")) for key, base in groups.items()}
    net_total = sum(groups.values(), Decimal(0))
    tax_total = sum(taxes.values(), Decimal(0))
    reason = f"<cbc:TaxExemptionReason>{exemption}</cbc:TaxExemptionReason>" if exemption else ""
    subtotals = "".join(
        f'<cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">{base:.2f}</cbc:TaxableAmount>'
        f'<cbc:TaxAmount currencyID="EUR">{taxes[(cat, rate)]:.2f}</cbc:TaxAmount>'
        f"<cac:TaxCategory><cbc:ID>{cat}</cbc:ID><cbc:Percent>{rate}</cbc:Percent>{reason}"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
        for (cat, rate), base in groups.items()
    )
    items = "".join(
        f'<cac:{line_tag}><cbc:ID>{index}</cbc:ID><cbc:{qty_tag} unitCode="C62">1</cbc:{qty_tag}>'
        f'<cbc:LineExtensionAmount currencyID="EUR">{Decimal(net):.2f}</cbc:LineExtensionAmount>'
        f"<cac:Item><cbc:Name>{name}</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>{cat}</cbc:ID>"
        f"<cbc:Percent>{rate}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        f'</cac:ClassifiedTaxCategory></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">{Decimal(net):.2f}'
        f"</cbc:PriceAmount></cac:Price></cac:{line_tag}>"
        for index, (name, net, cat, rate) in enumerate(lines, start=1)
    )
    ns = f"urn:oasis:names:specification:ubl:schema:xsd:{root}-2"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:{root} xmlns:ubl="{ns}" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ID>X-2026-1</cbc:ID>
  <cbc:IssueDate>2026-11-10</cbc:IssueDate>
  <cbc:{type_tag}>{"381" if credit_note else "380"}</cbc:{type_tag}>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:InvoicePeriod><cbc:StartDate>2026-11-01</cbc:StartDate><cbc:EndDate>2026-11-09</cbc:EndDate></cac:InvoicePeriod>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PostalAddress><cbc:StreetName>Musterweg 1</cbc:StreetName><cbc:CityName>Musterstadt</cbc:CityName><cbc:PostalZone>12345</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{SELLER}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PostalAddress><cbc:StreetName>Hauptstraße 2</cbc:StreetName><cbc:CityName>Beispielstadt</cbc:CityName><cbc:PostalZone>54321</cbc:PostalZone><cac:Country><cbc:IdentificationCode>{buyer_country}</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>{buyer_vat}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{BUYER}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{tax_total:.2f}</cbc:TaxAmount>{subtotals}</cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{net_total:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{net_total:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{net_total + tax_total:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{net_total + tax_total:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {items}
</ubl:{root}>
"""
    return xml.encode("utf-8")


XML_CASES = [
    pytest.param(
        _ubl([("Übernachtung", "270.00", "S", "7"), ("Frühstück", "45.00", "S", "19")]), id="xml-hotel_7_19"
    ),
    pytest.param(
        _ubl([("Trockenbauarbeiten", "4000.00", "AE", "0")],
             exemption="Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)"),
        id="xml-reverse_charge_13b",
    ),
    pytest.param(
        _ubl([("Fräsmaschine", "12500.00", "K", "0")], exemption="Innergemeinschaftliche Lieferung",
             buyer_vat="ATU12345678", buyer_country="AT"),
        id="xml-ig_lieferung",
    ),
    pytest.param(
        _ubl([("Logo-Entwurf", "600.00", "E", "0")], exemption="Kleinunternehmer gemäß § 19 UStG"),
        id="xml-kleinunternehmer",
    ),
    pytest.param(_ubl([("Rücksendung", "100.00", "S", "19")], credit_note=True), id="xml-gutschrift_381"),
]


@pytest.mark.parametrize("xml", XML_CASES)
def test_pruefmatrix_e_rechnung(client: TestClient, fake_ollama: FakeOllama, xml: bytes) -> None:
    fake_ollama.offline = True  # deterministischer XML-Pfad ohne Sprachmodell
    response = client.post("/documents/upload", files={"file": ("beleg.xml", xml, "application/xml")})
    assert response.status_code == 201, response.text
    card = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()["scorecard"]
    deducted = {c["id"]: c.get("detail") for t in card["tiles"] for c in t["checks"] if c["deduction"]}
    assert (card["score"], card["release_recommendation"]) == (100, RELEASED), deducted
    assert "ustg_14c_conflict" not in {c["id"] for t in card["tiles"] for c in t["checks"]}
