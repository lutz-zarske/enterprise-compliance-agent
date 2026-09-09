"""Maskierung und regelbasierte PII-Erkennung (Privacy-by-Design).

Zwei Aufgaben:

1. **Durchsetzung der Maskierung.** Ein LLM haelt sich nicht garantiert an die
   Anweisung, nur maskierte Werte zurueckzugeben.  Alles, was aus dem Modell
   kommt, laeuft hier durch, bevor es in die Datenbank geschrieben wird.
2. **Deterministische Zweitmeinung.** Regulaere Ausdruecke und Schluesselwort-
   listen finden IBANs, Ausweisnummern, Gesundheits- und Religionsbezuege
   reproduzierbar.  Zusammen mit der LLM-Bewertung entsteht ein Audit, das
   auch dann Treffer meldet, wenn das Modell etwas uebersieht - und das die
   Herkunft jedes Treffers ausweist (``source``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas import (
    SPECIAL_CATEGORIES,
    DetectionSource,
    PIICategory,
    PIIFinding,
    iban_checksum_valid,
)

#: Kategorien, deren Wert ein direkter Identifikator ist und maskiert gehoert.
IDENTIFIER_CATEGORIES: frozenset[PIICategory] = frozenset(
    {
        PIICategory.ID_DOCUMENT_NUMBER,
        PIICategory.SOCIAL_SECURITY_NUMBER,
        PIICategory.TAX_ID,
        PIICategory.BANK_ACCOUNT,
        PIICategory.DATE_OF_BIRTH,
        PIICategory.NAME,
        PIICategory.ADDRESS,
        PIICategory.CONTACT_DATA,
    }
)

#: Hoechstzahl an Treffern je Kategorie, damit ein Serienbrief das Audit nicht flutet.
MAX_FINDINGS_PER_CATEGORY = 5

#: Laenge des Kontextausschnitts um einen regelbasierten Treffer herum.
CONTEXT_WINDOW = 60


# ---------------------------------------------------------------------------
# Maskierung
# ---------------------------------------------------------------------------


def mask_value(value: str, *, keep: int = 4) -> str:
    """Maskiert die Mitte eines Wertes: ``DE89370400440532013000`` -> ``DE89****3000``."""
    cleaned = value.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 4:
        return "*" * len(cleaned)
    if len(cleaned) < 12:
        keep = 2
    prefix, suffix = cleaned[:keep], cleaned[-keep:]
    stars = "*" * min(max(len(cleaned) - 2 * keep, 1), 8)
    return f"{prefix}{stars}{suffix}"


def mask_email(value: str) -> str:
    """``max.mustermann@example.com`` -> ``m***@example.com``."""
    local, _, domain = value.partition("@")
    if not domain:
        return mask_value(value)
    head = local[:1] if local else ""
    return f"{head}***@{domain}"


_IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){2,8}\b")
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?:\+49|0049|\(0\)|\b0)[\s/.-]?\d{2,5}[\s/.-]?\d{3,}\b")
_LONG_DIGITS_PATTERN = re.compile(r"\b\d{8,}\b")


def redact_text(value: str, *, limit: int | None = None) -> str:
    """Entfernt offensichtliche Identifikatoren aus einem Freitext-Schnipsel."""
    redacted = _IBAN_PATTERN.sub(lambda m: mask_value(m.group(0).replace(" ", "")), value)
    redacted = _EMAIL_PATTERN.sub(lambda m: mask_email(m.group(0)), redacted)
    redacted = _PHONE_PATTERN.sub("[TEL-MASKIERT]", redacted)
    redacted = _LONG_DIGITS_PATTERN.sub(lambda m: mask_value(m.group(0)), redacted)
    redacted = " ".join(redacted.split())
    if limit is not None and len(redacted) > limit:
        redacted = redacted[: limit - 1].rstrip() + "…"
    return redacted


def enforce_masking(findings: Iterable[PIIFinding], *, enabled: bool = True) -> list[PIIFinding]:
    """Erzwingt die Maskierung aller Treffer, bevor sie persistiert werden.

    Auch wenn das LLM den Klartextwert liefert, verlaesst er diese
    Funktion nur maskiert.  Bei ``enabled=False`` wird lediglich der Kontext
    gekuerzt (Debug-Betrieb, ausdruecklich konfiguriert).
    """
    result: list[PIIFinding] = []
    for finding in findings:
        context = redact_text(finding.context, limit=300) if enabled else finding.context[:300]
        value = finding.masked_value

        if enabled and value:
            if "@" in value and _EMAIL_PATTERN.search(value):
                value = mask_email(value)
            elif finding.category in IDENTIFIER_CATEGORIES:
                # Bereits maskierte Werte werden nicht doppelt maskiert.
                value = value if "*" in value else mask_value(value)
            else:
                # Beschreibende Kategorien (Gesundheit, Religion) bleiben lesbar,
                # verlieren aber alle enthaltenen Identifikatoren.
                value = redact_text(value, limit=120)

        result.append(finding.model_copy(update={"masked_value": value, "context": context}))
    return result


# ---------------------------------------------------------------------------
# Regelbasierte Erkennung
# ---------------------------------------------------------------------------

#: Schluesselwoerter fuer besondere Kategorien nach Art. 9/10 DSGVO.
KEYWORD_RULES: dict[PIICategory, tuple[str, ...]] = {
    PIICategory.HEALTH_DATA: (
        "diagnose", "krankheit", "erkrankung", "patient", "patientin", "arztbericht",
        "aerztlich", "ärztlich", "krankenkasse", "krankenversicherung", "medikament",
        "therapie", "behandlung", "icd-10", "arbeitsunfaehig", "arbeitsunfähig",
        "attest", "befund", "rezept", "klinik", "krankenhaus", "schwanger",
        "allergie", "impfung", "pflegegrad", "reha",
    ),
    PIICategory.RELIGIOUS_BELIEF: (
        "konfession", "religionszugehoerigkeit", "religionszugehörigkeit",
        "kirchensteuer", "roemisch-katholisch", "römisch-katholisch", "katholisch",
        "evangelisch", "juedisch", "jüdisch", "muslimisch", "islamisch",
        "konfessionslos", "weltanschauung",
    ),
    PIICategory.TRADE_UNION: (
        "gewerkschaft", "gewerkschaftsmitglied", "ver.di", "ig metall", "tarifbindung",
    ),
    PIICategory.POLITICAL_OPINION: (
        "parteimitglied", "parteizugehoerigkeit", "parteizugehörigkeit",
        "politische ueberzeugung", "politische überzeugung",
    ),
    PIICategory.ETHNIC_ORIGIN: (
        "ethnische herkunft", "migrationshintergrund", "hautfarbe", "volksgruppe",
    ),
    PIICategory.CRIMINAL_DATA: (
        "vorstrafe", "strafverfahren", "verurteilung", "ermittlungsverfahren",
        "fuehrungszeugnis", "führungszeugnis", "bewaehrung", "bewährung",
    ),
    PIICategory.SEX_LIFE: (
        "sexuelle orientierung", "lebenspartnerschaft",
    ),
    PIICategory.BIOMETRIC_DATA: (
        "fingerabdruck", "gesichtserkennung", "iris-scan", "biometrisch",
    ),
    PIICategory.GENETIC_DATA: (
        "gentest", "dna-analyse", "erbgut", "genetische",
    ),
}

#: Muster fuer schluesselwortverankerte Identifikatoren.
_ANCHORED_PATTERNS: tuple[tuple[PIICategory, re.Pattern[str]], ...] = (
    (
        PIICategory.ID_DOCUMENT_NUMBER,
        re.compile(
            r"(?:ausweis(?:nummer)?|personalausweis|passnummer|reisepass|id[- ]?nr\.?)"
            r"[:\s]*([A-Z0-9]{6,12})",
            re.IGNORECASE,
        ),
    ),
    (
        PIICategory.SOCIAL_SECURITY_NUMBER,
        re.compile(
            r"(?:sozialversicherungsnummer|rentenversicherungsnummer|sv-?nr\.?)"
            r"[:\s]*(\d{2}\s?\d{6}\s?[A-Z]\s?\d{3})",
            re.IGNORECASE,
        ),
    ),
    (
        PIICategory.TAX_ID,
        re.compile(
            r"(?:steuer-?identifikationsnummer|steuer-?id|idnr\.?)[:\s]*(\d{11})",
            re.IGNORECASE,
        ),
    ),
    (
        PIICategory.DATE_OF_BIRTH,
        re.compile(
            r"(?:geboren am|geburtsdatum|geb\.)[:\s]*"
            r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        ),
    ),
)


def _context_around(text: str, start: int, end: int) -> str:
    """Schneidet einen bereits entschaerften Kontext um eine Fundstelle."""
    left = max(start - CONTEXT_WINDOW, 0)
    right = min(end + CONTEXT_WINDOW, len(text))
    return redact_text(text[left:right], limit=300)


def scan_text(text: str) -> list[PIIFinding]:
    """Deterministische PII-Erkennung ohne LLM-Beteiligung."""
    findings: list[PIIFinding] = []
    counts: dict[PIICategory, int] = {}
    lowered = text.casefold()

    def add(category: PIICategory, value: str, start: int, end: int, confidence: float) -> None:
        if counts.get(category, 0) >= MAX_FINDINGS_PER_CATEGORY:
            return
        counts[category] = counts.get(category, 0) + 1
        findings.append(
            PIIFinding(
                category=category,
                masked_value=value,
                context=_context_around(text, start, end),
                confidence=confidence,
                source=DetectionSource.RULE_BASED,
            )
        )

    # --- IBANs (mit Pruefsumme, daher praktisch falsch-positiv-frei) --------
    for match in _IBAN_PATTERN.finditer(text):
        candidate = match.group(0).replace(" ", "")
        if iban_checksum_valid(candidate):
            add(PIICategory.BANK_ACCOUNT, mask_value(candidate), *match.span(), 0.99)

    # --- E-Mail-Adressen und Telefonnummern --------------------------------
    for match in _EMAIL_PATTERN.finditer(text):
        add(PIICategory.CONTACT_DATA, mask_email(match.group(0)), *match.span(), 0.95)

    for match in _PHONE_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 7:
            add(PIICategory.CONTACT_DATA, mask_value(match.group(0).strip()), *match.span(), 0.7)

    # --- Schluesselwortverankerte Identifikatoren --------------------------
    for category, pattern in _ANCHORED_PATTERNS:
        for match in pattern.finditer(text):
            add(category, mask_value(match.group(1).strip()), *match.span(), 0.9)

    # --- Besondere Kategorien nach Art. 9/10 DSGVO -------------------------
    for category, keywords in KEYWORD_RULES.items():
        for keyword in keywords:
            index = lowered.find(keyword)
            if index == -1:
                continue
            add(
                category,
                f"Schluesselwort: {keyword}",
                index,
                index + len(keyword),
                0.6,
            )

    return findings


# ---------------------------------------------------------------------------
# Zusammenfuehrung von LLM- und Regelbefunden
# ---------------------------------------------------------------------------


def _dedupe_key(finding: PIIFinding) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z0-9*@]", "", finding.masked_value.casefold())
    return finding.category.value, normalized


def merge_findings(
    llm_findings: Iterable[PIIFinding], rule_findings: Iterable[PIIFinding]
) -> list[PIIFinding]:
    """Vereinigt beide Quellen und markiert Doppeltreffer als ``both``.

    Doppelt gefundene Werte erhoehen die Konfidenz - was Regeln *und* Modell
    unabhaengig voneinander finden, ist selten ein Fehlalarm.
    """
    merged: dict[tuple[str, str], PIIFinding] = {}

    for finding in llm_findings:
        merged[_dedupe_key(finding)] = finding

    for finding in rule_findings:
        key = _dedupe_key(finding)
        existing = merged.get(key)
        if existing is None:
            # Kategorie bereits vom LLM erkannt, aber mit anderem Wortlaut?
            same_category = [
                candidate for candidate in merged.values() if candidate.category == finding.category
            ]
            if same_category and finding.category in SPECIAL_CATEGORIES:
                # Beschreibende Kategorien nicht mehrfach auffuehren, sondern
                # den vorhandenen Treffer auf "both" hochstufen.
                first = same_category[0]
                merged[_dedupe_key(first)] = first.model_copy(
                    update={
                        "source": DetectionSource.BOTH,
                        "confidence": max(first.confidence, finding.confidence),
                    }
                )
                continue
            merged[key] = finding
        else:
            merged[key] = existing.model_copy(
                update={
                    "source": DetectionSource.BOTH,
                    "confidence": max(existing.confidence, finding.confidence, 0.9),
                }
            )

    # Besondere Kategorien zuerst, danach nach Konfidenz absteigend.
    return sorted(
        merged.values(),
        key=lambda item: (item.category not in SPECIAL_CATEGORIES, -item.confidence),
    )
