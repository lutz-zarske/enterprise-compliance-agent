"""Tests des Ollama-Clients gegen einen auf HTTP-Ebene gemockten Dienst."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.llm import (
    DEFAULT_SEED,
    LLMResponseError,
    OllamaClient,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
    extract_json_object,
)
from app.schemas import AIActRiskLevel, DocType
from tests.conftest import DEFAULT_EXTRACTION, FakeOllama


def test_json_wird_auch_aus_verunreinigten_antworten_gelesen() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Gerne! Hier das Ergebnis:\n{"a": 1}\nViel Erfolg.') == {"a": 1}

    with pytest.raises(LLMResponseError):
        extract_json_object("voellig ohne JSON")
    with pytest.raises(LLMResponseError):
        extract_json_object("")
    with pytest.raises(LLMResponseError):
        extract_json_object("[1, 2, 3]")  # Array statt Objekt


async def test_extraktion_ruft_ollama_mit_den_geforderten_optionen(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    extraction, duration_ms = await ollama_client.extract_document("Beispieltext")

    assert duration_ms >= 0
    assert extraction.doc_type is DocType.INVOICE
    assert extraction.document_date == date(2024, 3, 15)
    assert extraction.total_amount == Decimal("32725.00")
    assert extraction.currency == "EUR"
    assert extraction.iban_valid is True

    payload = fake_ollama.calls[-1]
    assert payload["model"] == "qwen2.5:14b-instruct"
    assert payload["format"] == "json"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.0, "num_ctx": 16384, "seed": DEFAULT_SEED}
    assert payload["messages"][0]["role"] == "system"
    assert "Beispieltext" in payload["messages"][1]["content"]


async def test_compliance_audit_wird_schemakonform_validiert(
    ollama_client: OllamaClient,
) -> None:
    audit, _ = await ollama_client.audit_document("Beispieltext")

    assert audit.ai_act.describes_ai_system is True
    assert audit.ai_act.systems[0].name == "TalentMatch Screening Suite"
    assert audit.ai_act.systems[0].risk_level is AIActRiskLevel.HIGH
    assert audit.gdpr.contains_special_categories is True


async def test_kaputte_antwort_wird_in_einer_reparaturrunde_korrigiert(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    """Erster Versuch liefert Muell, der zweite das korrekte JSON."""
    fake_ollama.pending_raw = ["Ich bin ein Sprachmodell und kein JSON."]

    extraction, _ = await ollama_client.extract_document("Beispieltext")

    assert extraction.document_number == "RE-2024-0815"
    assert len(fake_ollama.calls) == 2

    repair_messages = fake_ollama.calls[1]["messages"]
    assert repair_messages[-1]["role"] == "user"
    assert "nicht dem geforderten Schema" in repair_messages[-1]["content"]


async def test_dauerhaft_unbrauchbare_antwort_wird_zum_fehler(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    fake_ollama.pending_raw = ["kein json", "immer noch kein json"]

    with pytest.raises(LLMResponseError) as exc_info:
        await ollama_client.extract_document("Beispieltext")

    assert exc_info.value.code == "llm_invalid_response"
    assert len(fake_ollama.calls) == 2


async def test_fehlendes_modell_liefert_eigene_ausnahme(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    fake_ollama.chat_status = 404

    with pytest.raises(OllamaModelNotFoundError) as exc_info:
        await ollama_client.extract_document("Beispieltext")

    assert "ollama pull" in (exc_info.value.hint or "")


async def test_nicht_erreichbarer_dienst_liefert_eigene_ausnahme(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    fake_ollama.offline = True

    with pytest.raises(OllamaUnavailableError):
        await ollama_client.list_models()
    with pytest.raises(OllamaUnavailableError):
        await ollama_client.extract_document("Beispieltext")


async def test_modellverfuegbarkeit_beruecksichtigt_latest_tag(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    assert await ollama_client.is_model_available() is True

    fake_ollama.models = ["qwen2.5:14b-instruct:latest"]
    assert await ollama_client.is_model_available() is True

    fake_ollama.models = ["llama3:8b"]
    assert await ollama_client.is_model_available() is False


async def test_zusatzfelder_des_modells_brechen_die_validierung_nicht(
    ollama_client: OllamaClient, fake_ollama: FakeOllama
) -> None:
    fake_ollama.extraction_response = json.dumps(
        {**DEFAULT_EXTRACTION, "confidence_score": 0.87, "internal_notes": "..."},
        ensure_ascii=False,
    )

    extraction, _ = await ollama_client.extract_document("Beispieltext")
    assert extraction.sender == "TalentMatch GmbH"
