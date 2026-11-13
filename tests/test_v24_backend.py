"""v2.4: Archiv, Musterbeleg-Auswahl, Ausweich-Kaskade, Modellwechsel im Ledger, Modell-Katalog."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from app.model_catalog import ModelInfo, family, parse_catalog, suggest_upgrade
from tests.conftest import uploaded_document_id


def _seed(client: TestClient, only: str | None = None) -> dict[str, str]:
    params = {"only": only} if only else None
    response = client.post("/api/demo/seed", params=params)
    assert response.status_code == 200, response.text
    return {item["filename"]: item["id"] for item in response.json()["items"]}


def _trail(client: TestClient, document_id: str) -> list[dict]:
    return client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"]


# --- Archiv -----------------------------------------------------------------


def test_archivieren_blendet_aus_und_protokolliert(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_Fehlerhaft_Steuerfalle.pdf"]
    detail = full_client.put(f"/documents/{document_id}/archive", json={"archived": True}).json()
    assert detail["archived"] is True and detail["archived_at"]
    listed = {item["id"]: item for item in full_client.get("/documents").json()["items"]}
    assert listed[document_id]["archived"] is True  # nie geloescht, nur markiert

    entry = _trail(full_client, document_id)[0]
    assert entry["event_type"] == "archive" and entry["signature_status"] == "valid"

    # Zweimal archivieren erzeugt keinen zweiten Eintrag.
    full_client.put(f"/documents/{document_id}/archive", json={"archived": True})
    assert [e["event_type"] for e in _trail(full_client, document_id)].count("archive") == 1

    restored = full_client.put(f"/documents/{document_id}/archive", json={"archived": False}).json()
    assert restored["archived"] is False and restored["archived_at"] is None
    assert _trail(full_client, document_id)[0]["event_type"] == "unarchive"
    assert full_client.get("/api/audit/verify").json()["valid"] is True


def test_archiv_unbekanntes_dokument(full_client: TestClient) -> None:
    response = full_client.put("/documents/00000000-0000-4000-8000-000000000000/archive", json={"archived": True})
    assert response.status_code == 404


# --- Musterbelege einzeln ------------------------------------------------------


def test_einzelner_musterbeleg(full_client: TestClient) -> None:
    items = full_client.post("/api/demo/seed", params={"only": "Rechnung_Fehlerhaft_Steuerfalle.pdf"}).json()
    assert [item["filename"] for item in items["items"]] == ["Rechnung_Fehlerhaft_Steuerfalle.pdf"]
    assert items["items"][0]["compliance_score"] == 45
    assert full_client.post("/api/demo/seed", params={"only": "gibt-es-nicht.pdf"}).status_code == 404


# --- Ausweich-Kaskade ---------------------------------------------------------------


def _gemini_overloaded(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, json={"error": {"message": "Resource has been exhausted"}})


def test_kaskade_wechselt_bei_429_und_protokolliert(
    make_full_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    client = make_full_client(cloud_handler=_gemini_overloaded)
    client.post(
        "/api/settings",
        json={"inference_mode": "gemini", "api_keys": {"gemini": "AIza-key-1234567890"}, "fallbacks": ["local"]},
    )
    document_id = uploaded_document_id(client, invoice_pdf)
    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 200, response.text

    detail = client.get(f"/documents/{document_id}").json()
    assert detail["provider"] == "local"
    switch = detail["compliance"]["failover"][0]
    assert (switch["from_provider"], switch["to_provider"], switch["reason_code"]) == (
        "gemini", "local", "provider_unavailable",
    )
    events = [entry["event_type"] for entry in _trail(client, document_id)]
    assert events[:2] == ["analysis", "provider_failover"]
    assert client.get("/api/audit/verify").json()["valid"] is True


def test_kaskade_ueberspringt_stufe_ohne_key(
    make_full_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    client = make_full_client(cloud_handler=_gemini_overloaded)
    client.post(
        "/api/settings",
        json={"inference_mode": "gemini", "api_keys": {"gemini": "AIza-key-1234567890"},
              "fallbacks": ["openai", "local"]},
    )
    document_id = uploaded_document_id(client, invoice_pdf)
    assert client.post(f"/documents/{document_id}/extract?wait=true").status_code == 200
    assert client.get(f"/documents/{document_id}").json()["provider"] == "local"


def test_ohne_kaskade_und_ohne_regelwerk_bleibt_der_fehler_sichtbar(
    make_full_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    client = make_full_client(cloud_handler=_gemini_overloaded, heuristic_fallback=False)
    client.post("/api/settings", json={"inference_mode": "gemini", "api_keys": {"gemini": "AIza-key-1234567890"}})
    document_id = uploaded_document_id(client, invoice_pdf)
    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_ohne_kaskade_schliesst_das_regelwerk_markiert_ab(
    make_full_client: Callable[..., TestClient], invoice_pdf: bytes
) -> None:
    client = make_full_client(cloud_handler=_gemini_overloaded)
    client.post("/api/settings", json={"inference_mode": "gemini", "api_keys": {"gemini": "AIza-key-1234567890"}})
    document_id = uploaded_document_id(client, invoice_pdf)
    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 200, response.text
    assert response.json()["compliance"]["heuristic"] is True
    assert client.get(f"/documents/{document_id}").json()["provider"] == "heuristic"


# --- Modellwechsel im Ledger ----------------------------------------------------------


def test_modellwechsel_wird_signiert_protokolliert(full_client: TestClient) -> None:
    full_client.post("/api/settings", json={"pii_strictness": "strict"})  # kein Modellbezug
    assert _trail(full_client, "system") == []

    full_client.post("/api/settings", json={"models": {"local": "qwen2.5:7b-instruct"}})
    entry = _trail(full_client, "system")[0]
    assert entry["event_type"] == "model_change" and entry["signature_status"] == "valid"
    assert entry["model_name"] == "qwen2.5:7b-instruct"
    assert entry["details"]["before"]["model"] != entry["details"]["after"]["model"]
    assert entry["prompt_hash"]

    full_client.post("/api/settings", json={"fallbacks": ["local"]})  # local ist primaer -> keine Aenderung
    assert len(_trail(full_client, "system")) == 1
    assert full_client.get("/api/settings").json()["fallbacks"] == []


# --- Modell-Katalog und Upgrade-Erkennung --------------------------------------------------


ANTHROPIC_CATALOG = {
    "data": [
        {"id": "claude-haiku-4-5-20251001", "created_at": "2025-10-01T00:00:00Z"},
        {"id": "claude-sonnet-5-5", "created_at": "2026-05-01T00:00:00Z"},
        {"id": "claude-sonnet-6-0", "created_at": "2026-10-20T00:00:00Z"},
    ]
}


def test_modell_liste_mit_upgrade_vorschlag(make_full_client: Callable[..., TestClient]) -> None:
    def cloud(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models") and request.headers["x-api-key"] == "sk-ant-test-123456"
        return httpx.Response(200, json=ANTHROPIC_CATALOG)

    client = make_full_client(cloud_handler=cloud)
    without_key = client.get("/api/settings/models", params={"provider": "anthropic"}).json()
    assert without_key["source"] == "suggested" and without_key["upgrade"] is None

    client.post("/api/settings", json={"api_keys": {"anthropic": "sk-ant-test-123456"},
                                       "models": {"anthropic": "claude-sonnet-5-5"}})
    body = client.get("/api/settings/models", params={"provider": "anthropic"}).json()
    assert body["source"] == "api"
    assert body["models"][0] == "claude-sonnet-6-0"  # neueste zuerst
    assert body["upgrade"] == "claude-sonnet-6-0"
    assert client.get("/api/settings").json()["models"]["anthropic"] == "claude-sonnet-5-5"  # nie still gewechselt

    local = client.get("/api/settings/models", params={"provider": "local"}).json()
    assert "qwen2.5:14b-instruct" in local["models"] and local["upgrade"] is None


def test_katalog_heuristik() -> None:
    assert family("gemini-2.5-flash-lite") == "flash+lite"
    assert family("claude-sonnet-5-5") == "sonnet"
    gemini = parse_catalog("gemini", {"models": [
        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-4-argon", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-4-carbon", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/lyria-3.5", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3-pro-preview-06", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    ]})
    assert [m.id for m in gemini] == ["gemini-3-pro", "gemini-2.5-pro"]
    assert suggest_upgrade("gemini-2.5-pro", gemini) == "gemini-3-pro"
    assert suggest_upgrade("gemini-3-pro", gemini) is None
    assert suggest_upgrade("gemini-2.5-flash", gemini) is None  # andere Klasse: kein Vorschlag

    openai = parse_catalog("openai", {"data": [
        {"id": "gpt-4o", "created": 1715000000}, {"id": "gpt-4o-realtime", "created": 1730000000},
        {"id": "whisper-1", "created": 1680000000}, {"id": "gpt-5", "created": 1755000000},
    ]})
    assert [m.id for m in openai] == ["gpt-5", "gpt-4o"]
    assert suggest_upgrade("gpt-4o", openai) == "gpt-5"
    assert suggest_upgrade("gpt-4o", [ModelInfo("gpt-4o", 1.0)]) is None
