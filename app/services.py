"""Fachlogik: Ingestion, Extraktion, Compliance-Audit und Mapping.

Diese Schicht kennt weder FastAPI noch SQLAlchemy - sie arbeitet gegen das
``DocumentRepository``-Protocol und den ``InferenceRouter`` (bzw. direkt
einen ``StructuredLLMClient``).  Dadurch ist sie
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
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

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
from app.extractors.einvoice import looks_like_xml
from app.llm import PROMPT_HASH, ComplianceAuditPayload, StructuredLLMClient
from app.pdf_reader import PdfExtraction, extract_text_async
from app.privacy_vault import VaultedClient
from app.redaction import build_text_view, enforce_masking, merge_findings, scan_text
from app.runtime_settings import RuntimeSettingsStore
from app.scoring import RULESET_VERSION, compute_scorecard
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
    Scorecard,
    SignOff,
    SignOffRequest,
    iban_checksum_valid,
)

logger = logging.getLogger(__name__)

#: Erlaubte Dateiendungen und MIME-Typen fuer den Upload (je Endung).
ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf", "application/octet-stream"})
XML_CONTENT_TYPES = frozenset({"application/xml", "text/xml", "application/octet-stream"})
ALLOWED_SUFFIXES = frozenset({".pdf", ".xml"})

#: Kennung des deterministischen E-Rechnungs-Pfads in Datenbank, Ledger und UI.
STRUCTURED_MODEL = "en16931-parser"
STRUCTURED_PROVIDER = "structured"

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


class DocumentNotAnalyzedError(ServiceError):
    """Aktion setzt eine abgeschlossene Analyse voraus."""

    code = "document_not_analyzed"
    status_code = 409
    hint = "Zuerst POST /documents/{id}/extract ausfuehren."


class InvalidEInvoiceUploadError(UploadValidationError):
    """Reiner XML-Upload ist keine auswertbare EN-16931-Rechnung."""

    code = "invalid_einvoice"
    status_code = 422
    hint = "Erwartet wird eine XRechnung bzw. ein ZUGFeRD-/Factur-X-Datensatz (CII oder UBL)."


class OriginalMissingError(ServiceError):
    """Die Originaldatei fehlt im Ablageverzeichnis."""

    code = "original_missing"
    status_code = 410
    hint = "Ablageverzeichnis (UPLOAD_DIR) und Datensicherung pruefen; das Dokument erneut hochladen."


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
# E-Rechnung (EN 16931)
# ---------------------------------------------------------------------------


def read_embedded_einvoice(pdf_bytes: bytes, visual_text: str) -> EInvoiceData | None:
    """Liest den eingebetteten XML-Datensatz einer hybriden Rechnung (falls vorhanden).

    Ein defektes oder nicht unterstuetztes XML verhindert den Upload nicht: Es
    wird mit ``error`` vermerkt, und das Dokument laeuft ueber die Textanalyse.
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
    """XML ist massgeblich, wenn es auswertbar ist und - bei hybriden Rechnungen - ein
    E-Rechnungs-Profil traegt.  MINIMUM/BASIC WL sind keine E-Rechnungen: Dort ist
    der Bildteil die Rechnung, und die Analyse laeuft ueber den Text."""
    if einvoice is None or einvoice.error:
        return False
    return einvoice.source == "standalone" or einvoice.is_einvoice


# ---------------------------------------------------------------------------
# Fortschritt der Pipeline (fuer den Live-Audit-Stepper im Frontend)
# ---------------------------------------------------------------------------

#: Reihenfolge der echten Verarbeitungsschritte in ``extract_and_audit``.
PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("text_check", "Text-Layer & PDF-Check"),
    ("pii_scan", "PII-Scanner & DSGVO-Maskierung"),
    ("ustg_check", "§ 14 UStG Rechnungsprüfung"),
    ("ai_act", "EU AI Act Risikobewertung"),
)


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


