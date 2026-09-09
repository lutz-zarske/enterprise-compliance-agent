"""Fachlogik: Ingestion, Extraktion, Compliance-Audit und Mapping.

Diese Schicht kennt weder FastAPI noch SQLAlchemy - sie arbeitet gegen das
``DocumentRepository``-Protocol und den ``OllamaClient``.  Dadurch ist sie
isoliert testbar, und die Endpunkte in ``main.py`` bleiben duenn.

Der Ablauf von ``extract_and_audit`` ist bewusst zweistufig: ein LLM-Aufruf
fuer die fachliche Extraktion, ein zweiter fuer das Compliance-Audit.  Zwei
fokussierte Prompts liefern bei einem 14B-Modell deutlich stabilere Ergebnisse
als ein einziger Prompt, der beide Aufgaben vermischt.  Anschliessend laufen
deterministische Kontrollen (IBAN-Pruefsumme, Regex-PII-Scan, Eskalations-
regeln), die das Modellergebnis korrigieren statt ihm blind zu vertrauen.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread

from app.config import Settings
from app.db import DocumentRecord, DocumentRepository, NewDocument, utcnow
from app.llm import OllamaClient
from app.pdf_reader import PdfExtraction, extract_text_async
from app.redaction import enforce_masking, merge_findings, scan_text
from app.schemas import (
    SPECIAL_CATEGORIES,
    AIActAssessment,
    AIActRiskLevel,
    ComplianceAudit,
    DocType,
    DocumentDetail,
    DocumentStatus,
    DocumentSummary,
    ExtractionResult,
    GDPRAssessment,
    PIICategory,
    RiskLevel,
    iban_checksum_valid,
)

logger = logging.getLogger(__name__)

#: Erlaubte Dateiendungen und MIME-Typen fuer den Upload.
ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream"})
ALLOWED_SUFFIXES = frozenset({".pdf"})

#: Laenge der Textvorschau in der Detailansicht.
TEXT_PREVIEW_CHARS = 1200

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Fehler der Fachschicht
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Basisklasse fuer fachliche Fehler mit stabilem Fehlercode."""

    code = "service_error"
    hint: str | None = None
    status_code = 400


class UploadValidationError(ServiceError):
    """Der Upload verletzt Typ-, Groessen- oder Formatvorgaben."""

    code = "invalid_upload"
    status_code = 415


class UploadTooLargeError(UploadValidationError):
    """Die Datei ueberschreitet das konfigurierte Groessenlimit."""

    code = "file_too_large"
    status_code = 413


class DocumentNotFoundError(ServiceError):
    """Es existiert kein Dokument mit der angefragten ID."""

    code = "document_not_found"
    status_code = 404
    hint = "IDs aller vorhandenen Dokumente liefert GET /documents."


class NoTextAvailableError(ServiceError):
    """Zum Dokument liegt kein extrahierbarer Text vor."""

    code = "no_text_available"
    status_code = 422
    hint = "Das Dokument erneut hochladen; gescannte PDFs vorab per OCR aufbereiten."


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def sanitize_filename(filename: str) -> str:
    """Entschaerft einen Dateinamen fuer Anzeige und Ablage."""
    name = unicodedata.normalize("NFKC", filename or "").strip()
    name = Path(name.replace("\\", "/")).name  # Pfadanteile entfernen
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return name[:200] or "dokument.pdf"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _truncate_for_prompt(text: str, limit: int) -> str:
    """Kuerzt lange Dokumente auf das Kontextbudget des Modells."""
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.25) :]
    return (
        f"{head}\n\n[... {len(text) - len(head) - len(tail)} Zeichen aus der "
        f"Dokumentmitte ausgelassen ...]\n\n{tail}"
    )


# ---------------------------------------------------------------------------
# Deterministische Nachkontrollen
# ---------------------------------------------------------------------------


