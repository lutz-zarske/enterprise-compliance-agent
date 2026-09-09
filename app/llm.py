"""Strukturierte JSON-Inferenz gegen die Ollama-REST-API.

Bewusst ohne LangChain oder CrewAI: ein transparenter HTTP-Aufruf gegen
``POST /api/chat`` mit ``format="json"``, gefolgt von strikter Validierung
gegen ein Pydantic-Modell.  Der komplette Pfad zwischen Dokument und
Datenbank ist damit lesbar, testbar und ohne Framework-Magie nachvollziehbar.

Robustheitsmassnahmen:

* ``temperature=0`` und ein fester ``seed`` - dieselbe Eingabe liefert dieselbe
  Bewertung, was fuer ein Compliance-Audit die Mindestanforderung ist.
* Ein Reparaturversuch: schlaegt die Schemavalidierung fehl, bekommt das
  Modell seine eigenen Validierungsfehler zurueck und korrigiert.
* Klar getrennte Ausnahmen fuer "Dienst nicht erreichbar", "Modell fehlt",
  "Zeitueberschreitung" und "unbrauchbare Antwort".
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.schemas import (
    AIActAssessment,
    AIActRiskLevel,
    AnnexIIICategory,
    DocType,
    ExtractionResult,
    GDPRAssessment,
    PIICategory,
    RiskLevel,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

#: Fester Seed - macht Bewertungen reproduzierbar und damit auditierbar.
DEFAULT_SEED = 42

#: Kurzes Timeout fuer Verfuegbarkeitspruefungen, damit /health schnell bleibt.
HEALTH_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Ausnahmen
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Basisklasse aller Inferenzfehler."""

    code = "llm_error"
    hint: str | None = None


class OllamaUnavailableError(LLMError):
    """Der Ollama-Dienst ist nicht erreichbar."""

    code = "ollama_unavailable"
    hint = "Laeuft 'ollama serve'? Erreichbarkeit mit scripts/smoke_test_ollama.py pruefen."


class OllamaModelNotFoundError(LLMError):
    """Das konfigurierte Modell ist auf dem Ollama-Host nicht installiert."""

    code = "model_not_found"
    hint = "Modell einmalig laden: 'ollama pull qwen2.5:14b-instruct'."


class OllamaTimeoutError(LLMError):
    """Die Inferenz hat das konfigurierte Zeitlimit ueberschritten."""

    code = "llm_timeout"
    hint = "OLLAMA_TIMEOUT_SECONDS erhoehen oder ein kleineres Modell verwenden."


class LLMResponseError(LLMError):
    """Die Antwort war kein valides, schemakonformes JSON."""

    code = "llm_invalid_response"
    hint = "Modellantwort entsprach auch nach einem Reparaturversuch nicht dem Schema."


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DOC_TYPES = ", ".join(f'"{member.value}"' for member in DocType)
_RISK_LEVELS = ", ".join(f'"{member.value}"' for member in AIActRiskLevel)
_ANNEX_III = ", ".join(f'"{member.value}"' for member in AnnexIIICategory)
_PII_CATEGORIES = ", ".join(f'"{member.value}"' for member in PIICategory)
_GDPR_RISK = ", ".join(f'"{member.value}"' for member in RiskLevel)

