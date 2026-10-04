"""Tests fuer JSON-Logging, Request-Tracing, PII-Filter und Rate-Limiting."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.logging_config import (
    JsonFormatter,
    PIIRedactionFilter,
    normalize_request_id,
    request_id_var,
    scrub,
)
from app.rate_limit import RateLimitExceededError, TokenBucketLimiter
from tests.conftest import build_pdf

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _format(message: str, *args: object, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    PIIRedactionFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_json_log_enthaelt_request_id_und_zusatzfelder() -> None:
    token = request_id_var.set("req-123")
    try:
        payload = _format("Dokument %s verarbeitet", "abc", duration_ms=12.5)
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "req-123"
    assert payload["message"] == "Dokument abc verarbeitet"
    assert payload["level"] == "INFO"
    assert payload["duration_ms"] == 12.5
    assert payload["timestamp"].endswith("+00:00")


def test_pii_filter_schwaerzt_iban_email_telefon_und_schluessel() -> None:
    payload = _format(
        "Fehler bei %s / %s / %s / %s",
        "DE89 3704 0044 0532 0130 00",
        "petra.simon@example.com",
        "+49 30 1234567",
        "sk-abcdefghijklmnop1234",
        raw_text="Vollstaendiger Dokumenttext",
    )

    message = str(payload["message"])
    assert "DE89" not in message and "[IBAN]" in message
    assert "petra.simon" not in message and "[EMAIL]" in message
    assert "1234567" not in message
    assert "sk-abc" not in message and "[SECRET]" in message
    assert payload["raw_text"] == "[REDACTED]"


def test_scrub_laesst_harmlose_texte_unveraendert() -> None:
    assert scrub("Upload von 3 Seiten in 120 ms") == "Upload von 3 Seiten in 120 ms"


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("abc-123_DEF.4:5", "abc-123_DEF.4:5"),
        ("evil\nINFO fake log line", None),
        ("x" * 200, None),
        (None, None),
    ],
)
def test_request_id_wird_gegen_log_injection_validiert(
    candidate: str | None, expected: str | None
) -> None:
    assert normalize_request_id(candidate) == expected


def test_client_request_id_wird_uebernommen_unsichere_ersetzt(client: TestClient) -> None:
    good = client.get("/health", headers={"X-Request-ID": "trace-42"})
    assert good.headers["X-Request-ID"] == "trace-42"

    bad = client.get("/health", headers={"X-Request-ID": "a b c <script>"})
    assert bad.headers["X-Request-ID"] != "a b c <script>"
    assert len(bad.headers["X-Request-ID"]) == 36  # neu vergebene UUID


def test_accesslog_traegt_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/documents", headers={"X-Request-ID": "trace-access"})
    records = [record for record in caplog.records if record.name == "app.access"]
    assert records
    assert records[-1].request_id == "trace-access"  # type: ignore[attr-defined]
    assert records[-1].http_status == 200  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Rate-Limiting
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_erlaubt_burst_und_fuellt_nach() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(clock=clock)

    for _ in range(3):
        limiter.hit("extract", "1.2.3.4", per_minute=3)
    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.hit("extract", "1.2.3.4", per_minute=3)
    assert exc_info.value.retry_after == 20  # 3/min -> ein Token alle 20 s

    # Andere Clients und andere Gruppen sind unabhaengig.
    limiter.hit("extract", "5.6.7.8", per_minute=3)
    limiter.hit("upload", "1.2.3.4", per_minute=3)

    clock.now += 20
    limiter.hit("extract", "1.2.3.4", per_minute=3)


def test_limit_null_bedeutet_unbegrenzt() -> None:
    limiter = TokenBucketLimiter()
    for _ in range(100):
        limiter.hit("upload", "x", per_minute=0)


def test_api_antwortet_mit_429_und_retry_after(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(rate_limit_upload_per_minute=2)
    pdfs = [build_pdf([[f"Rechnung Nr. {index}", "Betrag 10,00 EUR", "x" * 50]]) for index in range(3)]

    statuses = [
        client.post("/documents/upload", files={"file": ("r.pdf", pdf, "application/pdf")}).status_code
        for pdf in pdfs
    ]
    assert statuses == [201, 201, 429]

    blocked = client.post("/documents/upload", files={"file": ("r.pdf", pdfs[0], "application/pdf")})
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1

    # Lesende Endpunkte sind nicht limitiert.
    assert client.get("/documents").status_code == 200


def test_rate_limit_abschaltbar(make_client: Callable[..., TestClient]) -> None:
    client = make_client(rate_limit_enabled=False, rate_limit_upload_per_minute=1)
    for index in range(3):
        pdf = build_pdf([[f"Beleg {index}", "Betrag 10,00 EUR", "y" * 50]])
        response = client.post("/documents/upload", files={"file": ("r.pdf", pdf, "application/pdf")})
        assert response.status_code == 201
