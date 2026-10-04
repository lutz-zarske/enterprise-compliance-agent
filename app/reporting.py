"""Revisionssicheres Audit-Zertifikat in drei Formaten (JSON, Markdown, HTML/A4).

Der Bericht ist eine *Sicht* auf bereits gespeicherte, im Ledger verankerte
Daten - er berechnet nichts neu.  Die Audit-ID ist die ``entry_id`` des
juengsten Analyse-Eintrags im Hash-Ledger; der Eintrags-Hash steht im Bericht,
sodass ein Pruefer das Zertifikat gegen ``GET /api/audit/trail`` abgleichen kann.

Sicherheit: Alle Werte (auch LLM-Freitexte) werden HTML-escaped; die
HTML-Antwort wird mit einer restriktiven Content-Security-Policy ausgeliefert.
"""

from __future__ import annotations

import html
from typing import Any

from app.audit_ledger import AuditEventType, ChainVerification, LedgerEntry
from app.config import APP_TITLE, APP_VERSION
from app.db import DocumentRecord, utcnow
from app.redaction import mask_value
from app.schemas import ANNEX_III_LABELS, AnnexIIICategory
from app.services import parse_compliance, parse_extraction, parse_scorecard, parse_sign_off

#: CSP fuer die HTML-Ausgabe: keine Skripte, keine externen Ressourcen.
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"

_RISK_LABELS = {
    "unacceptable": "Verbotene Praktik (Art. 5)",
    "high": "Hochrisiko (Art. 6 Abs. 2 i. V. m. Anhang III)",
    "limited": "Begrenztes Risiko (Art. 50)",
    "minimal": "Minimales Risiko",
    "not_applicable": "Kein KI-System beschrieben",
}

_STATUS_LABELS = {"pass": "Erfuellt", "warn": "Hinweis", "fail": "Mangel", "not_applicable": "n. e."}

