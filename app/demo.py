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

import hashlib
from datetime import date
from decimal import Decimal
from functools import cache
from typing import Any
from xml.sax.saxutils import escape

from app.config import BASE_DIR


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
    """Liefert (Dateiname, PDF-Bytes) der vier Referenzdokumente."""
    try:
        recruiting = SAMPLE_CONTRACT.read_bytes()
    except OSError:
        recruiting = build_pdf([RECRUITING_FALLBACK_LINES])
    return [
        ("Rechnung_Gueltig_14UStG.pdf", build_pdf([VALID_INVOICE_LINES])),
        ("Rechnung_Fehlerhaft_Steuerfalle.pdf", build_pdf([FAULTY_INVOICE_LINES])),
        ("KI_Recruiting_Dienstleistervertrag.pdf", recruiting),
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


REFERENCE_ANSWERS[HYBRID_FILENAME] = (
    "Keine. Maßgeblich ist der eingebettete XML-Datensatz factur-x.xml [Z. 18] (BMF-Schreiben vom 15.10.2024, "
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


def normalize_question(question: str) -> str:
    """Toleranter Vergleich: Gross-/Kleinschreibung, Leerzeichen und Satzzeichen egal."""
    return "".join(char for char in question.casefold() if char.isalnum())


_STANDARD_KEYS = {normalize_question(question): index for index, question in enumerate(STANDARD_QUESTIONS)}


@cache
def hybrid_demo_sha256() -> str:
    """SHA-256 der hybriden Musterrechnung - Musterantworten gelten nur fuer exakt diese Datei."""
    return hashlib.sha256(build_hybrid_pdf(HYBRID_INVOICE)).hexdigest()


def reference_answer(filename: str, question: str) -> str | None:
    """Musterantwort fuer eine Standardfrage zu einem Musterdokument (sonst ``None``)."""
    index = _STANDARD_KEYS.get(normalize_question(question))
    answers = REFERENCE_ANSWERS.get(filename)
    if index is None or answers is None:
        return None
    return answers[index]
