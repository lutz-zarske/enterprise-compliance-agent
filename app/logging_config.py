"""Strukturiertes JSON-Logging mit Request-Tracing und PII-Filter.

* Jede Logzeile ist genau ein JSON-Objekt (``timestamp``, ``level``,
  ``logger``, ``message``, ``request_id`` und optionale Zusatzfelder).  Damit
  laesst sich der Logstream ohne Parsing-Regeln in Loki, Elastic, Splunk oder
  Azure Monitor einspielen.
* Die ``request_id`` stammt aus einer ``ContextVar``: Die Middleware setzt sie
  einmal pro Anfrage, und jede Logzeile innerhalb dieser Anfrage - auch aus
  tieferen Schichten wie ``services`` oder ``llm`` - traegt sie automatisch.
* Der ``PIIRedactionFilter`` laeuft vor jeder Ausgabe und entfernt IBANs,
  E-Mail-Adressen, Telefonnummern und lange Ziffernfolgen aus Nachricht und
  Argumenten.  Er ist ein Sicherheitsnetz, kein Freibrief: Der Code loggt
  grundsaetzlich keine Dokumentinhalte, sondern nur IDs, Zaehler und Dauern.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Request-ID der aktuell bearbeiteten Anfrage ("-" ausserhalb einer Anfrage).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

#: Erlaubtes Format fuer extern gelieferte Request-IDs (Schutz vor Log-Injection).
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

#: Standardattribute eines LogRecord - alles andere gilt als Zusatzfeld.
_RESERVED = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    | {"message", "asctime", "request_id"}
)

#: Schluessel, deren Werte grundsaetzlich nie im Log erscheinen.
_SENSITIVE_KEYS = frozenset(
    {"raw_text", "text", "content", "api_key", "authorization", "password", "secret"}
)

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){2,8}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_PHONE = re.compile(r"(?:\+49|0049|\(0\)|\b0)[\s/.-]?\d{2,5}[\s/.-]?\d{3,}\b")
_LONG_DIGITS = re.compile(r"\b\d{9,}\b")
_API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,})\b")


def normalize_request_id(candidate: str | None) -> str | None:
    """Uebernimmt eine Client-Request-ID nur, wenn sie harmlos ist."""
    if candidate and _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return None


def scrub(value: str) -> str:
    """Entfernt offensichtliche Identifikatoren und Schluessel aus einem String."""
    value = _API_KEY.sub("[SECRET]", value)
    value = _IBAN.sub("[IBAN]", value)
    value = _EMAIL.sub("[EMAIL]", value)
    value = _PHONE.sub("[TEL]", value)
    return _LONG_DIGITS.sub("[NUM]", value)


def _scrub_any(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if str(key).casefold() in _SENSITIVE_KEYS else _scrub_any(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_any(item) for item in value]
    return value


class PIIRedactionFilter(logging.Filter):
    """Schwaerzt PII in Nachricht, Argumenten und Zusatzfeldern."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - kaputte Formatierung darf nicht crashen
            message = str(record.msg)
        record.msg = scrub(message)
        record.args = None
        for key, value in list(vars(record).items()):
            if key in _RESERVED:
                continue
            if key.casefold() in _SENSITIVE_KEYS:
                setattr(record, key, "[REDACTED]")
            else:
                setattr(record, key, _scrub_any(value))
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Gibt jeden LogRecord als einzeiliges JSON-Objekt aus."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # Nur Typ und (geschwaerzte) Meldung - Tracebacks koennen Daten enthalten.
            exc_type, exc_value = record.exc_info[0], record.exc_info[1]
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": scrub(str(exc_value))[:500],
            }
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Richtet den Root-Logger einmalig ein (idempotent, auch fuer uvicorn)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        if getattr(handler, "_compliance_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler._compliance_handler = True  # type: ignore[attr-defined]  # noqa: SLF001
    handler.addFilter(PIIRedactionFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)

    # uvicorn-Accesslogs ersetzt die eigene Request-Logzeile (mit request_id).
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    # httpx loggt sonst jede URL inkl. Query-Parametern (z. B. API-Keys).
    logging.getLogger("httpx").setLevel(logging.WARNING)
