"""Pydantic-v2-Datenmodelle der gesamten Anwendung.

Die Modelle erfuellen zwei Aufgaben gleichzeitig:

* **Vertrag gegenueber dem LLM** - aus ``model_json_schema()`` wird der
  JSON-Vertrag generiert, den das Modell einhalten muss.  Diese Modelle sind
  bewusst tolerant gegenueber typischen LLM-Eigenheiten (deutsche Datums- und
  Betragsformate, ``"nicht angegeben"`` statt ``null``, zusaetzliche Keys).
* **Vertrag gegenueber dem API-Client** - aus denselben Modellen entsteht die
  OpenAPI-Dokumentation.

Alles, was aus dem Modell kommt, wird strikt validiert, bevor es die
Persistenzschicht erreicht.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# ---------------------------------------------------------------------------
# Hilfsfunktionen fuer die tolerante Normalisierung von LLM-Ausgaben
# ---------------------------------------------------------------------------

#: Zeichenketten, die ein LLM anstelle von ``null`` liefert.
_NULL_TOKENS = {
    "", "-", "--", "n/a", "na", "null", "none", "nil", "unbekannt", "unknown",
    "nicht angegeben", "nicht vorhanden", "keine angabe", "keine angaben",
    "not specified", "not available", "k.a.", "ka", "entfaellt", "entfällt",
}

_GERMAN_MONTHS = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "maerz": 3, "märz": 3,
    "mrz": 3, "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6,
    "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "sept": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
    "%d.%m.%y", "%Y%m%d", "%m/%d/%Y",
)

_CURRENCY_SYMBOLS = {
    "€": "EUR", "eur": "EUR", "euro": "EUR",
    "$": "USD", "usd": "USD", "us$": "USD",
    "£": "GBP", "gbp": "GBP",
    "chf": "CHF", "sfr": "CHF",
}

_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def normalize_optional_text(value: Any) -> Any:
    """Trimmt Strings und uebersetzt Platzhalter-Formulierungen nach ``None``."""
    if not isinstance(value, str):
        return value
    cleaned = " ".join(value.split())
    if cleaned.casefold() in _NULL_TOKENS:
        return None
    return cleaned


def parse_flexible_date(value: Any) -> Any:
    """Akzeptiert ISO-, deutsche und ausgeschriebene Datumsangaben."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    value = normalize_optional_text(value)
    if value is None or not isinstance(value, str):
        return value

    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # "15. Maerz 2024" / "15 Maerz 2024"
    match = re.match(r"^(\d{1,2})\.?\s+([A-Za-zÄÖÜäöü]+)\.?\s+(\d{4})$", text)
    if match:
        day, month_name, year = match.groups()
        month = _GERMAN_MONTHS.get(month_name.casefold())
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None

    # Unparsbare Angabe verwerfen statt einen Validierungsfehler zu erzwingen -
    # ein fehlendes Datum ist fachlich verkraftbar, ein Abbruch nicht.
    return None


def parse_flexible_amount(value: Any) -> Any:
    """Wandelt ``"1.234,56 EUR"`` / ``"1,234.56"`` / ``1234.56`` in ``Decimal``."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    value = normalize_optional_text(value)
    if value is None or not isinstance(value, str):
        return value

    text = re.sub(r"[^\d,.\-]", "", value).strip()
    if not text or text in {"-", ".", ","}:
        return None

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # Das zuletzt auftretende Trennzeichen ist das Dezimaltrennzeichen.
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousand_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousand_sep, "").replace(decimal_sep, ".")
    elif has_comma:
        # "1,234" ist mehrdeutig: exakt dreistellige Gruppen deuten auf Tausender.
        is_grouped = re.fullmatch(r"-?\d{1,3}(,\d{3})+", text) is not None
        text = text.replace(",", "" if is_grouped else ".")
    elif has_dot:
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
            text = text.replace(".", "")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_currency(value: Any) -> Any:
    """Normalisiert Waehrungsangaben auf ISO-4217 (``EUR``, ``USD``, ...)."""
    value = normalize_optional_text(value)
    if not isinstance(value, str):
        return value
    key = value.strip().casefold()
    if key in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[key]
    upper = value.strip().upper()
    return upper if re.fullmatch(r"[A-Z]{3}", upper) else None


def normalize_iban(value: Any) -> Any:
    """Entfernt Gruppierungszeichen und schreibt die IBAN gross."""
    value = normalize_optional_text(value)
    if not isinstance(value, str):
        return value
    candidate = re.sub(r"[\s\-]", "", value).upper()
    return candidate or None


def iban_checksum_valid(iban: str) -> bool:
    """IBAN-Pruefsumme nach ISO 13616 / MOD-97-10."""
    candidate = re.sub(r"[\s\-]", "", iban).upper()
    if not _IBAN_RE.fullmatch(candidate):
        return False
    rearranged = candidate[4:] + candidate[:4]
    numeric = "".join(
        str(ord(char) - 55) if char.isalpha() else char for char in rearranged
    )
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Aufzaehlungstypen
# ---------------------------------------------------------------------------


class DocumentStatus(str, Enum):
    """Lebenszyklus eines Dokuments in der Verarbeitungspipeline."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    FAILED = "failed"


