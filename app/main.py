"""FastAPI-Anwendung mit den fuenf Endpunkten des Compliance-Agenten.

Die Endpunkte bleiben bewusst duenn: Validierung, Autorisierung und
Fehlerabbildung liegen hier, die gesamte Fachlogik in ``app.services``.
Jeder Fehler verlaesst die Anwendung im einheitlichen Format
``{"error": {"code", "message", "hint"}}`` - maschinenlesbar und mit
konkretem Handlungshinweis.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Path, Query, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.audit_ledger import AuditLedger
from app.config import APP_TITLE, APP_VERSION, Settings, get_settings
from app.db import build_repository, utcnow
from app.llm import LLMError, OllamaClient, OllamaUnavailableError
from app.logging_config import configure_logging, normalize_request_id, request_id_var
from app.rate_limit import RateLimitExceededError, TokenBucketLimiter, rate_limit
from app.pdf_reader import PdfReadError
from app.schemas import (
    ComponentHealth,
    DatabaseHealth,
    DocumentDetail,
    DocumentListResponse,
    DocumentStatus,
    ErrorResponse,
    ExtractionResponse,
    HealthResponse,
    OllamaHealth,
    UploadResponse,
)
from app.services import (
    DocumentService,
    ServiceError,
    UploadTooLargeError,
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

* **Extraktion** von Rechnungen und Vertraegen (Absender, Empfaenger, Belegnummer,
  Datum, Faelligkeit, Betrag, Waehrung, IBAN, Zusammenfassung, Auffaelligkeiten).
* **EU-AI-Act-Klassifizierung** nach VO (EU) 2024/1689 - insbesondere die
  Hochrisiko-Bereiche aus Anhang III (HR-Recruiting, kritische Infrastruktur,
  Kreditwuerdigkeitspruefung).
* **DSGVO-Audit** mit Erkennung besonderer Kategorien nach Art. 9/10
  (Gesundheitsdaten, Religionszugehoerigkeit, Ausweisnummern).

**Privacy-First**: Die Inferenz laeuft vollstaendig lokal ueber Ollama; kein
Dokumentinhalt verlaesst den Rechner. PII-Treffer werden ausschliesslich
maskiert persistiert.

**Authentifizierung**: Ist `API_KEY` gesetzt, verlangen alle `/documents`-Endpunkte
den Header `X-API-Key`. Ohne gesetzten Wert ist die Pruefung deaktiviert.
"""

TAGS_METADATA = [
    {"name": "System", "description": "Betriebszustand von Datenbank, Ollama und Modell."},
    {"name": "Dokumente", "description": "Upload, Extraktion, Compliance-Audit und Uebersicht."},
    {"name": "Audit-Ledger", "description": "Hash-verkettetes Pruefprotokoll (EU AI Act Art. 12, GoBD)."},
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
    llm = OllamaClient(settings)
    ledger = AuditLedger(engine)

    app.state.engine = engine
    app.state.repository = repository
    app.state.llm = llm
    app.state.ledger = ledger
    app.state.service = DocumentService(settings, repository, llm, ledger=ledger)

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
    if api_key and api_key == settings.api_key:
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
        # 503, solange der Dienst selbst das Problem ist; 502 bei unbrauchbarer Antwort.
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if isinstance(exc, OllamaUnavailableError)
            else status.HTTP_502_BAD_GATEWAY
        )
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

        components: list[ComponentHealth] = [database, ollama]
        overall = "ok" if all(item.status == "ok" for item in components) else "degraded"

        return HealthResponse(
            status=overall,
            version=APP_VERSION,
            environment=settings.app_env,
            auth_enabled=settings.auth_enabled,
            timestamp=utcnow(),
            database=database,
            ollama=ollama,
        )

    # --- POST /documents/upload -------------------------------------------
    @application.post(
        "/documents/upload",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["Dokumente"],
        summary="PDF hochladen, validieren und Text extrahieren",
        dependencies=[
            Depends(require_api_key),
            Depends(rate_limit("upload", "rate_limit_upload_per_minute")),
        ],
        responses={
            **error_responses,
            413: {"model": ErrorResponse, "description": "Datei zu gross"},
            429: {"model": ErrorResponse, "description": "Rate-Limit erreicht"},
            415: {"model": ErrorResponse, "description": "Kein PDF"},
            422: {"model": ErrorResponse, "description": "PDF ohne Textlayer oder beschaedigt"},
        },
    )
    async def upload_document(
        file: UploadFile = File(..., description="PDF-Datei (multipart/form-data)."),
        service: DocumentService = Depends(get_service),
        settings: Settings = Depends(get_app_settings),
    ) -> UploadResponse:
        """Nimmt ein PDF entgegen, prueft es und legt es samt Text ab.

        Geprueft werden Dateiendung, Content-Type, Groesse, die PDF-Signatur und
        das Vorhandensein eines Textlayers. Erst danach wird gespeichert - ein
        unlesbares Dokument landet nie in der Datenbank. Die Extraktion selbst
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
        """Gibt Metadaten, Extraktion, Compliance-Audit und eine Textvorschau zurueck."""
        record = await service.require_document(document_id)
        return to_detail(record)

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
        """Neueste Eintraege zuerst; jeder Eintrag traegt ``previous_hash`` und ``entry_hash``."""
        ledger: AuditLedger = request.app.state.ledger
        entries = await ledger.list(document_id=document_id, limit=limit)
        return {"items": [entry.to_dict() for entry in entries], "count": len(entries)}

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


# Modul-Level-Instanz fuer "uvicorn app.main:app".
app = create_app()
