"""Fachlogik: Ingestion, Extraktion, Compliance-Audit und Mapping.

Diese Schicht kennt weder FastAPI noch SQLAlchemy - sie arbeitet gegen das
``DocumentRepository``-Protocol und den ``InferenceRouter`` (bzw. direkt
einen ``StructuredLLMClient``).  Dadurch ist sie
isoliert testbar, und die Endpunkte in ``main.py`` bleiben dünn.

Der Ablauf von ``extract_and_audit`` ist bewusst zweistufig: ein LLM-Aufruf
für die fachliche Extraktion, ein zweiter für das Compliance-Audit.  Zwei
fokussierte Prompts liefern bei einem 14B-Modell deutlich stabilere Ergebnisse
als ein einziger Prompt, der beide Aufgaben vermischt.  Anschließend laufen
deterministische Kontrollen (IBAN-Prüfsumme, Regex-PII-Scan, Eskalations-
regeln), die das Modellergebnis korrigieren statt ihm blind zu vertrauen.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import anyio.to_thread

from app.audit_ledger import AuditEventType, AuditLedger, LedgerEntry
from app.config import Settings
from app.db import DocumentRecord, DocumentRepository, NewDocument, utcnow
from app.extractors import (
    EInvoiceError,
    compare_with_visual,
    find_einvoice_attachment,
    parse_einvoice_xml,
    render_reading_text,
    to_extraction,
)
from app.extractors.einvoice import PARSER_VERSION, looks_like_xml
from app.heuristics import (
    HEURISTIC_LABEL,
    HEURISTIC_MODEL,
    HEURISTIC_PROVIDER,
    heuristic_audit,
    heuristic_copilot_answer,
    heuristic_extraction,
)
from app.inference import STAGE_LABELS, is_failover_error
from app.jobs import PHASES, JobCancelled
from app.llm import PROMPT_HASH, ComplianceAuditPayload, LLMError, StructuredLLMClient
from app.pdf_reader import PdfExtraction, extract_text_async
from app.privacy_vault import PrivacyVault
from app.redaction import build_text_view, enforce_masking, merge_findings, scan_text
from app.runtime_settings import RuntimeSettingsStore
from app.scoring import RULESET_VERSION, SMALL_AMOUNT_LIMIT, complete_amounts, compute_scorecard, presented_band
from app.schemas import (
    SPECIAL_CATEGORIES,
    AIActAssessment,
    AIActRiskLevel,
    ComplianceAudit,
    DocType,
    DocumentDetail,
    DocumentStatus,
    DocumentSummary,
    EInvoiceData,
    ExtractionResult,
    GDPRAssessment,
    PIICategory,
    PIIFinding,
    RiskLevel,
    HumanOverride,
    OverrideRequest,
    Scorecard,
    SignOff,
    SignOffDecision,
    SignOffRequest,
    iban_checksum_valid,
)

logger = logging.getLogger(__name__)

#: Erlaubte Dateiendungen und MIME-Typen für den Upload (je Endung).
ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream"})
XML_CONTENT_TYPES = frozenset({"application/xml", "text/xml", "application/octet-stream"})
ALLOWED_SUFFIXES = frozenset({".pdf", ".xml"})

#: Kennung des deterministischen E-Rechnungs-Pfads in Datenbank, Ledger und UI.
STRUCTURED_MODEL = "en16931-parser"
STRUCTURED_PROVIDER = "structured"

#: Länge der Textvorschau in der Detailansicht.
TEXT_PREVIEW_CHARS = 1200

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Fehler der Fachschicht
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Basisklasse für fachliche Fehler mit stabilem Fehlercode."""

    code = "service_error"
    hint: str | None = None
    status_code = 400


class UploadValidationError(ServiceError):
    """Der Upload verletzt Typ-, Größen- oder Formatvorgaben."""

    code = "invalid_upload"
    status_code = 415


class UploadTooLargeError(UploadValidationError):
    """Die Datei überschreitet das konfigurierte Größenlimit."""

    code = "file_too_large"
    status_code = 413


class ReleaseUpdateRunningError(ServiceError):
    """Während eines Release-Wechsels startet keine neue Analyse."""

    code = "release_update_running"
    status_code = 409
    hint = "Das Update dauert nur Sekunden - danach erneut prüfen."


class DocumentNotFoundError(ServiceError):
    """Es existiert kein Dokument mit der angefragten ID."""

    code = "document_not_found"
    status_code = 404
    hint = "IDs aller vorhandenen Dokumente liefert GET /documents."


class DocumentNotAnalyzedError(ServiceError):
    """Aktion setzt eine abgeschlossene Analyse voraus."""

    code = "document_not_analyzed"
    status_code = 409
    hint = "Zuerst POST /documents/{id}/extract ausführen."


class InvalidEInvoiceUploadError(UploadValidationError):
    """Reiner XML-Upload ist keine auswertbare EN-16931-Rechnung."""

    code = "invalid_einvoice"
    status_code = 422
    hint = "Erwartet wird eine XRechnung bzw. ein ZUGFeRD-/Factur-X-Datensatz (CII oder UBL)."


class OverrideWithoutChangeError(ServiceError):
    """Die beantragte Einstufung entspricht der bestehenden."""

    code = "override_without_change"
    status_code = 422
    hint = "Eine Übersteuerung muss die Risikostufe ändern; zur reinen Freigabe das Siegel verwenden."


class OriginalMissingError(ServiceError):
    """Die Originaldatei fehlt im Ablageverzeichnis."""

    code = "original_missing"
    status_code = 410
    hint = "Ablageverzeichnis und Datensicherung prüfen; das Dokument erneut hochladen."


class NoTextAvailableError(ServiceError):
    """Zum Dokument liegt kein extrahierbarer Text vor."""

    code = "no_text_available"
    status_code = 422
    hint = "Das Dokument erneut hochladen; gescannte PDFs vorab per OCR aufbereiten."


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def sanitize_filename(filename: str) -> str:
    """Entschärft einen Dateinamen für Anzeige und Ablage."""
    name = unicodedata.normalize("NFKC", filename or "").strip()
    name = Path(name.replace("\\", "/")).name  # Pfadanteile entfernen
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return name[:200] or "dokument.pdf"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def describe_failure(exc: BaseException) -> str:
    """Ruhige, verständliche Fehlermeldung für Beleg und Oberfläche - nie ein Klassenname."""
    if isinstance(exc, (LLMError, ServiceError)):
        return str(exc)
    return "Unerwarteter Fehler bei der Analyse – Details stehen im Serverprotokoll."


#: Kurzbezeichnung der Scorecard-Kacheln für die Ledger-Zusammenfassung.
TILE_SHORT_LABELS: dict[str, str] = {
    "formal": "§ 14 UStG",
    "regulatory": "EU AI Act",
    "privacy": "DSGVO",
    "math": "Finanzmathematik",
}
NO_COMPLIANCE_FINDINGS = "Keine Compliance-Auffälligkeiten"
#: Lesbare Entscheidung im Prüfprotokoll (statt des Enum-Werts).
SIGN_OFF_LABELS: dict[SignOffDecision, str] = {
    SignOffDecision.APPROVED: "Freigegeben und versiegelt",
    SignOffDecision.REJECTED: "Freigabe verweigert und versiegelt",
}


def fallback_explanation(exc: BaseException, stages: int) -> str:
    """Ursache plus nächster Schritt für das Regelwerk-Audit.

    Ohne Ausweich-Stufe hilft der Hinweis des Fehlers (z. B. Ausweichmodell oder
    zweiten Key hinterlegen); mit Kaskade ist wichtig, dass alle Stufen scheiterten.
    """
    message = describe_failure(exc)
    if stages == 2:
        return f"{message} Auch die zweite Stufe der Ausweich-Kaskade antwortete nicht."
    if stages > 2:
        return f"{message} Auch die übrigen {stages - 1} Stufen der Ausweich-Kaskade antworteten nicht."
    hint = getattr(exc, "hint", None)
    return f"{message} {hint}" if hint else message


def analysis_summary(scorecard: Scorecard, compliance: ComplianceAudit) -> str:
    """Kurzfassung des ``analysis``-Ledger-Eintrags ohne Widerspruch zum Score.

    ``ComplianceAudit.headline`` betrachtet nur EU AI Act und DSGVO.  Bei formalen
    oder rechnerischen Abzügen (z. B. Steuerfalle mit Score 45) stünde dort sonst
    „Keine Compliance-Auffälligkeiten“ neben „Freigabe gesperrt“ - stattdessen
    nennt die Zusammenfassung Score und betroffene Kacheln.
    """
    parts = [scorecard.release_recommendation]
    deductions = [
        f"{TILE_SHORT_LABELS.get(tile.key, tile.title)} −{tile.deduction}"
        for tile in scorecard.tiles
        if tile.deduction > 0
    ]
    if deductions:
        parts.append(f"Score {scorecard.score}: " + ", ".join(deductions))
    if compliance.headline != NO_COMPLIANCE_FINDINGS or not deductions:
        parts.append(compliance.headline)
    return " | ".join(parts)


