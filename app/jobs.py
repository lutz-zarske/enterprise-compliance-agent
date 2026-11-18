"""Asynchrone Analyse-Jobs mit Fortschritt, Restzeit und Abbruch.

Eine Dokumentprüfung mit einem 14B-Modell dauert Minuten.  Ein einzelner
HTTP-Request, der so lange offen bleibt, scheitert an Timeouts von Browser,
Proxy oder Reverse-Proxy - und die Prüfperson sieht bis dahin nichts.

Stattdessen nimmt ``POST /api/v1/jobs`` (bzw. ``POST /documents/{id}/extract``)
den Auftrag sofort an und liefert eine ``job_id``.  Die Oberfläche fragt den
Zustand ab: Warteschlangenplatz, Fortschritt 0-1, Phase, geglättete Restzeit.
Die Jobs laufen als asyncio-Tasks im Prozess; ein Semaphor begrenzt die
gleichzeitigen Analysen (``ANALYSIS_WORKERS``, lokal sinnvoll: 1).

* Abbruch: kooperativ - der Task wird beendet, der Beleg behält sein
  vorheriges Ergebnis; ausgelöste Provider-Wechsel stehen trotzdem im Ledger.
* Hängende Jobs: ohne Fortschrittsmeldung länger als ``stall_seconds``
  meldet der Snapshot ``stalled=true`` (die Oberfläche bietet dann Abbrechen an).
* Release-Wechsel: Während ``ReleaseManager.busy`` startet kein Job; der
  Release-Assistent wartet seinerseits, bis keine Analyse mehr offen ist.
* Beendete Jobs bleiben ``JOB_RETENTION_SECONDS`` abrufbar.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Vier Phasen der Prüfung: Schlüssel, Anzeige, Anteil am Gesamtfortschritt.
PHASES: tuple[tuple[str, str, float], ...] = (
    ("text_check", "Text-Layer & XML-Vorrang", 0.06),
    ("pii_scan", "PII-Scanner & Privacy Vault", 0.10),
    ("ustg_check", "§ 14 UStG Extraktion & Prüfung", 0.44),
    ("ai_act", "EU AI Act, Scorecard & Ledger", 0.40),
)
PHASE_KEYS = tuple(key for key, _label, _weight in PHASES)
PHASE_LABELS = {key: label for key, label, _weight in PHASES}

#: Erwartete Dauer einer KI-Prüfung, bis eigene Messwerte vorliegen (s).
DEFAULT_EXPECTED_SECONDS = 45.0
#: Gewicht der jüngsten Messung in der gleitenden Erwartung.
EXPECTATION_ALPHA = 0.35
#: Glättung der angezeigten Restzeit (Anteil des neuen Werts).
ETA_ALPHA = 0.3

Runner = Callable[["JobContext"], Awaitable[dict[str, Any]]]


class JobCancelled(Exception):
    """Abbruch durch die Prüfperson."""


@dataclass(slots=True)
class Job:
    job_id: str
    kind: str
    document_id: str
    title: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    phase: str | None = None
    phase_index: int = -1
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    last_update: float = field(default_factory=time.time)
    phase_started_at: float | None = None
    eta_smoothed: float | None = None
    cancel_requested: bool = False
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[Any] | None = field(default=None, repr=False)
    done_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    expected_seconds: float = DEFAULT_EXPECTED_SECONDS
    exception: BaseException | None = field(default=None, repr=False)


class JobContext:
    """Wird an die Analyse übergeben: Phase melden, Kaskaden-Ereignisse anhängen."""

    def __init__(self, manager: JobManager, job: Job) -> None:
        self._manager = manager
        self._job = job

    @property
    def job_id(self) -> str:
        return self._job.job_id

    def stage(self, key: str) -> None:
        if self._job.cancel_requested:
            raise JobCancelled()
        job = self._job
        if key in PHASE_KEYS and PHASE_KEYS.index(key) > job.phase_index:
            job.phase_index = PHASE_KEYS.index(key)
            job.phase = key
            job.phase_started_at = time.time()
            job.message = PHASE_LABELS[key]
        job.last_update = time.time()

    def event(self, kind: str, info: dict[str, Any]) -> None:
        """Wiederholung oder Stufenwechsel der KI-Kaskade (für den Job-Monitor)."""
        job = self._job
        if kind == "retry":
            job.message = (
                f"Modell antwortet nicht – automatischer Neuversuch ({info.get('attempt')}/{info.get('total')})…"
            )
        elif kind == "switch":
            job.message = f"Wechsle auf Ausweichmodell {info.get('to_model')}…"
        # "at" einheitlich als Epoch-Sekunden wie created_at/started_at (der Stufenwechsel
        # bringt für das Ledger einen ISO-Zeitstempel mit, der hier nicht durchschlagen soll).
        details = {k: v for k, v in info.items() if k not in {"reason", "at"}}
        job.events.append({"kind": kind, **details, "at": time.time()})
        job.events = job.events[-20:]
        job.last_update = time.time()


class JobManager:
    """Warteschlange der Analyse-Jobs (ein Prozess, asyncio)."""

    def __init__(
        self,
        *,
        max_parallel: int = 1,
        retention_seconds: float = 3600.0,
        stall_seconds: float = 600.0,
        is_paused: Callable[[], bool] | None = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._max_parallel = max_parallel
        self._semaphore: asyncio.Semaphore | None = None
        self._retention = retention_seconds
        self._stall = stall_seconds
        self._is_paused = is_paused or (lambda: False)
        #: Gleitende Erwartung der Dauer je Pfad ("llm" | "structured").
        self._expected: dict[str, float] = {"llm": DEFAULT_EXPECTED_SECONDS, "structured": 2.0}

    # --- Verwaltung ----------------------------------------------------------
    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_parallel)
        return self._semaphore

    def _prune(self) -> None:
        limit = time.time() - self._retention
        for job_id in [key for key, job in self._jobs.items() if job.finished_at and job.finished_at < limit]:
            del self._jobs[job_id]

    @property
    def open_count(self) -> int:
        """Wartende und laufende Jobs (sperrt den Release-Wechsel)."""
        return sum(1 for job in self._jobs.values() if job.status in {"queued", "running"})

    def open_for(self, document_id: str) -> Job | None:
        return next(
            (job for job in self._jobs.values()
             if job.document_id == document_id and job.status in {"queued", "running"}),
            None,
        )

    def submit(self, *, document_id: str, title: str, runner: Runner, kind: str = "analysis",
               path: str = "llm") -> Job:
        """Reiht eine Analyse ein; läuft für den Beleg schon eine, kommt diese zurück."""
        self._prune()
        existing = self.open_for(document_id)
        if existing is not None:
            return existing
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, document_id=document_id, title=title[:120])
        job.expected_seconds = self._expected.get(path, DEFAULT_EXPECTED_SECONDS)
        self._jobs[job.job_id] = job
        job.task = asyncio.create_task(self._run(job, runner, path), name=f"job-{job.job_id}")
        job.task.add_done_callback(lambda _task: self._close(job, "cancelled", "Abgebrochen"))
        return job

    @staticmethod
    def _close(job: Job, status: str, message: str) -> None:
        """Schließt einen noch offenen Job ab (idempotent).

        Wird ein Task vor seinem ersten Schritt abgebrochen, läuft ``_run`` nie an -
        auch dessen ``finally`` nicht.  Ohne diesen Abschluss bliebe der Job "queued",
        ``open_count`` sperrte den Release-Wechsel und ``wait`` kehrte nie zurück.
        """
        if job.status not in {"queued", "running"}:
            return
        job.status = status
        job.message = message
        job.finished_at = job.last_update = time.time()
        job.done_event.set()

    async def _run(self, job: Job, runner: Runner, path: str) -> None:
        try:
            async with self._sem():
                while self._is_paused() and not job.cancel_requested:
                    job.message = "Wartet auf den Release-Wechsel …"
                    await asyncio.sleep(0.5)
                if job.cancel_requested:
                    raise JobCancelled()
                job.status = "running"
                job.started_at = job.last_update = time.time()
                job.message = "Analyse startet …"
                result = await runner(JobContext(self, job))
                job.result = result
                job.status = "done"
                job.message = "Fertig"
                duration = time.time() - job.started_at
                key = "structured" if result.get("provider") == "structured" else path
                previous = self._expected.get(key, DEFAULT_EXPECTED_SECONDS)
                self._expected[key] = (1 - EXPECTATION_ALPHA) * previous + EXPECTATION_ALPHA * max(duration, 0.5)
        except (JobCancelled, asyncio.CancelledError):
            job.status = "cancelled"
            job.message = "Abgebrochen"
        except Exception as exc:  # noqa: BLE001 - der Fehler gehört in den Job, nicht in den Event-Loop
            job.status = "failed"
            job.error = {
                "code": getattr(exc, "code", "internal_error"),
                "message": str(exc) if hasattr(exc, "code") else "Unerwarteter Fehler bei der Analyse.",
                "hint": getattr(exc, "hint", None),
                "status_code": getattr(exc, "status_code", None),
            }
            job.message = job.error["message"]
            if not hasattr(exc, "code"):
                logger.exception("Analyse-Job %s fehlgeschlagen", job.job_id)
            job.exception = exc
        finally:
            job.finished_at = time.time()
            job.last_update = job.finished_at
            job.done_event.set()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, *, include_finished: bool = True) -> list[Job]:
        self._prune()
        jobs = sorted(self._jobs.values(), key=lambda job: job.created_at)
        return [job for job in jobs if include_finished or job.status in {"queued", "running"}]

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status in {"queued", "running"}:
            job.cancel_requested = True
            job.message = "Wird abgebrochen …"
            if job.task is not None and not job.task.done():
                job.task.cancel()
            # Ein wartender Job hat noch nichts verändert: sofort als abgebrochen führen.
            if job.status == "queued":
                self._close(job, "cancelled", "Abgebrochen")
        return job

    async def wait(self, job: Job, timeout: float | None = None) -> Job:
        await asyncio.wait_for(job.done_event.wait(), timeout)
        return job

    async def shutdown(self) -> None:
        tasks = [job.task for job in self._jobs.values() if job.task is not None and not job.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- Anzeige -------------------------------------------------------------
    def _progress(self, job: Job, now: float) -> tuple[float, float | None]:
        """(Anzeige-Fortschritt, geglättete Restzeit in s).

        Innerhalb einer Phase kriecht der Balken asymptotisch Richtung Phasenende
        (nie darüber hinaus); erst die echte nächste Phase schiebt ihn weiter.
        """
        if job.status == "done":
            return 1.0, 0.0
        if job.status != "running" or job.started_at is None:
            return 0.0, None
        index = max(job.phase_index, 0)
        floor = sum(weight for _key, _label, weight in PHASES[:index])
        weight = PHASES[index][2]
        phase_expected = max(job.expected_seconds * weight, 0.5)
        inside = now - (job.phase_started_at or job.started_at)
        creep = 1.0 - math.exp(-inside / phase_expected)
        progress = min(0.99, floor + weight * 0.95 * creep)
        elapsed = now - job.started_at
        raw_eta = max(0.0, job.expected_seconds - elapsed)
        if elapsed > job.expected_seconds * 0.9 and progress > 0.05:
            raw_eta = max(1.0, elapsed / progress - elapsed)
        job.eta_smoothed = raw_eta if job.eta_smoothed is None else (
            (1 - ETA_ALPHA) * job.eta_smoothed + ETA_ALPHA * raw_eta
        )
        return progress, job.eta_smoothed

    def snapshot(self, job: Job) -> dict[str, Any]:
        now = time.time()
        progress, eta = self._progress(job, now)
        queued = [item for item in self.list(include_finished=False) if item.status == "queued"]
        position = queued.index(job) + 1 if job in queued else 0
        stalled = job.status == "running" and now - job.last_update > self._stall
        return {
            "job_id": job.job_id,
            "kind": job.kind,
            "document_id": job.document_id,
            "title": job.title,
            "status": job.status,
            "phase": job.phase,
            "phase_label": PHASE_LABELS.get(job.phase or "", None),
            "phase_index": job.phase_index,
            "phases": [{"key": key, "label": label} for key, label, _weight in PHASES],
            "message": job.message,
            "progress": round(progress, 4),
            "eta_seconds": round(eta, 1) if eta is not None else None,
            "queue_position": position,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "stalled": stalled,
            "cancel_requested": job.cancel_requested,
            "events": job.events[-5:],
            "result": job.result if job.status == "done" else None,
            "error": {k: v for k, v in (job.error or {}).items() if k != "status_code"} or None,
        }
