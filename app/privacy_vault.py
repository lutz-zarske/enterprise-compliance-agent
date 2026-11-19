"""Confidential AI Privacy Gateway: Pseudonymisierung vor jedem Cloud-Aufruf.

Ablauf
------
1. **Pseudonymisieren:** Vor dem Versand an Gemini, Claude oder GPT ersetzt der
   Vault identifizierende Werte durch Platzhalter (``{{PERSON_1}}``,
   ``{{IBAN_1}}``, ``{{ORG_1}}``, ``{{AMOUNT_1}}`` ...).  Gleiche Werte erhalten
   denselben Platzhalter, damit das Modell Bezüge weiterhin erkennt.
2. **Flüchtiges Mapping:** Die Zuordnung Platzhalter -> Klartext lebt nur im
   Arbeitsspeicher dieses Prozesses und nur für die Dauer eines Auftrags.
   Sie wird weder geloggt noch persistiert noch versendet.
3. **Re-Identifizierung:** Die Modellantwort wird lokal zurückübersetzt,
   *bevor* sie gegen das Pydantic-Schema validiert wird.

Rechtliche Einordnung (bewusst nüchtern)
-----------------------------------------
Pseudonymisierte Daten bleiben personenbezogene Daten (Art. 4 Nr. 5 DSGVO,
ErwG 26), solange der Verantwortliche re-identifizieren kann - und genau das
tut dieser Vault.  Er *reduziert* das Übermittlungsrisiko im Sinne von
Art. 25 und Art. 32 DSGVO und ist eine anerkannte ergänzende Maßnahme für
Drittlandtransfers (EDSA-Empfehlungen 01/2020, Use Case 2).  Er ersetzt aber
weder Auftragsverarbeitungsvertrag noch Transfergrundlage (Art. 44 ff.).
Die Erkennung ist regelbasiert: Namen ohne Anrede oder Rollenbezeichnung und
Freitext-Merkmale (z. B. eine Diagnose im Fließtext) werden nicht erfasst.
Für den Volldatenschutz bleibt der lokale Modus der Standard.
"""

from __future__ import annotations

import bisect
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from app.llm import StructuredLLMClient

#: Zusatzanweisung an Cloud-Modelle, damit Platzhalter erhalten bleiben.
VAULT_SYSTEM_NOTE = (
    "Hinweis zum Datenschutz: Geschützte Werte wurden durch Platzhalter der Form "
    "{{TYP_n}} ersetzt (z. B. {{PERSON_1}}, {{ORG_1}}, {{IBAN_1}}, {{AMOUNT_1}}). "
    "Übernimm Platzhalter unverändert und vollständig mit doppelten geschweiften "
    "Klammern als String in die passenden Felder. Versuche nicht, sie aufzulösen."
)

_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+_\d+)\}\}")

#: Wörter, die vor einer Rechtsform stehen, aber nicht zum Firmennamen gehören.
_ORG_STOPWORDS = frozenset(
    {
        "zwischen", "und", "der", "die", "das", "den", "dem", "des", "von", "an", "bei",
        "firma", "rechnung", "vertrag", "empfaenger", "empfänger", "auftraggeber",
        "auftragnehmer", "lieferant", "kunde", "mit", "fuer", "für", "durch", "im", "in",
    }
)

_CAP = r"[A-ZÄÖÜ][\wÄÖÜäöüß&.\-]*"

