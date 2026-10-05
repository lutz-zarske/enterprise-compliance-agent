"""Testdaten fuer E-Rechnungen: UBL-XRechnung und Varianten der hybriden Musterrechnung."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from app.demo import HYBRID_INVOICE

XRECHNUNG_30 = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"


def hybrid_spec(**changes: Any) -> dict[str, Any]:
    """Tiefe Kopie der Musterrechnung mit gezielten Aenderungen."""
    spec = copy.deepcopy(HYBRID_INVOICE)
    for key, value in changes.items():
        if key in {"seller", "buyer"}:
            spec[key].update(value)
        else:
            spec[key] = value
    return spec


def b2b_spec(**changes: Any) -> dict[str, Any]:
    """Musterrechnung an ein Unternehmen (keine Behoerde, keine Leitweg-ID)."""
    return hybrid_spec(
        buyer={"name": "Brandt Maschinenbau AG", "street": "Industrieweg 7", "postcode": "70565",
               "city": "Stuttgart", "leitweg": None},
        buyer_reference=None,
        **changes,
    )


def build_ubl_invoice(
    *,
    customization: str = XRECHNUNG_30,
    buyer_reference: str | None = "04011000-1234512345-06",
    buyer_name: str = "Landratsamt Musterkreis",
    lines: tuple[tuple[str, str, str, Decimal, Decimal], ...] = (
        ("1", "Wartung Fachanwendung", "C62", Decimal("1"), Decimal("1000.00")),
        ("2", "Fachbuch Verwaltungsrecht", "C62", Decimal("2"), Decimal("100.00")),
    ),
    tax_overrides: dict[str, Decimal] | None = None,
) -> bytes:
    """XRechnung 3.0 in UBL-Syntax mit Mischsteuersatz (19 % und 7 %)."""
    rates = {"Wartung Fachanwendung": Decimal("19"), "Fachbuch Verwaltungsrecht": Decimal("7")}
    groups: dict[Decimal, Decimal] = {}
    for _, name, _, _, amount in lines:
        groups[rates.get(name, Decimal("19"))] = groups.get(rates.get(name, Decimal("19")), Decimal(0)) + amount
    subtotals = {rate: (base * rate / 100).quantize(Decimal("0.01")) for rate, base in groups.items()}
    net = sum(groups.values(), Decimal(0))
    tax = sum(subtotals.values(), Decimal(0))
    totals = {"net": net, "tax": tax, "grand": net + tax, **(tax_overrides or {})}
    reference = f"<cbc:BuyerReference>{buyer_reference}</cbc:BuyerReference>" if buyer_reference else ""
    sub_xml = "".join(
        f"""<cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">{groups[rate]:.2f}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="EUR">{subtotals[rate]:.2f}</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{rate}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>"""
        for rate in sorted(groups, reverse=True)
    )
    line_xml = "".join(
        f"""<cac:InvoiceLine><cbc:ID>{line_id}</cbc:ID><cbc:InvoicedQuantity unitCode="{unit}">{quantity}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{amount:.2f}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>{name}</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{rates.get(name, Decimal("19"))}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{amount / quantity:.2f}</cbc:PriceAmount></cac:Price></cac:InvoiceLine>"""
        for line_id, name, unit, quantity, amount in lines
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>{customization}</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>XR-2026-077</cbc:ID>
  <cbc:IssueDate>2026-09-30</cbc:IssueDate>
  <cbc:DueDate>2026-10-30</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  {reference}
  <cac:InvoicePeriod><cbc:StartDate>2026-09-01</cbc:StartDate><cbc:EndDate>2026-09-30</cbc:EndDate></cac:InvoicePeriod>
  <cac:AccountingSupplierParty><cac:Party>
    <cbc:EndpointID schemeID="EM">rechnung@softwarehaus.example</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Hauptstraße 5</cbc:StreetName><cbc:CityName>Kassel</cbc:CityName><cbc:PostalZone>34117</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>DE298765432</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Softwarehaus Nordhessen GmbH</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cbc:EndpointID schemeID="0204">{buyer_reference or "keine"}</cbc:EndpointID>
    <cac:PostalAddress><cbc:StreetName>Kreishausplatz 1</cbc:StreetName><cbc:CityName>Musterkreis</cbc:CityName><cbc:PostalZone>34999</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
    <cac:PartyLegalEntity><cbc:RegistrationName>{buyer_name}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode><cac:PayeeFinancialAccount><cbc:ID>DE89370400440532013000</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>
  <cac:PaymentTerms><cbc:Note>Zahlbar innerhalb von 30 Tagen.</cbc:Note></cac:PaymentTerms>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{totals["tax"]:.2f}</cbc:TaxAmount>
    {sub_xml}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{net:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{totals["net"]:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{totals["grand"]:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">{totals["grand"]:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {line_xml}
</ubl:Invoice>
"""
    return xml.encode("utf-8")


ZUGFERD_1_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryDocument xmlns:rsm="urn:ferd:CrossIndustryDocument:invoice:1p0">
  <rsm:HeaderExchangedDocument/>
</rsm:CrossIndustryDocument>"""

XXE_XML = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">&xxe;</rsm:CrossIndustryInvoice>"""

BILLION_LAUGHS_XML = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&lol2;</ubl:Invoice>"""
