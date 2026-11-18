"""Regressionstests mit offiziellen Musterrechnungen (Herkunft und Lizenz: tests/fixtures/NOTICE).

* KoSIT XRechnung-Testsuite 01.01a (UBL, XRechnung 3.0): Leistungszeitraum steht
  nur in der Position (BG-26) und muss als Leistungszeitpunkt zählen.
* Mustangproject EN16931_Einfach.pdf (ZUGFeRD, EN 16931): Der Bildteil nennt
  „netto bis 15.12.2024“ in den Zahlungsbedingungen – ein Datum ist kein Betrag.
* Mustangproject invalidXRechnung.pdf: XRechnung 1.2 ohne Verkäufer-Kontakt
  (BR-DE-2, Befund des Mustang-Validators 2.26.0).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.demo import HYBRID_INVOICE, build_cii_invoice
from app.extractors.einvoice import parse_einvoice_xml, service_time, to_extraction, xrechnung_version_notice
from app.schemas import ScoreBand
from app.scoring import labeled_amounts, presented_band, verdict_band
from tests.conftest import FakeOllama

FIXTURES = Path(__file__).parent / "fixtures" / "official"


def _analyse(client: TestClient, name: str, content_type: str) -> tuple[dict, dict]:
    data = (FIXTURES / name).read_bytes()
    response = client.post("/documents/upload", files={"file": (name, data, content_type)})
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]
    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    detail = client.get(f"/documents/{document_id}").json()
    return body["scorecard"], detail


def _check(card: dict, check_id: str) -> dict:
    return next(c for tile in card["tiles"] for c in tile["checks"] if c["id"] == check_id)


# ---------------------------------------------------------------------------
# Die drei Belege über die API
# ---------------------------------------------------------------------------


def test_kosit_01_01a_positionszeitraum_zaehlt(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    card, _ = _analyse(client, "01.01a-INVOICE_ubl.xml", "application/xml")
    service = _check(card, "ustg_6_service_date")
    assert service["status"] == "pass"
    assert "01.01.2016 – 31.12.2016 (BG-26)" in service["detail"]
    assert "BR-DE-TMP-32" in service["detail"]  # Porto-Position ohne eigenen Zeitraum: nur Hinweis
    assert card["release_blocked"] is False
    assert (card["score"], card["band"]) == (100, "green")
    assert card["ustg_fulfilled"] == card["ustg_required_total"]


def test_mustang_en16931_einfach_ohne_abgleichsfehler(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    card, detail = _analyse(client, "EN16931_Einfach.pdf", "application/pdf")
    checks = {c["bt"]: c for c in detail["einvoice"]["visual_check"]}
    assert all(c["status"] == "match" for c in checks.values()), checks
    assert _check(card, "xml_primacy")["status"] == "pass"
    assert card["release_recommendation"] == "Zur Auszahlung freigegeben"
    assert (card["score"], card["band"]) == (100, "green")


def test_mustang_invalid_xrechnung_versionshinweis(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    card, detail = _analyse(client, "invalidXRechnung.pdf", "application/pdf")
    version = _check(card, "xrechnung_version")
    assert version["status"] == "warn" and version["deduction"] == 0
    assert "XRechnung 1.2" in version["detail"] and "31.12.2020" in version["detail"]
    assert "XRechnung 3.0" in version["detail"]
    assert any(rule.startswith("BR-DE-2:") for rule in detail["einvoice"]["rule_violations"])
    assert "BR-DE-2" in _check(card, "en16931")["detail"]


# ---------------------------------------------------------------------------
# Leistungszeitpunkt in CII: BG-14, BT-72 und BG-26
# ---------------------------------------------------------------------------

_HEADER_PERIOD = re.compile(rb"<ram:BillingSpecifiedPeriod>.*?</ram:BillingSpecifiedPeriod>", re.S)
_DELIVERY = re.compile(rb"<ram:ActualDeliverySupplyChainEvent>.*?</ram:ActualDeliverySupplyChainEvent>", re.S)
_LINE_SETTLEMENT = b"<ram:SpecifiedLineTradeSettlement>"
_LINE_PERIOD = (
    b"<ram:SpecifiedLineTradeSettlement><ram:BillingSpecifiedPeriod>"
    b'<ram:StartDateTime><udt:DateTimeString format="102">20260801</udt:DateTimeString></ram:StartDateTime>'
    b'<ram:EndDateTime><udt:DateTimeString format="102">20260831</udt:DateTimeString></ram:EndDateTime>'
    b"</ram:BillingSpecifiedPeriod>"
)


def _cii(*, header_period: bool, delivery: bool, line_period: bool) -> bytes:
    xml = build_cii_invoice(HYBRID_INVOICE)
    if not header_period:
        xml = _HEADER_PERIOD.sub(b"", xml)
    if not delivery:
        xml = _DELIVERY.sub(b"", xml)
    if line_period:
        xml = xml.replace(_LINE_SETTLEMENT, _LINE_PERIOD)
    return xml


@pytest.mark.parametrize(
    ("header_period", "delivery", "line_period", "source"),
    [
        (True, False, False, "BG-14"),
        (False, False, True, "BG-26"),
        (False, True, False, None),
    ],
)
def test_cii_leistungszeitpunkt(header_period: bool, delivery: bool, line_period: bool, source: str | None) -> None:
    invoice = parse_einvoice_xml(_cii(header_period=header_period, delivery=delivery, line_period=line_period))
    start, end, found, uncovered = service_time(invoice)
    assert found == source
    extraction = to_extraction(invoice)
    if source:
        assert (start, end) == (HYBRID_INVOICE["period"][0], HYBRID_INVOICE["period"][1])
        assert extraction.service_period == "01.08.2026 - 31.08.2026"
        assert uncovered == 0
    else:
        assert invoice.delivery_date == HYBRID_INVOICE["delivery_date"]
        assert extraction.service_date == HYBRID_INVOICE["delivery_date"]


def test_cii_ohne_jeden_leistungszeitpunkt() -> None:
    invoice = parse_einvoice_xml(_cii(header_period=False, delivery=False, line_period=False))
    assert service_time(invoice)[2] is None
    extraction = to_extraction(invoice)
    assert extraction.service_date is None and extraction.service_period is None


# ---------------------------------------------------------------------------
# Beträge im Bildteil und Ampel
# ---------------------------------------------------------------------------


def test_datum_und_zahlungsbedingungen_sind_keine_betraege() -> None:
    found = labeled_amounts(
        "Zahlbar innerhalb 30 Tagen netto bis 15.12.2024, 3% Skonto\n"
        "Nettobetrag fällig am 15.12.\n"
        "Rechnungssumme ohne USt. 473,00\n"
        "Umsatzsteuer (S) 275,00 7 19,25\n"
        "Steuerbetrag 56,87\n"
        "Gesamtbetrag der Zuschläge 0,00\n"
        "Bruttosumme 529,87\n"
    )
    assert found["net"] == [(1, Decimal("473.00"))]
    assert (1, Decimal("56.87")) in found["tax"]
    assert found["gross"] == [(1, Decimal("529.87"))]


def test_ampel_folgt_der_freigabeentscheidung() -> None:
    assert verdict_band(90, blocked=True, recommendation="Freigabe gesperrt — Nachforderung nötig") == (
        ScoreBand.AMBER, "Nachforderung nötig"
    )
    assert verdict_band(
        90, blocked=False, recommendation="Freigabe unter Vorbehalt — Abweichung zwischen XML und PDF klären"
    ) == (ScoreBand.AMBER, "Freigabe unter Vorbehalt")
    assert verdict_band(100, blocked=False, recommendation="Zur Auszahlung freigegeben") == (
        ScoreBand.GREEN, "Vollständig verkehrsfähig & konform"
    )
    assert verdict_band(40, blocked=True, recommendation="Freigabe gesperrt — Nachforderung nötig")[0] is ScoreBand.RED


def test_aeltere_ergebnisse_zeigen_die_ampel_der_freigabe() -> None:
    legacy = {
        "score": 90, "band": "green", "band_label": "Vollständig verkehrsfähig & konform",
        "release_blocked": True, "release_recommendation": "Freigabe gesperrt — Nachforderung nötig",
    }
    assert presented_band(legacy) == ("amber", "Nachforderung nötig")
    clean = {**legacy, "release_blocked": False, "release_recommendation": "Zur Auszahlung freigegeben"}
    assert presented_band(clean) == ("green", "Vollständig verkehrsfähig & konform")


def test_aktuelle_xrechnung_ohne_versionshinweis() -> None:
    invoice = parse_einvoice_xml((FIXTURES / "01.01a-INVOICE_ubl.xml").read_bytes())
    assert xrechnung_version_notice(invoice) is None