def _truncate_for_prompt(text: str, limit: int) -> str:
    """Kürzt lange Dokumente auf das Kontextbudget des Modells."""
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


MISSING_NUMBER_ISSUE = "Pflichtangabe fehlt: fortlaufende Rechnungsnummer (Paragraf 14 Abs. 4 Nr. 4 UStG)."
MISSING_TOTAL_ISSUE = "Pflichtangabe fehlt: Rechnungsbetrag."


def _drop_stale_issues(extraction: ExtractionResult) -> ExtractionResult:
    """Entfernt Hinweise, die nach der Betragsabsicherung nicht mehr zutreffen."""
    total = extraction.total_amount
    stale = set()
    if total is not None:
        stale.add(MISSING_TOTAL_ISSUE)
        if Decimal(0) < total <= SMALL_AMOUNT_LIMIT and (extraction.currency or "EUR") == "EUR":
            stale.add(MISSING_NUMBER_ISSUE)  # Kleinbetragsrechnung: keine Rechnungsnummer nötig (§ 33 UStDV)
    issues = [issue for issue in extraction.issues if issue not in stale]
    return extraction if issues == extraction.issues else extraction.model_copy(update={"issues": issues})


def augment_extraction_issues(extraction: ExtractionResult) -> ExtractionResult:
    """Ergänzt regelbasierte Befunde, die das Modell übersehen haben könnte."""
    issues = list(extraction.issues)

    def add(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if extraction.iban and not iban_checksum_valid(extraction.iban):
        add("Die angegebene IBAN besteht die MOD-97-Prüfsummenkontrolle nicht.")

    if extraction.doc_type is DocType.INVOICE:
        total = extraction.total_amount
        small = total is not None and Decimal(0) < total <= SMALL_AMOUNT_LIMIT and (extraction.currency or "EUR") == "EUR"
        if not extraction.document_number and not small:
            add(MISSING_NUMBER_ISSUE)
        if not extraction.document_date:
            add("Pflichtangabe fehlt: Ausstellungsdatum (Paragraf 14 Abs. 4 Nr. 3 UStG).")
        if total is None:
            add(MISSING_TOTAL_ISSUE)
        elif total < 0:
            add("Negativer Gesamtbetrag: Rechnungskorrektur bzw. Gutschrift – Bezug zur ursprünglichen Rechnung prüfen.")
        elif total == 0:
            add("Der ausgewiesene Gesamtbetrag ist null.")
        if extraction.total_amount is not None and not extraction.currency:
            add("Zum Gesamtbetrag ist keine Währung angegeben.")

    if (
        extraction.document_date
        and extraction.due_date
        and extraction.due_date < extraction.document_date
    ):
        add("Das Fälligkeitsdatum liegt vor dem Ausstellungsdatum.")

    return extraction.model_copy(update={"issues": issues})


def _derive_gdpr_risk(findings_categories: set[PIICategory], model_risk: RiskLevel) -> RiskLevel:
    """Hebt die DSGVO-Risikostufe an, wenn deterministisch mehr gefunden wurde.

    Abgesenkt wird nie - das Modell darf die Einstufung verschärfen, aber eine
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
    """Erzwingt die höchste System-Risikostufe bzw. "high" bei belegter Anhang-III-Kategorie.

    Ein Modell benennt gelegentlich korrekt eine Hochrisiko-Kategorie oder ein
    System als ``high``/``unacceptable``, stuft die Gesamtrisikostufe aber zu
    niedrig ein.  Diese Regel schließt die Lücke.
    """
    order = (
        AIActRiskLevel.NOT_APPLICABLE,
        AIActRiskLevel.MINIMAL,
        AIActRiskLevel.LIMITED,
        AIActRiskLevel.HIGH,
        AIActRiskLevel.UNACCEPTABLE,
    )
    has_annex_iii = any(system.annex_iii_categories for system in assessment.systems)
    highest_system = max(
        (system.risk_level for system in assessment.systems),
        key=order.index,
        default=AIActRiskLevel.NOT_APPLICABLE,
    )
    target = max(assessment.overall_risk_level, highest_system, key=order.index)
    if has_annex_iii and order.index(target) < order.index(AIActRiskLevel.HIGH):
        target = AIActRiskLevel.HIGH
    if target is assessment.overall_risk_level:
        return assessment

    reasoning = assessment.reasoning
    note = (
        "Automatische Korrektur: Es wurde mindestens eine Anhang-III-Kategorie "
        "belegt, daher gilt die Einstufung als Hochrisiko-KI-System (Art. 6 Abs. 2)."
        if has_annex_iii and target is AIActRiskLevel.HIGH
        else f"Automatische Korrektur: Ein erkanntes KI-System trägt die Stufe '{target.value}', "
        "daher wird die Gesamtrisikostufe entsprechend angehoben."
    )
    return assessment.model_copy(
        update={
            "overall_risk_level": target,
            "describes_ai_system": True,
            "reasoning": f"{reasoning}\n{note}".strip(),
        }
    )


# ---------------------------------------------------------------------------
# E-Rechnung (EN 16931)
# ---------------------------------------------------------------------------


def read_embedded_einvoice(pdf_bytes: bytes, visual_text: str) -> EInvoiceData | None:
    """Liest den eingebetteten XML-Datensatz einer hybriden Rechnung (falls vorhanden).

    Ein defektes oder nicht unterstütztes XML verhindert den Upload nicht: Es
    wird mit ``error`` vermerkt, und das Dokument läuft über die Textanalyse.
    """
    attachment = find_einvoice_attachment(pdf_bytes)
    if attachment is None:
        return None
    try:
        einvoice = parse_einvoice_xml(attachment.data, source="embedded", attachment_name=attachment.name)
    except EInvoiceError as exc:
        logger.warning("Eingebettetes XML %s nicht auswertbar: %s", attachment.name, exc)
        return EInvoiceData(
            source="embedded",
            attachment_name=attachment.name,
            error=str(exc),
            xml_sha256=compute_sha256(attachment.data),
            xml_size=len(attachment.data),
        )
    einvoice.visual_check = compare_with_visual(einvoice, visual_text)
    return einvoice


def parse_einvoice(record: DocumentRecord) -> EInvoiceData | None:
    if not record.einvoice:
        return None
    try:
        return EInvoiceData.model_validate(record.einvoice)
    except Exception:  # noqa: BLE001 - alter Datenbestand darf die API nicht kippen
        logger.warning("E-Rechnungsdaten von Dokument %s nicht lesbar.", record.id, exc_info=True)
        return None


def uses_structured_path(einvoice: EInvoiceData | None) -> bool:
    """XML ist maßgeblich, wenn es auswertbar ist und - bei hybriden Rechnungen - ein
    E-Rechnungs-Profil trägt.  MINIMUM/BASIC WL sind keine E-Rechnungen: Dort ist
    der Bildteil die Rechnung, und die Analyse läuft über den Text."""
    if einvoice is None or einvoice.error:
        return False
    return einvoice.source == "standalone" or einvoice.is_einvoice


# ---------------------------------------------------------------------------
# Fortschritt der Pipeline (für den Live-Audit-Stepper im Frontend)
# ---------------------------------------------------------------------------

#: Reihenfolge der echten Verarbeitungsschritte in ``extract_and_audit`` (eine Quelle: ``app.jobs``).
PIPELINE_STAGES: tuple[tuple[str, str], ...] = tuple((key, label) for key, label, _weight in PHASES)

#: Rückrufe für Live-Fortschritt: Phase (Job-Monitor) und Kaskaden-Ereignis (Neuversuch, Wechsel).
StageHook = Callable[[str], None]
EventHook = Callable[[str, dict[str, Any]], None]


class ProgressTracker:
    """Prozesslokaler Fortschrittsspeicher je Dokument (bewusst ohne DB-Schreiblast)."""

    def __init__(self) -> None:
        self._stages: dict[str, str] = {}

    def set(self, document_id: str, stage: str) -> None:
        self._stages[document_id] = stage

    def get(self, document_id: str) -> str | None:
        return self._stages.get(document_id)

    def clear(self, document_id: str) -> None:
        self._stages.pop(document_id, None)

    @property
    def active(self) -> int:
        """Anzahl laufender Analysen (sperrt den Release-Wechsel)."""
        return len(self._stages)


PROGRESS = ProgressTracker()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractionOutcome:
    """Ergebnis eines vollständigen Extraktions- und Auditlaufs."""

    record: DocumentRecord
    extraction: ExtractionResult
    compliance: ComplianceAudit
    duration_ms: int
    scorecard: Scorecard | None = None
    provider: str = "local"
    audit_entry_id: str | None = None


def _vault_of(client: object) -> PrivacyVault | None:
    """Vault des Privacy Gateways - beim einfachen Cloud-Client wie in der Ausweich-Kaskade."""
    vault = getattr(client, "vault", None)
    return vault if isinstance(vault, PrivacyVault) else None


class DocumentService:
    """Orchestriert Upload, Extraktion und Compliance-Audit."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        llm: object,
        *,
        ledger: AuditLedger | None = None,
        runtime: RuntimeSettingsStore | None = None,
        progress: ProgressTracker | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        #: Entweder ein ``InferenceRouter`` (Produktion) oder direkt ein Client (Tests).
        self._llm = llm
        self._ledger = ledger
        self._runtime = runtime
        self._progress = progress or PROGRESS

    # --- Konfiguration -----------------------------------------------------
    def _acquire_client(self, on_event: EventHook | None = None) -> StructuredLLMClient:
        acquire = getattr(self._llm, "acquire", None)
        if callable(acquire):
            return acquire(on_event=on_event)  # type: ignore[no-any-return]
        return self._llm  # type: ignore[return-value]

    @property
    def heuristic_fallback(self) -> bool:
        return self._settings.heuristic_fallback

    @property
    def pii_level(self) -> str:
        if self._runtime is not None:
            return self._runtime.snapshot().pii_strictness.value
        return self._settings.pii_strictness

    def _flags(self) -> tuple[bool, bool]:
        """(Paragraf-14-Prüfung erzwingen, AI-Act-Eskalation aktiv)."""
        if self._runtime is None:
            return True, True
        snap = self._runtime.snapshot()
        return snap.enforce_ustg_check, snap.ai_act_escalation

    def _read_pdf(self, record: DocumentRecord) -> bytes | None:
        path = self._settings.upload_path / record.stored_filename
        try:
            return path.read_bytes()
        except OSError:
            return None

    async def read_original(self, record: DocumentRecord) -> bytes:
        """Originalbeleg bitgenau; die Prüfsumme muss zur Datenbank passen."""
        data = await anyio.to_thread.run_sync(self._read_pdf, record)
        if data is None:
            raise OriginalMissingError(f"Originaldatei zu Dokument {record.id} nicht gefunden.")
        if compute_sha256(data) != record.sha256:
            raise OriginalMissingError(
                f"Originaldatei zu Dokument {record.id} weicht von der gespeicherten SHA-256 ab."
            )
        return data

    @staticmethod
    def embedded_xml(record: DocumentRecord, original: bytes) -> tuple[str, bytes] | None:
        """Eingebetteter E-Rechnungs-Datensatz einer hybriden Rechnung (für das Prüfpaket)."""
        einvoice = parse_einvoice(record)
        if einvoice is None or einvoice.source != "embedded":
            return None
        attachment = find_einvoice_attachment(original)
        if attachment is None:
            return None
        return attachment.name, attachment.data

    # --- Ingestion ---------------------------------------------------------
    async def ingest(
        self, *, filename: str, content_type: str | None, data: bytes
    ) -> tuple[DocumentRecord, str | None]:
        """Validiert, parst und persistiert ein hochgeladenes PDF oder XML.

        PDFs werden auf einen eingebetteten E-Rechnungs-Datensatz (ZUGFeRD,
        Factur-X, XRechnung) untersucht; reine XML-Dateien müssen eine
        EN-16931-Rechnung in CII- oder UBL-Syntax sein.

        Returns:
            Das angelegte Dokument und - falls vorhanden - die ID eines bereits
            gespeicherten Dokuments mit identischer Prüfsumme.
        """
        safe_name = sanitize_filename(filename)
        suffix = Path(safe_name).suffix.lower()

        if suffix not in ALLOWED_SUFFIXES:
            raise UploadValidationError(
                f"Nicht unterstützte Dateiendung '{suffix or '(keine)'}'. Erlaubt sind .pdf und .xml."
            )
        allowed_types = XML_CONTENT_TYPES if suffix == ".xml" else ALLOWED_CONTENT_TYPES
        if content_type and content_type.split(";")[0].strip() not in allowed_types:
            expected = "application/xml" if suffix == ".xml" else "application/pdf"
            raise UploadValidationError(
                f"Nicht unterstützter Content-Type '{content_type}'. Erwartet wird {expected}."
            )
        if not data:
            raise UploadValidationError("Die hochgeladene Datei ist leer.")
        if len(data) > self._settings.max_upload_bytes:
            raise UploadTooLargeError(
                f"Die Datei ist {len(data) / 1_048_576:.1f} MB groß; erlaubt sind "
                f"{self._settings.max_upload_bytes / 1_048_576:.1f} MB."
            )

        # Parsen vor dem Speichern: ein unlesbares Dokument wird gar nicht
        # erst persistiert.
        if suffix == ".xml":
            einvoice, text, pages = await self._ingest_xml(data)
            stored_type = "application/xml"
        else:
            parsed: PdfExtraction = await extract_text_async(data)
            einvoice = await anyio.to_thread.run_sync(lambda: read_embedded_einvoice(data, parsed.text))
            text, pages = parsed.text, parsed.page_count
            stored_type = "application/pdf"

        sha256 = compute_sha256(data)
        duplicate = await self._repository.get_by_sha256(sha256)

        document = NewDocument(
            original_filename=safe_name,
            stored_filename="",  # wird nach der ID-Vergabe gesetzt
            content_type=stored_type,
            size_bytes=len(data),
            sha256=sha256,
            page_count=pages,
            char_count=len(text),
            raw_text=text,
            einvoice=einvoice.model_dump(mode="json") if einvoice else None,
        )
        document.stored_filename = f"{document.id}{suffix}"

        target = self._settings.upload_path / document.stored_filename
        await anyio.to_thread.run_sync(lambda: target.write_bytes(data))

        record = await self._repository.create(document)
        logger.info(
            "Dokument %s aufgenommen (%s, %s Seiten, %s Zeichen, %s Bytes, E-Rechnung: %s)",
            record.id,
            stored_type,
            pages,
            len(text),
            len(data),
            einvoice.profile if einvoice and not einvoice.error else "nein",
        )
        return record, (duplicate.id if duplicate else None)

    async def _ingest_xml(self, data: bytes) -> tuple[EInvoiceData, str, int]:
        if not looks_like_xml(data):
            raise InvalidEInvoiceUploadError("Die Datei beginnt nicht mit einem XML-Element.")
        try:
            einvoice = await anyio.to_thread.run_sync(lambda: parse_einvoice_xml(data, source="standalone"))
        except EInvoiceError as exc:
            raise InvalidEInvoiceUploadError(str(exc)) from exc
        return einvoice, render_reading_text(einvoice), 0

    async def _reread_original(self, record: DocumentRecord) -> tuple[DocumentRecord, bool]:
        """Liest den gespeicherten Originalbeleg mit dem aktuellen Parser neu ein.

        So wirkt jede Neuprüfung mit dem aktuellen Parser und XML-↔-PDF-Abgleich,
        auch bei Belegen, die unter einer älteren Version hochgeladen wurden.
        Fehlt das Original oder passt die Prüfsumme nicht, bleibt der
        gespeicherte Stand – die Prüfung läuft wie bisher weiter.
        """
        data = await anyio.to_thread.run_sync(self._read_pdf, record)
        if data is None or compute_sha256(data) != record.sha256:
            logger.warning("Original zu Dokument %s nicht lesbar – gespeicherter Stand wird geprüft.", record.id)
            return record, False
        text = record.raw_text or ""
        try:
            if record.content_type == "application/xml":
                einvoice: EInvoiceData | None = await anyio.to_thread.run_sync(
                    lambda: parse_einvoice_xml(data, source="standalone")
                )
                text = render_reading_text(einvoice)  # type: ignore[arg-type]
            else:
                einvoice = await anyio.to_thread.run_sync(lambda: read_embedded_einvoice(data, text))
        except Exception:  # noqa: BLE001 - ein Parserfehler darf die Neuprüfung nicht verhindern
            logger.warning("Original zu Dokument %s nicht neu auswertbar.", record.id, exc_info=True)
            return record, False
        dumped = einvoice.model_dump(mode="json") if einvoice else None
        if dumped == record.einvoice and text == (record.raw_text or ""):
            return record, False
        updated = await self._repository.update_source(
            record.id, einvoice=dumped, raw_text=text, char_count=len(text)
        )
        logger.info("Dokument %s mit Parser %s neu eingelesen.", record.id, PARSER_VERSION)
        return updated, True

    # --- Extraktion & Audit ------------------------------------------------
    async def extract_and_audit(
        self,
        record: DocumentRecord,
        *,
        on_stage: StageHook | None = None,
        on_event: EventHook | None = None,
    ) -> ExtractionOutcome:
        """Vier echte Pipeline-Stufen; jede Stufe meldet sich im ProgressTracker und beim Job.

        1. Text-Layer & XML-Vorrang (E-Rechnungen laufen deterministisch über den Datensatz)
        2. Regelbasierter PII-Scan; bei Cloud-Inferenz Pseudonymisierung im Vault
        3. LLM-Extraktion + Paragraf-14-Kontrollen
        4. LLM-Audit (EU AI Act, DSGVO), Eskalationsregeln, Scorecard, Ledger

        Scheitern alle KI-Stufen an Überlast oder Ausfall, schließt das Regelwerk
        die Prüfung ab (``heuristic_fallback``) - gekennzeichnet in UI und Ledger.
        Ein Abbruch stellt den vorherigen Status wieder her; ein vorhandenes
        Ergebnis bleibt unangetastet.
        """
        progress = self._progress
        previous_status = record.status if record.status != DocumentStatus.PROCESSING.value else (
            DocumentStatus.EXTRACTED.value if record.scorecard else DocumentStatus.UPLOADED.value
        )

        def stage(key: str) -> None:
            progress.set(record.id, key)
            if on_stage is not None:
                on_stage(key)

        stage("text_check")
        record, reread = await self._reread_original(record)
        text = record.raw_text or ""
        if len(text.strip()) < 1:
            progress.clear(record.id)
            raise NoTextAvailableError(
                f"Zum Dokument {record.id} ist kein extrahierter Text gespeichert."
            )

        einvoice = parse_einvoice(record)
        if uses_structured_path(einvoice):
            return await self._structured_analysis(record, einvoice, stage, reread=reread)  # type: ignore[arg-type]

        prompt_text = _truncate_for_prompt(text, self._settings.max_prompt_chars)
        enforce_ustg, escalate = self._flags()

        try:
            client = self._acquire_client(on_event)
        except Exception:
            progress.clear(record.id)
            raise
        vault = _vault_of(client)
        rule_findings: list[PIIFinding] = []
        try:
            await self._repository.mark_processing(record.id)
            stage("pii_scan")
            rule_findings = scan_text(text)
            if vault is not None:
                # Mapping vorab aufbauen: gleiche Platzhalter für beide Cloud-LLM-Aufrufe.
                vault.pseudonymize(prompt_text)

            stage("ustg_check")
            extraction, extraction_ms = await client.extract_document(prompt_text)
            extraction = augment_extraction_issues(extraction)

            stage("ai_act")
            audit_payload, audit_ms = await client.audit_document(prompt_text)
        except (asyncio.CancelledError, JobCancelled):
            if vault is not None:
                vault.clear()
            await self._repository.restore_status(record.id, previous_status)
            progress.clear(record.id)
            await self._log_failover(record, client)
            raise
        except Exception as exc:
            if vault is not None:
                vault.clear()
            switches = await self._log_failover(record, client)
            if is_failover_error(exc) and self.heuristic_fallback:
                return await self._heuristic_analysis(
                    record, reason=exc, rule_findings=rule_findings or scan_text(text), stage=stage,
                    enforce_ustg=enforce_ustg, escalate=escalate, einvoice=einvoice, failover=switches,
                    stages=int(getattr(client, "stage_count", 1) or 1),
                )
            await self._record_failure(record, previous_status, exc)
            progress.clear(record.id)
            raise

        provider = getattr(client, "provider", "local")
        switches = await self._log_failover(record, client)
        cloud_touched = provider != "local" or any(
            s.get("from_provider") not in {None, "local"} or s.get("to_provider") not in {None, "local"}
            for s in switches
        )
        vault_report = vault.report if (vault is not None and cloud_touched) else None
        if vault is not None:
            vault.clear()
        return await self._finalize_analysis(
            record,
            extraction=extraction,
            audit_payload=audit_payload,
            rule_findings=rule_findings,
            model=client.model,
            provider=provider,
            vault_report=vault_report,
            duration_ms=extraction_ms + audit_ms,
            audit_ms=audit_ms,
            enforce_ustg=enforce_ustg,
            escalate=escalate,
            einvoice=einvoice,
            failover=switches or None,
        )

    async def _heuristic_analysis(
        self,
        record: DocumentRecord,
        *,
        reason: BaseException,
        rule_findings: list[PIIFinding],
        stage: StageHook,
        enforce_ustg: bool,
        escalate: bool,
        einvoice: EInvoiceData | None,
        failover: list[dict[str, str]],
        stages: int = 1,
    ) -> ExtractionOutcome:
        """Stufe 5: deterministisches Regelwerk, wenn keine KI-Stufe antwortet."""
        logger.warning("Dokument %s: alle KI-Stufen ausgefallen (%s) - Regelwerk übernimmt.",
                       record.id, getattr(reason, "code", type(reason).__name__))
        text = record.raw_text or ""
        stage("ustg_check")
        extraction = augment_extraction_issues(heuristic_extraction(text))
        stage("ai_act")
        audit_payload = heuristic_audit(text)
        fallback_reason = fallback_explanation(reason, stages)
        return await self._finalize_analysis(
            record,
            extraction=extraction,
            audit_payload=audit_payload,
            rule_findings=rule_findings,
            model=HEURISTIC_MODEL,
            provider=HEURISTIC_PROVIDER,
            vault_report=None,
            duration_ms=0,
            audit_ms=0,
            enforce_ustg=enforce_ustg,
            escalate=escalate,
            einvoice=einvoice,
            failover=failover or None,
            heuristic_reason=fallback_reason,
            ledger_details={
                "heuristic_fallback": True,
                "label": HEURISTIC_LABEL,
                "reason_code": getattr(reason, "code", "llm_error"),
                "reason": fallback_reason[:300],
            },
        )

    async def _log_failover(self, record: DocumentRecord, client: object) -> list[dict[str, str]]:
        """Schreibt jeden Provider-Wechsel als eigenen Ledger-Eintrag (auch bei späterem Fehlschlag)."""
        switches: list[dict[str, str]] = list(getattr(client, "switches", None) or [])
        if self._ledger is not None:
            for switch in switches:
                await self._ledger.append(
                    event_type=AuditEventType.PROVIDER_FAILOVER,
                    document_id=record.id,
                    sha256_hash=record.sha256,
                    model_name=switch["to_model"],
                    prompt_hash=PROMPT_HASH,
                    result_summary=(
                        f"Wechsel {switch['from_provider']} -> {switch['to_provider']} ({switch['reason_code']})"
                    ),
                    compliance_score=None,
                    risk_tier="unknown",
                    details=switch,
                )
        return switches

    async def _structured_analysis(
        self,
        record: DocumentRecord,
        einvoice: EInvoiceData,
        stage: StageHook | None = None,
        *,
        reread: bool = False,
    ) -> ExtractionOutcome:
        """Deterministischer Pfad für E-Rechnungen: XML ist maßgeblich, kein Sprachmodell.

        Die Rechnungsdaten stammen vollständig aus dem EN-16931-Datensatz; der
        DSGVO-Teil beruht auf dem Regex-Scanner.  Eine KI-Einstufung nach dem
        AI Act findet nicht statt - eine Rechnung begründet keine Anbieter-
        oder Betreiberpflichten; maßgeblich ist der zugrunde liegende Vertrag.
        """
        progress = self._progress
        mark = stage or (lambda key: progress.set(record.id, key))
        enforce_ustg, escalate = self._flags()
        previous_status = DocumentStatus.EXTRACTED.value if record.scorecard else DocumentStatus.UPLOADED.value
        try:
            await self._repository.mark_processing(record.id)
            mark("pii_scan")
            rule_findings = scan_text(record.raw_text or "")
            mark("ustg_check")
            extraction = augment_extraction_issues(to_extraction(einvoice))
            mark("ai_act")
            audit_payload = ComplianceAuditPayload.model_validate(
                {
                    "ai_act": {
                        "describes_ai_system": False,
                        "overall_risk_level": "not_applicable",
                        "systems": [],
                        "reasoning": (
                            "Strukturierte E-Rechnung, deterministisch aus dem EN-16931-Datensatz geprüft (keine "
                            "KI-Inferenz). Eine Rechnung begründet keine Pflichten nach der VO (EU) 2024/1689; "
                            "ein KI-Einsatz ist im zugrunde liegenden Vertrag zu prüfen."
                        ),
                        "obligations": [],
                    },
                    "gdpr": {
                        "contains_personal_data": bool(rule_findings),
                        "findings": [],
                        "risk_level": "none",
                        "reasoning": "Regelbasierter PII-Scan über den Rechnungstext (keine KI-Inferenz).",
                        "recommendations": [],
                    },
                }
            )
        except (asyncio.CancelledError, JobCancelled):
            await self._repository.restore_status(record.id, previous_status)
            progress.clear(record.id)
            raise
        except Exception as exc:
            await self._record_failure(record, previous_status, exc)
            progress.clear(record.id)
            raise
        return await self._finalize_analysis(
            record,
            extraction=extraction,
            audit_payload=audit_payload,
            rule_findings=rule_findings,
            model=STRUCTURED_MODEL,
            provider=STRUCTURED_PROVIDER,
            vault_report=None,
            duration_ms=0,
            audit_ms=0,
            enforce_ustg=enforce_ustg,
            escalate=escalate,
            einvoice=einvoice,
            ledger_details={
                "structured_einvoice": True,
                "einvoice_profile": einvoice.profile,
                "einvoice_syntax": einvoice.syntax,
                "xml_sha256": einvoice.xml_sha256,
                **({"einvoice_reread": True} if reread else {}),
            },
        )

    async def _finalize_analysis(
        self,
        record: DocumentRecord,
        *,
        extraction: ExtractionResult,
        audit_payload: ComplianceAuditPayload,
        rule_findings: list[PIIFinding],
        model: str,
        provider: str,
        vault_report: dict[str, int] | None,
        duration_ms: int,
        audit_ms: int,
        enforce_ustg: bool,
        escalate: bool,
        ledger_details: dict[str, object] | None = None,
        einvoice: EInvoiceData | None = None,
        failover: list[dict[str, str]] | None = None,
        heuristic_reason: str | None = None,
    ) -> ExtractionOutcome:
        """Gemeinsamer Abschluss für Live- und Referenz-Audits.

        Maskierungszwang, Regex-Zweitmeinung, Eskalationsregeln, Scorecard und
        Ledger-Eintrag sind für beide Wege identisch - nur die Herkunft der
        Modellantwort unterscheidet sich.
        """
        # Deterministische Gegenprobe auf dem vollständigen Text.  Die
        # Maskierung läuft vor dem Zusammenführen: nur so treffen sich ein
        # vom Modell im Klartext gemeldeter Wert und derselbe, vom
        # Regelscanner bereits maskierte Wert im selben Deduplizierungs-
        # schlüssel und werden als ein Treffer (source="both") erkannt.
        text = record.raw_text or ""
        if provider != STRUCTURED_PROVIDER:
            extraction = complete_amounts(extraction, text, rule_based=provider == HEURISTIC_PROVIDER)
            extraction = _drop_stale_issues(extraction)
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
        ai_act = escalate_ai_act(audit_payload.ai_act) if escalate else audit_payload.ai_act

        compliance = ComplianceAudit(
            ai_act=ai_act,
            gdpr=gdpr,
            model=model,
            audited_at=utcnow(),
            duration_ms=audit_ms,
            provider=provider,
            privacy_gateway=vault_report,
            failover=failover,
            heuristic=heuristic_reason is not None,
            fallback_reason=heuristic_reason,
        )

        pdf_bytes = await anyio.to_thread.run_sync(self._read_pdf, record)
        scorecard = compute_scorecard(
            extraction,
            compliance,
            text,
            enforce_ustg_check=enforce_ustg,
            pdf_bytes=pdf_bytes,
            einvoice=einvoice,
            structured=provider == STRUCTURED_PROVIDER,
        )

        updated = await self._repository.save_results(
            record.id,
            model=model,
            extraction=extraction.model_dump(mode="json"),
            compliance=compliance.model_dump(mode="json"),
            scorecard=scorecard.model_dump(mode="json"),
            provider=provider,
        )

        entry_id: str | None = None
        if self._ledger is not None:
            entry = await self._ledger.append(
                event_type=AuditEventType.ANALYSIS,
                document_id=record.id,
                sha256_hash=record.sha256,
                model_name=model,
                prompt_hash=PROMPT_HASH,
                result_summary=(f"{HEURISTIC_LABEL} | " if heuristic_reason else "")
                + analysis_summary(scorecard, compliance),
                compliance_score=scorecard.score,
                risk_tier=ai_act.overall_risk_level.value,
                details={
                    "doc_type": extraction.doc_type.value,
                    "provider": provider,
                    "score_band": scorecard.band.value,
                    "ruleset_version": scorecard.ruleset_version,
                    **({"einvoice_parser": einvoice.parser_version} if einvoice is not None else {}),
                    "pii_findings": len(masked),
                    "privacy_gateway": vault_report,
                    **({"failover": failover} if failover else {}),
                    **(ledger_details or {}),
                },
            )
            entry_id = entry.entry_id
        self._progress.clear(record.id)
        logger.info(
            "Dokument %s ausgewertet: %s | Score %s | %s",
            record.id,
            extraction.doc_type.value,
            scorecard.score,
            compliance.headline,
            extra={"document_id": record.id, "provider": provider, "score": scorecard.score},
        )
        return ExtractionOutcome(
            record=updated,
            extraction=extraction,
            compliance=compliance,
            duration_ms=duration_ms,
            scorecard=scorecard,
            provider=provider,
            audit_entry_id=entry_id,
        )

    async def apply_reference_audit(self, record: DocumentRecord) -> ExtractionOutcome:
        """Wendet das hinterlegte Referenz-Audit eines Musterdokuments an (ohne Inferenz)."""
        from app.demo import REFERENCE_AUDITS, REFERENCE_MODEL, REFERENCE_PROVIDER

        fixture = REFERENCE_AUDITS.get(record.original_filename)
        if fixture is None:
            raise ServiceError(f"Für '{record.original_filename}' ist kein Referenz-Audit hinterlegt.")
        enforce_ustg, escalate = self._flags()
        extraction = augment_extraction_issues(ExtractionResult.model_validate(fixture["extraction"]))
        audit_payload = ComplianceAuditPayload.model_validate(fixture["audit"])
        return await self._finalize_analysis(
            record,
            extraction=extraction,
            audit_payload=audit_payload,
            rule_findings=scan_text(record.raw_text or ""),
            model=REFERENCE_MODEL,
            provider=REFERENCE_PROVIDER,
            vault_report=None,
            duration_ms=0,
            audit_ms=0,
            enforce_ustg=enforce_ustg,
            escalate=escalate,
            einvoice=parse_einvoice(record),
            ledger_details={
                "reference_audit": True,
                "note": "Vorberechnete Modellantwort (Musterdaten), keine Inferenz.",
            },
        )

    # --- Demo-Daten ---------------------------------------------------------
    async def seed_demo(self, only: str | None = None) -> list[dict[str, object]]:
        """Legt die vier Musterdokumente an und analysiert sie ohne Sprachmodell.

        Die drei PDF-Musterdokumente erhalten Referenz-Audits (vorberechnete
        Modellantwort aus ``app/demo.py``, Score, Maskierung und Ledger aus dem
        echten Regelwerk).  Die hybride ZUGFeRD-Rechnung braucht keine
        Vorberechnung: Sie läuft über den deterministischen XML-Pfad.
        Idempotent über die SHA-256: Vorhandene Dokumente werden nur
        analysiert, wenn sie es noch nicht sind - ein späteres Live-Audit wird
        nie überschrieben.  Die gültige Rechnung erhält zusätzlich ein
        ausdrücklich als Demo gekennzeichnetes Siegel.
        """
        from app.demo import DEMO_AUDITOR, DEMO_SEAL_NOTE, REFERENCE_AUDITS, demo_documents

        documents = demo_documents()
        if only is not None:
            documents = [(name, data) for name, data in documents if name == only]
            if not documents:
                raise DocumentNotFoundError(f"Unbekannter Musterbeleg '{only}'.")
        results: list[dict[str, object]] = []
        for filename, data in documents:
            record = await self._repository.get_by_sha256(compute_sha256(data))
            created = record is None
            if record is None:
                record, _ = await self.ingest(filename=filename, content_type="application/pdf", data=data)
            audited = structured = False
            if record.status != DocumentStatus.EXTRACTED.value:
                if filename in REFERENCE_AUDITS:
                    outcome = await self.apply_reference_audit(record)
                    audited = True
                else:
                    # E-Rechnung: echter, deterministischer Lauf über den XML-Datensatz.
                    outcome = await self.extract_and_audit(record)
                    structured = outcome.provider == STRUCTURED_PROVIDER
                record = outcome.record
                if filename == "Rechnung_Gueltig_14UStG.pdf":
                    record = await self.sign_off(
                        record,
                        SignOffRequest(auditor_name=DEMO_AUDITOR, note=DEMO_SEAL_NOTE),
                    )
            results.append(
                {
                    "id": record.id,
                    "filename": record.original_filename,
                    "status": record.status,
                    "created": created,
                    "reference_audit": audited,
                    "structured_audit": structured,
                    "compliance_score": (record.scorecard or {}).get("score"),
                }
            )
        return results

    # --- Human Oversight (EU AI Act Art. 14) --------------------------------
    async def _record_failure(self, record: DocumentRecord, previous_status: str, exc: BaseException) -> None:
        """Gescheiterte Prüfung: Ein vorhandenes gültiges Ergebnis bleibt Hauptstatus, der Fehler wird Hinweis."""
        message = describe_failure(exc)
        if record.scorecard:
            await self._repository.mark_recheck_failed(record.id, previous_status, message)
        else:
            await self._repository.mark_failed(record.id, message)

    async def sign_off(self, record: DocumentRecord, request: SignOffRequest) -> DocumentRecord:
        """Versiegelt das Prüfergebnis durch eine natürliche Person."""
        if record.status != DocumentStatus.EXTRACTED.value or not record.scorecard:
            raise DocumentNotAnalyzedError(
                f"Dokument {record.id} ist noch nicht analysiert - kein Siegel möglich."
            )
        score = (record.scorecard or {}).get("score")
        entry: LedgerEntry | None = None
        if self._ledger is not None:
            entry = await self._ledger.append(
                event_type=AuditEventType.SIGN_OFF,
                document_id=record.id,
                sha256_hash=record.sha256,
                model_name=record.model or "",
                prompt_hash=PROMPT_HASH,
                result_summary=f"{SIGN_OFF_LABELS[request.decision]} durch {request.auditor_name}",
                # Maschinenlesbar bleibt die Entscheidung in den Details.
                details={"auditor_name": request.auditor_name, "note": request.note[:500],
                         "decision": request.decision.value},
                compliance_score=score,
                risk_tier=((record.compliance or {}).get("ai_act") or {}).get("overall_risk_level", "unknown"),
            )
        sign_off = SignOff(
            status=request.decision,
            auditor_name=request.auditor_name,
            note=request.note,
            sealed_at=utcnow(),
            ledger_entry_id=entry.entry_id if entry else "",
            ledger_entry_hash=entry.entry_hash if entry else "",
            compliance_score=score,
        )
        return await self._repository.save_sign_off(record.id, sign_off.model_dump(mode="json"))

    async def override(self, record: DocumentRecord, request: OverrideRequest) -> DocumentRecord:
        """Übersteuert die EU-AI-Act-Einstufung (Art. 14 Abs. 4 lit. d) und rechnet den Score neu.

        Der Score bleibt deterministisch: Die Prüfperson ändert die Eingabe
        (Risikostufe), nicht das Ergebnis.  Der Ledger-Eintrag ``human_override``
        hält Person, Begründung, Rechtsnorm sowie Score vorher/nachher fest und
        wird Ed25519-signiert.  Ein bestehendes Siegel verliert seinen Gegenstand;
        eine erneute Analyse verwirft den Override (die Historie bleibt im Ledger).
        """
        compliance = parse_compliance(record)
        extraction = parse_extraction(record)
        previous_card = parse_scorecard(record)
        if record.status != DocumentStatus.EXTRACTED.value or compliance is None or extraction is None:
            raise DocumentNotAnalyzedError(f"Dokument {record.id} ist noch nicht analysiert - kein Override möglich.")
        previous_level = compliance.ai_act.overall_risk_level
        if request.risk_level is previous_level:
            raise OverrideWithoutChangeError(
                f"Die Einstufung ist bereits '{previous_level.value}'."
            )

        now = utcnow()
        note = (
            f"Menschliche Übersteuerung am {now:%d.%m.%Y} durch {request.auditor_name} "
            f"({previous_level.value} -> {request.risk_level.value}; {request.legal_basis}): {request.reason}"
        )
        risk_order = (
            AIActRiskLevel.NOT_APPLICABLE,
            AIActRiskLevel.MINIMAL,
            AIActRiskLevel.LIMITED,
            AIActRiskLevel.HIGH,
            AIActRiskLevel.UNACCEPTABLE,
        )
        capped_systems = [
            system.model_copy(update={"risk_level": request.risk_level})
            if risk_order.index(system.risk_level) > risk_order.index(request.risk_level)
            else system
            for system in compliance.ai_act.systems
        ]
        ai_act = compliance.ai_act.model_copy(
            update={
                "overall_risk_level": request.risk_level,
                "systems": capped_systems,
                "reasoning": f"{compliance.ai_act.reasoning}\n{note}".strip()[:2000],
            }
        )
        updated = compliance.model_copy(update={"ai_act": ai_act})
        enforce_ustg, _ = self._flags()
        pdf_bytes = await anyio.to_thread.run_sync(self._read_pdf, record)
        scorecard = compute_scorecard(
            extraction,
            updated,
            record.raw_text or "",
            enforce_ustg_check=enforce_ustg,
            pdf_bytes=pdf_bytes,
            einvoice=parse_einvoice(record),
            structured=record.provider == STRUCTURED_PROVIDER,
        )
        previous_score = previous_card.score if previous_card else None

        entry: LedgerEntry | None = None
        if self._ledger is not None:
            entry = await self._ledger.append(
                event_type=AuditEventType.HUMAN_OVERRIDE,
                document_id=record.id,
                sha256_hash=record.sha256,
                model_name=record.model or "",
                prompt_hash=PROMPT_HASH,
                result_summary=(
                    f"Einstufung {previous_level.value} -> {request.risk_level.value} durch "
                    f"{request.auditor_name}; Score {previous_score} -> {scorecard.score}"
                ),
                compliance_score=scorecard.score,
                risk_tier=request.risk_level.value,
                details={
                    "auditor_name": request.auditor_name,
                    "previous_risk_level": previous_level.value,
                    "new_risk_level": request.risk_level.value,
                    "previous_score": previous_score,
                    "new_score": scorecard.score,
                    "reason": request.reason,
                    "legal_basis": request.legal_basis,
                    "overridden_at": now.isoformat(),
                    "legal_reference": "Art. 14 Abs. 4 lit. d VO (EU) 2024/1689",
                },
            )
        scorecard.human_override = HumanOverride(
            auditor_name=request.auditor_name,
            previous_risk_level=previous_level,
            new_risk_level=request.risk_level,
            previous_score=previous_score,
            new_score=scorecard.score,
            reason=request.reason,
            legal_basis=request.legal_basis,
            overridden_at=now,
            ledger_entry_id=entry.entry_id if entry else "",
            ledger_entry_hash=entry.entry_hash if entry else "",
        )
        logger.info(
            "Dokument %s: Einstufung durch Prüfperson übersteuert (%s -> %s, Score %s -> %s)",
            record.id, previous_level.value, request.risk_level.value, previous_score, scorecard.score,
            extra={"document_id": record.id},
        )
        return await self._repository.save_override(
            record.id,
            compliance=updated.model_dump(mode="json"),
            scorecard=scorecard.model_dump(mode="json"),
        )

    async def set_pinned(self, record: DocumentRecord, pinned: bool) -> DocumentRecord:
        return await self._repository.set_pinned(record.id, pinned)

    async def set_archived(self, record: DocumentRecord, archived: bool) -> DocumentRecord:
        """Blendet einen Beleg aus der Arbeitsliste aus bzw. holt ihn zurück.

        Archivieren löscht nichts (GoBD-Unveränderbarkeit): Beleg, Ergebnis und
        Ledger bleiben vollständig erhalten; der Wechsel selbst wird protokolliert.
        """
        if record.archived == archived:
            return record
        updated = await self._repository.set_archived(record.id, archived)
        if self._ledger is not None:
            await self._ledger.append(
                event_type=AuditEventType.ARCHIVE if archived else AuditEventType.UNARCHIVE,
                document_id=record.id,
                sha256_hash=record.sha256,
                model_name=record.model or "",
                prompt_hash=PROMPT_HASH,
                result_summary="Beleg archiviert" if archived else "Beleg aus dem Archiv geholt",
                compliance_score=(record.scorecard or {}).get("score"),
                risk_tier=((record.compliance or {}).get("ai_act") or {}).get("overall_risk_level", "unknown"),
                details={"archived": archived},
            )
        return updated

    def progress_of(self, record: DocumentRecord) -> dict[str, object]:
        stage = self._progress.get(record.id)
        keys = [key for key, _ in PIPELINE_STAGES]
        if record.status == DocumentStatus.EXTRACTED.value and stage is None:
            index = len(keys)
        elif stage in keys:
            index = keys.index(stage)
        else:
            index = -1
        return {
            "document_id": record.id,
            "status": record.status,
            "current_stage": stage,
            "stages": [
                {
                    "key": key,
                    "label": label,
                    "state": "done" if i < index else "active" if i == index else "pending",
                }
                for i, (key, label) in enumerate(PIPELINE_STAGES)
            ],
        }

    # --- Compliance Copilot -------------------------------------------------
    async def copilot(
        self,
        record: DocumentRecord,
        question: str,
        history: list[dict[str, str]],
        *,
        thinking: str = "medium",
        lang: str = "de",
        progress_id: str | None = None,
    ) -> dict[str, object]:
        """Beantwortet eine Prüfer-Frage, geerdet auf Dokumenttext und Prüfergebnis.

        ``progress_id`` meldet die Arbeitsschritte live (``GET /api/v1/copilot/progress/{id}``),
        inklusive Neuversuch und Wechsel auf ein Ausweichmodell.  Fällt die ganze
        Kaskade aus, antwortet das Regelwerk aus dem gespeicherten Prüfergebnis.
        """
        steps = COPILOT_STEPS
        steps.step(progress_id, "Belegstellen und Prüfergebnis aufbereiten")
        steps.register_task(progress_id, asyncio.current_task())
        try:
            if not record.raw_text:
                raise NoTextAvailableError(f"Zum Dokument {record.id} liegt kein Text vor.")

            # Musterdokumente mit Referenz-Audit: Standardfragen ohne Sprachmodell.
            from app.demo import REFERENCE_PROVIDER, hybrid_demo_sha256, reference_answer

            is_demo_einvoice = record.provider == STRUCTURED_PROVIDER and record.sha256 == hybrid_demo_sha256()
            if record.provider == REFERENCE_PROVIDER or is_demo_einvoice:
                answer = reference_answer(record.original_filename, question, lang=lang)
                if answer is not None:
                    return {"answer": answer, "model": "reference-answer", "provider": REFERENCE_PROVIDER,
                            "duration_ms": 0, "reference": True}

            def on_event(kind: str, info: dict[str, Any]) -> None:
                if kind == "retry":
                    model_name = info.get("model") or "Modell"
                    attempt, total = info.get("attempt"), info.get("total")
                    if info.get("reason_code") == "provider_unavailable":
                        steps.step(
                            progress_id,
                            f"{model_name} ausgelastet – automatischer Neuversuch ({attempt}/{total})…",
                        )
                    else:
                        steps.step(
                            progress_id,
                            f"{model_name} antwortet nicht rechtzeitig – Neuversuch ({attempt}/{total})…",
                        )
                elif kind == "switch":
                    to_label = STAGE_LABELS.get(str(info.get("to_stage")), "Ausweich-Stufe")
                    steps.step(progress_id, f"Wechsle auf {to_label}: {info.get('to_model')}…")

            client = self._acquire_client(on_event)
            grounding = build_copilot_grounding(record, self._settings.max_prompt_chars)
            messages = [
                *[
                    {"role": turn["role"], "content": turn["content"][:2000]}
                    for turn in history[-8:]
                    if turn.get("role") in {"user", "assistant"} and turn.get("content")
                ],
                {"role": "user", "content": f"{grounding}\n\nFRAGE DES PRÜFERS:\n{question.strip()}"},
            ]
            vault = _vault_of(client)
            cloud_primary = getattr(client, "provider", "local") != "local"
            if vault is not None and cloud_primary:
                steps.step(progress_id, "Personenbezogene Daten pseudonymisieren (Privacy Vault)")
            steps.step(progress_id, f"{client.model} prüft Belegstellen und Rechtsnormen")
            lang_hint = (
                "\n\nLANGUAGE: Respond concisely in professional English. Keep German/EU statutory citations (e.g. § 14 UStG, EN 16931, EU AI Act) and [Z. n] line citations intact."
                if lang == "en"
                else "\n\nIDIOMA: Responde de forma concisa y precisa en español profesional. Conserva exactamente las referencias normativas (p. ej. § 14 UStG, EN 16931, Reglamento de IA) y las citas [Z. n]."
                if lang == "es"
                else ""
            )
            system_prompt = COPILOT_SYSTEM_PROMPT + THINKING_INSTRUCTIONS.get(thinking, "") + lang_hint
            try:
                answer, duration_ms = await client.chat_text(system_prompt=system_prompt, messages=messages)
            except asyncio.CancelledError:
                if vault is not None:
                    vault.clear()
                raise
            except LLMError as exc:
                if vault is not None:
                    vault.clear()
                if not (is_failover_error(exc) and self.heuristic_fallback):
                    raise
                steps.step(progress_id, "Regelwerk antwortet (KI nicht verfügbar)")
                return {
                    "answer": heuristic_copilot_answer(record, question, describe_failure(exc), lang=lang),
                    "model": HEURISTIC_MODEL, "provider": HEURISTIC_PROVIDER, "duration_ms": 0,
                    "reference": False, "heuristic": True,
                    "failover": list(getattr(client, "switches", None) or []) or None,
                    "notice": HEURISTIC_LABEL,
                }
            switches = list(getattr(client, "switches", None) or [])
            used_cloud = getattr(client, "provider", "local") != "local"
            if vault is not None:
                if used_cloud:
                    steps.step(progress_id, "Antwort re-identifizieren")
                vault.clear()
            steps.step(progress_id, "Antwort formulieren")
            return {
                "answer": answer, "model": client.model, "provider": getattr(client, "provider", "local"),
                "duration_ms": duration_ms, "reference": False, "heuristic": False,
                "failover": switches or None,
                "notice": f"Ausweichmodell {client.model} hat geantwortet." if switches else None,
            }
        finally:
            steps.finish(progress_id)

    # --- Kennzahlen ---------------------------------------------------------
    async def kpis(self) -> dict[str, object]:
        if hasattr(self._repository, "kpi_rows"):
            rows = await self._repository.kpi_rows()
        else:
            records = await self._repository.list_all()
            rows = [
                {
                    "status": r.status,
                    "scorecard": r.scorecard,
                    "compliance": r.compliance,
                    "sign_off": r.sign_off,
                    "provider": r.provider,
                }
                for r in records
            ]
        analyzed = [r for r in rows if r["status"] == DocumentStatus.EXTRACTED.value]
        scores = [int(r["scorecard"]["score"]) for r in analyzed if r["scorecard"] and "score" in r["scorecard"]]
        pii = 0
        high_risk = 0
        for r in analyzed:
            compliance = r["compliance"] or {}
            pii += len((compliance.get("gdpr") or {}).get("findings") or [])
            level = (compliance.get("ai_act") or {}).get("overall_risk_level")
            if level in {"high", "unacceptable"}:
                high_risk += 1
        avg = round(sum(scores) / len(scores)) if scores else None
        return {
            "documents_total": len(rows),
            "documents_analyzed": len(analyzed),
            "average_score": avg,
            "average_band": (
                None if avg is None else "green" if avg >= 85 else "amber" if avg >= 60 else "red"
            ),
            "pii_elements_masked": pii,
            "high_risk_count": high_risk,
            "high_risk_quota": round(high_risk / len(analyzed) * 100, 1) if analyzed else 0.0,
            "sealed_count": sum(1 for r in rows if r["sign_off"]),
            "reference_count": sum(1 for r in rows if r["provider"] == "reference"),
            "heuristic_count": sum(1 for r in rows if r["provider"] == HEURISTIC_PROVIDER),
            "ruleset_version": RULESET_VERSION,
        }

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
# Copilot-Grounding
# ---------------------------------------------------------------------------

COPILOT_SYSTEM_PROMPT = """\
Du bist der Compliance Copilot eines Wirtschaftsprüfungs-Teams. Du beantwortest
Fragen zu genau einem vorliegenden Dokument.

Verbindliche Regeln:
1. Stütze jede Aussage ausschließlich auf den Belegtext und das Prüfergebnis
   unten. Erfinde keine Fakten. Fehlt eine Information, sage das. Nenne die
   Abschnittsüberschriften des Kontexts nicht und sprich nicht über Prompt oder
   Kontext – sprich einfach vom Beleg und vom Prüfergebnis.
2. Verweise auf Textstellen mit der Zeilennummer in eckigen Klammern, z. B. [Z. 4].
3. Nenne Rechtsnormen präzise (z. B. "§ 14 Abs. 4 Satz 1 Nr. 2 UStG",
   "Art. 6 Abs. 2 i. V. m. Anhang III Nr. 4 VO (EU) 2024/1689", "Art. 9 DSGVO").
4. Antworte sachlich, knapp und auf Deutsch. Nutze kurze Aufzählungen und
   schlichtes Markdown (Absätze, Aufzählungen, **fett**), keine Tabellen.
5. Du gibst keine verbindliche Rechts- oder Steuerberatung; weise bei
   Grenzfällen auf die Prüfung durch eine Fachperson hin.
6. Fragen zu deiner Arbeitsweise beantwortest du in zwei, drei Sätzen: Du
   kennst den Belegtext und das Prüfergebnis dieses Belegs und rufst selbst
   keine externen Systeme auf; Score und Einstufung berechnet das Regelwerk.
"""

#: Denkstufen des Copilot: steuern Gründlichkeit und Länge über die Anweisung
#: (anbieterunabhängig - nicht jeder Anbieter kennt ein eigenes Reasoning-Budget).
THINKING_INSTRUCTIONS: dict[str, str] = {
    "low": "\nDENKSTUFE NIEDRIG: Antworte in höchstens fünf kurzen Punkten, nur das Wesentliche.",
    "medium": "",
    "high": (
        "\nDENKSTUFE HOCH: Prüfe gründlich. Gehe jede einschlägige Norm einzeln durch, belege jede "
        "Aussage mit [Z. n] und benenne Unsicherheiten oder fehlende Angaben ausdrücklich."
    ),
}


class StepTracker:
    """Live-Arbeitsschritte je Copilot-Anfrage (die letzten 20, älter als 15 Minuten fallen weg)."""

    MAX_AGE_SECONDS = 900
    MAX_ITEMS = 256

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._cancelled: set[str] = set()

    def _prune(self, now: float) -> None:
        for key in [key for key, item in self._items.items() if now - item["at"] > self.MAX_AGE_SECONDS]:
            self._items.pop(key, None)
            self._tasks.pop(key, None)
            self._cancelled.discard(key)
        if len(self._items) > self.MAX_ITEMS:
            oldest = sorted(self._items.items(), key=lambda pair: pair[1]["at"])
            for key, _ in oldest[: len(self._items) - self.MAX_ITEMS]:
                if key not in self._tasks:
                    self._items.pop(key, None)
                    self._cancelled.discard(key)
        if len(self._cancelled) > self.MAX_ITEMS:
            self._cancelled = set(list(self._cancelled)[-self.MAX_ITEMS :])

    def register_task(self, progress_id: str | None, task: asyncio.Task[Any] | None) -> None:
        """Verknüpft die laufende Coroutine mit ``progress_id`` für den gezielten Abbruch."""
        if not progress_id or task is None:
            return
        self._prune(time.time())
        if progress_id in self._cancelled:
            task.cancel()
            return
        self._tasks[progress_id] = task

    def cancel(self, progress_id: str) -> bool:
        """Markiert eine bekannte Anfrage als abgebrochen und beendet einen laufenden Task."""
        now = time.time()
        self._prune(now)
        task = self._tasks.pop(progress_id, None)
        had_item = progress_id in self._items
        if not had_item and task is None:
            return False
        self._cancelled.add(progress_id)
        item = self._items.setdefault(
            progress_id, {"steps": [], "at": now, "started": now, "done": True, "cancelled": True}
        )
        if not item["steps"] or item["steps"][-1] != "Abgebrochen":
            item["steps"] = (item["steps"] + ["Abgebrochen"])[-20:]
        item["at"] = now
        item["done"] = True
        item["cancelled"] = True
        if task is not None and not task.done():
            task.cancel()
            return True
        return had_item

    def step(self, progress_id: str | None, text: str) -> None:
        if not progress_id:
            return
        now = time.time()
        self._prune(now)
        item = self._items.setdefault(
            progress_id, {"steps": [], "at": now, "started": now, "done": False, "cancelled": False}
        )
        if not item["steps"] or item["steps"][-1] != text:
            item["steps"] = (item["steps"] + [text])[-20:]
        item["at"] = now

    def finish(self, progress_id: str | None) -> None:
        if progress_id:
            self._tasks.pop(progress_id, None)
            self._cancelled.discard(progress_id)
            if progress_id in self._items:
                self._items[progress_id]["done"] = True

    def get(self, progress_id: str) -> dict[str, Any]:
        item = self._items.get(progress_id)
        if item is None:
            return {"current": None, "steps": [], "done": False, "cancelled": False, "started_at": None}
        return {
            "current": item["steps"][-1] if item["steps"] else None,
            "steps": list(item["steps"]),
            "done": bool(item["done"]),
            "cancelled": bool(item.get("cancelled", False)),
            "started_at": item["started"],
        }


COPILOT_STEPS = StepTracker()


def build_copilot_grounding(record: DocumentRecord, max_chars: int) -> str:
    """Nummerierter Dokumenttext plus kompaktes Prüfergebnis als Kontext."""
    lines = (record.raw_text or "").splitlines()
    numbered: list[str] = []
    used = 0
    for index, line in enumerate(lines, start=1):
        entry = f"[Z. {index}] {line}"
        if used + len(entry) > max_chars:
            numbered.append(f"[... {len(lines) - index + 1} weitere Zeilen ausgelassen ...]")
            break
        numbered.append(entry)
        used += len(entry) + 1

    scorecard = record.scorecard or {}
    open_points = [
        f"- {check.get('label')}: {check.get('detail') or check.get('status')} ({check.get('legal_reference') or ''})"
        for tile in scorecard.get("tiles", [])
        for check in tile.get("checks", [])
        if check.get("status") in {"fail", "warn"}
    ]
    compliance = record.compliance or {}
    ai_act = compliance.get("ai_act") or {}
    extraction = record.extraction or {}
    summary = {
        "doc_type": extraction.get("doc_type"),
        "aussteller": extraction.get("sender"),
        "rechnungsnummer": extraction.get("document_number"),
        "brutto": extraction.get("total_amount"),
        "netto": extraction.get("net_amount"),
        "steuersatz": extraction.get("tax_rate"),
        "steuerbetrag": extraction.get("tax_amount"),
        "compliance_score": scorecard.get("score"),
        "freigabeempfehlung": scorecard.get("release_recommendation"),
        "ai_act_risikostufe": ai_act.get("overall_risk_level"),
        "ai_act_begruendung": ai_act.get("reasoning"),
        "anhang_iii": sorted(
            {label for system in ai_act.get("systems", []) for label in system.get("annex_iii_labels", [])}
        ),
        "dsgvo_risiko": (compliance.get("gdpr") or {}).get("risk_level"),
    }
    return (
        "=== BELEGTEXT (Zeilen nummeriert) ===\n" + "\n".join(numbered)
        + "\n=== PRÜFERGEBNIS (feste Regeln und KI-Audit) ===\n"
        + json.dumps(summary, ensure_ascii=False, default=str, indent=1)
        + "\nOffene Prüfpunkte:\n" + ("\n".join(open_points) or "- keine")
    )


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
    """Erzeugt eine Zeile der tabellarischen Übersicht."""
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
        document_number=extraction.document_number if extraction else None,
        document_date=extraction.document_date if extraction else None,
        total_amount=extraction.total_amount if extraction else None,
        currency=extraction.currency if extraction else None,
        ai_act_risk_level=compliance.ai_act.overall_risk_level if compliance else None,
        gdpr_risk_level=compliance.gdpr.risk_level if compliance else None,
        contains_special_categories=(
            compliance.gdpr.contains_special_categories if compliance else None
        ),
        compliance_score=(record.scorecard or {}).get("score"),
        score_band=presented_band(record.scorecard)[0],
        pii_findings=len(compliance.gdpr.findings) if compliance else None,
        sealed=bool(record.sign_off),
        pinned=record.pinned,
        archived=record.archived,
        provider=record.provider,
        einvoice_profile=(record.einvoice or {}).get("profile") if not (record.einvoice or {}).get("error") else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def parse_scorecard(record: DocumentRecord) -> Scorecard | None:
    if not record.scorecard:
        return None
    try:
        return Scorecard.model_validate(record.scorecard)
    except Exception:  # noqa: BLE001
        logger.warning("Scorecard von Dokument %s ist nicht lesbar.", record.id, exc_info=True)
        return None


def parse_sign_off(record: DocumentRecord) -> SignOff | None:
    if not record.sign_off:
        return None
    try:
        return SignOff.model_validate(record.sign_off)
    except Exception:  # noqa: BLE001
        return None


def to_detail(record: DocumentRecord, *, pii_level: str = "standard") -> DocumentDetail:
    """Erzeugt die Detailansicht inklusive Compliance-Audit.

    Textvorschau und Textansicht werden gemäß der aktiven PII-Strenge
    geschwärzt; der Rohtext verlässt die API nie ungefiltert, außer im
    ausdrücklich gewählten Modus ``audit_only``.
    """
    compliance = parse_compliance(record)
    preview: str | None = None
    text_view = None
    if record.raw_text:
        text_view = build_text_view(
            record.raw_text, pii_level, compliance.gdpr.findings if compliance else ()
        )
        redacted = str(text_view["text"])
        preview = redacted[:TEXT_PREVIEW_CHARS]
        if len(redacted) > TEXT_PREVIEW_CHARS:
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
        compliance=compliance,
        text_preview=preview,
        scorecard=parse_scorecard(record),
        sign_off=parse_sign_off(record),
        text_view=text_view,
        einvoice=parse_einvoice(record),
        pinned=record.pinned,
        archived=record.archived,
        archived_at=record.archived_at,
        provider=record.provider,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        extracted_at=record.extracted_at,
    )
