"""Generisches Data-Loss-Prevention-Gateway (``POST /api/v1/redact``).

Andere Anwendungen (externe Fachanwendungen, Analyse-Pipelines) schicken Text
hierher, *bevor* sie ihn an ein Cloud-LLM geben.  Anders als der Privacy Vault der Dokumentprüfung
schwärzt dieses Gateway **endgültig**: Es gibt kein Mapping, keine
Re-Identifizierung, und die Antwort enthält nur den geschwärzten Text und
Zähler - nie die gefundenen Werte.

Regeln (deterministisch, in dieser Reihenfolge, ohne Überlappung):

1. **Zugangsdaten** (API-Keys, Tokens, ``password=...``) -> ``[REDACTED_SECRET]``
2. **Vertrauliche Dateinamen** (``internal_audit_memo.md``, ``pricing_algorithm.py``)
   -> ``[REDACTED_CONFIDENTIAL]``
3. **Geschützte Parameter**: der *Wert* von Schwellwerten, Gewichten und
   Strategie-Parametern (``threshold=0.73`` -> ``threshold=[REDACTED_CONFIDENTIAL]``)
4. **Sperrbegriffe** aus ``DLP_TERMS`` und ``extra_terms`` -> ``[REDACTED_CONFIDENTIAL]``
5. **Personenbezogene Daten** über die Muster des Privacy Gateways
   (E-Mail, IBAN, USt-IdNr., Steuernummer, Telefon, Adresse, Firma, Person)
   -> ``[REDACTED_<KATEGORIE>]``; Beträge nur auf Wunsch.

Grenzen: Die Erkennung ist regelbasiert.  Geheimnisse in Freitext ohne
erkennbares Muster bleiben stehen - das Gateway senkt das Abflussrisiko, es
garantiert keine Vertraulichkeit.

CLI: ``python -m app.redact < eingabe.txt`` gibt den geschwärzten Text aus.
"""

from __future__ import annotations

import bisect
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass

from app.privacy_vault import PrivacyVault

RULESET_VERSION = "dlp-2026.1"
CONFIDENTIAL = "[REDACTED_CONFIDENTIAL]"
SECRET = "[REDACTED_SECRET]"

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk-ant-|sk-proj-|sk-)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:password|passwort|kennwort|secret|api[_-]?key|token|bearer)\b\s*[:=]\s*[\"']?[^\s\"',;]{4,}"
    ),
)

_CONFIDENTIAL_WORDS = (
    "intern", "internal", "confidential", "vertraulich", "secret", "geheim", "private", "privat",
    "audit", "pricing", "preis", "algorithm", "algorithmus", "strategy", "strategie", "alpha",
    "salary", "gehalt", "memo", "roadmap", "board", "vorstand", "nda", "proprietary",
)
_FILENAME = re.compile(
    r"\b[\w\-]+\.(?:md|txt|py|ipynb|pine|sql|csv|xlsx?|json|ya?ml|toml|docx?|pptx?|pdf)\b", re.IGNORECASE
)
_PARAMETER = re.compile(
    r"(?i)\b(?P<key>[a-z_]*(?:threshold|schwellwert|schwelle|cutoff|limit|weight|gewicht|faktor|factor|"
    r"alpha|beta|stop_?loss|take_?profit|lookback|hurdle|marge|margin|spread)[a-z_0-9]*)"
    r"(?P<sep>\s*(?:=|:|>=|<=|>|<)\s*)(?P<value>-?\d+(?:[.,]\d+)?%?)"
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def configured_terms() -> list[str]:
    """Sperrbegriffe aus ``DLP_TERMS`` (kommagetrennt)."""
    return [term.strip() for term in os.environ.get("DLP_TERMS", "").split(",") if term.strip()]


def _is_confidential_filename(name: str) -> bool:
    stem = name.rsplit(".", 1)[0].lower()
    return any(word in stem for word in _CONFIDENTIAL_WORDS)


def redact(
    text: str,
    *,
    extra_terms: list[str] | None = None,
    redact_pii: bool = True,
    redact_amounts: bool = False,
) -> RedactionResult:
    """Schwärzt ``text`` endgültig; liefert Text und Anzahl je Kategorie."""
    spans: list[tuple[int, int, str, str]] = []  # nach start sortiert: (start, end, kategorie, ersatz)
    starts: list[int] = []

    def add(start: int, end: int, category: str, replacement: str) -> None:
        if start >= end:
            return
        idx = bisect.bisect_left(starts, start)
        if idx > 0 and spans[idx - 1][1] > start:
            return
        if idx < len(spans) and spans[idx][0] < end:
            return
        starts.insert(idx, start)
        spans.insert(idx, (start, end, category, replacement))

    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            add(*match.span(), "SECRET", SECRET)
    for match in _FILENAME.finditer(text):
        if _is_confidential_filename(match.group(0)):
            add(*match.span(), "CONFIDENTIAL_FILE", CONFIDENTIAL)
    for match in _PARAMETER.finditer(text):
        add(*match.span("value"), "PROTECTED_PARAMETER", CONFIDENTIAL)
    seen_terms: set[str] = set()
    terms: list[str] = []
    for raw_term in [*configured_terms(), *(extra_terms or [])]:
        cleaned = raw_term.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen_terms:
            seen_terms.add(key)
            terms.append(cleaned)
    if terms:
        combined = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)) + r")(?!\w)",
            re.IGNORECASE,
        )
        for match in combined.finditer(text):
            add(*match.span(), "CONFIDENTIAL_TERM", CONFIDENTIAL)
    if redact_pii or redact_amounts:
        for span in PrivacyVault().find_spans(text):
            is_amount = span.category == "AMOUNT"
            if (is_amount and redact_amounts) or (not is_amount and redact_pii):
                add(span.start, span.end, span.category, f"[REDACTED_{span.category}]")

    out: list[str] = []
    cursor = 0
    for start, end, _category, replacement in spans:
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    counts = Counter(category for _, _, category, _ in spans)
    return RedactionResult("".join(out), dict(sorted(counts.items())))


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.stdout.write(redact(sys.stdin.read()).text)
