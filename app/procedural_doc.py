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
from app.print_layout import BASE_CSS, page_rules
from app.retention import RETENTION_NOTE, RETENTION_RULES, invoice_retention
from app.scoring import RULESET_VERSION
from app.services import STRUCTURED_PROVIDER, parse_einvoice, parse_extraction, parse_scorecard, parse_sign_off

ZU_ERGAENZEN = "[vom Unternehmen zu ergänzen]"

_EVENT_LABELS = {
    AuditEventType.ANALYSIS: "Analyse",
    AuditEventType.SIGN_OFF: "Prüfer-Siegel",
    AuditEventType.HUMAN_OVERRIDE: "Übersteuerung durch Prüfperson",
    AuditEventType.PROVIDER_FAILOVER: "Provider-Wechsel nach Ausfall",
    AuditEventType.ARCHIVE: "Archiviert",
    AuditEventType.UNARCHIVE: "Aus dem Archiv geholt",
}

_EVENT_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _EVENT_LABELS,
    "en": {
        AuditEventType.ANALYSIS: "Audit Analysis",
        AuditEventType.SIGN_OFF: "Auditor Seal",
        AuditEventType.HUMAN_OVERRIDE: "Human Override by Auditor",
        AuditEventType.PROVIDER_FAILOVER: "Provider Failover",
        AuditEventType.ARCHIVE: "Archived",
        AuditEventType.UNARCHIVE: "Unarchived",
    },
    "es": {
        AuditEventType.ANALYSIS: "Análisis",
        AuditEventType.SIGN_OFF: "Sello del auditor",
        AuditEventType.HUMAN_OVERRIDE: "Anulación por auditor",
        AuditEventType.PROVIDER_FAILOVER: "Cambio de proveedor",
        AuditEventType.ARCHIVE: "Archivado",
        AuditEventType.UNARCHIVE: "Desarchivado",
    },
}

_PATH_LABELS = {
    STRUCTURED_PROVIDER: "XML-Pfad (EN 16931, deterministisch, ohne KI)",
    "reference": "Referenz-Audit der Musterdaten (vorberechnete KI-Antwort)",
    "local": "LLM-Pfad, lokale Inferenz (Ollama)",
    "gemini": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (Google Gemini)",
    "anthropic": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (Anthropic Claude)",
    "openai": "LLM-Pfad, Cloud-Inferenz über Privacy Gateway (OpenAI)",
}

_PATH_LABELS_I18N: dict[str, dict[str, str]] = {
    "de": _PATH_LABELS,
    "en": {
        STRUCTURED_PROVIDER: "XML Path (EN 16931, deterministic, offline)",
        "reference": "Sample Reference Audit (precomputed AI response)",
        "local": "LLM Path, local inference (Ollama)",
        "gemini": "LLM Path, cloud inference via Privacy Gateway (Google Gemini)",
        "anthropic": "LLM Path, cloud inference via Privacy Gateway (Anthropic Claude)",
        "openai": "LLM Path, cloud inference via Privacy Gateway (OpenAI)",
    },
    "es": {
        STRUCTURED_PROVIDER: "Ruta XML (EN 16931, determinista, sin IA)",
        "reference": "Auditoría de referencia (respuesta precalculada)",
        "local": "Ruta LLM, inferencia local (Ollama)",
        "gemini": "Ruta LLM, nube vía Privacy Gateway (Google Gemini)",
        "anthropic": "Ruta LLM, nube vía Privacy Gateway (Anthropic Claude)",
        "openai": "Ruta LLM, nube vía Privacy Gateway (OpenAI)",
    },
}

