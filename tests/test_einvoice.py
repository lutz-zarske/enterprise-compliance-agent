"""EN-16931-Parser: XML-Extraktion, Profile, BT-Mapping, Leitweg-ID, Diskrepanzen, Scorecard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.demo import (
    HYBRID_INVOICE,
    build_cii_invoice,
    build_hybrid_pdf,
    build_pdf,
    hybrid_visual_lines,
)
from app.extractors import (
    EInvoiceError,
    UnsupportedEInvoiceError,
    detect_profile,
    find_einvoice_attachment,
    parse_einvoice_xml,
    render_reading_text,
    to_extraction,
    validate_leitweg_id,
)
from app.extractors.einvoice import leitweg_check_digits
from app.pdf_reader import extract_text
from app.schemas import AIActAssessment, ComplianceAudit, EInvoiceData, ExtractionResult, GDPRAssessment
from app.scoring import compute_scorecard
from app.services import read_embedded_einvoice, uses_structured_path
from tests.einvoice_samples import (
    BILLION_LAUGHS_XML,
    XRECHNUNG_30,
    XXE_XML,
    ZUGFERD_1_XML,
    b2b_spec,
    build_ubl_invoice,
    hybrid_spec,
)


def _terms(invoice: EInvoiceData) -> dict[str, str | None]:
    return {field.bt: field.value for field in invoice.business_terms}


def _no_findings() -> ComplianceAudit:
    return ComplianceAudit(
        ai_act=AIActAssessment(), gdpr=GDPRAssessment(), model="test", audited_at="2026-10-01T00:00:00Z"
    )


def _structured_card(invoice: EInvoiceData, text: str):
    return compute_scorecard(
        to_extraction(invoice), _no_findings(), text, einvoice=invoice, structured=True
    )


def _check(card, check_id: str):
    return next((c for t in card.tiles for c in t.checks if c.id == check_id), None)


# ---------------------------------------------------------------------------
# XML-Extraktion und BT-Mapping
# ---------------------------------------------------------------------------


def test_cii_bt_mapping() -> None:
    invoice = parse_einvoice_xml(build_cii_invoice(HYBRID_INVOICE), source="embedded", attachment_name="factur-x.xml")
    assert (invoice.syntax, invoice.profile, invoice.is_einvoice) == ("CII", "EN 16931 (COMFORT)", True)
    terms = _terms(invoice)
    assert terms["BT-1"] == "ECS-2026-0412"
    assert terms["BT-2"] == "15.09.2026"
    assert terms["BT-10"] == "05999000-VERGABE-24"
    assert terms["BT-27"] == "Elbtal Cloud Solutions GmbH"
    assert terms["BT-31"] == "DE312345678"
    assert terms["BT-34"] == "rechnung@elbtal-cloud.example (Schema EM)"
    assert terms["BT-49"] == "05999000-VERGABE-24 (Schema 0204)"
    assert terms["BT-112"] == "5.712,00 EUR"
    assert invoice.seller.tax_number == "203/118/02417"
    assert invoice.net_total == Decimal("4800.00") and invoice.tax_total == Decimal("912.00")
    assert [line.name for line in invoice.lines][0].startswith("Hosting")
    assert invoice.period_start.isoformat() == "2026-08-01" and invoice.delivery_date.isoformat() == "2026-08-31"
    assert invoice.rule_violations == []
    assert len(invoice.xml_sha256) == 64


def test_ubl_xrechnung_bt_mapping() -> None:
    invoice = parse_einvoice_xml(build_ubl_invoice())
    assert (invoice.syntax, invoice.profile, invoice.profile_key) == ("UBL", "XRECHNUNG 3.0", "xrechnung")
    terms = _terms(invoice)
    assert terms["BT-1"] == "XR-2026-077"
    assert terms["BT-10"] == "04011000-1234512345-06"
    assert terms["BT-27"] == "Softwarehaus Nordhessen GmbH"
    assert terms["BT-31"] == "DE298765432"
    assert terms["BT-34"] == "rechnung@softwarehaus.example (Schema EM)"
    assert terms["BT-112"] == "1.297,00 EUR"  # 1.000 x 19 % + 100 x 7 %
    assert {(v.rate, v.tax_amount) for v in invoice.vat_breakdown} == {
        (Decimal("19"), Decimal("190.00")), (Decimal("7"), Decimal("7.00"))
    }
    assert invoice.public_buyer is True and invoice.leitweg.valid is True


def test_lesefassung_und_extraktion_aus_xml() -> None:
    invoice = parse_einvoice_xml(build_ubl_invoice())
    text = render_reading_text(invoice)
    assert "XRECHNUNG 3.0" in text and "Rechnungsnummer (BT-1): XR-2026-077" in text
    assert "Gesamtbetrag (BT-112): 1.297,00 EUR" in text
    extraction = to_extraction(invoice)
    assert extraction.doc_type.value == "invoice"
    assert extraction.sender == "Softwarehaus Nordhessen GmbH"
    assert extraction.total_amount == Decimal("1297.00")
    assert extraction.tax_rate is None  # Mischsteuersatz: Pruefung je Satz aus BG-23
    assert extraction.service_period == "01.09.2026 - 30.09.2026"


@pytest.mark.parametrize(
    ("spec", "key", "label"),
    [
        ("urn:cen.eu:en16931:2017", "en16931", "EN 16931 (COMFORT)"),
        ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended", "extended", "EXTENDED"),
        ("urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic", "basic", "BASIC"),
        ("urn:factur-x.eu:1p0:basicwl", "basic_wl", "BASIC WL"),
        ("urn:factur-x.eu:1p0:minimum", "minimum", "MINIMUM"),
        (XRECHNUNG_30, "xrechnung", "XRECHNUNG 3.0"),
        (
            XRECHNUNG_30 + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0",
            "xrechnung", "XRECHNUNG 3.0 (Extension)",
        ),
        ("urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0", "peppol", "PEPPOL BIS Billing 3.0"),
        ("urn:example:eigenes-profil", "unknown", "Unbekannt"),
    ],
)
def test_profil_erkennung(spec: str, key: str, label: str) -> None:
    assert detect_profile(spec) == (key, label)


def test_minimum_profil_ist_keine_e_rechnung() -> None:
    invoice = parse_einvoice_xml(build_cii_invoice(hybrid_spec(specification_id="urn:factur-x.eu:1p0:minimum")))
    assert invoice.is_einvoice is False
    assert invoice.rule_violations == []  # Geschaeftsregeln gelten fuer MINIMUM nicht
    embedded = invoice.model_copy(update={"source": "embedded"})
    assert uses_structured_path(embedded) is False  # Bildteil ist die Rechnung
    assert uses_structured_path(invoice) is True  # reines XML: es gibt nur den Datensatz


# ---------------------------------------------------------------------------
# Sicherheit und Fehlerfaelle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [XXE_XML, BILLION_LAUGHS_XML])
def test_dtd_und_entitaeten_werden_abgelehnt(payload: bytes) -> None:
    with pytest.raises(EInvoiceError, match="DTD"):
        parse_einvoice_xml(payload)


def test_zugferd_1_wird_als_nicht_unterstuetzt_erkannt() -> None:
    with pytest.raises(UnsupportedEInvoiceError, match="ZUGFeRD 1.0"):
        parse_einvoice_xml(ZUGFERD_1_XML)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"<kaputt><xml>", EInvoiceError),
        (b"<?xml version='1.0'?><Bestellung xmlns='urn:x'/>", UnsupportedEInvoiceError),
        (b"   ", EInvoiceError),
    ],
)
def test_ungueltiges_xml(payload: bytes, error: type[Exception]) -> None:
    with pytest.raises(error):
        parse_einvoice_xml(payload)


def test_geschaeftsregeln_br_co_15_und_br_de_15() -> None:
    spec = hybrid_spec(specification_id=XRECHNUNG_30, buyer_reference=None, override={"grand": Decimal("5812.00")})
    invoice = parse_einvoice_xml(build_cii_invoice(spec))
    rules = " ".join(invoice.rule_violations)
    assert "BR-CO-15" in rules and "5.812,00 EUR" in rules
    assert "BR-DE-15" in rules


# ---------------------------------------------------------------------------
# Leitweg-ID
# ---------------------------------------------------------------------------


def test_leitweg_id_pruefziffer_nach_kosit() -> None:
    # Beispiel der Formatspezifikation und Test-Leitweg-ID der KoSIT-Testsuite.
    assert validate_leitweg_id("04011000-1234512345-06").valid is True
    assert leitweg_check_digits("991", "33333TEST") == "33"
    assert validate_leitweg_id("991-33333TEST-33").valid is True
    assert validate_leitweg_id("991-33333test-33").valid is True  # Buchstaben ohne Ruecksicht auf Gross/Klein


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("04011000-1234512345-07", "Prüfziffer ungültig (erwartet 06"),
        ("PO-4711", "Kein Leitweg-ID-Format"),
        ("1-12", "Kein Leitweg-ID-Format"),
        ("04011000-12345_67-06", "Kein Leitweg-ID-Format"),
    ],
)
def test_leitweg_id_fehler(value: str, reason: str) -> None:
    check = validate_leitweg_id(value)
    assert check.valid is False and reason in (check.reason or "")


# ---------------------------------------------------------------------------
# Hybride PDF: Anhang und Abgleich mit dem Bildteil
# ---------------------------------------------------------------------------


def test_eingebettetes_xml_wird_gefunden() -> None:
    pdf = build_hybrid_pdf(HYBRID_INVOICE)
    attachment = find_einvoice_attachment(pdf)
    assert attachment is not None and attachment.name == "factur-x.xml"
    assert attachment.data == build_cii_invoice(HYBRID_INVOICE)
    assert find_einvoice_attachment(build_pdf([["Nur ein PDF ohne Anhang mit genug Text fuer den Reader."]])) is None


def test_deckungsgleicher_bildteil() -> None:
    pdf = build_hybrid_pdf(HYBRID_INVOICE)
    invoice = read_embedded_einvoice(pdf, extract_text(pdf).text)
    assert invoice is not None and invoice.source == "embedded"
    assert {check.status for check in invoice.visual_check} == {"match"}
    assert {check.bt for check in invoice.visual_check} >= {"BT-1", "BT-31", "BT-84", "BT-109", "BT-110", "BT-112"}


def test_diskrepanz_bei_abweichenden_betraegen() -> None:
    pdf = build_hybrid_pdf(HYBRID_INVOICE, visual_override={"tax": Decimal("1012.00"), "grand": Decimal("5812.00")})
    invoice = read_embedded_einvoice(pdf, extract_text(pdf).text)
    mismatches = {check.bt: check for check in invoice.visual_check if check.status == "mismatch"}
    assert set(mismatches) == {"BT-110", "BT-112"}
    assert mismatches["BT-112"].xml_value == "5.712,00 EUR" and mismatches["BT-112"].visual_value == "5.812,00 EUR"

    card = _structured_card(invoice, extract_text(pdf).text)
    primacy = _check(card, "xml_primacy")
    assert primacy.status.value == "warn" and primacy.deduction == 10
    assert "Diskrepanz zwischen visuellem PDF und maßgeblichem XML-Datensatz" in primacy.detail
    assert "BMF 15.10.2024: XML hat Vorrang" in primacy.detail
    assert "§ 14c" in (primacy.risk_note or "")
    assert card.score == 90
    assert "Abweichung zwischen XML und PDF" in card.release_recommendation
    # Massgeblich bleiben die XML-Werte: Mathematik und Pflichtangaben sind sauber.
    assert all(c.status.value == "pass" for c in next(t for t in card.tiles if t.key == "math").checks)


def test_diskrepanz_bei_abweichender_iban() -> None:
    lines = [line.replace("DE02 1203 0000 0000 2020 51", "DE89 3704 0044 0532 0130 00")
             for line in hybrid_visual_lines(HYBRID_INVOICE)]
    pdf = build_pdf([lines], attachments=[("factur-x.xml", build_cii_invoice(HYBRID_INVOICE), "Alternative")])
    invoice = read_embedded_einvoice(pdf, extract_text(pdf).text)
    iban = next(check for check in invoice.visual_check if check.bt == "BT-84")
    assert iban.status == "mismatch" and iban.visual_value == "DE89…3000"


def test_fehlender_wert_im_bildteil_ohne_abzug() -> None:
    lines = [line for line in hybrid_visual_lines(HYBRID_INVOICE) if not line.startswith("Steuernummer")]
    pdf = build_pdf([lines], attachments=[("factur-x.xml", build_cii_invoice(HYBRID_INVOICE), "Alternative")])
    invoice = read_embedded_einvoice(pdf, extract_text(pdf).text)
    vat = next(check for check in invoice.visual_check if check.bt == "BT-31")
    assert vat.status == "not_found"
    primacy = _check(_structured_card(invoice, extract_text(pdf).text), "xml_primacy")
    assert primacy.status.value == "warn" and primacy.deduction == 0 and primacy.risk_note is None


def test_defekter_anhang_faellt_auf_textanalyse_zurueck() -> None:
    pdf = build_pdf([hybrid_visual_lines(HYBRID_INVOICE)], attachments=[("factur-x.xml", b"<kaputt>", "Alternative")])
    invoice = read_embedded_einvoice(pdf, extract_text(pdf).text)
    assert invoice is not None and invoice.error and invoice.attachment_name == "factur-x.xml"
    assert uses_structured_path(invoice) is False


# ---------------------------------------------------------------------------
# Scorecard: Leitweg-ID, Mischsteuersatz, Musterbeleg
# ---------------------------------------------------------------------------


def test_musterbeleg_erreicht_100_punkte() -> None:
    pdf = build_hybrid_pdf(HYBRID_INVOICE)
    text = extract_text(pdf).text
    card = _structured_card(read_embedded_einvoice(pdf, text), text)
    assert (card.score, card.band.value) == (100, "green")
    assert _check(card, "en16931").status.value == "pass"
    assert _check(card, "leitweg_id").status.value == "pass"
    assert _check(card, "ustg_4_number").evidence_source == "xml"


def test_b2g_ohne_leitweg_id_fuehrt_zu_abzug() -> None:
    spec = hybrid_spec(buyer_reference=None, buyer={"leitweg": None})
    invoice = parse_einvoice_xml(build_cii_invoice(spec))
    assert invoice.public_buyer is True and invoice.leitweg is None
    card = _structured_card(invoice, render_reading_text(invoice))
    leitweg = _check(card, "leitweg_id")
    assert leitweg.status.value == "fail" and leitweg.deduction == 10
    assert "Stadtverwaltung Musterstadt" in leitweg.detail
    assert "ERechV" in leitweg.legal_reference
    assert card.score == 90 and card.release_blocked is True


def test_b2g_mit_falscher_pruefziffer() -> None:
    spec = hybrid_spec(buyer_reference="05999000-VERGABE-25", buyer={"leitweg": None})
    card = _structured_card(parse_einvoice_xml(build_cii_invoice(spec)), "")
    assert "Prüfziffer ungültig (erwartet 24" in _check(card, "leitweg_id").detail


def test_b2b_ohne_leitweg_pruefung() -> None:
    invoice = parse_einvoice_xml(build_cii_invoice(b2b_spec()))
    assert invoice.public_buyer is False
    card = _structured_card(invoice, render_reading_text(invoice))
    assert _check(card, "leitweg_id") is None
    assert card.score == 100


def test_pdf_rechnung_an_behoerde_ohne_xml() -> None:
    extraction = ExtractionResult.model_validate(
        {"doc_type": "invoice", "sender": "X GmbH", "recipient": "Landratsamt Musterkreis",
         "document_number": "1", "document_date": "2026-09-01", "net_amount": 100, "tax_rate": 19,
         "tax_amount": 19, "total_amount": 119}
    )
    without = compute_scorecard(extraction, _no_findings(), "Rechnung an das Landratsamt Musterkreis")
    assert _check(without, "leitweg_id").status.value == "fail"
    assert "ERechV" in _check(without, "en16931").detail
    with_id = compute_scorecard(extraction, _no_findings(), "Leitweg-ID: 04011000-1234512345-06")
    assert _check(with_id, "leitweg_id").status.value == "pass"
    assert _check(with_id, "leitweg_id").evidence_source == "rule_based"


def test_mischsteuersatz_wird_je_satz_geprueft() -> None:
    invoice = parse_einvoice_xml(build_ubl_invoice())
    card = _structured_card(invoice, render_reading_text(invoice))
    assert _check(card, "tax_calc").status.value == "pass"
    assert _check(card, "vat_rate").status.value == "pass"
    assert card.score == 100

    wrong = parse_einvoice_xml(build_ubl_invoice(tax_overrides={"tax": Decimal("297.00"), "grand": Decimal("1297.00")}))
    assert any("BR-CO-14" in rule for rule in wrong.rule_violations)
    card = _structured_card(wrong, render_reading_text(wrong))
    assert _check(card, "sum_check").status.value == "fail"
    assert _check(card, "en16931").status.value == "warn"
