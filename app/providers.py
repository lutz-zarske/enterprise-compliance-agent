"""Cloud-Provider fuer die Inferenz: Google Gemini, Anthropic Claude, OpenAI.

Alle drei Clients sind schmale ``httpx``-Transporte ohne SDK-Abhaengigkeit.
Sie erben Prompts, JSON-Extraktion, Schemavalidierung und Reparaturrunde von
``StructuredLLMClient`` - jeder Provider implementiert nur ``_post_chat``.

Datenschutz: Diese Clients werden ausschliesslich ueber den
``PrivacyVault`` (``app/privacy_vault.py``) angesprochen, der identifizierende
Werte vor dem Versand pseudonymisiert.  Siehe ``app/inference.py``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.llm import DEFAULT_SEED, LLMError, LLMResponseError, StructuredLLMClient

#: Antwortlaenge fuer strukturierte Audits (JSON mit Begruendungen).
MAX_OUTPUT_TOKENS = 4096


class ProviderNotConfiguredError(LLMError):
    """Cloud-Modus gewaehlt, aber kein API-Key hinterlegt."""

    code = "provider_not_configured"
    hint = "API-Key im Einstellungsdialog (Zahnrad) hinterlegen oder auf 'Lokal' umschalten."


class ProviderAuthError(LLMError):
    """Der Provider lehnt den API-Key ab."""

    code = "provider_auth_failed"
    hint = "API-Key pruefen; ggf. Berechtigung fuer das gewaehlte Modell freischalten."


class ProviderUnavailableError(LLMError):
    """Provider nicht erreichbar, ueberlastet oder Kontingent erschoepft."""

    code = "provider_unavailable"
    hint = "Spaeter erneut versuchen oder auf den lokalen Modus umschalten."


class ProviderTimeoutError(LLMError):
    code = "provider_timeout"
    hint = "CLOUD_TIMEOUT_SECONDS erhoehen oder ein schnelleres Modell waehlen."


class CloudLLMClient(StructuredLLMClient):
    """Gemeinsame Fehlerabbildung fuer HTTP-basierte Cloud-Provider."""

    provider = "cloud"
    label = "Cloud"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 180.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Fuer {self.label} ist kein API-Key hinterlegt.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=timeout_seconds, write=30.0, pool=10.0)
        )

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _send(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.label}: Zeitueberschreitung.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.label} nicht erreichbar: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(f"{self.label} lehnt den API-Key ab (HTTP {response.status_code}).")
        if response.status_code == 404:
            raise LLMResponseError(f"{self.label}: Modell '{self._model}' nicht gefunden (HTTP 404).")
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUnavailableError(
                f"{self.label} antwortet mit HTTP {response.status_code} (Ueberlast/Kontingent)."
            )
        if response.status_code >= 400:
            # Fehlertext des Providers kann Prompt-Auszuege enthalten -> gekuerzt.
            raise LLMResponseError(
                f"{self.label} antwortet mit HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise LLMResponseError(f"{self.label} lieferte kein JSON.") from exc

    async def test_connection(self) -> str:
        """Leichter Erreichbarkeits-/Auth-Test ohne Dokumentinhalt."""
        raise NotImplementedError  # pragma: no cover

    async def fetch_catalog(self) -> dict[str, Any]:
        """Rohantwort der Modell-Liste des Providers (ohne Dokumentinhalt)."""
        raise NotImplementedError  # pragma: no cover


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    return system, rest


class GeminiClient(CloudLLMClient):
    """Google Gemini ueber die Generative Language REST-API (``generateContent``)."""

    provider = "gemini"
    label = "Google Gemini"

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        system, rest = _split_system(messages)
        generation: dict[str, Any] = {"temperature": 0.0, "maxOutputTokens": 8192}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in rest
            ],
            "generationConfig": generation,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        data = await self._send(
            "POST",
            f"{self._base_url}/models/{self._model}:generateContent",
            json=body,
            headers={"x-goog-api-key": self._api_key},
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise LLMResponseError(
                f"Gemini lieferte keinen Text{f' (blockiert: {reason})' if reason else ''}."
            ) from exc

    async def test_connection(self) -> str:
        await self._send(
            "GET", f"{self._base_url}/models/{self._model}", headers={"x-goog-api-key": self._api_key}
        )
        return f"{self.label} erreichbar, Modell {self._model} verfuegbar."

    async def fetch_catalog(self) -> dict[str, Any]:
        return await self._send(
            "GET", f"{self._base_url}/models", params={"pageSize": 200}, headers={"x-goog-api-key": self._api_key}
        )


class AnthropicClient(CloudLLMClient):
    """Anthropic Claude ueber die Messages API."""

    provider = "anthropic"
    label = "Anthropic Claude"
    api_version = "2023-06-01"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "anthropic-version": self.api_version}

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        system, rest = _split_system(messages)
        if json_mode:
            system += (
                "\n\nAntworte ausschliesslich mit einem einzigen JSON-Objekt, ohne Markdown."
            )
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in rest],
        }
        data = await self._send("POST", f"{self._base_url}/messages", json=body, headers=self._headers())
        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text:
            raise LLMResponseError("Claude lieferte keinen Textinhalt.")
        return text

    async def test_connection(self) -> str:
        await self._send("GET", f"{self._base_url}/models/{self._model}", headers=self._headers())
        return f"{self.label} erreichbar, Modell {self._model} verfuegbar."

    async def fetch_catalog(self) -> dict[str, Any]:
        return await self._send("GET", f"{self._base_url}/models", params={"limit": 100}, headers=self._headers())


class OpenAIClient(CloudLLMClient):
    """OpenAI Chat Completions mit JSON-Mode."""

    provider = "openai"
    label = "OpenAI"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "seed": DEFAULT_SEED,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = await self._send(
            "POST", f"{self._base_url}/chat/completions", json=body, headers=self._headers()
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("OpenAI lieferte keine Nachricht.") from exc
        if not isinstance(content, str) or not content:
            raise LLMResponseError("OpenAI lieferte keinen Textinhalt.")
        return content

    async def test_connection(self) -> str:
        await self._send("GET", f"{self._base_url}/models/{self._model}", headers=self._headers())
        return f"{self.label} erreichbar, Modell {self._model} verfuegbar."

    async def fetch_catalog(self) -> dict[str, Any]:
        return await self._send("GET", f"{self._base_url}/models", headers=self._headers())
