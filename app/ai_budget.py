"""Optionales Tagesbudget für Cloud-Sprachmodelle ("Bring Your Own Key").

Wer einen eigenen Cloud-Schlüssel hinterlegt, soll nicht mit einem Stapel
Belege unbemerkt eine hohe Rechnung erzeugen.  Deshalb:

* Jede Cloud-Antwort bucht ihre Tokens (aus den Nutzungsangaben des Anbieters,
  sonst geschätzt: vier Zeichen je Token).
* Vor jedem Cloud-Aufruf wird geprüft, ob das Tageslimit erreicht ist
  (``CLOUD_DAILY_TOKEN_LIMIT``; Standard ``-1`` = ohne Limit).  Ist es erreicht,
  überspringt die Kaskade alle Cloud-Stufen - lokal oder das Regelwerk
  übernehmen, die Prüfung bricht nicht ab.
* Lokale Modelle (Ollama) zählen nicht.

Gespeichert wird nur die Tagessumme je Modell (``data/ai_usage.json``), nie ein
Prompt oder eine Antwort.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.llm import LLMError

logger = logging.getLogger(__name__)


class BudgetExceededError(LLMError):
    """Tagesbudget für Cloud-Tokens aufgebraucht."""

    code = "cloud_budget_exceeded"
    hint = "Bis morgen lokal prüfen – lokale Modelle sind nicht begrenzt – oder das Tageslimit unter Einstellungen › KI-Einrichtung › Ausweich-Kaskade anheben."
    failover = True
    retry = False


def tokens_from_response(provider: str, data: dict[str, Any], prompt_chars: int = 0) -> int:
    """Verbrauchte Tokens laut Anbieterantwort; ohne Angabe grob geschätzt."""
    if provider == "gemini":
        usage = data.get("usageMetadata") or {}
        if usage.get("totalTokenCount"):
            return int(usage["totalTokenCount"])
    else:
        usage = data.get("usage") or {}
        total = usage.get("total_tokens") or (
            (usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            + (usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        )
        if total:
            return int(total)
    return int((prompt_chars + len(json.dumps(data, ensure_ascii=False))) / 4)


class CloudBudget:
    """Threadsichere Tagessumme der Cloud-Tokens."""

    def __init__(self, limit: int, path: Path | None) -> None:
        self.limit = limit
        self._path = path
        self._lock = threading.Lock()
        self._memory: dict[str, Any] = {}

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _read(self) -> dict[str, Any]:
        raw: dict[str, Any] = dict(self._memory)
        if self._path is not None:
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = dict(self._memory)
        if raw.get("date") != self._today():
            raw = {"date": self._today(), "tokens": 0, "calls": 0, "by_model": {}}
        return raw

    def status(self) -> dict[str, Any]:
        with self._lock:
            raw = self._read()
        used = int(raw.get("tokens", 0))
        return {
            "date": raw["date"],
            "tokens": used,
            "calls": int(raw.get("calls", 0)),
            "limit": self.limit,
            "enabled": self.limit >= 0,
            "remaining": None if self.limit < 0 else max(0, self.limit - used),
        }

    def check(self) -> None:
        """Vor einem Cloud-Aufruf: wirft ``BudgetExceededError``, wenn das Limit erreicht ist."""
        if self.limit < 0:
            return
        used = self.status()["tokens"]
        if used >= self.limit:
            raise BudgetExceededError(
                f"Tagesbudget für Cloud-KI erreicht ({used:,} von {self.limit:,} Tokens).".replace(",", ".")
            )

    def book(self, provider: str, model: str, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._lock:
            raw = self._read()
            raw["tokens"] = int(raw.get("tokens", 0)) + tokens
            raw["calls"] = int(raw.get("calls", 0)) + 1
            key = f"{provider}:{model}"
            raw.setdefault("by_model", {})[key] = int(raw["by_model"].get(key, 0)) + tokens
            self._memory = raw
            if self._path is None:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(raw), encoding="utf-8")
                tmp.replace(self._path)
            except OSError:
                logger.warning("Cloud-Budget konnte nicht gespeichert werden.", exc_info=True)
