"""v2.8.2: Netto (BT-109) umfasst steuerfreie Posten – Summenregel ohne Fehlalarm.

Beleg wie in der Praxisprüfung: Druckerpapier 100,00 EUR (19 %), Porto als
steuerfreier durchlaufender Posten 4,95 EUR, „Summe netto 104,95 EUR“,
„zzgl. 19 % USt auf 100,00 EUR: 19,00 EUR“, „Gesamtbetrag 123,95 EUR“.  Die
KI-Antwort ist fest vorgegeben – einmal mit der steuerpflichtigen
Bemessungsgrundlage (100,00) als Netto, einmal mit der Summe netto (104,95).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm import EXTRACTION_SYSTEM_PROMPT
from app.scoring import tax_free_positions
from tests.conftest import FakeOllama, build_pdf

PORTO_INVOICE = [
    "Bürobedarf Nord GmbH, Hafenstraße 12, 20457 Hamburg",
    "USt-IdNr.: DE123456789",
    "An: Beispiel AG, Hauptstraße 2, 54321 Beispielstadt",
    "Rechnung Nr. 2026-311 vom 10.11.2026",
    "Lieferdatum: 09.11.2026",
    "Pos. 1 Druckerpapier A4, 20 Pakete (19 %) 100,00 EUR",
    "Pos. 2 Porto (steuerfreier durchlaufender Posten) 4,95 EUR",
    "Summe netto: 104,95 EUR",
    "zzgl. 19 % USt auf 100,00 EUR: 19,00 EUR",
    "Gesamtbetrag: 123,95 EUR",
    "Die Kleinunternehmerregelung findet keine Anwendung.",
]

NEUTRAL_AUDIT: dict[str, Any] = {
    "ai_act": {
        "describes_ai_system": False,
        "overall_risk_level": "not_applicable",
        "systems": [],
        "reasoning": "Rechnung über Büromaterial, kein KI-System.",
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


def _extraction(net: str) -> dict[str, Any]:
    return {
        "doc_type": "Rechnung",
        "sender": "Bürobedarf Nord GmbH",
        "recipient": "Beispiel AG",
        "sender_address": "Hafenstraße 12, 20457 Hamburg",
        "recipient_address": "Hauptstraße 2, 54321 Beispielstadt",
        "document_number": "2026-311",
        "document_date": "2026-11-10",
        "service_date": "2026-11-09",
        "sender_vat_id": "DE123456789",
        "items_description": "20 Pakete Druckerpapier A4 und Porto",
        "net_amount": net,
        "tax_rate": 19,
        "tax_amount": "19.00",
        "total_amount": "123.95",
        "currency": "EUR",
        "summary": "Rechnung über Druckerpapier zuzüglich Porto.",
        "issues": [],
    }


def _math(client: TestClient, fake_ollama: FakeOllama, net: str) -> tuple[dict, dict[str, dict]]:
    fake_ollama.extraction_response = _extraction(net)
    fake_ollama.compliance_response = NEUTRAL_AUDIT
    pdf = build_pdf([PORTO_INVOICE])
    response = client.post("/documents/upload", files={"file": ("Rechnung_Porto.pdf", pdf, "application/pdf")})
    assert response.status_code == 201, response.text
    body = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()
    card = body["scorecard"]
    math = next(tile for tile in card["tiles"] if tile["key"] == "math")
    return card, {check["id"]: check for check in math["checks"]}


@pytest.mark.parametrize("net", ["100.00", "104.95"])
def test_porto_beleg_ohne_rechenfehler(client: TestClient, fake_ollama: FakeOllama, net: str) -> None:
    card, checks = _math(client, fake_ollama, net)
    assert checks["sum_check"]["deduction"] == 0, checks["sum_check"]
    assert checks["sum_check"]["status"] in {"pass", "warn"}
    assert checks.get("tax_calc", {}).get("deduction", 0) == 0
    assert "ustg_14c_conflict" not in checks
    assert card["release_blocked"] is False
    assert card["score"] == 100


def test_summe_netto_aus_belegtext_ersetzt_bemessungsgrundlage(client: TestClient, fake_ollama: FakeOllama) -> None:
    _, checks = _math(client, fake_ollama, "100.00")
    # Mit „Summe netto 104,95“ im Beleg stimmt die Summenregel ohne Hinweis.
    assert checks["sum_check"]["status"] == "pass"
    extraction = client.get("/documents").json()["items"][0]
    detail = client.get(f"/documents/{extraction['id']}").json()["extraction"]
    assert Decimal(str(detail["net_amount"])) == Decimal("104.95")
    assert any("Summe netto" in issue for issue in detail["issues"])


def test_differenz_gleich_steuerfreie_posten_ist_nur_hinweis(client: TestClient, fake_ollama: FakeOllama) -> None:
    lines = [line for line in PORTO_INVOICE if not line.startswith("Summe netto")]
    fake_ollama.extraction_response = _extraction("100.00")
    fake_ollama.compliance_response = NEUTRAL_AUDIT
    response = client.post(
        "/documents/upload", files={"file": ("ohne_summe.pdf", build_pdf([lines]), "application/pdf")}
    )
    body = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()
    card, extraction = body["scorecard"], body["extraction"]
    checks = {c["id"]: c for t in card["tiles"] for c in t["checks"]}
    # Seit v2.8.4: Netto wird um die steuerfreien Posten ergänzt (Kerndaten 104,95) – Summe stimmt.
    assert checks["sum_check"]["status"] == "pass" and checks["sum_check"]["deduction"] == 0
    assert Decimal(str(extraction["net_amount"])) == Decimal("104.95")
    assert any("steuerfreie Posten" in issue for issue in extraction["issues"])
    assert card["release_blocked"] is False


def test_echter_summenfehler_bleibt_mangel(client: TestClient, fake_ollama: FakeOllama) -> None:
    lines = [line for line in PORTO_INVOICE if not line.startswith("Summe netto")]
    lines = [line.replace("Gesamtbetrag: 123,95 EUR", "Gesamtbetrag: 130,00 EUR") for line in lines]
    fake_ollama.extraction_response = {**_extraction("100.00"), "total_amount": "130.00"}
    fake_ollama.compliance_response = NEUTRAL_AUDIT
    response = client.post("/documents/upload", files={"file": ("falsch.pdf", build_pdf([lines]), "application/pdf")})
    card = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()["scorecard"]
    checks = {c["id"]: c for t in card["tiles"] for c in t["checks"]}
    assert checks["sum_check"]["status"] == "fail" and checks["sum_check"]["deduction"] == 15


def test_steuerfreie_posten_erkennung() -> None:
    assert tax_free_positions("\n".join(PORTO_INVOICE)) == [Decimal("4.95")]
    assert tax_free_positions("Pos. 1 Beratung 1.000,00 EUR\nSumme netto 1.000,00 EUR") == []
    assert tax_free_positions("Versandkosten 0 % USt 5,90 EUR") == [Decimal("5.90")]


def test_prompt_klaert_netto_inklusive_steuerfreier_posten() -> None:
    assert "steuerfreie" in EXTRACTION_SYSTEM_PROMPT and "Summe netto" in EXTRACTION_SYSTEM_PROMPT
