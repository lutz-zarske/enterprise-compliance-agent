"""Regressionstests aus dem Praxistest mit öffentlichen Testbelegen (Mustangproject, KoSIT, EU-Kommission).

Die Belege selbst liegen nicht im Repository; nachgebaut sind die Zeilenmuster, an
denen das Regelwerk vor v2.8.4 falsch lag (Auswertung: docs/PRUEFMATRIX.md).
"""

from __future__ import annotations

from decimal import Decimal

from app.extractors.einvoice import compare_with_visual
from app.heuristics import heuristic_extraction
from app.schemas import EInvoiceData, EInvoiceVat
from app.scoring import analyze_text, complete_amounts, tax_breakdown


def _d(value: str) -> Decimal:
    return Decimal(value)


def test_zwei_steuerzeilen_mit_gleichem_satz_werden_addiert() -> None:
    text = (
        "Positionen netto 804,35 €\nVersandkosten netto 4,99 €\n"
        "Positionen USt. 19,00% auf 804,35 € 152,83 €\nVersandkosten USt. 19,00% auf 4,99 € 0,95 €\nEndsumme 963,12 €\n"
    )
    facts = analyze_text(text)
    assert facts.tax_amount == _d("153.78") and facts.gross_amount == _d("963.12")
    invoice = EInvoiceData(source="embedded", tax_total=_d("153.78"), currency="EUR",
                           vat_breakdown=[EInvoiceVat(rate=_d("19"), taxable_amount=_d("809.34"), tax_amount=_d("153.78"))])
    check = next(c for c in compare_with_visual(invoice, text) if c.bt == "BT-110")
    assert check.status == "match"  # vorher: Abweichung mit −10


def test_zu_und_abschlaege_sind_keine_steuerzeilen() -> None:
    text = (
        "Umsatzsteuer (S) 129,37 7 9,06\nUmsatzsteuer (S) 64,40 19 12,24\n"
        "Abschlag Sondernachlass 10,00 19%UST(S) -1,00\nZuschlag Versandkosten 137,30 7%UST(S) 5,80\n"
        "Transportkosten 19%UST(S) 3,00\n"
    )
    assert tax_breakdown(text) == [(_d("7"), _d("129.37"), _d("9.06")), (_d("19"), _d("64.40"), _d("12.24"))]
    assert analyze_text(text).tax_amount == _d("21.30")


def test_netto_steuer_brutto_in_einer_zeile_und_netto_mit_satz() -> None:
    text = "Nettobetrag (zzgl. 19,00% MwSt.) 376,37\n19,00% MwSt.: 376,37 71,51 447,88\nSumme gesamt 447,88\n"
    facts = analyze_text(text)
    assert tax_breakdown(text) == [(_d("19"), _d("376.37"), _d("71.51"))]
    assert (facts.net_amount, facts.tax_amount, facts.gross_amount) == (_d("376.37"), _d("71.51"), _d("447.88"))


def test_steuertabelle_ohne_steuerwort_bestaetigt_sich_selbst() -> None:
    text = "USt. Satz Nettopreis Ust.-Betrag\n7% 160,00 € 11,20 €\n19% 336,00 € 63,84 €\nUSt. Gesamt: 75,04 €\n"
    assert tax_breakdown(text) == [(_d("7"), _d("160.00"), _d("11.20")), (_d("19"), _d("336.00"), _d("63.84"))]
    # Positionen mit Satz, aber ohne passende Steuer, sind keine Steuerzeilen.
    assert tax_breakdown("Frühstück 2 x 15,00 EUR = 30,00 EUR (19 %)\n") == []


def test_englische_rechnung() -> None:
    text = "Subtotal 573.00\n19% VAT 108.87\nTotal € Incl. VAT 681.87\nVAT Registration No. DE123456789\n"
    facts = analyze_text(text)
    assert (facts.tax_amount, facts.gross_amount) == (_d("108.87"), _d("681.87"))
    extraction = complete_amounts(heuristic_extraction("Invoice # 4711\n" + text), text, rule_based=True)
    assert extraction.net_amount == _d("573.00")


