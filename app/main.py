"""FastAPI-Anwendung des Enterprise Compliance Agent.

Die Endpunkte bleiben bewusst duenn: Validierung, Autorisierung und
Fehlerabbildung liegen hier, die gesamte Fachlogik in ``app.services``.
Jeder Fehler verlässt die Anwendung im einheitlichen Format
``{"error": {"code", "message", "hint"}}`` - maschinenlesbar und mit
konkretem Handlungshinweis.  Analysen laufen als Hintergrund-Jobs
(``app.jobs``); kein Request wartet minutenlang auf ein Sprachmodell.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
import uuid
from pathlib import Path as FsPath
from functools import partial
from urllib.parse import quote

import anyio.to_thread
import httpx
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from typing import Literal

from fastapi import Depends, FastAPI, File, Path, Query, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import local_ai
from app.ai_budget import CloudBudget
from app.audit_ledger import NO_DOCUMENT_HASH, SYSTEM_DOCUMENT_ID, AuditEventType, AuditLedger
from app.config import APP_TITLE, APP_VERSION, BASE_DIR, Settings, get_settings
from app.db import DocumentRecord, build_repository, utcnow
from app.docx_export import render_docx
from app.gobd_export import build_gobd_package
from app.jobs import Job, JobContext, JobManager
from app.procedural_doc import build_procedural_doc, procedural_ui
from app.procedural_doc import render_html as render_procedural_html
from app.procedural_doc import render_markdown as render_procedural_markdown
from app.inference import InferenceRouter
from app.llm import PROMPT_HASH, LLMError, OllamaClient, OllamaUnavailableError, suggest_local_model
from app.providers import (
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.reporting import REPORT_CSP, build_report, export_stem, render_html, render_markdown, report_title
from app.runtime_settings import (
    CLOUD_PROVIDERS,
    SUGGESTED_MODELS,
    InferenceMode,
    RuntimeSettingsStore,
    RuntimeSnapshot,
    SettingsError,
    describe_model_change,
)
from app.model_catalog import parse_catalog, suggest_upgrade
from app.redact import RULESET_VERSION as DLP_RULESET
from app.redact import redact as redact_text_dlp
from app.release import ReleaseError, ReleaseManager
from app.logging_config import configure_logging, normalize_request_id, request_id_var
from app.rate_limit import RateLimitExceededError, TokenBucketLimiter, rate_limit
from app.pdf_reader import PdfReadError
from app.signing import SystemSigner
from app.schemas import (
    ComponentHealth,
    ConnectionTestRequest,
    CopilotRequest,
    CopilotResponse,
    OverrideRequest,
    DatabaseHealth,
    DocumentDetail,
    DocumentListResponse,
    DocumentStatus,
    ErrorResponse,
    ExtractionResponse,
    HealthResponse,
    JobSubmitRequest,
    OllamaHealth,
    PinRequest,
    ArchiveRequest,
    RedactRequest,
    ReleaseApplyRequest,
    RedactResponse,
    SettingsUpdate,
    SignOffRequest,
    UploadResponse,
    VatVerification,
    VatVerifyRequest,
)
from app.vies import ViesClient
from app.services import (
    COPILOT_STEPS,
    PROGRESS,
    DocumentNotAnalyzedError,
    DocumentService,
    ExtractionOutcome,
    ReleaseUpdateRunningError,
    ServiceError,
    UploadTooLargeError,
    UploadValidationError,
    parse_compliance,
    parse_einvoice,
    parse_extraction,
    parse_scorecard,
    to_detail,
    uses_structured_path,
)

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("app.access")

API_KEY_HEADER = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

#: Grenze fuer den gepufferten Upload-Lesevorgang.
_CHUNK_SIZE = 1024 * 1024
#: So lange gilt ein Cloud-Verbindungstest als aktuell (Schutz vor Mehrfachklicks).
CONNECTION_TEST_TTL_SECONDS = 15.0

DESCRIPTION = """\
Institutionelles Backend zur automatisierten Prüfung von Geschäftsdokumenten.

**Funktionsumfang**

* **Extraktion** von Rechnungen und Verträgen inkl. aller Pflichtangaben nach
  § 14 Abs. 4 UStG (Steuernummer/USt-IdNr., Leistungszeitpunkt, Netto, Steuersatz).
* **Deterministische Compliance-Scorecard (0-100)** mit vier Kacheln: formelle
  Gültigkeit (§ 14 UStG, EN 16931), EU AI Act, DSGVO, Finanzmathematik (MOD-97, MwSt.).
* **EU-AI-Act-Klassifizierung** nach VO (EU) 2024/1689 mit Anhang-III-Eskalation.
* **DSGVO-Audit** mit Art.-9/10-Erkennung und drei Maskierungsstufen.
* **Hash-verkettetes Prüfprotokoll** (EU AI Act Art. 12, GoBD) und
  **Human-Oversight-Siegel** (Art. 14) mit druckfertigem Prüfzertifikat.
* **E-Rechnung (EN 16931)**: ZUGFeRD/Factur-X-Anhänge und reine XRechnung (CII/UBL)
  werden deterministisch gelesen; bei hybriden Rechnungen ist der XML-Teil maßgeblich.
* **Prüfdatenpaket (ZIP)** mit Originalbeleg, XML, Ledger-Auszug, Zertifikat und
  Ed25519-signiertem Manifest.
* **Multi-Provider-Inferenz mit Ausweich-Kaskade**: lokal (Ollama) oder Gemini / Claude / GPT;
  Wiederholung mit Backoff, Ausweichmodell, Ausweich-Schluessel, lokales Modell und zuletzt das
  deterministische Regelwerk. Cloud-Aufrufe ausschließlich über das Privacy Gateway.
* **Hintergrund-Jobs**: Analysen laufen asynchron mit Phase, Fortschritt, Restzeit und Abbruch
  (`/api/v1/jobs`); `POST /documents/{id}/extract?wait=true` wartet für Skripte auf das Ergebnis.

