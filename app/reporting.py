"""Revisionssicheres Audit-Zertifikat in drei Formaten (JSON, Markdown, HTML/A4).

Der Bericht ist eine *Sicht* auf bereits gespeicherte, im Ledger verankerte
Daten - er berechnet nichts neu.  Die Audit-ID ist die ``entry_id`` des
jüngsten Analyse-Eintrags im Hash-Ledger; der Eintrags-Hash steht im Bericht,
sodass ein Prüfer das Zertifikat gegen ``GET /api/audit/trail`` abgleichen kann.

Sicherheit: Alle Werte (auch LLM-Freitexte) werden HTML-escaped; die
HTML-Antwort wird mit einer restriktiven Content-Security-Policy ausgeliefert.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from app.audit_ledger import AuditEventType, ChainVerification, LedgerEntry
from app.config import APP_TITLE, APP_VERSION
from app.db import DocumentRecord, utcnow
from app.redaction import mask_value
from app.schemas import ANNEX_III_LABELS, AnnexIIICategory
from app.services import (
    STRUCTURED_PROVIDER,
    parse_compliance,
    parse_einvoice,
    parse_extraction,
    parse_scorecard,
    parse_sign_off,
)

#: CSP für die HTML-Ausgabe: keine Skripte, keine externen Ressourcen.
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"

_RISK_LABELS = {
    "unacceptable": "Verbotene Praktik (Art. 5)",
    "high": "Hochrisiko (Art. 6 Abs. 2 i. V. m. Anhang III)",
    "limited": "Begrenztes Risiko (Art. 50)",
    "minimal": "Minimales Risiko",
    "not_applicable": "Kein KI-System beschrieben",
}

_RISK_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _RISK_LABELS,
    "en": {
        "unacceptable": "Prohibited Practice (Art. 5)",
        "high": "High Risk (Art. 6(2) w/ Annex III)",
        "limited": "Limited Risk (Art. 50)",
        "minimal": "Minimal Risk",
        "not_applicable": "No AI system described",
    },
    "es": {
        "unacceptable": "Práctica prohibida (Art. 5)",
        "high": "Alto riesgo (Art. 6(2) y Anexo III)",
        "limited": "Riesgo limitado (Art. 50)",
        "minimal": "Riesgo mínimo",
        "not_applicable": "Sin sistema de IA descrito",
    },
}

#: Kennzeichnung vorberechneter Musterdaten-Audits in allen Ausgabeformaten.
REFERENCE_NOTE = (
    "Referenz-Audit der Musterdaten: Die Modellantwort ist vorberechnet (keine KI-Inferenz). "
    "Score, Maskierung, Eskalationsregeln und Hash-Kette stammen aus dem regulären Regelwerk."
)

REFERENCE_NOTE_I18N: dict[str, str] = {
    "de": REFERENCE_NOTE,
    "en": (
        "Reference audit (sample cases): LLM output is precomputed (no live inference). "
        "Score, PII redaction, escalation rules and hash chain come from the deterministic ruleset."
    ),
    "es": (
        "Auditoría de referencia (casos de ejemplo): la respuesta IA está precalculada. "
        "Puntuación, anonimización, escalado y cadena de hash proceden del motor determinista."
    ),
}

#: Kennzeichnung des deterministischen E-Rechnungs-Pfads.
STRUCTURED_NOTE = (
    "Strukturierte E-Rechnung: Rechnungsdaten deterministisch aus dem EN-16931-Datensatz gelesen, "
    "keine KI-Inferenz. Bei hybriden Rechnungen ist der XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36)."
)

STRUCTURED_NOTE_I18N: dict[str, str] = {
    "de": STRUCTURED_NOTE,
    "en": (
        "Structured E-Invoice: invoice data parsed deterministically from EN 16931 XML without AI inference. "
        "For hybrid invoices, the XML dataset prevails (German BMF decree 15 Oct 2024, para. 36)."
    ),
    "es": (
        "Factura electrónica estructurada: datos leídos de forma determinista del XML EN 16931 sin IA. "
        "En facturas híbridas prevalece el conjunto XML (circular BMF 15/10/2024, Rz. 36)."
    ),
}

_SOURCE_LABELS = {
    "llm": "KI-Modell",
    "rule_based": "Regelwerk",
    "both": "KI + Regelwerk",
    "xml": "XML-Datensatz",
    "xml_rule": "XML + Regelwerk",
}

_SOURCE_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _SOURCE_LABELS,
    "en": {"llm": "AI Model", "rule_based": "Ruleset", "both": "AI + Ruleset", "xml": "XML Dataset", "xml_rule": "XML + Ruleset"},
    "es": {"llm": "Modelo IA", "rule_based": "Reglamento", "both": "IA + Reglamento", "xml": "Conjunto XML", "xml_rule": "XML + Reglamento"},
}

_VISUAL_LABELS = {"match": "übereinstimmend", "mismatch": "ABWEICHUNG", "not_found": "im Bildteil nicht gefunden"}

_VISUAL_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _VISUAL_LABELS,
    "en": {"match": "matched", "mismatch": "MISMATCH", "not_found": "not found in visual PDF"},
    "es": {"match": "coincide", "mismatch": "DISCREPANCIA", "not_found": "no encontrado en PDF visual"},
}

_EVENT_LABELS = {
    AuditEventType.ANALYSIS: "Analyse",
    AuditEventType.SIGN_OFF: "Prüfer-Siegel",
    AuditEventType.HUMAN_OVERRIDE: "Übersteuerung (Art. 14)",
    AuditEventType.PROVIDER_FAILOVER: "Provider-Wechsel (Ausfall)",
    AuditEventType.ARCHIVE: "Archiviert",
    AuditEventType.UNARCHIVE: "Aus dem Archiv geholt",
}

_EVENT_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _EVENT_LABELS,
    "en": {
        AuditEventType.ANALYSIS: "Audit Analysis",
        AuditEventType.SIGN_OFF: "Auditor Seal",
        AuditEventType.HUMAN_OVERRIDE: "Human Override (Art. 14)",
        AuditEventType.PROVIDER_FAILOVER: "Provider Failover",
        AuditEventType.ARCHIVE: "Archived",
        AuditEventType.UNARCHIVE: "Unarchived",
    },
    "es": {
        AuditEventType.ANALYSIS: "Análisis",
        AuditEventType.SIGN_OFF: "Sello del auditor",
        AuditEventType.HUMAN_OVERRIDE: "Anulación humana (Art. 14)",
        AuditEventType.PROVIDER_FAILOVER: "Cambio de proveedor",
        AuditEventType.ARCHIVE: "Archivado",
        AuditEventType.UNARCHIVE: "Desarchivado",
    },
}


def _fmt_date(value: Any) -> str:
    """ISO-Datum -> 31.12.2034."""
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def _fmt_ts(value: Any) -> str:
    """ISO-Zeitstempel -> "04.10.2026, 01:35:38 UTC" (Rohwert bleibt im JSON erhalten)."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return str(value)
    return parsed.strftime("%d.%m.%Y, %H:%M:%S UTC")


