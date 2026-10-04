"""Gemeinsame Test-Fixtures.

Zwei bewusste Entscheidungen:

* **Der Ollama-Dienst wird auf HTTP-Ebene gemockt** (``httpx.MockTransport``),
  nicht durch Austausch des Clients.  Dadurch laufen ``app/llm.py`` -
  Payload-Aufbau, JSON-Extraktion, Schemavalidierung und Reparaturrunde -
  in jedem Test mit durch, statt wegabstrahiert zu werden.
* **PDF-Fixtures werden zur Laufzeit erzeugt**, ohne zusaetzliche Abhaengigkeit
  wie reportlab.  ``build_pdf`` schreibt ein minimales, gueltiges PDF mit
  echtem Textlayer; ``build_scanned_pdf`` eines ohne.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import OllamaClient
from app.main import create_app, get_llm, get_service
from app.services import DocumentService

# ---------------------------------------------------------------------------
# PDF-Erzeugung ohne externe Abhaengigkeiten
# ---------------------------------------------------------------------------


def _escape_pdf_text(value: str) -> bytes:
    escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return escaped.encode("cp1252", errors="replace")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Baut ein minimales PDF mit echtem Textlayer.

    Args:
        pages: Je Seite eine Liste von Textzeilen. Eine leere Liste erzeugt
            eine Seite ohne Textobjekte (Simulation eines Scans).
    """
    page_count = len(pages)
    font_obj = 3 + 2 * page_count
    objects: dict[int, bytes] = {}

    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(page_count))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")

    for index, lines in enumerate(pages):
        page_obj = 3 + 2 * index
        content_obj = page_obj + 1

        if lines:
            body = b"BT\n/F1 11 Tf\n50 800 Td\n14 TL\n"
            for line in lines:
                body += b"(" + _escape_pdf_text(line) + b") Tj\nT*\n"
            body += b"ET\n"
        else:
            # Nur eine gezeichnete Linie: gueltige Seite, aber ohne Textlayer.
            body = b"q 1 w 50 50 m 300 50 l S Q\n"

        objects[page_obj] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {content_obj} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        ).encode("ascii")
        objects[content_obj] = (
            f"<< /Length {len(body)} >>\nstream\n".encode("ascii") + body + b"endstream"
        )

    objects[font_obj] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("ascii") + objects[number] + b"\nendobj\n"

    xref_offset = len(out)
    total = max(objects) + 1
    out += f"xref\n0 {total}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for number in range(1, total):
        out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
        "ascii"
    )
    return bytes(out)


#: Beispielrechnung ueber ein KI-Recruiting-System mit PII (Hochrisiko-Fall).
RECRUITING_INVOICE_LINES = [
    "TalentMatch GmbH, Innovationsweg 12, 10115 Berlin",
    "RECHNUNG Nr. RE-2024-0815",
    "Rechnungsdatum: 15.03.2024",
    "Faellig am: 14.04.2024",
    "Empfaenger: Nordwind Personalservice AG, Hamburg",
    "Position 1: Jahreslizenz TalentMatch Screening Suite -",
    "KI-gestuetzte Vorauswahl und Rangfolgebildung von Bewerbungen.",
    "Gesamtbetrag: 32.725,00 EUR",
    "Bankverbindung: DE89370400440532013000",
    "Ansprechpartnerin: Dr. Petra Simon, p.simon@talentmatch.example",
    "Hinweis: Attest der Krankenkasse liegt der Personalakte bei.",
]

SIMPLE_INVOICE_LINES = [
    "Bueromarkt Nord GmbH, Kiel",
    "RECHNUNG Nr. 2024-11",
    "Rechnungsdatum: 02.02.2024",
    "Gesamtbetrag: 119,00 EUR",
]


@pytest.fixture
def invoice_pdf() -> bytes:
    return build_pdf([RECRUITING_INVOICE_LINES])


@pytest.fixture
def simple_pdf() -> bytes:
    return build_pdf([SIMPLE_INVOICE_LINES])


@pytest.fixture
def scanned_pdf() -> bytes:
    """PDF ohne Textlayer - simuliert einen Scan."""
    return build_pdf([[]])


# ---------------------------------------------------------------------------
# Gemockter Ollama-Dienst
# ---------------------------------------------------------------------------

DEFAULT_EXTRACTION: dict[str, Any] = {
    "doc_type": "Rechnung",
    "sender": "TalentMatch GmbH",
    "recipient": "Nordwind Personalservice AG",
    "document_number": "RE-2024-0815",
    "document_date": "15.03.2024",
    "due_date": "14.04.2024",
    "total_amount": "32.725,00",
    "currency": "€",
    "iban": "DE89 3704 0044 0532 0130 00",
    "summary": "Rechnung ueber die Jahreslizenz einer KI-gestuetzten Recruiting-Software.",
    "issues": [],
}