#: (Kategorie, Muster, Gruppe) - Reihenfolge = Priorität bei Überlappung.
_RULES: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"), 0),
    (
        "VAT_ID",
        re.compile(
            r"\b(?:DE ?\d{9}|ATU\d{8}"
            r"|(?:BE|BG|CY|CZ|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)"
            r"[A-Z0-9]{0,2}\d{6,10}[A-Z0-9]{0,3})\b"
        ),
        0,
    ),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){3,8}\b"), 0),
    (
        "ID_NUMBER",
        re.compile(
            r"(?:ausweis(?:nummer)?|personalausweis|passnummer|reisepass|(?<!ust-)(?<!ust)id[- ]?nr\.?)"
            r"[:\s]*([A-Z0-9]{6,12})",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        "ID_NUMBER",
        re.compile(
            r"(?:sozialversicherungsnummer|rentenversicherungsnummer|sv-?nr\.?)"
            r"[:\s]*(\d{2}\s?\d{6}\s?[A-Z]\s?\d{3})",
            re.IGNORECASE,
        ),
        1,
    ),
    (
        "TAX_NUMBER",
        re.compile(r"(?:steuer-?identifikationsnummer|steuer-?id|idnr\.?)[:\s]*(\d{11})", re.IGNORECASE),
        1,
    ),
    (
        "DATE_OF_BIRTH",
        re.compile(
            r"(?:geboren am|geburtsdatum|geb\.)[:\s]*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        ),
        1,
    ),
    ("TAX_NUMBER", re.compile(r"\b\d{2,3}/\d{3,4}/\d{4,5}\b"), 0),
    ("PHONE", re.compile(r"(?:\+49|0049|\(0\)|\b0)[\s/.-]?\d{2,5}[\s/.-]?\d{3,}(?:[\s-]\d{1,5})?\b"), 0),
    (
        "AMOUNT",
        re.compile(
            r"(?:(?:EUR|€|USD|GBP|CHF|\$|£)\s?\d{1,3}(?:[.,\s]?\d{3})*(?:[.,]\d{1,2})?"
            r"|\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?\s?(?:EUR|€|Euro|USD|GBP|CHF)\b"
            r"|\b\d{4,}(?:[.,]\d{1,2})?\s?(?:EUR|€|Euro|USD|GBP|CHF)\b)"
        ),
        0,
    ),
    (
        "ADDRESS",
        re.compile(
            r"\b[A-ZÄÖÜ][a-zäöüß\-]+(?:straße|strasse|str\.|weg|allee|platz|gasse|ring|damm|ufer|chaussee)"
            r"[ \t]+\d+(?:[ ]?[a-z])?\b"
        ),
        0,
    ),
    ("ADDRESS", re.compile(r"\b\d{5}[ \t]+[A-ZÄÖÜ][a-zäöüß]+(?:[ \t](?:am|an der|a\.)[ \t]?[A-ZÄÖÜ][a-zäöüß]+)?"), 0),
    (
        "ORG",
        re.compile(
            rf"\b(?:(?:{_CAP}|&)[ ]){{0,3}}{_CAP}[ ]"
            r"(?:GmbH\s&\sCo\.\sKG|GmbH|gGmbH|AG|SE|KGaA|KG|OHG|UG(?:\s\(haftungsbeschränkt\))?|"
            r"e\.\s?K\.|e\.\s?V\.|mbH|Ltd\.?|Inc\.?|LLC|S\.A\.|B\.V\.)(?![\wÄÖÜäöüß])"
        ),
        0,
    ),
    (
        "PERSON",
        re.compile(
            r"\b(?:Herr|Frau|Hr\.|Fr\.|Mr\.|Mrs\.|Ms\.|Sr\.|Sra\.)[ \t]+(?:(?:Dr\.|Prof\.)[ \t]+)*([A-ZÄÖÜ][a-zäöüß]+(?:[ \t]+[A-ZÄÖÜ][a-zäöüß\-]+)?)"
        ),
        1,
    ),
    (
        "PERSON",
        re.compile(
            r"\b(?:Dr\.|Prof\.)[ \t]+(?:(?:Dr\.|Prof\.)[ \t]+)*([A-ZÄÖÜ][a-zäöüß]+[ \t]+[A-ZÄÖÜ][a-zäöüß\-]+)"
        ),
        1,
    ),
    (
        "PERSON",
        re.compile(
            r"(?:Ansprechpartner(?:in)?|Kontaktperson|Bewerber(?:in)?|Mitarbeiter(?:in)?|"
            r"Gesch(?:ä|ae)ftsf(?:ü|ue)hrer(?:in)?|Inhaber(?:in)?|Unterzeichner(?:in)?|z\.\s?Hd\.?|Name)"
            r"[: \t]+([A-ZÄÖÜ][a-zäöüß]+[ \t]+[A-ZÄÖÜ][a-zäöüß\-]+)"
        ),
        1,
    ),
)


@dataclass(slots=True)
class _Span:
    start: int
    end: int
    category: str
    value: str


def _trim_org(value: str, start: int) -> tuple[str, int]:
    """Entfernt führende Stoppwörter ("Zwischen TalentScreen AI GmbH" -> "TalentScreen AI GmbH")."""
    words = value.split(" ")
    offset = 0
    while len(words) > 2 and words[0].casefold() in _ORG_STOPWORDS:
        offset += len(words[0]) + 1
        words = words[1:]
    return " ".join(words), start + offset


@dataclass
class PrivacyVault:
    """Pseudonymisiert Texte und re-identifiziert Antworten - nur im Speicher."""

    _forward: dict[tuple[str, str], str] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)
    _counters: Counter[str] = field(default_factory=Counter)

    def _token_for(self, category: str, value: str) -> str:
        key = (category, value)
        token = self._forward.get(key)
        if token is None:
            self._counters[category] += 1
            token = f"{{{{{category}_{self._counters[category]}}}}}"
            self._forward[key] = token
            self._reverse[token] = value
        return token

    def find_spans(self, text: str) -> list[_Span]:
        chosen: list[_Span] = []
        starts: list[int] = []
        for category, pattern, group in _RULES:
            for match in pattern.finditer(text):
                start, end = match.span(group)
                raw = match.group(group)
                lead = len(raw) - len(raw.lstrip())
                trail = len(raw) - len(raw.rstrip())
                start += lead
                end -= trail
                value = raw.strip()
                if start >= end or not value or _PLACEHOLDER.fullmatch(value):
                    continue
                if category == "IBAN" and len(value.replace(" ", "")) < 15:
                    continue
                if category == "ORG":
                    value, start = _trim_org(value, start)
                    end = start + len(value)
                idx = bisect.bisect_left(starts, start)
                if idx > 0 and chosen[idx - 1].end > start:
                    continue
                if idx < len(chosen) and chosen[idx].start < end:
                    continue
                starts.insert(idx, start)
                chosen.insert(idx, _Span(start, end, category, value))
        return chosen

    def pseudonymize(self, text: str) -> str:
        """Ersetzt alle erkannten Identifikatoren durch stabile Platzhalter."""
        if not text:
            return text
        out: list[str] = []
        cursor = 0
        for span in self.find_spans(text):
            out.append(text[cursor : span.start])
            out.append(self._token_for(span.category, span.value))
            cursor = span.end
        out.append(text[cursor:])
        return "".join(out)

    def reidentify(self, text: str, *, json_escape: bool = False) -> str:
        """Setzt die Originalwerte wieder ein (optional JSON-escaped)."""

        def replace(match: re.Match[str]) -> str:
            value = self._reverse.get(match.group(0))
            if value is None:
                return match.group(0)
            return json.dumps(value, ensure_ascii=False)[1:-1] if json_escape else value

        return _PLACEHOLDER.sub(replace, text)

    @property
    def report(self) -> dict[str, int]:
        """Anzahl pseudonymisierter Werte je Kategorie - ohne Klartext."""
        return dict(sorted(self._counters.items()))

    def clear(self) -> None:
        self._forward.clear()
        self._reverse.clear()


class VaultedClient(StructuredLLMClient):
    """Wrapper: Pseudonymisiert jede ausgehende Nachricht, re-identifiziert jede Antwort.

    Weil der Wrapper auf ``_post_chat`` sitzt, greift er auch in der
    Reparaturrunde: Die (bereits re-identifizierte) Vorantwort wird vor dem
    erneuten Versand wieder pseudonymisiert.
    """

    def __init__(self, inner: StructuredLLMClient, vault: PrivacyVault | None = None) -> None:
        self._inner = inner
        self.vault = vault or PrivacyVault()
        self.provider = inner.provider

    @property
    def model(self) -> str:
        return self._inner.model

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def _post_chat(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        outgoing: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                outgoing.append(message)
            else:
                outgoing.append({**message, "content": self.vault.pseudonymize(message["content"])})
        outgoing.insert(1 if outgoing and outgoing[0]["role"] == "system" else 0,
                        {"role": "system", "content": VAULT_SYSTEM_NOTE})
        raw = await self._inner._post_chat(outgoing, json_mode=json_mode)  # noqa: SLF001
        return self.vault.reidentify(raw, json_escape=json_mode)
