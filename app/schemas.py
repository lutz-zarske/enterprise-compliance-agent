"""Pydantic-v2-Datenmodelle der gesamten Anwendung.

Die Modelle erfuellen zwei Aufgaben gleichzeitig:

* **Vertrag gegenüber dem LLM** - aus ``model_json_schema()`` wird der
  JSON-Vertrag generiert, den das Modell einhalten muss.  Diese Modelle sind
  bewusst tolerant gegenüber typischen LLM-Eigenheiten (deutsche Datums- und
  Betragsformate, ``"nicht angegeben"`` statt ``null``, zusätzliche Keys).
* **Vertrag gegenüber dem API-Client** - aus denselben Modellen entsteht die
  OpenAPI-Dokumentation.

Alles, was aus dem Modell kommt, wird strikt validiert, bevor es die
Persistenzschicht erreicht.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, Literal

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
    """Trimmt Strings und übersetzt Platzhalter-Formulierungen nach ``None``."""
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
    """Normalisiert Währungsangaben auf ISO-4217 (``EUR``, ``USD``, ...)."""
    value = normalize_optional_text(value)
    if not isinstance(value, str):
        return value
    key = value.strip().casefold()
    if key in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[key]
    upper = value.strip().upper()
    return upper if re.fullmatch(r"[A-Z]{3}", upper) else None


def normalize_iban(value: Any) -> Any:
    """Entfernt Gruppierungszeichen und schreibt die IBAN groß."""
    value = normalize_optional_text(value)
    if not isinstance(value, str):
        return value
    candidate = re.sub(r"[\s\-]", "", value).upper()
    return candidate or None


def iban_checksum_valid(iban: str) -> bool:
    """IBAN-Prüfsumme nach ISO 13616 / MOD-97-10."""
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
    AnnexIIICategory.EMPLOYMENT: "Anhang III Nr. 4 - Beschäftigung und Personalmanagement",
    AnnexIIICategory.ESSENTIAL_SERVICES: (
        "Anhang III Nr. 5 - Wesentliche Dienste, u. a. Kreditwürdigkeitsprüfung"
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
    PIICategory.RELIGIOUS_BELIEF: "Religions- oder Weltanschauungszugehörigkeit (Art. 9 Abs. 1 DSGVO)",
    PIICategory.ETHNIC_ORIGIN: "Rassische oder ethnische Herkunft (Art. 9 Abs. 1 DSGVO)",
    PIICategory.POLITICAL_OPINION: "Politische Meinung (Art. 9 Abs. 1 DSGVO)",
    PIICategory.TRADE_UNION: "Gewerkschaftszugehörigkeit (Art. 9 Abs. 1 DSGVO)",
    PIICategory.BIOMETRIC_DATA: "Biometrische Daten (Art. 9 Abs. 1 DSGVO)",
    PIICategory.GENETIC_DATA: "Genetische Daten (Art. 9 Abs. 1 DSGVO)",
    PIICategory.SEX_LIFE: "Sexualleben oder sexuelle Orientierung (Art. 9 Abs. 1 DSGVO)",
    PIICategory.CRIMINAL_DATA: "Strafrechtliche Verurteilungen und Straftaten (Art. 10 DSGVO)",
    PIICategory.ID_DOCUMENT_NUMBER: "Ausweis- oder Passnummer",
    PIICategory.SOCIAL_SECURITY_NUMBER: "Sozialversicherungsnummer",
    PIICategory.TAX_ID: "Steueridentifikationsnummer",
    PIICategory.BANK_ACCOUNT: "Bankverbindung (IBAN/BIC)",
    PIICategory.DATE_OF_BIRTH: "Geburtsdatum",
    PIICategory.NAME: "Name einer natürlichen Person",
    PIICategory.ADDRESS: "Anschrift",
    PIICategory.CONTACT_DATA: "Kontaktdaten (E-Mail, Telefon)",
    PIICategory.OTHER: "Sonstige personenbezogene Daten",
}


class RiskLevel(str, Enum):
    """Generische Risikoeinstufung für den DSGVO-Teilbericht."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DetectionSource(str, Enum):
    """Herkunft eines PII-Treffers - für die Nachvollziehbarkeit des Audits."""

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
    """Basis für alle Modelle, die direkt aus einer LLM-Antwort entstehen."""

    model_config = _LLM_CONFIG