EXTRACTION_SYSTEM_PROMPT = f"""\
Du bist ein praeziser Extraktionsagent fuer deutschsprachige Geschaeftsdokumente
(Rechnungen, Vertraege, Angebote, Mahnungen).

Verbindliche Regeln:
1. Antworte ausschliesslich mit genau einem JSON-Objekt. Kein Fliesstext, keine
   Erklaerungen, keine Markdown-Codebloecke.
2. Extrahiere nur, was tatsaechlich im Dokument steht. Rate niemals. Fehlt eine
   Angabe, setze null (bzw. eine leere Liste).
3. Datumsangaben im Format YYYY-MM-DD.
4. Betraege als Dezimalzahl mit Punkt als Dezimaltrennzeichen, ohne
   Tausenderpunkte und ohne Waehrungssymbol (Beispiel: 1234.56).
5. "total_amount" ist der Bruttoendbetrag inklusive Umsatzsteuer.
6. "currency" als ISO-4217-Code (EUR, USD, CHF, ...).
7. "iban" ohne Leerzeichen, in Grossbuchstaben.
8. "summary" ist eine sachliche deutsche Zusammenfassung in zwei bis vier Saetzen.
9. "issues" listet konkrete Auffaelligkeiten auf Deutsch, zum Beispiel fehlende
   Pflichtangaben nach Paragraf 14 UStG (Steuernummer, Rechnungsnummer,
   Leistungsdatum), widerspruechliche Betraege oder ungewoehnliche
   Vertragsklauseln. Keine Auffaelligkeit bedeutet eine leere Liste.

Antwortschema (exakt diese Schluessel, keine zusaetzlichen):
{{
  "doc_type": einer von [{_DOC_TYPES}],
  "sender": string oder null,
  "recipient": string oder null,
  "document_number": string oder null,
  "document_date": "YYYY-MM-DD" oder null,
  "due_date": "YYYY-MM-DD" oder null,
  "total_amount": Zahl oder null,
  "currency": "EUR" oder null,
  "iban": string oder null,
  "summary": string,
  "issues": [string, ...]
}}"""

COMPLIANCE_SYSTEM_PROMPT = f"""\
Du bist ein Compliance-Pruefer fuer die KI-Verordnung der EU (VO (EU) 2024/1689,
"EU AI Act") und die Datenschutz-Grundverordnung (DSGVO).

Verbindliche Regeln:
1. Antworte ausschliesslich mit genau einem JSON-Objekt. Kein Fliesstext, keine
   Erklaerungen, keine Markdown-Codebloecke.
2. Alle Freitexte auf Deutsch.
3. Bewerte ausschliesslich das vorgelegte Dokument. Erfinde keine Sachverhalte.

TEIL A - EU AI ACT
Pruefe, ob im Dokument ein Softwaresystem beschaffen, entwickelt, lizenziert oder
beschrieben wird, das ein KI-System im Sinne von Artikel 3 Nr. 1 ist (Systeme mit
maschinellem Lernen, Scoring, automatisierter Entscheidungsfindung, Ranking oder
Vorhersage).
- Eine gewoehnliche Rechnung ueber Bueromaterial, Miete oder Beratung beschreibt
  KEIN KI-System: dann "describes_ai_system": false und
  "overall_risk_level": "not_applicable".
- Beschreibt das Dokument ein KI-System, ordne es einer Risikostufe zu:
  * "unacceptable": verbotene Praktik nach Artikel 5 (z. B. Social Scoring,
    Emotionserkennung am Arbeitsplatz, biometrische Echtzeit-Fernidentifizierung).
  * "high": Anwendungsfall faellt unter Anhang III. Besonders relevant:
    - "employment_and_worker_management": Bewerberauswahl, CV-Screening,
      Recruiting, Leistungsbewertung, Befoerderung, Kuendigung.
    - "critical_infrastructure": Steuerung von Strom-, Wasser-, Gas-, Waerme-,
      Verkehrs- oder Digitalinfrastruktur.
    - "essential_services_and_creditworthiness": Bonitaets- und
      Kreditwuerdigkeitspruefung, Scoring, Versicherungs-Risikobewertung,
      Zugang zu Sozialleistungen.
  * "limited": nur Transparenzpflichten nach Artikel 50 (Chatbots, Deepfakes).
  * "minimal": alle uebrigen KI-Systeme (Spamfilter, Empfehlungen).
- "annex_iii_categories" enthaelt ausschliesslich Werte aus dieser Liste:
  [{_ANNEX_III}]. Trifft keine zu, gib eine leere Liste zurueck.
- "obligations" nennt die konkreten Folgepflichten (z. B. Risikomanagementsystem
  nach Art. 9, Daten-Governance nach Art. 10, technische Dokumentation nach
  Art. 11, menschliche Aufsicht nach Art. 14, Konformitaetsbewertung nach Art. 43).

TEIL B - DSGVO
Erkenne personenbezogene Daten und insbesondere besondere Kategorien nach
Artikel 9 (Gesundheitsdaten, Religions- und Weltanschauungszugehoerigkeit,
ethnische Herkunft, politische Meinung, Gewerkschaftszugehoerigkeit, Biometrie,
Genetik, Sexualleben) sowie strafrechtliche Daten nach Artikel 10.
- Ausweis-, Pass-, Sozialversicherungs- und Steueridentifikationsnummern sind
  ebenfalls zu melden.
- "masked_value" enthaelt NIEMALS den vollstaendigen Wert. Maskiere die Mitte,
  Beispiel: "DE89****3000", "M***@example.com", "geb. **.**.1985".
- "context" ist ein kurzer, ebenfalls entschaerfter Umgebungstext.
- Risikostufe: "high" bei besonderen Kategorien nach Art. 9/10, "medium" bei
  Ausweis-, Konto- oder Sozialdaten, "low" bei blossen Kontaktdaten von
  Ansprechpartnern, "none" wenn ausschliesslich Firmendaten vorliegen.

Antwortschema (exakt diese Schluessel, keine zusaetzlichen):
{{
  "ai_act": {{
    "describes_ai_system": true oder false,
    "overall_risk_level": einer von [{_RISK_LEVELS}],
    "systems": [
      {{
        "name": string,
        "purpose": string,
        "risk_level": einer von [{_RISK_LEVELS}],
        "annex_iii_categories": [ausschliesslich Werte aus der Anhang-III-Liste],
        "evidence": string,
        "confidence": Zahl zwischen 0.0 und 1.0
      }}
    ],
    "reasoning": string,
    "obligations": [string, ...]
  }},
  "gdpr": {{
    "contains_personal_data": true oder false,
    "findings": [
      {{
        "category": einer von [{_PII_CATEGORIES}],
        "masked_value": string (maskiert!),
        "context": string,
        "confidence": Zahl zwischen 0.0 und 1.0
      }}
    ],
    "risk_level": einer von [{_GDPR_RISK}],
    "reasoning": string,
    "recommendations": [string, ...]
  }}
}}"""