class DocType(str, Enum):
    """Fachliche Dokumentklasse."""

    INVOICE = "invoice"
    CONTRACT = "contract"
    OFFER = "offer"
    REMINDER = "reminder"
    OTHER = "other"


class AIActRiskLevel(str, Enum):
    """Risikostufen des EU AI Act (VO (EU) 2024/1689)."""

    UNACCEPTABLE = "unacceptable"      # Art. 5 - verbotene Praktiken
    HIGH = "high"                      # Art. 6 i. V. m. Anhang III
    LIMITED = "limited"                # Art. 50 - Transparenzpflichten
    MINIMAL = "minimal"
    NOT_APPLICABLE = "not_applicable"  # kein KI-System im Dokument beschrieben


class AnnexIIICategory(str, Enum):
    """Hochrisiko-Anwendungsbereiche nach Anhang III des EU AI Act."""

    BIOMETRICS = "biometrics"                                       # Nr. 1
    CRITICAL_INFRASTRUCTURE = "critical_infrastructure"             # Nr. 2
    EDUCATION = "education_and_vocational_training"                 # Nr. 3
    EMPLOYMENT = "employment_and_worker_management"                 # Nr. 4 (HR/Recruiting)
    ESSENTIAL_SERVICES = "essential_services_and_creditworthiness"  # Nr. 5 (Kreditwuerdigkeit)
    LAW_ENFORCEMENT = "law_enforcement"                             # Nr. 6
    MIGRATION_AND_BORDER = "migration_asylum_border_control"        # Nr. 7
    JUSTICE_AND_DEMOCRACY = "justice_and_democratic_processes"      # Nr. 8


#: Menschenlesbare deutsche Bezeichnungen fuer Reports und UI.
ANNEX_III_LABELS: dict[AnnexIIICategory, str] = {
    AnnexIIICategory.BIOMETRICS: "Anhang III Nr. 1 - Biometrie",
    AnnexIIICategory.CRITICAL_INFRASTRUCTURE: "Anhang III Nr. 2 - Kritische Infrastruktur",
    AnnexIIICategory.EDUCATION: "Anhang III Nr. 3 - Allgemeine und berufliche Bildung",
    AnnexIIICategory.EMPLOYMENT: "Anhang III Nr. 4 - Beschaeftigung und Personalmanagement",
    AnnexIIICategory.ESSENTIAL_SERVICES: (
        "Anhang III Nr. 5 - Wesentliche Dienste, u. a. Kreditwuerdigkeitspruefung"
    ),
    AnnexIIICategory.LAW_ENFORCEMENT: "Anhang III Nr. 6 - Strafverfolgung",
    AnnexIIICategory.MIGRATION_AND_BORDER: "Anhang III Nr. 7 - Migration, Asyl und Grenzkontrolle",
    AnnexIIICategory.JUSTICE_AND_DEMOCRACY: "Anhang III Nr. 8 - Rechtspflege und demokratische Prozesse",
}