_PD_UI: dict[str, dict[str, str]] = {
    "de": {
        "todo": ZU_ERGAENZEN,
        "title": "Verfahrensdokumentation nach GoBD",
        "subtitle": "Prüfung eingehender Rechnungen und Verträge mit dem Enterprise Compliance Agent",
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
        "stand": "Stand",
        "ruleset": "Regelwerk",
        "col_key": "Merkmal",
        "col_val": "Wert",
        "col_event": "Ereignis",
        "col_time": "Zeitpunkt",
        "col_actor": "Person / Modell",
        "col_hash": "Eintrags-Hash",
        "col_sig": "Signatur",
        "no_ledger": "Noch keine Ledger-Einträge.",
        "footer": "Automatisch erzeugter Entwurf. Keine Steuer- oder Rechtsberatung.",
        "annex_title": "Anhang A – Prüfpfad des Belegs",
        "row_doc": "Dokument",
        "row_in": "Eingang",
        "row_type": "Belegart",
        "row_path": "Analysepfad",
        "row_score": "Score / Band",
        "row_rec": "Freigabeempfehlung",
        "row_seal": "Siegel",
        "row_4eyes": "Vier-Augen-Prinzip",
        "row_ret": "Aufbewahrung",
        "not_analyzed": "noch nicht analysiert",
        "unsealed": "nicht versiegelt",
        "by": "durch",
        "on": "am",
    },
    "en": {
        "todo": "[to be completed by company]",
        "title": "GoBD Procedural Documentation",
        "subtitle": "Automated pre-audit of incoming invoices and contracts with Enterprise Compliance Agent",
        "status": (
            "System-generated technical draft. Marked placeholders must be completed by the organization prior to formal sign-off."
        ),
        "retention": "Retention: 10 years as organizational documentation (§ 147(1) No. 1, (3) German Fiscal Code AO).",
        "basis": (
            "Structured in four pillars per GoBD Rz. 153 (BMF Decree). Covers ingestion, SHA-256 integrity, Ed25519 seals, "
            "EU AI Act Art. 12/14 compliance and GDPR Privacy Gateway controls. Does not cover physical document scanning (TR-03138 RESISCAN)."
        ),
        "stand": "As of",
        "ruleset": "Ruleset",
        "col_key": "Attribute",
        "col_val": "Value",
        "col_event": "Event",
        "col_time": "Timestamp",
        "col_actor": "Actor / Model",
        "col_hash": "Entry Hash",
        "col_sig": "Signature",
        "no_ledger": "No ledger entries recorded yet.",
        "footer": "Automatically generated draft. Not binding tax or legal advice.",
        "annex_title": "Annex A – Document Audit Trail",
        "row_doc": "Document",
        "row_in": "Ingested",
        "row_type": "Document Type",
        "row_path": "Analysis Path",
        "row_score": "Score / Band",
        "row_rec": "Release Recommendation",
        "row_seal": "Seal",
        "row_4eyes": "Dual Control (4-Eyes)",
        "row_ret": "Retention",
        "not_analyzed": "not yet analyzed",
        "unsealed": "unsealed",
        "by": "by",
        "on": "on",
    },
    "es": {
        "todo": "[a completar por la empresa]",
        "title": "Documentación de procedimientos GoBD",
        "subtitle": "Pre-auditoría de facturas y contratos entrantes con Enterprise Compliance Agent",
        "status": (
            "Borrador técnico generado desde el sistema. Los campos marcados deben completarse por la empresa antes de la aprobación."
        ),
        "retention": "Conservación: 10 años como documentación organizativa (§ 147(1) n.º 1, (3) AO).",
        "basis": (
            "Estructurada en cuatro pilares según GoBD Rz. 153. Cubre ingesta, cadena SHA-256, sellos Ed25519, Reglamento de IA (Art. 12/14) "
            "y controles RGPD mediante Privacy Gateway. No cubre escaneo físico sustitutivo."
        ),
        "stand": "Fecha",
        "ruleset": "Reglamento",
        "col_key": "Característica",
        "col_val": "Valor",
        "col_event": "Evento",
        "col_time": "Fecha y hora",
        "col_actor": "Actor / Modelo",
        "col_hash": "Hash entrada",
        "col_sig": "Firma",
        "no_ledger": "Sin entradas registradas.",
        "footer": "Borrador generado automáticamente. No constituye asesoramiento fiscal ni legal.",
        "annex_title": "Anexo A – Pista de auditoría del documento",
        "row_doc": "Documento",
        "row_in": "Entrada",
        "row_type": "Tipo de documento",
        "row_path": "Ruta de análisis",
        "row_score": "Puntuación / Banda",
        "row_rec": "Recomendación",
        "row_seal": "Sello",
        "row_4eyes": "Control dual (4 ojos)",
        "row_ret": "Conservación",
        "not_analyzed": "aún sin analizar",
        "unsealed": "sin sellar",
        "by": "por",
        "on": "el",
    },
}


def _fmt_ts(value: Any) -> str:
    if not value:
        return "–"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return str(value)
    return parsed.strftime("%d.%m.%Y, %H:%M:%S UTC")


def procedural_ui(lang: str) -> dict[str, str]:
    """Feste Texte der Verfahrensdokumentation in der gewünschten Sprache (auch für den Word-Export)."""
    return _PD_UI.get(lang, _PD_UI["de"])


