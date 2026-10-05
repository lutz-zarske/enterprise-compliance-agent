"""FastAPI-Anwendung mit den fuenf Endpunkten des Compliance-Agenten.

Die Endpunkte bleiben bewusst duenn: Validierung, Autorisierung und
Fehlerabbildung liegen hier, die gesamte Fachlogik in ``app.services``.
Jeder Fehler verlaesst die Anwendung im einheitlichen Format
``{"error": {"code", "message", "hint"}}`` - maschinenlesbar und mit
konkretem Handlungshinweis.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
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

from app.audit_ledger import AuditLedger
from app.config import APP_TITLE, APP_VERSION, Settings, get_settings
from app.db import build_repository, utcnow
from app.gobd_export import build_gobd_package
from app.procedural_doc import build_procedural_doc
from app.procedural_doc import render_html as render_procedural_html
from app.procedural_doc import render_markdown as render_procedural_markdown
from app.inference import InferenceRouter
from app.llm import LLMError, OllamaClient, OllamaUnavailableError
from app.providers import (
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.reporting import REPORT_CSP, build_report, render_html, render_markdown
from app.runtime_settings import CLOUD_PROVIDERS, InferenceMode, RuntimeSettingsStore
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
    OllamaHealth,
    PinRequest,
    SettingsUpdate,
    SignOffRequest,
    UploadResponse,
)
from app.services import (
    PROGRESS,
    DocumentNotAnalyzedError,
    DocumentService,
    ServiceError,
    UploadTooLargeError,
    UploadValidationError,
    to_detail,
)

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("app.access")

API_KEY_HEADER = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

#: Grenze fuer den gepufferten Upload-Lesevorgang.
_CHUNK_SIZE = 1024 * 1024

DESCRIPTION = """\
Institutionelles Backend zur automatisierten Pruefung von Geschaeftsdokumenten.

**Funktionsumfang**

* **Extraktion** von Rechnungen und Vertraegen inkl. aller Pflichtangaben nach
  § 14 Abs. 4 UStG (Steuernummer/USt-IdNr., Leistungszeitpunkt, Netto, Steuersatz).
* **Deterministische Compliance-Scorecard (0-100)** mit vier Kacheln: formelle
  Gueltigkeit (§ 14 UStG, EN 16931), EU AI Act, DSGVO, Finanzmathematik (MOD-97, MwSt.).
* **EU-AI-Act-Klassifizierung** nach VO (EU) 2024/1689 mit Anhang-III-Eskalation.
* **DSGVO-Audit** mit Art.-9/10-Erkennung und drei Maskierungsstufen.
* **Hash-verkettetes Pruefprotokoll** (EU AI Act Art. 12, GoBD) und
  **Human-Oversight-Siegel** (Art. 14) mit druckfertigem Pruefzertifikat.
* **E-Rechnung (EN 16931)**: ZUGFeRD/Factur-X-Anhaenge und reine XRechnung (CII/UBL)
  werden deterministisch gelesen; bei hybriden Rechnungen ist der XML-Teil massgeblich.
* **Pruefdatenpaket (ZIP)** mit Originalbeleg, XML, Ledger-Auszug, Zertifikat und
  Ed25519-signiertem Manifest.
* **Multi-Provider-Inferenz**: lokal (Ollama, Default) oder Gemini / Claude / GPT -
  Cloud-Aufrufe ausschliesslich ueber das Privacy Gateway (Pseudonymisierung).

