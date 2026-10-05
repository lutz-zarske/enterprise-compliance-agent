"""Aufbewahrungsfristen nach AO, UStG und HGB (Stand nach BEG IV, 2026).

* Buchungsbelege und Rechnungen: **8 Jahre** (§ 147 Abs. 1 Nr. 4, Abs. 3 AO,
  § 14b Abs. 1 UStG, § 257 Abs. 4 HGB i. d. F. des BEG IV, ab 01.01.2025; gilt
  auch fuer Belege, deren Frist am 31.12.2024 noch nicht abgelaufen war).
* Ausnahme Finanzsektor: Kreditinstitute, Versicherungsunternehmen und
  Wertpapierinstitute bewahren Buchungsbelege wieder **10 Jahre** auf (Gesetz zur
  Modernisierung und Digitalisierung der Schwarzarbeitsbekaempfung, Bundesrat
  19.12.2025).
* Buecher, Jahresabschluesse, Inventare, Arbeitsanweisungen und sonstige
  Organisationsunterlagen - also auch die **Verfahrensdokumentation** - bleiben
  bei **10 Jahren** (§ 147 Abs. 1 Nr. 1, Abs. 3 AO).
* Empfangene Handels- und Geschaeftsbriefe: 6 Jahre (§ 147 Abs. 1 Nr. 2, Abs. 3 AO).

Die Frist beginnt mit dem Schluss des Kalenderjahres, in dem der Beleg
entstanden ist (§ 147 Abs. 4 AO), und endet nicht, solange die Festsetzungsfrist
fuer die betroffenen Steuern laeuft (§ 147 Abs. 3 Satz 5 AO).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

INVOICE_YEARS = 8
FINANCIAL_SECTOR_YEARS = 10
PROCEDURAL_DOC_YEARS = 10
BUSINESS_LETTER_YEARS = 6


@dataclass(frozen=True, slots=True)
class RetentionRule:
    """Eine Zeile der Fristentabelle (Verfahrensdokumentation, Zertifikat, Tooltip)."""

    subject: str
    years: int
    basis: str


RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule(
        "Buchungsbelege und Rechnungen (auch E-Rechnungen samt XML-Datensatz)",
        INVOICE_YEARS,
        "§ 147 Abs. 1 Nr. 4, Abs. 3 AO; § 14b Abs. 1 UStG; § 257 Abs. 4 HGB (BEG IV)",
    ),
    RetentionRule(
        "Buchungsbelege bei Kreditinstituten, Versicherungsunternehmen und Wertpapierinstituten",
        FINANCIAL_SECTOR_YEARS,
        "§ 147 Abs. 3 AO, § 257 Abs. 4 HGB i. d. F. des Gesetzes zur Modernisierung der Schwarzarbeitsbekämpfung",
    ),
    RetentionRule(
        "Bücher, Jahresabschlüsse, Inventare, Arbeitsanweisungen und Organisationsunterlagen "
        "– einschließlich dieser Verfahrensdokumentation",
        PROCEDURAL_DOC_YEARS,
        "§ 147 Abs. 1 Nr. 1, Abs. 3 AO",
    ),
    RetentionRule(
        "Empfangene Handels- und Geschäftsbriefe",
        BUSINESS_LETTER_YEARS,
        "§ 147 Abs. 1 Nr. 2, Abs. 3 AO",
    ),
)

RETENTION_NOTE = (
    "Die Frist beginnt mit dem Schluss des Kalenderjahres, in dem der Beleg entstanden ist (§ 147 Abs. 4 AO), "
    "und läuft nicht ab, solange die Festsetzungsfrist für die betroffenen Steuern noch läuft "
    "(§ 147 Abs. 3 Satz 5 AO)."
)


def retention_end(document_date: date, years: int) -> date:
    """Letzter Tag der Aufbewahrungsfrist: 31.12. des Jahres (Belegjahr + Jahre)."""
    return date(document_date.year + years, 12, 31)


@dataclass(frozen=True, slots=True)
class DocumentRetention:
    """Fristen fuer einen konkreten Beleg."""

    years: int
    until: date
    financial_sector_until: date
    basis: str


def invoice_retention(document_date: date | None) -> DocumentRetention | None:
    """Fristende fuer eine Rechnung; ``None`` ohne Belegdatum."""
    if document_date is None:
        return None
    return DocumentRetention(
        years=INVOICE_YEARS,
        until=retention_end(document_date, INVOICE_YEARS),
        financial_sector_until=retention_end(document_date, FINANCIAL_SECTOR_YEARS),
        basis=RETENTION_RULES[0].basis,
    )
