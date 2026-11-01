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

#: Kennzeichnung vorberechneter Musterdaten-Audits in allen Ausgabeformaten.
REFERENCE_NOTE = (
    "Referenz-Audit der Musterdaten: Die Modellantwort ist vorberechnet (keine KI-Inferenz). "
    "Score, Maskierung, Eskalationsregeln und Hash-Kette stammen aus dem regulären Regelwerk."
)

#: Kennzeichnung des deterministischen E-Rechnungs-Pfads.
STRUCTURED_NOTE = (
    "Strukturierte E-Rechnung: Rechnungsdaten deterministisch aus dem EN-16931-Datensatz gelesen, "
    "keine KI-Inferenz. Bei hybriden Rechnungen ist der XML-Teil maßgeblich (BMF-Schreiben vom 15.10.2024, Rz. 36)."
)

_SOURCE_LABELS = {
    "llm": "KI-Modell",
    "rule_based": "Regelwerk",
    "both": "KI + Regelwerk",
    "xml": "XML-Datensatz",
    "xml_rule": "XML + Regelwerk",
}

_VISUAL_LABELS = {"match": "übereinstimmend", "mismatch": "ABWEICHUNG", "not_found": "im Bildteil nicht gefunden"}

_EVENT_LABELS = {
    AuditEventType.ANALYSIS: "Analyse",
    AuditEventType.SIGN_OFF: "Prüfer-Siegel",
    AuditEventType.HUMAN_OVERRIDE: "Übersteuerung (Art. 14)",
    AuditEventType.PROVIDER_FAILOVER: "Provider-Wechsel (Ausfall)",
    AuditEventType.ARCHIVE: "Archiviert",
    AuditEventType.UNARCHIVE: "Aus dem Archiv geholt",
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


def build_report(
    record: DocumentRecord,
    entries: list[LedgerEntry],
    verification: ChainVerification,
) -> dict[str, Any]:
    """Strukturierter Bericht (Grundlage aller drei Ausgabeformate)."""
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
        "report_type": "Compliance-Prüfzertifikat",
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
        "release_recommendation": scorecard.release_recommendation if scorecard else "Noch nicht analysiert",
        "release_blocked": scorecard.release_blocked if scorecard else True,
        "ustg_matrix": checks("formal"),
        "math_checks": checks("math"),
        "privacy_checks": checks("privacy"),
        "ai_act": {
            "risk_level": ai_level,
            "risk_label": _RISK_LABELS.get(ai_level or "", "-"),
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
                "event_label": _EVENT_LABELS.get(entry.event_type, entry.event_type),
                "timestamp_utc": entry.timestamp_utc,
                "compliance_score": entry.compliance_score,
                "entry_hash": entry.entry_hash,
                "actor": (entry.details or {}).get("auditor_name"),
                "signed": entry.signature is not None,
                "milestone": entry.event_type in AuditEventType.MILESTONES,
            }
            for entry in entries
        ],
        "disclaimer": (
            "Automatisierte Vorprüfung mit deterministischem Regelwerk und KI-Unterstützung. "
            "Ersetzt keine Steuer- oder Rechtsberatung. Maßgeblich ist die Freigabe durch die "
            "verantwortliche Prüfperson (Human Oversight, Art. 14 VO (EU) 2024/1689)."
        ),
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _md(value: Any) -> str:
    text = "-" if value in (None, "") else str(value)
    return text.replace("|", "/").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    score = report["score"] or {}
    doc = report["document"]
    lines = [
        "# Compliance-Prüfzertifikat",
        "",
        f"**Freigabeempfehlung:** {report['release_recommendation']}  ",
        f"**Compliance-Score:** {score.get('score', '-')}/100 ({score.get('band_label', '-')})  ",
        f"**Audit-ID:** `{_md(report['audit_id'])}`  ",
        f"**Dokument:** {_md(doc['filename'])} · SHA-256 `{doc['sha256']}`  ",
        f"**Modell:** {_md(report['inference']['model'])} ({_md(report['inference']['provider'])})  ",
        f"**Ledger-Hash:** `{_md(report['ledger']['entry_hash'])}` · Kette "
        f"{'intakt' if report['ledger']['chain_valid'] else 'GEBROCHEN'}",
        "",
    ]
    if report["inference"].get("reference_audit"):
        lines += [f"> {REFERENCE_NOTE}", ""]
    if report["inference"].get("structured"):
        lines += [f"> {STRUCTURED_NOTE}", ""]
    if score.get("cap_applied"):
        lines += [f"> {score['cap_applied']}", ""]

    lines += ["## § 14 Abs. 4 UStG – Pflichtangaben", "", "| Merkmal | Norm | Status | Hinweis |", "|---|---|---|---|"]
    for check in report["ustg_matrix"]:
        lines.append(
            f"| {_md(check['label'])} | {_md(check.get('legal_reference'))} | "
            f"{_STATUS_LABELS.get(check['status'], check['status'])} | {_md(check.get('detail'))}"
            f"{(' ' + _md(check['risk_note'])) if check.get('risk_note') else ''} |"
        )
    einvoice = report.get("einvoice")
    if einvoice and not einvoice.get("error"):
        lines += [
            "",
            f"## E-Rechnung (EN 16931) – {_md(einvoice['profile'])} · {_md(einvoice['syntax'])}",
            "",
            "| BT | Business Term | Wert |",
            "|---|---|---|",
        ]
        lines += [f"| {f['bt']} | {_md(f['label'])} | {_md(f['value'])} |" for f in einvoice["business_terms"]]
        if einvoice["visual_check"]:
            lines += ["", "**Abgleich XML ↔ PDF-Bildteil:**"]
            lines += [
                f"- {c['bt']} {_md(c['label'])}: {_VISUAL_LABELS[c['status']]}"
                + (f" (XML {_md(c['xml_value'])}, PDF {_md(c['visual_value'])})" if c["status"] == "mismatch" else "")
                for c in einvoice["visual_check"]
            ]
    ai = report["ai_act"]
    lines += [
        "",
        "## EU AI Act (VO (EU) 2024/1689)",
        "",
        f"- **Einstufung:** {ai['risk_label']}",
        f"- **Anhang III:** {', '.join(ai['annex_iii']) or '-'}",
        f"- **Begründung:** {_md(ai['reasoning'])}",
    ]
    if ai["article_references"]:
        lines.append(f"- **Einschlägige Artikel:** {', '.join(ai['article_references'])}")
    lines += ["", "## Mathematische Validität", ""]
    for check in report["math_checks"]:
        lines.append(f"- {check['label']}: **{_STATUS_LABELS.get(check['status'])}** {_md(check.get('detail')) if check.get('detail') else ''}")
    gdpr = report["gdpr"]
    lines += ["", "## DSGVO", "", f"- **Risiko:** {_md(gdpr['risk_level'])}", f"- **Treffer:** {len(gdpr['findings'])} (maskiert)"]
    for finding in gdpr["findings"][:20]:
        lines.append(
            f"  - {finding['category']}: `{_md(finding['masked_value'])}` "
            f"({_SOURCE_LABELS.get(finding['source'], finding['source'])})"
        )
    override = report.get("human_override")
    if override:
        lines += [
            "",
            "## Prüfer-Meilenstein: Übersteuerung der KI-Einstufung (Art. 14 Abs. 4 lit. d AI Act)",
            "",
            f"- **Prüfperson:** {_md(override['auditor_name'])} · {_fmt_ts(override['overridden_at'])}",
            f"- **Einstufung:** {override['previous_risk_level']} → {override['new_risk_level']} · "
            f"Score {_md(override['previous_score'])} → {override['new_score']}",
            f"- **Rechtsnorm:** {_md(override['legal_basis'])}",
            f"- **Begründung:** {_md(override['reason'])}",
            f"- **Ledger-Eintrag (Ed25519-signiert):** `{_md(override['ledger_entry_hash'])}`",
        ]
    retention = report.get("retention")
    if retention:
        lines += [
            "",
            f"**Aufbewahrung:** {retention['years']} Jahre, bis mindestens {_fmt_date(retention['until'])} "
            f"({_md(retention['basis'])}). Finanzsektor: bis {_fmt_date(retention['financial_sector_until'])}.",
        ]
    sign = report["sign_off"]
    lines += ["", "## Prüfvermerk (Human Oversight, Art. 14)", ""]
    if sign:
        lines += [
            f"**{sign['status']}** durch **{_md(sign['auditor_name'])}** am {_fmt_ts(sign['sealed_at'])}  ",
            f"Notiz: {_md(sign['note'])}  ",
            f"Siegel-Hash: `{sign['ledger_entry_hash']}`",
        ]
    else:
        lines.append("_Noch nicht versiegelt._")
    lines += ["", "---", f"_{report['disclaimer']}_", f"_Erstellt: {_fmt_ts(report['generated_at'])} · {report['generator']}_", ""]
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


