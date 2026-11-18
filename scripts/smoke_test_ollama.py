#!/usr/bin/env python
"""Smoke-Test für die Ollama-Anbindung.

Prüft in drei Stufen, ob die Inferenzstrecke einsatzbereit ist:

1. Ist der Ollama-Dienst unter ``OLLAMA_BASE_URL`` erreichbar?
2. Ist das konfigurierte Modell installiert?
3. Liefert das Modell auf einen echten deutschen Beispieltext ein
   schemakonformes JSON zurück?

Aufruf::

    python scripts/smoke_test_ollama.py            # alle drei Stufen
    python scripts/smoke_test_ollama.py --quick    # nur Stufe 1 und 2

Exitcodes: 0 = alles in Ordnung, 1 = mindestens eine Prüfung fehlgeschlagen.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Projektwurzel in den Importpfad aufnehmen, damit "app" gefunden wird.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm import LLMError, OllamaClient  # noqa: E402

BEISPIELDOKUMENT = """\
TalentMatch GmbH
Innovationsweg 12, 10115 Berlin

RECHNUNG Nr. RE-2024-0815
Rechnungsdatum: 15.03.2024
Fällig am: 14.04.2024

Empfänger: Nordwind Personalservice AG, Hafenstraße 3, 20457 Hamburg

Position 1: Jahreslizenz "TalentMatch Screening Suite" - eine KI-gestützte
Software zur automatisierten Vorauswahl und Rangfolgebildung von Bewerbungen
im Recruiting-Prozess.                                     24.000,00 EUR
Position 2: Einrichtung und Schulung                        3.500,00 EUR

Zwischensumme:                                             27.500,00 EUR
Umsatzsteuer 19 %:                                          5.225,00 EUR
Gesamtbetrag:                                              32.725,00 EUR

Bankverbindung: DE89370400440532013000
Ansprechpartner: Frau Dr. Petra Simon, p.simon@talentmatch.example
"""

OK = "[ OK ]"
FAIL = "[FEHL]"
INFO = "[INFO]"


def _line(char: str = "-") -> str:
    return char * 72


async def run(quick: bool) -> int:
    settings = get_settings()
    client = OllamaClient(settings)
    failures = 0

    print(_line("="))
    print(" Smoke-Test: Ollama-Anbindung")
    print(_line("="))
    print(f"{INFO} Basis-URL : {settings.ollama_base_url}")
    print(f"{INFO} Modell    : {settings.ollama_model}")
    print(f"{INFO} Kontext   : num_ctx={settings.ollama_num_ctx}, "
          f"temperature={settings.ollama_temperature}")
    print(_line())

    try:
        # --- Stufe 1: Erreichbarkeit --------------------------------------
        try:
            models = await client.list_models()
            print(f"{OK} Stufe 1: Ollama ist erreichbar ({len(models)} Modelle installiert).")
        except LLMError as exc:
            print(f"{FAIL} Stufe 1: {exc}")
            print(f"       Hinweis: {exc.hint}")
            return 1

        # --- Stufe 2: Modellverfügbarkeit --------------------------------
        if await client.is_model_available(models):
            print(f"{OK} Stufe 2: Modell '{settings.ollama_model}' ist installiert.")
        else:
            failures += 1
            print(f"{FAIL} Stufe 2: Modell '{settings.ollama_model}' fehlt.")
            print(f"       Verfügbar: {', '.join(sorted(models)) or '(keine)'}")
            print(f"       Abhilfe  : ollama pull {settings.ollama_model}")
            return 1

        if quick:
            print(_line())
            print(f"{INFO} --quick gesetzt: Inferenztest übersprungen.")
            return 0

        # --- Stufe 3a: Extraktion -----------------------------------------
        print(f"{INFO} Stufe 3a: Extraktion läuft (das kann bei 14B eine Weile dauern) ...")
        try:
            extraction, ms = await client.extract_document(BEISPIELDOKUMENT)
            print(f"{OK} Stufe 3a: schemakonformes JSON nach {ms} ms.")
            print(f"       Typ        : {extraction.doc_type.value}")
            print(f"       Absender   : {extraction.sender}")
            print(f"       Belegnummer: {extraction.document_number}")
            print(f"       Datum      : {extraction.document_date}")
            print(f"       Betrag     : {extraction.total_amount} {extraction.currency or ''}")
            print(f"       IBAN gültig: {extraction.iban_valid}")
        except LLMError as exc:
            failures += 1
            print(f"{FAIL} Stufe 3a: {exc}")

        # --- Stufe 3b: Compliance-Audit ------------------------------------
        print(f"{INFO} Stufe 3b: Compliance-Audit läuft ...")
        try:
            audit, ms = await client.audit_document(BEISPIELDOKUMENT)
            print(f"{OK} Stufe 3b: schemakonformes JSON nach {ms} ms.")
            print(f"       KI-System erkannt : {audit.ai_act.describes_ai_system}")
            print(f"       Risikostufe       : {audit.ai_act.overall_risk_level.value}")
            for system in audit.ai_act.systems:
                labels = ", ".join(system.annex_iii_labels) or "keine Anhang-III-Kategorie"
                print(f"         - {system.name}: {labels}")
            print(f"       DSGVO-Risiko      : {audit.gdpr.risk_level.value}")
            print(f"       PII-Treffer       : {len(audit.gdpr.findings)}")

            # Fachliche Erwartung an dieses Beispiel: HR-Recruiting = Hochrisiko.
            if audit.ai_act.is_high_risk:
                print(f"{OK} Plausibilität: Das Recruiting-Beispiel wurde als Hochrisiko erkannt.")
            else:
                print(f"{INFO} Plausibilität: Erwartet war 'high' (Anhang III Nr. 4), "
                      f"erhalten '{audit.ai_act.overall_risk_level.value}'. "
                      "Kein Fehler, aber ein Hinweis auf Prompt- oder Modellqualität.")
        except LLMError as exc:
            failures += 1
            print(f"{FAIL} Stufe 3b: {exc}")

    finally:
        await client.aclose()

    print(_line("="))
    if failures:
        print(f"{FAIL} {failures} Prüfung(en) fehlgeschlagen.")
        return 1
    print(f"{OK} Alle Prüfungen bestanden - die Inferenzstrecke ist einsatzbereit.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüft Verbindung und Modellverfügbarkeit.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Nur Erreichbarkeit und Modellverfügbarkeit prüfen, keine Inferenz.",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.quick))


if __name__ == "__main__":
    raise SystemExit(main())