def build_procedural_doc(
    *,
    settings: Settings,
    runtime: Any | None,
    record: DocumentRecord | None,
    entries: list[LedgerEntry],
    verification: ChainVerification,
    signing_key: dict[str, str],
    lang: str = "de",
) -> dict[str, Any]:
    """Strukturierte Verfahrensdokumentation (Grundlage fuer HTML und Markdown)."""
    snapshot = runtime.snapshot() if runtime is not None else None
    inference_mode = snapshot.inference_mode.value if snapshot else settings.inference_mode
    model = snapshot.active_model if snapshot else settings.ollama_model
    pii_level = snapshot.pii_strictness.value if snapshot else settings.pii_strictness
    dialect = settings.resolved_database_url.split(":", 1)[0].split("+", 1)[0]
    ui = _PD_UI.get(lang, _PD_UI["de"])
    todo = ui["todo"]

    if lang == "de":
        sections = _sections_de(
            settings=settings,
            inference_mode=inference_mode,
            model=model,
            pii_level=pii_level,
            dialect=dialect,
            verification=verification,
            signing_key=signing_key,
        )
    else:
        sections = _sections_i18n(
            lang=lang,
            todo=todo,
            settings=settings,
            inference_mode=inference_mode,
            model=model,
            pii_level=pii_level,
            dialect=dialect,
            verification=verification,
            signing_key=signing_key,
        )

    annex = _document_annex(record, entries, lang=lang) if record is not None else None
    return {
        "lang": lang,
        "todo": todo,
        "title": ui["title"],
        "subtitle": ui["subtitle"],
        "generated_at": utcnow().isoformat(),
        "version": APP_VERSION,
        "ruleset_version": RULESET_VERSION,
        "status": ui["status"],
        "retention": ui["retention"],
        "basis": ui["basis"],
        "sections": sections,
        "annex": annex,
    }


def _sections_de(
    *,
    settings: Settings,
    inference_mode: str,
    model: str,
    pii_level: str,
    dialect: str,
    verification: ChainVerification,
    signing_key: dict[str, str],
) -> list[dict[str, Any]]:
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
                            ["Verantwortlich für das Verfahren (Prozesseigner)", ZU_ERGAENZEN],
                            ["Prüfpersonen mit Freigabebefugnis", ZU_ERGAENZEN],
                            ["IT-Betrieb und Datensicherung", ZU_ERGAENZEN],
                            ["Datenschutzbeauftragte Person", ZU_ERGAENZEN],
                            ["Freigabe dieser Verfahrensdokumentation (Name, Datum)", ZU_ERGAENZEN],
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
                        "Eingang: Upload einzeln oder im Stapel (PDF oder XML); Weiterleitung aus dem Posteingang: " + ZU_ERGAENZEN,
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
                        "Export: Prüfzertifikat und Prüfdatenpaket (ZIP); Übergabe an ERP bzw. Archiv: " + ZU_ERGAENZEN,
                    ],
                },
                {
                    "heading": "2.2 Vier-Augen-Prinzip",
                    "text": (
                        "Übersteuerung (Override) und Siegel werden je mit Namen der handelnden Person im Ledger "
                        "festgehalten. Empfohlen ist, dass Übersteuerung und abschließende Freigabe durch "
                        "verschiedene Personen erfolgen; der Anhang weist für den Beleg aus, ob das der Fall war. "
                        "Der Name im System ist selbst erklärt – die Identität muss über die vorgelagerte "
                        "Anmeldung (Single Sign-on) belegt werden: " + ZU_ERGAENZEN
                    ),
                },
                {
                    "heading": "2.3 Rollen und Berechtigungen",
                    "table": {
                        "head": ["Rolle", "Aufgaben im System", "Zuordnung"],
                        "rows": [
                            ["Sachbearbeitung", "Upload, Analyse starten, Befunde lesen, Copilot", ZU_ERGAENZEN],
                            ["Prüfperson", "Übersteuerung der Einstufung, Siegel (Freigabe/Ablehnung)", ZU_ERGAENZEN],
                            ["Administration", "Inferenz-Modus, API-Schlüssel, PII-Strenge", ZU_ERGAENZEN],
                            ["Revision / Betriebsprüfung", "Lesezugriff, Zertifikat, Prüfdatenpaket", ZU_ERGAENZEN],
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
                    "text": "Zuständigkeiten sind Vorschläge: " + ZU_ERGAENZEN,
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
                        "Anbindung an ERP und Archiv: " + ZU_ERGAENZEN,
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
                        "Zeitstempel): " + ZU_ERGAENZEN,
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
                        "prüfbar. Sicherungsintervall, Aufbewahrungsort und Wiederherstellungstest: " + ZU_ERGAENZEN
                    ),
                },
                {
                    "heading": "4.2 Unveränderbarkeit (WORM-Prinzip)",
                    "text": (
                        "Originale werden nur einmal geschrieben; das Prüfprotokoll ist append-only (Trigger) und "
                        "hash-verkettet. Die Datenbank selbst ist kein WORM-Speicher: Gegen einen Angreifer mit "
                        "Vollzugriff auf die Datenbankdatei schützt erst die externe Verankerung des Kopf-Hashes bzw. "
                        "die Ablage in einem revisionssicheren Archiv. Archivsystem: " + ZU_ERGAENZEN
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
                        "(Versionsstand, Datum, freigebende Person): " + ZU_ERGAENZEN,
                    ],
                },
                {
                    "heading": "4.4 Zugriffsschutz und IT-Sicherheit",
                    "list": [
                        "API-Schlüssel (X-API-Key), Rate-Limit je Client-IP",
                        "Provider-Schlüssel Fernet-verschlüsselt gespeichert, nur maskiert ausgeliefert",
                        "Zertifikate mit restriktiver Content-Security-Policy, alle Werte HTML-escaped",
                        "Netzwerkzonen, Härtung und Patch-Management: " + ZU_ERGAENZEN,
                    ],
                },
            ],
        },
    ]
    return sections