def render_html(report: dict[str, Any]) -> str:
    score = report["score"] or {}
    band = score.get("band", "red")
    doc = report["document"]
    sign = report["sign_off"]
    approved = bool(sign and sign["status"] == "SEALED_APPROVED")
    ai = report["ai_act"]

    def rows(checks: list[dict[str, Any]]) -> str:
        return "".join(
            f"<tr><td>{_e(c['label'])}</td><td class='mono'>{_e(c.get('legal_reference'))}</td>"
            f"<td><span class='st st-{_e(c['status'])}'>{_e(_STATUS_LABELS.get(c['status'], c['status']))}</span></td>"
            f"<td>{_e(c.get('detail') or '')}"
            f"{('<div class=risk>' + _e(c['risk_note']) + '</div>') if c.get('risk_note') else ''}"
            f"{('<div class=small>' + _e(c['note']) + '</div>') if c.get('note') else ''}</td></tr>"
            for c in checks
        ) or "<tr><td colspan='4'>Keine Prüfpunkte.</td></tr>"

    findings = "".join(
        f"<tr><td>{_e(f['category'])}</td><td class='mono'>{_e(f['masked_value'])}</td>"
        f"<td>{_e(_SOURCE_LABELS.get(f['source'], f['source']))}</td><td>{f['confidence'] * 100:.0f} %</td></tr>"
        for f in report["gdpr"]["findings"][:25]
    ) or "<tr><td colspan='4'>Keine personenbezogenen Daten erkannt.</td></tr>"

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
            f"{_e(_VISUAL_LABELS[c['status']])}</span></td>"
            f"<td class='mono'>{_e(c['xml_value'])}{(' / PDF ' + _e(c['visual_value'])) if c.get('visual_value') else ''}</td></tr>"
            for c in einvoice["visual_check"]
        )
        container = (
            f"eingebettet als {_e(einvoice['attachment_name'])}" if einvoice["source"] == "embedded" else "reines XML"
        )
        einvoice_block = f"""<h2>E-Rechnung (EN 16931)</h2>
<p><strong>{_e(einvoice['profile'])}</strong> · Syntax {_e(einvoice['syntax'])} · {container}</p>
<div class="grid small"><div>SHA-256 XML-Datensatz</div><div class="mono">{_e(einvoice['xml_sha256'])}</div>
<div>Spezifikation (BT-24)</div><div class="mono">{_e(einvoice['specification_id'])}</div></div>
<table><thead><tr><th style="width:12%">BT</th><th style="width:38%">Business Term</th><th>Wert</th></tr></thead><tbody>{terms}</tbody></table>
{f'<table><thead><tr><th style="width:12%">BT</th><th style="width:30%">Abgleich XML ↔ Bildteil</th><th style="width:20%">Ergebnis</th><th>Wert</th></tr></thead><tbody>{visual}</tbody></table>' if visual else ''}"""

    override = report.get("human_override")
    override_block = ""
    if override:
        override_block = f"""<h2>Prüfer-Meilenstein · Übersteuerung (Art. 14 Abs. 4 lit. d AI Act)</h2>
<div class="milestone">
<div class="grid small">
<div>Prüfperson</div><div><strong>{_e(override['auditor_name'])}</strong> · {_e(_fmt_ts(override['overridden_at']))}</div>
<div>Einstufung</div><div>{_e(override['previous_risk_level'])} → <strong>{_e(override['new_risk_level'])}</strong></div>
<div>Score</div><div class="num">{_e(override['previous_score'])} → <strong>{_e(override['new_score'])}</strong></div>
<div>Rechtsnorm</div><div>{_e(override['legal_basis'])}</div>
<div>Begründung</div><div>{_e(override['reason'])}</div>
<div>Ledger-Eintrag</div><div class="mono">{_e(override['ledger_entry_hash'])} · Ed25519-signiert</div>
</div></div>"""

    history = "".join(
        f"<tr class='{'ms' if h['milestone'] else ''}'><td class='num'>{_e(h['seq'])}</td>"
        f"<td>{_e(h['event_label'])}{' · Prüfer-Meilenstein' if h['milestone'] else ''}</td>"
        f"<td>{_e(_fmt_ts(h['timestamp_utc']))}</td><td>{_e(h['actor'] or '')}</td>"
        f"<td class='num'>{_e(h['compliance_score'])}</td><td class='mono'>{_e(h['entry_hash'][:16])}…</td>"
        f"<td>{'Ed25519' if h['signed'] else '–'}</td></tr>"
        for h in sorted(report["ledger_history"], key=lambda item: item["seq"] or 0)
    ) or "<tr><td colspan='7'>Keine Ledger-Einträge.</td></tr>"

    retention = report.get("retention")
    retention_row = (
        f"<div>Aufbewahrung</div><div>{_e(retention['years'])} Jahre, bis mindestens "
        f"{_e(_fmt_date(retention['until']))} ({_e(retention['basis'])}); Finanzsektor bis "
        f"{_e(_fmt_date(retention['financial_sector_until']))}</div>"
        if retention
        else ""
    )

    seal_block = (
        f"""<div class="sealbox {'ok' if approved else 'bad'}">{_SEAL_SVG}
        <div><div class="sealtitle">{'GEPRÜFT &amp; FREIGEGEBEN' if approved else 'GEPRÜFT – FREIGABE VERWEIGERT'}</div>
        <div>Prüfer: <strong>{_e(sign['auditor_name'])}</strong></div>
        <div>Versiegelt: {_e(_fmt_ts(sign['sealed_at']))}</div>
        <div class="mono small">Siegel-Hash {_e(sign['ledger_entry_hash'])}</div>
        {f"<div class='small'>Notiz: {_e(sign['note'])}</div>" if sign.get('note') else ''}</div></div>"""
        if sign
        else '<div class="draft">ENTWURF – noch nicht durch eine Prüfperson versiegelt (Art. 14 EU AI Act)</div>'
    )

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prüfzertifikat {_e(doc['filename'])}</title>
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
  <div><div class="kicker">Compliance-Prüfzertifikat · VO (EU) 2024/1689 · § 14 UStG · DSGVO</div>
  <h1>{_e(doc['filename'])}</h1>
  <div class="small">Audit-ID <span class="mono">{_e(report['audit_id'])}</span></div></div>
  <div class="score {_e(band)}"><b>{_e(score.get('score', '–'))}</b>/100<div class="small">{_e(score.get('band_label'))}</div></div>