def test_kontokennung_ohne_iban_form_wird_nicht_als_iban_geprueft() -> None:
    from app.schemas import ComplianceAudit, ExtractionResult
    from app.scoring import compute_scorecard

    extraction = ExtractionResult.model_validate({"doc_type": "invoice", "iban": "1234567891234"})
    audit = ComplianceAudit.model_validate({
        "ai_act": {"describes_ai_system": False, "overall_risk_level": "not_applicable"},
        "gdpr": {"contains_personal_data": False, "risk_level": "none"},
        "model": "test", "audited_at": "2026-11-19T00:00:00Z", "duration_ms": 0,
    })
    card = compute_scorecard(extraction, audit, "")
    iban = next(c for t in card.tiles for c in t.checks if c.id == "iban_mod97")
    assert iban.status.value == "not_applicable" and iban.deduction == 0


def test_mehrere_bankverbindungen_im_bildteil_sind_keine_abweichung() -> None:
    invoice = EInvoiceData(source="embedded", iban="DE88200800000970375700", currency="EUR")
    text = "IBAN DE89 3704 0044 0532 0130 00\nIBAN DE02 1203 0000 0000 2020 51\n"
    check = next(c for c in compare_with_visual(invoice, text) if c.bt == "BT-84")
    assert check.status == "not_found"


def test_mit_nachbarspalte_verschmolzene_iban_ist_keine_abweichung() -> None:
    invoice = EInvoiceData(source="embedded", iban="DE88200800000970375700", currency="EUR")
    text = "Weltweit Bank IBAN SWIFT Code Giro No.\n044 025 50 99-99-888 DE88 2008 0000 0970 375-9999\n"
    check = next(c for c in compare_with_visual(invoice, text) if c.bt == "BT-84")
    assert check.status == "not_found"
    other = "IBAN DE89 3704 0044 0532 0130 00\n"  # gültige, abweichende IBAN bleibt eine Abweichung
    assert next(c for c in compare_with_visual(invoice, other) if c.bt == "BT-84").status == "mismatch"


def test_rundungsdifferenz_im_rahmen_von_br_co_17() -> None:
    from app.schemas import ComplianceAudit, ExtractionResult
    from app.scoring import compute_scorecard

    einvoice = EInvoiceData(
        source="standalone", is_einvoice=True, profile_key="en16931", currency="HUF",
        net_total=_d("69180"), tax_total=_d("18679"), grand_total=_d("87859"),
        vat_breakdown=[EInvoiceVat(category="S", rate=_d("27"), taxable_amount=_d("69180"), tax_amount=_d("18679"))],
    )
    extraction = ExtractionResult.model_validate({"doc_type": "invoice", "currency": "HUF", "total_amount": "87859"})
    audit = ComplianceAudit.model_validate({
        "ai_act": {"describes_ai_system": False, "overall_risk_level": "not_applicable"},
        "gdpr": {"contains_personal_data": False, "risk_level": "none"},
        "model": "test", "audited_at": "2026-11-19T00:00:00Z", "duration_ms": 0,
    })
    card = compute_scorecard(extraction, audit, "", einvoice=einvoice, structured=True)
    calc = next(c for t in card.tiles for c in t.checks if c.id == "tax_calc")
    assert calc.status.value == "warn" and calc.deduction == 0 and "BR-CO-17" in (calc.detail or "")


def test_rechnungslayout_ohne_empfaenger_label() -> None:
    text = (
        "2017-05-09\nBei Spiel GmbH\nEcke 12\nBei Spiel GmbH ● Ecke 12 ● 12345 Stadthausen 12345 Stadthausen\n"
        "Theodor Est\nfon (555) 23 78 -0\nBahnstr. 42\n88802Spielkreis\n"
        "Rechnung # RE-20170509/505 von 09.05.2017\nLeistungsdatum 07.05.2017\n"
        "1,00 Künstlerische Gestaltung 7% 160,00 € 160,00 €\nNettobetrag: 160,00 €\n"
        "USt. Satz Nettopreis Ust.-Betrag\n7% 160,00 € 11,20 €\nGesamtbetrag: 171,20 €\n"
    )
    extraction = heuristic_extraction(text)
    assert extraction.sender == "Bei Spiel GmbH"
    assert extraction.recipient == "Theodor Est"
    assert extraction.document_number == "RE-20170509/505"
    assert str(extraction.document_date) == "2017-05-09"
    assert analyze_text(text).address_count >= 2