def augment_extraction_issues(extraction: ExtractionResult) -> ExtractionResult:
    """Ergaenzt regelbasierte Befunde, die das Modell uebersehen haben koennte."""
    issues = list(extraction.issues)

    def add(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if extraction.iban and not iban_checksum_valid(extraction.iban):
        add("Die angegebene IBAN besteht die MOD-97-Pruefsummenkontrolle nicht.")

    if extraction.doc_type is DocType.INVOICE:
        if not extraction.document_number:
            add("Pflichtangabe fehlt: fortlaufende Rechnungsnummer (Paragraf 14 Abs. 4 Nr. 4 UStG).")
        if not extraction.document_date:
            add("Pflichtangabe fehlt: Ausstellungsdatum (Paragraf 14 Abs. 4 Nr. 3 UStG).")
        if extraction.total_amount is None:
            add("Pflichtangabe fehlt: Rechnungsbetrag.")
        elif extraction.total_amount <= 0:
            add("Der ausgewiesene Gesamtbetrag ist nicht positiv.")
        if extraction.total_amount is not None and not extraction.currency:
            add("Zum Gesamtbetrag ist keine Waehrung angegeben.")

    if (
        extraction.document_date
        and extraction.due_date
        and extraction.due_date < extraction.document_date
    ):
        add("Das Faelligkeitsdatum liegt vor dem Ausstellungsdatum.")

    return extraction.model_copy(update={"issues": issues})


def _derive_gdpr_risk(findings_categories: set[PIICategory], model_risk: RiskLevel) -> RiskLevel:
    """Hebt die DSGVO-Risikostufe an, wenn deterministisch mehr gefunden wurde.

    Abgesenkt wird nie - das Modell darf die Einstufung verschaerfen, aber eine
    regelbasiert belegte besondere Kategorie nach Art. 9/10 kann es nicht
    wegargumentieren.
    """
    order = [RiskLevel.NONE, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]

    if findings_categories & SPECIAL_CATEGORIES:
        derived = RiskLevel.HIGH
    elif findings_categories & {
        PIICategory.ID_DOCUMENT_NUMBER,
        PIICategory.SOCIAL_SECURITY_NUMBER,
        PIICategory.TAX_ID,
        PIICategory.BANK_ACCOUNT,
        PIICategory.DATE_OF_BIRTH,
    }:
        derived = RiskLevel.MEDIUM
    elif findings_categories:
        derived = RiskLevel.LOW
    else:
        derived = RiskLevel.NONE

    return max(derived, model_risk, key=order.index)


def escalate_ai_act(assessment: AIActAssessment) -> AIActAssessment:
    """Erzwingt "high", wenn eine Anhang-III-Kategorie belegt ist.

    Ein Modell benennt gelegentlich korrekt die Hochrisiko-Kategorie, stuft die
    Gesamtrisikostufe aber zu niedrig ein.  Diese Regel schliesst die Luecke.
    """
    has_annex_iii = any(system.annex_iii_categories for system in assessment.systems)
    if not has_annex_iii:
        return assessment
    if assessment.overall_risk_level in {AIActRiskLevel.HIGH, AIActRiskLevel.UNACCEPTABLE}:
        return assessment

    reasoning = assessment.reasoning
    note = (
        "Automatische Korrektur: Es wurde mindestens eine Anhang-III-Kategorie "
        "belegt, daher gilt die Einstufung als Hochrisiko-KI-System (Art. 6 Abs. 2)."
    )
    return assessment.model_copy(
        update={
            "overall_risk_level": AIActRiskLevel.HIGH,
            "describes_ai_system": True,
            "reasoning": f"{reasoning}\n{note}".strip(),
        }
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractionOutcome:
    """Ergebnis eines vollstaendigen Extraktions- und Auditlaufs."""

    record: DocumentRecord
    extraction: ExtractionResult
    compliance: ComplianceAudit
    duration_ms: int


class DocumentService:
    """Orchestriert Upload, Extraktion und Compliance-Audit."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        llm: OllamaClient,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._llm = llm

    # --- Ingestion ---------------------------------------------------------
    async def ingest(
        self, *, filename: str, content_type: str | None, data: bytes
    ) -> tuple[DocumentRecord, str | None]:
        """Validiert, parst und persistiert ein hochgeladenes PDF.

        Returns:
            Das angelegte Dokument und - falls vorhanden - die ID eines bereits
            gespeicherten Dokuments mit identischer Pruefsumme.
        """
        safe_name = sanitize_filename(filename)
        suffix = Path(safe_name).suffix.lower()

        if suffix not in ALLOWED_SUFFIXES:
            raise UploadValidationError(
                f"Nicht unterstuetzte Dateiendung '{suffix or '(keine)'}'. Erlaubt ist ausschliesslich .pdf."
            )
        if content_type and content_type.split(";")[0].strip() not in ALLOWED_CONTENT_TYPES:
            raise UploadValidationError(
                f"Nicht unterstuetzter Content-Type '{content_type}'. Erwartet wird application/pdf."
            )
        if not data:
            raise UploadValidationError("Die hochgeladene Datei ist leer.")
        if len(data) > self._settings.max_upload_bytes:
            raise UploadTooLargeError(
                f"Die Datei ist {len(data) / 1_048_576:.1f} MB gross; erlaubt sind "
                f"{self._settings.max_upload_bytes / 1_048_576:.1f} MB."
            )

        # Textextraktion vor dem Speichern: ein unlesbares PDF wird gar nicht
        # erst persistiert.
        parsed: PdfExtraction = await extract_text_async(data)

        sha256 = compute_sha256(data)
        duplicate = await self._repository.get_by_sha256(sha256)

        document = NewDocument(
            original_filename=safe_name,
            stored_filename="",  # wird nach der ID-Vergabe gesetzt
            content_type="application/pdf",
            size_bytes=len(data),
            sha256=sha256,
            page_count=parsed.page_count,
            char_count=parsed.char_count,
            raw_text=parsed.text,
        )
        document.stored_filename = f"{document.id}.pdf"

        target = self._settings.upload_path / document.stored_filename
        await anyio.to_thread.run_sync(lambda: target.write_bytes(data))

        record = await self._repository.create(document)
        logger.info(
            "Dokument %s aufgenommen (%s Seiten, %s Zeichen, %s Bytes)",
            record.id,
            parsed.page_count,
            parsed.char_count,
            len(data),
        )
        return record, (duplicate.id if duplicate else None)

    # --- Extraktion & Audit ------------------------------------------------
    async def extract_and_audit(self, record: DocumentRecord) -> ExtractionOutcome:
        """Fuehrt beide LLM-Aufrufe aus und verrechnet sie mit den Regelbefunden."""
        text = record.raw_text or ""
        if len(text.strip()) < 1:
            raise NoTextAvailableError(
                f"Zum Dokument {record.id} ist kein extrahierter Text gespeichert."
            )

        prompt_text = _truncate_for_prompt(text, self._settings.max_prompt_chars)
        await self._repository.mark_processing(record.id)

        try:
            # Schritt 1: fachliche Extraktion.
            extraction, extraction_ms = await self._llm.extract_document(prompt_text)
            extraction = augment_extraction_issues(extraction)

            # Schritt 2: Compliance-Audit (EU AI Act + DSGVO).
            audit_payload, audit_ms = await self._llm.audit_document(prompt_text)
        except Exception as exc:
            await self._repository.mark_failed(record.id, f"{type(exc).__name__}: {exc}")
            raise

        # Schritt 3: deterministische Gegenprobe auf dem vollstaendigen Text.
        # Die Maskierung laeuft vor dem Zusammenfuehren: nur so treffen sich
        # ein vom Modell im Klartext gemeldeter Wert und derselbe, vom
        # Regelscanner bereits maskierte Wert im selben Deduplizierungs-
        # schluessel und werden als ein Treffer (source="both") erkannt.
        rule_findings = scan_text(text)
        llm_findings = enforce_masking(
            audit_payload.gdpr.findings, enabled=self._settings.mask_pii_in_storage
        )
        masked = merge_findings(llm_findings, rule_findings)

        categories = {finding.category for finding in masked}
        gdpr = GDPRAssessment.model_validate(
            {
                **audit_payload.gdpr.model_dump(mode="json", exclude={"findings"}),
                "findings": [finding.model_dump(mode="json") for finding in masked],
                "contains_personal_data": bool(masked) or audit_payload.gdpr.contains_personal_data,
                "risk_level": _derive_gdpr_risk(categories, audit_payload.gdpr.risk_level).value,
            }
        )
        ai_act = escalate_ai_act(audit_payload.ai_act)

        compliance = ComplianceAudit(
            ai_act=ai_act,
            gdpr=gdpr,
            model=self._llm.model,
            audited_at=utcnow(),
            duration_ms=audit_ms,
        )

        updated = await self._repository.save_results(
            record.id,
            model=self._llm.model,
            extraction=extraction.model_dump(mode="json"),
            compliance=compliance.model_dump(mode="json"),
        )
        logger.info(
            "Dokument %s ausgewertet: %s | %s",
            record.id,
            extraction.doc_type.value,
            compliance.headline,
        )
        return ExtractionOutcome(
            record=updated,
            extraction=extraction,
            compliance=compliance,
            duration_ms=extraction_ms + audit_ms,
        )

    # --- Lesezugriffe ------------------------------------------------------
    async def require_document(self, document_id: str) -> DocumentRecord:
        record = await self._repository.get(document_id)
        if record is None:
            raise DocumentNotFoundError(f"Kein Dokument mit der ID '{document_id}' gefunden.")
        return record

    async def list_documents(
        self, *, limit: int, offset: int, status: DocumentStatus | None = None
    ) -> tuple[list[DocumentSummary], int]:
        records, total = await self._repository.list(
            limit=limit, offset=offset, status=status.value if status else None
        )
        return [to_summary(record) for record in records], total


# ---------------------------------------------------------------------------
# Mapping Datensatz -> API-Modell
# ---------------------------------------------------------------------------


def parse_extraction(record: DocumentRecord) -> ExtractionResult | None:
    if not record.extraction:
        return None
    try:
        return ExtractionResult.model_validate(record.extraction)
    except Exception:  # noqa: BLE001 - alter Datenbestand darf die API nicht kippen
        logger.warning("Extraktion von Dokument %s ist nicht lesbar.", record.id, exc_info=True)
        return None


def parse_compliance(record: DocumentRecord) -> ComplianceAudit | None:
    if not record.compliance:
        return None
    try:
        return ComplianceAudit.model_validate(record.compliance)
    except Exception:  # noqa: BLE001
        logger.warning("Audit von Dokument %s ist nicht lesbar.", record.id, exc_info=True)
        return None


def to_summary(record: DocumentRecord) -> DocumentSummary:
    """Erzeugt eine Zeile der tabellarischen Uebersicht."""
    extraction = parse_extraction(record)
    compliance = parse_compliance(record)
    return DocumentSummary(
        id=record.id,
        filename=record.original_filename,
        status=DocumentStatus(record.status),
        size_bytes=record.size_bytes,
        page_count=record.page_count,
        doc_type=extraction.doc_type if extraction else None,
        sender=extraction.sender if extraction else None,
        document_date=extraction.document_date if extraction else None,
        total_amount=extraction.total_amount if extraction else None,
        currency=extraction.currency if extraction else None,
        ai_act_risk_level=compliance.ai_act.overall_risk_level if compliance else None,
        gdpr_risk_level=compliance.gdpr.risk_level if compliance else None,
        contains_special_categories=(
            compliance.gdpr.contains_special_categories if compliance else None
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(record: DocumentRecord) -> DocumentDetail:
    """Erzeugt die Detailansicht inklusive Compliance-Audit."""
    preview: str | None = None
    if record.raw_text:
        preview = record.raw_text[:TEXT_PREVIEW_CHARS]
        if len(record.raw_text) > TEXT_PREVIEW_CHARS:
            preview += " …"

    return DocumentDetail(
        id=record.id,
        filename=record.original_filename,
        content_type=record.content_type,
        status=DocumentStatus(record.status),
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        page_count=record.page_count,
        char_count=record.char_count,
        model=record.model,
        extraction=parse_extraction(record),
        compliance=parse_compliance(record),
        text_preview=preview,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        extracted_at=record.extracted_at,
    )