_STATUS_LABELS = {"pass": "Erfüllt", "warn": "Hinweis", "fail": "Mangel", "not_applicable": "n. e."}

_STATUS_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _STATUS_LABELS,
    "en": {"pass": "Pass", "warn": "Notice", "fail": "Defect", "not_applicable": "n/a"},
    "es": {"pass": "Cumple", "warn": "Aviso", "fail": "Defecto", "not_applicable": "n/a"},
}

_ARTICLE_REFS = {
    "high": [
        "Art. 9 Risikomanagementsystem",
        "Art. 10 Daten und Daten-Governance",
        "Art. 11 Technische Dokumentation",
        "Art. 12 Aufzeichnungspflichten (Logging)",
        "Art. 13 Transparenz gegenüber Betreibern",
        "Art. 14 Menschliche Aufsicht",
        "Art. 15 Genauigkeit, Robustheit, Cybersicherheit",
        "Art. 26 Pflichten der Betreiber",
        "Art. 43 Konformitätsbewertung",
    ],
    "limited": ["Art. 50 Transparenzpflichten"],
    "unacceptable": ["Art. 5 Verbotene Praktiken"],
}

_REPORT_TEXT: dict[str, dict[str, str]] = {
    "de": {
        "report_type": "Compliance-Prüfzertifikat",
        "not_analyzed": "Noch nicht analysiert",
        "disclaimer": (
            "Automatisierte Vorprüfung mit deterministischem Regelwerk und KI-Unterstützung. "
            "Ersetzt keine Steuer- oder Rechtsberatung. Maßgeblich ist die Freigabe durch die "
            "verantwortliche Prüfperson (Human Oversight, Art. 14 VO (EU) 2024/1689)."
        ),
        "title_prefix": "Prüfzertifikat",
        "kicker": "Compliance-Prüfzertifikat · VO (EU) 2024/1689 · § 14 UStG · DSGVO",
        "rec": "Freigabeempfehlung",
        "score": "Compliance-Score",
        "doc": "Dokument",
        "model": "Modell",
        "hash_chain": "Ledger-Hash",
        "chain": "Kette",
        "intact": "intakt",
        "broken": "GEBROCHEN",
        "ustg_h": "§ 14 Abs. 4 UStG – Pflichtangaben",
        "col_item": "Merkmal",
        "col_norm": "Norm",
        "col_status": "Status",
        "col_note": "Hinweis",
        "einvoice_h": "E-Rechnung (EN 16931)",
        "bt_val": "Wert",
        "visual_h": "Abgleich XML ↔ PDF-Bildteil",
        "visual_col_res": "Ergebnis",
        "ai_h": "EU AI Act (VO (EU) 2024/1689)",
        "ai_level": "Einstufung",
        "annex3": "Anhang III",
        "reason": "Begründung",
        "articles": "Einschlägige Artikel",
        "articles_html": "Einschlägige Pflichten",
        "math_h": "Mathematische Validität",
        "col_check": "Prüfung",
        "gdpr_h": "DSGVO",
        "gdpr_html": "DSGVO – PII-Befunde (maskiert)",
        "risk": "Risiko",
        "hits": "Treffer",
        "masked_note": "(maskiert)",
        "col_cat": "Kategorie",
        "col_val": "Wert",
        "col_src": "Quelle",
        "col_conf": "Konfidenz",
        "override_h": "Prüfer-Meilenstein · Übersteuerung (Art. 14 Abs. 4 lit. d AI Act)",
        "override_md_h": "Prüfer-Meilenstein: Übersteuerung der KI-Einstufung (Art. 14 Abs. 4 lit. d AI Act)",
        "auditor": "Prüfperson",
        "legal_basis": "Rechtsnorm",
        "ledger_entry": "Ledger-Eintrag",
        "retention": "Aufbewahrung",
        "years": "Jahre",
        "until_at_least": "bis mindestens",
        "fin_sector": "Finanzsektor bis",
        "sign_h": "Prüfvermerk (Human Oversight, Art. 14)",
        "by": "durch",
        "at": "am",
        "note": "Notiz",
        "seal_hash": "Siegel-Hash",
        "unsealed": "Noch nicht versiegelt.",
        "generated": "Erstellt",
        "chain_section": "Dokument & Prüfkette",
        "sha_doc": "SHA-256 Dokument",
        "prev_hash": "Vorgänger-Hash",
        "prompt_hash": "Prompt-Hash",
        "audit_time": "Prüfzeitpunkt",
        "hash_chain_lbl": "Hash-Kette",
        "entries": "Einträge",
        "model_provider": "Modell / Provider",
        "ruleset": "Regelwerk",
        "ledger_h": "Prüfpfad (Ledger)",
        "col_seq": "Seq",
        "col_event": "Ereignis",
        "col_time": "Zeitpunkt",
        "col_person": "Person",
        "col_ehash": "Eintrags-Hash",
        "col_sig": "Signatur",
        "no_checks": "Keine Prüfpunkte.",
        "no_pii": "Keine personenbezogenen Daten erkannt.",
        "no_ledger": "Keine Ledger-Einträge.",
        "embedded_as": "eingebettet als",
        "pure_xml": "reines XML",
        "sha_xml": "SHA-256 XML-Datensatz",
        "spec_bt24": "Spezifikation (BT-24)",
        "milestone_tag": "Prüfer-Meilenstein",
        "ed25519_signed": "Ed25519-signiert",
        "seal_approved": "GEPRÜFT & FREIGEGEBEN",
        "seal_rejected": "GEPRÜFT – FREIGABE VERWEIGERT",
        "auditor_lbl": "Prüfer",
        "sealed_lbl": "Versiegelt",
        "draft_banner": "ENTWURF – noch nicht durch eine Prüfperson versiegelt (Art. 14 EU AI Act)",
    },
    "en": {
        "report_type": "Compliance Audit Certificate",
        "not_analyzed": "Not yet analyzed",
        "disclaimer": (
            "Automated pre-audit with deterministic ruleset and AI assistance. "
            "Not binding legal or tax advice. Final sign-off rests with the responsible human auditor "
            "(Human Oversight, Art. 14 Regulation (EU) 2024/1689)."
        ),
        "title_prefix": "Audit Certificate",
        "kicker": "Compliance Audit Certificate · Reg. (EU) 2024/1689 · Sec. 14 UStG · GDPR",
        "rec": "Release Recommendation",
        "score": "Compliance Score",
        "doc": "Document",
        "model": "Model",
        "hash_chain": "Ledger Hash",
        "chain": "Chain",
        "intact": "intact",
        "broken": "BROKEN",
        "ustg_h": "Sec. 14(4) UStG – Mandatory Invoice Elements",
        "col_item": "Criterion",
        "col_norm": "Statute",
        "col_status": "Status",
        "col_note": "Details",
        "einvoice_h": "E-Invoice (EN 16931)",
        "bt_val": "Value",
        "visual_h": "Cross-check XML ↔ Visual PDF",
        "visual_col_res": "Result",
        "ai_h": "EU AI Act (Reg. (EU) 2024/1689)",
        "ai_level": "Classification",
        "annex3": "Annex III",
        "reason": "Reasoning",
        "articles": "Applicable Articles",
        "articles_html": "Applicable Obligations",
        "math_h": "Financial Math Checks",
        "col_check": "Check",
        "gdpr_h": "GDPR",
        "gdpr_html": "GDPR – PII Findings (masked)",
        "risk": "Risk Level",
        "hits": "Findings",
        "masked_note": "(masked)",
        "col_cat": "Category",
        "col_val": "Value",
        "col_src": "Source",
        "col_conf": "Confidence",
        "override_h": "Auditor Milestone · Human Override (Art. 14(4)(d) AI Act)",
        "auditor": "Auditor",
        "legal_basis": "Legal Basis",
        "ledger_entry": "Ledger Entry",
        "retention": "Retention",
        "years": "years",
        "until_at_least": "at least until",
        "fin_sector": "financial sector until",
        "sign_h": "Audit Sign-Off (Human Oversight, Art. 14)",
        "by": "by",
        "at": "on",
        "note": "Note",
        "seal_hash": "Seal Hash",
        "unsealed": "Not yet sealed.",
        "generated": "Generated",
        "chain_section": "Document & Audit Chain",
        "sha_doc": "Document SHA-256",
        "prev_hash": "Previous Hash",
        "prompt_hash": "Prompt Hash",
        "audit_time": "Audit Time",
        "hash_chain_lbl": "Hash Chain",
        "entries": "entries",
        "model_provider": "Model / Provider",
        "ruleset": "Ruleset",
        "ledger_h": "Audit Trail (Ledger)",
        "col_seq": "Seq",
        "col_event": "Event",
        "col_time": "Timestamp",
        "col_person": "Actor",
        "col_ehash": "Entry Hash",
        "col_sig": "Signature",
        "no_checks": "No checks recorded.",
        "no_pii": "No personal data detected.",
        "no_ledger": "No ledger entries.",
        "embedded_as": "embedded as",
        "pure_xml": "standalone XML",
        "sha_xml": "XML Dataset SHA-256",
        "spec_bt24": "Specification (BT-24)",
        "milestone_tag": "Auditor Milestone",
        "ed25519_signed": "Ed25519-signed",
        "seal_approved": "AUDITED & APPROVED",
        "seal_rejected": "AUDITED – APPROVAL DENIED",
        "auditor_lbl": "Auditor",
        "sealed_lbl": "Sealed",
        "draft_banner": "DRAFT – not yet sealed by a human auditor (Art. 14 EU AI Act)",
    },
    "es": {
        "report_type": "Certificado de Auditoría de Cumplimiento",
        "not_analyzed": "Aún sin analizar",
        "disclaimer": (
            "Pre-auditoría automatizada mediante reglamento determinista y asistencia de IA. "
            "No constituye asesoramiento legal ni fiscal. La aprobación final recae en el auditor responsable "
            "(Supervisión humana, Art. 14 Reglamento (UE) 2024/1689)."
        ),
        "title_prefix": "Certificado de auditoría",
        "kicker": "Certificado de Cumplimiento · Reg. (UE) 2024/1689 · § 14 UStG · RGPD",
        "rec": "Recomendación",
        "score": "Puntuación",
        "doc": "Documento",
        "model": "Modelo",
        "hash_chain": "Hash de registro",
        "chain": "Cadena",
        "intact": "intacta",
        "broken": "ROTA",
        "ustg_h": "§ 14(4) UStG – Requisitos obligatorios de factura",
        "col_item": "Criterio",
        "col_norm": "Normativa",
        "col_status": "Estado",
        "col_note": "Detalle",
        "einvoice_h": "Factura electrónica (EN 16931)",
        "bt_val": "Valor",
        "visual_h": "Cotejo XML ↔ PDF visual",
        "visual_col_res": "Resultado",
        "ai_h": "Reglamento de IA (Reg. (UE) 2024/1689)",
        "ai_level": "Clasificación",
        "annex3": "Anexo III",
        "reason": "Justificación",
        "articles": "Artículos aplicables",
        "articles_html": "Obligaciones aplicables",
        "math_h": "Validación matemática",
        "col_check": "Control",
        "gdpr_h": "RGPD",
        "gdpr_html": "RGPD – Hallazgos PII (ocultos)",
        "risk": "Nivel de riesgo",
        "hits": "Hallazgos",
        "masked_note": "(enmascarado)",
        "col_cat": "Categoría",
        "col_val": "Valor",
        "col_src": "Fuente",
        "col_conf": "Confianza",
        "override_h": "Hito de auditoría · Anulación humana (Art. 14(4)(d) Reg. IA)",
        "auditor": "Auditor",
        "legal_basis": "Base legal",
        "ledger_entry": "Entrada de registro",
        "retention": "Conservación",
        "years": "años",
        "until_at_least": "al menos hasta",
        "fin_sector": "sector financiero hasta",
        "sign_h": "Sello de auditoría (Supervisión humana, Art. 14)",
        "by": "por",
        "at": "el",
        "note": "Nota",
        "seal_hash": "Hash de sello",
        "unsealed": "Sin sellar aún.",
        "generated": "Generado",
        "chain_section": "Documento y cadena de auditoría",
        "sha_doc": "SHA-256 documento",
        "prev_hash": "Hash previo",
        "prompt_hash": "Hash de prompt",
        "audit_time": "Fecha de auditoría",
        "hash_chain_lbl": "Cadena de hash",
        "entries": "entradas",
        "model_provider": "Modelo / Proveedor",
        "ruleset": "Reglamento",
        "ledger_h": "Registro de auditoría (Ledger)",
        "col_seq": "Sec.",
        "col_event": "Evento",
        "col_time": "Fecha",
        "col_person": "Actor",
        "col_ehash": "Hash entrada",
        "col_sig": "Firma",
        "no_checks": "Sin controles registrados.",
        "no_pii": "Sin datos personales detectados.",
        "no_ledger": "Sin entradas.",
        "embedded_as": "incrustado como",
        "pure_xml": "XML independiente",
        "sha_xml": "SHA-256 XML",
        "spec_bt24": "Especificación (BT-24)",
        "milestone_tag": "Hito de auditoría",
        "ed25519_signed": "Firmado Ed25519",
        "seal_approved": "AUDITADO Y APROBADO",
        "seal_rejected": "AUDITADO – APROBACIÓN DENEGADA",
        "auditor_lbl": "Auditor",
        "sealed_lbl": "Sellado",
        "draft_banner": "BORRADOR – aún sin sellar por un auditor humano (Art. 14 Reg. IA)",
    },
}


