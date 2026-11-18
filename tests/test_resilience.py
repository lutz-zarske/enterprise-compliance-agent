"""Ausfallsichere KI-Kaskade, Hintergrund-Jobs, Cloud-Budget und lokale KI."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai_budget import BudgetExceededError, CloudBudget
from app.config import Settings, normalize_loopback
from app.heuristics import heuristic_audit, heuristic_extraction
from app.jobs import JobManager
from app.llm import suggest_local_model
from app.runtime_settings import RuntimeSettingsStore
from tests.conftest import (
    DEFAULT_COMPLIANCE,
    DEFAULT_EXTRACTION,
    SIMPLE_INVOICE_LINES,
    FakeOllama,
    uploaded_document_id,
)

KEY_A = "AIza-primary-key-0001"
KEY_B = "AIza-backup-key-0002"


class FakeGemini:
    """Gemini-REST auf HTTP-Ebene: Status je Modell bzw. Schlüssel steuerbar."""

    def __init__(self) -> None:
        self.status_by_model: dict[str, list[int]] = {}
        self.status_by_key: dict[str, int] = {}
        self.calls: list[dict[str, Any]] = []
        self.delay = 0.0

    def _answer(self, body: dict[str, Any]) -> httpx.Response:
        system = " ".join(part["text"] for part in body.get("systemInstruction", {}).get("parts", []))
        payload = DEFAULT_COMPLIANCE if "EU AI ACT" in system.upper() else DEFAULT_EXTRACTION
        text = json.dumps(payload, ensure_ascii=False)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"totalTokenCount": 1200},
        })

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if self.delay:
            await asyncio.sleep(self.delay)
        model = request.url.path.rsplit("/", 1)[-1].split(":")[0]
        key = request.headers.get("x-goog-api-key", "")
        body = json.loads(request.content) if request.content else {}
        self.calls.append({"model": model, "key": key, "body": body})
        if key in self.status_by_key:
            return httpx.Response(self.status_by_key[key], json={"error": {"message": "nope"}})
        queue = self.status_by_model.get(model)
        if queue:
            status = queue.pop(0) if len(queue) > 1 else queue[0]
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "overloaded"}})
        return self._answer(body)


@pytest.fixture
def fake_gemini() -> FakeGemini:
    return FakeGemini()


def _gemini_client(make_full_client: Callable[..., TestClient], fake: FakeGemini, **overrides: Any) -> TestClient:
    client = make_full_client(cloud_handler=fake.handler, **overrides)
    response = client.post("/api/settings", json={
        "inference_mode": "gemini", "api_keys": {"gemini": KEY_A}, "models": {"gemini": "gemini-3.8-flash"},
    })
    assert response.status_code == 200, response.text
    return client


def _trail(client: TestClient, document_id: str) -> list[dict[str, Any]]:
    return client.get("/api/audit/trail", params={"document_id": document_id}).json()["items"]


# --- Ollama-Härtung ----------------------------------------------------------------


def test_localhost_wird_auf_ipv4_normalisiert() -> None:
    assert normalize_loopback("http://localhost:11434") == "http://127.0.0.1:11434"
    assert normalize_loopback("HTTP://LOCALHOST/") == "HTTP://127.0.0.1/"
    assert normalize_loopback("http://localhost.example:11434") == "http://localhost.example:11434"
    assert normalize_loopback("http://ollama:11434") == "http://ollama:11434"
    settings = Settings(_env_file=None, ollama_base_url="http://localhost:11434/")
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.ollama_num_ctx == 32_768


def test_vorrangliste_schlaegt_nur_vor() -> None:
    assert suggest_local_model("qwen2.5:14b-instruct", ["qwen2.5:14b-instruct"]) is None
    assert suggest_local_model("qwen2.5:14b-instruct", ["nomic-embed-text", "qwen2.5:7b-instruct"]) == "qwen2.5:7b-instruct"
    assert suggest_local_model("qwen2.5:14b-instruct", ["nomic-embed-text:latest", "llama3:8b"]) == "llama3:8b"
    assert suggest_local_model("x", []) is None


def test_health_schlaegt_installiertes_modell_vor(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.models = ["qwen2.5:7b-instruct"]
    body = client.get("/health").json()
    assert body["ollama"]["model_available"] is False
    assert body["ollama"]["suggested_model"] == "qwen2.5:7b-instruct"
    # Nur Vorschlag - das eingestellte Modell bleibt (kein stiller Wechsel).
    assert client.get("/api/settings").json()["models"]["local"] == "qwen2.5:14b-instruct"


# --- Retries, Ausweichmodell, Ausweich-Schlüssel --------------------------------------


def test_neuversuch_auf_derselben_stufe_ohne_wechsel(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    fake_gemini.status_by_model["gemini-3.8-flash"] = [503, 200]
    client = _gemini_client(make_full_client, fake_gemini)
    document_id = uploaded_document_id(client, invoice_pdf)

    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["provider"] == "gemini" and body["model"] == "gemini-3.8-flash"
    assert not body["compliance"]["failover"]
    assert [call["model"] for call in fake_gemini.calls][:2] == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert "provider_failover" not in [entry["event_type"] for entry in _trail(client, document_id)]


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_ausweichmodell_desselben_anbieters(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes, status: int
) -> None:
    fake_gemini.status_by_model["gemini-3.8-flash"] = [status]
    client = _gemini_client(make_full_client, fake_gemini)
    client.post("/api/settings", json={"ausweich_modelle": {"gemini": "gemini-3.6-flash"}})
    document_id = uploaded_document_id(client, invoice_pdf)

    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["model"] == "gemini-3.6-flash" and body["provider"] == "gemini"
    switch = body["compliance"]["failover"][0]
    assert (switch["from_model"], switch["to_model"], switch["to_stage"]) == (
        "gemini-3.8-flash", "gemini-3.6-flash", "ausweichmodell",
    )
    # Erst zweimal wiederholt (Backoff), dann gewechselt.
    assert [call["model"] for call in fake_gemini.calls][:4] == ["gemini-3.8-flash"] * 3 + ["gemini-3.6-flash"]
    events = [entry["event_type"] for entry in _trail(client, document_id)]
    assert events[:2] == ["analysis", "provider_failover"]


def test_mehrere_schluessel_desselben_anbieters_mit_vault(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    fake_gemini.status_by_key[KEY_A] = 429
    client = _gemini_client(make_full_client, fake_gemini)
    settings = client.post("/api/settings", json={
        "ausweich_schluessel": [{"id": "g2", "provider": "gemini", "api_key": KEY_B}],
    }).json()
    assert settings["ausweich_schluessel"] == [{
        "id": "g2", "provider": "gemini", "model": "gemini-3.8-flash", "has_key": True, "key_hint": "AIz...0002",
    }]
    assert KEY_B not in json.dumps(settings)
    document_id = uploaded_document_id(client, invoice_pdf)

    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["provider"] == "gemini" and body["compliance"]["privacy_gateway"]
    switch = body["compliance"]["failover"][0]
    assert switch["to_stage"] == "ausweich_schluessel"
    backup_calls = [call for call in fake_gemini.calls if call["key"] == KEY_B]
    assert backup_calls
    # Auch die Ausweich-Stufe sieht nur Platzhalter - nie die Klartext-IBAN.
    for call in backup_calls:
        assert "DE89370400440532013000" not in json.dumps(call["body"])
    entry = next(e for e in _trail(client, document_id) if e["event_type"] == "provider_failover")
    assert entry["details"]["to_stage"] == "ausweich_schluessel"
    assert client.get("/api/audit/verify").json()["valid"] is True


def test_abgelehnter_key_loest_keinen_wechsel_aus(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    fake_gemini.status_by_key[KEY_A] = 401
    client = _gemini_client(make_full_client, fake_gemini)
    client.post("/api/settings", json={
        "fallbacks": ["local"], "ausweich_modelle": {"gemini": "gemini-3.6-flash"},
        "ausweich_schluessel": [{"id": "g2", "provider": "gemini", "api_key": KEY_B}],
    })
    document_id = uploaded_document_id(client, invoice_pdf)

    response = client.post(f"/documents/{document_id}/extract?wait=true")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_auth_failed"
    assert len(fake_gemini.calls) == 1  # kein Neuversuch, kein Wechsel, kein Regelwerk
    assert client.get(f"/documents/{document_id}").json()["status"] == "failed"


def test_ausweich_schluessel_validierung(make_full_client: Callable[..., TestClient]) -> None:
    client = make_full_client()
    too_many = [{"id": f"k{i}", "provider": "gemini", "api_key": f"AIza-key-{i:08d}"} for i in range(7)]
    assert client.post("/api/settings", json={"ausweich_schluessel": too_many}).status_code == 422
    missing = client.post("/api/settings", json={"ausweich_schluessel": [{"id": "k1", "provider": "openai"}]})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "invalid_settings"
    local = client.post("/api/settings", json={"ausweich_schluessel": [{"id": "k1", "provider": "local"}]})
    assert local.status_code == 422

    client.post("/api/settings", json={"ausweich_schluessel": [{"id": "k1", "provider": "openai", "api_key": "sk-x-12345678"}]})
    # Ohne api_key bleibt der gespeicherte Schlüssel (gleiche id, gleicher Anbieter).
    kept = client.post("/api/settings", json={"ausweich_schluessel": [{"id": "k1", "provider": "openai", "model": "gpt-4o"}]})
    assert kept.json()["ausweich_schluessel"][0]["key_hint"] == "sk-...5678"


def test_ausweich_schluessel_verschluesselt_gespeichert(full_client: TestClient) -> None:
    full_client.post("/api/settings", json={"ausweich_schluessel": [{"id": "g2", "provider": "gemini", "api_key": KEY_B}]})
    engine = full_client.app.state.engine  # type: ignore[attr-defined]
    with engine.connect() as connection:
        stored = connection.exec_driver_sql("SELECT value FROM app_settings WHERE key='ausweich_schluessel'").scalar_one()
    assert KEY_B not in stored and "backup-key" not in stored


# --- Regelwerk-Fallback ------------------------------------------------------------------


def test_regelwerk_extraktion_und_einstufung() -> None:
    extraction = heuristic_extraction("\n".join(SIMPLE_INVOICE_LINES))
    assert extraction.doc_type.value == "invoice"
    assert extraction.document_number == "2024-11"
    assert str(extraction.document_date) == "2024-02-02"
    assert extraction.total_amount is not None and float(extraction.total_amount) == 119.0
    assert heuristic_audit("Rechnung ueber Bueromaterial").ai_act.overall_risk_level.value == "not_applicable"
    risky = heuristic_audit("Lizenz fuer KI-gestuetzte Vorauswahl von Bewerbungen")
    assert risky.ai_act.overall_risk_level.value == "high"
    assert risky.ai_act.systems[0].annex_iii_categories[0].value == "employment_and_worker_management"


def test_kaskade_endet_im_regelwerk_mit_protokoll(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, fake_ollama: FakeOllama,
    invoice_pdf: bytes,
) -> None:
    fake_gemini.status_by_model["gemini-3.8-flash"] = [503]
    fake_ollama.offline = True
    client = _gemini_client(make_full_client, fake_gemini)
    client.post("/api/settings", json={"fallbacks": ["local"]})
    document_id = uploaded_document_id(client, invoice_pdf)

    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["provider"] == "heuristic" and body["compliance"]["heuristic"] is True
    assert body["scorecard"]["score"] >= 0  # valides Ergebnis statt HTTP 503
    events = [entry["event_type"] for entry in _trail(client, document_id)]
    assert events[0] == "analysis" and "provider_failover" in events


# --- Cloud-Tagesbudget ---------------------------------------------------------------------


def test_cloud_budget(tmp_path: Any) -> None:
    budget = CloudBudget(1000, tmp_path / "usage.json")
    budget.check()
    budget.book("gemini", "gemini-3.8-flash", 1200)
    assert budget.status()["remaining"] == 0
    with pytest.raises(BudgetExceededError):
        budget.check()
    assert CloudBudget(1000, tmp_path / "usage.json").status()["tokens"] == 1200  # persistiert
    CloudBudget(-1, None).check()  # -1 = ohne Limit


def test_erschoepftes_budget_weicht_lokal_aus(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    client = _gemini_client(make_full_client, fake_gemini, cloud_daily_token_limit=0)
    client.post("/api/settings", json={"fallbacks": ["local"]})
    document_id = uploaded_document_id(client, invoice_pdf)
    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["provider"] == "local"
    assert body["compliance"]["failover"][0]["reason_code"] == "cloud_budget_exceeded"
    assert fake_gemini.calls == []  # kein einziger Cloud-Aufruf über dem Limit
    assert client.get("/api/settings").json()["cloud_budget"]["enabled"] is True


def test_tageslimit_in_den_einstellungen_aenderbar(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    client = _gemini_client(make_full_client, fake_gemini)
    # Ohne Server-Vorgabe frei wählbar; 0 sperrt die Cloud sofort, -1 hebt das Limit wieder auf.
    assert client.post("/api/settings", json={"cloud_daily_token_limit": 0}).json()["cloud_budget"]["max"] is None
    document_id = uploaded_document_id(client, invoice_pdf)
    client.post(f"/documents/{document_id}/extract?wait=true")
    assert fake_gemini.calls == []
    budget = client.post("/api/settings", json={"cloud_daily_token_limit": -1}).json()["cloud_budget"]
    assert budget["enabled"] is False and budget["limit"] == -1
    body = client.post(f"/documents/{document_id}/extract?wait=true").json()
    assert body["provider"] == "gemini" and len(fake_gemini.calls) >= 1

    assert client.post("/api/settings", json={"cloud_daily_token_limit": 250_000}).json()["cloud_budget"]["limit"] == 250_000
    assert client.post("/api/settings", json={"cloud_daily_token_limit": -2}).status_code == 422
    # Persistiert: Ein neuer Store auf derselben Datenbank liest den Wert wieder.
    state = client.app.state  # type: ignore[attr-defined]
    assert RuntimeSettingsStore(state.settings, state.engine).cloud_daily_token_limit == 250_000
    # Server-Vorgabe 100.000: Sie ist die Obergrenze, auch für einen höher gespeicherten Wert.
    capped = RuntimeSettingsStore(state.settings.model_copy(update={"cloud_daily_token_limit": 100_000}), state.engine)
    assert capped.cloud_daily_token_limit == 100_000 and capped.cloud_daily_token_limit_max == 100_000


def test_server_tageslimit_ist_obergrenze(make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini) -> None:
    client = _gemini_client(make_full_client, fake_gemini, cloud_daily_token_limit=300_000)
    assert client.get("/api/settings").json()["cloud_budget"]["max"] == 300_000
    for too_much in (-1, 500_000):
        response = client.post("/api/settings", json={"cloud_daily_token_limit": too_much, "pii_strictness": "strict"})
        assert response.status_code == 422 and "300.000" in response.json()["error"]["message"]
    view = client.get("/api/settings").json()
    assert view["pii_strictness"] != "strict"  # abgelehnte Anfrage ändert nichts
    assert client.post("/api/settings", json={"cloud_daily_token_limit": 250_000}).json()["cloud_budget"]["limit"] == 250_000


# --- Hintergrund-Jobs ------------------------------------------------------------------------


def _poll(client: TestClient, job_id: str, until: set[str], timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in until:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} nicht in {until}: {job}")


def test_extract_nimmt_sofort_an_und_meldet_fortschritt(client: TestClient, invoice_pdf: bytes) -> None:
    document_id = uploaded_document_id(client, invoice_pdf)
    accepted = client.post(f"/documents/{document_id}/extract")
    assert accepted.status_code == 202
    job = accepted.json()
    assert job["status"] in {"queued", "running", "done"} and job["document_id"] == document_id
    assert [phase["label"] for phase in job["phases"]] == [
        "Text-Layer & XML-Vorrang", "PII-Scanner & Privacy Vault",
        "§ 14 UStG Extraktion & Prüfung", "EU AI Act, Scorecard & Ledger",
    ]
    done = _poll(client, job["job_id"], {"done"})
    assert done["progress"] == 1.0 and done["phase"] == "ai_act"
    assert done["result"]["score"] is not None and done["result"]["provider"] == "local"
    assert client.get("/api/v1/jobs", params={"active": True}).json() == {"jobs": [], "open": 0}
    assert client.get(f"/documents/{document_id}").json()["status"] == "extracted"


def test_batch_reiht_mehrere_belege_ein(client: TestClient, invoice_pdf: bytes, simple_pdf: bytes) -> None:
    first = uploaded_document_id(client, invoice_pdf)
    second = uploaded_document_id(client, simple_pdf, "einfach.pdf")
    response = client.post("/api/v1/jobs", json={"document_ids": [first, second, "00000000-0000-4000-8000-000000000000"]})
    assert response.status_code == 202
    body = response.json()
    assert len(body["jobs"]) == 2 and body["rejected"][0]["code"] == "document_not_found"
    for job in body["jobs"]:
        assert _poll(client, job["job_id"], {"done"})["status"] == "done"


def test_job_ereignisse_tragen_einheitliche_zeitstempel(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    fake_gemini.status_by_model["gemini-3.8-flash"] = [503]
    client = _gemini_client(make_full_client, fake_gemini)
    client.post("/api/settings", json={"ausweich_modelle": {"gemini": "gemini-3.6-flash"}})
    document_id = uploaded_document_id(client, invoice_pdf)
    job = client.post(f"/documents/{document_id}/extract").json()
    done = _poll(client, job["job_id"], {"done"})
    kinds = [event["kind"] for event in done["events"]]
    assert "retry" in kinds and "switch" in kinds
    # Epoch-Sekunden wie started_at – auch beim Stufenwechsel, der fürs Ledger ISO mitbringt.
    assert all(isinstance(event["at"], float) for event in done["events"])
    switch = next(event for event in done["events"] if event["kind"] == "switch")
    assert switch["from_stage"] == "primary" and switch["to_stage"] == "ausweichmodell"


def test_abbruch_stellt_den_vorherigen_stand_her(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini, invoice_pdf: bytes
) -> None:
    fake_gemini.delay = 5.0
    client = _gemini_client(make_full_client, fake_gemini)
    document_id = uploaded_document_id(client, invoice_pdf)
    job = client.post(f"/documents/{document_id}/extract").json()
    _poll(client, job["job_id"], {"running"})
    # Ein zweiter Start für denselben Beleg liefert den laufenden Job.
    assert client.post(f"/documents/{document_id}/extract").json()["job_id"] == job["job_id"]

    client.post(f"/api/v1/jobs/{job['job_id']}/cancel")
    cancelled = _poll(client, job["job_id"], {"cancelled"})
    assert cancelled["message"] == "Abgebrochen"
    assert client.get(f"/documents/{document_id}").json()["status"] == "uploaded"
    assert client.post("/api/v1/jobs/gibt-es-nicht/cancel").status_code == 404


def test_fortschritt_kriecht_monoton_und_bleibt_unter_eins() -> None:
    async def scenario() -> list[float]:
        manager = JobManager(max_parallel=1)
        gate = asyncio.Event()

        async def runner(context: Any) -> dict[str, Any]:
            context.stage("text_check")
            context.stage("ustg_check")
            await gate.wait()
            return {"provider": "local"}

        job = manager.submit(document_id="doc-12345678", title="t", runner=runner)
        values = []
        for _ in range(5):
            await asyncio.sleep(0.02)
            values.append(manager.snapshot(job)["progress"])
        gate.set()
        await manager.wait(job)
        values.append(manager.snapshot(job)["progress"])
        return values

    values = asyncio.run(scenario())
    assert values == sorted(values) and values[-2] < 0.99 and values[-1] == 1.0
    assert values[0] >= 0.16  # Phase 3 beginnt nach Text- und PII-Phase


def test_abbruch_eines_wartenden_jobs_gibt_die_sperre_frei() -> None:
    async def scenario() -> tuple[dict[str, Any], int, int, str]:
        manager = JobManager(max_parallel=1)
        gate = asyncio.Event()

        async def runner(_context: Any) -> dict[str, Any]:
            await gate.wait()
            return {"provider": "local"}

        first = manager.submit(document_id="doc-aaaaaaaa", title="erster", runner=runner)
        # Abbruch, bevor der Event-Loop den zweiten Task auch nur einmal angefasst hat.
        second = manager.submit(document_id="doc-bbbbbbbb", title="zweiter", runner=runner)
        manager.cancel(second.job_id)
        snapshot = manager.snapshot(second)
        await asyncio.wait_for(manager.wait(second), 1.0)
        open_while_first_runs = manager.open_count
        gate.set()
        await manager.wait(first)
        return snapshot, open_while_first_runs, manager.open_count, first.status

    snapshot, open_while_first_runs, open_after, first_status = asyncio.run(scenario())
    assert snapshot["status"] == "cancelled" and snapshot["message"] == "Abgebrochen"
    assert snapshot["finished_at"] is not None
    assert open_while_first_runs == 1 and open_after == 0 and first_status == "done"


def test_ledger_zusammenfassung_widerspricht_dem_score_nicht() -> None:
    from types import SimpleNamespace

    from app.services import analysis_summary

    def tile(key: str, deduction: int) -> SimpleNamespace:
        return SimpleNamespace(key=key, title=key, deduction=deduction)

    clean = SimpleNamespace(headline="Keine Compliance-Auffälligkeiten")
    steuerfalle = SimpleNamespace(
        score=45, release_recommendation="Freigabe gesperrt — Nachforderung nötig",
        tiles=[tile("formal", 30), tile("regulatory", 0), tile("privacy", 0), tile("math", 25)],
    )
    summary = analysis_summary(steuerfalle, clean)  # type: ignore[arg-type]
    assert summary == "Freigabe gesperrt — Nachforderung nötig | Score 45: § 14 UStG −30, Finanzmathematik −25"
    assert "Keine Compliance-Auffälligkeiten" not in summary

    gueltig = SimpleNamespace(score=100, release_recommendation="Zur Auszahlung freigegeben", tiles=[tile("formal", 0)])
    assert analysis_summary(gueltig, clean) == "Zur Auszahlung freigegeben | Keine Compliance-Auffälligkeiten"  # type: ignore[arg-type]

    hochrisiko = SimpleNamespace(headline="EU AI Act: Hochrisiko")
    assert analysis_summary(steuerfalle, hochrisiko).endswith("| EU AI Act: Hochrisiko")  # type: ignore[arg-type]


# --- Lokale KI -------------------------------------------------------------------------------


def test_lokale_ki_steuerung_nur_am_server(make_full_client: Callable[..., TestClient], monkeypatch: Any) -> None:
    client = make_full_client()
    status = client.get("/api/v1/ai/local").json()
    assert {"running", "startable", "controllable", "text", "control_allowed"} <= status.keys()
    assert status["control_allowed"] is False  # Testclient ist nicht localhost
    denied = client.post("/api/v1/ai/start-ollama")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "local_only"

    from app import local_ai

    monkeypatch.setattr(local_ai, "start_ollama", lambda: {"ok": True, "message": "gestartet"})
    open_client = make_full_client(local_ai_control_local_only=False)
    assert open_client.post("/api/v1/ai/start-ollama").json() == {"ok": True, "message": "gestartet"}


def test_ueberlast_meldung_nennt_die_tatsaechliche_ursache() -> None:
    from app.providers import ProviderUnavailableError, overload_message
    from app.services import fallback_explanation

    assert "Anfragelimit oder Kontingent" in overload_message("Gemini", 429)
    assert overload_message("Gemini", 503) == "Gemini ist vorübergehend überlastet (HTTP 503)."
    assert "Störung (HTTP 500)" in overload_message("Claude", 500)
    assert "Zeitüberschreitung" in overload_message("OpenAI", 408)

    # Nur ein Key, keine Ausweich-Stufe: Ursache plus konkreter nächster Schritt.
    single = fallback_explanation(ProviderUnavailableError(overload_message("Gemini", 503)), stages=1)
    assert single.startswith("Gemini ist vorübergehend überlastet (HTTP 503).")
    assert "Einstellungen › KI-Einrichtung › Ausweich-Kaskade" in single
    # Mit Kaskade: kein Ratschlag, eine Kaskade anzulegen, sondern der Hinweis auf alle Stufen.
    chain = fallback_explanation(ProviderUnavailableError(overload_message("Claude", 529)), stages=3)
    assert chain.endswith("Auch die übrigen 2 Stufen der Ausweich-Kaskade antworteten nicht.")
    two = fallback_explanation(ProviderUnavailableError(overload_message("Gemini", 429)), stages=2)
    assert two.endswith("Auch die zweite Stufe der Ausweich-Kaskade antwortete nicht.")


def test_copilot_cancel_beendet_laufende_anfrage_und_meldet_status(
    full_client: TestClient, monkeypatch: Any
) -> None:
    """Stoppknopf: POST /api/v1/copilot/cancel/{id} bricht laufende Anfragen serverseitig ab."""
    import threading
    from app.services import COPILOT_STEPS, DocumentService

    started = threading.Event()
    original = DocumentService.copilot

    async def slow_copilot(self: Any, *args: Any, **kwargs: Any) -> dict[str, object]:
        COPILOT_STEPS.register_task(kwargs.get("progress_id"), asyncio.current_task())
        started.set()
        try:
            await asyncio.sleep(5.0)
        finally:
            COPILOT_STEPS.finish(kwargs.get("progress_id"))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(DocumentService, "copilot", slow_copilot)
    seeded = full_client.post("/api/demo/seed", params={"only": "Rechnung_Gueltig_14UStG.pdf"}).json()
    doc_id = seeded["items"][0]["id"]
    progress_id = "cancel-test-123"

    outcomes: list[Any] = []

    def run_chat() -> None:
        try:
            outcomes.append(
                full_client.post(
                    f"/documents/{doc_id}/copilot",
                    json={"question": "Wer ist der Empfänger?", "progress_id": progress_id},
                ).status_code
            )
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)

    worker = threading.Thread(target=run_chat)
    worker.start()
    assert started.wait(timeout=3.0)

    cancelled = full_client.post(f"/api/v1/copilot/cancel/{progress_id}")
    assert cancelled.status_code == 200
    assert cancelled.json() == {"cancelled": True, "progress_id": progress_id}
    worker.join(timeout=3.0)
    assert not worker.is_alive()

    status = full_client.get(f"/api/v1/copilot/progress/{progress_id}").json()
    assert status["done"] is True
    assert status["cancelled"] is True
    assert status["current"] == "Abgebrochen"


def test_gemini_verbindungstest_erkennt_503_ueberlast(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini
) -> None:
    """Ein 200 auf GET /models reicht nicht: bei 503 auf :generateContent meldet der Test Fehler."""
    fake_gemini.status_by_model["gemini-3.8-flash"] = [503]
    client = _gemini_client(make_full_client, fake_gemini)
    result = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    assert result["ok"] is False
    assert result["code"] == "provider_unavailable"
    assert "503" in result["message"]
    assert fake_gemini.calls[0]["body"]["generationConfig"]["maxOutputTokens"] == 1


def test_verbindungstest_mehrfachklick_pingt_nur_einmal(
    make_full_client: Callable[..., TestClient], fake_gemini: FakeGemini
) -> None:
    """Mehrfachklicks auf „Speichern“ verbrauchen kein Anfragelimit: derselbe Test kommt aus dem Speicher."""
    client = _gemini_client(make_full_client, fake_gemini)
    first = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    second = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    assert first["ok"] is True and "cached" not in first
    assert second["ok"] is True and second["cached"] is True
    assert len(fake_gemini.calls) == 1

    # Ein neuer Schlüssel ist eine neue Konfiguration und wird wieder echt geprüft.
    client.post("/api/settings", json={"api_keys": {"gemini": "AIza-zweiter-key-987654"}})
    third = client.post("/api/settings/test-connection", json={"provider": "gemini"}).json()
    assert "cached" not in third
    assert len(fake_gemini.calls) == 2