**Authentifizierung**: Ist `API_KEY` gesetzt, verlangen alle Endpunkte außer
`/health` den Header `X-API-Key`. Ohne gesetzten Wert ist die Prüfung deaktiviert -
dann kann jeder im Netz auch die Einstellungen ändern; produktiv immer setzen.
"""

TAGS_METADATA = [
    {"name": "System", "description": "Betriebszustand von Datenbank, Ollama und Modell."},
    {"name": "Dokumente", "description": "Upload, Extraktion, Compliance-Audit und Übersicht."},
    {"name": "Jobs", "description": "Asynchrone Analysen: Warteschlange, Fortschritt, Restzeit, Abbruch."},
    {"name": "Lokale KI", "description": "Ollama erkennen, starten und stoppen (nur direkt am Server)."},
    {"name": "Audit-Ledger", "description": "Hash-verkettetes Prüfprotokoll (EU AI Act Art. 12, GoBD)."},
    {"name": "Human Oversight", "description": "Prüfbericht und Siegel durch eine Prüfperson (Art. 14)."},
    {"name": "Compliance Copilot", "description": "Dokumentbezogene Fragen an das aktive Modell."},
    {"name": "Einstellungen", "description": "Inferenz-Provider, API-Keys (verschlüsselt), PII-Strenge."},
    {"name": "USt-IdNr.", "description": "Live-Prüfung über VIES der Europäischen Kommission (ohne API-Key)."},
    {"name": "Dashboard", "description": "Kennzahlen und Demo-Daten."},
]


# ---------------------------------------------------------------------------
# Lebenszyklus
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Baut Datenbank, Repository und Ollama-Client einmalig auf."""
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, json_logs=settings.log_json)

    engine, repository = build_repository(settings)
    ollama_transport = getattr(app.state, "ollama_transport", None)
    llm = OllamaClient(
        settings,
        client=httpx.AsyncClient(transport=ollama_transport) if ollama_transport else None,
    )
    signer = SystemSigner(settings.data_dir / ".signing.key")
    ledger = AuditLedger(engine, signer=signer)
    runtime = RuntimeSettingsStore(settings, engine)
    budget = CloudBudget(runtime.cloud_daily_token_limit, settings.data_dir / "ai_usage.json")
    router = InferenceRouter(
        settings, runtime, llm, cloud_transport=getattr(app.state, "cloud_transport", None), budget=budget
    )
    vies = ViesClient(settings, transport=getattr(app.state, "vies_transport", None))
    release = ReleaseManager(
        FsPath(settings.release_repo_dir) if settings.release_repo_dir else BASE_DIR, APP_VERSION
    )

    app.state.engine = engine
    app.state.repository = repository
    app.state.llm = llm
    app.state.ledger = ledger
    app.state.runtime = runtime
    app.state.router = router
    app.state.budget = budget
    app.state.signer = signer
    app.state.vies = vies
    app.state.release = release
    app.state.jobs = JobManager(
        max_parallel=settings.analysis_workers,
        retention_seconds=settings.job_retention_seconds,
        stall_seconds=max(settings.ollama_timeout_seconds, settings.cloud_timeout_seconds) + 60,
        is_paused=lambda: release.busy,
    )
    app.state.service = DocumentService(
        settings, repository, router, ledger=ledger, runtime=runtime, progress=PROGRESS
    )

    logger.info(
        "%s v%s gestartet | DB=%s | Modell=%s | Auth=%s",
        APP_TITLE,
        APP_VERSION,
        engine.dialect.name,
        settings.ollama_model,
        "aktiv" if settings.auth_enabled else "deaktiviert",
    )
    try:
        yield
    finally:
        await app.state.jobs.shutdown()
        await router.aclose()
        await llm.aclose()
        await vies.aclose()
        engine.dispose()
        logger.info("Anwendung heruntergefahren.")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application Factory - erlaubt Tests mit eigener Konfiguration."""
    resolved = settings or get_settings()

    application = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        contact={"name": "Compliance Engineering"},
        license_info={"name": "MIT"},
        responses={
            500: {"model": ErrorResponse, "description": "Unerwarteter Serverfehler"},
        },
    )
    application.state.settings = resolved
    application.state.rate_limiter = TokenBucketLimiter()

    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list if resolved.cors_origin_list else ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    _register_middleware(application)
    _register_exception_handlers(application)
    _register_routes(application)
    return application


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_service(request: Request) -> DocumentService:
    return request.app.state.service


def get_llm(request: Request) -> OllamaClient:
    return request.app.state.llm


def get_runtime(request: Request) -> RuntimeSettingsStore:
    return request.app.state.runtime


class ApiKeyError(Exception):
    """Fehlender oder falscher API-Key."""


class LocalOnlyError(ServiceError):
    """Aktion nur direkt am Server erlaubt (Prozesse starten, Releases einspielen)."""

    code = "local_only"
    status_code = 403
    hint = "Direkt am Server (http://127.0.0.1) ausführen."


class JobNotFoundError(ServiceError):
    code = "job_not_found"
    status_code = 404
    hint = "Beendete Jobs bleiben JOB_RETENTION_SECONDS abrufbar; die Liste liefert GET /api/v1/jobs."


class JobCancelledError(ServiceError):
    code = "job_cancelled"
    status_code = 409
    hint = "Die Analyse wurde abgebrochen; der Beleg behält sein vorheriges Ergebnis."


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_local_request(request: Request) -> bool:
    return (request.client.host if request.client else "") in _LOCAL_HOSTS


def _analysis_summary(outcome: ExtractionOutcome) -> dict[str, object]:
    scorecard = outcome.scorecard
    return {
        "document_id": outcome.record.id,
        "score": scorecard.score if scorecard else None,
        "band": scorecard.band.value if scorecard else None,
        "release_recommendation": scorecard.release_recommendation if scorecard else None,
        "release_blocked": scorecard.release_blocked if scorecard else None,
        "provider": outcome.provider,
        "model": outcome.compliance.model,
        "heuristic": outcome.compliance.heuristic,
        "failover": outcome.compliance.failover or [],
        "duration_ms": outcome.duration_ms,
        "audit_entry_id": outcome.audit_entry_id,
    }


def submit_analysis(jobs: JobManager, service: DocumentService, record: DocumentRecord) -> Job:
    """Reiht die Prüfung eines Belegs ein (läuft für ihn schon eine, kommt diese zurück)."""

    async def runner(context: JobContext) -> dict[str, object]:
        current = await service.require_document(record.id)
        outcome = await service.extract_and_audit(current, on_stage=context.stage, on_event=context.event)
        return _analysis_summary(outcome)

    path = "structured" if uses_structured_path(parse_einvoice(record)) else "llm"
    return jobs.submit(document_id=record.id, title=record.original_filename, runner=runner, path=path)


async def require_api_key(
    request: Request,
    api_key: str | None = Depends(_api_key_scheme),
) -> None:
    """Prüft den API-Key, sofern in der Konfiguration einer hinterlegt ist."""
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    # Konstantzeit-Vergleich: verhindert Timing-Angriffe auf den Schluessel.
    if api_key and secrets.compare_digest(api_key.encode(), settings.api_key.encode()):
        return
    raise ApiKeyError()


# ---------------------------------------------------------------------------
# Middleware und Fehlerbehandlung
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int, code: str, message: str, hint: str | None = None
) -> JSONResponse:
    payload = ErrorResponse.model_validate(
        {"error": {"code": code, "message": message, "hint": hint}}
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _register_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def add_request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Vergibt eine Request-ID, misst die Dauer und schreibt eine Accesslog-Zeile.

        Eine vom Client gelieferte ``X-Request-ID`` wird nur übernommen, wenn
        sie dem erlaubten Zeichensatz entspricht (Schutz vor Log-Injection).
        Geloggt werden Methode, Pfad (enthält nur UUIDs), Status und Dauer -
        niemals Query-Strings, Header oder Bodies.
        """
        request_id = normalize_request_id(request.headers.get("X-Request-ID")) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
            return response
        finally:
            access_logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                status_code,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "client_ip": request.client.host if request.client else None,
                },
            )
            request_id_var.reset(token)


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(ApiKeyError)
    async def _handle_api_key(_request: Request, _exc: ApiKeyError) -> JSONResponse:
        response = _error_response(
            status.HTTP_401_UNAUTHORIZED,
            "unauthorized",
            f"Fehlender oder ungültiger API-Key im Header '{API_KEY_HEADER}'.",
            "Den in der .env hinterlegten Wert von API_KEY als Header senden.",
        )
        response.headers["WWW-Authenticate"] = API_KEY_HEADER
        return response

    @application.exception_handler(RateLimitExceededError)
    async def _handle_rate_limit(_request: Request, exc: RateLimitExceededError) -> JSONResponse:
        response = _error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            exc.code,
            str(exc),
            "Das Kontingent schützt die Inferenz-Schnittstelle vor Überlastung.",
        )
        response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @application.exception_handler(ServiceError)
    async def _handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, str(exc), exc.hint)

    @application.exception_handler(SettingsError)
    async def _handle_settings_error(_request: Request, exc: SettingsError) -> JSONResponse:
        return _error_response(422, "invalid_settings", str(exc), "Eingaben im Einstellungsdialog prüfen.")

    @application.exception_handler(PdfReadError)
    async def _handle_pdf_error(_request: Request, exc: PdfReadError) -> JSONResponse:
        return _error_response(
            422, exc.code, str(exc), exc.hint  # Unprocessable Content
        )

    @application.exception_handler(LLMError)
    async def _handle_llm_error(_request: Request, exc: LLMError) -> JSONResponse:
        # 400 bei fehlender Konfiguration, 503/504 bei Dienststoerung,
        # 502 bei unbrauchbarer Antwort oder abgelehntem Key.
        if isinstance(exc, ProviderNotConfiguredError):
            code = status.HTTP_400_BAD_REQUEST
        elif isinstance(exc, (OllamaUnavailableError, ProviderUnavailableError)):
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif isinstance(exc, ProviderTimeoutError):
            code = status.HTTP_504_GATEWAY_TIMEOUT
        else:
            code = status.HTTP_502_BAD_GATEWAY
        logger.warning("Inferenzfehler (%s): %s", exc.code, exc)
        return _error_response(code, exc.code, str(exc), exc.hint)

    @application.exception_handler(RequestValidationError)
    async def _handle_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = " -> ".join(str(part) for part in first.get("loc", []))
        return _error_response(
            422,  # Unprocessable Content
            "validation_error",
            f"Ungültige Anfrage: {first.get('msg', 'Validierung fehlgeschlagen')} ({location}).",
            "Parameterformate mit der OpenAPI-Spezifikation unter /docs abgleichen.",
        )

    @application.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 413: "file_too_large"}
        return _error_response(
            exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail)
        )

    @application.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unbehandelter Fehler: %s", exc)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Unerwarteter Serverfehler.",
            "Details stehen im Serverprotokoll.",
        )