class ApiModel(BaseModel):
    """Basis für alle nach aussen sichtbaren API-Modelle."""

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
        description="Empfänger des Dokuments (Firma oder Person).",
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
        description="Fälligkeitsdatum bzw. Vertragsende im Format YYYY-MM-DD.",
    )
    total_amount: Decimal | None = Field(
        default=None,
        description="Gesamtbetrag inkl. Steuern als Dezimalzahl (Punkt als Trennzeichen).",
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Währung als ISO-4217-Code, z. B. EUR.",
    )
    iban: str | None = Field(
        default=None,
        max_length=42,
        description="Im Dokument genannte IBAN ohne Leerzeichen.",
    )
    summary: str = Field(
        default="",
        max_length=2000,
        description="Sachliche Zusammenfassung in zwei bis vier Sätzen (Deutsch).",
    )
    # --- Pflichtangaben nach Paragraf 14 Abs. 4 UStG (seit v2.0) -------------
    sender_address: str | None = Field(default=None, max_length=400, description="Anschrift des Ausstellers.")
    recipient_address: str | None = Field(default=None, max_length=400, description="Anschrift des Empfängers.")
    sender_tax_number: str | None = Field(default=None, max_length=40, description="Steuernummer des Ausstellers.")
    sender_vat_id: str | None = Field(default=None, max_length=20, description="USt-IdNr. des Ausstellers.")
    service_date: date | None = Field(default=None, description="Liefer-/Leistungsdatum.")
    service_period: str | None = Field(default=None, max_length=120, description="Leistungszeitraum als Text.")
    items_description: str | None = Field(
        default=None, max_length=600, description="Menge und Art der Lieferung bzw. Umfang und Art der Leistung."
    )
    net_amount: Decimal | None = Field(default=None, description="Nettoentgelt.")
    tax_rate: Decimal | None = Field(default=None, description="Umsatzsteuersatz in Prozent, z. B. 19.")
    tax_amount: Decimal | None = Field(default=None, description="Umsatzsteuerbetrag.")
    tax_exemption_note: str | None = Field(
        default=None, max_length=300, description="Hinweis auf Steuerbefreiung / Reverse Charge."
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Auffälligkeiten: fehlende Pflichtangaben, Widersprüche, ungewöhnliche Klauseln.",
    )

    # --- Normalisierung ----------------------------------------------------
    @field_validator(
        "sender", "recipient", "document_number", "sender_address", "recipient_address",
        "sender_tax_number", "sender_vat_id", "service_period", "items_description",
        "tax_exemption_note",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, value: Any) -> Any:
        return normalize_optional_text(value)

    @field_validator("service_date", mode="before")
    @classmethod
    def _clean_service_date(cls, value: Any) -> Any:
        return parse_flexible_date(value)

    @field_validator("net_amount", "tax_amount", mode="before")
    @classmethod
    def _clean_money(cls, value: Any) -> Any:
        return parse_flexible_amount(value)

    @field_validator("tax_rate", mode="before")
    @classmethod
    def _clean_rate(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.replace("%", "")
        rate = parse_flexible_amount(value)
        # 0.19 statt 19 -> in Prozent umrechnen.
        if isinstance(rate, Decimal) and Decimal(0) < rate < Decimal(1):
            rate = rate * 100
        return rate

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
        description="MOD-97-Prüfsummenkontrolle; null, wenn keine IBAN gefunden wurde."
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
        description="Risikostufe nach EU AI Act für genau dieses System.",
    )
    annex_iii_categories: list[AnnexIIICategory] = Field(
        default_factory=list,
        description="Zutreffende Hochrisiko-Kategorien aus Anhang III (leer, wenn keine zutrifft).",
    )
    evidence: str = Field(
        default="",
        max_length=1000,
        description="Wörtliche oder sinngemäße Textstelle, die die Einstufung stützt.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Selbsteinschätzung der Sicherheit zwischen 0.0 und 1.0.",
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
    """Gesamtergebnis der EU-AI-Act-Prüfung eines Dokuments."""

    describes_ai_system: bool = Field(
        default=False,
        description="True, wenn das Dokument mindestens ein KI-System beschreibt oder beschafft.",
    )
    overall_risk_level: AIActRiskLevel = Field(
        default=AIActRiskLevel.NOT_APPLICABLE,
        description="Höchste im Dokument festgestellte Risikostufe.",
    )
    systems: list[AISystemFinding] = Field(
        default_factory=list,
        description="Liste der erkannten KI-Systeme.",
    )
    reasoning: str = Field(
        default="",
        max_length=2000,
        description="Nachvollziehbare Begründung der Gesamteinstufung auf Deutsch.",
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
            "Niemals der vollständige Wert."
        ),
    )
    context: str = Field(
        default="",
        max_length=500,
        description="Kurzer, ebenfalls entschärfter Kontext der Fundstelle.",
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
    """Gesamtergebnis der DSGVO-Prüfung eines Dokuments."""

    contains_personal_data: bool = Field(
        default=False,
        description="Enthält das Dokument personenbezogene Daten?",
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
        description="Begründung der Einstufung auf Deutsch.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Empfohlene Maßnahmen, z. B. Löschfristen oder Zugriffsbeschränkungen.",
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
    """Bündel aus AI-Act- und DSGVO-Bewertung inklusive Metadaten."""

    # Dieses Modell wird als JSON persistiert und beim Lesen wieder validiert.
    # Berechnete Felder (``headline``) sind Teil des Dumps, aber keine Eingabe-
    # felder - deshalb hier "ignore" statt des sonst ueblichen "forbid".
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ai_act: AIActAssessment
    gdpr: GDPRAssessment
    model: str = Field(description="Modell, das die Bewertung erzeugt hat.")
    audited_at: datetime = Field(description="Zeitpunkt der Bewertung (UTC).")
    duration_ms: int = Field(default=0, ge=0, description="Dauer der Bewertung in Millisekunden.")
    provider: str = Field(default="local", description="local | gemini | anthropic | openai")
    privacy_gateway: dict[str, int] | None = Field(
        default=None,
        description="Bei Cloud-Inferenz: Anzahl pseudonymisierter Werte je Kategorie (ohne Klartext).",
    )
    failover: list[dict[str, str]] | None = Field(
        default=None,
        description="Provider-Wechsel während der Analyse (Ausfall, 429, Zeitüberschreitung), je Wechsel im Ledger.",
    )
    heuristic: bool = Field(
        default=False,
        description="True, wenn alle KI-Stufen ausfielen und das deterministische Regelwerk die Prüfung abschloss.",
    )
    fallback_reason: str | None = Field(
        default=None, description="Grund für das regelbasierte Referenz-Audit (z. B. Überlast aller Stufen)."
    )

    @computed_field(description="Kurzfazit für Übersichtslisten und Dashboards.")  # type: ignore[prop-decorator]
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
        return " | ".join(parts) if parts else "Keine Compliance-Auffälligkeiten"


# ---------------------------------------------------------------------------
# API-Modelle
# ---------------------------------------------------------------------------

DocumentId = Annotated[str, Field(description="UUID4 des Dokuments.")]


class DocumentSummary(ApiModel):
    """Zeile der tabellarischen Übersicht (GET /documents)."""

    id: DocumentId
    filename: str
    status: DocumentStatus
    size_bytes: int
    page_count: int | None = None
    doc_type: DocType | None = None
    sender: str | None = None
    document_number: str | None = None
    document_date: date | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    ai_act_risk_level: AIActRiskLevel | None = None
    gdpr_risk_level: RiskLevel | None = None
    contains_special_categories: bool | None = None
    compliance_score: int | None = None
    score_band: str | None = None
    pii_findings: int | None = None
    sealed: bool = False
    pinned: bool = False
    archived: bool = False
    provider: str | None = None
    einvoice_profile: str | None = Field(
        default=None, description="Profil der strukturierten E-Rechnung (z. B. 'XRECHNUNG 3.0'), sonst null."
    )
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(ApiModel):
    """Paginierte Übersicht aller Dokumente."""

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
        description="Erste Zeichen des extrahierten Textes (gekürzt, gemäß PII-Strenge geschwärzt).",
    )
    scorecard: Scorecard | None = None
    sign_off: SignOff | None = None
    text_view: TextView | None = None
    einvoice: EInvoiceData | None = Field(
        default=None, description="EN-16931-Datensatz (eingebettetes oder reines XML), sonst null."
    )
    pinned: bool = False
    archived: bool = False
    archived_at: datetime | None = None
    provider: str | None = None
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
        description="Gesetzt, wenn bereits ein Dokument mit identischer Prüfsumme existiert.",
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
    scorecard: Scorecard | None = None
    provider: str | None = None
    audit_entry_id: str | None = None


# ---------------------------------------------------------------------------
# Compliance-Scorecard (seit v2.0)
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ScoreBand(str, Enum):
    GREEN = "green"   # >= 85: verkehrsfaehig
    AMBER = "amber"   # 60-84: Nachbesserung
    RED = "red"       # < 60: Revisionssperre


class ScoreCheck(ApiModel):
    """Ein einzelnes Prüfmerkmal (z. B. Paragraf 14 Abs. 4 Nr. 2 UStG)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    legal_reference: str | None = None
    status: CheckStatus
    deduction: int = 0
    detail: str | None = None
    evidence_source: str | None = Field(
        default=None, description="'llm', 'rule_based' oder 'both' - woher der Nachweis stammt."
    )
    risk_note: str | None = Field(
        default=None, description="Ein Satz zur steuerlichen bzw. haftungsrechtlichen Folge eines Mangels."
    )
    note: str | None = Field(default=None, description="Rechtlicher Kontext (z. B. Stichtage, Ausnahmen).")


class ScoreTile(ApiModel):
    """Eine der vier Unterkacheln der Scorecard."""

    model_config = ConfigDict(extra="ignore")

    key: str
    title: str
    status: CheckStatus
    headline: str
    deduction: int = 0
    checks: list[ScoreCheck] = Field(default_factory=list)


class RetentionInfo(ApiModel):
    """Aufbewahrungsfrist eines Belegs nach BEG IV (§ 147 AO, § 14b UStG)."""

    model_config = ConfigDict(extra="ignore")

    years: int
    until: date
    financial_sector_until: date
    basis: str
    note: str


class HumanOverride(ApiModel):
    """Uebersteuerung einer KI-Einstufung durch eine natürliche Person (Art. 14 Abs. 4 lit. d AI Act)."""

    model_config = ConfigDict(extra="ignore")

    auditor_name: str
    previous_risk_level: AIActRiskLevel
    new_risk_level: AIActRiskLevel
    previous_score: int | None = None
    new_score: int
    reason: str
    legal_basis: str
    overridden_at: datetime
    ledger_entry_id: str = ""
    ledger_entry_hash: str = ""


class Scorecard(ApiModel):
    """Deterministischer Compliance-Score (0-100) mit Begründung je Abzug."""

    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=100)
    band: ScoreBand
    band_label: str
    cap_applied: str | None = Field(default=None, description="Begründung, falls der Score gedeckelt wurde.")
    tiles: list[ScoreTile]
    release_recommendation: str
    release_blocked: bool
    ustg_required_total: int = 0
    ustg_fulfilled: int = 0
    small_amount_invoice: bool = False
    structured_einvoice_detected: bool = False
    computed_at: datetime
    ruleset_version: str
    human_override: HumanOverride | None = Field(
        default=None, description="Gesetzt, wenn eine Prüfperson die KI-Einstufung uebersteuert hat."
    )
    retention: RetentionInfo | None = Field(
        default=None, description="Aufbewahrungsfrist bei Rechnungen mit Belegdatum (BEG IV)."
    )


# ---------------------------------------------------------------------------
# Strukturierte E-Rechnung nach EN 16931 (seit v2.1)
# ---------------------------------------------------------------------------


class EInvoiceParty(ApiModel):
    """Verkäufer bzw. Käufer aus dem XML-Datensatz."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    vat_id: str | None = None
    tax_number: str | None = None
    street: str | None = None
    postcode: str | None = None
    city: str | None = None
    country: str | None = None
    electronic_address: str | None = None
    electronic_address_scheme: str | None = None

    @computed_field(description="Anschrift in einer Zeile.")  # type: ignore[prop-decorator]
    @property
    def address(self) -> str | None:
        city = " ".join(part for part in (self.postcode, self.city) if part)
        parts = [part for part in (self.street, city, self.country) if part]
        return ", ".join(parts) or None


class EInvoiceVat(ApiModel):
    """Eine Zeile der Umsatzsteueraufschluesselung (BG-23)."""

    model_config = ConfigDict(extra="ignore")

    category: str | None = None
    rate: Decimal | None = None
    taxable_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    exemption_reason: str | None = None


class EInvoiceLine(ApiModel):
    """Eine Rechnungsposition (BG-25)."""

    model_config = ConfigDict(extra="ignore")

    line_id: str | None = None
    name: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    net_amount: Decimal | None = None
    vat_rate: Decimal | None = None


class LeitwegCheck(ApiModel):
    """Formal- und Prüfziffernkontrolle einer Leitweg-ID (KoSIT-Formatspezifikation 2.0.2)."""

    model_config = ConfigDict(extra="ignore")

    value: str
    valid: bool
    reason: str | None = None


class VisualCheck(ApiModel):
    """Abgleich eines XML-Werts mit dem visuellen PDF-Teil einer hybriden Rechnung."""

    model_config = ConfigDict(extra="ignore")

    bt: str
    label: str
    xml_value: str
    status: Literal["match", "mismatch", "not_found"]
    visual_value: str | None = None


class BusinessTermField(ApiModel):
    """Zeile der BT-Tabelle im Inspektor."""

    bt: str
    label: str
    value: str | None = None


class EInvoiceData(ApiModel):
    """Ausgelesener EN-16931-Datensatz (CII oder UBL) samt Prüfbefunden.

    Der Datensatz entsteht beim Upload und wird mit dem Dokument gespeichert.
    Bei hybriden Rechnungen (ZUGFeRD/Factur-X) ist er nach dem BMF-Schreiben vom
    15.10.2024 (Rz. 36) der führende Teil der Rechnung.
    """

    model_config = ConfigDict(extra="ignore")

    source: Literal["embedded", "standalone"]
    attachment_name: str | None = None
    error: str | None = Field(default=None, description="Gesetzt, wenn das XML nicht auswertbar ist.")
    syntax: Literal["CII", "UBL"] | None = None
    specification_id: str | None = Field(default=None, description="BT-24 Spezifikationskennung.")
    profile: str = "Unbekannt"
    profile_key: str = "unknown"
    is_einvoice: bool = Field(
        default=False,
        description="False bei MINIMUM/BASIC WL: keine E-Rechnung im Sinne von § 14 Abs. 1 UStG.",
    )
    invoice_number: str | None = None
    issue_date: date | None = None
    type_code: str | None = None
    currency: str | None = None
    buyer_reference: str | None = None
    order_reference: str | None = None
    seller: EInvoiceParty = Field(default_factory=EInvoiceParty)
    buyer: EInvoiceParty = Field(default_factory=EInvoiceParty)
    delivery_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    due_date: date | None = None
    payment_terms: str | None = None
    iban: str | None = None
    line_total: Decimal | None = None
    allowance_total: Decimal | None = None
    charge_total: Decimal | None = None
    net_total: Decimal | None = None
    tax_total: Decimal | None = None
    grand_total: Decimal | None = None
    due_payable: Decimal | None = None
    vat_breakdown: list[EInvoiceVat] = Field(default_factory=list)
    lines: list[EInvoiceLine] = Field(default_factory=list)
    rule_violations: list[str] = Field(default_factory=list)
    leitweg: LeitwegCheck | None = None
    public_buyer: bool = False
    public_buyer_reason: str | None = None
    visual_check: list[VisualCheck] = Field(default_factory=list)
    xml_sha256: str | None = None
    xml_size: int | None = None

    @computed_field(description="Zentrale Business Terms für die Tabellenansicht.")  # type: ignore[prop-decorator]
    @property
    def business_terms(self) -> list[BusinessTermField]:
        def money(value: Decimal | None) -> str | None:
            if value is None:
                return None
            text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{text} {self.currency or ''}".strip()

        def electronic(party: EInvoiceParty) -> str | None:
            if not party.electronic_address:
                return None
            scheme = party.electronic_address_scheme
            return f"{party.electronic_address} (Schema {scheme})" if scheme else party.electronic_address

        return [
            BusinessTermField(bt="BT-1", label="Rechnungsnummer", value=self.invoice_number),
            BusinessTermField(
                bt="BT-2", label="Rechnungsdatum", value=self.issue_date.strftime("%d.%m.%Y") if self.issue_date else None
            ),
            BusinessTermField(bt="BT-10", label="Käuferreferenz / Leitweg-ID", value=self.buyer_reference),
            BusinessTermField(bt="BT-27", label="Name des Verkäufers", value=self.seller.name),
            BusinessTermField(bt="BT-31", label="USt-IdNr. des Verkäufers", value=self.seller.vat_id),
            BusinessTermField(bt="BT-34", label="Elektronische Adresse des Verkäufers", value=electronic(self.seller)),
            BusinessTermField(bt="BT-44", label="Name des Käufers", value=self.buyer.name),
            BusinessTermField(bt="BT-49", label="Elektronische Adresse des Käufers", value=electronic(self.buyer)),
            BusinessTermField(bt="BT-109", label="Summe netto", value=money(self.net_total)),
            BusinessTermField(bt="BT-110", label="Umsatzsteuer gesamt", value=money(self.tax_total)),
            BusinessTermField(bt="BT-112", label="Rechnungsgesamtbetrag (brutto)", value=money(self.grand_total)),
            BusinessTermField(bt="BT-115", label="Zahlbetrag", value=money(self.due_payable)),
        ]


class SignOffDecision(str, Enum):
    APPROVED = "SEALED_APPROVED"
    REJECTED = "SEALED_REJECTED"


class SignOffRequest(ApiModel):
    auditor_name: str = Field(min_length=2, max_length=120)
    note: str = Field(default="", max_length=2000)
    decision: SignOffDecision = SignOffDecision.APPROVED


class OverrideRequest(ApiModel):
    """Uebersteuerung der EU-AI-Act-Einstufung durch die Prüfperson."""

    auditor_name: str = Field(min_length=2, max_length=120)
    risk_level: AIActRiskLevel = Field(description="Neue Risikostufe nach Würdigung durch die Prüfperson.")
    reason: str = Field(
        min_length=20, max_length=2000,
        description="Begründung - nachvollziehbar für Dritte (Art. 14 Abs. 4 lit. d, Art. 12 AI Act).",
    )
    legal_basis: str = Field(
        min_length=3, max_length=300, description="Rechtsnorm, z. B. 'Art. 6 Abs. 3 lit. d VO (EU) 2024/1689'."
    )

    @field_validator("auditor_name", "reason", "legal_basis", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class SignOff(ApiModel):
    model_config = ConfigDict(extra="ignore")

    status: SignOffDecision
    auditor_name: str
    note: str
    sealed_at: datetime
    ledger_entry_id: str
    ledger_entry_hash: str
    compliance_score: int | None = None


InferenceModeLiteral = Literal["local", "gemini", "anthropic", "openai"]


class BackupKeyInput(ApiModel):
    """Ein Ausweich-Schluessel der Kaskade (Schluessel wird verschlüsselt gespeichert, nie zurückgegeben)."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$", description="Stabile Kennung des Eintrags.")
    provider: Literal["gemini", "anthropic", "openai"]
    model: str | None = Field(default=None, max_length=120, description="Leer = Hauptmodell des Anbieters.")
    api_key: str | None = Field(default=None, max_length=400, description="Leer = gespeicherten Schluessel behalten.")


class SettingsUpdate(ApiModel):
    """Teilaktualisierung der Laufzeit-Einstellungen (nur gesetzte Felder wirken)."""

    inference_mode: InferenceModeLiteral | None = None
    models: dict[str, str] | None = Field(default=None, description="Modell je Provider.")
    api_keys: dict[str, str] | None = Field(
        default=None, description="Neue Provider-Keys; leerer String löscht den Key."
    )
    pii_strictness: Literal["strict", "standard", "audit_only"] | None = None
    enforce_ustg_check: bool | None = None
    ai_act_escalation: bool | None = None
    fallbacks: list[InferenceModeLiteral] | None = Field(
        default=None,
        max_length=3,
        description="Ausweich-Provider in Reihenfolge, je Provider einmal (z. B. ['anthropic', 'local']).",
    )
    ausweich_modelle: dict[str, Annotated[str, Field(max_length=120)]] | None = Field(
        default=None,
        description="Ausweichmodell desselben Anbieters je Cloud-Provider (leerer String = aus).",
    )
    ausweich_schluessel: list[BackupKeyInput] | None = Field(
        default=None,
        max_length=6,
        description=(
            "Ganze Liste der Ausweich-Schluessel in Reihenfolge; Einträge ohne api_key behalten "
            "den gespeicherten Schluessel derselben id."
        ),
    )


class ConnectionTestRequest(ApiModel):
    provider: InferenceModeLiteral | None = Field(default=None, description="Leer = aktiver Provider.")


class PinRequest(ApiModel):
    pinned: bool


class ArchiveRequest(ApiModel):
    archived: bool


class VatVerifyRequest(ApiModel):
    """USt-IdNr. für die VIES-Abfrage - Ländercode und Nummer getrennt."""

    country_code: str = Field(
        min_length=2, max_length=2, description="Ländercode nach VIES, z. B. 'DE' (Griechenland: 'EL')."
    )
    vat_number: str = Field(
        min_length=2, max_length=20, description="Nummer ohne Länderpräfix, z. B. '312345678'."
    )


class VatVerification(ApiModel):
    """Antwort der VIES-Abfrage (Momentaufnahme, nicht gespeichert, ohne Score-Einfluss)."""

    country_code: str
    vat_number: str
    valid: bool = Field(description="USt-IdNr. ist laut VIES zum Abfragezeitpunkt gültig.")
    name: str | None = Field(
        default=None, description="Firmenname laut VIES; Deutschland übermittelt keine Namen (dann leer)."
    )
    address: str | None = None
    request_date: datetime | None = Field(default=None, description="Zeitstempel der Behördenantwort.")
    request_identifier: str | None = Field(default=None, description="Abfrage-ID von VIES, falls vergeben.")
    source: str = "VIES – Europäische Kommission"


class CopilotTurn(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class CopilotRequest(ApiModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[CopilotTurn] = Field(default_factory=list, max_length=20)
    thinking: Literal["low", "medium", "high"] = Field(
        default="medium", description="Denkstufe: Gründlichkeit und Länge der Antwort."
    )
    lang: Literal["de", "en", "es"] = Field(
        default="de", description="Antwortsprache für den Compliance Copilot (de | en | es)."
    )
    progress_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{6,64}$",
        description="Vom Client vergebene Kennung für die Live-Arbeitsschritte (GET /api/v1/copilot/progress/{id}).",
    )


class CopilotResponse(ApiModel):
    answer: str
    model: str
    provider: str
    duration_ms: int
    reference: bool = Field(
        default=False, description="True bei hinterlegter Musterantwort (Musterdaten, ohne Sprachmodell)."
    )
    heuristic: bool = Field(
        default=False, description="True, wenn alle KI-Stufen ausfielen und das Regelwerk geantwortet hat."
    )
    failover: list[dict[str, str]] | None = Field(default=None, description="Stufenwechsel während der Antwort.")
    notice: str | None = Field(default=None, description="Ruhiger Hinweis für die Oberfläche.")


class JobSubmitRequest(ApiModel):
    """Batch-Prüfung: mehrere Belege auf einmal in die Warteschlange."""

    document_ids: list[Annotated[str, Field(min_length=8, max_length=64)]] = Field(min_length=1, max_length=100)


class TextSpan(ApiModel):
    """Markierte PII-Fundstelle in der Textansicht."""

    start: int
    end: int
    category: str
    label: str
    masked: bool
    source: str


class TextView(ApiModel):
    level: str
    text: str
    spans: list[TextSpan]
    truncated: bool = False


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
    suggested_model: str | None = Field(
        default=None,
        description="Installiertes Ersatzmodell aus der Vorrangliste, falls das eingestellte fehlt (nur Vorschlag).",
    )


class HealthResponse(ApiModel):
    """Antwort von GET /health."""

    status: str = Field(description="'ok', wenn alle Komponenten erreichbar sind, sonst 'degraded'.")
    version: str
    environment: str
    auth_enabled: bool
    timestamp: datetime
    database: DatabaseHealth
    ollama: OllamaHealth
    inference: dict[str, Any] | None = Field(
        default=None, description="Aktiver Inferenz-Modus, Modell und Privacy-Gateway-Status."
    )


class ErrorDetail(ApiModel):
    """Maschinenlesbare Fehlerbeschreibung."""

    code: str = Field(description="Stabiler Fehlercode, z. B. 'document_not_found'.")
    message: str = Field(description="Menschenlesbare Fehlermeldung auf Deutsch.")
    hint: str | None = Field(default=None, description="Konkreter Lösungsvorschlag.")


class ErrorResponse(ApiModel):
    """Einheitliches Fehlerformat aller Endpunkte."""

    error: ErrorDetail


class RedactRequest(ApiModel):
    """Text für das DLP-Gateway (``POST /api/v1/redact``)."""

    text: str = Field(min_length=1, max_length=200_000, description="Zu schwärzender Text (wird nicht gespeichert).")
    extra_terms: list[Annotated[str, Field(min_length=2, max_length=100)]] = Field(
        default_factory=list, max_length=50, description="Zusätzliche Sperrbegriffe nur für diese Anfrage."
    )
    redact_pii: bool = Field(default=True, description="Personenbezogene Daten schwärzen (ohne Beträge).")
    redact_amounts: bool = Field(default=False, description="Auch Geldbeträge schwärzen.")


class RedactResponse(ApiModel):
    """Geschwärzter Text und Treffer je Kategorie - nie die gefundenen Werte."""

    redacted_text: str
    counts: dict[str, int]
    total: int
    ruleset_version: str


class ReleaseApplyRequest(ApiModel):
    """Bestätigung eines Release-Wechsels durch die Administration."""

    tag: str = Field(pattern=r"^v\d+\.\d+\.\d+$", description="Release-Tag, z. B. 'v2.6.0'.")
    commit: str = Field(pattern=r"^[0-9a-f]{40}$", description="Bestätigter Commit-Hash des Tags (40 Zeichen).")
    admin_name: str = Field(default="System", min_length=2, max_length=120, description="Wer das Update auslöst.")
