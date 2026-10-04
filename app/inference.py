"""Universeller Inference-Router: lokal (Ollama) oder Cloud (Gemini, Claude, GPT).

Der Router liest bei *jedem* Auftrag die aktuelle Laufzeitkonfiguration und
liefert einen passenden Client:

* ``local``  -> ``OllamaClient`` (kein Byte verlaesst den Rechner)
* ``gemini`` / ``anthropic`` / ``openai`` -> Cloud-Client, **immer** umhuellt
  vom ``VaultedClient``.  Ein Cloud-Aufruf ohne Privacy Gateway ist im Code
  nicht vorgesehen.

Pro Auftrag entsteht ein frischer ``PrivacyVault``; das Mapping lebt damit
nur so lange wie die Analyse eines einzelnen Dokuments.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.llm import OllamaClient, StructuredLLMClient
from app.privacy_vault import VaultedClient
from app.providers import (
    AnthropicClient,
    CloudLLMClient,
    GeminiClient,
    OpenAIClient,
    ProviderNotConfiguredError,
)
from app.runtime_settings import InferenceMode, RuntimeSettingsStore, RuntimeSnapshot

_CLOUD_CLASSES: dict[InferenceMode, type[CloudLLMClient]] = {
    InferenceMode.GEMINI: GeminiClient,
    InferenceMode.ANTHROPIC: AnthropicClient,
    InferenceMode.OPENAI: OpenAIClient,
}


class InferenceRouter:
    """Waehlt pro Auftrag den aktiven Provider und erzwingt das Privacy Gateway."""

    def __init__(
        self,
        settings: Settings,
        store: RuntimeSettingsStore,
        ollama: OllamaClient,
        *,
        cloud_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._ollama = ollama
        self._cloud_http = httpx.AsyncClient(
            transport=cloud_transport,
            timeout=httpx.Timeout(
                connect=10.0, read=settings.cloud_timeout_seconds, write=30.0, pool=10.0
            ),
        )

    @property
    def store(self) -> RuntimeSettingsStore:
        return self._store

    async def aclose(self) -> None:
        await self._cloud_http.aclose()

    def _base_url(self, mode: InferenceMode) -> str:
        return {
            InferenceMode.GEMINI: self._settings.gemini_base_url,
            InferenceMode.ANTHROPIC: self._settings.anthropic_base_url,
            InferenceMode.OPENAI: self._settings.openai_base_url,
        }[mode]

    def cloud_client(self, mode: InferenceMode, snapshot: RuntimeSnapshot | None = None) -> CloudLLMClient:
        """Roher Cloud-Client (ohne Vault) - nur fuer Verbindungstests ohne Dokumentinhalt."""
        snap = snapshot or self._store.snapshot()
        key = snap.key_for(mode.value)
        cls = _CLOUD_CLASSES[mode]
        if not key:
            raise ProviderNotConfiguredError(
                f"Inferenz-Modus '{cls.label}' ist aktiv, aber es ist kein API-Key hinterlegt."
            )
        return cls(
            api_key=key,
            model=snap.models[mode.value],
            base_url=self._base_url(mode),
            timeout_seconds=self._settings.cloud_timeout_seconds,
            client=self._cloud_http,
        )

    def acquire(self) -> StructuredLLMClient:
        """Client fuer genau einen Auftrag (Dokumentanalyse oder Copilot-Frage)."""
        snap = self._store.snapshot()
        if snap.inference_mode is InferenceMode.LOCAL:
            if snap.models["local"] == self._ollama.model:
                return self._ollama
            # Abweichendes lokales Modell: gleicher HTTP-Client, andere Konfiguration.
            return OllamaClient(
                self._settings.model_copy(update={"ollama_model": snap.models["local"]}),
                client=self._ollama._client,  # noqa: SLF001
            )
        return VaultedClient(self.cloud_client(snap.inference_mode, snap))