class ComplianceAuditPayload(BaseModel):
    """Wrapper fuer die kombinierte Compliance-Antwort des Modells."""

    model_config = ConfigDict(extra="ignore")

    ai_act: AIActAssessment = Field(default_factory=AIActAssessment)
    gdpr: GDPRAssessment = Field(default_factory=GDPRAssessment)


def build_extraction_prompt(text: str) -> str:
    return (
        "Extrahiere die strukturierten Daten aus dem folgenden Dokument.\n\n"
        "=== DOKUMENTBEGINN ===\n"
        f"{text}\n"
        "=== DOKUMENTENDE ===\n\n"
        "Antworte ausschliesslich mit dem JSON-Objekt gemaess Schema."
    )


def build_compliance_prompt(text: str) -> str:
    return (
        "Pruefe das folgende Dokument auf EU-AI-Act-Relevanz und auf "
        "personenbezogene Daten nach DSGVO.\n\n"
        "=== DOKUMENTBEGINN ===\n"
        f"{text}\n"
        "=== DOKUMENTENDE ===\n\n"
        "Antworte ausschliesslich mit dem JSON-Objekt gemaess Schema."
    )


# ---------------------------------------------------------------------------
# Antwort-Parsing
# ---------------------------------------------------------------------------

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json_object(content: str) -> dict[str, Any]:
    """Holt das JSON-Objekt aus der Modellantwort.

    ``format="json"`` liefert im Regelfall bereits reines JSON; die Fallbacks
    fangen Modelle ab, die trotzdem einen Codeblock oder einleitenden Text
    voranstellen.
    """
    content = content.strip()
    if not content:
        raise LLMResponseError("Das Modell hat eine leere Antwort geliefert.")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        fenced = _JSON_FENCE.search(content)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1))
            except json.JSONDecodeError:
                parsed = None

    if parsed is None:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMResponseError(
                    f"Antwort des Modells ist kein gueltiges JSON: {exc}"
                ) from exc

    if not isinstance(parsed, dict):
        raise LLMResponseError("Das Modell hat kein JSON-Objekt auf oberster Ebene geliefert.")
    return parsed


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OllamaClient:
    """Schmaler, vollstaendig asynchroner Client fuer die Ollama-REST-API."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=settings.ollama_timeout_seconds,
                write=30.0,
                pool=5.0,
            )
        )

    @property
    def model(self) -> str:
        return self._settings.ollama_model

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- Verfuegbarkeit ----------------------------------------------------
    async def list_models(self) -> list[str]:
        """Namen aller auf dem Ollama-Host installierten Modelle."""
        try:
            response = await self._client.get(
                self._settings.ollama_tags_url, timeout=HEALTH_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(
                f"Zeitueberschreitung bei {self._settings.ollama_tags_url}."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(
                f"Ollama unter {self._settings.ollama_base_url} nicht erreichbar: {exc}"
            ) from exc

        payload = response.json()
        return [entry.get("name", "") for entry in payload.get("models", []) if entry.get("name")]

    async def is_model_available(self, models: list[str] | None = None) -> bool:
        """Prueft das konfigurierte Modell inklusive impliziter ``:latest``-Tags."""
        names = models if models is not None else await self.list_models()
        wanted = self.model
        candidates = {wanted, f"{wanted}:latest", wanted.removesuffix(":latest")}
        return any(name in candidates for name in names)

    # --- Inferenz ----------------------------------------------------------
    async def _post_chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._settings.ollama_temperature,
                "num_ctx": self._settings.ollama_num_ctx,
                "seed": DEFAULT_SEED,
            },
        }

        try:
            response = await self._client.post(self._settings.ollama_chat_url, json=payload)
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Die Inferenz hat {self._settings.ollama_timeout_seconds:.0f}s ueberschritten."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(
                f"Ollama unter {self._settings.ollama_base_url} nicht erreichbar: {exc}"
            ) from exc

        if response.status_code == 404:
            raise OllamaModelNotFoundError(
                f"Das Modell '{self.model}' ist auf dem Ollama-Host nicht installiert."
            )
        if response.status_code >= 400:
            raise LLMResponseError(
                f"Ollama antwortete mit HTTP {response.status_code}: {response.text[:500]}"
            )

        body = response.json()
        content = (body.get("message") or {}).get("content", "")
        if not isinstance(content, str):
            raise LLMResponseError("Die Antwort von Ollama enthielt keinen Textinhalt.")
        return content

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        max_attempts: int = 2,
    ) -> tuple[T, int]:
        """Fuehrt eine JSON-Inferenz aus und validiert sie gegen ``schema``.

        Returns:
            Tupel aus validiertem Modell und Dauer in Millisekunden.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        started = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            content = await self._post_chat(messages)
            try:
                data = extract_json_object(content)
                validated = schema.model_validate(data)
            except (LLMResponseError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "Schemavalidierung fehlgeschlagen (Versuch %s/%s): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt == max_attempts:
                    break
                # Reparaturrunde: das Modell bekommt seine eigenen Fehler zurueck.
                messages = [
                    *messages,
                    {"role": "assistant", "content": content[:4000]},
                    {
                        "role": "user",
                        "content": (
                            "Deine Antwort entsprach nicht dem geforderten Schema. "
                            f"Fehler:\n{exc}\n\n"
                            "Antworte erneut - ausschliesslich mit einem einzigen, "
                            "gueltigen JSON-Objekt gemaess Schema."
                        ),
                    },
                ]
                continue

            duration_ms = int((time.perf_counter() - started) * 1000)
            return validated, duration_ms

        raise LLMResponseError(
            f"Das Modell lieferte auch nach {max_attempts} Versuchen keine "
            f"schemakonforme Antwort. Letzter Fehler: {last_error}"
        )

    # --- Fachliche Aufrufe -------------------------------------------------
    async def extract_document(self, text: str) -> tuple[ExtractionResult, int]:
        """Extrahiert Rechnungs- bzw. Vertragsdaten."""
        return await self.chat_structured(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_prompt=build_extraction_prompt(text),
            schema=ExtractionResult,
        )

    async def audit_document(self, text: str) -> tuple[ComplianceAuditPayload, int]:
        """Fuehrt die EU-AI-Act- und DSGVO-Pruefung durch."""
        return await self.chat_structured(
            system_prompt=COMPLIANCE_SYSTEM_PROMPT,
            user_prompt=build_compliance_prompt(text),
            schema=ComplianceAuditPayload,
        )