# ---------------------------------------------------------------------------
# Endpunkte
# ---------------------------------------------------------------------------


async def _read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Liest den Upload gepuffert und bricht bei Überschreitung früh ab."""
    buffer = bytearray()
    while chunk := await upload.read(_CHUNK_SIZE):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise UploadTooLargeError(
                f"Die Datei überschreitet das Limit von {max_bytes / 1_048_576:.1f} MB."
            )
    return bytes(buffer)


def _settings_view(request: Request) -> dict[str, object]:
    """Laufzeit-Konfiguration plus Betriebswerte (Regelwerk-Fallback, Budget, DLP) - Keys nur maskiert."""
    settings: Settings = request.app.state.settings
    runtime: RuntimeSettingsStore = request.app.state.runtime
    budget: CloudBudget | None = getattr(request.app.state, "budget", None)
    terms = [term for term in settings.dlp_terms.split(",") if term.strip()]
    return {
        **runtime.public_view(),
        "heuristic_fallback": settings.heuristic_fallback,
        "retry_delays": list(settings.retry_delays),
        "cloud_budget": {**budget.status(), "max": runtime.cloud_daily_token_limit_max} if budget else None,
        "dlp": {"ruleset_version": DLP_RULESET, "configured_terms": len(terms), "endpoint": "/api/v1/redact"},
    }


def _export_name(prefix: str, original_filename: str, extension: str) -> str:
    """Download-Name: Prefix_Beleg_JJJJ-MM-TT.ext (Exportdatum, UTC) - eindeutig je Beleg und Tag."""
    return f"{prefix}_{export_stem(original_filename)}_{utcnow().date().isoformat()}.{extension}"


def _attachment_header(filename: str, disposition: Literal["attachment", "inline"] = "attachment") -> str:
    """Content-Disposition mit ASCII-Fallback und RFC-5987-Dateinamen (Umlaute)."""
    fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


async def _procedural_doc(
    request: Request,
    record: object,
    *,
    entries: list | None = None,
    verification: object | None = None,
    lang: str = "de",
) -> dict[str, object]:
    """Baut die Verfahrensdokumentation aus Settings, Laufzeitstand, Ledger und Schluessel."""
    ledger: AuditLedger = request.app.state.ledger
    if entries is None:
        entries = await ledger.list(document_id=record.id, limit=1000)  # type: ignore[attr-defined]
    if verification is None:
        verification = await ledger.verify_chain()
    signer: SystemSigner = request.app.state.signer
    return build_procedural_doc(
        settings=request.app.state.settings,
        runtime=getattr(request.app.state, "runtime", None),
        record=record,  # type: ignore[arg-type]
        entries=entries,
        verification=verification,  # type: ignore[arg-type]
        signing_key=await anyio.to_thread.run_sync(signer.public_info),
        lang=lang,
    )


def _register_routes(application: FastAPI) -> None:
    # Verbindungstest: je (Anbieter, Modell, Schlüssel) kurz merken und nacheinander ausführen -
    # Mehrfachklicks verbrauchen so kein Anfragelimit beim Anbieter.
    connection_tests: dict[tuple[str, str, str], tuple[float, dict[str, object]]] = {}
    connection_test_lock = asyncio.Lock()
    error_responses: dict[int | str, dict[str, object]] = {
        401: {"model": ErrorResponse, "description": "API-Key fehlt oder ist ungültig"},
        404: {"model": ErrorResponse, "description": "Dokument nicht gefunden"},
    }

    # --- GET /health -------------------------------------------------------
    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["System"],
        summary="Betriebszustand von Datenbank, Ollama und Modell",
    )
    async def health(
        request: Request,
        settings: Settings = Depends(get_app_settings),
        llm: OllamaClient = Depends(get_llm),
    ) -> HealthResponse:
        """Prüft alle externen Abhängigkeiten und meldet sie einzeln.

        Der Endpunkt antwortet immer mit HTTP 200; der Gesamtstatus im Body ist
        ``degraded``, sobald eine Komponente ausfällt. Monitoring-Systeme
        können dadurch zwischen "Anwendung tot" und "Abhängigkeit gestört"
        unterscheiden.
        """
        repository = request.app.state.repository

        # --- Datenbank ---
        started = time.perf_counter()
        try:
            ping = await repository.ping()
            database = DatabaseHealth(
                status="ok",
                dialect=ping["dialect"],
                documents=ping["documents"],
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:  # noqa: BLE001 - Health darf nie selbst scheitern
            logger.warning("Datenbank-Health fehlgeschlagen: %s", exc)
            database = DatabaseHealth(status="unavailable", detail=str(exc)[:300])

        # --- Ollama (eingestelltes lokales Modell der Laufzeit-Konfiguration) ---
        runtime: RuntimeSettingsStore = request.app.state.runtime
        snap = runtime.snapshot()
        local_model = snap.models["local"]
        started = time.perf_counter()
        try:
            models = await llm.list_models()
            wanted = {local_model, f"{local_model}:latest", local_model.removesuffix(":latest")}
            available = any(name in wanted for name in models)
            ollama = OllamaHealth(
                status="ok" if available else "degraded",
                detail=None if available else f"Modell '{local_model}' ist nicht installiert.",
                base_url=settings.ollama_base_url,
                model=local_model,
                model_available=available,
                available_models=sorted(models),
                suggested_model=None if available else suggest_local_model(local_model, models),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except LLMError as exc:
            ollama = OllamaHealth(
                status="unavailable",
                detail=str(exc)[:300],
                base_url=settings.ollama_base_url,
                model=local_model,
            )
        is_cloud = snap.inference_mode in CLOUD_PROVIDERS
        inference = {
            "mode": snap.inference_mode.value,
            "model": snap.active_model,
            "is_cloud": is_cloud,
            "privacy_gateway_active": is_cloud,
            "configured": (not is_cloud) or bool(snap.key_for(snap.inference_mode.value)),
            "uses_local": any(stage.provider is InferenceMode.LOCAL for stage in snap.effective_chain()),
            "chain_length": len(snap.effective_chain()),
            "heuristic_fallback": settings.heuristic_fallback,
            "open_jobs": request.app.state.jobs.open_count,
        }
        components: list[ComponentHealth] = [database, ollama]
        if is_cloud:
            # Im Cloud-Modus ist Ollama optional; massgeblich ist der hinterlegte Key.
            healthy = database.status == "ok" and bool(inference["configured"])
        else:
            healthy = all(item.status == "ok" for item in components)
        overall = "ok" if healthy else "degraded"

        return HealthResponse(
            status=overall,
            version=APP_VERSION,
            environment=settings.app_env,
            auth_enabled=settings.auth_enabled,
            timestamp=utcnow(),
            database=database,
            ollama=ollama,
            inference=inference,
        )

    # --- POST /documents/upload -------------------------------------------
    @application.post(
        "/documents/upload",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["Dokumente"],
        summary="PDF oder XML (E-Rechnung) hochladen, validieren und Text extrahieren",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("upload", "rate_limit_upload_per_minute")),
        ],
        responses={
            **error_responses,
            413: {"model": ErrorResponse, "description": "Datei zu groß"},
            429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"},
            415: {"model": ErrorResponse, "description": "Weder PDF noch XML"},
            422: {"model": ErrorResponse, "description": "PDF ohne Textlayer/beschädigt oder XML keine EN-16931-Rechnung"},
        },
    )
    async def upload_document(
        file: UploadFile = File(..., description="PDF oder XRechnung/ZUGFeRD-XML (multipart/form-data)."),
        service: DocumentService = Depends(get_service),
        settings: Settings = Depends(get_app_settings),
    ) -> UploadResponse:
        """Nimmt ein PDF oder eine XML-E-Rechnung entgegen, prüft sie und legt sie samt Text ab.

        PDF: Dateiendung, Content-Type, Größe, PDF-Signatur und Textlayer; ein
        eingebetteter ZUGFeRD-/Factur-X-/XRechnung-Datensatz wird gelesen und mit
        dem Bildteil abgeglichen. XML: EN-16931-Rechnung in CII- oder UBL-Syntax,
        geparst ohne DTD und Entitäten. Erst danach wird gespeichert. Die Analyse
        startet separat über ``POST /documents/{id}/extract``.
        """
        data = await _read_upload(file, settings.max_upload_bytes)
        record, duplicate_of = await service.ingest(
            filename=file.filename or "",
            content_type=file.content_type,
            data=data,
        )
        return UploadResponse(
            id=record.id,
            filename=record.original_filename,
            status=DocumentStatus(record.status),
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            page_count=record.page_count or 0,
            char_count=record.char_count or 0,
            duplicate_of=duplicate_of,
            created_at=record.created_at,
        )

    # --- POST /documents/{id}/extract --------------------------------------
    @application.post(
        "/documents/{document_id}/extract",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=None,
        tags=["Dokumente"],
        summary="Prüfung starten (Hintergrund-Job; mit ?wait=true blockierend für Skripte)",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("extract", "rate_limit_extract_per_minute")),
        ],
        responses={
            **error_responses,
            200: {"model": ExtractionResponse, "description": "Ergebnis (nur mit wait=true)"},
            202: {"description": "Job angenommen - Zustand über GET /api/v1/jobs/{job_id}"},
            409: {"model": ErrorResponse, "description": "Release-Wechsel läuft oder Analyse abgebrochen"},
            422: {"model": ErrorResponse, "description": "Kein Text zum Dokument vorhanden"},
            429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"},
            502: {"model": ErrorResponse, "description": "Modellantwort unbrauchbar"},
            503: {"model": ErrorResponse, "description": "Keine KI-Stufe erreichbar und Regelwerk-Fallback aus"},
        },
    )
    async def extract_document(
        request: Request,
        document_id: str = Path(..., description="UUID des Dokuments."),
        wait: bool = Query(False, description="true = auf das Ergebnis warten (Skripte, CI); Standard: sofort 202."),
        service: DocumentService = Depends(get_service),
    ) -> JSONResponse:
        """Nimmt die Prüfung sofort als Hintergrund-Job an (HTTP 202 mit ``job_id``).

        Ablauf in vier Phasen: Text-Layer & XML-Vorrang -> PII-Scanner & Privacy Vault ->
        Paragraf-14-Extraktion & Prüfung -> EU AI Act, Scorecard & Ledger.  Danach laufen
        deterministische Kontrollen (IBAN-Prüfsumme, Regex-PII-Scan als Zweitmeinung,
        Maskierung, Anhang-III-Eskalation).  Fällt die ganze KI-Kaskade aus, schließt das
        Regelwerk die Prüfung gekennzeichnet ab.  Ein erneuter Aufruf überschreibt das
        vorherige Ergebnis; läuft für den Beleg bereits ein Job, kommt dieser zurück.
        """
        if request.app.state.release.busy:
            raise ReleaseUpdateRunningError("Ein Release-Wechsel läuft gerade - keine neue Analyse.")
        record = await service.require_document(document_id)
        jobs: JobManager = request.app.state.jobs
        job = submit_analysis(jobs, service, record)
        if not wait:
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=jobs.snapshot(job))
        await jobs.wait(job)
        if job.status == "cancelled":
            raise JobCancelledError("Die Analyse wurde abgebrochen.")
        if job.status != "done":
            if job.exception is not None:
                raise job.exception
            raise ServiceError((job.error or {}).get("message", "Analyse fehlgeschlagen."))
        updated = await service.require_document(document_id)
        compliance = parse_compliance(updated)
        result = job.result or {}
        response = ExtractionResponse(
            id=updated.id,
            status=DocumentStatus(updated.status),
            model=compliance.model if compliance else (updated.model or ""),
            extraction=parse_extraction(updated),  # type: ignore[arg-type]
            compliance=compliance,  # type: ignore[arg-type]
            duration_ms=int(result.get("duration_ms") or 0),  # type: ignore[call-overload]
            scorecard=parse_scorecard(updated),
            provider=updated.provider or "local",
            audit_entry_id=result.get("audit_entry_id"),  # type: ignore[arg-type]
        )
        return JSONResponse(status_code=200, content=response.model_dump(mode="json"))

    # --- Jobs ----------------------------------------------------------------
    @application.post(
        "/api/v1/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Jobs"],
        summary="Einen oder mehrere Belege zur Prüfung einreihen (Batch)",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("extract", "rate_limit_extract_per_minute")),
        ],
    )
    async def submit_jobs(
        request: Request, body: JobSubmitRequest, service: DocumentService = Depends(get_service)
    ) -> dict[str, object]:
        """Jeder Beleg wird einzeln eingereiht; unbekannte IDs erscheinen unter ``rejected``."""
        if request.app.state.release.busy:
            raise ReleaseUpdateRunningError("Ein Release-Wechsel läuft gerade - keine neue Analyse.")
        jobs: JobManager = request.app.state.jobs
        accepted: list[dict[str, object]] = []
        rejected: list[dict[str, str]] = []
        for document_id in dict.fromkeys(body.document_ids):
            try:
                record = await service.require_document(document_id)
            except ServiceError as exc:
                rejected.append({"document_id": document_id, "code": exc.code, "message": str(exc)})
                continue
            accepted.append(jobs.snapshot(submit_analysis(jobs, service, record)))
        return {"jobs": accepted, "rejected": rejected}

    @application.get(
        "/api/v1/jobs",
        tags=["Jobs"],
        summary="Warteschlange: laufende, wartende und kürzlich beendete Jobs",
        dependencies=[Depends(require_api_key)],
    )
    async def list_jobs(
        request: Request, active: bool = Query(False, description="true = nur wartende und laufende Jobs.")
    ) -> dict[str, object]:
        jobs: JobManager = request.app.state.jobs
        items = [jobs.snapshot(job) for job in jobs.list(include_finished=not active)]
        return {"jobs": items, "open": jobs.open_count}

    @application.get(
        "/api/v1/jobs/{job_id}",
        tags=["Jobs"],
        summary="Zustand eines Jobs (Phase, Fortschritt 0-1, Restzeit, Ergebnis)",
        dependencies=[Depends(require_api_key)],
    )
    async def get_job(request: Request, job_id: str = Path(..., max_length=64)) -> dict[str, object]:
        jobs: JobManager = request.app.state.jobs
        job = jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Kein Job mit der ID '{job_id}'.")
        return jobs.snapshot(job)

    @application.post(
        "/api/v1/jobs/{job_id}/cancel",
        tags=["Jobs"],
        summary="Job abbrechen (der Beleg behält sein vorheriges Ergebnis)",
        dependencies=[Depends(require_api_key)],
    )
    async def cancel_job(request: Request, job_id: str = Path(..., max_length=64)) -> dict[str, object]:
        jobs: JobManager = request.app.state.jobs
        job = jobs.cancel(job_id)
        if job is None:
            raise JobNotFoundError(f"Kein Job mit der ID '{job_id}'.")
        return jobs.snapshot(job)

    # --- GET /documents ----------------------------------------------------
    @application.get(
        "/documents",
        response_model=DocumentListResponse,
        tags=["Dokumente"],
        summary="Tabellarische Übersicht aller Dokumente",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def list_documents(
        limit: int = Query(50, ge=1, le=200, description="Maximale Anzahl Zeilen."),
        offset: int = Query(0, ge=0, description="Versatz für die Blätterung."),
        document_status: DocumentStatus | None = Query(
            None, alias="status", description="Optionaler Statusfilter."
        ),
        service: DocumentService = Depends(get_service),
    ) -> DocumentListResponse:
        """Liefert die neuesten Dokumente zuerst, inklusive Compliance-Kennzahlen."""
        items, total = await service.list_documents(
            limit=limit, offset=offset, status=document_status
        )
        return DocumentListResponse(items=items, total=total, limit=limit, offset=offset)

    # --- GET /documents/{id} ----------------------------------------------
    @application.get(
        "/documents/{document_id}",
        response_model=DocumentDetail,
        tags=["Dokumente"],
        summary="Detailansicht inklusive Compliance-Audit",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def get_document(
        document_id: str = Path(..., description="UUID des Dokuments."),
        service: DocumentService = Depends(get_service),
    ) -> DocumentDetail:
        """Metadaten, Extraktion, Audit, Scorecard, Siegel und geschwärzte Textansicht."""
        record = await service.require_document(document_id)
        return to_detail(record, pii_level=service.pii_level)

    # --- Batch-Upload -------------------------------------------------------
    @application.post(
        "/documents/upload-batch",
        tags=["Dokumente"],
        summary="Mehrere PDFs bzw. XML-E-Rechnungen in einem multipart-Request hochladen",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("upload", "rate_limit_upload_per_minute")),
        ],
        responses={**error_responses, 429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"}},
    )
    async def upload_batch(
        files: list[UploadFile] = File(..., description="Eine oder mehrere PDF- bzw. XML-Dateien."),
        service: DocumentService = Depends(get_service),
        settings: Settings = Depends(get_app_settings),
    ) -> dict[str, object]:
        """Jede Datei wird einzeln validiert; eine fehlerhafte Datei bricht den Batch nicht ab."""
        if len(files) > settings.max_batch_files:
            raise UploadValidationError(
                f"Maximal {settings.max_batch_files} Dateien pro Batch erlaubt ({len(files)} gesendet)."
            )
        items: list[dict[str, object]] = []
        for upload in files:
            name = upload.filename or ""
            try:
                data = await _read_upload(upload, settings.max_upload_bytes)
                record, duplicate_of = await service.ingest(
                    filename=name, content_type=upload.content_type, data=data
                )
                items.append(
                    {
                        "filename": record.original_filename,
                        "ok": True,
                        "id": record.id,
                        "sha256": record.sha256,
                        "page_count": record.page_count,
                        "duplicate_of": duplicate_of,
                        "einvoice_profile": (record.einvoice or {}).get("profile"),
                    }
                )
            except (ServiceError, PdfReadError) as exc:
                items.append({"filename": name, "ok": False, "error": {"code": exc.code, "message": str(exc)}})
        succeeded = sum(1 for item in items if item["ok"])
        return {"items": items, "succeeded": succeeded, "failed": len(items) - succeeded}

    # --- Fortschritt, Pins, Siegel, Bericht, Copilot -----------------------
    @application.get(
        "/documents/{document_id}/progress",
        tags=["Dokumente"],
        summary="Aktuelle Pipeline-Stufe (Live-Audit-Stepper)",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def document_progress(
        document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> dict[str, object]:
        record = await service.require_document(document_id)
        return service.progress_of(record)

    @application.put(
        "/documents/{document_id}/pin",
        response_model=DocumentDetail,
        tags=["Dokumente"],
        summary="Dokument oben anpinnen bzw. lösen",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def pin_document(
        body: PinRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        record = await service.require_document(document_id)
        updated = await service.set_pinned(record, body.pinned)
        return to_detail(updated, pii_level=service.pii_level)

    @application.put(
        "/documents/{document_id}/archive",
        response_model=DocumentDetail,
        tags=["Dokumente"],
        summary="Beleg archivieren bzw. aus dem Archiv holen (nur ausblenden, nie löschen)",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def archive_document(
        body: ArchiveRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        record = await service.require_document(document_id)
        updated = await service.set_archived(record, body.archived)
        return to_detail(updated, pii_level=service.pii_level)

    @application.post(
        "/documents/{document_id}/sign-off",
        response_model=DocumentDetail,
        tags=["Human Oversight"],
        summary="Prüfergebnis durch eine Prüfperson versiegeln (EU AI Act Art. 14)",
        dependencies=[Depends(require_api_key)],
        responses={**error_responses, 409: {"model": ErrorResponse, "description": "Noch nicht analysiert"}},
    )
    async def sign_off_document(
        body: SignOffRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        """Schreibt einen ``sign_off``-Eintrag in den Hash-Ledger und versiegelt das Dokument.

        Eine erneute Analyse hebt das Siegel auf (der Prüfgegenstand hat sich
        geändert); die Historie bleibt im Ledger vollständig erhalten.
        """
        record = await service.require_document(document_id)
        updated = await service.sign_off(record, body)
        return to_detail(updated, pii_level=service.pii_level)

    @application.get(
        "/api/documents/{document_id}/export/procedural-doc",
        tags=["Human Oversight"],
        summary="GoBD-Verfahrensdokumentation (Entwurf) mit Prüfpfad des Belegs (html | markdown | docx)",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def export_procedural_doc(
        request: Request,
        document_id: str = Path(...),
        doc_format: Literal["html", "markdown", "docx"] = Query("html", alias="format"),
        lang: Literal["de", "en", "es"] = Query("de"),
        service: DocumentService = Depends(get_service),
    ) -> Response:
        """Vier Säulen nach GoBD Rz. 153 aus dem aktuellen Systemzustand, plus Anhang zum Beleg.

        Organisatorische Angaben, die das System nicht kennt, sind als
        ``[vom Unternehmen zu ergänzen]`` markiert. Aufbewahrung: 10 Jahre
        (§ 147 Abs. 1 Nr. 1 AO). ``format=docx`` liefert eine Word-Datei zum Ergänzen
        der Platzhalter und Fortschreiben.
        """
        record = await service.require_document(document_id)
        doc = await _procedural_doc(request, record, lang=lang)
        prefix = {"de": "Verfahrensdokumentation", "en": "ProceduralDocumentation", "es": "DocumentacionProcedimientos"}[lang]
        if doc_format == "markdown":
            return PlainTextResponse(
                render_procedural_markdown(doc, lang=lang),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": _attachment_header(_export_name(prefix, record.original_filename, "md"))},
            )
        if doc_format == "docx":
            data = await anyio.to_thread.run_sync(partial(render_docx, doc, procedural_ui(lang)))
            return Response(
                data,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": _attachment_header(_export_name(prefix, record.original_filename, "docx"))},
            )
        return HTMLResponse(
            render_procedural_html(doc, lang=lang),
            headers={
                "Content-Security-Policy": REPORT_CSP,
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": _attachment_header(_export_name(prefix, record.original_filename, "html"), "inline"),
            },
        )

    @application.post(
        "/api/documents/{document_id}/override",
        response_model=DocumentDetail,
        tags=["Human Oversight"],
        summary="KI-Einstufung durch eine Prüfperson übersteuern (Art. 14 Abs. 4 lit. d AI Act)",
        dependencies=[Depends(require_api_key)],
        responses={
            **error_responses,
            409: {"model": ErrorResponse, "description": "Noch nicht analysiert"},
            422: {"model": ErrorResponse, "description": "Keine Änderung oder Begründung zu kurz"},
        },
    )
    async def override_document(
        body: OverrideRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        """Setzt die EU-AI-Act-Risikostufe neu und rechnet den Score deterministisch neu.

        Schreibt einen Ed25519-signierten ``human_override``-Eintrag in den Ledger
        (Person, Begründung, Rechtsnorm, Score vorher/nachher). Ein bestehendes
        Siegel wird aufgehoben, weil sich der Prüfgegenstand geändert hat.
        """
        record = await service.require_document(document_id)
        updated = await service.override(record, body)
        return to_detail(updated, pii_level=service.pii_level)

    @application.post(
        "/api/vat/verify",
        response_model=VatVerification,
        tags=["USt-IdNr."],
        summary="USt-IdNr. live bei VIES (Europäische Kommission) prüfen",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("vies", "rate_limit_vies_per_minute")),
        ],
        responses={
            401: error_responses[401],
            422: {"model": ErrorResponse, "description": "Ländercode oder Nummer nicht abfragbar"},
            503: {"model": ErrorResponse, "description": "VIES oder Mitgliedstaat nicht erreichbar"},
        },
    )
    async def verify_vat(body: VatVerifyRequest, request: Request) -> VatVerification:
        """Fragt VIES mit kurzem Timeout ab und gibt Gültigkeit, Name und Behördenzeitstempel zurück.

        Übertragen werden nur Ländercode und Nummer. Das Ergebnis ist eine
        Momentaufnahme: nicht gespeichert, ohne Einfluss auf den Score. Für
        deutsche Nummern liefert VIES keinen Namen; die qualifizierte
        Bestätigung nach § 18e UStG erteilt das BZSt.
        """
        vies: ViesClient = request.app.state.vies
        return await vies.verify(body.country_code, body.vat_number)

    @application.get(
        "/documents/{document_id}/report",
        tags=["Human Oversight"],
        summary="Revisionssicheres Audit-Zertifikat (html | markdown | json)",
        dependencies=[Depends(require_api_key)],
        responses={**error_responses, 409: {"model": ErrorResponse, "description": "Noch nicht analysiert"}},
    )
    async def document_report(
        request: Request,
        document_id: str = Path(...),
        report_format: Literal["html", "markdown", "json"] = Query("html", alias="format"),
        lang: Literal["de", "en", "es"] = Query("de"),
        service: DocumentService = Depends(get_service),
    ) -> Response:
        record = await service.require_document(document_id)
        if not record.scorecard:
            raise DocumentNotAnalyzedError(f"Dokument {document_id} ist noch nicht analysiert.")
        ledger: AuditLedger = request.app.state.ledger
        report = build_report(
            record, await ledger.list(document_id=document_id, limit=50), await ledger.verify_chain(), lang=lang
        )
        title = report_title(report, lang)
        if report_format == "json":
            return JSONResponse(
                report,
                headers={"Content-Disposition": _attachment_header(f"{title}.json", "inline")},
            )
        if report_format == "markdown":
            return PlainTextResponse(
                render_markdown(report, lang=lang),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": _attachment_header(f"{title}.md", "inline")},
            )
        return HTMLResponse(
            render_html(report, lang=lang),
            headers={"Content-Security-Policy": REPORT_CSP, "X-Content-Type-Options": "nosniff"},
        )

    @application.get(
        "/api/documents/{document_id}/export/gobd",
        tags=["Human Oversight"],
        summary="Prüfdatenpaket als ZIP (Original, XML, Ledger, Zertifikat, signiertes Manifest)",
        dependencies=[Depends(require_api_key)],
        response_class=Response,
        responses={
            **error_responses,
            200: {"content": {"application/zip": {}}, "description": "ZIP-Archiv"},
            409: {"model": ErrorResponse, "description": "Noch nicht analysiert"},
            410: {"model": ErrorResponse, "description": "Originaldatei fehlt oder weicht ab"},
        },
    )
    async def export_gobd(
        request: Request,
        document_id: str = Path(...),
        lang: Literal["de", "en", "es"] = Query("de"),
        service: DocumentService = Depends(get_service),
    ) -> Response:
        """GoBD-orientiertes Einzelbeleg-Paket (Rz. 58 ff.: Nachvollziehbarkeit, Unveränderbarkeit).

        Das Manifest trägt SHA-256 je Datei und eine Ed25519-Signatur dieser
        Installation; den Fingerabdruck liefert ``GET /api/audit/signing-key``.
        Kein Datenträger nach dem Beschreibungsstandard (index.xml) und kein
        qualifiziertes Siegel nach eIDAS.
        """
        record = await service.require_document(document_id)
        if not record.scorecard:
            raise DocumentNotAnalyzedError(f"Dokument {document_id} ist noch nicht analysiert.")
        ledger: AuditLedger = request.app.state.ledger
        entries = await ledger.list(document_id=document_id, limit=1000)
        verification = await ledger.verify_chain()
        original = await service.read_original(record)
        certificate = render_html(build_report(record, entries[:50], verification, lang=lang), lang=lang)
        procedural = render_procedural_html(
            await _procedural_doc(request, record, entries=entries, verification=verification, lang=lang), lang=lang
        )
        data, _ = await anyio.to_thread.run_sync(
            partial(
                build_gobd_package,
                record,
                original=original,
                embedded_xml=service.embedded_xml(record, original),
                entries=entries,
                verification=verification,
                certificate_html=certificate,
                signer=request.app.state.signer,
                procedural_doc_html=procedural,
            )
        )
        pkg_prefix = {"de": "Pruefdatenpaket", "en": "AuditDataPackage", "es": "PaqueteAuditoria"}[lang]
        logger.info("Prüfdatenpaket für %s erzeugt (%s Bytes).", record.id, len(data))
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": _attachment_header(_export_name(pkg_prefix, record.original_filename, "zip")),
                "X-Content-SHA256": hashlib.sha256(data).hexdigest(),
            },
        )

    @application.post(
        "/documents/{document_id}/copilot",
        response_model=CopilotResponse,
        tags=["Compliance Copilot"],
        summary="Frage zum Dokument an den Compliance Copilot",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("copilot", "rate_limit_copilot_per_minute")),
        ],
        responses=error_responses,
    )
    async def copilot(
        body: CopilotRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> CopilotResponse:
        """Antwort des aktiven Modells, geerdet auf nummeriertem Dokumenttext und Prüfergebnis.

        Mit ``progress_id`` liefert ``GET /api/v1/copilot/progress/{id}`` die Arbeitsschritte live
        (inklusive Neuversuch und Wechsel auf ein Ausweichmodell).
        """
        record = await service.require_document(document_id)
        result = await service.copilot(
            record,
            body.question,
            [turn.model_dump() for turn in body.history],
            thinking=body.thinking,
            lang=body.lang,
            progress_id=body.progress_id,
        )
        return CopilotResponse.model_validate(result)

    @application.get(
        "/api/v1/copilot/progress/{progress_id}",
        tags=["Compliance Copilot"],
        summary="Live-Arbeitsschritte einer laufenden Copilot-Anfrage",
        dependencies=[Depends(require_api_key)],
    )
    async def copilot_progress(progress_id: str = Path(..., pattern=r"^[A-Za-z0-9_-]{6,64}$")) -> dict[str, object]:
        return COPILOT_STEPS.get(progress_id)

    @application.post(
        "/api/v1/copilot/cancel/{progress_id}",
        tags=["Compliance Copilot"],
        summary="Laufende Copilot-Anfrage serverseitig abbrechen",
        dependencies=[Depends(require_api_key)],
    )
    async def cancel_copilot_progress(
        progress_id: str = Path(..., pattern=r"^[A-Za-z0-9_-]{6,64}$"),
    ) -> dict[str, object]:
        """Bricht eine laufende Copilot-Anfrage serverseitig ab."""
        return {"cancelled": COPILOT_STEPS.cancel(progress_id), "progress_id": progress_id}

    # --- Lokale KI ---------------------------------------------------------------
    @application.get(
        "/api/v1/ai/local",
        tags=["Lokale KI"],
        summary="Lokale KI erkennen (Ollama, LM Studio): installiert, läuft, steuerbar?",
        dependencies=[Depends(require_api_key)],
    )
    async def local_ai_status(request: Request) -> dict[str, object]:
        settings_: Settings = request.app.state.settings
        result = await anyio.to_thread.run_sync(local_ai.detect, settings_.ollama_base_url)
        allowed = _is_local_request(request) or not settings_.local_ai_control_local_only
        return {**result, "control_allowed": allowed and bool(result["controllable"])}

    @application.post(
        "/api/v1/ai/start-ollama",
        tags=["Lokale KI"],
        summary="Ollama im Hintergrund starten (Flash Attention, 8-Bit-KV-Cache)",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
        responses={403: {"model": ErrorResponse, "description": "Nur direkt am Server"}},
    )
    async def local_ai_start(request: Request) -> dict[str, object]:
        settings_: Settings = request.app.state.settings
        if settings_.local_ai_control_local_only and not _is_local_request(request):
            raise LocalOnlyError("Lokale KI lässt sich nur direkt am Server starten.")
        result = await anyio.to_thread.run_sync(local_ai.start_ollama)
        logger.info("Lokale KI starten: %s", result.get("message"))
        return result

    @application.post(
        "/api/v1/ai/stop-local",
        tags=["Lokale KI"],
        summary="Ollama beenden und den Grafikspeicher freigeben",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
        responses={403: {"model": ErrorResponse, "description": "Nur direkt am Server"}},
    )
    async def local_ai_stop(request: Request) -> dict[str, object]:
        settings_: Settings = request.app.state.settings
        if settings_.local_ai_control_local_only and not _is_local_request(request):
            raise LocalOnlyError("Lokale KI lässt sich nur direkt am Server stoppen.")
        if request.app.state.jobs.open_count:
            raise ServiceError("Während einer laufenden Analyse wird die lokale KI nicht gestoppt.")
        result = await anyio.to_thread.run_sync(local_ai.stop_ollama)
        logger.info("Lokale KI stoppen: %s", result.get("message"))
        return result

    # --- Dashboard & Demo ---------------------------------------------------
    @application.get(
        "/api/dashboard/kpis",
        tags=["Dashboard"],
        summary="Aggregierte Portfolio-Kennzahlen",
        dependencies=[Depends(require_api_key)],
    )
    async def dashboard_kpis(service: DocumentService = Depends(get_service)) -> dict[str, object]:
        return await service.kpis()

    @application.post(
        "/api/demo/seed",
        tags=["Dashboard"],
        summary="Vier Musterbelege (oder einen davon) ohne Sprachmodell anlegen und prüfen",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("upload", "rate_limit_upload_per_minute")),
        ],
    )
    async def demo_seed(
        only: str | None = Query(
            default=None, max_length=120, description="Nur diesen Musterbeleg laden (Dateiname), sonst alle vier."
        ),
        service: DocumentService = Depends(get_service),
    ) -> dict[str, object]:
        """Idempotent: bereits vorhandene Referenzdokumente (gleiche SHA-256) werden wiederverwendet."""
        items = await service.seed_demo(only)
        return {"items": items, "created": sum(1 for item in items if item["created"])}

    # --- Einstellungen ------------------------------------------------------
    @application.get(
        "/api/settings",
        tags=["Einstellungen"],
        summary="Aktive Inferenz- und Compliance-Konfiguration (Keys maskiert)",
        dependencies=[Depends(require_api_key)],
    )
    async def get_runtime_settings(request: Request) -> dict[str, object]:
        return _settings_view(request)

    @application.post(
        "/api/settings",
        tags=["Einstellungen"],
        summary="Inferenz-Modus, Modelle, API-Keys und PII-Strenge ändern",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
    )
    async def update_runtime_settings(
        request: Request, body: SettingsUpdate, runtime: RuntimeSettingsStore = Depends(get_runtime)
    ) -> dict[str, object]:
        """API-Keys werden Fernet-verschlüsselt gespeichert und nur maskiert zurückgegeben.

        Ändert sich der Provider, ein Modell der Kette oder die Ausweich-Reihenfolge, entsteht ein
        signierter ``model_change``-Eintrag im Ledger (GoBD-Reproduzierbarkeit: kein stiller Modellwechsel).
        """
        before = runtime.snapshot().fingerprint()
        after = (await runtime.update(body.model_dump(exclude_none=True))).fingerprint()
        budget: CloudBudget | None = getattr(request.app.state, "budget", None)
        if budget is not None:
            budget.limit = runtime.cloud_daily_token_limit
        logger.info(
            "Einstellungen geändert: %s",
            ", ".join(sorted(body.model_dump(exclude_none=True).keys())),
        )
        if after != before:
            ledger: AuditLedger = request.app.state.ledger
            await ledger.append(
                event_type=AuditEventType.MODEL_CHANGE,
                document_id=SYSTEM_DOCUMENT_ID,
                sha256_hash=NO_DOCUMENT_HASH,
                model_name=after["model"],
                prompt_hash=PROMPT_HASH,
                result_summary=describe_model_change(before, after),
                compliance_score=None,
                risk_tier="none",
                details={"before": before, "after": after},
            )
        return _settings_view(request)

    @application.get(
        "/api/settings/models",
        tags=["Einstellungen"],
        summary="Verfügbare Modelle eines Providers, neueste zuerst, mit Upgrade-Vorschlag",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
    )
    async def list_provider_models(
        request: Request,
        provider: Literal["local", "gemini", "anthropic", "openai"] = Query(...),
        runtime: RuntimeSettingsStore = Depends(get_runtime),
        llm: OllamaClient = Depends(get_llm),
    ) -> dict[str, object]:
        """Liest die Modell-Liste über die API des Providers (ohne Dokumentinhalt).

        Ohne Key oder bei einem Fehler kommt die eingebaute Vorschlagsliste zurück (``source=suggested``).
        Ein Upgrade wird nur vorgeschlagen, nie automatisch übernommen.
        """
        snap = runtime.snapshot()
        current = snap.models[provider]
        fallback = {"provider": provider, "current": current, "models": SUGGESTED_MODELS[provider],
                    "upgrade": None, "source": "suggested"}
        try:
            if provider == "local":
                names = await llm.list_models()
                return {**fallback, "models": sorted(names), "source": "api"}
            if not snap.key_for(provider):
                return {**fallback, "message": "Kein API-Key hinterlegt - Vorschlagsliste."}
            router: InferenceRouter = request.app.state.router
            client = router.cloud_client(InferenceMode(provider), snap)
            catalog = parse_catalog(provider, await client.fetch_catalog())
        except LLMError as exc:
            return {**fallback, "message": str(exc)}
        return {**fallback, "models": [model.id for model in catalog] or SUGGESTED_MODELS[provider],
                "upgrade": suggest_upgrade(current, catalog), "source": "api"}

    @application.post(
        "/api/settings/test-connection",
        tags=["Einstellungen"],
        summary="Verbindung zum gewählten Provider prüfen (ohne Dokumentinhalt)",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
    )
    async def test_connection(
        request: Request,
        body: ConnectionTestRequest,
        runtime: RuntimeSettingsStore = Depends(get_runtime),
        llm: OllamaClient = Depends(get_llm),
    ) -> dict[str, object]:
        snap = runtime.snapshot()
        mode = InferenceMode(body.provider) if body.provider else snap.inference_mode
        model = snap.models[mode.value]
        try:
            if mode is InferenceMode.LOCAL:
                models = await llm.list_models()
                wanted = {model, f"{model}:latest", model.removesuffix(":latest")}
                if not any(name in wanted for name in models):
                    suggestion = suggest_local_model(model, models)
                    return {"ok": False, "provider": mode.value, "model": model, "suggested_model": suggestion,
                            "message": f"Ollama erreichbar, Modell '{model}' aber nicht installiert."
                                       + (f" Installiert ist {suggestion} – per Klick übernehmen." if suggestion else "")}
                message = f"Ollama erreichbar, Modell {model} installiert."
            else:
                return await _cloud_connection_test(request, mode, model, snap)
        except LLMError as exc:
            return {"ok": False, "provider": mode.value, "model": model, "message": str(exc), "code": exc.code}
        return {"ok": True, "provider": mode.value, "model": model, "message": message}

    async def _cloud_connection_test(
        request: Request, mode: InferenceMode, model: str, snap: RuntimeSnapshot
    ) -> dict[str, object]:
        """Cloud-Ping höchstens einmal je CONNECTION_TEST_TTL_SECONDS und Konfiguration."""
        fingerprint = hashlib.sha256((snap.key_for(mode.value) or "").encode()).hexdigest()[:16]
        cache_key = (mode.value, model, fingerprint)
        async with connection_test_lock:
            cached = connection_tests.get(cache_key)
            if cached and time.monotonic() - cached[0] < CONNECTION_TEST_TTL_SECONDS:
                return {**cached[1], "cached": True}
            try:
                router: InferenceRouter = request.app.state.router
                message = await router.cloud_client(mode, snap).test_connection()
                result: dict[str, object] = {"ok": True, "provider": mode.value, "model": model, "message": message}
            except LLMError as exc:
                result = {"ok": False, "provider": mode.value, "model": model, "message": str(exc), "code": exc.code}
            connection_tests.clear()
            connection_tests[cache_key] = (time.monotonic(), result)
            return result

    # --- Release-Assistent -------------------------------------------------
    @application.get(
        "/api/system/release",
        tags=["System"],
        summary="Neue Version prüfen (git fetch --tags, SemVer, Tag-Signatur, Änderungen)",
        dependencies=[Depends(require_api_key)],
    )
    async def release_status(
        request: Request, fetch: bool = Query(default=True, description="false = ohne Netzwerk, nur lokale Tags.")
    ) -> dict[str, object]:
        manager: ReleaseManager = request.app.state.release
        try:
            return await anyio.to_thread.run_sync(partial(manager.status, fetch=fetch))
        except ReleaseError as exc:
            return {"git": False, "current_version": APP_VERSION, "update_available": False, "message": str(exc)}

    @application.post(
        "/api/system/release/apply",
        tags=["System"],
        summary="Release einspielen: nach Bestätigung des Commit-Hashes, nur Fast-Forward, mit DB-Sicherung",
        dependencies=[Depends(require_api_key)],
        responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def release_apply(request: Request, body: ReleaseApplyRequest) -> JSONResponse:
        settings_: Settings = request.app.state.settings
        manager: ReleaseManager = request.app.state.release
        host = request.client.host if request.client else ""
        try:
            if settings_.release_update_local_only and host not in {"127.0.0.1", "::1", "localhost"}:
                raise ReleaseError("local_only", "Updates nur direkt am Server (localhost) einspielen.", 403)
            release = await anyio.to_thread.run_sync(
                partial(manager.preflight, body.tag, body.commit,
                        # Ein laufender Job zaehlt in beiden Zaehlern - Maximum statt Summe.
                        active_analyses=max(PROGRESS.active, request.app.state.jobs.open_count))
            )
            database_file = (
                FsPath(settings_.resolved_database_url.removeprefix("sqlite:///")) if settings_.is_sqlite else None
            )
            backup = await anyio.to_thread.run_sync(
                manager.backup_database, database_file, settings_.data_dir / "backups", body.tag
            )
            previous = await anyio.to_thread.run_sync(manager.fast_forward, body.tag)
        except ReleaseError as exc:
            return JSONResponse(
                status_code=exc.status_code, content={"error": {"code": exc.code, "message": str(exc), "hint": None}}
            )
        ledger: AuditLedger = request.app.state.ledger
        await ledger.append(
            event_type=AuditEventType.RELEASE_UPDATE,
            document_id=SYSTEM_DOCUMENT_ID,
            sha256_hash=release["commit"],
            model_name=f"release {release['tag']}",
            prompt_hash=PROMPT_HASH,
            result_summary=f"Release-Wechsel v{APP_VERSION} -> {release['tag']} durch {body.admin_name}",
            compliance_score=None,
            risk_tier="none",
            details={
                "admin_name": body.admin_name, "from_version": APP_VERSION, "from_commit": previous,
                "to_tag": release["tag"], "to_commit": release["commit"], "tag_signature": release["signature"],
                "database_backup": backup.name if backup else None,
            },
        )
        auto_restarting = manager.schedule_restart_if_managed()
        return JSONResponse({
            "ok": True, "from_commit": previous, "to_tag": release["tag"], "to_commit": release["commit"],
            "database_backup": backup.name if backup else None, "restart_required": not auto_restarting,
            "message": (
                "Update installiert – Dienste werden im Hintergrund automatisch neu gestartet und die Oberfläche lädt gleich neu."
                if auto_restarting
                else "Code aktualisiert. Bitte Stop_Compliance_Agent.bat und danach Start_Compliance_Agent.bat "
                     "ausführen - der Starter aktualisiert Abhängigkeiten und baut das Frontend neu."
            ),
        })

    # --- Data-Loss-Prevention ----------------------------------------------
    @application.post(
        "/api/v1/redact",
        response_model=RedactResponse,
        tags=["Data Loss Prevention"],
        summary="Text vor dem Versand an ein Cloud-LLM endgültig schwärzen (DLP-Gateway)",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("redact", "rate_limit_redact_per_minute")),
        ],
    )
    async def redact_text_endpoint(request: Request, body: RedactRequest) -> RedactResponse:
        """Schwärzt Zugangsdaten, vertrauliche Dateinamen, geschützte Parameter, Sperrbegriffe
        (``DLP_TERMS`` plus ``extra_terms``) und personenbezogene Daten zu ``[REDACTED_...]``.

        Endgültig und ohne Mapping; der Text wird weder gespeichert noch geloggt.
        """
        result = await anyio.to_thread.run_sync(
            partial(
                redact_text_dlp,
                body.text,
                extra_terms=[
                    *(term.strip() for term in request.app.state.settings.dlp_terms.split(",") if term.strip()),
                    *body.extra_terms,
                ],
                redact_pii=body.redact_pii,
                redact_amounts=body.redact_amounts,
            )
        )
        logger.info("DLP-Gateway: %s Schwärzungen", result.total, extra={"counts": result.counts})
        return RedactResponse(
            redacted_text=result.text, counts=result.counts, total=result.total, ruleset_version=DLP_RULESET
        )

    # --- Audit-Ledger ------------------------------------------------------
    @application.get(
        "/api/audit/trail",
        tags=["Audit-Ledger"],
        summary="Einträge des unveränderbaren Prüfprotokolls",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_trail(
        request: Request,
        document_id: str | None = Query(None, description="Optional auf ein Dokument filtern."),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, object]:
        """Neueste Einträge zuerst; jeder Eintrag trägt ``previous_hash`` und ``entry_hash``.

        ``signature_status`` (``valid`` | ``invalid`` | ``unsigned``) weist für
        Prüfer-Einträge die Ed25519-Signatur gegen den System-Schluessel aus.
        """
        ledger: AuditLedger = request.app.state.ledger
        entries = await ledger.list(document_id=document_id, limit=limit)
        statuses = await ledger.signature_statuses(entries)
        return {
            "items": [{**entry.to_dict(), "signature_status": status} for entry, status in zip(entries, statuses)],
            "count": len(entries),
        }

    @application.get(
        "/api/audit/verify",
        tags=["Audit-Ledger"],
        summary="Hash-Kette vollständig nachrechnen",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_verify(request: Request) -> dict[str, object]:
        """Prüft Sequenz, Verkettung und Inhalts-Hash jedes Eintrags."""
        ledger: AuditLedger = request.app.state.ledger
        return (await ledger.verify_chain()).to_dict()

    @application.get(
        "/api/audit/head",
        tags=["Audit-Ledger"],
        summary="Aktueller Kopf-Hash zur externen Verankerung",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_head(request: Request) -> dict[str, object]:
        """Den Kopf-Hash regelmäßig extern ablegen - dann ist auch Abschneiden nachweisbar."""
        ledger: AuditLedger = request.app.state.ledger
        head_hash, seq = await ledger.head()
        return {"head_hash": head_hash, "seq": seq, "timestamp": utcnow().isoformat()}

    @application.get(
        "/api/audit/signing-key",
        tags=["Audit-Ledger"],
        summary="Öffentlicher Schlüssel der System-Signatur (Ed25519)",
        dependencies=[Depends(require_api_key)],
    )
    async def signing_key(request: Request) -> dict[str, str]:
        """Den Fingerabdruck in der Verfahrensdokumentation hinterlegen - nur dann belegt
        die Signatur eines Prüfdatenpakets die Herkunft aus dieser Installation."""
        signer: SystemSigner = request.app.state.signer
        return await anyio.to_thread.run_sync(signer.public_info)


# Modul-Level-Instanz fuer "uvicorn app.main:app".
app = create_app()