def _sections_i18n(
    *,
    lang: str,
    todo: str,
    settings: Settings,
    inference_mode: str,
    model: str,
    pii_level: str,
    dialect: str,
    verification: ChainVerification,
    signing_key: dict[str, str],
) -> list[dict[str, Any]]:
    es = lang == "es"
    auth_txt = (
        ("activo" if settings.auth_enabled else "desactivado – habilitar en producción")
        if es
        else ("enabled" if settings.auth_enabled else "disabled – enforce in production")
    )
    chain_state = ("intacta" if verification.valid else "ROTA") if es else ("intact" if verification.valid else "BROKEN")
    if es:
        return [
            {
                "number": "1",
                "title": "Descripción general",
                "blocks": [
                    {
                        "heading": "1.1 Finalidad y alcance",
                        "text": (
                            f"{APP_TITLE} respalda la pre-auditoría de facturas y contratos entrantes: "
                            "requisitos obligatorios según § 14(4) UStG, facturación electrónica EN 16931, "
                            "clasificación de riesgo según Reglamento (UE) 2024/1689 y protección de datos RGPD. "
                            "No sustituye la supervisión humana (Human Oversight)."
                        ),
                    },
                    {
                        "heading": "1.2 Tipos de documentos",
                        "table": {
                            "head": ["Tipo", "Procesamiento", "Referencia vinculante"],
                            "rows": [
                                ["Factura híbrida (ZUGFeRD 2.x, Factur-X)", "XML incrustado PDF/A-3", "Conjunto XML (BMF 15/10/2024, Rz. 36)"],
                                ["XRechnung (CII / UBL .xml)", "Conjunto XML", "Conjunto XML"],
                                ["PDF simple sin XML", "Capa de texto, LLM + regex", "PDF"],
                                ["Contratos", "Capa de texto, evaluación Reglamento IA", "PDF"],
                            ],
                        },
                    },
                    {
                        "heading": "1.3 Organización y responsabilidades",
                        "table": {
                            "head": ["Función", "Responsable"],
                            "rows": [
                                ["Propietario del proceso", todo],
                                ["Auditores autorizados", todo],
                                ["Operación TI y copias de seguridad", todo],
                                ["Delegado de Protección de Datos", todo],
                                ["Aprobación manual (nombre, fecha)", todo],
                            ],
                        },
                    },
                    {
                        "heading": "1.4 Marco normativo",
                        "list": [
                            "§§ 145–147 AO, GoBD Rz. 58 ss. y Rz. 151 ss.",
                            "§ 14(4) UStG, EN 16931, circular BMF 15/10/2024",
                            "Reglamento (UE) 2024/1689 (Art. 12 registro, Art. 14 supervisión humana)",
                            "RGPD Art. 4(5), 5, 9, 25, 32 (seudonimización en Privacy Gateway)",
                        ],
                    },
                ],
            },
            {
                "number": "2",
                "title": "Documentación de usuario",
                "blocks": [
                    {
                        "heading": "2.1 Flujo operativo",
                        "list": [
                            f"Ingesta individual o por lotes (PDF / XML); origen corporativo: {todo}",
                            "Hash SHA-256 inmutable del archivo original al ingresar",
                            f"Evaluación determinista (0–100) según reglamento {RULESET_VERSION}",
                            "Sellado Ed25519 y exportación de paquete GoBD (ZIP)",
                        ],
                    },
                    {
                        "heading": "2.2 Control dual (4 ojos)",
                        "text": f"Las anulaciones y los sellos finales quedan firmados nominalmente; identidad verificada vía SSO: {todo}",
                    },
                ],
            },
            {
                "number": "3",
                "title": "Documentación técnica del sistema",
                "blocks": [
                    {
                        "heading": "3.1 Configuración técnica",
                        "table": {
                            "head": ["Parámetro", "Valor"],
                            "rows": [
                                ["Aplicación", f"{APP_TITLE} v{APP_VERSION}"],
                                ["Reglamento", RULESET_VERSION],
                                ["Prompt Hash", PROMPT_HASH],
                                ["Base de datos", dialect],
                                ["Inferencia / Modelo", f"{inference_mode} / {model}"],
                                ["Nivel PII", pii_level],
                                ["Autenticación (X-API-Key)", auth_txt],
                                ["Clave pública (huella)", signing_key.get("fingerprint", "–")],
                                ["Cadena SHA-256", f"{chain_state} ({verification.entries} entradas, {verification.signed_entries} firmadas)"],
                            ],
                        },
                    },
                ],
            },
            {
                "number": "4",
                "title": "Documentación operativa",
                "blocks": [
                    {
                        "heading": "4.1 Copias de seguridad e inmutabilidad",
                        "text": f"Incluir base de datos, originales y claves (.settings.key, .signing.key). Calendario de respaldo y archivo WORM: {todo}",
                    },
                ],
            },
        ]

    return [
        {
            "number": "1",
            "title": "General Description",
            "blocks": [
                {
                    "heading": "1.1 Purpose & Scope",
                    "text": (
                        f"{APP_TITLE} assists compliance pre-audits of incoming invoices and contracts: "
                        "mandatory invoice fields under Sec. 14(4) UStG, EN 16931 e-invoices, risk classification under "
                        "Regulation (EU) 2024/1689 (EU AI Act) and GDPR controls. Final sign-off remains strictly with the human auditor."
                    ),
                },
                {
                    "heading": "1.2 Document Types",
                    "table": {
                        "head": ["Document Type", "Processing Path", "Authoritative Source"],
                        "rows": [
                            ["Hybrid E-Invoice (ZUGFeRD 2.x, Factur-X)", "Embedded XML in PDF/A-3 container", "XML dataset (BMF 15 Oct 2024, para. 36)"],
                            ["XRechnung (CII or UBL .xml)", "Structured XML dataset", "XML dataset"],
                            ["ZUGFeRD MINIMUM / BASIC WL", "XML metadata read, visual audit", "Visual PDF (non-E-Invoice)"],
                            ["Plain PDF Invoice", "Text layer, LLM extraction, regex cross-check", "PDF"],
                            ["Contracts", "Text layer, EU AI Act risk classification", "PDF"],
                        ],
                    },
                },
                {
                    "heading": "1.3 Organization & Responsibilities",
                    "table": {
                        "head": ["Role", "Assigned Person / Team"],
                        "rows": [
                            ["Process Owner", todo],
                            ["Authorized Auditors", todo],
                            ["IT Operations & Backup", todo],
                            ["Data Protection Officer", todo],
                            ["Manual Sign-Off (Name, Date)", todo],
                        ],
                    },
                },
                {
                    "heading": "1.4 Statutory Basis",
                    "list": [
                        "§§ 145–147 AO, German GoBD (BMF Decree, Rz. 58 ff. immutability & Rz. 151 ff. procedural docs)",
                        "§ 14(1)/(4), § 14b, § 15 UStG; EN 16931; German BMF Decrees 15 Oct 2024 & 15 Oct 2025",
                        "§ 5(1) ERechV (Leitweg-ID routing for German federal public buyers)",
                        "EU AI Act Reg. (EU) 2024/1689: Art. 12 (logging), Art. 14 (human oversight), Art. 26(6) (log retention ≥6 months)",
                        "GDPR: Art. 4(5) (pseudonymization), Art. 5, 9, 25, 32",
                    ],
                },
            ],
        },
        {
            "number": "2",
            "title": "User Documentation",
            "blocks": [
                {
                    "heading": "2.1 Document Workflow",
                    "list": [
                        f"Ingestion: single or batch upload (PDF/XML); upstream mailroom routing: {todo}",
                        "Integrity: bit-exact SHA-256 hash of original file recorded on upload",
                        f"Scoring: deterministic scorecard (0–100) under versioned ruleset {RULESET_VERSION}",
                        "Sign-Off & Export: Ed25519 auditor seal and offline-verifiable GoBD ZIP package",
                    ],
                },
                {
                    "heading": "2.2 Dual Control (4-Eyes Principle)",
                    "text": f"Both classification overrides and final seals record the acting person in the hash ledger; upstream SSO identity verification: {todo}",
                },
            ],
        },
        {
            "number": "3",
            "title": "Technical System Documentation",
            "blocks": [
                {
                    "heading": "3.1 System State",
                    "table": {
                        "head": ["Parameter", "Value"],
                        "rows": [
                            ["Application", f"{APP_TITLE} v{APP_VERSION}"],
                            ["Scorecard Ruleset", RULESET_VERSION],
                            ["Prompt Fingerprint (Hash)", PROMPT_HASH],
                            ["Database Backend", dialect],
                            ["Active Inference / Model", f"{inference_mode} / {model}"],
                            ["Text View PII Masking Level", pii_level],
                            ["API Authentication (X-API-Key)", auth_txt],
                            ["Ed25519 Key Fingerprint", signing_key.get("fingerprint", "–")],
                            ["SHA-256 Chain Verification", f"{chain_state} ({verification.entries} entries, {verification.signed_entries} signed)"],
                        ],
                    },
                },
            ],
        },
        {
            "number": "4",
            "title": "Operations & Continuity",
            "blocks": [
                {
                    "heading": "4.1 Backups, Immutability & Access Control",
                    "text": (
                        f"Back up the data directory including agent database, originals and cryptographic keys (.settings.key, .signing.key). "
                        f"External head-hash anchoring schedule and WORM archive target: {todo}"
                    ),
                },
            ],
        },
    ]


