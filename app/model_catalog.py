"""Modell-Kataloge der Provider und Upgrade-Erkennung.

Liest die verfügbaren Modelle über die jeweilige API und schlägt ein
neueres Modell *derselben Klasse* vor (Sonnet -> neueres Sonnet, Flash ->
neueres Flash).  Es wird nie still gewechselt: Ein Vorschlag erscheint als
Banner, übernommen wird er erst per Klick - der Wechsel landet dann als
``model_change`` im Ledger (GoBD-Reproduzierbarkeit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Modellklassen, innerhalb derer ein Upgrade vorgeschlagen wird.
TIERS = ("pro", "flash", "lite", "opus", "sonnet", "haiku", "mini", "nano")
#: Spezialmodelle, die für die Dokumentprüfung nicht in Frage kommen.
NOISE = (
    "audio", "realtime", "tts", "transcribe", "image", "imagen", "embedding", "search", "moderation",
    "whisper", "dall-e", "codex", "computer-use", "preview", "exp", "instruct", "learnlm", "gemma",
    "aqa", "veo", "live", "native", "tuning", "babbage", "davinci",
    "argon", "carbon", "lyria", "music", "deep-research",
)


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    created: float | None = None


def _tokens(model_id: str) -> list[str]:
    return re.split(r"[-_.:/]", model_id.lower())


def family(model_id: str) -> str:
    """Modellklasse aus den Klassenwörtern, z. B. ``gemini-2.5-flash-lite`` -> ``flash+lite``."""
    return "+".join(sorted({token for token in _tokens(model_id) if token in TIERS}))


def is_candidate(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(word in lowered for word in NOISE)


def _version(model_id: str) -> tuple[float, ...]:
    return tuple(float(part) for part in re.findall(r"\d+(?:\.\d+)?", model_id.split("-20")[0])[:3])


def _rank(info: ModelInfo) -> tuple[float, tuple[float, ...]]:
    return (info.created or 0.0, _version(info.id))


def parse_catalog(provider: str, payload: dict[str, Any]) -> list[ModelInfo]:
    """Antwort der Modell-Liste je Provider -> sortierte Liste (neueste zuerst)."""
    models: list[ModelInfo] = []
    if provider == "gemini":
        for entry in payload.get("models", []):
            if "generateContent" not in (entry.get("supportedGenerationMethods") or []):
                continue
            models.append(ModelInfo(str(entry.get("name", "")).removeprefix("models/")))
    elif provider == "anthropic":
        from datetime import datetime

        for entry in payload.get("data", []):
            created = entry.get("created_at")
            stamp = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() if created else None
            models.append(ModelInfo(str(entry.get("id", "")), stamp))
    elif provider == "openai":
        for entry in payload.get("data", []):
            model_id = str(entry.get("id", ""))
            if model_id.startswith("gpt-") or re.match(r"^o\d", model_id):
                models.append(ModelInfo(model_id, float(entry.get("created") or 0) or None))
    models = [model for model in models if model.id and is_candidate(model.id)]
    return sorted(models, key=_rank, reverse=True)


def suggest_upgrade(current: str, models: list[ModelInfo]) -> str | None:
    """Neuestes Modell derselben Klasse, falls es neuer ist als ``current``."""
    same = [model for model in models if family(model.id) == family(current)]
    if not same:
        return None
    newest = max(same, key=_rank)
    if newest.id == current:
        return None
    known = next((model for model in models if model.id == current), None)
    if known is None or _rank(newest) > _rank(known):
        return newest.id
    return None
