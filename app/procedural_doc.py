"""GoBD-Verfahrensdokumentation fuer den Pruefprozess (Entwurf aus dem Systemzustand).

Gliederung nach GoBD Rz. 153 (BMF-Schreiben vom 28.11.2019 in der geltenden
Fassung): allgemeine Beschreibung, Anwenderdokumentation, technische
Systemdokumentation, Betriebsdokumentation.  Ein Anhang stellt den Bezug zum
konkreten Beleg her (Pruefpfad, Ledger-Eintraege, Siegel, Aufbewahrungsfrist).

Einordnung
----------
Eine Verfahrensdokumentation beschreibt das *Verfahren* eines Unternehmens,
nicht einen einzelnen Beleg.  Das System kennt seine eigene Technik genau, die
Organisation des Unternehmens dagegen nicht: Verantwortliche, Rollen und
Intervalle sind deshalb als ``[vom Unternehmen zu ergaenzen]`` markiert.  Der
Generator liefert einen belastbaren technischen Kern, keinen fertigen
Pruefungsnachweis.  Fuer ersetzendes Scannen gelten ergaenzend die
Muster-Verfahrensdokumentation von BStBK/DStV und die BSI TR-03138 (RESISCAN) -
das System scannt nicht und ist davon nicht erfasst.

Aufbewahrung: 10 Jahre als Organisationsunterlage (§ 147 Abs. 1 Nr. 1 AO).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from app.audit_ledger import AuditEventType, ChainVerification, LedgerEntry
from app.config import APP_TITLE, APP_VERSION, Settings
from app.db import DocumentRecord, utcnow
from app.extractors.einvoice import MAX_XML_BYTES
from app.llm import PROMPT_HASH
from app.retention import RETENTION_NOTE, RETENTION_RULES, invoice_retention
from app.scoring import RULESET_VERSION
from app.services import STRUCTURED_PROVIDER, parse_einvoice, parse_extraction, parse_scorecard, parse_sign_off

TODO = "[vom Unternehmen zu ergänzen]"

_EVENT_LABELS = {
    AuditEventType.ANALYSIS: "Analyse",
    AuditEventType.SIGN_OFF: "Prüfer-Siegel",
    AuditEventType.HUMAN_OVERRIDE: "Übersteuerung durch Prüfperson",
}

_PATH_LABELS = {
    STRUCTURED_PROVIDER: "XML-Pfad (EN 16931, deterministisch, ohne KI)",
    "reference": "Referenz-Audit der Musterdaten (vorberechnete KI-Antwort)",
    "local": "LLM-Pfad, lokale Inferenz (Ollama)",
    "gemini": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (Google Gemini)",
    "anthropic": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (Anthropic Claude)",
    "openai": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (OpenAI)",
}


def _fmt_ts(value: Any) -> str:
    if not value:
        return "–"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return str(value)
    return parsed.strftime("%d.%m.%Y, %H:%M:%S UTC")


def build_procedural_doc(
    *,
    settings: Settings,
    runtime: Any | None,
    record: DocumentRecord | None,
    entries: list[LedgerEntry],
    verification: ChainVerification,
    signing_key: dict[str, str],
) -> dict[str, Any]:
    """Strukturierte Verfahrensdokumentation (Grundlage fuer HTML und Markdown)."""
    snapshot = runtime.snapshot() if runtime is not None else None
    inference_mode = snapshot.inference_mode.value if snapshot else settings.inference_mode
    model = snapshot.active_model if snapshot else settings.ollama_model
    pii_level = snapshot.pii_strictness.value if snapshot else settings.pii_strictness
    dialect = settings.resolved_database_url.split(":", 1)[0].split("+", 1)[0]

    sections: list[dict[str, Any]] = [
        {
            "number": "1",
            "title": "Allgemeine Beschreibung",
            "blocks": [
                {
                    "heading": "1.1 Zweck und Geltungsbereich",
                    "text": (
                        f"Der {APP_TITLE} unterstützt die Vorprüfung eingehender Rechnungen und Verträge: "
                        "Pflichtangaben nach § 14 Abs. 4 UStG, strukturierte E-Rechnungen nach EN 16931, "
                        "Risikoeinstufung nach der VO (EU) 2024/1689 (EU AI Act) und Datenschutz nach DSGVO. "
                        "Das System trifft keine Buchungen und ersetzt keine Freigabe: Maßgeblich ist die "
                        "Entscheidung der Prüfperson (Human Oversight)."
                    ),
                },
                {
                    "heading": "1.2 Belegarten",
                    "table": {
                        "head": ["Belegart", "Verarbeitung", "Maßgeblicher Teil"],
                        "rows": [
                            ["Hybride E-Rechnung (ZUGFeRD 2.x, Factur-X)", "eingebettetes XML aus dem PDF/A-3-Container", "XML-Datensatz (BMF 15.10.2024, Rz. 36)"],
                            ["XRechnung (CII oder UBL, .xml)", "XML-Datensatz", "XML-Datensatz"],
                            ["ZUGFeRD MINIMUM / BASIC WL", "XML gelesen, Analyse über den Bildteil", "Bildteil (keine E-Rechnung)"],
                            ["PDF ohne XML („sonstige Rechnung“)", "Textlayer, KI-Extraktion, Regex-Gegenprobe", "PDF"],
                            ["Verträge", "Textlayer, KI-Risikoeinstufung", "PDF"],
                        ],
                    },
                },
                {
                    "heading": "1.3 Organisation und Verantwortlichkeiten",
                    "table": {
                        "head": ["Funktion", "Person / Stelle"],
                        "rows": [
                            ["Verantwortlich für das Verfahren (Prozesseigner)", TODO],
                            ["Prüfpersonen mit Freigabebefugnis", TODO],
                            ["IT-Betrieb und Datensicherung", TODO],
                            ["Datenschutzbeauftragte Person", TODO],
                            ["Freigabe dieser Verfahrensdokumentation (Name, Datum)", TODO],
                        ],
                    },
                },
                {
                    "heading": "1.4 Rechtliche Grundlagen",
                    "list": [
                        "§§ 145–147 AO, GoBD (BMF-Schreiben vom 28.11.2019 in der jeweils geltenden Fassung), "
                        "insbesondere Rz. 58 ff. (Unveränderbarkeit) und Rz. 151 ff. (Verfahrensdokumentation)",
                        "§ 14 Abs. 1 und 4, § 14b, § 15 UStG; EN 16931; BMF-Schreiben vom 15.10.2024 und 15.10.2025",
                        "§ 5 Abs. 1 ERechV (Leitweg-ID bei Rechnungen an den Bund)",
                        "VO (EU) 2024/1689: Art. 12 (Protokollierung), Art. 14 (menschliche Aufsicht), "
                        "Art. 26 Abs. 6 (Aufbewahrung der Protokolle mindestens sechs Monate)",
                        "DSGVO: Art. 4 Nr. 5 (Pseudonymisierung), Art. 5, 9, 25, 32",
                    ],
                },
                {
                    "heading": "1.5 Aufbewahrungsfristen",
                    "table": {
                        "head": ["Unterlage", "Frist", "Rechtsgrundlage"],
                        "rows": [[rule.subject, f"{rule.years} Jahre", rule.basis] for rule in RETENTION_RULES],
                    },
                    "text": RETENTION_NOTE,
                },
            ],
        },
        {
            "number": "2",
            "title": "Anwenderdokumentation",
            "blocks": [
                {
                    "heading": "2.1 Belegfluss",
                    "list": [
                        "Eingang: Upload einzeln oder im Stapel (PDF oder XML); Weiterleitung aus dem Posteingang: " + TODO,
                        "Validierung: Dateityp, Größe, PDF-Signatur und Textlayer bzw. XML ohne DTD und Entitäten; "
                        "unlesbare Dateien werden nicht gespeichert",
                        "Ablage: Original bitgenau mit SHA-256; bei hybriden Rechnungen wird der XML-Datensatz "
                        "gelesen und mit dem Bildteil abgeglichen",
                        "Analyse: E-Rechnungen deterministisch aus dem XML; übrige Belege über ein Sprachmodell "
                        "(lokal oder über das Privacy Gateway), Ergebnis immer mit Regex-Gegenprobe",
                        "Bewertung: deterministische Scorecard (0–100) nach Regelwerk " + RULESET_VERSION,
                        "Prüfung: Prüfperson sichtet Befunde im Inspektor; Übersteuerung der KI-Einstufung "
                        "nur mit Begründung und Rechtsnorm (Art. 14 Abs. 4 lit. d AI Act)",
                        "Siegel: Freigabe oder Ablehnung durch die Prüfperson als signierter Ledger-Eintrag",
                        "Export: Prüfzertifikat und Prüfdatenpaket (ZIP); Übergabe an ERP bzw. Archiv: " + TODO,
                    ],
                },
                {
                    "heading": "2.2 Vier-Augen-Prinzip",
                    "text": (
                        "Übersteuerung (Override) und Siegel werden je mit Namen der handelnden Person im Ledger "
                        "festgehalten. Empfohlen ist, dass Übersteuerung und abschließende Freigabe durch "
                        "verschiedene Personen erfolgen; der Anhang weist für den Beleg aus, ob das der Fall war. "
                        "Der Name im System ist selbst erklärt – die Identität muss über die vorgelagerte "
                        "Anmeldung (Single Sign-on) belegt werden: " + TODO
                    ),
                },
                {
                    "heading": "2.3 Rollen und Berechtigungen",
                    "table": {
                        "head": ["Rolle", "Aufgaben im System", "Zuordnung"],
                        "rows": [
                            ["Sachbearbeitung", "Upload, Analyse starten, Befunde lesen, Copilot", TODO],
                            ["Prüfperson", "Übersteuerung der Einstufung, Siegel (Freigabe/Ablehnung)", TODO],
                            ["Administration", "Inferenz-Modus, API-Schlüssel, PII-Strenge", TODO],
                            ["Revision / Betriebsprüfung", "Lesezugriff, Zertifikat, Prüfdatenpaket", TODO],
                        ],
                    },
                    "text": (
                        "Technisch schützt ein gemeinsamer API-Schlüssel (X-API-Key) alle Endpunkte; eine "
                        "Rollentrennung erfolgt über das vorgelagerte Identitäts- und Zugriffsmanagement."
                    ),
                },
                {
                    "heading": "2.4 Eskalationsmatrix",
                    "table": {
                        "head": ["Befund", "Maßnahme", "Zuständig"],
                        "rows": [
                            ["Freigabe gesperrt (Pflichtangabe fehlt, Rechenfehler)", "Berichtigte Rechnung beim Lieferanten anfordern", "Kreditorenbuchhaltung"],
                            ["IBAN mit falscher Prüfziffer", "Zahlung stoppen, Bankverbindung auf bekanntem Weg verifizieren", "Kreditorenbuchhaltung / Treasury"],
                            ["Abweichung XML ↔ Bildteil", "Mit dem Lieferanten klären; gebucht wird nach dem XML", "Kreditorenbuchhaltung"],
                            ["Leitweg-ID fehlt oder ungültig (B2G)", "Rechnungssteller zur Korrektur auffordern", "Rechnungsstellung / Vergabestelle"],
                            ["Hochrisiko-KI ohne Konformitätsnachweis", "Nachweis nach Art. 43 anfordern, Betreiberpflichten nach Art. 26 prüfen", "Compliance / Rechtsabteilung"],
                            ["Besondere Kategorien (Art. 9/10 DSGVO)", "Zugriff beschränken, Rechtsgrundlage prüfen", "Datenschutzbeauftragte Person"],
                            ["Hash-Kette gebrochen oder Signatur ungültig", "Sicherheitsvorfall eröffnen, Datenbank sichern, extern verankerten Kopf-Hash vergleichen", "IT-Sicherheit"],
                        ],
                    },
                    "text": "Zuständigkeiten sind Vorschläge: " + TODO,
                },
            ],
        },
        {
            "number": "3",
            "title": "Technische Systemdokumentation",
            "blocks": [
                {
                    "heading": "3.1 Systemstand",
                    "table": {
                        "head": ["Merkmal", "Wert"],
                        "rows": [
                            ["Anwendung", f"{APP_TITLE} v{APP_VERSION}"],
                            ["Regelwerk der Scorecard", RULESET_VERSION],
                            ["Prompt-Hash (Fingerabdruck der Prompt-Version)", PROMPT_HASH],
                            ["Datenbank", dialect],
                            ["Aktiver Inferenz-Modus / Modell", f"{inference_mode} / {model}"],
                            ["Schwärzungsstufe der Textansicht", pii_level],
                            ["Authentifizierung (X-API-Key)", "aktiv" if settings.auth_enabled else "nicht aktiv – produktiv zwingend setzen"],
                        ],
                    },
                },
                {
                    "heading": "3.2 Schnittstellen",
                    "list": [
                        "REST-API (FastAPI, OpenAPI unter /docs): Upload, Analyse, Detail, Siegel, Übersteuerung, "
                        "Zertifikat, Prüfdatenpaket, Verfahrensdokumentation, Ledger",
                        "Inferenz: Ollama (lokal) oder Gemini / Claude / OpenAI über HTTPS, Cloud-Aufrufe nur nach "
                        "Pseudonymisierung im Privacy Gateway",
                        "Ausgaben: Zertifikat (HTML/Markdown/JSON), Prüfdatenpaket (ZIP mit signiertem Manifest)",
                        "Anbindung an ERP und Archiv: " + TODO,
                    ],
                },
                {
                    "heading": "3.3 Integritätssicherung",
                    "list": [
                        "Jeder Beleg erhält beim Eingang eine SHA-256-Prüfsumme; das Original wird nicht verändert.",
                        "Prüfprotokoll (Tabelle audit_trails): lineare SHA-256-Hash-Kette über das kanonische JSON "
                        "jedes Eintrags (sortierte Schlüssel, UTF-8), Genesis 0…0; Datenbank-Trigger verhindern "
                        "UPDATE und DELETE.",
                        "Einträge natürlicher Personen (Siegel, Übersteuerung) und Manifeste der Prüfdatenpakete sind "
                        "zusätzlich mit Ed25519 signiert; die Signatur deckt den Vorgänger-Hash ab.",
                        f"Öffentlicher Schlüssel, Fingerabdruck: {signing_key.get('fingerprint', '–')}",
                        f"Kettenprüfung zum Erstellungszeitpunkt: {'intakt' if verification.valid else 'GEBROCHEN'}, "
                        f"{verification.entries} Einträge, davon {verification.signed_entries} signiert; "
                        f"Kopf-Hash {verification.head_hash}",
                        "Kopf-Hash regelmäßig außerhalb des Systems verankern (Ticket, WORM-Speicher, qualifizierter "
                        "Zeitstempel): " + TODO,
                    ],
                },
                {
                    "heading": "3.4 XML-Verarbeitung (EN 16931)",
                    "list": [
                        "Parser: defusedxml mit forbid_dtd=True – keine DTDs, keine Entitäten, keine externen "
                        f"Referenzen; Obergrenze {MAX_XML_BYTES // 1_048_576} MB je Datensatz",
                        "Syntaxen: UN/CEFACT CII und OASIS UBL 2.1; Profil aus BT-24",
                        "Geprüft: Pflichtfelder, Summenregeln BR-CO-10/13/14/15, BR-DE-15, Steuer je Satz",
                        "Nicht geprüft: XSD und Schematron (KoSIT-Validator) – Annahme beim Empfänger nicht garantiert",
                    ],
                },
                {
                    "heading": "3.5 KI-Komponente",
                    "list": [
                        "Zwei getrennte Modellaufrufe (Extraktion, Compliance-Audit) mit striktem JSON-Vertrag",
                        "Deterministische Kontrollen nach dem Modell: Prüfziffern, Regex-PII-Scan, "
                        "Eskalation bei Anhang-III-Kategorien, Maskierungszwang vor dem Speichern",
                        "Der Score entsteht nicht im Modell, sondern im versionierten Regelwerk",
                        "Jeder Ledger-Eintrag hält Modell, Provider und Prompt-Hash fest (Art. 12 AI Act)",
                    ],
                },
            ],
        },
        {
            "number": "4",
            "title": "Betriebsdokumentation",
            "blocks": [
                {
                    "heading": "4.1 Datensicherung",
                    "text": (
                        "Zu sichern sind das Datenverzeichnis mit Datenbank, Originalbelegen und Schlüsseldateien "
                        "(.settings.key, .signing.key). Ohne den Signaturschlüssel lassen sich neue Prüfer-Einträge "
                        "nicht mehr dem System zuordnen; bestehende bleiben über den hinterlegten Fingerabdruck "
                        "prüfbar. Sicherungsintervall, Aufbewahrungsort und Wiederherstellungstest: " + TODO
                    ),
                },
                {
                    "heading": "4.2 Unveränderbarkeit (WORM-Prinzip)",
                    "text": (
                        "Originale werden nur einmal geschrieben; das Prüfprotokoll ist append-only (Trigger) und "
                        "hash-verkettet. Die Datenbank selbst ist kein WORM-Speicher: Gegen einen Angreifer mit "
                        "Vollzugriff auf die Datenbankdatei schützt erst die externe Verankerung des Kopf-Hashes bzw. "
                        "die Ablage in einem revisionssicheren Archiv. Archivsystem: " + TODO
                    ),
                },
                {
                    "heading": "4.3 Protokollierung von Systemänderungen",
                    "list": [
                        "Anwendungsversion, Regelwerk und Prompt-Hash stehen in jedem Ledger-Eintrag; ein Wechsel "
                        "von Regeln oder Prompts ist dadurch je Prüfung nachvollziehbar.",
                        "Änderungen der Einstellungen (Inferenz-Modus, Schlüssel, PII-Strenge) werden im "
                        "Anwendungsprotokoll (JSON-Logs mit Request-ID) festgehalten, nicht im Ledger.",
                        "Software-Updates und Änderungen dieser Dokumentation sind zu historisieren "
                        "(Versionsstand, Datum, freigebende Person): " + TODO,
                    ],
                },
                {
                    "heading": "4.4 Zugriffsschutz und IT-Sicherheit",
                    "list": [
                        "API-Schlüssel (X-API-Key), Rate-Limit je Client-IP",
                        "Provider-Schlüssel Fernet-verschlüsselt gespeichert, nur maskiert ausgeliefert",
                        "Zertifikate mit restriktiver Content-Security-Policy, alle Werte HTML-escaped",
                        "Netzwerkzonen, Härtung und Patch-Management: " + TODO,
                    ],
                },
            ],
        },
    ]

    annex = _document_annex(record, entries) if record is not None else None
    return {
        "title": "Verfahrensdokumentation nach GoBD",
        "subtitle": "Prüfung eingehender Rechnungen und Verträge mit dem Enterprise Compliance Agent",
        "generated_at": utcnow().isoformat(),
        "version": APP_VERSION,
        "ruleset_version": RULESET_VERSION,
        "status": (
            "Entwurf aus dem Systemzustand. Markierte Stellen ergänzt das Unternehmen; erst mit Freigabe durch "
            "die verantwortliche Person ist die Dokumentation vollständig."
        ),
        "retention": "Aufbewahrung 10 Jahre als Organisationsunterlage (§ 147 Abs. 1 Nr. 1, Abs. 3 AO).",
        "basis": (
            "Gliederung nach GoBD Rz. 153. Eine fehlende oder unzureichende Verfahrensdokumentation ist nach "
            "GoBD Rz. 155 nur dann ein formeller Mangel mit sachlichem Gewicht, wenn sie die Nachvollziehbarkeit "
            "und Nachprüfbarkeit beeinträchtigt. Für ersetzendes Scannen gelten ergänzend die "
            "Muster-Verfahrensdokumentation von BStBK/DStV und die BSI TR-03138 (RESISCAN); das System scannt "
            "nicht und ist davon nicht erfasst."
        ),
        "sections": sections,
        "annex": annex,
    }


def _document_annex(record: DocumentRecord, entries: list[LedgerEntry]) -> dict[str, Any]:
    """Anhang A: Pruefpfad des konkreten Belegs."""
    extraction = parse_extraction(record)
    scorecard = parse_scorecard(record)
    sign_off = parse_sign_off(record)
    einvoice = parse_einvoice(record)
    ordered = sorted(entries, key=lambda entry: entry.seq or 0)

    override_people = {
        str((entry.details or {}).get("auditor_name"))
        for entry in ordered
        if entry.event_type == AuditEventType.HUMAN_OVERRIDE
    }
    seal_person = sign_off.auditor_name if sign_off else None
    if not override_people:
        four_eyes = "Keine Übersteuerung – Vier-Augen-Prüfung nicht berührt."
    elif seal_person is None:
        four_eyes = "Übersteuert, aber noch nicht versiegelt."
    elif seal_person in override_people:
        four_eyes = f"Nicht gewahrt: „{seal_person}“ hat übersteuert und versiegelt."
    else:
        four_eyes = "Gewahrt: Übersteuerung und Siegel durch verschiedene Personen."

    retention = None
    if extraction is not None and extraction.doc_type.value == "invoice":
        period = invoice_retention(extraction.document_date)
        retention = (
            f"{period.years} Jahre, bis mindestens 31.12.{period.until.year} "
            f"(Finanzsektor: 10 Jahre, bis 31.12.{period.financial_sector_until.year}); {period.basis}"
            if period
            else "Belegdatum unbekannt – Frist ab Schluss des Entstehungsjahres (§ 147 Abs. 4 AO)."
        )
    elif extraction is not None:
        retention = (
            "Abhängig von der Funktion des Dokuments: als Buchungsbeleg 8 Jahre, als empfangener "
            "Handels- oder Geschäftsbrief 6 Jahre (§ 147 Abs. 1, Abs. 3 AO)."
        )

    rows = [
        ["Dokument", record.original_filename],
        ["SHA-256", record.sha256],
        ["Eingang", _fmt_ts(record.created_at.isoformat())],
        ["Belegart", (f"E-Rechnung, {einvoice.profile} ({einvoice.syntax})" if einvoice and not einvoice.error
                      else (extraction.doc_type.value if extraction else "noch nicht analysiert"))],
        ["Analysepfad", _PATH_LABELS.get(record.provider or "", record.provider or "–")],
        ["Score / Band", f"{scorecard.score}/100 ({scorecard.band_label})" if scorecard else "–"],
        ["Freigabeempfehlung", scorecard.release_recommendation if scorecard else "–"],
        ["Siegel", (f"{sign_off.status.value} durch {sign_off.auditor_name} am {_fmt_ts(sign_off.sealed_at.isoformat())}"
                    if sign_off else "nicht versiegelt")],
        ["Vier-Augen-Prinzip", four_eyes],
        ["Aufbewahrung", retention or "–"],
    ]
    return {
        "title": "Anhang A – Prüfpfad des Belegs",
        "rows": rows,
        "ledger": [
            {
                "seq": entry.seq,
                "event": _EVENT_LABELS.get(entry.event_type, entry.event_type),
                "timestamp": _fmt_ts(entry.timestamp_utc),
                "actor": (entry.details or {}).get("auditor_name") or entry.model_name or "–",
                "score": entry.compliance_score,
                "entry_hash": entry.entry_hash,
                "signed": entry.signature is not None,
            }
            for entry in ordered
        ],
    }


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------


def _md(value: Any) -> str:
    return ("–" if value in (None, "") else str(value)).replace("|", "/").replace("\n", " ")


def render_markdown(doc: dict[str, Any]) -> str:
    lines = [
        f"# {doc['title']}",
        "",
        f"_{doc['subtitle']}_",
        "",
        f"- **Stand:** {_fmt_ts(doc['generated_at'])} · v{doc['version']} · Regelwerk {doc['ruleset_version']}",
        f"- **Status:** {doc['status']}",
        f"- **{doc['retention']}**",
        "",
        f"> {doc['basis']}",
        "",
    ]
    for section in doc["sections"]:
        lines += [f"## {section['number']}. {section['title']}", ""]
        for block in section["blocks"]:
            lines += [f"### {block['heading']}", ""]
            if "table" in block:
                head = block["table"]["head"]
                lines.append("| " + " | ".join(head) + " |")
                lines.append("|" + "---|" * len(head))
                lines += ["| " + " | ".join(_md(cell) for cell in row) + " |" for row in block["table"]["rows"]]
                lines.append("")
            if "list" in block:
                lines += [f"- {item}" for item in block["list"]]
                lines.append("")
            if "text" in block:
                lines += [block["text"], ""]
    annex = doc.get("annex")
    if annex:
        lines += [f"## {annex['title']}", "", "| Merkmal | Wert |", "|---|---|"]
        lines += [f"| {_md(key)} | {_md(value)} |" for key, value in annex["rows"]]
        lines += ["", "| Seq | Ereignis | Zeitpunkt | Person / Modell | Score | Eintrags-Hash | Signatur |",
                  "|---:|---|---|---|---:|---|---|"]
        lines += [
            f"| {e['seq']} | {e['event']} | {e['timestamp']} | {_md(e['actor'])} | {_md(e['score'])} | "
            f"`{e['entry_hash'][:16]}…` | {'Ed25519' if e['signed'] else '–'} |"
            for e in annex["ledger"]
        ]
        lines.append("")
    return "\n".join(lines)


def _e(value: Any) -> str:
    return html.escape("–" if value in (None, "") else str(value))


def _todo(text: str) -> str:
    """Hebt Platzhalter hervor (nach dem Escaping, daher sicher)."""
    return _e(text).replace(html.escape(TODO), f'<span class="todo">{html.escape(TODO)}</span>')


def render_html(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for section in doc["sections"]:
        parts.append(f"<h2>{_e(section['number'])}. {_e(section['title'])}</h2>")
        for block in section["blocks"]:
            parts.append(f"<h3>{_e(block['heading'])}</h3>")
            if "table" in block:
                head = "".join(f"<th>{_e(cell)}</th>" for cell in block["table"]["head"])
                rows = "".join(
                    "<tr>" + "".join(f"<td>{_todo(str(cell))}</td>" for cell in row) + "</tr>"
                    for row in block["table"]["rows"]
                )
                parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
            if "list" in block:
                parts.append("<ul>" + "".join(f"<li>{_todo(item)}</li>" for item in block["list"]) + "</ul>")
            if "text" in block:
                parts.append(f"<p>{_todo(block['text'])}</p>")

    annex = doc.get("annex")
    if annex:
        facts = "".join(
            f"<tr><th>{_e(key)}</th><td{' class=mono' if key == 'SHA-256' else ''}>{_e(value)}</td></tr>"
            for key, value in annex["rows"]
        )
        ledger = "".join(
            f"<tr><td class='num'>{_e(e['seq'])}</td><td>{_e(e['event'])}</td><td>{_e(e['timestamp'])}</td>"
            f"<td>{_e(e['actor'])}</td><td class='num'>{_e(e['score'])}</td>"
            f"<td class='mono'>{_e(e['entry_hash'][:16])}…</td><td>{'Ed25519' if e['signed'] else '–'}</td></tr>"
            for e in annex["ledger"]
        ) or "<tr><td colspan='7'>Noch keine Ledger-Einträge.</td></tr>"
        parts.append(
            f"<h2 class='annex'>{_e(annex['title'])}</h2><table class='facts'><tbody>{facts}</tbody></table>"
            "<table><thead><tr><th class='num'>Seq</th><th>Ereignis</th><th>Zeitpunkt</th><th>Person / Modell</th>"
            f"<th class='num'>Score</th><th>Eintrags-Hash</th><th>Signatur</th></tr></thead><tbody>{ledger}</tbody></table>"
        )

    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(doc['title'])}</title>
<style>
@page {{ size: A4; margin: 16mm 14mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Inter, "Segoe UI", Helvetica, Arial, sans-serif; color: #0f172a; background: #f1f5f9; margin: 0; font-size: 10.5pt; line-height: 1.5; }}
.page {{ background: #fff; max-width: 210mm; margin: 12px auto; padding: 18mm 16mm; border: 1px solid #e2e8f0; }}
h1 {{ font-size: 18pt; margin: 0; }}
h2 {{ font-size: 12pt; margin: 22px 0 6px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }}
h3 {{ font-size: 10.5pt; margin: 14px 0 4px; }}
p, li {{ max-width: 75ch; }}
.kicker {{ font-size: 8pt; letter-spacing: .12em; text-transform: uppercase; color: #475569; }}
.meta {{ margin-top: 10px; font-size: 9pt; color: #334155; }}
.note {{ margin-top: 12px; padding: 8px 12px; border: 1px dashed #94a3b8; border-radius: 8px; font-size: 9pt; color: #334155; }}
.todo {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; border-radius: 4px; padding: 0 4px; white-space: nowrap; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
th, td {{ text-align: left; padding: 5px 6px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
th {{ font-size: 8pt; text-transform: uppercase; letter-spacing: .06em; color: #475569; }}
.facts th {{ width: 28%; text-transform: none; letter-spacing: 0; font-size: 9pt; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.mono {{ font-family: "JetBrains Mono", Consolas, monospace; font-size: 8.5pt; }}
footer {{ margin-top: 18px; font-size: 8pt; color: #64748b; }}
@media print {{
  body {{ background: #fff; }}
  .page {{ border: 0; margin: 0; padding: 0; max-width: none; }}
  h2, h3 {{ break-after: avoid; }}
  tr, .note {{ break-inside: avoid; }}
  thead {{ display: table-header-group; }}
  h2.annex {{ break-before: page; }}
}}
</style></head>
<body><main class="page">
<div class="kicker">GoBD Rz. 151 ff. · § 147 AO · VO (EU) 2024/1689</div>
<h1>{_e(doc['title'])}</h1>
<div class="meta">{_e(doc['subtitle'])}<br>Stand {_e(_fmt_ts(doc['generated_at']))} · {_e(APP_TITLE)} v{_e(doc['version'])} · Regelwerk {_e(doc['ruleset_version'])}</div>
<div class="note"><strong>{_e(doc['status'])}</strong><br>{_e(doc['retention'])}</div>
<p class="meta">{_e(doc['basis'])}</p>
{''.join(parts)}
<footer>Automatisch erzeugter Entwurf. Keine Steuer- oder Rechtsberatung.</footer>
</main></body></html>"""
