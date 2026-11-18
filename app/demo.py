"""Referenzdokumente fuer Live-Praesentationen (``POST /api/demo/seed``).

Vier bewusst konstruierte Faelle decken Ampelfarben und E-Rechnung ab:

1. ``Rechnung_Gueltig_14UStG.pdf`` - alle Pflichtangaben, korrekte Mathematik.
   Erwartung: gruen, Score 100 (keine Abzuege nach Regelwerk 2026.2).
2. ``Rechnung_Fehlerhaft_Steuerfalle.pdf`` - keine Steuernummer/USt-IdNr. (-20),
   unzulaessiger Steuersatz 16 % (-10), kein Leistungsdatum (-10), IBAN mit
   falscher Pruefziffer (-15).  Erwartung: rot, Score 45.
3. ``KI_Recruiting_Dienstleistervertrag.pdf`` - KI-gestuetztes Bewerber-
   Screening (Anhang III Nr. 4) ohne Konformitaetsnachweis.  Erwartung: rot,
   Score gedeckelt auf 59.
4. ``Rechnung_ZUGFeRD_Hybrid.pdf`` - hybride E-Rechnung (Profil EN 16931) mit
   eingebettetem ``factur-x.xml`` an eine (fiktive) Kommune mit gueltiger
   Leitweg-ID.  Erwartung: gruen, Score 100 - deterministisch aus dem XML,
   ohne Sprachmodell und ohne Vorberechnung.

Die Erwartungswerte gelten fuer eine vollstaendige Extraktion; da Stufe 3 der
Pipeline ein LLM ist, kann ein schwaecheres Modell einzelne Felder verfehlen.
Die Regex-Gegenprobe in ``app/scoring.py`` faengt die meisten dieser Faelle ab.

Die PDFs entstehen zur Laufzeit ohne Zusatzbibliothek (gleiches Verfahren wie
in ``tests/conftest.py``).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Any
from xml.sax.saxutils import escape



def _escape_pdf_text(value: str) -> bytes:
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("cp1252", errors="replace")


def build_pdf(
    pages: list[list[str]],
    *,
    attachments: list[tuple[str, bytes, str]] | None = None,
    xmp: bytes | None = None,
) -> bytes:
    """Minimales, gueltiges PDF mit echtem Textlayer (Helvetica, WinAnsi).

    ``attachments`` bettet Dateien wie bei ZUGFeRD/Factur-X ein
    (``/EmbeddedFiles`` + ``/AF`` mit ``/AFRelationship``); ``xmp`` setzt den
    Metadatenstrom.  Das Ergebnis ist strukturell eine hybride Rechnung, aber
    kein validiertes PDF/A-3 (Schriften nicht eingebettet, kein OutputIntent).
    """
    page_count = len(pages)
    font_obj = 3 + 2 * page_count
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(page_count))
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

    catalog = "<< /Type /Catalog /Pages 2 0 R"
    next_obj = font_obj + 1
    if attachments:
        names: list[str] = []
        specs: list[str] = []
        for filename, data, relationship in attachments:
            stream_obj, spec_obj = next_obj, next_obj + 1
            next_obj += 2
            subtype = "/Subtype /text#2Fxml " if filename.endswith(".xml") else ""
            objects[stream_obj] = (
                f"<< /Type /EmbeddedFile {subtype}/Length {len(data)} /Params << /Size {len(data)} >> >>\nstream\n"
            ).encode("ascii") + data + b"\nendstream"
            objects[spec_obj] = (
                f"<< /Type /Filespec /F ({filename}) /UF ({filename}) /Desc (E-Rechnung {filename}) "
                f"/AFRelationship /{relationship} /EF << /F {stream_obj} 0 R /UF {stream_obj} 0 R >> >>"
            ).encode("ascii")
            names.append(f"({filename}) {spec_obj} 0 R")
            specs.append(f"{spec_obj} 0 R")
        catalog += f" /Names << /EmbeddedFiles << /Names [{' '.join(names)}] >> >> /AF [{' '.join(specs)}]"
    if xmp:
        objects[next_obj] = (
            f"<< /Type /Metadata /Subtype /XML /Length {len(xmp)} >>\nstream\n".encode("ascii") + xmp + b"\nendstream"
        )
        catalog += f" /Metadata {next_obj} 0 R"
        next_obj += 1
    objects[1] = (catalog + " >>").encode("ascii")

    out = bytearray(b"%PDF-1.7\n" if attachments else b"%PDF-1.4\n")
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
    "Pos. 1   Büromöbel-Set Executive, 3 Stück   4.500,00 EUR",
    "",
    "Nettobetrag: 4.500,00 EUR",
    "MwSt. 16 %: 720,00 EUR",
    "Gesamtbetrag: 5.220,00 EUR",
    "",
    "Bitte sofort überweisen auf: DE12 3456 7890 1234 5678 90",
]

# Fiktiver Vertrag; Kontaktadresse unter der reservierten Domain .example (RFC 2606),
# IBAN ist das Standard-Beispiel der Bundesbank-Dokumentation.
RECRUITING_LINES = [
    "VERTRAG UEBER KI-GESTUETZTES RECRUITING & BEWERBERMANAGEMENT",
    "Zwischen TalentScreen AI GmbH und Enterprise Corp SE.",
    "Das System TalentAI bewertet Bewerber automatisiert gemäß Anhang III Nr. 4 EU AI Act.",
    "Rechnungsbetrag: 45000 EUR fällig zum 31.12.2024.",
    "Bankverbindung: DE89370400440532013000.",
    "Kontakt: datenschutz@talentscreen.example.",
]


# ---------------------------------------------------------------------------
# Hybride E-Rechnung (ZUGFeRD 2.3 / Factur-X, Profil EN 16931)
# ---------------------------------------------------------------------------
#
# Eine Quelle fuer XML und Bildteil: Beide werden aus ``HYBRID_INVOICE``
# erzeugt, damit der Abgleich XML <-> PDF in den Musterdaten deckungsgleich ist.
# Kaeufer ist eine (fiktive) Kommune - so zeigt der Beleg auch die
# B2G-Pruefung mit Leitweg-ID (Pruefziffer nach KoSIT-Spezifikation gueltig).

HYBRID_FILENAME = "Rechnung_ZUGFeRD_Hybrid.pdf"

HYBRID_INVOICE: dict[str, Any] = {
    "specification_id": "urn:cen.eu:en16931:2017",
    "number": "ECS-2026-0412",
    "issue_date": date(2026, 9, 15),
    "delivery_date": date(2026, 8, 31),
    "period": (date(2026, 8, 1), date(2026, 8, 31)),
    "due_date": date(2026, 10, 15),
    "currency": "EUR",
    "buyer_reference": "05999000-VERGABE-24",
    "order_reference": "VG-2026-117",
    "seller": {
        "name": "Elbtal Cloud Solutions GmbH",
        "street": "Königsbrücker Straße 96",
        "postcode": "01099",
        "city": "Dresden",
        "country": "DE",
        "vat_id": "DE312345678",
        "tax_number": "203/118/02417",
        "email": "rechnung@elbtal-cloud.example",
    },
    "buyer": {
        "name": "Stadtverwaltung Musterstadt",
        "street": "Rathausplatz 1",
        "postcode": "59999",
        "city": "Musterstadt",
        "country": "DE",
        "leitweg": "05999000-VERGABE-24",
    },
    "lines": [
        ("1", "Hosting Fachverfahren Bürgerservice (August 2026)", Decimal("1"), "C62", Decimal("3200.00")),
        ("2", "Betriebsunterstützung, Stunden", Decimal("16"), "HUR", Decimal("1600.00")),
    ],
    "rate": Decimal("19"),
    "iban": "DE02120300000000202051",
    "payment_terms": "Zahlbar innerhalb von 30 Tagen ohne Abzug.",
}


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _de_money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cii_date(value: date) -> str:
    return f'<udt:DateTimeString format="102">{value:%Y%m%d}</udt:DateTimeString>'


def build_cii_invoice(spec: dict[str, Any]) -> bytes:
    """CII-Datensatz (ZUGFeRD 2.x / Factur-X) aus einer Rechnungsbeschreibung.

    Reihenfolge der Elemente folgt dem CII-Schema D16B; die Summen werden aus
    den Positionen berechnet, ``spec["override"]`` kann sie fuer Tests gezielt
    verfaelschen.
    """
    e = escape
    line_total = sum((line[4] for line in spec["lines"]), Decimal(0))
    tax = (line_total * spec["rate"] / 100).quantize(Decimal("0.01"))
    totals = {"line": line_total, "net": line_total, "tax": tax, "grand": line_total + tax}
    totals.update(spec.get("override", {}))
    seller, buyer = spec["seller"], spec["buyer"]

    items = "".join(
        f"""
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>{e(line_id)}</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>{e(name)}</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{_money(amount / quantity)}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="{unit}">{quantity}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{spec["rate"]}</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{_money(amount)}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>"""
        for line_id, name, quantity, unit, amount in spec["lines"]
    )
    buyer_reference = (
        f"<ram:BuyerReference>{e(spec['buyer_reference'])}</ram:BuyerReference>" if spec.get("buyer_reference") else ""
    )
    buyer_uri = (
        f'<ram:URIUniversalCommunication><ram:URIID schemeID="0204">{e(buyer["leitweg"])}</ram:URIID></ram:URIUniversalCommunication>'
        if buyer.get("leitweg")
        else ""
    )
    start, end = spec["period"]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{e(spec["specification_id"])}</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{e(spec["number"])}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>{_cii_date(spec["issue_date"])}</ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>{items}
    <ram:ApplicableHeaderTradeAgreement>
      {buyer_reference}
      <ram:SellerTradeParty>
        <ram:Name>{e(seller["name"])}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>{seller["postcode"]}</ram:PostcodeCode><ram:LineOne>{e(seller["street"])}</ram:LineOne><ram:CityName>{e(seller["city"])}</ram:CityName><ram:CountryID>{seller["country"]}</ram:CountryID></ram:PostalTradeAddress>
        <ram:URIUniversalCommunication><ram:URIID schemeID="EM">{e(seller["email"])}</ram:URIID></ram:URIUniversalCommunication>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">{e(seller["tax_number"])}</ram:ID></ram:SpecifiedTaxRegistration>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(seller["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{e(buyer["name"])}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>{buyer["postcode"]}</ram:PostcodeCode><ram:LineOne>{e(buyer["street"])}</ram:LineOne><ram:CityName>{e(buyer["city"])}</ram:CityName><ram:CountryID>{buyer["country"]}</ram:CountryID></ram:PostalTradeAddress>
        {buyer_uri}
      </ram:BuyerTradeParty>
      <ram:BuyerOrderReferencedDocument><ram:IssuerAssignedID>{e(spec["order_reference"])}</ram:IssuerAssignedID></ram:BuyerOrderReferencedDocument>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime>{_cii_date(spec["delivery_date"])}</ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>{spec["currency"]}</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{spec["iban"]}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>{_money(totals["tax"])}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>{_money(totals["net"])}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{spec["rate"]}</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:BillingSpecifiedPeriod><ram:StartDateTime>{_cii_date(start)}</ram:StartDateTime><ram:EndDateTime>{_cii_date(end)}</ram:EndDateTime></ram:BillingSpecifiedPeriod>
      <ram:SpecifiedTradePaymentTerms><ram:Description>{e(spec["payment_terms"])}</ram:Description><ram:DueDateDateTime>{_cii_date(spec["due_date"])}</ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{_money(totals["line"])}</ram:LineTotalAmount>
        <ram:ChargeTotalAmount>0.00</ram:ChargeTotalAmount>
        <ram:AllowanceTotalAmount>0.00</ram:AllowanceTotalAmount>
        <ram:TaxBasisTotalAmount>{_money(totals["net"])}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="{spec["currency"]}">{_money(totals["tax"])}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{_money(totals["grand"])}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{_money(totals["grand"])}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    return xml.encode("utf-8")


def hybrid_visual_lines(spec: dict[str, Any], *, visual_override: dict[str, Decimal] | None = None) -> list[str]:
    """Bildteil der hybriden Rechnung; ``visual_override`` erzeugt gezielt Abweichungen (Tests)."""
    net = sum((line[4] for line in spec["lines"]), Decimal(0))
    tax = (net * spec["rate"] / 100).quantize(Decimal("0.01"))
    values = {"net": net, "tax": tax, "grand": net + tax, **(visual_override or {})}
    seller, buyer = spec["seller"], spec["buyer"]
    start, end = spec["period"]
    iban = " ".join(spec["iban"][i : i + 4] for i in range(0, len(spec["iban"]), 4))
    lines = [
        seller["name"],
        f"{seller['street']}, {seller['postcode']} {seller['city']}",
        f"Steuernummer: {seller['tax_number']}   USt-IdNr.: {seller['vat_id']}",
        "",
        f"An: {buyer['name']}",
        f"{buyer['street']}, {buyer['postcode']} {buyer['city']}",
    ]
    if spec.get("buyer_reference"):
        lines.append(f"Leitweg-ID: {spec['buyer_reference']}   Bestellnummer: {spec['order_reference']}")
    lines += [
        "",
        f"RECHNUNG Nr. {spec['number']}",
        f"Rechnungsdatum: {spec['issue_date']:%d.%m.%Y}",
        f"Leistungszeitraum: {start:%d.%m.%Y} - {end:%d.%m.%Y}",
        "",
    ]
    for line_id, name, quantity, unit, amount in spec["lines"]:
        unit_label = "Std." if unit == "HUR" else "Stk."
        lines.append(f"Pos. {line_id}  {quantity} {unit_label} {name}  {_de_money(amount)} EUR")
    lines += [
        "",
        f"Summe netto: {_de_money(values['net'])} EUR",
        f"zzgl. {spec['rate']} % USt: {_de_money(values['tax'])} EUR",
        f"Gesamtbetrag: {_de_money(values['grand'])} EUR",
        "",
        f"Zahlbar bis {spec['due_date']:%d.%m.%Y} auf IBAN {iban}",
        "Diese Rechnung ist eine hybride E-Rechnung (ZUGFeRD 2.3, Profil EN 16931).",
        "Maßgeblich ist der eingebettete XML-Datensatz factur-x.xml.",
    ]
    return lines


FACTURX_XMP = b"""<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
<fx:DocumentType>INVOICE</fx:DocumentType><fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>
<fx:Version>1.0</fx:Version><fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"""


def build_hybrid_pdf(spec: dict[str, Any], **visual: Any) -> bytes:
    """Hybride Rechnung: Bildteil + eingebettetes ``factur-x.xml`` (AFRelationship /Alternative)."""
    return build_pdf(
        [hybrid_visual_lines(spec, **visual)],
        attachments=[("factur-x.xml", build_cii_invoice(spec), "Alternative")],
        xmp=FACTURX_XMP,
    )


def demo_documents() -> list[tuple[str, bytes]]:
    """Liefert (Dateiname, PDF-Bytes) der vier Referenzdokumente.

    Alle vier entstehen aus Code - lokal und im Container (dort ist ``data/``
    per ``.dockerignore`` ausgeschlossen) byte-gleich.
    """
    return [
        ("Rechnung_Gueltig_14UStG.pdf", build_pdf([VALID_INVOICE_LINES])),
        ("Rechnung_Fehlerhaft_Steuerfalle.pdf", build_pdf([FAULTY_INVOICE_LINES])),
        ("KI_Recruiting_Dienstleistervertrag.pdf", build_pdf([RECRUITING_LINES])),
        (HYBRID_FILENAME, build_hybrid_pdf(HYBRID_INVOICE)),
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
                        "masked_value": "datenschutz@talentscreen.example",
                        "context": "Kontakt: datenschutz@talentscreen.example",
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
        "Es fehlt keine Pflichtangabe – alle nach § 14 Abs. 4 Satz 1 UStG sind vorhanden:\n"
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


REFERENCE_ANSWERS[HYBRID_FILENAME] = (
    "Es fehlt keine Pflichtangabe. Maßgeblich ist der eingebettete XML-Datensatz factur-x.xml [Z. 18] (BMF-Schreiben vom 15.10.2024, "
    "Rz. 36); er enthält alle Pflichtangaben nach § 14 Abs. 4 Satz 1 UStG:\n"
    "- Name und Anschrift von Leistendem [Z. 2] [Z. 3] und Empfänger [Z. 5] [Z. 6] (Nr. 1)\n"
    "- Steuernummer und USt-IdNr. [Z. 4] (Nr. 2; BT-31 im XML)\n"
    "- Rechnungsdatum [Z. 9] und Rechnungsnummer [Z. 8] (Nr. 3 und 4)\n"
    "- Leistungen [Z. 11] [Z. 12] und Leistungszeitraum [Z. 10] (Nr. 5 und 6)\n"
    "- Nettoentgelt, Steuersatz und Steuerbetrag [Z. 13] [Z. 14] (Nr. 7 und 8)\n"
    "Alle acht Kernwerte des XML stimmen mit dem Bildteil überein. Da der Käufer eine Behörde ist, ist "
    "zusätzlich die Leitweg-ID [Z. 7] nötig; Aufbau und Prüfziffer sind gültig.",
    "Gar nicht. Das Dokument ist eine Rechnung über Hosting und Betriebsunterstützung [Z. 11] [Z. 12] und "
    "beschreibt kein KI-System im Sinne von Art. 3 Nr. 1 VO (EU) 2024/1689. Anhang III Nr. 4 ist nicht "
    "einschlägig; die Prüfung lief deterministisch über den XML-Datensatz, ohne KI-Modell.",
    "Eine Korrektur ist nicht nötig. Der XML-Datensatz ist vollständig, die Summen sind stimmig "
    "(4.800,00 EUR + 912,00 EUR = 5.712,00 EUR [Z. 13] [Z. 14] [Z. 15]), die IBAN besteht die Prüfziffernkontrolle "
    "[Z. 16], und der Bildteil weicht nicht vom XML ab. Wichtig für die Archivierung: Aufzubewahren ist die "
    "Datei so, wie sie empfangen wurde – einschließlich des XML-Datensatzes (§ 14b UStG, § 147 AO).",
)


STANDARD_QUESTIONS_EN = (
    "Which mandatory fields are missing from this invoice?",
    "Why does the system classify this PDF as Annex III No. 4?",
    "How must the invoice be corrected to qualify for input VAT deduction?",
)

STANDARD_QUESTIONS_ES = (
    "¿Qué datos obligatorios faltan en esta factura?",
    "¿Por qué clasifica el sistema este PDF como Anexo III n.º 4?",
    "¿Cómo debe corregirse la factura para poder deducir el IVA soportado?",
)

REFERENCE_ANSWERS_EN: dict[str, tuple[str, str, str]] = {
    "Rechnung_Gueltig_14UStG.pdf": (
        "No mandatory field is missing – all under § 14(4) sent. 1 UStG are present:\n"
        "- Supplier name and address [Z. 2] [Z. 3] and recipient [Z. 5] [Z. 6] (No. 1)\n"
        "- Tax number and VAT ID [Z. 4] (No. 2)\n"
        "- Issue date [Z. 8] and invoice number [Z. 7] (Nos. 3 & 4)\n"
        "- Scope and type of services [Z. 10] [Z. 11] and service period [Z. 9] (Nos. 5 & 6)\n"
        "- Net amount, VAT rate and VAT amount [Z. 12] [Z. 13] (Nos. 7 & 8)\n"
        "Note: This is a plain visual PDF ('other invoice' in domestic B2B since 01 Jan 2025, only permissible under transitional rules).",
        "Not at all. The document is an IT security services invoice and describes no AI system under Art. 3(1) Regulation (EU) 2024/1689.",
        "No correction required. The invoice meets § 14(4) UStG, VAT of 1,140.00 EUR matches 19% of net [Z. 12] [Z. 13], and IBAN passes MOD-97 [Z. 16]. Input VAT deduction under § 15(1) UStG is formally valid.",
    ),
    "Rechnung_Fehlerhaft_Steuerfalle.pdf": (
        "Two mandatory elements are missing:\n"
        "- Supplier tax number or VAT ID – missing from header [Z. 2] [Z. 3] (§ 14(4) sent. 1 No. 2 UStG)\n"
        "- Delivery/service date or period – only invoice issue date [Z. 7] is stated (§ 14(4) sent. 1 No. 6 UStG)\n"
        "Additional defects: VAT rate 16% [Z. 10] is invalid since 01 Jan 2021 (§ 12(1) UStG), and IBAN [Z. 12] fails the MOD-97 check digit.",
        "Not at all. It is an office furniture goods invoice [Z. 8] describing no AI system; Annex III No. 4 does not apply.",
        "The supplier must issue a corrected invoice:\n"
        "1. Add tax number or VAT ID (§ 14(4) sent. 1 No. 2 UStG).\n"
        "2. Add supply/service date (No. 6).\n"
        "3. Apply the standard 19% VAT rate (§ 12(1) UStG).\n"
        "4. Fix the bank details – IBAN [Z. 12] is invalid; verify out-of-band before payment.\n"
        "Until corrected, input VAT deduction (§ 15(1) UStG) is at risk. Not binding tax/legal advice.",
    ),
    "KI_Recruiting_Dienstleistervertrag.pdf": (
        "This document is a contract, not an invoice [Z. 2]. § 14(4) UStG invoice elements therefore do not apply directly, though a subsequent invoice must state invoice number, issue date, tax/VAT ID, net amount, tax rate and tax amount ('45000 EUR' [Z. 5] is insufficient).",
        "Because TalentAI evaluates job applicants automatically [Z. 4]. This falls under Annex III No. 4(a) Regulation (EU) 2024/1689 (recruitment/selection of natural persons) and is High-Risk under Art. 6(2); Art. 6(3) derogation does not apply to profiling.\n"
        "Deployer obligations (Art. 26): human oversight, ≥6 months log retention, inform worker representatives. Require EU conformity assessment (Art. 43) and CE mark (Art. 48) from provider. Annex III obligations apply from 02 Dec 2027 (Reg. (EU) 2026/1744).",
        "This is not an invoice; input VAT deduction requires a proper subsequent invoice stating all § 14(4) UStG items with net, tax rate and VAT separated ('45000 EUR' [Z. 5] leaves tax status open).",
    ),
}

REFERENCE_ANSWERS_ES: dict[str, tuple[str, str, str]] = {
    "Rechnung_Gueltig_14UStG.pdf": (
        "No falta ningún dato obligatorio: todos los requisitos del § 14(4) frase 1 UStG están presentes:\n"
        "- Nombre y dirección del emisor [Z. 2] [Z. 3] y destinatario [Z. 5] [Z. 6] (n.º 1)\n"
        "- NIF e ID de IVA [Z. 4] (n.º 2)\n"
        "- Fecha de emisión [Z. 8] y número de factura [Z. 7] (n.os 3 y 4)\n"
        "- Alcance y tipo de servicios [Z. 10] [Z. 11] y período [Z. 9] (n.os 5 y 6)\n"
        "- Base imponible, tipo e importe de IVA [Z. 12] [Z. 13] (n.os 7 y 8)\n"
        "Nota: Es un PDF visual simple (admisible solo en período transitorio B2B en Alemania desde 01/01/2025).",
        "De ningún modo. El documento es una factura de seguridad TI y no describe ningún sistema de IA según el art. 3(1) del Reglamento (UE) 2024/1689.",
        "No requiere corrección. Cumple el § 14(4) UStG, el IVA de 1.140,00 EUR corresponde al 19 % neto [Z. 12] [Z. 13] y el IBAN supera la verificación MOD-97 [Z. 16].",
    ),
    "Rechnung_Fehlerhaft_Steuerfalle.pdf": (
        "Faltan dos datos obligatorios:\n"
        "- NIF o ID de IVA del emisor – ausente en la cabecera [Z. 2] [Z. 3] (§ 14(4) n.º 2 UStG)\n"
        "- Fecha o período de entrega/prestación – solo consta fecha de emisión [Z. 7] (§ 14(4) n.º 6 UStG)\n"
        "Defectos adicionales: tipo de IVA 16 % [Z. 10] inválido desde 01/01/2021 (§ 12(1) UStG) e IBAN [Z. 12] con dígito de control MOD-97 erróneo.",
        "De ningún modo. Es una factura de mobiliario [Z. 8] sin ningún sistema de IA.",
        "El proveedor debe emitir factura rectificada: 1) Añadir NIF/IVA; 2) Añadir fecha de entrega; 3) Aplicar 19 % de IVA; 4) Corregir y verificar el IBAN [Z. 12] antes de pagar. Deducción de IVA en riesgo (§ 15(1) UStG). Sin carácter de asesoría fiscal.",
    ),
    "KI_Recruiting_Dienstleistervertrag.pdf": (
        "El documento es un contrato, no una factura [Z. 2]. Para facturar posteriormente deberá incluirse número, fecha, NIF/IVA, período, base imponible, tipo y cuota de IVA ('45000 EUR' [Z. 5] es insuficiente).",
        "Porque TalentAI evalúa candidatos de forma automatizada [Z. 4] (Anexo III n.º 4(a) del Reglamento (UE) 2024/1689: selección de personal; alto riesgo art. 6(2), sin excepción art. 6(3) al elaborar perfiles).\n"
        "Obligaciones del responsable (art. 26): supervisión humana, registros ≥6 meses, informar a representantes laborales y exigir evaluación de conformidad (art. 43) y marcado CE (art. 48). Obligaciones aplicables desde 02/12/2027.",
        "No es una factura; la deducción de IVA soportado requiere una factura formal conforme al § 14(4) UStG con desglose de neto e IVA.",
    ),
}

REFERENCE_ANSWERS_EN[HYBRID_FILENAME] = (
    "No mandatory field is missing. The embedded XML dataset factur-x.xml prevails [Z. 18] (BMF 15 Oct 2024, para. 36) and contains all mandatory § 14(4) sent. 1 UStG fields, matching the visual PDF across all eight core values, plus a valid B2G Leitweg-ID [Z. 7].",
    "Not at all. The invoice covers hosting and operational support [Z. 11] [Z. 12] with no AI system; verified deterministically from XML without an LLM.",
    "No correction required. Sums reconcile (4,800.00 + 912.00 = 5,712.00 EUR [Z. 13]–[Z. 15]), IBAN passes MOD-97 [Z. 16], and XML matches PDF. Archive the received file including embedded XML (§ 14b UStG, § 147 AO).",
)

REFERENCE_ANSWERS_ES[HYBRID_FILENAME] = (
    "No falta ningún dato obligatorio. El XML incrustado factur-x.xml prevalece [Z. 18] (BMF 15/10/2024) e incluye todos los campos del § 14(4) UStG en consonancia con el PDF visual, además de una Leitweg-ID válida [Z. 7].",
    "De ningún modo. Factura por alojamiento y soporte operativo [Z. 11] [Z. 12] sin sistema de IA; verificada de forma determinista mediante XML.",
    "No requiere corrección. Los importes cuadran (4.800,00 + 912,00 = 5.712,00 EUR [Z. 13]–[Z. 15]) y el IBAN supera MOD-97 [Z. 16]. Conservar el archivo íntegro con su XML (§ 14b UStG, § 147 AO).",
)


def normalize_question(question: str) -> str:
    """Toleranter Vergleich: Gross-/Kleinschreibung, Leerzeichen und Satzzeichen egal."""
    return "".join(char for char in question.casefold() if char.isalnum())


#: Gleiche Musterantwort wie Frage 1 - für Rechnungen ohne fehlende Pflichtangaben schlägt die
#: Oberfläche diese Formulierung vor (statt „Welche Pflichtangaben fehlen …?“).
COMPLETE_FIELDS_QUESTIONS = (
    "Sind alle Pflichtangaben nach § 14 UStG vorhanden?",
    "Are all mandatory fields under Sec. 14 UStG present?",
    "¿Están presentes todos los datos obligatorios del § 14 UStG?",
)

_STANDARD_KEYS: dict[str, int] = {}
for _qs in (STANDARD_QUESTIONS, STANDARD_QUESTIONS_EN, STANDARD_QUESTIONS_ES):
    for _idx, _q in enumerate(_qs):
        _STANDARD_KEYS[normalize_question(_q)] = _idx
for _q in COMPLETE_FIELDS_QUESTIONS:
    _STANDARD_KEYS[normalize_question(_q)] = 0

_BY_LANG = {
    "de": REFERENCE_ANSWERS,
    "en": REFERENCE_ANSWERS_EN,
    "es": REFERENCE_ANSWERS_ES,
}


@cache
def hybrid_demo_sha256() -> str:
    """SHA-256 der hybriden Musterrechnung - Musterantworten gelten nur fuer exakt diese Datei."""
    return hashlib.sha256(build_hybrid_pdf(HYBRID_INVOICE)).hexdigest()


def reference_answer(filename: str, question: str, lang: str = "de") -> str | None:
    """Musterantwort fuer eine Standardfrage zu einem Musterdokument (sonst ``None``)."""
    index = _STANDARD_KEYS.get(normalize_question(question))
    answers = _BY_LANG.get(lang, REFERENCE_ANSWERS).get(filename) or REFERENCE_ANSWERS.get(filename)
    if index is None or answers is None:
        return None
    return answers[index]
