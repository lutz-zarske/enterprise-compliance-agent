"""Universeller Inference-Router: lokal (Ollama) oder Cloud (Gemini, Claude, GPT).

Der Router liest bei *jedem* Auftrag die aktuelle Laufzeitkonfiguration und
liefert einen passenden Client:

* ``local``  -> ``OllamaClient`` (kein Byte verlaesst den Rechner)
* ``gemini`` / ``anthropic`` / ``openai`` -> Cloud-Client, **immer** umhuellt
  vom ``VaultedClient``.  Ein Cloud-Aufruf ohne Privacy Gateway ist im Code
  nicht vorgesehen.

Pro Auftrag entsteht ein frischer ``PrivacyVault``; das Mapping lebt damit
nur so lange wie die Analyse eines einzelnen Dokuments.

Ausweich-Kaskade (seit v2.4): Sind Ausweich-Provider hinterlegt, liefert
``acquire`` einen ``FailoverClient``.  Faellt der aktive Provider mit HTTP 429,
5xx, Netzwerkfehler oder Zeitueberschreitung aus, uebernimmt der naechste der
Kette - jeder Wechsel wird festgehalten und von ``services`` im Ledger
protokolliert.  Alle Cloud-Stufen teilen sich einen Vault: gleiche Platzhalter,
ein Bericht.  Abgelehnte Keys (401/403) loesen bewusst keinen Wechsel aus -
eine Fehlkonfiguration soll sichtbar bleiben.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.llm import OllamaClient, OllamaTimeoutError, OllamaUnavailableError, StructuredLLMClient
from app.privacy_vault import PrivacyVault, VaultedClient
from app.providers import (
    AnthropicClient,
    CloudLLMClient,
    GeminiClient,
    OpenAIClient,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.runtime_settings import InferenceMode, RuntimeSettingsStore, RuntimeSnapshot

logger = logging.getLogger(__name__)

#: Ausfaelle, bei denen die naechste Stufe der Kette uebernimmt.
FAILOVER_ERRORS = (ProviderUnavailableError, ProviderTimeoutError, OllamaUnavailableError, OllamaTimeoutError)

_CLOUD_CLASSES: dict[InferenceMode, type[CloudLLMClient]] = {
    InferenceMode.GEMINI: GeminiClient,
    InferenceMode.ANTHROPIC: AnthropicClient,
    InferenceMode.OPENAI: OpenAIClient,
}


class FailoverClient(StructuredLLMClient):
    """Probiert die Stufen der Kette der Reihe nach; einmal gewechselt, bleibt es beim Ersatz."""

    def __init__(self, clients: list[StructuredLLMClient], vault: PrivacyVault | None) -> None:
        self._clients = clients
        self._index = 0
        self.vault = vault
        #: Protokoll der Wechsel (Grundlage fuer die Ledger-Eintraege).
        self.switches: list[dict[str, str]] = []

    @property
    def current(self) -> StructuredLLMClient:
        return self._clients[self._index]

    @property
    def provider(self) -> str:  # type: ignore[override]
        return self.current.provider

    @property
    def model(self) -> str:
        return self.current.model

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        while True:
            try:
                return await self.current._post_chat(messages, json_mode=json_mode)  # noqa: SLF001
            except FAILOVER_ERRORS as exc:
                if self._index + 1 >= len(self._clients):
                    raise
                failed = self.current
                self._index += 1
                switch = {
                    "from_provider": failed.provider,
                    "from_model": failed.model,
                    "to_provider": self.current.provider,
                    "to_model": self.current.model,
                    "reason_code": exc.code,
                    "reason": str(exc)[:300],
                    "at": datetime.now(UTC).isoformat(),
                }
                self.switches.append(switch)
                logger.warning(
                    "Provider-Wechsel %s -> %s (%s)", switch["from_provider"], switch["to_provider"], exc.code
                )


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

    def _local_client(self, snap: RuntimeSnapshot) -> OllamaClient:
        if snap.models["local"] == self._ollama.model:
            return self._ollama
        # Abweichendes lokales Modell: gleicher HTTP-Client, andere Konfiguration.
        return OllamaClient(
            self._settings.model_copy(update={"ollama_model": snap.models["local"]}),
            client=self._ollama._client,  # noqa: SLF001
        )

    def acquire(self) -> StructuredLLMClient:
        """Client fuer genau einen Auftrag (Dokumentanalyse oder Copilot-Frage)."""
        snap = self._store.snapshot()
        if not snap.fallbacks:
            if snap.inference_mode is InferenceMode.LOCAL:
                return self._local_client(snap)
            return VaultedClient(self.cloud_client(snap.inference_mode, snap))

        vault = PrivacyVault()
        clients: list[StructuredLLMClient] = []
        for position, mode in enumerate(snap.chain):
            if mode is InferenceMode.LOCAL:
                clients.append(self._local_client(snap))
                continue
            try:
                clients.append(VaultedClient(self.cloud_client(mode, snap), vault))
            except ProviderNotConfiguredError:
                if position == 0:
                    raise  # Der primaere Provider muss eingerichtet sein.
                logger.warning("Ausweich-Provider %s ohne API-Key - Stufe uebersprungen.", mode.value)
        uses_cloud = any(isinstance(client, VaultedClient) for client in clients)
        return FailoverClient(clients, vault if uses_cloud else None)