**Authentifizierung**: Ist `API_KEY` gesetzt, verlangen alle Endpunkte ausser
`/health` den Header `X-API-Key`. Ohne gesetzten Wert ist die Pruefung deaktiviert -
dann kann jeder im Netz auch die Einstellungen aendern; produktiv immer setzen.
"""

TAGS_METADATA = [
    {"name": "System", "description": "Betriebszustand von Datenbank, Ollama und Modell."},
    {"name": "Dokumente", "description": "Upload, Extraktion, Compliance-Audit und Uebersicht."},
    {"name": "Audit-Ledger", "description": "Hash-verkettetes Pruefprotokoll (EU AI Act Art. 12, GoBD)."},
    {"name": "Human Oversight", "description": "Pruefbericht und Siegel durch eine Pruefperson (Art. 14)."},
    {"name": "Compliance Copilot", "description": "Dokumentbezogene Fragen an das aktive Modell."},
    {"name": "Einstellungen", "description": "Inferenz-Provider, API-Keys (verschluesselt), PII-Strenge."},
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
    router = InferenceRouter(
        settings, runtime, llm, cloud_transport=getattr(app.state, "cloud_transport", None)
    )

    app.state.engine = engine
    app.state.repository = repository
    app.state.llm = llm
    app.state.ledger = ledger
    app.state.runtime = runtime
    app.state.router = router
    app.state.signer = signer
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
        await router.aclose()
        await llm.aclose()
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


async def require_api_key(
    request: Request,
    api_key: str | None = Depends(_api_key_scheme),
) -> None:
    """Prueft den API-Key, sofern in der Konfiguration einer hinterlegt ist."""
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

        Eine vom Client gelieferte ``X-Request-ID`` wird nur uebernommen, wenn
        sie dem erlaubten Zeichensatz entspricht (Schutz vor Log-Injection).
        Geloggt werden Methode, Pfad (enthaelt nur UUIDs), Status und Dauer -
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
            f"Fehlender oder ungueltiger API-Key im Header '{API_KEY_HEADER}'.",
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
            "Das Kontingent schuetzt die Inferenz-Schnittstelle vor Ueberlastung.",
        )
        response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @application.exception_handler(ServiceError)
    async def _handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, str(exc), exc.hint)

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
            f"Ungueltige Anfrage: {first.get('msg', 'Validierung fehlgeschlagen')} ({location}).",
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
    """Liest den Upload gepuffert und bricht bei Ueberschreitung frueh ab."""
    buffer = bytearray()
    while chunk := await upload.read(_CHUNK_SIZE):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise UploadTooLargeError(
                f"Die Datei ueberschreitet das Limit von {max_bytes / 1_048_576:.1f} MB."
            )
    return bytes(buffer)


def _attachment_header(filename: str) -> str:
    """Content-Disposition mit ASCII-Fallback und RFC-5987-Dateinamen (Umlaute)."""
    fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


async def _procedural_doc(
    request: Request,
    record: object,
    *,
    entries: list | None = None,
    verification: object | None = None,
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
    )


def _register_routes(application: FastAPI) -> None:
    error_responses: dict[int | str, dict[str, object]] = {
        401: {"model": ErrorResponse, "description": "API-Key fehlt oder ist ungueltig"},
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
        """Prueft alle externen Abhaengigkeiten und meldet sie einzeln.

        Der Endpunkt antwortet immer mit HTTP 200; der Gesamtstatus im Body ist
        ``degraded``, sobald eine Komponente ausfaellt. Monitoring-Systeme
        koennen dadurch zwischen "Anwendung tot" und "Abhaengigkeit gestoert"
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

        # --- Ollama ---
        started = time.perf_counter()
        try:
            models = await llm.list_models()
            available = await llm.is_model_available(models)
            ollama = OllamaHealth(
                status="ok" if available else "degraded",
                detail=(
                    None
                    if available
                    else f"Modell '{settings.ollama_model}' ist nicht installiert."
                ),
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                model_available=available,
                available_models=sorted(models),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except LLMError as exc:
            ollama = OllamaHealth(
                status="unavailable",
                detail=str(exc)[:300],
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
            )

        runtime: RuntimeSettingsStore = request.app.state.runtime
        snap = runtime.snapshot()
        is_cloud = snap.inference_mode in CLOUD_PROVIDERS
        inference = {
            "mode": snap.inference_mode.value,
            "model": snap.active_model,
            "is_cloud": is_cloud,
            "privacy_gateway_active": is_cloud,
            "configured": (not is_cloud) or bool(snap.key_for(snap.inference_mode.value)),
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
            413: {"model": ErrorResponse, "description": "Datei zu gross"},
            429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"},
            415: {"model": ErrorResponse, "description": "Weder PDF noch XML"},
            422: {"model": ErrorResponse, "description": "PDF ohne Textlayer/beschaedigt oder XML keine EN-16931-Rechnung"},
        },
    )
    async def upload_document(
        file: UploadFile = File(..., description="PDF oder XRechnung/ZUGFeRD-XML (multipart/form-data)."),
        service: DocumentService = Depends(get_service),
        settings: Settings = Depends(get_app_settings),
    ) -> UploadResponse:
        """Nimmt ein PDF oder eine XML-E-Rechnung entgegen, prueft sie und legt sie samt Text ab.

        PDF: Dateiendung, Content-Type, Groesse, PDF-Signatur und Textlayer; ein
        eingebetteter ZUGFeRD-/Factur-X-/XRechnung-Datensatz wird gelesen und mit
        dem Bildteil abgeglichen. XML: EN-16931-Rechnung in CII- oder UBL-Syntax,
        geparst ohne DTD und Entitaeten. Erst danach wird gespeichert. Die Analyse
        startet separat ueber ``POST /documents/{id}/extract``.
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
        response_model=ExtractionResponse,
        tags=["Dokumente"],
        summary="Extraktion und Compliance-Audit ausfuehren",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("extract", "rate_limit_extract_per_minute")),
        ],
        responses={
            **error_responses,
            422: {"model": ErrorResponse, "description": "Kein Text zum Dokument vorhanden"},
            429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"},
            502: {"model": ErrorResponse, "description": "Modellantwort unbrauchbar"},
            503: {"model": ErrorResponse, "description": "Ollama nicht erreichbar"},
        },
    )
    async def extract_document(
        document_id: str = Path(..., description="UUID des Dokuments."),
        service: DocumentService = Depends(get_service),
    ) -> ExtractionResponse:
        """Startet beide LLM-Durchlaeufe und persistiert das Ergebnis.

        Durchlauf 1 extrahiert die fachlichen Kerndaten, Durchlauf 2 fuehrt das
        Compliance-Audit (EU AI Act + DSGVO) aus. Anschliessend laufen
        deterministische Kontrollen: IBAN-Pruefsumme, Regex-basierter
        PII-Scan als Zweitmeinung, Maskierung aller Treffer und die
        Hochstufung auf "high", wenn eine Anhang-III-Kategorie belegt ist.

        Der Aufruf ist wiederholbar; ein erneuter Aufruf ueberschreibt das
        vorherige Ergebnis.
        """
        record = await service.require_document(document_id)
        outcome = await service.extract_and_audit(record)
        return ExtractionResponse(
            id=outcome.record.id,
            status=DocumentStatus(outcome.record.status),
            model=outcome.compliance.model,
            extraction=outcome.extraction,
            compliance=outcome.compliance,
            duration_ms=outcome.duration_ms,
            scorecard=outcome.scorecard,
            provider=outcome.provider,
            audit_entry_id=outcome.audit_entry_id,
        )

    # --- GET /documents ----------------------------------------------------
    @application.get(
        "/documents",
        response_model=DocumentListResponse,
        tags=["Dokumente"],
        summary="Tabellarische Uebersicht aller Dokumente",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def list_documents(
        limit: int = Query(50, ge=1, le=200, description="Maximale Anzahl Zeilen."),
        offset: int = Query(0, ge=0, description="Versatz fuer die Blaetterung."),
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
        """Metadaten, Extraktion, Audit, Scorecard, Siegel und geschwaerzte Textansicht."""
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
        summary="Dokument oben anpinnen bzw. loesen",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def pin_document(
        body: PinRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        record = await service.require_document(document_id)
        updated = await service.set_pinned(record, body.pinned)
        return to_detail(updated, pii_level=service.pii_level)

    @application.post(
        "/documents/{document_id}/sign-off",
        response_model=DocumentDetail,
        tags=["Human Oversight"],
        summary="Pruefergebnis durch eine Pruefperson versiegeln (EU AI Act Art. 14)",
        dependencies=[Depends(require_api_key)],
        responses={**error_responses, 409: {"model": ErrorResponse, "description": "Noch nicht analysiert"}},
    )
    async def sign_off_document(
        body: SignOffRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        """Schreibt einen ``sign_off``-Eintrag in den Hash-Ledger und versiegelt das Dokument.

        Eine erneute Analyse hebt das Siegel auf (der Pruefgegenstand hat sich
        geaendert); die Historie bleibt im Ledger vollstaendig erhalten.
        """
        record = await service.require_document(document_id)
        updated = await service.sign_off(record, body)
        return to_detail(updated, pii_level=service.pii_level)

    @application.get(
        "/api/documents/{document_id}/export/procedural-doc",
        tags=["Human Oversight"],
        summary="GoBD-Verfahrensdokumentation (Entwurf) mit Prüfpfad des Belegs (html | markdown)",
        dependencies=[Depends(require_api_key)],
        responses=error_responses,
    )
    async def export_procedural_doc(
        request: Request,
        document_id: str = Path(...),
        doc_format: Literal["html", "markdown"] = Query("html", alias="format"),
        service: DocumentService = Depends(get_service),
    ) -> Response:
        """Vier Saeulen nach GoBD Rz. 153 aus dem aktuellen Systemzustand, plus Anhang zum Beleg.

        Organisatorische Angaben, die das System nicht kennt, sind als
        ``[vom Unternehmen zu ergaenzen]`` markiert. Aufbewahrung: 10 Jahre
        (§ 147 Abs. 1 Nr. 1 AO).
        """
        record = await service.require_document(document_id)
        doc = await _procedural_doc(request, record)
        stem = record.original_filename.rsplit(".", 1)[0]
        if doc_format == "markdown":
            return PlainTextResponse(
                render_procedural_markdown(doc),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": _attachment_header(f"Verfahrensdokumentation_{stem}.md")},
            )
        return HTMLResponse(
            render_procedural_html(doc),
            headers={"Content-Security-Policy": REPORT_CSP, "X-Content-Type-Options": "nosniff"},
        )

    @application.post(
        "/api/documents/{document_id}/override",
        response_model=DocumentDetail,
        tags=["Human Oversight"],
        summary="KI-Einstufung durch eine Pruefperson uebersteuern (Art. 14 Abs. 4 lit. d AI Act)",
        dependencies=[Depends(require_api_key)],
        responses={
            **error_responses,
            409: {"model": ErrorResponse, "description": "Noch nicht analysiert"},
            422: {"model": ErrorResponse, "description": "Keine Aenderung oder Begruendung zu kurz"},
        },
    )
    async def override_document(
        body: OverrideRequest, document_id: str = Path(...), service: DocumentService = Depends(get_service)
    ) -> DocumentDetail:
        """Setzt die EU-AI-Act-Risikostufe neu und rechnet den Score deterministisch neu.

        Schreibt einen Ed25519-signierten ``human_override``-Eintrag in den Ledger
        (Person, Begruendung, Rechtsnorm, Score vorher/nachher). Ein bestehendes
        Siegel wird aufgehoben, weil sich der Pruefgegenstand geaendert hat.
        """
        record = await service.require_document(document_id)
        updated = await service.override(record, body)
        return to_detail(updated, pii_level=service.pii_level)

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
        service: DocumentService = Depends(get_service),
    ) -> Response:
        record = await service.require_document(document_id)
        if not record.scorecard:
            raise DocumentNotAnalyzedError(f"Dokument {document_id} ist noch nicht analysiert.")
        ledger: AuditLedger = request.app.state.ledger
        report = build_report(
            record, await ledger.list(document_id=document_id, limit=50), await ledger.verify_chain()
        )
        stem = record.original_filename.rsplit(".", 1)[0]
        if report_format == "json":
            return JSONResponse(
                report,
                headers={"Content-Disposition": f'inline; filename="Pruefzertifikat_{stem}.json"'},
            )
        if report_format == "markdown":
            return PlainTextResponse(
                render_markdown(report),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'inline; filename="Pruefzertifikat_{stem}.md"'},
            )
        return HTMLResponse(
            render_html(report),
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
        service: DocumentService = Depends(get_service),
    ) -> Response:
        """GoBD-orientiertes Einzelbeleg-Paket (Rz. 58 ff.: Nachvollziehbarkeit, Unveraenderbarkeit).

        Das Manifest traegt SHA-256 je Datei und eine Ed25519-Signatur dieser
        Installation; den Fingerabdruck liefert ``GET /api/audit/signing-key``.
        Kein Datentraeger nach dem Beschreibungsstandard (index.xml) und kein
        qualifiziertes Siegel nach eIDAS.
        """
        record = await service.require_document(document_id)
        if not record.scorecard:
            raise DocumentNotAnalyzedError(f"Dokument {document_id} ist noch nicht analysiert.")
        ledger: AuditLedger = request.app.state.ledger
        entries = await ledger.list(document_id=document_id, limit=1000)
        verification = await ledger.verify_chain()
        original = await service.read_original(record)
        certificate = render_html(build_report(record, entries[:50], verification))
        procedural = render_procedural_html(
            await _procedural_doc(request, record, entries=entries, verification=verification)
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
        stem = record.original_filename.rsplit(".", 1)[0]
        logger.info("Pruefdatenpaket fuer %s erzeugt (%s Bytes).", record.id, len(data))
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": _attachment_header(f"Pruefdatenpaket_{stem}.zip"),
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
        """Antwort des aktiven Modells, geerdet auf nummeriertem Dokumenttext und Pruefergebnis."""
        record = await service.require_document(document_id)
        result = await service.copilot(
            record, body.question, [turn.model_dump() for turn in body.history]
        )
        return CopilotResponse.model_validate(result)

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
        summary="Drei Referenzdokumente fuer Live-Demos anlegen",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("upload", "rate_limit_upload_per_minute")),
        ],
    )
    async def demo_seed(service: DocumentService = Depends(get_service)) -> dict[str, object]:
        """Idempotent: bereits vorhandene Referenzdokumente (gleiche SHA-256) werden wiederverwendet.

        Die Analyse startet bewusst separat (``POST /documents/{id}/extract``),
        damit das Frontend den Live-Stepper je Dokument zeigen kann.
        """
        items = await service.seed_demo()
        return {"items": items, "created": sum(1 for item in items if item["created"])}

    # --- Einstellungen ------------------------------------------------------
    @application.get(
        "/api/settings",
        tags=["Einstellungen"],
        summary="Aktive Inferenz- und Compliance-Konfiguration (Keys maskiert)",
        dependencies=[Depends(require_api_key)],
    )
    async def get_runtime_settings(runtime: RuntimeSettingsStore = Depends(get_runtime)) -> dict[str, object]:
        return runtime.public_view()

    @application.post(
        "/api/settings",
        tags=["Einstellungen"],
        summary="Inferenz-Modus, Modelle, API-Keys und PII-Strenge aendern",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("settings", "rate_limit_settings_per_minute")),
        ],
    )
    async def update_runtime_settings(
        body: SettingsUpdate, runtime: RuntimeSettingsStore = Depends(get_runtime)
    ) -> dict[str, object]:
        """API-Keys werden Fernet-verschluesselt gespeichert und nur maskiert zurueckgegeben."""
        await runtime.update(body.model_dump(exclude_none=True))
        logger.info(
            "Einstellungen geaendert: %s",
            ", ".join(sorted(body.model_dump(exclude_none=True).keys())),
        )
        return runtime.public_view()

    @application.post(
        "/api/settings/test-connection",
        tags=["Einstellungen"],
        summary="Verbindung zum gewaehlten Provider pruefen (ohne Dokumentinhalt)",
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
                    return {"ok": False, "provider": mode.value, "model": model,
                            "message": f"Ollama erreichbar, Modell '{model}' aber nicht installiert."}
                message = f"Ollama erreichbar, Modell {model} installiert."
            else:
                router: InferenceRouter = request.app.state.router
                message = await router.cloud_client(mode, snap).test_connection()
        except LLMError as exc:
            return {"ok": False, "provider": mode.value, "model": model, "message": str(exc), "code": exc.code}
        return {"ok": True, "provider": mode.value, "model": model, "message": message}

    # --- Audit-Ledger ------------------------------------------------------
    @application.get(
        "/api/audit/trail",
        tags=["Audit-Ledger"],
        summary="Eintraege des unveraenderbaren Pruefprotokolls",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_trail(
        request: Request,
        document_id: str | None = Query(None, description="Optional auf ein Dokument filtern."),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, object]:
        """Neueste Eintraege zuerst; jeder Eintrag traegt ``previous_hash`` und ``entry_hash``.

        ``signature_status`` (``valid`` | ``invalid`` | ``unsigned``) weist fuer
        Pruefer-Eintraege die Ed25519-Signatur gegen den System-Schluessel aus.
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
        summary="Hash-Kette vollstaendig nachrechnen",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_verify(request: Request) -> dict[str, object]:
        """Prueft Sequenz, Verkettung und Inhalts-Hash jedes Eintrags."""
        ledger: AuditLedger = request.app.state.ledger
        return (await ledger.verify_chain()).to_dict()

    @application.get(
        "/api/audit/head",
        tags=["Audit-Ledger"],
        summary="Aktueller Kopf-Hash zur externen Verankerung",
        dependencies=[Depends(require_api_key)],
    )
    async def audit_head(request: Request) -> dict[str, object]:
        """Den Kopf-Hash regelmaessig extern ablegen - dann ist auch Abschneiden nachweisbar."""
        ledger: AuditLedger = request.app.state.ledger
        head_hash, seq = await ledger.head()
        return {"head_hash": head_hash, "seq": seq, "timestamp": utcnow().isoformat()}

    @application.get(
        "/api/audit/signing-key",
        tags=["Audit-Ledger"],
        summary="Oeffentlicher Schluessel der System-Signatur (Ed25519)",
        dependencies=[Depends(require_api_key)],
    )
    async def signing_key(request: Request) -> dict[str, str]:
        """Den Fingerabdruck in der Verfahrensdokumentation hinterlegen - nur dann belegt
        die Signatur eines Pruefdatenpakets die Herkunft aus dieser Installation."""
        signer: SystemSigner = request.app.state.signer
        return await anyio.to_thread.run_sync(signer.public_info)


# Modul-Level-Instanz fuer "uvicorn app.main:app".
app = create_app()