_ARTICLE_REFS = {
    "high": [
        "Art. 9 Risikomanagementsystem",
        "Art. 10 Daten und Daten-Governance",
        "Art. 11 Technische Dokumentation",
        "Art. 12 Aufzeichnungspflichten (Logging)",
        "Art. 13 Transparenz gegenueber Betreibern",
        "Art. 14 Menschliche Aufsicht",
        "Art. 15 Genauigkeit, Robustheit, Cybersicherheit",
        "Art. 26 Pflichten der Betreiber",
        "Art. 43 Konformitaetsbewertung",
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
        "report_type": "Compliance-Pruefzertifikat",
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
        },
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
        "ledger_history": [
            {
                "seq": entry.seq,
                "event_type": entry.event_type,
                "timestamp_utc": entry.timestamp_utc,
                "compliance_score": entry.compliance_score,
                "entry_hash": entry.entry_hash,
            }
            for entry in entries
        ],
        "disclaimer": (
            "Automatisierte Vorpruefung mit deterministischem Regelwerk und KI-Unterstuetzung. "
            "Ersetzt keine Steuer- oder Rechtsberatung. Massgeblich ist die Freigabe durch die "
            "verantwortliche Pruefperson (Human Oversight, Art. 14 VO (EU) 2024/1689)."
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
        "# Compliance-Pruefzertifikat",
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
    if score.get("cap_applied"):
        lines += [f"> {score['cap_applied']}", ""]

    lines += ["## § 14 Abs. 4 UStG – Pflichtangaben", "", "| Merkmal | Norm | Status | Hinweis |", "|---|---|---|---|"]
    for check in report["ustg_matrix"]:
        lines.append(
            f"| {_md(check['label'])} | {_md(check.get('legal_reference'))} | "
            f"{_STATUS_LABELS.get(check['status'], check['status'])} | {_md(check.get('detail'))} |"
        )
    ai = report["ai_act"]
    lines += [
        "",
        "## EU AI Act (VO (EU) 2024/1689)",
        "",
        f"- **Einstufung:** {ai['risk_label']}",
        f"- **Anhang III:** {', '.join(ai['annex_iii']) or '-'}",
        f"- **Begruendung:** {_md(ai['reasoning'])}",
    ]
    if ai["article_references"]:
        lines.append(f"- **Einschlaegige Artikel:** {', '.join(ai['article_references'])}")
    lines += ["", "## Mathematische Validitaet", ""]
    for check in report["math_checks"]:
        lines.append(f"- {check['label']}: **{_STATUS_LABELS.get(check['status'])}** {_md(check.get('detail')) if check.get('detail') else ''}")
    gdpr = report["gdpr"]
    lines += ["", "## DSGVO", "", f"- **Risiko:** {_md(gdpr['risk_level'])}", f"- **Treffer:** {len(gdpr['findings'])} (maskiert)"]
    for finding in gdpr["findings"][:20]:
        lines.append(f"  - {finding['category']}: `{_md(finding['masked_value'])}` ({finding['source']})")
    sign = report["sign_off"]
    lines += ["", "## Pruefvermerk (Human Oversight, Art. 14)", ""]
    if sign:
        lines += [
            f"**{sign['status']}** durch **{_md(sign['auditor_name'])}** am {sign['sealed_at']}  ",
            f"Notiz: {_md(sign['note'])}  ",
            f"Siegel-Hash: `{sign['ledger_entry_hash']}`",
        ]
    else:
        lines.append("_Noch nicht versiegelt._")
    lines += ["", "---", f"_{report['disclaimer']}_", f"_Erstellt: {report['generated_at']} · {report['generator']}_", ""]
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
            f"<td>{_e(c.get('detail') or '')}</td></tr>"
            for c in checks
        ) or "<tr><td colspan='4'>Keine Pruefpunkte.</td></tr>"

    findings = "".join(
        f"<tr><td>{_e(f['category'])}</td><td class='mono'>{_e(f['masked_value'])}</td>"
        f"<td>{_e(f['source'])}</td><td>{f['confidence'] * 100:.0f} %</td></tr>"
        for f in report["gdpr"]["findings"][:25]
    ) or "<tr><td colspan='4'>Keine personenbezogenen Daten erkannt.</td></tr>"

    seal_block = (
        f"""<div class="sealbox {'ok' if approved else 'bad'}">{_SEAL_SVG}
        <div><div class="sealtitle">{'GEPRUEFT &amp; FREIGEGEBEN' if approved else 'GEPRUEFT – FREIGABE VERWEIGERT'}</div>
        <div>Pruefer: <strong>{_e(sign['auditor_name'])}</strong></div>
        <div>Versiegelt: {_e(sign['sealed_at'])}</div>
        <div class="mono small">Siegel-Hash {_e(sign['ledger_entry_hash'])}</div>
        {f"<div class='small'>Notiz: {_e(sign['note'])}</div>" if sign.get('note') else ''}</div></div>"""
        if sign
        else '<div class="draft">ENTWURF – noch nicht durch eine Pruefperson versiegelt (Art. 14 EU AI Act)</div>'
    )

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pruefzertifikat {_e(doc['filename'])}</title>
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
.draft {{ margin-top: 18px; padding: 10px; border: 1px dashed #94a3b8; color: #475569; text-align: center; border-radius: 8px; }}
footer {{ margin-top: 18px; font-size: 8pt; color: #64748b; }}
@media print {{ body {{ background: #fff; }} .page {{ border: 0; margin: 0; padding: 0; max-width: none; }} h2, table, .sealbox {{ break-inside: avoid; }} }}
</style></head>
<body><main class="page">
<div class="head">
  <div><div class="kicker">Compliance-Pruefzertifikat · VO (EU) 2024/1689 · § 14 UStG · DSGVO</div>
  <h1>{_e(doc['filename'])}</h1>
  <div class="small">Audit-ID <span class="mono">{_e(report['audit_id'])}</span></div></div>
  <div class="score {_e(band)}"><b>{_e(score.get('score', '–'))}</b>/100<div class="small">{_e(score.get('band_label'))}</div></div>
</div>
<div class="verdict {'bad' if report['release_blocked'] else 'ok'}">{_e(report['release_recommendation'])}{f" · {_e(score.get('cap_applied'))}" if score.get('cap_applied') else ''}</div>

<h2>Dokument &amp; Pruefkette</h2>
<div class="grid small">
<div>SHA-256 Dokument</div><div class="mono">{_e(doc['sha256'])}</div>
<div>Ledger-Eintrag</div><div class="mono">{_e(report['ledger']['entry_hash'])}</div>
<div>Vorgaenger-Hash</div><div class="mono">{_e(report['ledger']['previous_hash'])}</div>
<div>Prompt-Hash</div><div class="mono">{_e(report['ledger']['prompt_hash'])}</div>
<div>Pruefzeitpunkt (UTC)</div><div>{_e(report['ledger']['timestamp_utc'])}</div>
<div>Hash-Kette</div><div>{'intakt' if report['ledger']['chain_valid'] else 'GEBROCHEN'} ({_e(report['ledger']['chain_entries'])} Eintraege)</div>
<div>Modell / Provider</div><div>{_e(report['inference']['model'])} / {_e(report['inference']['provider'])}</div>
<div>Regelwerk</div><div>{_e(score.get('ruleset_version'))}</div>
</div>

<h2>§ 14 Abs. 4 UStG – Pflichtangaben</h2>
<table><thead><tr><th>Merkmal</th><th>Norm</th><th>Status</th><th>Hinweis</th></tr></thead><tbody>{rows(report['ustg_matrix'])}</tbody></table>

<h2>EU AI Act</h2>
<p><strong>{_e(ai['risk_label'])}</strong>{(' · ' + _e(', '.join(ai['annex_iii']))) if ai['annex_iii'] else ''}</p>
<p class="small">{_e(ai['reasoning'])}</p>
{f"<p class='small'>Einschlaegige Pflichten: {_e(', '.join(ai['article_references']))}</p>" if ai['article_references'] else ''}

<h2>Mathematische Validitaet</h2>
<table><thead><tr><th>Pruefung</th><th>Norm</th><th>Status</th><th>Hinweis</th></tr></thead><tbody>{rows(report['math_checks'])}</tbody></table>

<h2>DSGVO – PII-Befunde (maskiert)</h2>
<table><thead><tr><th>Kategorie</th><th>Wert</th><th>Quelle</th><th>Konfidenz</th></tr></thead><tbody>{findings}</tbody></table>

{seal_block}
<footer>{_e(report['disclaimer'])}<br>Erstellt {_e(report['generated_at'])} · {_e(report['generator'])}</footer>
</main></body></html>"""
