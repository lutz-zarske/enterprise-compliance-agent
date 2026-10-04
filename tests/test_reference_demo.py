"""Musterdaten mit Referenz-Audits: Sofort-Funktion ohne Sprachmodell."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.demo import DEMO_AUDITOR, REFERENCE_MODEL, STANDARD_QUESTIONS, normalize_question, reference_answer
from tests.conftest import FakeOllama


def _seed(client: TestClient) -> dict[str, dict]:
    response = client.post("/api/demo/seed")
    assert response.status_code == 200, response.text
    return {item["filename"]: item for item in response.json()["items"]}


def test_seed_funktioniert_ohne_modell(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True  # kein Ollama, kein Cloud-Key
    seeded = _seed(full_client)

    expected = {
        "Rechnung_Gueltig_14UStG.pdf": (100, "green"),
        "Rechnung_Fehlerhaft_Steuerfalle.pdf": (45, "red"),
        "KI_Recruiting_Dienstleistervertrag.pdf": (59, "red"),
    }
    for filename, (score, band) in expected.items():
        item = seeded[filename]
        assert item["status"] == "extracted" and item["reference_audit"] is True
        detail = full_client.get(f"/documents/{item['id']}").json()
        assert detail["scorecard"]["score"] == score
        assert detail["scorecard"]["band"] == band
        assert detail["model"] == REFERENCE_MODEL
        assert detail["provider"] == "reference"
        assert detail["compliance"]["provider"] == "reference"
    # Kein einziger Inferenzaufruf.
    assert fake_ollama.calls == []


def test_steuerfalle_abzuege_entsprechen_der_spezifikation(full_client: TestClient) -> None:
    seeded = _seed(full_client)
    card = full_client.get(f"/documents/{seeded['Rechnung_Fehlerhaft_Steuerfalle.pdf']['id']}").json()["scorecard"]
    deductions = {check["id"]: check["deduction"] for tile in card["tiles"] for check in tile["checks"] if check["deduction"]}
    assert deductions == {"ustg_2_tax_id": 20, "vat_rate": 10, "ustg_6_service_date": 10, "iban_mod97": 15}


def test_recruiting_vertrag_anhang_iii_nr_4(full_client: TestClient) -> None:
    seeded = _seed(full_client)
    detail = full_client.get(f"/documents/{seeded['KI_Recruiting_Dienstleistervertrag.pdf']['id']}").json()
    assert detail["compliance"]["ai_act"]["overall_risk_level"] == "high"
    labels = detail["compliance"]["ai_act"]["systems"][0]["annex_iii_labels"]
    assert any("Anhang III Nr. 4" in label for label in labels)
    assert "Gedeckelt auf 59" in detail["scorecard"]["cap_applied"]


def test_gueltige_rechnung_traegt_gekennzeichnetes_demo_siegel(full_client: TestClient) -> None:
    seeded = _seed(full_client)
    detail = full_client.get(f"/documents/{seeded['Rechnung_Gueltig_14UStG.pdf']['id']}").json()
    seal = detail["sign_off"]
    assert seal["status"] == "SEALED_APPROVED"
    assert seal["auditor_name"] == DEMO_AUDITOR
    assert "nicht die Prüfung durch eine reale Person" in seal["note"]
    # Nur die gueltige Rechnung ist versiegelt.
    others = [item for name, item in seeded.items() if name != "Rechnung_Gueltig_14UStG.pdf"]
    assert all(full_client.get(f"/documents/{item['id']}").json()["sign_off"] is None for item in others)


def test_ledger_kennzeichnet_referenz_audits_und_bleibt_valide(full_client: TestClient) -> None:
    _seed(full_client)
    trail = full_client.get("/api/audit/trail").json()["items"]
    assert [entry["event_type"] for entry in reversed(trail)] == ["analysis", "sign_off", "analysis", "analysis"]
    analyses = [entry for entry in trail if entry["event_type"] == "analysis"]
    assert all(entry["model_name"] == REFERENCE_MODEL for entry in analyses)
    assert all(entry["details"]["reference_audit"] is True for entry in analyses)
    assert full_client.get("/api/audit/verify").json()["valid"] is True


def test_erneuter_seed_ueberschreibt_kein_live_audit(full_client: TestClient) -> None:
    seeded = _seed(full_client)
    recruiting = seeded["KI_Recruiting_Dienstleistervertrag.pdf"]["id"]
    # Live-Audit mit dem (gemockten) lokalen Modell.
    assert full_client.post(f"/documents/{recruiting}/extract").status_code == 200
    entries_before = full_client.get("/api/audit/verify").json()["entries"]

    again = _seed(full_client)
    assert all(item["created"] is False and item["reference_audit"] is False for item in again.values())
    assert full_client.get(f"/documents/{recruiting}").json()["provider"] == "local"
    assert full_client.get("/api/audit/verify").json()["entries"] == entries_before


def test_kpis_sofort_befuellt(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    _seed(full_client)
    kpis = full_client.get("/api/dashboard/kpis").json()
    assert kpis["documents_analyzed"] == 3
    assert kpis["average_score"] == 68  # (100 + 45 + 59) / 3
    assert kpis["high_risk_count"] == 1
    assert kpis["sealed_count"] == 1


def test_zertifikat_kennzeichnet_referenz_audit(full_client: TestClient) -> None:
    seeded = _seed(full_client)
    document_id = seeded["Rechnung_Gueltig_14UStG.pdf"]["id"]
    html = full_client.get(f"/documents/{document_id}/report").text
    assert "Referenz-Audit der Musterdaten" in html
    assert "GEPRÜFT &amp; FREIGEGEBEN" in html
    report = full_client.get(f"/documents/{document_id}/report", params={"format": "json"}).json()
    assert report["inference"]["reference_audit"] is True


# ---------------------------------------------------------------------------
# Copilot-Musterantworten
# ---------------------------------------------------------------------------


def test_copilot_musterantwort_ohne_modell(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    seeded = _seed(full_client)
    document_id = seeded["Rechnung_Fehlerhaft_Steuerfalle.pdf"]["id"]

    response = full_client.post(
        f"/documents/{document_id}/copilot", json={"question": "welche Pflichtangaben fehlen in dieser Rechnung"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reference"] is True
    assert body["model"] == "reference-answer"
    assert "[Z. 10]" in body["answer"] and "§ 14 Abs. 4 Satz 1 Nr. 2 UStG" in body["answer"]
    assert fake_ollama.calls == []


def test_freie_frage_ohne_modell_liefert_klaren_fehler(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.offline = True
    seeded = _seed(full_client)
    document_id = seeded["Rechnung_Gueltig_14UStG.pdf"]["id"]
    response = full_client.post(f"/documents/{document_id}/copilot", json={"question": "Wer ist der Lieferant?"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ollama_unavailable"


def test_nach_live_audit_antwortet_das_modell(full_client: TestClient, fake_ollama: FakeOllama) -> None:
    seeded = _seed(full_client)
    document_id = seeded["Rechnung_Gueltig_14UStG.pdf"]["id"]
    full_client.post(f"/documents/{document_id}/extract")
    body = full_client.post(
        f"/documents/{document_id}/copilot", json={"question": STANDARD_QUESTIONS[0]}
    ).json()
    assert body["reference"] is False
    assert body["provider"] == "local"


def test_musterantworten_vollstaendig_und_zeilengenau() -> None:
    from app.demo import REFERENCE_ANSWERS, demo_documents
    from app.pdf_reader import extract_text

    texts = {name: extract_text(data).text.splitlines() for name, data in demo_documents()}
    for filename, answers in REFERENCE_ANSWERS.items():
        assert len(answers) == len(STANDARD_QUESTIONS)
        lines = texts[filename]
        for answer in answers:
            for number in re.findall(r"\[Z\. (\d+)\]", answer):
                assert 1 <= int(number) <= len(lines), (filename, number)
    # Stichprobe: Zeile 10 der Steuerfalle ist tatsaechlich die 16-%-Zeile.
    assert "16 %" in texts["Rechnung_Fehlerhaft_Steuerfalle.pdf"][9]
    assert normalize_question("  Welche Pflichtangaben fehlen in dieser Rechnung? ") == normalize_question(
        STANDARD_QUESTIONS[0]
    )
    assert reference_answer("unbekannt.pdf", STANDARD_QUESTIONS[0]) is None
