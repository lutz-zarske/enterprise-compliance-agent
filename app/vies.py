"""Live-Pruefung von USt-IdNr. ueber VIES (Europaeische Kommission).

Die Kommission stellt die REST-Schnittstelle kostenlos und ohne API-Key bereit.
Bewusste Grenzen:

* Uebertragen werden ausschliesslich Laendercode und Nummer - kein
  Dokumentinhalt.  Die Abfrage loest die Pruefperson aus, nie ein Automatismus.
* Das Ergebnis ist eine Momentaufnahme: Es wird nicht gespeichert und fliesst
  nicht in den deterministischen Compliance-Score ein.
* Deutschland uebermittelt ueber VIES weder Namen noch Anschrift ("---").  Eine
  qualifizierte Bestaetigung nach § 18e UStG erteilt allein das BZSt.
* Kurzes Timeout (Standard 3 s): VIES verbindet die nationalen Datenbanken,
  die einzeln ausfallen koennen (``MS_UNAVAILABLE``).
* Die Nummer selbst wird nicht geloggt - bei Einzelunternehmern ist sie ein
  personenbezogenes Datum.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.schemas import VatVerification
from app.services import ServiceError

logger = logging.getLogger(__name__)

#: Teilnehmer an VIES (Griechenland als "EL", Nordirland als "XI").
VIES_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU",
        "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
    }
)
_ISO_TO_VIES = {"GR": "EL"}

_NUMBER = re.compile(r"^[0-9A-Z+*]{2,12}$")
_DE_NUMBER = re.compile(r"^\d{9}$")
_SEPARATORS = re.compile(r"[\s.\-/]")

#: VIES-Fehlercodes, die auf eine fehlerhafte Eingabe zurueckgehen.
_INPUT_ERRORS = {"INVALID_INPUT", "INVALID_REQUESTER_INFO"}
#: Voruebergehende Stoerungen - spaeter erneut versuchen.
_BUSY_ERRORS = {
    "MS_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ", "GLOBAL_MAX_CONCURRENT_REQ",
    "SERVICE_UNAVAILABLE", "TIMEOUT", "SERVER_BUSY",
}
_NOT_PROVIDED = {"", "---"}


class ViesInputError(ServiceError):
    """Laendercode oder Nummer sind fuer VIES nicht abfragbar."""

    code = "vies_invalid_input"
    status_code = 422
    hint = "Laendercode (z. B. 'DE') und Nummer ohne Praefix angeben, z. B. '312345678'."


class ViesUnavailableError(ServiceError):
    """VIES oder die Datenbank des Mitgliedstaats antwortet nicht."""

    code = "vies_unavailable"
    status_code = 503
    hint = "VIES ist ein Verbund nationaler Datenbanken; in einigen Minuten erneut pruefen."


def normalize_vat(country_code: str, vat_number: str) -> tuple[str, str]:
    """Bringt Laendercode und Nummer in die von VIES erwartete Form.

    Akzeptiert Leerzeichen, Punkte und Bindestriche sowie ein vorangestelltes
    Laenderpraefix (``DE 312 345 678``).  Griechenland wird als ``EL`` gefuehrt.
    """
    country = country_code.strip().upper()
    country = _ISO_TO_VIES.get(country, country)
    if country not in VIES_COUNTRIES:
        raise ViesInputError(f"Laendercode '{country}' nimmt nicht an VIES teil.")
    number = _SEPARATORS.sub("", vat_number).upper()
    if number.startswith(country) or (country == "EL" and number.startswith("GR")):
        number = number[2:]
    if not _NUMBER.fullmatch(number):
        raise ViesInputError("Die USt-IdNr. enthaelt unzulaessige Zeichen oder hat eine falsche Laenge.")
    if country == "DE" and not _DE_NUMBER.fullmatch(number):
        raise ViesInputError("Eine deutsche USt-IdNr. besteht aus 'DE' und genau neun Ziffern.")
    return country, number


def _error_codes(payload: dict[str, Any]) -> list[str]:
    codes = [
        str(wrapper.get("error", "")).strip()
        for wrapper in payload.get("errorWrappers") or []
        if isinstance(wrapper, dict)
    ]
    user_error = str(payload.get("userError") or "").strip()
    if user_error and user_error not in {"VALID", "INVALID"}:
        codes.append(user_error)
    return [code for code in codes if code]


def _provided(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return None if text in _NOT_PROVIDED else text


class ViesClient:
    """Asynchroner Client fuer ``check-vat-number`` (Transport in Tests gemockt)."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = settings.vies_url
        self._timeout = settings.vies_timeout_seconds
        self._client = httpx.AsyncClient(transport=transport, timeout=self._timeout)

    async def verify(self, country_code: str, vat_number: str) -> VatVerification:
        country, number = normalize_vat(country_code, vat_number)
        try:
            response = await self._client.post(self._url, json={"countryCode": country, "vatNumber": number})
        except httpx.TimeoutException as exc:
            logger.warning("VIES-Timeout (%s, %.0f s)", country, self._timeout)
            raise ViesUnavailableError(
                f"VIES hat nicht innerhalb von {self._timeout:g} s geantwortet."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("VIES nicht erreichbar (%s): %s", country, type(exc).__name__)
            raise ViesUnavailableError("VIES ist nicht erreichbar.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ViesUnavailableError(
                f"VIES lieferte keine auswertbare Antwort (HTTP {response.status_code})."
            ) from exc
        if not isinstance(payload, dict):
            raise ViesUnavailableError("VIES lieferte keine auswertbare Antwort.")

        codes = _error_codes(payload)
        if codes:
            logger.info("VIES-Fehler (%s): %s", country, ", ".join(codes))
            if any(code in _INPUT_ERRORS or code.startswith("VOW-ERR") for code in codes):
                raise ViesInputError(f"VIES lehnt die Eingabe ab ({codes[0]}).")
            if any(code in _BUSY_ERRORS for code in codes):
                raise ViesUnavailableError(
                    f"Die Datenbank des Mitgliedstaats {country} antwortet derzeit nicht ({codes[0]})."
                )
            raise ViesUnavailableError(f"VIES meldet einen Fehler ({codes[0]}).")
        if response.status_code >= 400 or not isinstance(payload.get("valid"), bool):
            raise ViesUnavailableError(f"Unerwartete Antwort von VIES (HTTP {response.status_code}).")

        logger.info("VIES-Abfrage (%s): %s", country, "gueltig" if payload["valid"] else "ungueltig")
        return VatVerification(
            country_code=country,
            vat_number=number,
            valid=payload["valid"],
            name=_provided(payload.get("name")),
            address=_provided(payload.get("address")),
            request_date=payload.get("requestDate") or None,
            request_identifier=_provided(payload.get("requestIdentifier")),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
