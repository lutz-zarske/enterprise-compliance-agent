"""Maskierung und regelbasierte PII-Erkennung (Privacy-by-Design).

Zwei Aufgaben:

1. **Durchsetzung der Maskierung.** Ein LLM hält sich nicht garantiert an die
   Anweisung, nur maskierte Werte zurückzugeben.  Alles, was aus dem Modell
   kommt, läuft hier durch, bevor es in die Datenbank geschrieben wird.
2. **Deterministische Zweitmeinung.** Reguläre Ausdrücke und Schlüsselwort-
   listen finden IBANs, Ausweisnummern, Gesundheits- und Religionsbezüge
   reproduzierbar.  Zusammen mit der LLM-Bewertung entsteht ein Audit, das
   auch dann Treffer meldet, wenn das Modell etwas übersieht - und das die
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

#: Kategorien, deren Wert ein direkter Identifikator ist und maskiert gehört.
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

#: Höchstzahl an Treffern je Kategorie, damit ein Serienbrief das Audit nicht flutet.
MAX_FINDINGS_PER_CATEGORY = 5

#: Länge des Kontextausschnitts um einen regelbasierten Treffer herum.
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
#: Leitweg-IDs öffentlicher Auftraggeber (z. B. 04011000-1234512345-06) sind
#: Behördenkennungen, keine Telefonnummern - erkannt am gültigen Prüfziffernpaar.
_LEITWEG_CANDIDATE = re.compile(r"\b\d{2,12}(?:-[A-Za-z0-9]{1,30})?-\d{2}\b")


def _leitweg_spans(text: str) -> list[tuple[int, int]]:
    from app.extractors.einvoice import validate_leitweg_id

    return [match.span() for match in _LEITWEG_CANDIDATE.finditer(text) if validate_leitweg_id(match.group(0)).valid]


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in spans)


def redact_text(value: str, *, limit: int | None = None) -> str:
    """Entfernt offensichtliche Identifikatoren aus einem Freitext-Schnipsel."""
    redacted = _IBAN_PATTERN.sub(lambda m: mask_value(m.group(0).replace(" ", "")), value)
    redacted = _EMAIL_PATTERN.sub(lambda m: mask_email(m.group(0)), redacted)
    leitweg = _leitweg_spans(redacted)
    redacted = _PHONE_PATTERN.sub(
        lambda m: m.group(0) if _overlaps(m.span(), leitweg) else "[TEL-MASKIERT]", redacted
    )
    redacted = _LONG_DIGITS_PATTERN.sub(lambda m: mask_value(m.group(0)), redacted)
    redacted = " ".join(redacted.split())
    if limit is not None and len(redacted) > limit:
        redacted = redacted[: limit - 1].rstrip() + "…"
    return redacted


def enforce_masking(findings: Iterable[PIIFinding], *, enabled: bool = True) -> list[PIIFinding]:
    """Erzwingt die Maskierung aller Treffer, bevor sie persistiert werden.

    Auch wenn das LLM den Klartextwert liefert, verlässt er diese
    Funktion nur maskiert.  Bei ``enabled=False`` wird lediglich der Kontext
    gekürzt (Debug-Betrieb, ausdrücklich konfiguriert).
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

#: Schlüsselwörter für besondere Kategorien nach Art. 9/10 DSGVO.
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

#: Kurze Schlüsselwörter nur am Wortanfang: sonst trifft "reha" in
#: "Softwarehaus".  Längere Begriffe bleiben Teilstrings (deutsche Komposita
#: wie "Arztattest" oder "Universitätsklinik").
_SHORT_KEYWORD = 5
_KEYWORD_OVERRIDES = {"rezept": r"rezept(?!ion)"}  # "Rezeption" ist kein Gesundheitsdatum


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    body = _KEYWORD_OVERRIDES.get(keyword, re.escape(keyword))
    prefix = r"(?<![a-zäöüß])" if len(keyword) <= _SHORT_KEYWORD else ""
    return re.compile(prefix + body)


_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    keyword: _keyword_pattern(keyword) for keywords in KEYWORD_RULES.values() for keyword in keywords
}