def _document_annex(record: DocumentRecord, entries: list[LedgerEntry], *, lang: str = "de") -> dict[str, Any]:
    """Anhang A: Pruefpfad des konkreten Belegs."""
    ui = _PD_UI.get(lang, _PD_UI["de"])
    event_labels = _EVENT_LABELS_I18N.get(lang, _EVENT_LABELS)
    path_labels = _PATH_LABELS_I18N.get(lang, _PATH_LABELS)
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
    if lang == "en":
        four_eyes = (
            "No override – dual control not triggered."
            if not override_people
            else "Overridden, not yet sealed."
            if seal_person is None
            else f"Violated: “{seal_person}” performed both override and seal."
            if seal_person in override_people
            else "Satisfied: override and final seal performed by distinct persons."
        )
    elif lang == "es":
        four_eyes = (
            "Sin anulación – control dual no activado."
            if not override_people
            else "Anulado, aún sin sellar."
            if seal_person is None
            else f"Incumplido: «{seal_person}» realizó tanto anulación como sellado."
            if seal_person in override_people
            else "Cumplido: anulación y sello final por personas distintas."
        )
    else:
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
            (
                f"{period.years} years, at least until 31.12.{period.until.year} (financial sector: 10 years, until 31.12.{period.financial_sector_until.year}); {period.basis}"
                if lang == "en"
                else f"{period.years} años, hasta 31.12.{period.until.year} (sector financiero: 10 años, hasta 31.12.{period.financial_sector_until.year}); {period.basis}"
                if lang == "es"
                else f"{period.years} Jahre, bis mindestens 31.12.{period.until.year} (Finanzsektor: 10 Jahre, bis 31.12.{period.financial_sector_until.year}); {period.basis}"
            )
            if period
            else (
                "Document date unknown – statutory period starts at end of creation fiscal year (§ 147(4) AO)."
                if lang == "en"
                else "Fecha desconocida – plazo desde el cierre del ejercicio (§ 147(4) AO)."
                if lang == "es"
                else "Belegdatum unbekannt – Frist ab Schluss des Entstehungsjahres (§ 147 Abs. 4 AO)."
            )
        )
    elif extraction is not None:
        retention = (
            "Depending on document role: accounting voucher 8 years, commercial correspondence 6 years (§ 147 AO)."
            if lang == "en"
            else "Según función: justificante contable 8 años, correspondencia comercial 6 años (§ 147 AO)."
            if lang == "es"
            else (
                "Abhängig von der Funktion des Dokuments: als Buchungsbeleg 8 Jahre, als empfangener "
                "Handels- oder Geschäftsbrief 6 Jahre (§ 147 Abs. 1, Abs. 3 AO)."
            )
        )

    rows = [
        [ui["row_doc"], record.original_filename],
        ["SHA-256", record.sha256],
        [ui["row_in"], _fmt_ts(record.created_at.isoformat())],
        [
            ui["row_type"],
            (
                f"{einvoice.profile} ({einvoice.syntax})"
                if einvoice and not einvoice.error
                else (extraction.doc_type.value if extraction else ui["not_analyzed"])
            ),
        ],
        [ui["row_path"], path_labels.get(record.provider or "", record.provider or "–")],
        [ui["row_score"], f"{scorecard.score}/100 ({scorecard.band_label})" if scorecard else "–"],
        [ui["row_rec"], scorecard.release_recommendation if scorecard else "–"],
        [
            ui["row_seal"],
            (
                f"{sign_off.status.value} {ui['by']} {sign_off.auditor_name} {ui['on']} {_fmt_ts(sign_off.sealed_at.isoformat())}"
                if sign_off
                else ui["unsealed"]
            ),
        ],
        [ui["row_4eyes"], four_eyes],
        [ui["row_ret"], retention or "–"],
    ]
    return {
        "title": ui["annex_title"],
        "rows": rows,
        "ledger": [
            {
                "seq": entry.seq,
                "event": event_labels.get(entry.event_type, entry.event_type),
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


def render_markdown(doc: dict[str, Any], *, lang: str = "de") -> str:
    lang = doc.get("lang", lang)
    ui = _PD_UI.get(lang, _PD_UI["de"])
    lines = [
        f"# {doc['title']}",
        "",
        f"_{doc['subtitle']}_",
        "",
        f"- **{ui['stand']}:** {_fmt_ts(doc['generated_at'])} · v{doc['version']} · {ui['ruleset']} {doc['ruleset_version']}",
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
        lines += [f"## {annex['title']}", "", f"| {ui['col_key']} | {ui['col_val']} |", "|---|---|"]
        lines += [f"| {_md(key)} | {_md(value)} |" for key, value in annex["rows"]]
        lines += [
            "",
            f"| Seq | {ui['col_event']} | {ui['col_time']} | {ui['col_actor']} | Score | {ui['col_hash']} | {ui['col_sig']} |",
            "|---:|---|---|---|---:|---|---|",
        ]
        lines += [
            f"| {e['seq']} | {e['event']} | {e['timestamp']} | {_md(e['actor'])} | {_md(e['score'])} | "
            f"`{e['entry_hash'][:16]}…` | {'Ed25519' if e['signed'] else '–'} |"
            for e in annex["ledger"]
        ]
        lines.append("")
    return "\n".join(lines)


def _e(value: Any) -> str:
    return html.escape("–" if value in (None, "") else str(value))


def _todo(text: str, todo_token: str = ZU_ERGAENZEN) -> str:
    """Hebt Platzhalter hervor (nach dem Escaping, daher sicher)."""
    return _e(text).replace(html.escape(todo_token), f'<span class="todo">{html.escape(todo_token)}</span>')


_PD_LAYOUT: dict[str, dict[str, str]] = {
    "de": {"print_hint": "A4-Druckansicht · Strg + P druckt die Dokumentation oder speichert sie als PDF. Zum Ergänzen der markierten Stellen den Word-Export verwenden.", "page": "Seite", "of": "von"},
    "en": {"print_hint": "A4 print view · Ctrl + P prints the documentation or saves it as PDF. Use the Word export to fill in the marked fields.", "page": "Page", "of": "of"},
    "es": {"print_hint": "Vista de impresión A4 · Ctrl + P imprime la documentación o la guarda como PDF. Para completar los campos marcados, use la exportación a Word.", "page": "Página", "of": "de"},
}


def render_html(doc: dict[str, Any], *, lang: str = "de") -> str:
    lang = doc.get("lang", lang)
    ui = _PD_UI.get(lang, _PD_UI["de"])
    lt = _PD_LAYOUT.get(lang, _PD_LAYOUT["de"])
    todo_token = doc.get("todo", ui["todo"])
    parts: list[str] = []
    for section in doc["sections"]:
        parts.append(f"<h2><span class=\"no\">{_e(section['number'])}</span>{_e(section['title'])}</h2>")
        for block in section["blocks"]:
            parts.append(f"<h3>{_e(block['heading'])}</h3>")
            if "table" in block:
                head = "".join(f"<th>{_e(cell)}</th>" for cell in block["table"]["head"])
                rows = "".join(
                    "<tr>" + "".join(f"<td>{_todo(str(cell), todo_token)}</td>" for cell in row) + "</tr>"
                    for row in block["table"]["rows"]
                )
                parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
            if "list" in block:
                parts.append("<ul>" + "".join(f"<li>{_todo(item, todo_token)}</li>" for item in block["list"]) + "</ul>")
            if "text" in block:
                parts.append(f"<p>{_todo(block['text'], todo_token)}</p>")

    annex = doc.get("annex")
    document_name = ""
    annex_sheet = ""
    running = f'<div class="running"><span>{_e(APP_TITLE)} · {_e(doc["title"])}</span><span>{{name}}</span></div>'
    if annex:
        document_name = str(annex["rows"][0][1]) if annex.get("rows") else ""
        facts = "".join(
            f"<dt>{_e(key)}</dt><dd{' class=mono' if key == 'SHA-256' else ''}>{_e(value)}</dd>"
            for key, value in annex["rows"]
        )
        ledger = "".join(
            f"<tr><td class='num'>{_e(e['seq'])}</td><td>{_e(e['event'])}</td><td>{_e(e['timestamp'])}</td>"
            f"<td>{_e(e['actor'])}</td><td class='num'>{_e(e['score'])}</td>"
            f"<td class='mono'>{_e(e['entry_hash'][:16])}…</td><td>{'Ed25519' if e['signed'] else '–'}</td></tr>"
            for e in annex["ledger"]
        ) or f"<tr><td colspan='7'>{_e(ui['no_ledger'])}</td></tr>"
        annex_sheet = (
            f"<section class=\"sheet\">{running.replace('{name}', _e(document_name))}"
            f"<h2 class='annex'>{_e(annex['title'])}</h2><dl class='facts'>{facts}</dl>"
            f"<table><thead><tr><th class='num'>Seq</th><th>{_e(ui['col_event'])}</th><th>{_e(ui['col_time'])}</th><th>{_e(ui['col_actor'])}</th>"
            f"<th class='num'>Score</th><th>{_e(ui['col_hash'])}</th><th>{_e(ui['col_sig'])}</th></tr></thead><tbody>{ledger}</tbody></table>"
            f"<footer class='legal'>{_e(ui['footer'])}</footer></section>"
        )

    stand = f"{ui['stand']} {_fmt_ts(doc['generated_at'])}"
    rules = page_rules(
        top_left=f"{APP_TITLE} · {doc['title']}",
        top_right=document_name,
        bottom_left=f"{stand} · {ui['ruleset']} {doc['ruleset_version']}",
        page_label=lt["page"],
        of_label=lt["of"],
    )
    return f"""<!doctype html>
<html lang="{_e(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(doc['title'])}</title>
<style>
{rules}
{BASE_CSS}
.todo {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; border-radius: 4px; padding: 0 4px; }}
td .todo {{ white-space: normal; }}
h2.annex {{ margin-top: 0; }}
</style></head>
<body>
<p class="hint">{_e(lt['print_hint'])}</p>
<section class="sheet">
{running.replace('{name}', _e(document_name))}
<div class="kicker">GoBD Rz. 151 ff. · § 147 AO · VO (EU) 2024/1689</div>
<h1>{_e(doc['title'])}</h1>
<p class="lead">{_e(doc['subtitle'])}<br>{_e(stand)} · {_e(APP_TITLE)} v{_e(doc['version'])} · {_e(ui['ruleset'])} {_e(doc['ruleset_version'])}</p>
<div class="note keep"><strong>{_e(doc['status'])}</strong><br>{_e(doc['retention'])}</div>
<p class="small">{_e(doc['basis'])}</p>
{''.join(parts)}
<footer class="legal">{_e(ui['footer'])}</footer>
</section>
{annex_sheet}
</body></html>"""
