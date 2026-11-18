"""In-Memory-Rate-Limiting nach dem Token-Bucket-Verfahren.

Schützt die teuren Routen (Upload, Extraktion, Copilot) vor Überlastung:
Ein lokales 14B-Modell bearbeitet nur wenige Anfragen gleichzeitig, und
Cloud-Provider rechnen pro Token ab.

Jeder Client (IP-Adresse) erhält pro Routengruppe einen eigenen Eimer mit
``capacity`` Token, der kontinuierlich mit ``capacity / 60`` Token pro Sekunde
nachgefüllt wird.  Kurze Spitzen sind damit erlaubt, Dauerlast nicht.

Grenzen der Lösung (bewusst dokumentiert):

* Der Zustand liegt im Prozessspeicher.  Bei mehreren uvicorn-Workern oder
  Replikas hat jeder Prozess eigene Eimer; für horizontale Skalierung gehört
  das Limit in Redis oder an das API-Gateway / den Reverse-Proxy.
* Hinter einem Reverse-Proxy ist die Client-IP die des Proxys, sofern uvicorn
  nicht mit ``--proxy-headers`` und ``--forwarded-allow-ips`` läuft.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request


class RateLimitExceededError(Exception):
    """Das Kontingent einer Routengruppe ist erschöpft."""

    code = "rate_limited"

    def __init__(self, group: str, retry_after: int) -> None:
        super().__init__(
            f"Zu viele Anfragen für '{group}'. Bitte in {retry_after} s erneut versuchen."
        )
        self.group = group
        self.retry_after = retry_after


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """Threadsicherer Token-Bucket je (Gruppe, Client)."""

    #: Eimer, die länger als so viele Sekunden unbenutzt sind, werden entfernt.
    _IDLE_EVICTION_SECONDS = 600

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, group: str, client: str, per_minute: int) -> None:
        """Verbraucht ein Token oder wirft ``RateLimitExceededError``."""
        if per_minute <= 0:
            return
        capacity = float(per_minute)
        refill_per_second = capacity / 60.0
        now = self._clock()

        with self._lock:
            self._sweep(now)
            bucket = self._buckets.get((group, client))
            if bucket is None:
                bucket = _Bucket(tokens=capacity, updated=now)
                self._buckets[(group, client)] = bucket

            elapsed = max(now - bucket.updated, 0.0)
            bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_per_second)
            bucket.updated = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return

            missing = 1.0 - bucket.tokens
            retry_after = max(1, math.ceil(missing / refill_per_second))
        raise RateLimitExceededError(group, retry_after)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        stale = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.updated > self._IDLE_EVICTION_SECONDS
        ]
        for key in stale:
            del self._buckets[key]


def client_key(request: Request) -> str:
    """Identifiziert den Client für das Rate-Limit (IP-Adresse)."""
    return request.client.host if request.client else "unknown"


def rate_limit(group: str, setting_name: str) -> Callable[[Request], None]:
    """FastAPI-Dependency-Fabrik: ``Depends(rate_limit("upload", "rate_limit_upload_per_minute"))``."""

    def dependency(request: Request) -> None:
        settings = request.app.state.settings
        if not settings.rate_limit_enabled:
            return
        limiter: TokenBucketLimiter = request.app.state.rate_limiter
        limiter.hit(group, client_key(request), int(getattr(settings, setting_name)))

    dependency.__name__ = f"rate_limit_{group}"
    return dependency