def _rt(lang: str) -> dict[str, str]:
    return _REPORT_TEXT.get(lang, _REPORT_TEXT["de"])


def build_report(
    record: DocumentRecord,
    entries: list[LedgerEntry],
    verification: ChainVerification,
    *,
    lang: str = "de",
) -> dict[str, Any]:
    """Strukturierter Bericht (Grundlage aller drei Ausgabeformate)."""
    t = _rt(lang)
    risk_labels = _RISK_LABELS_I18N.get(lang, _RISK_LABELS)
    event_labels = _EVENT_LABELS_I18N.get(lang, _EVENT_LABELS)
    extraction = parse_extraction(record)
    compliance = parse_compliance(record)
    scorecard = parse_scorecard(record)
    sign_off = parse_sign_off(record)
    einvoice = parse_einvoice(record)
    analysis = next((e for e in entries if e.event_type == AuditEventType.ANALYSIS), None)

    tiles = {tile.key: tile for tile in scorecard.tiles} if scorecard else {}
    ai_level = compliance.ai_act.overall_risk_level.value if compliance else None
    annex = sorted(
        {
            ANNEX_III_LABELS[AnnexIIICategory(category)]
            for system in (compliance.ai_act.systems if compliance else [])
            for category in system.annex_iii_categories
        }
    )

    def checks(key: str) -> list[dict[str, Any]]:
        tile = tiles.get(key)
        return [check.model_dump(mode="json") for check in tile.checks] if tile else []

    return {
        "report_type": t["report_type"],
        "lang": lang,
        "generator": f"{APP_TITLE} v{APP_VERSION}",
        "generated_at": utcnow().isoformat(),
        "audit_id": analysis.entry_id if analysis else None,
        "ledger": {
            "entry_hash": analysis.entry_hash if analysis else None,
            "previous_hash": analysis.previous_hash if analysis else None,
            "prompt_hash": analysis.prompt_hash if analysis else None,
            "timestamp_utc": analysis.timestamp_utc if analysis else None,
            "chain_valid": verification.valid,
            "chain_entries": verification.entries,
            "chain_head": verification.head_hash,
        },
        "document": {
            "id": record.id,
            "filename": record.original_filename,
            "sha256": record.sha256,
            "pages": record.page_count,
            "size_bytes": record.size_bytes,
            "uploaded_at": record.created_at.isoformat(),
        },
        "inference": {
            "model": record.model,
            "provider": record.provider or (compliance.provider if compliance else None),
            "privacy_gateway": compliance.privacy_gateway if compliance else None,
            "audited_at": compliance.audited_at.isoformat() if compliance else None,
            "reference_audit": record.provider == "reference",
            "structured": record.provider == STRUCTURED_PROVIDER,
        },
        "einvoice": (
            {
                "source": einvoice.source,
                "attachment_name": einvoice.attachment_name,
                "error": einvoice.error,
                "syntax": einvoice.syntax,
                "profile": einvoice.profile,
                "specification_id": einvoice.specification_id,
                "is_einvoice": einvoice.is_einvoice,
                "xml_sha256": einvoice.xml_sha256,
                "business_terms": [field.model_dump(mode="json") for field in einvoice.business_terms],
                "visual_check": [check.model_dump(mode="json") for check in einvoice.visual_check],
                "rule_violations": einvoice.rule_violations,
                "public_buyer": einvoice.public_buyer_reason,
                "leitweg": einvoice.leitweg.model_dump(mode="json") if einvoice.leitweg else None,
            }
            if einvoice
            else None
        ),
        "score": scorecard.model_dump(mode="json") if scorecard else None,
        "release_recommendation": scorecard.release_recommendation if scorecard else t["not_analyzed"],
        "release_blocked": scorecard.release_blocked if scorecard else True,
        "ustg_matrix": checks("formal"),
        "math_checks": checks("math"),
        "privacy_checks": checks("privacy"),
        "ai_act": {
            "risk_level": ai_level,
            "risk_label": risk_labels.get(ai_level or "", "-"),
            "annex_iii": annex,
            "reasoning": compliance.ai_act.reasoning if compliance else "",
            "obligations": compliance.ai_act.obligations if compliance else [],
            "article_references": _ARTICLE_REFS.get(ai_level or "", []),
            "checks": checks("regulatory"),
        },
        "gdpr": {
            "risk_level": compliance.gdpr.risk_level.value if compliance else None,
            "contains_special_categories": compliance.gdpr.contains_special_categories if compliance else False,
            "findings": [
                {
                    "category": finding.category_label,
                    "masked_value": finding.masked_value,
                    "source": finding.source.value,
                    "confidence": finding.confidence,
                }
                for finding in (compliance.gdpr.findings if compliance else [])
            ],
            "recommendations": compliance.gdpr.recommendations if compliance else [],
        },
        "extraction": {
            "doc_type": extraction.doc_type.value if extraction else None,
            "sender": extraction.sender if extraction else None,
            "recipient": extraction.recipient if extraction else None,
            "document_number": extraction.document_number if extraction else None,
            "document_date": str(extraction.document_date) if extraction and extraction.document_date else None,
            "net_amount": str(extraction.net_amount) if extraction and extraction.net_amount is not None else None,
            "tax_rate": str(extraction.tax_rate) if extraction and extraction.tax_rate is not None else None,
            "tax_amount": str(extraction.tax_amount) if extraction and extraction.tax_amount is not None else None,
            "total_amount": str(extraction.total_amount) if extraction and extraction.total_amount is not None else None,
            "currency": extraction.currency if extraction else None,
            "iban_masked": mask_value(extraction.iban) if extraction and extraction.iban else None,
            "iban_valid": extraction.iban_valid if extraction else None,
        },
        "sign_off": sign_off.model_dump(mode="json") if sign_off else None,
        "human_override": (
            scorecard.human_override.model_dump(mode="json") if scorecard and scorecard.human_override else None
        ),
        "retention": scorecard.retention.model_dump(mode="json") if scorecard and scorecard.retention else None,
        "ledger_history": [
            {
                "seq": entry.seq,
                "event_type": entry.event_type,
                "event_label": event_labels.get(entry.event_type, entry.event_type),
                "timestamp_utc": entry.timestamp_utc,
                "compliance_score": entry.compliance_score,
                "entry_hash": entry.entry_hash,
                "actor": (entry.details or {}).get("auditor_name"),
                "signed": entry.signature is not None,
                "milestone": entry.event_type in AuditEventType.MILESTONES,
            }
            for entry in entries
        ],
        "disclaimer": t["disclaimer"],
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _md(value: Any) -> str:
    text = "-" if value in (None, "") else str(value)
    return text.replace("|", "/").replace("\n", " ")


def render_markdown(report: dict[str, Any], *, lang: str | None = None) -> str:
    lang = lang or str(report.get("lang") or "de")
    t = _rt(lang)
    status_labels = _STATUS_LABELS_I18N.get(lang, _STATUS_LABELS)
    source_labels = _SOURCE_LABELS_I18N.get(lang, _SOURCE_LABELS)
    visual_labels = _VISUAL_LABELS_I18N.get(lang, _VISUAL_LABELS)
    ref_note = REFERENCE_NOTE_I18N.get(lang, REFERENCE_NOTE)
    struct_note = STRUCTURED_NOTE_I18N.get(lang, STRUCTURED_NOTE)
    score = report["score"] or {}
    doc = report["document"]
    lines = [
        f"# {t['report_type']}",
        "",
        f"**{t['rec']}:** {report['release_recommendation']}  ",
        f"**{t['score']}:** {score.get('score', '-')}/100 ({score.get('band_label', '-')})  ",
        f"**Audit-ID:** `{_md(report['audit_id'])}`  ",
        f"**{t['doc']}:** {_md(doc['filename'])} · SHA-256 `{doc['sha256']}`  ",
        f"**{t['model']}:** {_md(report['inference']['model'])} ({_md(report['inference']['provider'])})  ",
        f"**{t['hash_chain']}:** `{_md(report['ledger']['entry_hash'])}` · {t['chain']} "
        f"{t['intact'] if report['ledger']['chain_valid'] else t['broken']}",
        "",
    ]
    if report["inference"].get("reference_audit"):
        lines += [f"> {ref_note}", ""]
    if report["inference"].get("structured"):
        lines += [f"> {struct_note}", ""]
    if score.get("cap_applied"):
        lines += [f"> {score['cap_applied']}", ""]

    lines += [f"## {t['ustg_h']}", "", f"| {t['col_item']} | {t['col_norm']} | {t['col_status']} | {t['col_note']} |", "|---|---|---|---|"]
    for check in report["ustg_matrix"]:
        lines.append(
            f"| {_md(check['label'])} | {_md(check.get('legal_reference'))} | "
            f"{status_labels.get(check['status'], check['status'])} | {_md(check.get('detail'))}"
            f"{(' ' + _md(check['risk_note'])) if check.get('risk_note') else ''} |"
        )
    einvoice = report.get("einvoice")
    if einvoice and not einvoice.get("error"):
        lines += [
            "",
            f"## {t['einvoice_h']} – {_md(einvoice['profile'])} · {_md(einvoice['syntax'])}",
            "",
            f"| BT | Business Term | {t['bt_val']} |",
            "|---|---|---|",
        ]
        lines += [f"| {f['bt']} | {_md(f['label'])} | {_md(f['value'])} |" for f in einvoice["business_terms"]]
        if einvoice["visual_check"]:
            lines += ["", f"**{t['visual_h']}:**"]
            lines += [
                f"- {c['bt']} {_md(c['label'])}: {visual_labels[c['status']]}"
                + (f" (XML {_md(c['xml_value'])}, PDF {_md(c['visual_value'])})" if c["status"] == "mismatch" else "")
                for c in einvoice["visual_check"]
            ]
    ai = report["ai_act"]
    lines += [
        "",
        f"## {t['ai_h']}",
        "",
        f"- **{t['ai_level']}:** {ai['risk_label']}",
        f"- **{t['annex3']}:** {', '.join(ai['annex_iii']) or '-'}",
        f"- **{t['reason']}:** {_md(ai['reasoning'])}",
    ]
    if ai["article_references"]:
        lines.append(f"- **{t['articles']}:** {', '.join(ai['article_references'])}")
    lines += ["", f"## {t['math_h']}", ""]
    for check in report["math_checks"]:
        lines.append(
            f"- {check['label']}: **{status_labels.get(check['status'], check['status'])}** "
            f"{_md(check.get('detail')) if check.get('detail') else ''}"
        )
    gdpr = report["gdpr"]
    lines += ["", f"## {t['gdpr_h']}", "", f"- **{t['risk']}:** {_md(gdpr['risk_level'])}", f"- **{t['hits']}:** {len(gdpr['findings'])} {t['masked_note']}"]
    for finding in gdpr["findings"][:20]:
        lines.append(
            f"  - {finding['category']}: `{_md(finding['masked_value'])}` "
            f"({source_labels.get(finding['source'], finding['source'])})"
        )
    override = report.get("human_override")
    if override:
        lines += [
            "",
            f"## {t.get('override_md_h', t['override_h'])}",
            "",
            f"- **{t['auditor']}:** {_md(override['auditor_name'])} · {_fmt_ts(override['overridden_at'])}",
            f"- **{t['ai_level']}:** {override['previous_risk_level']} → {override['new_risk_level']} · "
            f"Score {_md(override['previous_score'])} → {override['new_score']}",
            f"- **{t['legal_basis']}:** {_md(override['legal_basis'])}",
            f"- **{t['reason']}:** {_md(override['reason'])}",
            f"- **{t['ledger_entry']} ({t['ed25519_signed']}):** `{_md(override['ledger_entry_hash'])}`",
        ]
    retention = report.get("retention")
    if retention:
        lines += [
            "",
            f"**{t['retention']}:** {retention['years']} {t['years']}, {t['until_at_least']} {_fmt_date(retention['until'])} "
            f"({_md(retention['basis'])}). {t['fin_sector']} {_fmt_date(retention['financial_sector_until'])}.",
        ]
    sign = report["sign_off"]
    lines += ["", f"## {t['sign_h']}", ""]
    if sign:
        lines += [
            f"**{sign['status']}** {t['by']} **{_md(sign['auditor_name'])}** {t['at']} {_fmt_ts(sign['sealed_at'])}  ",
            f"{t['note']}: {_md(sign['note'])}  ",
            f"{t['seal_hash']}: `{sign['ledger_entry_hash']}`",
        ]
    else:
        lines.append(f"_{t['unsealed']}_")
    lines += ["", "---", f"_{report['disclaimer']}_", f"_{t['generated']}: {_fmt_ts(report['generated_at'])} · {report['generator']}_", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML (A4, druckfertig)
# ---------------------------------------------------------------------------


def _e(value: Any) -> str:
    return html.escape("-" if value in (None, "") else str(value))


_SEAL_SVG = """<svg class="seal" viewBox="0 0 120 120" aria-hidden="true">
<circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="3"/>
<circle cx="60" cy="60" r="47" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="3 3"/>
<path d="M38 61l15 15 30-32" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def render_html(report: dict[str, Any], *, lang: str | None = None) -> str:
    lang = lang or str(report.get("lang") or "de")
    t = _rt(lang)
    status_labels = _STATUS_LABELS_I18N.get(lang, _STATUS_LABELS)
    source_labels = _SOURCE_LABELS_I18N.get(lang, _SOURCE_LABELS)
    visual_labels = _VISUAL_LABELS_I18N.get(lang, _VISUAL_LABELS)
    ref_note = REFERENCE_NOTE_I18N.get(lang, REFERENCE_NOTE)
    struct_note = STRUCTURED_NOTE_I18N.get(lang, STRUCTURED_NOTE)
    score = report["score"] or {}
    band = score.get("band", "red")
    doc = report["document"]
    sign = report["sign_off"]
    approved = bool(sign and sign["status"] == "SEALED_APPROVED")
    ai = report["ai_act"]

    def rows(checks: list[dict[str, Any]]) -> str:
        return "".join(
            f"<tr><td>{_e(c['label'])}</td><td class='mono'>{_e(c.get('legal_reference'))}</td>"
            f"<td><span class='st st-{_e(c['status'])}'>{_e(status_labels.get(c['status'], c['status']))}</span></td>"
            f"<td>{_e(c.get('detail') or '')}"
            f"{('<div class=risk>' + _e(c['risk_note']) + '</div>') if c.get('risk_note') else ''}"
            f"{('<div class=small>' + _e(c['note']) + '</div>') if c.get('note') else ''}</td></tr>"
            for c in checks
        ) or f"<tr><td colspan='4'>{_e(t['no_checks'])}</td></tr>"

    findings = "".join(
        f"<tr><td>{_e(f['category'])}</td><td class='mono'>{_e(f['masked_value'])}</td>"
        f"<td>{_e(source_labels.get(f['source'], f['source']))}</td><td>{f['confidence'] * 100:.0f} %</td></tr>"
        for f in report["gdpr"]["findings"][:25]
    ) or f"<tr><td colspan='4'>{_e(t['no_pii'])}</td></tr>"

    einvoice = report.get("einvoice")
    einvoice_block = ""
    if einvoice and not einvoice.get("error"):
        terms = "".join(
            f"<tr><td class='mono'>{_e(f['bt'])}</td><td>{_e(f['label'])}</td><td class='mono'>{_e(f['value'])}</td></tr>"
            for f in einvoice["business_terms"]
        )
        visual = "".join(
            f"<tr><td class='mono'>{_e(c['bt'])}</td><td>{_e(c['label'])}</td>"
            f"<td><span class='st st-{'pass' if c['status'] == 'match' else 'warn' if c['status'] == 'not_found' else 'fail'}'>"
            f"{_e(visual_labels[c['status']])}</span></td>"
            f"<td class='mono'>{_e(c['xml_value'])}{(' / PDF ' + _e(c['visual_value'])) if c.get('visual_value') else ''}</td></tr>"
            for c in einvoice["visual_check"]
        )
        container = (
            f"{_e(t['embedded_as'])} {_e(einvoice['attachment_name'])}" if einvoice["source"] == "embedded" else _e(t["pure_xml"])
        )
        einvoice_block = f"""<h2>{_e(t['einvoice_h'])}</h2>
<p><strong>{_e(einvoice['profile'])}</strong> · Syntax {_e(einvoice['syntax'])} · {container}</p>
<div class="grid small"><div>{_e(t['sha_xml'])}</div><div class="mono">{_e(einvoice['xml_sha256'])}</div>
<div>{_e(t['spec_bt24'])}</div><div class="mono">{_e(einvoice['specification_id'])}</div></div>
<table><thead><tr><th style="width:12%">BT</th><th style="width:38%">Business Term</th><th>{_e(t['bt_val'])}</th></tr></thead><tbody>{terms}</tbody></table>
{f'<table><thead><tr><th style="width:12%">BT</th><th style="width:30%">{_e(t["visual_h"])}</th><th style="width:20%">{_e(t["visual_col_res"])}</th><th>{_e(t["bt_val"])}</th></tr></thead><tbody>{visual}</tbody></table>' if visual else ''}"""

    override = report.get("human_override")
    override_block = ""
    if override:
        override_block = f"""<h2>{_e(t['override_h'])}</h2>
<div class="milestone">
<div class="grid small">
<div>{_e(t['auditor'])}</div><div><strong>{_e(override['auditor_name'])}</strong> · {_e(_fmt_ts(override['overridden_at']))}</div>
<div>{_e(t['ai_level'])}</div><div>{_e(override['previous_risk_level'])} → <strong>{_e(override['new_risk_level'])}</strong></div>
<div>Score</div><div class="num">{_e(override['previous_score'])} → <strong>{_e(override['new_score'])}</strong></div>
<div>{_e(t['legal_basis'])}</div><div>{_e(override['legal_basis'])}</div>
<div>{_e(t['reason'])}</div><div>{_e(override['reason'])}</div>
<div>{_e(t['ledger_entry'])}</div><div class="mono">{_e(override['ledger_entry_hash'])} · {_e(t['ed25519_signed'])}</div>
</div></div>"""

    history = "".join(
        f"<tr class='{'ms' if h['milestone'] else ''}'><td class='num'>{_e(h['seq'])}</td>"
        f"<td>{_e(h['event_label'])}{(' · ' + _e(t['milestone_tag'])) if h['milestone'] else ''}</td>"
        f"<td>{_e(_fmt_ts(h['timestamp_utc']))}</td><td>{_e(h['actor'] or '')}</td>"
        f"<td class='num'>{_e(h['compliance_score'])}</td><td class='mono'>{_e(h['entry_hash'][:16])}…</td>"
        f"<td>{'Ed25519' if h['signed'] else '–'}</td></tr>"
        for h in sorted(report["ledger_history"], key=lambda item: item["seq"] or 0)
    ) or f"<tr><td colspan='7'>{_e(t['no_ledger'])}</td></tr>"

    retention = report.get("retention")
    retention_row = (
        f"<div>{_e(t['retention'])}</div><div>{_e(retention['years'])} {_e(t['years'])}, {_e(t['until_at_least'])} "
        f"{_e(_fmt_date(retention['until']))} ({_e(retention['basis'])}); {_e(t['fin_sector'])} "
        f"{_e(_fmt_date(retention['financial_sector_until']))}</div>"
        if retention
        else ""
    )

    seal_block = (
        f"""<div class="sealbox {'ok' if approved else 'bad'}">{_SEAL_SVG}
        <div><div class="sealtitle">{_e(t['seal_approved'] if approved else t['seal_rejected'])}</div>
        <div>{_e(t['auditor_lbl'])}: <strong>{_e(sign['auditor_name'])}</strong></div>
        <div>{_e(t['sealed_lbl'])}: {_e(_fmt_ts(sign['sealed_at']))}</div>
        <div class="mono small">{_e(t['seal_hash'])} {_e(sign['ledger_entry_hash'])}</div>
        {f"<div class='small'>{_e(t['note'])}: {_e(sign['note'])}</div>" if sign.get('note') else ''}</div></div>"""
        if sign
        else f'<div class="draft">{_e(t["draft_banner"])}</div>'
    )

    return f"""<!doctype html>
<html lang="{_e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(t['title_prefix'])} {_e(doc['filename'])}</title>
<style>
@page {{ size: A4; margin: 16mm 14mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Inter, "Segoe UI", Helvetica, Arial, sans-serif; color: #0f172a; background: #f1f5f9; margin: 0; font-size: 10.5pt; line-height: 1.45; }}
.page {{ background: #fff; max-width: 210mm; margin: 12px auto; padding: 18mm 16mm; border: 1px solid #e2e8f0; }}
h1 {{ font-size: 18pt; margin: 0; letter-spacing: -0.01em; }}
h2 {{ font-size: 11.5pt; margin: 18px 0 6px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }}
.mono {{ font-family: "JetBrains Mono", Consolas, monospace; font-size: 8.5pt; word-break: break-all; }}
.small {{ font-size: 8.5pt; color: #475569; }}
.head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
.kicker {{ font-size: 8pt; letter-spacing: .12em; text-transform: uppercase; color: #475569; }}
.score {{ text-align: center; border: 2px solid; border-radius: 12px; padding: 8px 14px; min-width: 120px; }}
.score b {{ font-size: 26pt; display: block; line-height: 1; }}
.green {{ color: #047857; border-color: #059669; }} .amber {{ color: #b45309; border-color: #d97706; }} .red {{ color: #be123c; border-color: #e11d48; }}
.verdict {{ margin: 14px 0; padding: 10px 12px; border-radius: 8px; font-weight: 600; }}
.risk {{ margin-top: 3px; color: #9f1239; font-size: 8.5pt; }}
.refnote {{ margin-top: 12px; padding: 8px 12px; border: 1px dashed #94a3b8; border-radius: 8px; font-size: 9pt; color: #334155; }}
.verdict.ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
.verdict.bad {{ background: #fff1f2; color: #9f1239; border: 1px solid #fecdd3; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
th, td {{ text-align: left; padding: 5px 6px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
th {{ font-size: 8pt; text-transform: uppercase; letter-spacing: .06em; color: #475569; }}
.st {{ display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 8pt; font-weight: 600; white-space: nowrap; }}
.st-pass {{ background: #ecfdf5; color: #047857; }} .st-warn {{ background: #fffbeb; color: #b45309; }}
.st-fail {{ background: #fff1f2; color: #be123c; }} .st-not_applicable {{ background: #f1f5f9; color: #475569; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px; }}
.sealbox {{ display: flex; gap: 14px; align-items: center; margin-top: 18px; padding: 12px; border: 2px solid; border-radius: 12px; }}
.sealbox.ok {{ color: #047857; border-color: #059669; background: #f0fdf4; }}
.sealbox.bad {{ color: #be123c; border-color: #e11d48; background: #fff1f2; }}
.sealbox div {{ color: #0f172a; }}
.seal {{ width: 84px; height: 84px; flex: none; }}
.sealtitle {{ font-weight: 800; letter-spacing: .08em; color: inherit !important; }}
.sealbox.ok .sealtitle {{ color: #047857 !important; }} .sealbox.bad .sealtitle {{ color: #be123c !important; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.milestone {{ padding: 10px 12px; border: 1px solid #c7d2fe; background: #eef2ff; border-radius: 8px; }}
tr.ms td {{ background: #f5f7ff; }}
.draft {{ margin-top: 18px; padding: 10px; border: 1px dashed #94a3b8; color: #475569; text-align: center; border-radius: 8px; }}
footer {{ margin-top: 18px; font-size: 8pt; color: #64748b; }}
@media print {{
  body {{ background: #fff; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .page {{ border: 0; margin: 0; padding: 0; max-width: none; }}
  h2 {{ break-after: avoid; }}
  tr, .sealbox, .verdict, .refnote, .grid, .milestone {{ break-inside: avoid; }}
  thead {{ display: table-header-group; }}
}}
</style></head>
<body><main class="page">
<div class="head">
  <div><div class="kicker">{_e(t['kicker'])}</div>
  <h1>{_e(doc['filename'])}</h1>
  <div class="small">Audit-ID <span class="mono">{_e(report['audit_id'])}</span></div></div>
  <div class="score {_e(band)}"><b>{_e(score.get('score', '–'))}</b>/100<div class="small">{_e(score.get('band_label'))}</div></div>
</div>
{f'<div class="refnote">{_e(ref_note)}</div>' if report['inference'].get('reference_audit') else ''}
{f'<div class="refnote">{_e(struct_note)}</div>' if report['inference'].get('structured') else ''}
<div class="verdict {'bad' if report['release_blocked'] else 'ok'}">{_e(report['release_recommendation'])}{f" · {_e(score.get('cap_applied'))}" if score.get('cap_applied') else ''}</div>

<h2>{_e(t['chain_section'])}</h2>
<div class="grid small">
<div>{_e(t['sha_doc'])}</div><div class="mono">{_e(doc['sha256'])}</div>
<div>{_e(t['ledger_entry'])}</div><div class="mono">{_e(report['ledger']['entry_hash'])}</div>
<div>{_e(t['prev_hash'])}</div><div class="mono">{_e(report['ledger']['previous_hash'])}</div>
<div>{_e(t['prompt_hash'])}</div><div class="mono">{_e(report['ledger']['prompt_hash'])}</div>
<div>{_e(t['audit_time'])}</div><div>{_e(_fmt_ts(report['ledger']['timestamp_utc']))}</div>
<div>{_e(t['hash_chain_lbl'])}</div><div>{_e(t['intact'] if report['ledger']['chain_valid'] else t['broken'])} ({_e(report['ledger']['chain_entries'])} {_e(t['entries'])})</div>
<div>{_e(t['model_provider'])}</div><div>{_e(report['inference']['model'])} / {_e(report['inference']['provider'])}</div>
<div>{_e(t['ruleset'])}</div><div>{_e(score.get('ruleset_version'))}</div>
{retention_row}
</div>

{einvoice_block}

<h2>{_e(t['ustg_h'])}</h2>
<table><thead><tr><th style="width:30%">{_e(t['col_item'])}</th><th style="width:24%">{_e(t['col_norm'])}</th><th style="width:11%">{_e(t['col_status'])}</th><th>{_e(t['col_note'])}</th></tr></thead><tbody>{rows(report['ustg_matrix'])}</tbody></table>

<h2>{_e(t['ai_h'])}</h2>
<p><strong>{_e(ai['risk_label'])}</strong>{(' · ' + _e(', '.join(ai['annex_iii']))) if ai['annex_iii'] else ''}</p>
<p class="small">{_e(ai['reasoning'])}</p>
{f"<p class='small'>{_e(t['articles_html'])}: {_e(', '.join(ai['article_references']))}</p>" if ai['article_references'] else ''}
{''.join(f"<p class='small'>{_e(c['note'])}</p>" for c in ai['checks'] if c.get('note'))}
{''.join(f"<p class='risk'>{_e(c['risk_note'])}</p>" for c in ai['checks'] if c.get('risk_note'))}

<h2>{_e(t['math_h'])}</h2>
<table><thead><tr><th style="width:30%">{_e(t['col_check'])}</th><th style="width:24%">{_e(t['col_norm'])}</th><th style="width:11%">{_e(t['col_status'])}</th><th>{_e(t['col_note'])}</th></tr></thead><tbody>{rows(report['math_checks'])}</tbody></table>

<h2>{_e(t['gdpr_html'])}</h2>
<table><thead><tr><th>{_e(t['col_cat'])}</th><th>{_e(t['col_val'])}</th><th>{_e(t['col_src'])}</th><th>{_e(t['col_conf'])}</th></tr></thead><tbody>{findings}</tbody></table>

{override_block}

<h2>{_e(t['ledger_h'])}</h2>
<table><thead><tr><th class="num" style="width:6%">{_e(t['col_seq'])}</th><th style="width:26%">{_e(t['col_event'])}</th><th style="width:20%">{_e(t['col_time'])}</th><th>{_e(t['col_person'])}</th><th class="num" style="width:8%">Score</th><th style="width:18%">{_e(t['col_ehash'])}</th><th style="width:9%">{_e(t['col_sig'])}</th></tr></thead><tbody>{history}</tbody></table>

{seal_block}
<footer>{_e(report['disclaimer'])}<br>{_e(t['generated'])} {_e(_fmt_ts(report['generated_at']))} · {_e(report['generator'])}</footer>
</main></body></html>"""
