"""Universeller Inference-Router mit ausfallsicherer Kaskade.

Der Router liest bei *jedem* Auftrag die aktuelle Laufzeitkonfiguration und
liefert einen ``FailoverClient`` ueber die effektive Kaskade:

1. Hauptmodell des aktiven Providers
2. Ausweichmodell desselben Anbieters (nur Cloud)
3. Ausweich-Schluessel der Reihe nach (nur Cloud; auch mehrere Keys eines Anbieters)
4. Anbieter-Fallbacks (``fallbacks``), ``local`` = Ollama

* ``local``  -> ``OllamaClient`` (kein Byte verlaesst den Rechner)
* ``gemini`` / ``anthropic`` / ``openai`` -> Cloud-Client, **immer** umhuellt vom
  ``VaultedClient``.  Alle Cloud-Stufen teilen sich *einen* ``PrivacyVault``:
  gleiche Platzhalter, ein Bericht.  Ein Cloud-Aufruf ohne Privacy Gateway ist
  im Code nicht vorgesehen.

Wiederholen vor Wechseln: Bei HTTP 408/429/5xx, Verbindungsfehler oder
Zeitueberschreitung wiederholt der Client dieselbe Stufe zunaechst mit kurzem
Backoff (Standard 2 s, dann 5 s).  Erst danach uebernimmt die naechste Stufe;
jeder Wechsel wird festgehalten und von ``services`` als ``provider_failover``
in der SHA-256-Hash-Kette des Ledgers protokolliert (maschinelles Ereignis,
keine Ed25519-Signatur - die gilt Prueferereignissen).  Abgelehnte Keys (401/403) und
Schemafehler loesen bewusst weder Wiederholung noch Wechsel aus - eine
Fehlkonfiguration soll sichtbar bleiben.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.ai_budget import CloudBudget
from app.config import Settings
from app.llm import LLMError, OllamaClient, StructuredLLMClient
from app.privacy_vault import PrivacyVault, VaultedClient
from app.providers import (
    AnthropicClient,
    CloudLLMClient,
    GeminiClient,
    OpenAIClient,
    ProviderNotConfiguredError,
)
from app.runtime_settings import ChainStage, InferenceMode, RuntimeSettingsStore, RuntimeSnapshot

logger = logging.getLogger(__name__)

#: Standard-Backoff vor dem Stufenwechsel (s) - wie in der Konfiguration ``LLM_RETRY_DELAYS``.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0)

#: Ereignis-Rueckruf fuer Live-Fortschritt (Copilot-Arbeitsschritte, Job-Phase).
EventHook = Callable[[str, dict[str, Any]], None]

_CLOUD_CLASSES: dict[InferenceMode, type[CloudLLMClient]] = {
    InferenceMode.GEMINI: GeminiClient,
    InferenceMode.ANTHROPIC: AnthropicClient,
    InferenceMode.OPENAI: OpenAIClient,
}

STAGE_LABELS = {
    "primary": "Hauptmodell",
    "ausweichmodell": "Ausweichmodell",
    "ausweich_schluessel": "Ausweich-Schluessel",
    "fallback": "Anbieter-Fallback",
}


def is_failover_error(exc: BaseException) -> bool:
    """Ueberlast, Ausfall, Zeitueberschreitung oder Budget - nie 401/403 oder Schemafehler."""
    return isinstance(exc, LLMError) and bool(getattr(exc, "failover", False))


class FailoverClient(StructuredLLMClient):
    """Probiert die Stufen der Kette der Reihe nach; einmal gewechselt, bleibt es beim Ersatz."""

    def __init__(
        self,
        clients: list[StructuredLLMClient],
        vault: PrivacyVault | None,
        *,
        stages: list[ChainStage] | None = None,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        on_event: EventHook | None = None,
    ) -> None:
        if not clients:
            raise ProviderNotConfiguredError("Keine nutzbare KI-Stufe konfiguriert.")
        self._clients = clients
        self._stages = stages or [ChainStage("primary", InferenceMode.LOCAL, client.model) for client in clients]
        self._index = 0
        self._retry_delays = retry_delays
        self.vault = vault
        self.on_event = on_event
        #: Protokoll der Wechsel (Grundlage fuer die Ledger-Eintraege).
        self.switches: list[dict[str, str]] = []
        #: Anzahl der Wiederholungen ueber alle Stufen (fuer Bericht und Tests).
        self.retries = 0

    @property
    def current(self) -> StructuredLLMClient:
        return self._clients[self._index]

    @property
    def current_stage(self) -> ChainStage:
        return self._stages[self._index]

    @property
    def provider(self) -> str:  # type: ignore[override]
        return self.current.provider

    @property
    def model(self) -> str:
        return self.current.model

    @property
    def stage_count(self) -> int:
        return len(self._clients)

    def _emit(self, kind: str, info: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(kind, info)
        except Exception:  # noqa: BLE001 - ein Anzeige-Rueckruf darf die Pruefung nie kippen
            logger.debug("Ereignis-Rückruf fehlgeschlagen", exc_info=True)

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        while True:
            attempt = 0
            while True:
                try:
                    return await self.current._post_chat(messages, json_mode=json_mode)  # noqa: SLF001
                except LLMError as exc:
                    if not is_failover_error(exc):
                        raise
                    if getattr(exc, "retry", False) and attempt < len(self._retry_delays):
                        delay = self._retry_delays[attempt]
                        attempt += 1
                        self.retries += 1
                        self._emit("retry", {
                            "attempt": attempt, "total": len(self._retry_delays), "delay": delay,
                            "provider": self.current.provider, "model": self.current.model, "reason_code": exc.code,
                        })
                        logger.info("Neuversuch %s/%s auf %s (%s)", attempt, len(self._retry_delays),
                                    self.current.model, exc.code)
                        if delay:
                            await asyncio.sleep(delay)
                        continue
                    last = exc
                    break
            if self._index + 1 >= len(self._clients):
                raise last
            failed, failed_stage = self.current, self.current_stage
            self._index += 1
            switch = {
                "from_provider": failed.provider,
                "from_model": failed.model,
                "to_provider": self.current.provider,
                "to_model": self.current.model,
                "to_stage": self.current_stage.stage,
                "from_stage": failed_stage.stage,
                "reason_code": last.code,
                "reason": str(last)[:300],
                "at": datetime.now(UTC).isoformat(),
            }
            self.switches.append(switch)
            self._emit("switch", switch)
            logger.warning(
                "Provider-Wechsel %s/%s -> %s/%s (%s)",
                switch["from_provider"], switch["from_model"], switch["to_provider"], switch["to_model"], last.code,
            )


class InferenceRouter:
    """Waehlt pro Auftrag die Kaskade und erzwingt das Privacy Gateway."""

    def __init__(
        self,
        settings: Settings,
        store: RuntimeSettingsStore,
        ollama: OllamaClient,
        *,
        cloud_transport: httpx.AsyncBaseTransport | None = None,
        budget: CloudBudget | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._ollama = ollama
        self._budget = budget
        self._cloud_http = httpx.AsyncClient(
            transport=cloud_transport,
            timeout=httpx.Timeout(
                connect=10.0, read=settings.cloud_timeout_seconds, write=30.0, pool=10.0
            ),
        )

    @property
    def store(self) -> RuntimeSettingsStore:
        return self._store

    @property
    def budget(self) -> CloudBudget | None:
        return self._budget

    async def aclose(self) -> None:
        await self._cloud_http.aclose()

    def _base_url(self, mode: InferenceMode) -> str:
        return {
            InferenceMode.GEMINI: self._settings.gemini_base_url,
            InferenceMode.ANTHROPIC: self._settings.anthropic_base_url,
            InferenceMode.OPENAI: self._settings.openai_base_url,
        }[mode]

    def cloud_client(
        self,
        mode: InferenceMode,
        snapshot: RuntimeSnapshot | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> CloudLLMClient:
        """Roher Cloud-Client (ohne Vault) - fuer die Kaskade und Verbindungstests ohne Dokumentinhalt."""
        snap = snapshot or self._store.snapshot()
        key = api_key or snap.key_for(mode.value)
        cls = _CLOUD_CLASSES[mode]
        if not key:
            raise ProviderNotConfiguredError(
                f"Inferenz-Modus '{cls.label}' ist aktiv, aber es ist kein API-Key hinterlegt."
            )
        return cls(
            api_key=key,
            model=model or snap.models[mode.value],
            base_url=self._base_url(mode),
            timeout_seconds=self._settings.cloud_timeout_seconds,
            client=self._cloud_http,
            budget=self._budget,
        )

    def _local_client(self, snap: RuntimeSnapshot) -> OllamaClient:
        if snap.models["local"] == self._ollama.model:
            return self._ollama
        # Abweichendes lokales Modell: gleicher HTTP-Client, andere Konfiguration.
        return OllamaClient(
            self._settings.model_copy(update={"ollama_model": snap.models["local"]}),
            client=self._ollama._client,  # noqa: SLF001
        )

    def acquire(self, on_event: EventHook | None = None) -> FailoverClient:
        """Client fuer genau einen Auftrag (Dokumentanalyse oder Copilot-Frage)."""
        snap = self._store.snapshot()
        vault = PrivacyVault()
        clients: list[StructuredLLMClient] = []
        stages: list[ChainStage] = []
        backups = {key.id: key for key in snap.ausweich_schluessel}
        for position, stage in enumerate(snap.effective_chain()):
            if stage.provider is InferenceMode.LOCAL:
                clients.append(self._local_client(snap))
                stages.append(stage)
                continue
            backup = backups.get(stage.backup_id or "")
            try:
                inner = self.cloud_client(
                    stage.provider, snap,
                    api_key=backup.api_key if backup else None,
                    model=stage.model,
                )
            except ProviderNotConfiguredError:
                if position == 0:
                    raise  # Der primaere Provider muss eingerichtet sein.
                logger.warning("Ausweich-Stufe %s ohne API-Key - übersprungen.", stage.provider.value)
                continue
            clients.append(VaultedClient(inner, vault))
            stages.append(stage)
        uses_cloud = any(isinstance(client, VaultedClient) for client in clients)
        return FailoverClient(
            clients,
            vault if uses_cloud else None,
            stages=stages,
            retry_delays=self._settings.retry_delays,
            on_event=on_event,
        )
