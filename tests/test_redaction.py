"""Tests der Maskierung und der regelbasierten PII-Erkennung."""

from __future__ import annotations

from app.redaction import (
    enforce_masking,
    mask_email,
    mask_value,
    merge_findings,
    redact_text,
    scan_text,
)
from app.schemas import DetectionSource, PIICategory, PIIFinding


def test_maskierung_behaelt_nur_die_raender() -> None:
    assert mask_value("DE89370400440532013000") == "DE89********3000"
    assert mask_value("L01X00T47") == "L0*****47"
    assert mask_value("1234") == "****"
    assert mask_value("") == ""
    assert mask_email("max.mustermann@example.com") == "m***@example.com"


def test_freitext_verliert_alle_identifikatoren() -> None:
    text = "Bankverbindung DE89370400440532013000, Kontakt p.simon@talentmatch.example"
    redacted = redact_text(text)

    assert "DE89370400440532013000" not in redacted
    assert "p.simon@talentmatch.example" not in redacted
    assert "DE89********3000" in redacted
    assert "p***@talentmatch.example" in redacted


def test_regelscan_findet_iban_gesundheitsbezug_und_kontaktdaten() -> None:
    text = (
        "Rechnung an Nordwind AG. Bankverbindung: DE89370400440532013000. "
        "Ansprechpartnerin Dr. Petra Simon, p.simon@talentmatch.example. "
        "Ein Attest der Krankenkasse liegt der Personalakte bei. "
        "Steuer-ID: 12345678901"
    )
    findings = scan_text(text)
    categories = {finding.category for finding in findings}

    assert PIICategory.BANK_ACCOUNT in categories
    assert PIICategory.CONTACT_DATA in categories
    assert PIICategory.HEALTH_DATA in categories
    assert PIICategory.TAX_ID in categories
    # Alle Werte verlassen den Scanner bereits maskiert.
    assert all("DE89370400440532013000" not in finding.masked_value for finding in findings)
    assert all(finding.source is DetectionSource.RULE_BASED for finding in findings)


def test_ungueltige_iban_wird_vom_regelscan_ignoriert() -> None:
    """Die MOD-97-Pruefung haelt Fehlalarme aus Bestellnummern heraus."""
    findings = scan_text("Referenz DE00123456789012345678 ohne gueltige Pruefsumme.")
    assert not [f for f in findings if f.category is PIICategory.BANK_ACCOUNT]


def test_klartextwert_des_modells_wird_serverseitig_maskiert() -> None:
    """Kernschutz: Das Modell liefert Klartext, die DB sieht ihn nie."""
    leak = PIIFinding(
        category=PIICategory.BANK_ACCOUNT,
        masked_value="DE89370400440532013000",
        context="Bankverbindung: DE89370400440532013000",
        confidence=0.9,
    )

    masked = enforce_masking([leak])[0]

    assert masked.masked_value == "DE89********3000"
    assert "DE89370400440532013000" not in masked.context
    assert masked.is_special_category is False


def test_bereits_maskierte_werte_werden_nicht_erneut_maskiert() -> None:
    finding = PIIFinding(category=PIICategory.TAX_ID, masked_value="1234****8901")
    assert enforce_masking([finding])[0].masked_value == "1234****8901"


def test_doppelt_gefundene_treffer_werden_als_both_markiert() -> None:
    llm_finding = PIIFinding(
        category=PIICategory.BANK_ACCOUNT, masked_value="DE89********3000", confidence=0.6
    )
    rule_finding = PIIFinding(
        category=PIICategory.BANK_ACCOUNT,
        masked_value="DE89********3000",
        confidence=0.99,
        source=DetectionSource.RULE_BASED,
    )

    merged = merge_findings([llm_finding], [rule_finding])

    assert len(merged) == 1
    assert merged[0].source is DetectionSource.BOTH
    assert merged[0].confidence >= 0.9


def test_besondere_kategorien_stehen_in_der_ergebnisliste_vorn() -> None:
    findings = merge_findings(
        [
            PIIFinding(category=PIICategory.CONTACT_DATA, masked_value="m***@x.de", confidence=0.9),
            PIIFinding(category=PIICategory.HEALTH_DATA, masked_value="Diagnose", confidence=0.5),
        ],
        [],
    )
    assert findings[0].category is PIICategory.HEALTH_DATA


def test_ust_idnr_ist_keine_ausweisnummer_und_iban_keine_telefonnummer() -> None:
    findings = scan_text(
        "Steuernummer: 22/815/08150 USt-IdNr.: DE287654321\n"
        "Bankverbindung: DE89 3704 0044 0532 0130 00\nAusweisnummer: L01X00T47"
    )
    categories = [finding.category for finding in findings]
    assert categories.count(PIICategory.ID_DOCUMENT_NUMBER) == 1  # nur die echte Ausweisnummer
    assert PIICategory.CONTACT_DATA not in categories
