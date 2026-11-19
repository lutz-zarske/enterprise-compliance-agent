"""Nachbesserungen v2.8.1: § 14c ohne Fehlalarm, Swagger im lokalen Betrieb, DNS-Rebinding."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.scoring import full_exemption_claim
from tests.conftest import FakeOllama, build_pdf

LOCAL = {"cors_origins": "http://127.0.0.1:3001,http://localhost:3001", "api_key": None}
REDACT = {"text": "Ansprechpartner: Max Mustermann, max@example.com"}


def _math_checks(client: TestClient, lines: list[str]) -> tuple[dict, dict[str, dict]]:
    response = client.post("/documents/upload", files={"file": ("r.pdf", build_pdf([lines]), "application/pdf")})
    assert response.status_code == 201, response.text
    card = client.post(f"/documents/{response.json()['id']}/extract?wait=true").json()["scorecard"]
    math = next(tile for tile in card["tiles"] if tile["key"] == "math")
    return card, {check["id"]: check for check in math["checks"]}


_HEAD = [
    "Muster GmbH, Musterweg 1, 12345 Musterstadt",
    "USt-IdNr.: DE123456789",
    "An: Beispiel AG, Hauptstraße 2, 54321 Beispielstadt",
    "Rechnung Nr. 2026-7 vom 01.09.2026",
    "Leistungsdatum: 31.08.2026",
    "Pos. 1 Beratung 10 Stunden 1.000,00 EUR",
]


def test_steuerfreier_durchlaufposten_ist_kein_14c_widerspruch(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    card, checks = _math_checks(client, [
        *_HEAD,
        "Pos. 2 Porto (steuerfrei, durchlaufender Posten) 5,00 EUR",
        "Summe netto: 1.005,00 EUR",
        "zzgl. 19 % USt auf 1.000,00 EUR: 190,00 EUR",
        "Gesamtbetrag: 1.195,00 EUR",
    ])
    assert "ustg_14c_conflict" not in checks
    assert checks["tax_calc"]["status"] == "warn" and checks["tax_calc"]["deduction"] == 0
    assert card["release_blocked"] is False


def test_reverse_charge_mit_steuerausweis_bleibt_14c_mangel(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    _, checks = _math_checks(client, [
        *_HEAD,
        "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge, § 13b UStG)",
        "Summe netto: 1.000,00 EUR",
        "zzgl. 19 % USt: 190,00 EUR",
        "Gesamtbetrag: 1.190,00 EUR",
    ])
    assert checks["ustg_14c_conflict"]["status"] == "fail"
    assert checks["ustg_14c_conflict"]["deduction"] == 10


def test_befreiungshinweise_ganzer_beleg_und_verneinung() -> None:
    assert full_exemption_claim("Kein Umsatzsteuerausweis: Kleinunternehmer nach § 19 UStG") is True
    assert full_exemption_claim("Die Kleinunternehmerregelung (§ 19 UStG) findet keine Anwendung.") is False
    assert full_exemption_claim("Porto steuerfrei", "Leistungen nach § 4 Nr. 14 UStG steuerfrei") is False
    assert full_exemption_claim(None, "Innergemeinschaftliche Lieferung, steuerfrei nach § 4 Nr. 1b UStG") is True


def test_swagger_im_lokalen_betrieb_erlaubt(make_client: Callable[..., TestClient]) -> None:
    client = make_client(**LOCAL)
    same_origin = {"Origin": "http://127.0.0.1:8001", "Sec-Fetch-Site": "same-origin"}
    response = client.post("http://127.0.0.1:8001/api/v1/redact", json=REDACT, headers=same_origin)
    assert response.status_code == 200, response.text


def test_fremde_website_bleibt_gesperrt(make_client: Callable[..., TestClient]) -> None:
    client = make_client(**LOCAL)
    foreign = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    response = client.post("http://127.0.0.1:8001/api/v1/redact", json=REDACT, headers=foreign)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site_forbidden"


def test_dns_rebinding_wird_abgewiesen(make_client: Callable[..., TestClient]) -> None:
    client = make_client(**LOCAL)
    rebinding = {"Origin": "http://evil.example:8001", "Sec-Fetch-Site": "same-origin"}
    for method, url in (("GET", "/documents"), ("POST", "/api/v1/redact")):
        response = client.request(
            method, f"http://evil.example:8001{url}", headers=rebinding, json=REDACT if method == "POST" else None
        )
        assert response.status_code == 403, (method, url)
        assert response.json()["error"]["code"] == "untrusted_host"
    # Skripte ohne Browser-Kennung (kein Sec-Fetch-Site) sind nicht betroffen.
    assert client.get("/documents").status_code == 200
    # Die eigene Oberfläche über Loopback bleibt erreichbar.
    ui = {"Origin": "http://127.0.0.1:3001", "Sec-Fetch-Site": "same-site"}
    assert client.get("http://127.0.0.1:8001/documents", headers=ui).status_code == 200