DEFAULT_COMPLIANCE: dict[str, Any] = {
    "ai_act": {
        "describes_ai_system": True,
        # Absichtlich zu niedrig eingestuft: die Eskalationsregel muss greifen.
        "overall_risk_level": "limited",
        "systems": [
            {
                "name": "TalentMatch Screening Suite",
                "purpose": "Automatisierte Vorauswahl und Rangfolgebildung von Bewerbungen.",
                "risk_level": "high",
                "annex_iii_categories": [
                    "employment_and_worker_management",
                    "erfundene_kategorie",  # muss stillschweigend verworfen werden
                ],
                "evidence": "KI-gestuetzte Vorauswahl von Bewerbungen.",
                "confidence": 0.9,
            }
        ],
        "reasoning": "Das Dokument beschafft ein KI-System fuer das Bewerbermanagement.",
        "obligations": ["Risikomanagementsystem nach Art. 9 einrichten."],
    },
    "gdpr": {
        "contains_personal_data": True,
        "findings": [
            {
                "category": "health_data",
                "masked_value": "Attest der Krankenkasse",
                "context": "Attest der Krankenkasse liegt der Personalakte bei.",
                "confidence": 0.8,
            },
            {
                # Klartext-IBAN: die Maskierung muss serverseitig erzwungen werden.
                "category": "bank_account",
                "masked_value": "DE89370400440532013000",
                "context": "Bankverbindung: DE89370400440532013000",
                "confidence": 0.9,
            },
        ],
        "risk_level": "low",
        "reasoning": "Es liegen Kontaktdaten und ein Gesundheitsbezug vor.",
        "recommendations": ["Zugriff auf die Personalakte beschraenken."],
    },
}


class FakeOllama:
    """Stellt die Ollama-REST-API im Test nach.

    Alle Attribute sind zur Laufzeit veraenderbar, sodass ein Test gezielt
    Fehlerfaelle erzwingen kann (fehlendes Modell, Dienst offline, kaputtes
    JSON, Schemaverletzung mit anschliessender Reparatur).
    """

    def __init__(self) -> None:
        self.models: list[str] = ["qwen2.5:14b-instruct", "nomic-embed-text:latest"]
        self.extraction_response: Any = DEFAULT_EXTRACTION
        self.compliance_response: Any = DEFAULT_COMPLIANCE
        self.offline = False
        self.chat_status = 200
        self.calls: list[dict[str, Any]] = []
        #: Antworten, die vor der regulaeren Antwort ausgeliefert werden.
        self.pending_raw: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("Verbindung abgelehnt", request=request)

        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": name} for name in self.models]}
            )

        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            self.calls.append(payload)
            if self.chat_status != 200:
                return httpx.Response(self.chat_status, text="Fehler vom Modellserver")

            if self.pending_raw:
                return httpx.Response(
                    200, json={"message": {"content": self.pending_raw.pop(0)}}
                )

            system_prompt = payload["messages"][0]["content"]
            is_compliance = "EU AI ACT" in system_prompt.upper()
            body = self.compliance_response if is_compliance else self.extraction_response
            content = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            return httpx.Response(200, json={"message": {"content": content}})

        return httpx.Response(404, text="unbekannter Pfad")


@pytest.fixture
def fake_ollama() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolierte Konfiguration: eigene SQLite-Datei, eigenes Upload-Verzeichnis."""
    return Settings(
        app_env="test",
        api_key=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=2 * 1024 * 1024,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen2.5:14b-instruct",
        max_prompt_chars=8000,
        mask_pii_in_storage=True,
        log_json=False,
    )


@pytest.fixture
def make_client(
    settings: Settings, fake_ollama: FakeOllama
) -> Iterator[Callable[..., TestClient]]:
    """Fabrik fuer Testclients - erlaubt abweichende Settings je Test."""
    opened: list[TestClient] = []
    clients: list[OllamaClient] = []

    def factory(**overrides: Any) -> TestClient:
        effective = settings.model_copy(update=overrides) if overrides else settings
        llm = OllamaClient(
            effective,
            client=httpx.AsyncClient(transport=httpx.MockTransport(fake_ollama.handler)),
        )
        clients.append(llm)

        def service_override(request: Request) -> DocumentService:
            # Das Repository entsteht erst im Lifespan, daher hier verzoegert lesen.
            return DocumentService(
                effective,
                request.app.state.repository,
                llm,
                ledger=request.app.state.ledger,
            )

        application = create_app(effective)
        application.dependency_overrides[get_llm] = lambda: llm
        application.dependency_overrides[get_service] = service_override

        test_client = TestClient(application)
        test_client.__enter__()  # startet den Lifespan (DB-Aufbau)
        opened.append(test_client)
        return test_client

    yield factory

    for test_client in opened:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture
def ollama_client(settings: Settings, fake_ollama: FakeOllama) -> Iterator[OllamaClient]:
    """Direkter LLM-Client gegen den gemockten Dienst (fuer Unit-Tests)."""
    llm = OllamaClient(
        settings,
        client=httpx.AsyncClient(transport=httpx.MockTransport(fake_ollama.handler)),
    )
    yield llm


def uploaded_document_id(client: TestClient, pdf: bytes, filename: str = "rechnung.pdf") -> str:
    """Hilfsfunktion: laedt ein PDF hoch und gibt die Dokument-ID zurueck."""
    response = client.post(
        "/documents/upload",
        files={"file": (filename, pdf, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


__all__ = ["FakeOllama", "build_pdf", "uploaded_document_id"]