#: Muster für schlüsselwortverankerte Identifikatoren.
_ANCHORED_PATTERNS: tuple[tuple[PIICategory, re.Pattern[str]], ...] = (
    (
        PIICategory.ID_DOCUMENT_NUMBER,
        re.compile(
            # "USt-IdNr." ist eine Unternehmenskennung, keine Ausweisnummer.
            r"(?:ausweis(?:nummer)?|personalausweis|passnummer|reisepass|(?<!ust-)(?<!ust)id[- ]?nr\.?)"
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
    """Schneidet einen bereits entschärften Kontext um eine Fundstelle."""
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

    # --- IBANs (mit Prüfsumme, daher praktisch falsch-positiv-frei) --------
    iban_spans: list[tuple[int, int]] = []
    for match in _IBAN_PATTERN.finditer(text):
        iban_spans.append(match.span())
        candidate = match.group(0).replace(" ", "")
        if iban_checksum_valid(candidate):
            add(PIICategory.BANK_ACCOUNT, mask_value(candidate), *match.span(), 0.99)

    # --- E-Mail-Adressen und Telefonnummern --------------------------------
    for match in _EMAIL_PATTERN.finditer(text):
        add(PIICategory.CONTACT_DATA, mask_email(match.group(0)), *match.span(), 0.95)

    leitweg_spans = _leitweg_spans(text)
    for match in _PHONE_PATTERN.finditer(text):
        if _overlaps(match.span(), iban_spans) or _overlaps(match.span(), leitweg_spans):
            continue  # Ziffernblöcke einer IBAN oder Leitweg-ID sind keine Telefonnummer.
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 7:
            add(PIICategory.CONTACT_DATA, mask_value(match.group(0).strip()), *match.span(), 0.7)

    # --- Schlüsselwortverankerte Identifikatoren --------------------------
    for category, pattern in _ANCHORED_PATTERNS:
        for match in pattern.finditer(text):
            add(category, mask_value(match.group(1).strip()), *match.span(), 0.9)

    # --- Besondere Kategorien nach Art. 9/10 DSGVO -------------------------
    for category, keywords in KEYWORD_RULES.items():
        for keyword in keywords:
            match = _KEYWORD_PATTERNS[keyword].search(lowered)
            if match is None:
                continue
            add(
                category,
                f"Schlüsselwort: {keyword}",
                match.start(),
                match.end(),
                0.6,
            )

    return findings


# ---------------------------------------------------------------------------
# Zusammenführung von LLM- und Regelbefunden
# ---------------------------------------------------------------------------


def _dedupe_key(finding: PIIFinding) -> tuple[str, str]:
    normalized = re.sub(r"[^a-z0-9*@]", "", finding.masked_value.casefold())
    return finding.category.value, normalized


def merge_findings(
    llm_findings: Iterable[PIIFinding], rule_findings: Iterable[PIIFinding]
) -> list[PIIFinding]:
    """Vereinigt beide Quellen und markiert Doppeltreffer als ``both``.

    Doppelt gefundene Werte erhöhen die Konfidenz - was Regeln *und* Modell
    unabhängig voneinander finden, ist selten ein Fehlalarm.
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
                # Beschreibende Kategorien nicht mehrfach aufführen, sondern
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


# ---------------------------------------------------------------------------
# Textansicht mit Maskierungsstufen (strict | standard | audit_only)
# ---------------------------------------------------------------------------

#: Höchstlänge der Textansicht im Inspektor.
TEXT_VIEW_LIMIT = 20_000

_DATE_PATTERN = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")

#: Vault-Kategorie -> (Anzeigename, Platzhalter bzw. None = Mitte maskieren).
_VIEW_CATEGORIES: dict[str, tuple[str, str | None]] = {
    "EMAIL": ("Kontaktdaten (E-Mail)", None),
    "PHONE": ("Kontaktdaten (Telefon)", None),
    "IBAN": ("Bankverbindung (IBAN)", None),
    "VAT_ID": ("USt-IdNr.", None),
    "TAX_NUMBER": ("Steuernummer", None),
    "ID_NUMBER": ("Ausweis-/Kennnummer", None),
    "DATE_OF_BIRTH": ("Geburtsdatum", None),
    "ART9": ("Besondere Kategorie (Art. 9/10 DSGVO)", "[ART. 9]"),
    "PERSON": ("Name einer natuerlichen Person", "[NAME]"),
    "ORG": ("Firma / Organisation", "[FIRMA]"),
    "ADDRESS": ("Anschrift", "[ADRESSE]"),
    "AMOUNT": ("Betrag", "[BETRAG]"),
    "DATE": ("Datum", "[DATUM]"),
}

#: Welche Kategorien je Stufe tatsächlich geschwärzt werden.
MASKED_BY_LEVEL: dict[str, frozenset[str]] = {
    "strict": frozenset(_VIEW_CATEGORIES),
    "standard": frozenset(
        {"EMAIL", "PHONE", "IBAN", "VAT_ID", "TAX_NUMBER", "ID_NUMBER", "DATE_OF_BIRTH", "ART9"}
    ),
    "audit_only": frozenset(),
}

#: Abgleich Textansicht <-> Befundliste (für die Quelle "both").
_FINDING_CATEGORY: dict[str, PIICategory] = {
    "EMAIL": PIICategory.CONTACT_DATA,
    "PHONE": PIICategory.CONTACT_DATA,
    "IBAN": PIICategory.BANK_ACCOUNT,
    "ID_NUMBER": PIICategory.ID_DOCUMENT_NUMBER,
    "DATE_OF_BIRTH": PIICategory.DATE_OF_BIRTH,
    "PERSON": PIICategory.NAME,
    "ADDRESS": PIICategory.ADDRESS,
}


def _collect_view_spans(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, kategorie, wert) - ohne Überlappungen, nach Position sortiert."""
    from app.privacy_vault import PrivacyVault  # lokaler Import: vermeidet Zyklus

    raw: list[tuple[int, int, str, str]] = []
    # Höchste Priorität: verankerte Identifikatoren und Art.-9-Schlüsselwörter.
    for category, pattern in _ANCHORED_PATTERNS:
        name = {
            PIICategory.ID_DOCUMENT_NUMBER: "ID_NUMBER",
            PIICategory.SOCIAL_SECURITY_NUMBER: "ID_NUMBER",
            PIICategory.TAX_ID: "ID_NUMBER",
            PIICategory.DATE_OF_BIRTH: "DATE_OF_BIRTH",
        }[category]
        for match in pattern.finditer(text):
            raw.append((*match.span(1), name, match.group(1)))
    lowered = text.casefold()
    for keywords in KEYWORD_RULES.values():
        for keyword in keywords:
            for match in re.finditer(rf"\b{re.escape(keyword)}\w*", lowered):
                raw.append((match.start(), match.end(), "ART9", text[match.start() : match.end()]))
    for span in PrivacyVault().find_spans(text):
        raw.append((span.start, span.end, span.category, span.value))
    for match in _DATE_PATTERN.finditer(text):
        raw.append((*match.span(), "DATE", match.group(0)))

    # Leitweg-IDs sind Behördenkennungen: weder markieren noch schwärzen.
    leitweg = _leitweg_spans(text)
    chosen: list[tuple[int, int, str, str]] = []
    for item in raw:
        if _overlaps((item[0], item[1]), leitweg):
            continue
        if any(item[0] < other[1] and other[0] < item[1] for other in chosen):
            continue
        chosen.append(item)
    return sorted(chosen)


def build_text_view(
    text: str, level: str, findings: Iterable[PIIFinding] = ()
) -> dict[str, object]:
    """Erzeugt die Inspektor-Ansicht: geschwärzter Text plus markierte Fundstellen.

    * ``strict``: alle erkannten Merkmale geschwärzt (Namen, Firmen, Beträge,
      Datumsangaben, Adressen, Identifikatoren, Art.-9-Begriffe).
    * ``standard``: IBAN, Steuernummern/USt-IdNr., E-Mail, Telefon, Kennnummern
      und Art.-9-Begriffe geschwärzt; übrige Treffer nur markiert.
    * ``audit_only``: nichts geschwärzt, alle Treffer markiert (interne Revision).
    """
    level = level if level in MASKED_BY_LEVEL else "standard"
    truncated = len(text) > TEXT_VIEW_LIMIT
    source_text = text[:TEXT_VIEW_LIMIT]
    masked_categories = MASKED_BY_LEVEL[level]

    llm_keys: set[tuple[str, str]] = set()
    for finding in findings:
        if finding.source in (DetectionSource.LLM, DetectionSource.BOTH):
            llm_keys.add(_dedupe_key(finding))

    out: list[str] = []
    spans: list[dict[str, object]] = []
    cursor = 0
    length = 0
    for start, end, category, value in _collect_view_spans(source_text):
        segment = source_text[cursor:start]
        out.append(segment)
        length += len(segment)
        label, placeholder = _VIEW_CATEGORIES[category]
        masked = category in masked_categories
        if masked:
            if placeholder:
                display = placeholder
            elif category == "EMAIL":
                display = mask_email(value)
            else:
                display = mask_value(value.replace(" ", "") if category == "IBAN" else value)
        else:
            display = value

        source = "rule_based"
        finding_category = _FINDING_CATEGORY.get(category)
        if finding_category is not None:
            probe = PIIFinding(
                category=finding_category,
                masked_value=mask_email(value) if category == "EMAIL" else mask_value(value.replace(" ", "")),
            )
            if _dedupe_key(probe) in llm_keys:
                source = "both"

        out.append(display)
        spans.append(
            {
                "start": length,
                "end": length + len(display),
                "category": category.lower(),
                "label": label,
                "masked": masked,
                "source": source,
            }
        )
        length += len(display)
        cursor = end
    out.append(source_text[cursor:])
    return {"level": level, "text": "".join(out), "spans": spans, "truncated": truncated}