class PIICategory(str, Enum):
    """Kategorien personenbezogener Daten (DSGVO)."""

    # Besondere Kategorien - Art. 9 DSGVO
    HEALTH_DATA = "health_data"
    RELIGIOUS_BELIEF = "religious_belief"
    ETHNIC_ORIGIN = "racial_or_ethnic_origin"
    POLITICAL_OPINION = "political_opinion"
    TRADE_UNION = "trade_union_membership"
    BIOMETRIC_DATA = "biometric_data"
    GENETIC_DATA = "genetic_data"
    SEX_LIFE = "sex_life_or_orientation"
    # Strafrechtliche Daten - Art. 10 DSGVO
    CRIMINAL_DATA = "criminal_offence_data"
    # Allgemeine Identifikatoren - Art. 4 Nr. 1 DSGVO
    ID_DOCUMENT_NUMBER = "id_document_number"
    SOCIAL_SECURITY_NUMBER = "social_security_number"
    TAX_ID = "tax_identification_number"
    BANK_ACCOUNT = "bank_account"
    DATE_OF_BIRTH = "date_of_birth"
    NAME = "name"
    ADDRESS = "address"
    CONTACT_DATA = "contact_data"
    OTHER = "other_personal_data"


#: Kategorien, die unter Art. 9/10 DSGVO besonders geschuetzt sind.
SPECIAL_CATEGORIES: frozenset[PIICategory] = frozenset(
    {
        PIICategory.HEALTH_DATA,
        PIICategory.RELIGIOUS_BELIEF,
        PIICategory.ETHNIC_ORIGIN,
        PIICategory.POLITICAL_OPINION,
        PIICategory.TRADE_UNION,
        PIICategory.BIOMETRIC_DATA,
        PIICategory.GENETIC_DATA,
        PIICategory.SEX_LIFE,
        PIICategory.CRIMINAL_DATA,
    }
)

PII_CATEGORY_LABELS: dict[PIICategory, str] = {
    PIICategory.HEALTH_DATA: "Gesundheitsdaten (Art. 9 Abs. 1 DSGVO)",
    PIICategory.RELIGIOUS_BELIEF: "Religions- oder Weltanschauungszugehoerigkeit (Art. 9 Abs. 1 DSGVO)",
    PIICategory.ETHNIC_ORIGIN: "Rassische oder ethnische Herkunft (Art. 9 Abs. 1 DSGVO)",
    PIICategory.POLITICAL_OPINION: "Politische Meinung (Art. 9 Abs. 1 DSGVO)",
    PIICategory.TRADE_UNION: "Gewerkschaftszugehoerigkeit (Art. 9 Abs. 1 DSGVO)",
    PIICategory.BIOMETRIC_DATA: "Biometrische Daten (Art. 9 Abs. 1 DSGVO)",
    PIICategory.GENETIC_DATA: "Genetische Daten (Art. 9 Abs. 1 DSGVO)",
    PIICategory.SEX_LIFE: "Sexualleben oder sexuelle Orientierung (Art. 9 Abs. 1 DSGVO)",
    PIICategory.CRIMINAL_DATA: "Strafrechtliche Verurteilungen und Straftaten (Art. 10 DSGVO)",
    PIICategory.ID_DOCUMENT_NUMBER: "Ausweis- oder Passnummer",
    PIICategory.SOCIAL_SECURITY_NUMBER: "Sozialversicherungsnummer",
    PIICategory.TAX_ID: "Steueridentifikationsnummer",
    PIICategory.BANK_ACCOUNT: "Bankverbindung (IBAN/BIC)",
    PIICategory.DATE_OF_BIRTH: "Geburtsdatum",
    PIICategory.NAME: "Name einer natuerlichen Person",
    PIICategory.ADDRESS: "Anschrift",
    PIICategory.CONTACT_DATA: "Kontaktdaten (E-Mail, Telefon)",
    PIICategory.OTHER: "Sonstige personenbezogene Daten",
}


