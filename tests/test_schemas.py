"""Tests der Pydantic-Normalisierung.

Diese Schicht ist der Puffer zwischen einem 14B-Modell und der Datenbank:
deutsche Zahlen- und Datumsformate, Platzhaltertexte statt ``null`` und
halluzinierte Enum-Werte duerfen den Lauf nicht abbrechen.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.schemas import (
    AIActAssessment,
    AIActRiskLevel,
    AnnexIIICategory,
    ComplianceAudit,
    DocType,
    ExtractionResult,
    GDPRAssessment,
    PIICategory,
    RiskLevel,
    iban_checksum_valid,
    parse_flexible_amount,
    parse_flexible_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("32.725,00 EUR", Decimal("32725.00")),
        ("1,234.56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("119,00", Decimal("119.00")),
        ("1.234", Decimal("1234")),
        ("2,5", Decimal("2.5")),
        (1234.5, Decimal("1234.5")),
        ("nicht angegeben", None),
        ("", None),
    ],
)
def test_betragsformate_werden_normalisiert(raw: object, expected: Decimal | None) -> None:
    assert parse_flexible_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-03-15", date(2024, 3, 15)),
        ("15.03.2024", date(2024, 3, 15)),
        ("15. Maerz 2024", date(2024, 3, 15)),
        ("15. März 2024", date(2024, 3, 15)),
        ("keine Angabe", None),
        ("Unsinn", None),
    ],
)
def test_datumsformate_werden_normalisiert(raw: str, expected: date | None) -> None:
    assert parse_flexible_date(raw) == expected


def test_extraktion_normalisiert_eine_typische_modellantwort() -> None:
    result = ExtractionResult.model_validate(
        {
            "doc_type": "Rechnung",
            "sender": "  TalentMatch   GmbH ",
            "recipient": "nicht angegeben",
            "document_number": "RE-2024-0815",
            "document_date": "15.03.2024",
            "due_date": "14.04.2024",
            "total_amount": "32.725,00",
            "currency": "€",
            "iban": "de89 3704 0044 0532 0130 00",
            "summary": "Zusammenfassung.",
            "issues": None,
            "halluziniertes_feld": "wird ignoriert",
        }
    )

    assert result.doc_type is DocType.INVOICE
    assert result.sender == "TalentMatch GmbH"
    assert result.recipient is None  # Platzhaltertext wurde zu null
    assert result.document_date == date(2024, 3, 15)
    assert result.total_amount == Decimal("32725.00")
    assert result.currency == "EUR"
    assert result.iban == "DE89370400440532013000"
    assert result.iban_valid is True
    assert result.issues == []


def test_ungueltige_iban_wird_als_solche_erkannt() -> None:
    assert iban_checksum_valid("DE89370400440532013000") is True
    assert iban_checksum_valid("DE89370400440532013001") is False
    assert iban_checksum_valid("keine IBAN") is False

    result = ExtractionResult.model_validate({"iban": "DE89370400440532013001"})
    assert result.iban_valid is False


def test_halluzinierte_annex_iii_kategorie_wird_verworfen() -> None:
    assessment = AIActAssessment.model_validate(
        {
            "describes_ai_system": True,
            "overall_risk_level": "high",
            "systems": [
                {
                    "name": "Screening Suite",
                    "risk_level": "high",
                    "annex_iii_categories": [
                        "employment_and_worker_management",
                        "voellig_erfunden",
                    ],
                    "confidence": "0,95",
                }
            ],
        }
    )

    system = assessment.systems[0]
    assert system.annex_iii_categories == [AnnexIIICategory.EMPLOYMENT]
    assert "Anhang III Nr. 4" in system.annex_iii_labels[0]
    assert system.confidence == pytest.approx(0.95)
    assert assessment.is_high_risk is True


def test_besondere_kategorien_werden_erkannt_und_gezaehlt() -> None:
    gdpr = GDPRAssessment.model_validate(
        {
            "contains_personal_data": True,
            "findings": [
                {"category": "health_data", "masked_value": "Attest"},
                {"category": "health_data", "masked_value": "Diagnose"},
                {"category": "contact_data", "masked_value": "m***@example.com"},
                {"category": "gibt_es_nicht", "masked_value": "x"},
            ],
            "risk_level": "high",
        }
    )

    assert len(gdpr.findings) == 3  # unbekannte Kategorie verworfen
    assert gdpr.contains_special_categories is True
    assert gdpr.findings_by_category == {"health_data": 2, "contact_data": 1}
    assert gdpr.findings[0].is_special_category is True


def test_compliance_audit_ueberlebt_den_json_roundtrip() -> None:
    """Der Audit wird als JSON persistiert und beim Lesen wieder validiert."""
    audit = ComplianceAudit.model_validate(
        {
            "ai_act": {"describes_ai_system": True, "overall_risk_level": "high"},
            "gdpr": {"contains_personal_data": True, "risk_level": "medium"},
            "model": "qwen2.5:14b-instruct",
            "audited_at": "2024-03-15T10:00:00Z",
        }
    )
    dumped = audit.model_dump(mode="json")

    assert "headline" in dumped  # berechnetes Feld ist Teil des Dumps
    restored = ComplianceAudit.model_validate(dumped)

    assert restored.ai_act.overall_risk_level is AIActRiskLevel.HIGH
    assert restored.gdpr.risk_level is RiskLevel.MEDIUM
    assert restored.headline.startswith("EU AI Act: Hochrisiko")


def test_leere_modellantwort_faellt_auf_sichere_defaults_zurueck() -> None:
    """Ein Modell, das ein leeres Objekt liefert, darf nichts behaupten."""
    assessment = AIActAssessment.model_validate({})
    assert assessment.describes_ai_system is False
    assert assessment.overall_risk_level is AIActRiskLevel.NOT_APPLICABLE
    assert assessment.is_high_risk is False

    gdpr = GDPRAssessment.model_validate({})
    assert gdpr.contains_personal_data is False
    assert gdpr.risk_level is RiskLevel.NONE
    assert PIICategory.HEALTH_DATA not in {finding.category for finding in gdpr.findings}
