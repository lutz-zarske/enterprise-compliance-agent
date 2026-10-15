"""VIES-Live-Pruefung der USt-IdNr. (POST /api/vat/verify).

VIES ist ueber ``FakeVies`` auf HTTP-Ebene gemockt (``httpx.MockTransport``):
Normalisierung, Fehlerabbildung und Antwortaufbereitung in ``app/vies.py``
laufen vollstaendig mit, ohne dass ein Test das Netz beruehrt.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.vies import ViesInputError, normalize_vat
from tests.conftest import FakeVies

URL = "/api/vat/verify"


def test_valid_german_number_without_name(client: TestClient, fake_vies: FakeVies) -> None:
    response = client.post(URL, json={"country_code": "DE", "vat_number": "312345678"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["country_code"] == "DE"
    assert body["vat_number"] == "312345678"
    # Deutschland uebermittelt ueber VIES weder Namen noch Anschrift ("---").
    assert body["name"] is None
    assert body["address"] is None
    assert body["request_date"].startswith("2026-10-07T09:15:00")
    assert body["source"] == "VIES – Europäische Kommission"
    assert fake_vies.calls == [{"countryCode": "DE", "vatNumber": "312345678"}]


def test_foreign_number_returns_trader_name(client: TestClient) -> None:
    body = client.post(URL, json={"country_code": "fr", "vat_number": "40303265045"}).json()

    assert body["valid"] is True
    assert body["name"] == "SA ODIGEO FRANCE"
    assert body["address"].endswith("PARIS")


def test_unknown_number_is_reported_invalid(client: TestClient) -> None:
    response = client.post(URL, json={"country_code": "DE", "vat_number": "999999999"})

    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_prefix_and_separators_are_normalised(client: TestClient, fake_vies: FakeVies) -> None:
    response = client.post(URL, json={"country_code": "DE", "vat_number": "DE 312.345-678"})

    assert response.status_code == 200
    assert fake_vies.calls[-1] == {"countryCode": "DE", "vatNumber": "312345678"}


@pytest.mark.parametrize(
    ("country", "number", "expected"),
    [
        ("DE", "DE312345678", ("DE", "312345678")),
        ("gr", "EL094259216", ("EL", "094259216")),
        ("EL", "GR094259216", ("EL", "094259216")),
        ("AT", "U12345678", ("AT", "U12345678")),
    ],
)
def test_normalize_vat(country: str, number: str, expected: tuple[str, str]) -> None:
    assert normalize_vat(country, number) == expected


@pytest.mark.parametrize(
    ("country", "number"),
    [("US", "123456789"), ("DE", "12345678"), ("DE", "31234567X"), ("FR", "ABC$")],
)
def test_invalid_input_is_rejected_before_calling_vies(
    client: TestClient, fake_vies: FakeVies, country: str, number: str
) -> None:
    with pytest.raises(ViesInputError):
        normalize_vat(country, number)

    response = client.post(URL, json={"country_code": country, "vat_number": number})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "vies_invalid_input"
    assert fake_vies.calls == []


def test_missing_fields_fail_validation(client: TestClient) -> None:
    response = client.post(URL, json={"country_code": "DE"})

    assert response.status_code == 422


@pytest.mark.parametrize("code", ["MS_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ", "SERVICE_UNAVAILABLE"])
def test_member_state_outage_maps_to_503(client: TestClient, fake_vies: FakeVies, code: str) -> None:
    fake_vies.mode = "error"
    fake_vies.error_code = code

    response = client.post(URL, json={"country_code": "DE", "vat_number": "312345678"})

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "vies_unavailable"
    assert code in error["message"]
    assert error["hint"]


def test_vies_input_error_maps_to_422(client: TestClient, fake_vies: FakeVies) -> None:
    fake_vies.mode = "error"
    fake_vies.error_code = "INVALID_INPUT"

    response = client.post(URL, json={"country_code": "DE", "vat_number": "312345678"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "vies_invalid_input"


@pytest.mark.parametrize(
    ("mode", "fragment"),
    [("timeout", "3 s"), ("offline", "nicht erreichbar"), ("garbage", "HTTP 502")],
)
def test_transport_failures_map_to_503(
    client: TestClient, fake_vies: FakeVies, mode: str, fragment: str
) -> None:
    fake_vies.mode = mode

    response = client.post(URL, json={"country_code": "DE", "vat_number": "312345678"})

    assert response.status_code == 503
    assert fragment in response.json()["error"]["message"]


def test_requires_api_key_when_configured(make_client: Callable[..., TestClient], fake_vies: FakeVies) -> None:
    secured = make_client(api_key="geheim")

    denied = secured.post(URL, json={"country_code": "DE", "vat_number": "312345678"})
    allowed = secured.post(
        URL, json={"country_code": "DE", "vat_number": "312345678"}, headers={"X-API-Key": "geheim"}
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert len(fake_vies.calls) == 1


def test_vies_is_rate_limited(make_client: Callable[..., TestClient]) -> None:
    limited = make_client(rate_limit_vies_per_minute=2)
    payload = {"country_code": "DE", "vat_number": "312345678"}

    statuses = [limited.post(URL, json=payload).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]


def test_full_app_uses_mocked_transport(full_client: TestClient, fake_vies: FakeVies) -> None:
    """Auch der Produktionspfad ohne Dependency-Overrides bleibt offline."""
    response = full_client.post(URL, json={"country_code": "DE", "vat_number": "312345678"})

    assert response.status_code == 200
    assert len(fake_vies.calls) == 1
