"""Privacy Vault, Cloud-Provider, Laufzeit-Einstellungen und Cloud-Pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import build_repository
from app.llm import LLMResponseError, StructuredLLMClient
from app.privacy_vault import PrivacyVault, VaultedClient
from app.providers import (
    AnthropicClient,
    GeminiClient,
    OpenAIClient,
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)
from app.runtime_settings import RuntimeSettingsStore, mask_secret
from tests.conftest import (
    DEFAULT_COMPLIANCE,
    DEFAULT_EXTRACTION,
    RECRUITING_INVOICE_LINES,
    uploaded_document_id,
)

CLEAR_TEXT_SECRETS = ("DE89370400440532013000", "DE89 3704", "p.simon@talentmatch.example", "Petra Simon",
                      "TalentMatch GmbH", "32.725,00")

# ---------------------------------------------------------------------------
# PrivacyVault
# ---------------------------------------------------------------------------


def test_vault_pseudonymisiert_und_reidentifiziert_verlustfrei() -> None:
    text = "\n".join(RECRUITING_INVOICE_LINES)
    vault = PrivacyVault()
    pseudo = vault.pseudonymize(text)

    for secret in CLEAR_TEXT_SECRETS:
        assert secret not in pseudo
    assert "{{IBAN_1}}" in pseudo and "{{PERSON_1}}" in pseudo and "{{ORG_1}}" in pseudo
    assert vault.reidentify(pseudo) == text


def test_vault_vergibt_stabile_platzhalter() -> None:
    vault = PrivacyVault()
    first = vault.pseudonymize("IBAN DE89370400440532013000 und nochmal DE89370400440532013000")
    assert first.count("{{IBAN_1}}") == 2
    assert "{{IBAN_2}}" not in first
    # Zweiter Aufruf (z. B. Audit nach Extraktion) nutzt dasselbe Mapping.
    assert vault.pseudonymize("DE89370400440532013000") == "{{IBAN_1}}"


def test_vault_report_enthaelt_keinen_klartext() -> None:
    vault = PrivacyVault()
    vault.pseudonymize("Herr Max Mustermann, max@example.com, USt-IdNr. DE123456789, StNr 21/815/08150")
    report = vault.report
    assert report == {"EMAIL": 1, "PERSON": 1, "TAX_NUMBER": 1, "VAT_ID": 1}
    assert "Mustermann" not in json.dumps(report)


def test_vault_reidentifiziert_json_sicher() -> None:
    vault = PrivacyVault()
    token = vault._token_for("ORG", 'Back\\slash "Quote" GmbH')  # noqa: SLF001
    restored = vault.reidentify(f'{{"sender": "{token}"}}', json_escape=True)
    assert json.loads(restored)["sender"] == 'Back\\slash "Quote" GmbH'


class _RecordingInner(StructuredLLMClient):
    provider = "gemini"

    def __init__(self) -> None:
        self.seen: list[list[dict[str, str]]] = []

    @property
    def model(self) -> str:
        return "fake-cloud"

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        self.seen.append(messages)
        token = re.search(r"\{\{IBAN_\d+\}\}", messages[-1]["content"])
        return json.dumps({**DEFAULT_EXTRACTION, "iban": token.group(0) if token else None})


async def test_vaulted_client_sendet_keine_pii_und_setzt_werte_zurueck() -> None:
    inner = _RecordingInner()
    client = VaultedClient(inner)

    result, _ = await client.extract_document("\n".join(RECRUITING_INVOICE_LINES))

    outgoing = json.dumps(inner.seen, ensure_ascii=False)
    for secret in CLEAR_TEXT_SECRETS:
        assert secret not in outgoing
    assert "Platzhalter" in inner.seen[0][1]["content"]  # Vault-Hinweis als System-Nachricht
    assert result.iban == "DE89370400440532013000"  # lokal re-identifiziert


# ---------------------------------------------------------------------------
# Provider-Transporte
# ---------------------------------------------------------------------------


def _client(cls: type, handler: Callable[[httpx.Request], httpx.Response], key: str = "sk-test-123456"):
    return cls(api_key=key, model="m", base_url="https://api.example", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))


async def test_gemini_payload_und_antwort() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers["x-goog-api-key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]})

    text = await _client(GeminiClient, handler)._post_chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    )
    assert text == '{"a": 1}'
    assert captured["url"].endswith("/models/m:generateContent")
    assert captured["key"] == "sk-test-123456"
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "S"
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["temperature"] == 0.0


async def test_anthropic_payload_und_antwort() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"ok": true}'}]})

    text = await _client(AnthropicClient, handler)._post_chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    )
    assert text == '{"ok": true}'
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["headers"]["x-api-key"] == "sk-test-123456"
    assert captured["body"]["system"].startswith("S")
    assert captured["body"]["messages"] == [{"role": "user", "content": "U"}]


async def test_openai_payload_und_antwort() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 2}'}}]})

    text = await _client(OpenAIClient, handler)._post_chat([{"role": "user", "content": "U"}])
    assert text == '{"x": 2}'
    assert captured["auth"] == "Bearer sk-test-123456"
    assert captured["body"]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ProviderAuthError), (403, ProviderAuthError), (429, ProviderUnavailableError),
     (503, ProviderUnavailableError), (404, LLMResponseError), (400, LLMResponseError)],
)
async def test_provider_fehlerabbildung(status: int, error: type[Exception]) -> None:
    client = _client(OpenAIClient, lambda _r: httpx.Response(status, text="nope"))
    with pytest.raises(error):
        await client._post_chat([{"role": "user", "content": "U"}])


def test_provider_ohne_key_verweigert() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        GeminiClient(api_key="", model="m", base_url="https://x")


# ---------------------------------------------------------------------------
# Laufzeit-Einstellungen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "masked"),
    [("sk-proj-abcdefghijkl9876", "sk-...9876"), ("AIzaSyD-very-long-key-1234", "AIz...1234"),
     ("short", "****"), (None, None)],
)
def test_mask_secret(value: str | None, masked: str | None) -> None:
    assert mask_secret(value) == masked


async def test_keys_werden_verschluesselt_persistiert(settings: Settings) -> None:
    engine, _ = build_repository(settings)
    store = RuntimeSettingsStore(settings, engine)
    await store.update({"inference_mode": "anthropic", "api_keys": {"anthropic": "sk-ant-geheim-987654"}})

    with engine.connect() as connection:
        stored = connection.execute(sa.text("SELECT value FROM app_settings WHERE key='anthropic_api_key'")).scalar_one()
    assert "geheim" not in stored  # Fernet-Ciphertext

    reloaded = RuntimeSettingsStore(settings, engine)
    snap = reloaded.snapshot()
    assert snap.inference_mode.value == "anthropic"
    assert snap.key_for("anthropic") == "sk-ant-geheim-987654"
    assert (settings.data_dir / ".settings.key").exists()


def test_settings_api_liefert_nur_maskierte_keys(full_client: TestClient) -> None:
    initial = full_client.get("/api/settings").json()
    assert initial["inference_mode"] == "local"
    assert initial["has_gemini_key"] is False
    assert initial["pii_strictness"] == "standard"

    updated = full_client.post(
        "/api/settings",
        json={"inference_mode": "gemini", "api_keys": {"gemini": "AIzaSyTest-0000-1111-wxyz"},
              "models": {"gemini": "gemini-2.5-flash"}, "pii_strictness": "strict"},
    ).json()
    assert updated["inference_mode"] == "gemini"
    assert updated["active_model"] == "gemini-2.5-flash"
    assert updated["has_gemini_key"] is True
    assert updated["masked_keys"]["gemini"] == "AIz...wxyz"
    assert updated["privacy_gateway_active"] is True
    assert "AIzaSyTest" not in json.dumps(updated)

    deleted = full_client.post("/api/settings", json={"api_keys": {"gemini": ""}}).json()
    assert deleted["has_gemini_key"] is False


def test_settings_api_validiert_eingaben(full_client: TestClient) -> None:
    response = full_client.post("/api/settings", json={"inference_mode": "skynet"})
    assert response.status_code == 422
    assert full_client.post("/api/settings", json={"unbekannt": 1}).status_code == 422


def test_verbindungstest_lokal_und_cloud(make_full_client: Callable[..., TestClient]) -> None:
    def cloud(request: httpx.Request) -> httpx.Response:
        if request.headers.get("x-goog-api-key") == "AIza-good-key-123456":
            return httpx.Response(200, json={"name": "models/gemini-2.5-pro"})
        return httpx.Response(403, json={"error": "denied"})

    client = make_full_client(cloud_handler=cloud)
    local = client.post("/api/settings/test-connection", json={"provider": "local"}).json()
    assert local["ok"] is True

    missing = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    assert missing["ok"] is False and missing["code"] == "provider_not_configured"

    client.post("/api/settings", json={"api_keys": {"gemini": "AIza-bad-key-0000000"}})
    denied = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    assert denied["ok"] is False and denied["code"] == "provider_auth_failed"

    client.post("/api/settings", json={"api_keys": {"gemini": "AIza-good-key-123456"}})
    assert client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()["ok"] is True


# ---------------------------------------------------------------------------
# Cloud-Pipeline Ende-zu-Ende (Router + Vault)
# ---------------------------------------------------------------------------


class FakeGemini:
    """Antwortet wie Gemini und spiegelt die Platzhalter des Prompts zurueck."""

    def __init__(self) -> None:
        self.bodies: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        self.bodies.append(body)
        payload = json.loads(body)
        prompt = payload["contents"][-1]["parts"][0]["text"]
        system = payload["systemInstruction"]["parts"][0]["text"]

        def token(kind: str) -> str | None:
            match = re.search(r"\{\{" + kind + r"_\d+\}\}", prompt)
            return match.group(0) if match else None

        if "EU AI ACT" in system.upper():
            answer = json.loads(json.dumps(DEFAULT_COMPLIANCE))
            answer["gdpr"]["findings"][1]["masked_value"] = token("IBAN")
            answer["gdpr"]["findings"][1]["context"] = f"Bankverbindung: {token('IBAN')}"
        else:
            answer = {**DEFAULT_EXTRACTION, "iban": token("IBAN"), "sender": token("ORG"),
                      "total_amount": token("AMOUNT")}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]})


def test_cloud_analyse_ohne_klartext_pii(make_full_client: Callable[..., TestClient], invoice_pdf: bytes) -> None:
    gemini = FakeGemini()
    client = make_full_client(cloud_handler=gemini.handler)
    client.post("/api/settings", json={"inference_mode": "gemini", "api_keys": {"gemini": "AIza-key-1234567890"}})

    document_id = uploaded_document_id(client, invoice_pdf)
    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 200, response.text
    body = response.json()

    # 1. Kein Klartext hat den Rechner verlassen.
    assert len(gemini.bodies) == 2
    outgoing = "\n".join(gemini.bodies)
    for secret in CLEAR_TEXT_SECRETS:
        assert secret not in outgoing, secret

    # 2. Lokal re-identifiziert und anschliessend validiert.
    assert body["extraction"]["iban"] == "DE89370400440532013000"
    assert body["extraction"]["sender"] == "TalentMatch GmbH"
    assert body["extraction"]["total_amount"] == "32725.00"

    # 3. Herkunft und Vault-Statistik sind dokumentiert - ohne Klartext.
    assert body["provider"] == "gemini"
    assert body["compliance"]["provider"] == "gemini"
    gateway = body["compliance"]["privacy_gateway"]
    assert gateway["IBAN"] == 1 and gateway["EMAIL"] == 1
    # 4. Persistierte PII bleibt maskiert.
    stored_iban = next(f for f in body["compliance"]["gdpr"]["findings"] if f["category"] == "bank_account")
    assert stored_iban["masked_value"] == "DE89********3000"

    trail = client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"][0]
    assert trail["details"]["provider"] == "gemini"
    assert trail["compliance_score"] == body["scorecard"]["score"]


def test_cloud_modus_ohne_key_liefert_400(full_client: TestClient, invoice_pdf: bytes) -> None:
    full_client.post("/api/settings", json={"inference_mode": "openai"})
    document_id = uploaded_document_id(full_client, invoice_pdf)

    response = full_client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"
    # Das Dokument bleibt unveraendert verarbeitbar.
    assert full_client.get(f"/documents/{document_id}").json()["status"] == "uploaded"


def test_health_meldet_inferenzmodus(full_client: TestClient) -> None:
    body = full_client.get("/health").json()
    assert body["inference"] == {"mode": "local", "model": "qwen2.5:14b-instruct", "is_cloud": False,
                                 "privacy_gateway_active": False, "configured": True, "uses_local": True,
                                 "chain_length": 1, "heuristic_fallback": True, "open_jobs": 0}
    full_client.post("/api/settings", json={"inference_mode": "anthropic"})
    degraded = full_client.get("/health").json()
    assert degraded["status"] == "degraded" and degraded["inference"]["configured"] is False