class RiskLevel(str, Enum):
    """Generische Risikoeinstufung fuer den DSGVO-Teilbericht."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DetectionSource(str, Enum):
    """Herkunft eines PII-Treffers - fuer die Nachvollziehbarkeit des Audits."""

    LLM = "llm"
    RULE_BASED = "rule_based"
    BOTH = "both"


# ---------------------------------------------------------------------------
# Basisklassen
# ---------------------------------------------------------------------------

#: LLM-Ausgaben: unbekannte Zusatzfelder werden ignoriert statt zu scheitern.
_LLM_CONFIG = ConfigDict(
    extra="ignore",
    str_strip_whitespace=True,
    validate_default=True,
)


class LLMModel(BaseModel):
    """Basis fuer alle Modelle, die direkt aus einer LLM-Antwort entstehen."""

    model_config = _LLM_CONFIG


class ApiModel(BaseModel):
    """Basis fuer alle nach aussen sichtbaren API-Modelle."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _clean_string_list(value: Any) -> Any:
    """Normalisiert LLM-Listen aus Freitext (``None`` / String / Liste)."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return value
    cleaned = [normalize_optional_text(item) for item in value]
    return [item for item in cleaned if isinstance(item, str) and item]


def _clean_confidence(value: Any) -> Any:
    """Begrenzt Konfidenzwerte robust auf das Intervall [0, 1]."""
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            return 0.5
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return min(max(float(value), 0.0), 1.0)
    return value


# ---------------------------------------------------------------------------
# Fachliche Extraktion (Rechnungen & Vertraege)
# ---------------------------------------------------------------------------


class ExtractionResult(LLMModel):
    """Strukturierte Kerndaten einer Rechnung oder eines Vertrags."""

    doc_type: DocType = Field(
        default=DocType.OTHER,
        description="Dokumentklasse: invoice, contract, offer, reminder oder other.",
    )
    sender: str | None = Field(
        default=None,
        max_length=300,
        description="Aussteller bzw. Absender des Dokuments (Firma oder Person).",
    )
    recipient: str | None = Field(
        default=None,
        max_length=300,
        description="Empfaenger des Dokuments (Firma oder Person).",
    )
    document_number: str | None = Field(
        default=None,
        max_length=120,
        description="Rechnungs-, Vertrags- oder Belegnummer.",
    )
    document_date: date | None = Field(
        default=None,
        description="Ausstellungsdatum im Format YYYY-MM-DD.",
    )
    due_date: date | None = Field(
        default=None,
        description="Faelligkeitsdatum bzw. Vertragsende im Format YYYY-MM-DD.",
    )
    total_amount: Decimal | None = Field(
        default=None,
        description="Gesamtbetrag inkl. Steuern als Dezimalzahl (Punkt als Trennzeichen).",
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Waehrung als ISO-4217-Code, z. B. EUR.",
    )
    iban: str | None = Field(
        default=None,
        max_length=42,
        description="Im Dokument genannte IBAN ohne Leerzeichen.",
    )
    summary: str = Field(
        default="",
        max_length=2000,
        description="Sachliche Zusammenfassung in zwei bis vier Saetzen (Deutsch).",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Auffaelligkeiten: fehlende Pflichtangaben, Widersprueche, ungewoehnliche Klauseln.",
    )

    # --- Normalisierung ----------------------------------------------------
    @field_validator("sender", "recipient", "document_number", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return normalize_optional_text(value)

    @field_validator("summary", mode="before")
    @classmethod
    def _clean_summary(cls, value: Any) -> Any:
        return normalize_optional_text(value) or ""

    @field_validator("document_date", "due_date", mode="before")
    @classmethod
    def _clean_date(cls, value: Any) -> Any:
        return parse_flexible_date(value)

    @field_validator("total_amount", mode="before")
    @classmethod
    def _clean_amount(cls, value: Any) -> Any:
        return parse_flexible_amount(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _clean_currency(cls, value: Any) -> Any:
        return normalize_currency(value)

    @field_validator("iban", mode="before")
    @classmethod
    def _clean_iban(cls, value: Any) -> Any:
        return normalize_iban(value)

    @field_validator("doc_type", mode="before")
    @classmethod
    def _clean_doc_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            key = value.strip().casefold()
            aliases = {
                "rechnung": "invoice", "invoice": "invoice",
                "vertrag": "contract", "contract": "contract",
                "angebot": "offer", "offer": "offer", "quote": "offer",
                "mahnung": "reminder", "reminder": "reminder",
            }
            return aliases.get(key, key or "other")
        return value

    @field_validator("issues", mode="before")
    @classmethod
    def _clean_issues(cls, value: Any) -> Any:
        return _clean_string_list(value)

    @computed_field(  # type: ignore[prop-decorator]
        description="MOD-97-Pruefsummenkontrolle; null, wenn keine IBAN gefunden wurde."
    )
    @property
    def iban_valid(self) -> bool | None:
        return iban_checksum_valid(self.iban) if self.iban else None


# ---------------------------------------------------------------------------
# EU-AI-Act-Bewertung
# ---------------------------------------------------------------------------


class AISystemFinding(LLMModel):
    """Ein im Dokument beschriebenes KI-System samt Einstufung."""

    name: str = Field(
        default="",
        max_length=200,
        description="Bezeichnung des im Dokument beschriebenen Systems oder der Software.",
    )
    purpose: str = Field(
        default="",
        max_length=800,
        description="Zweckbestimmung des Systems laut Dokument.",
    )
    risk_level: AIActRiskLevel = Field(
        default=AIActRiskLevel.MINIMAL,
        description="Risikostufe nach EU AI Act fuer genau dieses System.",
    )
    annex_iii_categories: list[AnnexIIICategory] = Field(
        default_factory=list,
        description="Zutreffende Hochrisiko-Kategorien aus Anhang III (leer, wenn keine zutrifft).",
    )
    evidence: str = Field(
        default="",
        max_length=1000,
        description="Woertliche oder sinngemaesse Textstelle, die die Einstufung stuetzt.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Selbsteinschaetzung der Sicherheit zwischen 0.0 und 1.0.",
    )

    @field_validator("name", "purpose", "evidence", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return normalize_optional_text(value) or ""

    @field_validator("annex_iii_categories", mode="before")
    @classmethod
    def _clean_categories(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return value
        valid = {member.value for member in AnnexIIICategory}
        # Halluzinierte Kategorien werden verworfen statt den Audit abzubrechen.
        return [item for item in value if item in valid]

    @field_validator("confidence", mode="before")
    @classmethod
    def _clean_confidence_value(cls, value: Any) -> Any:
        return _clean_confidence(value)

    @computed_field(  # type: ignore[prop-decorator]
        description="Deutsche Klartextbezeichnungen der Anhang-III-Kategorien."
    )
    @property
    def annex_iii_labels(self) -> list[str]:
        return [ANNEX_III_LABELS[category] for category in self.annex_iii_categories]


class AIActAssessment(LLMModel):
    """Gesamtergebnis der EU-AI-Act-Pruefung eines Dokuments."""

    describes_ai_system: bool = Field(
        default=False,
        description="True, wenn das Dokument mindestens ein KI-System beschreibt oder beschafft.",
    )
    overall_risk_level: AIActRiskLevel = Field(
        default=AIActRiskLevel.NOT_APPLICABLE,
        description="Hoechste im Dokument festgestellte Risikostufe.",
    )
    systems: list[AISystemFinding] = Field(
        default_factory=list,
        description="Liste der erkannten KI-Systeme.",
    )
    reasoning: str = Field(
        default="",
        max_length=2000,
        description="Nachvollziehbare Begruendung der Gesamteinstufung auf Deutsch.",
    )
    obligations: list[str] = Field(
        default_factory=list,
        description="Konkrete Pflichten, die sich aus der Einstufung ergeben (Deutsch).",
    )

    @field_validator("reasoning", mode="before")
    @classmethod
    def _clean_reasoning(cls, value: Any) -> Any:
        return normalize_optional_text(value) or ""

    @field_validator("obligations", mode="before")
    @classmethod
    def _clean_obligations(cls, value: Any) -> Any:
        return _clean_string_list(value)

    @field_validator("systems", mode="before")
    @classmethod
    def _clean_systems(cls, value: Any) -> Any:
        if value is None:
            return []
        return value

    @computed_field(  # type: ignore[prop-decorator]
        description="True, wenn mindestens ein System als Hochrisiko eingestuft wurde."
    )
    @property
    def is_high_risk(self) -> bool:
        critical = {AIActRiskLevel.HIGH, AIActRiskLevel.UNACCEPTABLE}
        return self.overall_risk_level in critical or any(
            system.risk_level in critical for system in self.systems
        )


# ---------------------------------------------------------------------------
# DSGVO-Bewertung
# ---------------------------------------------------------------------------


class PIIFinding(LLMModel):
    """Ein einzelner Treffer personenbezogener Daten."""

    category: PIICategory = Field(description="Kategorie des gefundenen Datums.")
    masked_value: str = Field(
        default="",
        max_length=200,
        description=(
            "Maskierter Auszug des Fundes, z. B. 'DE89****1234'. "
            "Niemals der vollstaendige Wert."
        ),
    )
    context: str = Field(
        default="",
        max_length=500,
        description="Kurzer, ebenfalls entschaerfter Kontext der Fundstelle.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: DetectionSource = Field(
        default=DetectionSource.LLM,
        description="Wurde der Treffer vom LLM, von den Regexregeln oder von beiden gefunden?",
    )

    @field_validator("masked_value", "context", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return normalize_optional_text(value) or ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _clean_confidence_value(cls, value: Any) -> Any:
        return _clean_confidence(value)

    @computed_field(  # type: ignore[prop-decorator]
        description="True bei besonderen Kategorien nach Art. 9/10 DSGVO."
    )
    @property
    def is_special_category(self) -> bool:
        return self.category in SPECIAL_CATEGORIES

    @computed_field(description="Deutsche Klartextbezeichnung der Kategorie.")  # type: ignore[prop-decorator]
    @property
    def category_label(self) -> str:
        return PII_CATEGORY_LABELS[self.category]


class GDPRAssessment(LLMModel):
    """Gesamtergebnis der DSGVO-Pruefung eines Dokuments."""

    contains_personal_data: bool = Field(
        default=False,
        description="Enthaelt das Dokument personenbezogene Daten?",
    )
    findings: list[PIIFinding] = Field(
        default_factory=list,
        description="Alle erkannten PII-Fundstellen.",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.NONE,
        description="Datenschutzrechtliche Gesamtrisikostufe.",
    )
    reasoning: str = Field(
        default="",
        max_length=2000,
        description="Begruendung der Einstufung auf Deutsch.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Empfohlene Massnahmen, z. B. Loeschfristen oder Zugriffsbeschraenkungen.",
    )

    @field_validator("reasoning", mode="before")
    @classmethod
    def _clean_reasoning(cls, value: Any) -> Any:
        return normalize_optional_text(value) or ""

    @field_validator("recommendations", mode="before")
    @classmethod
    def _clean_recommendations(cls, value: Any) -> Any:
        return _clean_string_list(value)

    @field_validator("findings", mode="before")
    @classmethod
    def _clean_findings(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        # Treffer ohne gueltige Kategorie werden still verworfen.
        valid = {member.value for member in PIICategory}
        return [
            item
            for item in value
            if not isinstance(item, dict) or item.get("category") in valid
        ]

    @computed_field(  # type: ignore[prop-decorator]
        description="True, wenn besondere Kategorien nach Art. 9/10 DSGVO vorliegen."
    )
    @property
    def contains_special_categories(self) -> bool:
        return any(finding.category in SPECIAL_CATEGORIES for finding in self.findings)

    @computed_field(description="Anzahl der Treffer je Kategorie.")  # type: ignore[prop-decorator]
    @property
    def findings_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category.value] = counts.get(finding.category.value, 0) + 1
        return counts


class ComplianceAudit(ApiModel):
    """Buendel aus AI-Act- und DSGVO-Bewertung inklusive Metadaten."""

    # Dieses Modell wird als JSON persistiert und beim Lesen wieder validiert.
    # Berechnete Felder (``headline``) sind Teil des Dumps, aber keine Eingabe-
    # felder - deshalb hier "ignore" statt des sonst ueblichen "forbid".
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ai_act: AIActAssessment
    gdpr: GDPRAssessment
    model: str = Field(description="Modell, das die Bewertung erzeugt hat.")
    audited_at: datetime = Field(description="Zeitpunkt der Bewertung (UTC).")
    duration_ms: int = Field(default=0, ge=0, description="Dauer der Bewertung in Millisekunden.")

    @computed_field(description="Kurzfazit fuer Uebersichtslisten und Dashboards.")  # type: ignore[prop-decorator]
    @property
    def headline(self) -> str:
        parts: list[str] = []
        if self.ai_act.is_high_risk:
            parts.append("EU AI Act: Hochrisiko")
        elif self.ai_act.describes_ai_system:
            parts.append(f"EU AI Act: {self.ai_act.overall_risk_level.value}")
        if self.gdpr.contains_special_categories:
            parts.append("DSGVO: besondere Kategorien (Art. 9/10)")
        elif self.gdpr.contains_personal_data:
            parts.append(f"DSGVO: personenbezogene Daten ({self.gdpr.risk_level.value})")
        return " | ".join(parts) if parts else "Keine Compliance-Auffaelligkeiten"


# ---------------------------------------------------------------------------
# API-Modelle
# ---------------------------------------------------------------------------

DocumentId = Annotated[str, Field(description="UUID4 des Dokuments.")]


class DocumentSummary(ApiModel):
    """Zeile der tabellarischen Uebersicht (GET /documents)."""

    id: DocumentId
    filename: str
    status: DocumentStatus
    size_bytes: int
    page_count: int | None = None
    doc_type: DocType | None = None
    sender: str | None = None
    document_date: date | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    ai_act_risk_level: AIActRiskLevel | None = None
    gdpr_risk_level: RiskLevel | None = None
    contains_special_categories: bool | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(ApiModel):
    """Paginierte Uebersicht aller Dokumente."""

    items: list[DocumentSummary]
    total: int = Field(ge=0, description="Gesamtzahl der Dokumente im aktiven Filter.")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DocumentDetail(ApiModel):
    """Detailansicht inklusive Extraktion und Compliance-Audit."""

    id: DocumentId
    filename: str
    content_type: str
    status: DocumentStatus
    size_bytes: int
    sha256: str
    page_count: int | None = None
    char_count: int | None = None
    model: str | None = None
    extraction: ExtractionResult | None = None
    compliance: ComplianceAudit | None = None
    text_preview: str | None = Field(
        default=None,
        description="Erste Zeichen des extrahierten Textes (gekuerzt).",
    )
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    extracted_at: datetime | None = None


class UploadResponse(ApiModel):
    """Antwort auf einen erfolgreichen PDF-Upload."""

    id: DocumentId
    filename: str
    status: DocumentStatus
    size_bytes: int
    sha256: str
    page_count: int
    char_count: int
    duplicate_of: DocumentId | None = Field(
        default=None,
        description="Gesetzt, wenn bereits ein Dokument mit identischer Pruefsumme existiert.",
    )
    created_at: datetime


class ExtractionResponse(ApiModel):
    """Antwort auf POST /documents/{id}/extract."""

    id: DocumentId
    status: DocumentStatus
    model: str
    extraction: ExtractionResult
    compliance: ComplianceAudit
    duration_ms: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Health & Fehler
# ---------------------------------------------------------------------------


class ComponentHealth(ApiModel):
    """Zustand einer einzelnen Infrastrukturkomponente."""

    status: str = Field(description="'ok', 'degraded' oder 'unavailable'.")
    detail: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class DatabaseHealth(ComponentHealth):
    dialect: str | None = None
    documents: int | None = Field(default=None, ge=0)


class OllamaHealth(ComponentHealth):
    base_url: str
    model: str
    model_available: bool = False
    available_models: list[str] = Field(default_factory=list)


class HealthResponse(ApiModel):
    """Antwort von GET /health."""

    status: str = Field(description="'ok', wenn alle Komponenten erreichbar sind, sonst 'degraded'.")
    version: str
    environment: str
    auth_enabled: bool
    timestamp: datetime
    database: DatabaseHealth
    ollama: OllamaHealth


class ErrorDetail(ApiModel):
    """Maschinenlesbare Fehlerbeschreibung."""

    code: str = Field(description="Stabiler Fehlercode, z. B. 'document_not_found'.")
    message: str = Field(description="Menschenlesbare Fehlermeldung auf Deutsch.")
    hint: str | None = Field(default=None, description="Konkreter Loesungsvorschlag.")


class ErrorResponse(ApiModel):
    """Einheitliches Fehlerformat aller Endpunkte."""

    error: ErrorDetail