</div>
{f'<div class="refnote">{_e(REFERENCE_NOTE)}</div>' if report['inference'].get('reference_audit') else ''}
{f'<div class="refnote">{_e(STRUCTURED_NOTE)}</div>' if report['inference'].get('structured') else ''}
<div class="verdict {'bad' if report['release_blocked'] else 'ok'}">{_e(report['release_recommendation'])}{f" · {_e(score.get('cap_applied'))}" if score.get('cap_applied') else ''}</div>

<h2>Dokument &amp; Prüfkette</h2>
<div class="grid small">
<div>SHA-256 Dokument</div><div class="mono">{_e(doc['sha256'])}</div>
<div>Ledger-Eintrag</div><div class="mono">{_e(report['ledger']['entry_hash'])}</div>
<div>Vorgänger-Hash</div><div class="mono">{_e(report['ledger']['previous_hash'])}</div>
<div>Prompt-Hash</div><div class="mono">{_e(report['ledger']['prompt_hash'])}</div>
<div>Prüfzeitpunkt</div><div>{_e(_fmt_ts(report['ledger']['timestamp_utc']))}</div>
<div>Hash-Kette</div><div>{'intakt' if report['ledger']['chain_valid'] else 'GEBROCHEN'} ({_e(report['ledger']['chain_entries'])} Einträge)</div>
<div>Modell / Provider</div><div>{_e(report['inference']['model'])} / {_e(report['inference']['provider'])}</div>
<div>Regelwerk</div><div>{_e(score.get('ruleset_version'))}</div>
{retention_row}
</div>