PROGRESS = ProgressTracker()


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
    scorecard: Scorecard | None = None
    provider: str = "local"
    audit_entry_id: str | None = None


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
    def _acquire_client(self) -> StructuredLLMClient:
        acquire = getattr(self._llm, "acquire", None)
        return acquire() if callable(acquire) else self._llm  # type: ignore[return-value]

    @property
    def pii_level(self) -> str:
        if self._runtime is not None:
            return self._runtime.snapshot().pii_strictness.value
        return self._settings.pii_strictness

    def _flags(self) -> tuple[bool, bool]:
        """(Paragraf-14-Pruefung erzwingen, AI-Act-Eskalation aktiv)."""
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
        """Originalbeleg bitgenau; die Pruefsumme muss zur Datenbank passen."""
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
        """Eingebetteter E-Rechnungs-Datensatz einer hybriden Rechnung (fuer das Pruefpaket)."""
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
        Factur-X, XRechnung) untersucht; reine XML-Dateien muessen eine
        EN-16931-Rechnung in CII- oder UBL-Syntax sein.

        Returns:
            Das angelegte Dokument und - falls vorhanden - die ID eines bereits
            gespeicherten Dokuments mit identischer Pruefsumme.
        """
        safe_name = sanitize_filename(filename)
        suffix = Path(safe_name).suffix.lower()

        if suffix not in ALLOWED_SUFFIXES:
            raise UploadValidationError(
                f"Nicht unterstuetzte Dateiendung '{suffix or '(keine)'}'. Erlaubt sind .pdf und .xml."
            )
        allowed_types = XML_CONTENT_TYPES if suffix == ".xml" else ALLOWED_CONTENT_TYPES
        if content_type and content_type.split(";")[0].strip() not in allowed_types:
            expected = "application/xml" if suffix == ".xml" else "application/pdf"
            raise UploadValidationError(
                f"Nicht unterstuetzter Content-Type '{content_type}'. Erwartet wird {expected}."
            )
        if not data:
            raise UploadValidationError("Die hochgeladene Datei ist leer.")
        if len(data) > self._settings.max_upload_bytes:
            raise UploadTooLargeError(
                f"Die Datei ist {len(data) / 1_048_576:.1f} MB gross; erlaubt sind "
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

    # --- Extraktion & Audit ------------------------------------------------
    async def extract_and_audit(self, record: DocumentRecord) -> ExtractionOutcome:
        """Vier echte Pipeline-Stufen; jede Stufe meldet sich im ProgressTracker.

        1. Text-Layer-Pruefung
        2. Regelbasierter PII-Scan; bei Cloud-Inferenz Pseudonymisierung im Vault
        3. LLM-Extraktion + Paragraf-14-Kontrollen
        4. LLM-Audit (EU AI Act, DSGVO), Eskalationsregeln, Scorecard, Ledger
        """
        progress = self._progress
        progress.set(record.id, "text_check")
        text = record.raw_text or ""
        if len(text.strip()) < 1:
            progress.clear(record.id)
            raise NoTextAvailableError(
                f"Zum Dokument {record.id} ist kein extrahierter Text gespeichert."
            )

        einvoice = parse_einvoice(record)
        if uses_structured_path(einvoice):
            return await self._structured_analysis(record, einvoice)  # type: ignore[arg-type]

        prompt_text = _truncate_for_prompt(text, self._settings.max_prompt_chars)
        enforce_ustg, escalate = self._flags()

        try:
            client = self._acquire_client()
        except Exception:
            progress.clear(record.id)
            raise
        await self._repository.mark_processing(record.id)

        try:
            progress.set(record.id, "pii_scan")
            rule_findings = scan_text(text)
            if isinstance(client, VaultedClient):
                # Mapping vorab aufbauen: gleiche Platzhalter fuer beide LLM-Aufrufe.
                client.vault.pseudonymize(prompt_text)

            progress.set(record.id, "ustg_check")
            extraction, extraction_ms = await client.extract_document(prompt_text)
            extraction = augment_extraction_issues(extraction)

            progress.set(record.id, "ai_act")
            audit_payload, audit_ms = await client.audit_document(prompt_text)
        except Exception as exc:
            await self._repository.mark_failed(record.id, f"{type(exc).__name__}: {exc}")
            progress.clear(record.id)
            raise

        provider = getattr(client, "provider", "local")
        vault_report = client.vault.report if isinstance(client, VaultedClient) else None
        if isinstance(client, VaultedClient):
            client.vault.clear()
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
        )

    async def _structured_analysis(self, record: DocumentRecord, einvoice: EInvoiceData) -> ExtractionOutcome:
        """Deterministischer Pfad fuer E-Rechnungen: XML ist massgeblich, kein Sprachmodell.

        Die Rechnungsdaten stammen vollstaendig aus dem EN-16931-Datensatz; der
        DSGVO-Teil beruht auf dem Regex-Scanner.  Eine KI-Einstufung nach dem
        AI Act findet nicht statt - eine Rechnung begruendet keine Anbieter-
        oder Betreiberpflichten; massgeblich ist der zugrunde liegende Vertrag.
        """
        progress = self._progress
        enforce_ustg, escalate = self._flags()
        await self._repository.mark_processing(record.id)
        try:
            progress.set(record.id, "pii_scan")
            rule_findings = scan_text(record.raw_text or "")
            progress.set(record.id, "ustg_check")
            extraction = augment_extraction_issues(to_extraction(einvoice))
            progress.set(record.id, "ai_act")
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
        except Exception as exc:
            await self._repository.mark_failed(record.id, f"{type(exc).__name__}: {exc}")
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
    ) -> ExtractionOutcome:
        """Gemeinsamer Abschluss fuer Live- und Referenz-Audits.

        Maskierungszwang, Regex-Zweitmeinung, Eskalationsregeln, Scorecard und
        Ledger-Eintrag sind fuer beide Wege identisch - nur die Herkunft der
        Modellantwort unterscheidet sich.
        """
        # Deterministische Gegenprobe auf dem vollstaendigen Text.  Die
        # Maskierung laeuft vor dem Zusammenfuehren: nur so treffen sich ein
        # vom Modell im Klartext gemeldeter Wert und derselbe, vom
        # Regelscanner bereits maskierte Wert im selben Deduplizierungs-
        # schluessel und werden als ein Treffer (source="both") erkannt.
        text = record.raw_text or ""
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
                result_summary=f"{scorecard.release_recommendation} | {compliance.headline}",
                compliance_score=scorecard.score,
                risk_tier=ai_act.overall_risk_level.value,
                details={
                    "doc_type": extraction.doc_type.value,
                    "provider": provider,
                    "score_band": scorecard.band.value,
                    "ruleset_version": scorecard.ruleset_version,
                    "pii_findings": len(masked),
                    "privacy_gateway": vault_report,
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
    async def seed_demo(self) -> list[dict[str, object]]:
        """Legt die vier Musterdokumente an und analysiert sie ohne Sprachmodell.

        Die drei PDF-Musterdokumente erhalten Referenz-Audits (vorberechnete
        Modellantwort aus ``app/demo.py``, Score, Maskierung und Ledger aus dem
        echten Regelwerk).  Die hybride ZUGFeRD-Rechnung braucht keine
        Vorberechnung: Sie laeuft ueber den deterministischen XML-Pfad.
        Idempotent ueber die SHA-256: Vorhandene Dokumente werden nur
        analysiert, wenn sie es noch nicht sind - ein spaeteres Live-Audit wird
        nie ueberschrieben.  Die gueltige Rechnung erhaelt zusaetzlich ein
        ausdruecklich als Demo gekennzeichnetes Siegel.
        """
        from app.demo import DEMO_AUDITOR, DEMO_SEAL_NOTE, REFERENCE_AUDITS, demo_documents

        results: list[dict[str, object]] = []
        for filename, data in demo_documents():
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
                    # E-Rechnung: echter, deterministischer Lauf ueber den XML-Datensatz.
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
    async def sign_off(self, record: DocumentRecord, request: SignOffRequest) -> DocumentRecord:
        """Versiegelt das Pruefergebnis durch eine natuerliche Person."""
        if record.status != DocumentStatus.EXTRACTED.value or not record.scorecard:
            raise DocumentNotAnalyzedError(
                f"Dokument {record.id} ist noch nicht analysiert - kein Siegel moeglich."
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
                result_summary=f"{request.decision.value} durch {request.auditor_name}",
                compliance_score=score,
                risk_tier=((record.compliance or {}).get("ai_act") or {}).get("overall_risk_level", "unknown"),
                details={"auditor_name": request.auditor_name, "note": request.note[:500]},
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

    async def set_pinned(self, record: DocumentRecord, pinned: bool) -> DocumentRecord:
        return await self._repository.set_pinned(record.id, pinned)

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
        self, record: DocumentRecord, question: str, history: list[dict[str, str]]
    ) -> dict[str, object]:
        """Beantwortet eine Pruefer-Frage, geerdet auf Dokumenttext und Pruefergebnis."""
        if not record.raw_text:
            raise NoTextAvailableError(f"Zum Dokument {record.id} liegt kein Text vor.")

        # Musterdokumente mit Referenz-Audit: Standardfragen ohne Sprachmodell.
        from app.demo import REFERENCE_PROVIDER, hybrid_demo_sha256, reference_answer

        is_demo_einvoice = record.provider == STRUCTURED_PROVIDER and record.sha256 == hybrid_demo_sha256()
        if record.provider == REFERENCE_PROVIDER or is_demo_einvoice:
            answer = reference_answer(record.original_filename, question)
            if answer is not None:
                return {"answer": answer, "model": "reference-answer", "provider": REFERENCE_PROVIDER,
                        "duration_ms": 0, "reference": True}

        client = self._acquire_client()
        grounding = build_copilot_grounding(record, self._settings.max_prompt_chars)
        messages = [
            *[
                {"role": turn["role"], "content": turn["content"][:2000]}
                for turn in history[-8:]
                if turn.get("role") in {"user", "assistant"} and turn.get("content")
            ],
            {"role": "user", "content": f"{grounding}\n\nFRAGE DES PRUEFERS:\n{question.strip()}"},
        ]
        answer, duration_ms = await client.chat_text(system_prompt=COPILOT_SYSTEM_PROMPT, messages=messages)
        provider = getattr(client, "provider", "local")
        if isinstance(client, VaultedClient):
            client.vault.clear()
        return {"answer": answer, "model": client.model, "provider": provider, "duration_ms": duration_ms,
                "reference": False}

    # --- Kennzahlen ---------------------------------------------------------
    async def kpis(self) -> dict[str, object]:
        records = await self._repository.list_all()
        analyzed = [r for r in records if r.status == DocumentStatus.EXTRACTED.value]
        scores = [int(r.scorecard["score"]) for r in analyzed if r.scorecard and "score" in r.scorecard]
        pii = 0
        high_risk = 0
        for r in analyzed:
            compliance = r.compliance or {}
            pii += len((compliance.get("gdpr") or {}).get("findings") or [])
            level = (compliance.get("ai_act") or {}).get("overall_risk_level")
            if level in {"high", "unacceptable"}:
                high_risk += 1
        avg = round(sum(scores) / len(scores)) if scores else None
        return {
            "documents_total": len(records),
            "documents_analyzed": len(analyzed),
            "average_score": avg,
            "average_band": (
                None if avg is None else "green" if avg >= 85 else "amber" if avg >= 60 else "red"
            ),
            "pii_elements_masked": pii,
            "high_risk_count": high_risk,
            "high_risk_quota": round(high_risk / len(analyzed) * 100, 1) if analyzed else 0.0,
            "sealed_count": sum(1 for r in records if r.sign_off),
            "reference_count": sum(1 for r in records if r.provider == "reference"),
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
Du bist der Compliance Copilot eines Wirtschaftspruefungs-Teams. Du beantwortest
Fragen zu genau einem vorliegenden Dokument.

Verbindliche Regeln:
1. Stuetze jede Aussage ausschliesslich auf den DOKUMENTTEXT und das
   PRUEFERGEBNIS unten. Erfinde keine Fakten. Fehlt eine Information, sage das.
2. Verweise auf Textstellen mit der Zeilennummer in eckigen Klammern, z. B. [Z. 4].
3. Nenne Rechtsnormen praezise (z. B. "§ 14 Abs. 4 Satz 1 Nr. 2 UStG",
   "Art. 6 Abs. 2 i. V. m. Anhang III Nr. 4 VO (EU) 2024/1689", "Art. 9 DSGVO").
4. Antworte sachlich, knapp und auf Deutsch. Nutze kurze Aufzaehlungen.
5. Du gibst keine verbindliche Rechts- oder Steuerberatung; weise bei
   Grenzfaellen auf die Pruefung durch eine Fachperson hin.
"""


def build_copilot_grounding(record: DocumentRecord, max_chars: int) -> str:
    """Nummerierter Dokumenttext plus kompaktes Pruefergebnis als Kontext."""
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
        "=== DOKUMENTTEXT ===\n" + "\n".join(numbered)
        + "\n=== PRUEFERGEBNIS (deterministische Regeln + KI-Audit) ===\n"
        + json.dumps(summary, ensure_ascii=False, default=str, indent=1)
        + "\nOffene Pruefpunkte:\n" + ("\n".join(open_points) or "- keine")
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
        compliance_score=(record.scorecard or {}).get("score"),
        score_band=(record.scorecard or {}).get("band"),
        pii_findings=len(compliance.gdpr.findings) if compliance else None,
        sealed=bool(record.sign_off),
        pinned=record.pinned,
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

    Textvorschau und Textansicht werden gemaess der aktiven PII-Strenge
    geschwaerzt; der Rohtext verlaesst die API nie ungefiltert, ausser im
    ausdruecklich gewaehlten Modus ``audit_only``.
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
        provider=record.provider,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        extracted_at=record.extracted_at,
    )
