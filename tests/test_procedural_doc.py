"""GoBD-Verfahrensdokumentation und Aufbewahrungsfristen nach BEG IV."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

from fastapi.testclient import TestClient

from app.audit_ledger import ChainVerification
from app.procedural_doc import ZU_ERGAENZEN, build_procedural_doc, render_html, render_markdown
from app.retention import RETENTION_RULES, invoice_retention, retention_end
from app.signing import SystemSigner


def _seed(client: TestClient) -> dict[str, str]:
    return {item["filename"]: item["id"] for item in client.post("/api/demo/seed").json()["items"]}


def _doc(settings, tmp_path, record=None, entries=None) -> dict:
    return build_procedural_doc(
        settings=settings,
        runtime=None,
        record=record,
        entries=entries or [],
        verification=ChainVerification(True, 0, "0" * 64),
        signing_key=SystemSigner(tmp_path / ".signing.key").public_info(),
    )


# ---------------------------------------------------------------------------
# Inhalt
# ---------------------------------------------------------------------------


def test_vier_saeulen_nach_gobd_rz_153(settings, tmp_path) -> None:
    doc = _doc(settings, tmp_path)
    assert [section["title"] for section in doc["sections"]] == [
        "Allgemeine Beschreibung",
        "Anwenderdokumentation",
        "Technische Systemdokumentation",
        "Betriebsdokumentation",
    ]
    assert "Rz. 153" in doc["basis"] and "Rz. 155" in doc["basis"]
    assert doc["annex"] is None  # ohne Beleg nur der Verfahrensteil


def test_pflichtinhalte_der_anwender_und_systemdokumentation(settings, tmp_path) -> None:
    markdown = render_markdown(_doc(settings, tmp_path))
    for expected in ("Belegfluss", "Vier-Augen-Prinzip", "Rollen und Berechtigungen", "Eskalationsmatrix",
                     "SHA-256", "Ed25519", "defusedxml", "forbid_dtd=True", "Datensicherung", "WORM",
                     "Protokollierung von Systemänderungen"):
        assert expected in markdown, expected


def test_unbekannte_organisationsangaben_sind_markiert(settings, tmp_path) -> None:
    html = render_html(_doc(settings, tmp_path))
    assert html.count('class="todo"') >= 5
    assert ZU_ERGAENZEN in html
    assert "Entwurf aus dem Systemzustand" in html


def test_verfahrensdokumentation_zehn_jahre(settings, tmp_path) -> None:
    doc = _doc(settings, tmp_path)
    assert "10 Jahre" in doc["retention"] and "§ 147 Abs. 1 Nr. 1" in doc["retention"]
    table = doc["sections"][0]["blocks"][4]["table"]["rows"]
    assert ["Verfahrensdokumentation" in row[0] and row[1] == "10 Jahre" for row in table].count(True) == 1


def test_html_ist_escaped(settings, tmp_path) -> None:
    doc = _doc(settings, tmp_path)
    doc["sections"][0]["blocks"][0]["text"] = "<script>alert(1)</script>"
    html = render_html(doc)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Aufbewahrungsfristen (BEG IV)
# ---------------------------------------------------------------------------


def test_fristen_beg_iv() -> None:
    by_subject = {rule.subject: rule for rule in RETENTION_RULES}
    invoices = next(rule for subject, rule in by_subject.items() if subject.startswith("Buchungsbelege und Rechnungen"))
    banks = next(rule for subject, rule in by_subject.items() if "Kreditinstituten" in subject)
    books = next(rule for subject, rule in by_subject.items() if "Verfahrensdokumentation" in subject)
    assert (invoices.years, banks.years, books.years) == (8, 10, 10)
    assert "§ 14b Abs. 1 UStG" in invoices.basis and "§ 147 Abs. 1 Nr. 1" in books.basis


def test_fristende_ab_schluss_des_kalenderjahres() -> None:
    assert retention_end(date(2026, 9, 15), 8) == date(2034, 12, 31)
    period = invoice_retention(date(2026, 1, 2))
    assert (period.until, period.financial_sector_until) == (date(2034, 12, 31), date(2036, 12, 31))
    assert invoice_retention(None) is None


def test_scorecard_traegt_aufbewahrungsfrist(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_ZUGFeRD_Hybrid.pdf"]
    retention = full_client.get(f"/documents/{document_id}").json()["scorecard"]["retention"]
    assert (retention["years"], retention["until"], retention["financial_sector_until"]) == (8, "2034-12-31", "2036-12-31")
    assert "Verfahrensdokumentation ist 10 Jahre" in retention["note"]
    contract = _seed(full_client)["KI_Recruiting_Dienstleistervertrag.pdf"]
    assert full_client.get(f"/documents/{contract}").json()["scorecard"]["retention"] is None


def test_zertifikat_nennt_frist(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_ZUGFeRD_Hybrid.pdf"]
    html = full_client.get(f"/documents/{document_id}/report").text
    assert "bis mindestens 31.12.2034" in html and "Finanzsektor bis 31.12.2036" in html


# ---------------------------------------------------------------------------
# Endpunkt und Pruefdatenpaket
# ---------------------------------------------------------------------------


def test_endpunkt_html_mit_belegbezug(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_Gueltig_14UStG.pdf"]
    response = full_client.get(f"/api/documents/{document_id}/export/procedural-doc")
    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    html = response.text
    assert "Anhang A – Prüfpfad des Belegs" in html
    assert "Rechnung_Gueltig_14UStG.pdf" in html
    assert "Referenz-Audit der Musterdaten" in html
    assert "bis mindestens 31.12.2033" in html  # Rechnungsdatum 14.03.2025 + 8 Jahre


def test_endpunkt_markdown(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_ZUGFeRD_Hybrid.pdf"]
    response = full_client.get(
        f"/api/documents/{document_id}/export/procedural-doc", params={"format": "markdown"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Verfahrensdokumentation_Rechnung_ZUGFeRD_Hybrid.md" in response.headers["content-disposition"]
    assert "## 3. Technische Systemdokumentation" in response.text
    assert "XML-Pfad (EN 16931, deterministisch, ohne KI)" in response.text


def test_vier_augen_pruefung_im_anhang(full_client: TestClient) -> None:
    document_id = _seed(full_client)["KI_Recruiting_Dienstleistervertrag.pdf"]
    full_client.post(
        f"/api/documents/{document_id}/override",
        json={"auditor_name": "Erika Muster", "risk_level": "limited",
              "reason": "Reine Vorsortierung ohne Profiling; Entscheidung trifft der Mensch.",
              "legal_basis": "Art. 6 Abs. 3 lit. d VO (EU) 2024/1689"},
    )
    full_client.post(f"/documents/{document_id}/sign-off",
                     json={"auditor_name": "Erika Muster", "note": "", "decision": "SEALED_APPROVED"})
    markdown = full_client.get(
        f"/api/documents/{document_id}/export/procedural-doc", params={"format": "markdown"}
    ).text
    assert "Nicht gewahrt" in markdown and "Übersteuerung durch Prüfperson" in markdown

    full_client.post(f"/documents/{document_id}/sign-off",
                     json={"auditor_name": "Max Prüfer", "note": "", "decision": "SEALED_APPROVED"})
    markdown = full_client.get(
        f"/api/documents/{document_id}/export/procedural-doc", params={"format": "markdown"}
    ).text
    assert "Gewahrt: Übersteuerung und Siegel durch verschiedene Personen" in markdown


def test_unbekanntes_dokument(full_client: TestClient) -> None:
    response = full_client.get("/api/documents/gibt-es-nicht/export/procedural-doc")
    assert response.status_code == 404


def test_pruefdatenpaket_enthaelt_verfahrensdokumentation(full_client: TestClient) -> None:
    document_id = _seed(full_client)["Rechnung_ZUGFeRD_Hybrid.pdf"]
    archive = zipfile.ZipFile(io.BytesIO(full_client.get(f"/api/documents/{document_id}/export/gobd").content))
    assert "verfahrensdokumentation.html" in archive.namelist()
    manifest = json.loads(archive.read("manifest.json"))
    entry = next(item for item in manifest["files"] if item["path"] == "verfahrensdokumentation.html")
    assert "10 Jahre" in entry["description"]
    assert "Verfahrensdokumentation nach GoBD" in archive.read("verfahrensdokumentation.html").decode()
