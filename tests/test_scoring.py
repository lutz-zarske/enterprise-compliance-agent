"""Tests der deterministischen Compliance-Scorecard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.demo import FAULTY_INVOICE_LINES, RECRUITING_FALLBACK_LINES, VALID_INVOICE_LINES
from app.schemas import ComplianceAudit, ExtractionResult, ScoreBand
from app.scoring import analyze_text, band_for, compute_scorecard, detect_structured_einvoice


def _compliance(level: str = "not_applicable", findings: list[dict[str, Any]] | None = None,
                annex: list[str] | None = None) -> ComplianceAudit:
    systems = (
        [{"name": "TalentAI", "risk_level": level, "annex_iii_categories": annex or []}]
        if level not in {"not_applicable"} else []
    )
    return ComplianceAudit.model_validate(
        {
            "ai_act": {"describes_ai_system": level != "not_applicable", "overall_risk_level": level,
                       "systems": systems},
            "gdpr": {"findings": findings or []},
            "model": "test",
            "audited_at": datetime.now(UTC),
        }
    )


VALID_EXTRACTION = ExtractionResult.model_validate(
    {
        "doc_type": "invoice", "sender": "Nordlicht IT-Services GmbH", "recipient": "Brandt Maschinenbau AG",
        "sender_address": "Hafenstrasse 12, 20457 Hamburg", "recipient_address": "Industrieweg 7, 70565 Stuttgart",
        "sender_tax_number": "22/815/08150", "sender_vat_id": "DE287654321",
        "document_number": "RE-2025-0142", "document_date": "14.03.2025",
        "service_period": "01.02.2025 - 28.02.2025", "items_description": "Managed-Security-Service",
        "net_amount": "6.000,00", "tax_rate": "19", "tax_amount": "1.140,00", "total_amount": "7.140,00",
        "currency": "EUR", "iban": "DE89370400440532013000",
    }
)


def test_gueltige_rechnung_erreicht_100_und_freigabe() -> None:
    card = compute_scorecard(VALID_EXTRACTION, _compliance(), "\n".join(VALID_INVOICE_LINES))

    assert card.score == 100
    assert card.band is ScoreBand.GREEN
    assert card.release_recommendation == "Zur Auszahlung freigegeben"
    assert card.release_blocked is False
    assert card.ustg_fulfilled == card.ustg_required_total == 10
    formal = next(tile for tile in card.tiles if tile.key == "formal")
    assert formal.headline.startswith("Vollstaendig (10/10)")
    # Doppelter Nachweis LLM + Regex wird ausgewiesen.
    tax_check = next(check for check in formal.checks if check.id == "ustg_2_tax_id")
    assert tax_check.evidence_source == "both"
    # Reines PDF: Hinweis, aber kein Punktabzug.
    en = next(check for check in formal.checks if check.id == "en16931")
    assert en.status.value == "warn" and en.deduction == 0


def test_steuerfalle_ergibt_45_und_sperre() -> None:
    extraction = ExtractionResult.model_validate(
        {
            "doc_type": "invoice", "sender": "Schnell & Billig Handels GmbH",
            "recipient": "Brandt Maschinenbau AG", "recipient_address": "Industrieweg 7, 70565 Stuttgart",
            "document_number": "2025-77", "document_date": "02.05.2025",
            "items_description": "Bueromoebel-Set, 3 Stueck",
            "net_amount": "4.500,00", "tax_rate": "16 %", "tax_amount": "720,00", "total_amount": "5.220,00",
            "currency": "EUR", "iban": "DE12 3456 7890 1234 5678 90",
        }
    )
    card = compute_scorecard(extraction, _compliance(), "\n".join(FAULTY_INVOICE_LINES))

    deductions = {check.id: check.deduction for tile in card.tiles for check in tile.checks if check.deduction}
    assert deductions == {"ustg_2_tax_id": 20, "ustg_6_service_date": 10, "iban_mod97": 15, "vat_rate": 10}
    assert card.score == 45
    assert card.band is ScoreBand.RED
    assert card.release_blocked is True
    assert card.release_recommendation == "Freigabe gesperrt — Nachforderung noetig"


def test_regex_gegenprobe_rettet_luekenhafte_llm_extraktion() -> None:
    """Liefert das Modell nur Kernfelder, belegen die Textregeln die uebrigen Pflichtangaben."""
    sparse = ExtractionResult.model_validate(
        {"doc_type": "invoice", "sender": "Nordlicht IT-Services GmbH", "recipient": "Brandt Maschinenbau AG",
         "document_number": "RE-2025-0142", "document_date": "2025-03-14", "total_amount": 7140,
         "iban": "DE89370400440532013000"}
    )
    card = compute_scorecard(sparse, _compliance(), "\n".join(VALID_INVOICE_LINES))
    assert card.score == 100
    sources = {check.id: check.evidence_source for tile in card.tiles for check in tile.checks}
    assert sources["ustg_7_net"] == "rule_based"
    assert sources["ustg_6_service_date"] == "rule_based"


def test_textanalyse_liest_netto_steuer_brutto() -> None:
    facts = analyze_text("\n".join(VALID_INVOICE_LINES))
    assert (str(facts.net_amount), str(facts.tax_amount), str(facts.tax_rate), str(facts.gross_amount)) == (
        "6000.00", "1140.00", "19", "7140.00"
    )
    assert facts.vat_id and facts.tax_number and facts.service_date


def test_hochrisiko_ohne_konformitaet_deckelt_auf_59() -> None:
    contract = ExtractionResult.model_validate(
        {"doc_type": "contract", "sender": "TalentScreen AI GmbH", "iban": "DE89370400440532013000"}
    )
    card = compute_scorecard(
        contract, _compliance("high", annex=["employment_and_worker_management"]),
        "\n".join(RECRUITING_FALLBACK_LINES),
    )
    assert card.score == 59
    assert card.cap_applied and "Hochrisiko" in card.cap_applied
    assert card.release_recommendation.startswith("Freigabe gesperrt — Konformitaetsbewertung")
    formal = next(tile for tile in card.tiles if tile.key == "formal")
    assert formal.status.value == "not_applicable"
    regulatory = next(tile for tile in card.tiles if tile.key == "regulatory")
    assert "Anhang III Nr. 4" in (regulatory.checks[0].detail or "")


def test_hochrisiko_mit_konformitaetsnachweis_nur_abzug() -> None:
    contract = ExtractionResult.model_validate({"doc_type": "contract"})
    card = compute_scorecard(
        contract, _compliance("high", annex=["employment_and_worker_management"]),
        "Der Anbieter legt die EU-Konformitaetserklaerung und CE-Kennzeichnung vor.",
    )
    assert card.score == 90 and card.cap_applied is None
    assert card.release_blocked is False


def test_verbotene_praxis_deckelt_auf_20() -> None:
    card = compute_scorecard(ExtractionResult(), _compliance("unacceptable"), "")
    assert card.score == 0 or card.score <= 20
    assert card.band is ScoreBand.RED


def test_art9_daten_kosten_10_punkte() -> None:
    findings = [{"category": "health_data", "masked_value": "Attest", "source": "rule_based"}]
    card = compute_scorecard(ExtractionResult(doc_type="contract"), _compliance(findings=findings), "")
    assert card.score == 90
    privacy = next(tile for tile in card.tiles if tile.key == "privacy")
    assert privacy.status.value == "fail"


def test_kleinbetragsrechnung_reduzierter_katalog() -> None:
    small = ExtractionResult.model_validate(
        {"doc_type": "invoice", "sender": "Bueromarkt Nord GmbH", "sender_address": "Holstenstrasse 1, 24103 Kiel",
         "document_date": "02.02.2024", "items_description": "Druckerpapier", "tax_rate": 19,
         "total_amount": "119,00"}
    )
    card = compute_scorecard(small, _compliance(), "Bueromarkt Nord GmbH\nHolstenstraße 1, 24103 Kiel")
    assert card.small_amount_invoice is True
    assert card.score == 100
    formal = next(tile for tile in card.tiles if tile.key == "formal")
    na = [check.id for check in formal.checks if check.status.value == "not_applicable"]
    assert "ustg_2_tax_id" in na and "ustg_4_number" in na


def test_corona_steuersatz_2020_ist_zulaessig() -> None:
    base = {"doc_type": "invoice", "net_amount": 100, "tax_rate": 16, "tax_amount": 16, "total_amount": 116}
    in_2020 = compute_scorecard(ExtractionResult.model_validate({**base, "document_date": "2020-09-01"}),
                                _compliance(), "")
    in_2025 = compute_scorecard(ExtractionResult.model_validate({**base, "document_date": "2025-09-01"}),
                                _compliance(), "")
    rate = lambda card: next(c for t in card.tiles for c in t.checks if c.id == "vat_rate")  # noqa: E731
    assert rate(in_2020).status.value == "pass"
    assert rate(in_2025).status.value == "fail"


def test_rechenfehler_werden_erkannt() -> None:
    wrong = ExtractionResult.model_validate(
        {"doc_type": "invoice", "net_amount": 1000, "tax_rate": 19, "tax_amount": 180, "total_amount": 1200}
    )
    card = compute_scorecard(wrong, _compliance(), "")
    failed = {c.id for t in card.tiles for c in t.checks if c.status.value == "fail" and t.key == "math"}
    assert failed == {"sum_check", "tax_calc"}


def test_ustg_pruefung_abschaltbar() -> None:
    card = compute_scorecard(ExtractionResult(doc_type="invoice"), _compliance(), "", enforce_ustg_check=False)
    formal = next(tile for tile in card.tiles if tile.key == "formal")
    assert formal.status.value == "not_applicable"
    assert card.score == 100


@pytest.mark.parametrize(("score", "band"), [(100, "green"), (85, "green"), (84, "amber"), (60, "amber"), (59, "red")])
def test_baender(score: int, band: str) -> None:
    assert band_for(score).value == band


def test_zugferd_erkennung() -> None:
    assert detect_structured_einvoice(b"%PDF-1.7 ... /F (factur-x.xml) ...") is True
    assert detect_structured_einvoice(b"%PDF-1.4 plain") is False
    assert detect_structured_einvoice(None) is False