{einvoice_block}

<h2>§ 14 Abs. 4 UStG – Pflichtangaben</h2>
<table><thead><tr><th style="width:30%">Merkmal</th><th style="width:24%">Norm</th><th style="width:11%">Status</th><th>Hinweis</th></tr></thead><tbody>{rows(report['ustg_matrix'])}</tbody></table>

<h2>EU AI Act</h2>
<p><strong>{_e(ai['risk_label'])}</strong>{(' · ' + _e(', '.join(ai['annex_iii']))) if ai['annex_iii'] else ''}</p>
<p class="small">{_e(ai['reasoning'])}</p>
{f"<p class='small'>Einschlägige Pflichten: {_e(', '.join(ai['article_references']))}</p>" if ai['article_references'] else ''}
{''.join(f"<p class='small'>{_e(c['note'])}</p>" for c in ai['checks'] if c.get('note'))}
{''.join(f"<p class='risk'>{_e(c['risk_note'])}</p>" for c in ai['checks'] if c.get('risk_note'))}

<h2>Mathematische Validität</h2>
<table><thead><tr><th style="width:30%">Prüfung</th><th style="width:24%">Norm</th><th style="width:11%">Status</th><th>Hinweis</th></tr></thead><tbody>{rows(report['math_checks'])}</tbody></table>

<h2>DSGVO – PII-Befunde (maskiert)</h2>
<table><thead><tr><th>Kategorie</th><th>Wert</th><th>Quelle</th><th>Konfidenz</th></tr></thead><tbody>{findings}</tbody></table>

{override_block}

<h2>Prüfpfad (Ledger)</h2>
<table><thead><tr><th class="num" style="width:6%">Seq</th><th style="width:26%">Ereignis</th><th style="width:20%">Zeitpunkt</th><th>Person</th><th class="num" style="width:8%">Score</th><th style="width:18%">Eintrags-Hash</th><th style="width:9%">Signatur</th></tr></thead><tbody>{history}</tbody></table>

{seal_block}
<footer>{_e(report['disclaimer'])}<br>Erstellt {_e(_fmt_ts(report['generated_at']))} · {_e(report['generator'])}</footer>
</main></body></html>"""
