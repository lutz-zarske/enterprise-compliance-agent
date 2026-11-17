"""v2.4: DLP-Gateway (POST /api/v1/redact) und Release-Assistent (Fast-Forward mit Sicherung)."""

from __future__ import annotations

import io
import re
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import APP_VERSION
from app.demo import (
    HYBRID_INVOICE,
    REFERENCE_ANSWERS_EN,
    REFERENCE_ANSWERS_ES,
    build_hybrid_pdf,
)
from app.gobd_export import CERTIFICATE_FILE, PROCEDURAL_DOC_FILE, verify_package
from app.heuristics import heuristic_copilot_answer
from app.redact import CONFIDENTIAL, redact

# --- DLP-Gateway ---------------------------------------------------------------

PROMPT = (
    "Bitte fasse internal_audit_memo.md und pricing_algorithm.py zusammen; README.md ist oeffentlich.\n"
    "Parameter: entry_threshold=0.73, stop_loss: 4.5%, lookback = 20, Version 3.\n"
    "Kontakt: Frau Erika Muster, erika.muster@example.com, IBAN DE89 3704 0044 0532 0130 00.\n"
    "Schluessel: sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX und password=Geheim123.\n"
    "Projekt Nordlicht startet bei 12.500,00 EUR."
)


def test_schwaerzt_endgueltig_und_ohne_werte() -> None:
    result = redact(PROMPT, extra_terms=["Nordlicht"])
    text = result.text
    for secret in ("internal_audit_memo.md", "pricing_algorithm.py", "0.73", "4.5%", "erika.muster@example.com",
                   "DE89", "sk-ant-api03", "Geheim123", "Nordlicht", "Erika Muster"):
        assert secret not in text, secret
    assert "README.md" in text  # nicht vertraulich
    assert f"entry_threshold={CONFIDENTIAL}" in text and f"lookback = {CONFIDENTIAL}" in text
    assert "Version 3" in text
    assert "12.500,00 EUR" in text  # Betraege nur auf Wunsch
    assert result.counts["CONFIDENTIAL_FILE"] == 2 and result.counts["SECRET"] == 2
    assert result.counts["PROTECTED_PARAMETER"] == 3 and result.counts["CONFIDENTIAL_TERM"] == 1
    assert "{{" not in text  # kein umkehrbarer Platzhalter


def test_betraege_und_sperrbegriffe_aus_der_umgebung(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DLP_TERMS", "Projekt Nordlicht, Quartalsziel")
    result = redact(PROMPT, redact_pii=False, redact_amounts=True)
    assert "Projekt Nordlicht" not in result.text and "12.500,00 EUR" not in result.text
    assert "erika.muster@example.com" in result.text  # PII bewusst nicht geschwaerzt
    assert redact("Ohne Treffer.").total == 0


def test_redact_endpunkt(client: TestClient) -> None:
    response = client.post("/api/v1/redact", json={"text": PROMPT, "extra_terms": ["Nordlicht"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == sum(body["counts"].values()) > 0
    assert "pricing_algorithm.py" not in body["redacted_text"] and body["ruleset_version"]
    assert client.post("/api/v1/redact", json={"text": ""}).status_code == 422
    assert "/api/v1/redact" in client.get("/openapi.json").json()["paths"]


def test_sperrbegriffe_aus_den_settings(make_client) -> None:
    """DLP_TERMS aus der .env landet ueber die Settings im Gateway, nicht nur ueber os.environ."""
    client = make_client(dlp_terms="Projekt Nordlicht, Quartalsziel")
    body = client.post("/api/v1/redact", json={"text": "Projekt Nordlicht erreicht das Quartalsziel."}).json()
    assert "Nordlicht" not in body["redacted_text"] and "Quartalsziel" not in body["redacted_text"]
    assert body["counts"]["CONFIDENTIAL_TERM"] == 2


# --- Release-Assistent ---------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def release_repo(tmp_path: Path) -> tuple[Path, str]:
    """Arbeitskopie auf der laufenden Version, ein neueres Release-Tag liegt bereit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "CI")
    (repo / "app.txt").write_text("stand 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Release aktuell")
    _git(repo, "tag", "-a", f"v{APP_VERSION}", "-m", "laufende Version")
    (repo / "app.txt").write_text("stand 2\n")
    _git(repo, "commit", "-q", "-am", "fix: Neuerung")
    _git(repo, "tag", "-a", "v99.0.0", "-m", "v99.0.0: Testrelease")
    commit = _git(repo, "rev-parse", "v99.0.0^{commit}")
    _git(repo, "reset", "-q", "--hard", f"v{APP_VERSION}")
    return repo, commit


def test_release_status_ohne_netz(make_full_client: Callable[..., TestClient], release_repo: tuple[Path, str]) -> None:
    repo, commit = release_repo
    client = make_full_client(release_repo_dir=str(repo))
    status = client.get("/api/system/release", params={"fetch": "false"}).json()
    assert status["git"] is True and status["update_available"] is True
    latest = status["latest"]
    assert (latest["tag"], latest["commit"], latest["signature"]) == ("v99.0.0", commit, "unsigned")
    assert latest["fast_forward"] is True and latest["changelog"][0].endswith("fix: Neuerung")


def test_release_nur_lokal(make_full_client: Callable[..., TestClient], release_repo: tuple[Path, str]) -> None:
    repo, commit = release_repo
    client = make_full_client(release_repo_dir=str(repo))
    response = client.post("/api/system/release/apply", json={"tag": "v99.0.0", "commit": commit, "admin_name": "IT"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "local_only"


def test_release_einspielen(
    make_full_client: Callable[..., TestClient], release_repo: tuple[Path, str], settings
) -> None:
    repo, commit = release_repo
    client = make_full_client(release_repo_dir=str(repo), release_update_local_only=False)
    client.post("/api/demo/seed", params={"only": "Rechnung_Gueltig_14UStG.pdf"})

    wrong = client.post("/api/system/release/apply", json={"tag": "v99.0.0", "commit": "0" * 40, "admin_name": "IT"})
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "hash_mismatch"
    assert _git(repo, "rev-parse", "HEAD") != commit  # nichts veraendert

    (repo / "app.txt").write_text("lokal geaendert\n")
    dirty = client.post("/api/system/release/apply", json={"tag": "v99.0.0", "commit": commit, "admin_name": "IT"})
    assert dirty.json()["error"]["code"] == "dirty_worktree"
    _git(repo, "checkout", "-q", "--", "app.txt")

    done = client.post("/api/system/release/apply", json={"tag": "v99.0.0", "commit": commit, "admin_name": "IT"})
    assert done.status_code == 200, done.text
    assert _git(repo, "rev-parse", "HEAD") == commit
    backup = settings.data_dir / "backups" / done.json()["database_backup"]
    assert backup.exists() and backup.stat().st_size > 0

    entry = client.get("/api/audit/trail", params={"document_id": "system"}).json()["items"][0]
    assert entry["event_type"] == "release_update" and entry["signature_status"] == "valid"
    assert entry["details"]["to_commit"] == commit and entry["details"]["admin_name"] == "IT"
    assert client.get("/api/audit/verify").json()["valid"] is True


def test_release_ohne_git(make_full_client: Callable[..., TestClient], tmp_path: Path) -> None:
    client = make_full_client(release_repo_dir=str(tmp_path / "kein-repo"))
    status = client.get("/api/system/release", params={"fetch": "false"}).json()
    assert status["git"] is False and status["update_available"] is False and "Git" in status["message"]


def test_i18n_reports_procedural_doc_and_copilot(make_full_client: Callable[..., TestClient]) -> None:
    """DE/EN/ES-Lokalisierung für Berichte, GoBD-Verfahrensdokumentation, ZIP und Referenz-Copilot."""
    client = make_full_client()
    seed = client.post("/api/demo/seed").json()
    doc = next(item for item in seed["items"] if "Steuerfalle" in item["filename"])
    doc_id = doc["id"]

    # Default (de) unveraendert
    r_de = client.get(f"/documents/{doc_id}/report", params={"format": "html"})
    assert r_de.status_code == 200 and '<html lang="de">' in r_de.text and "Compliance-Prüfzertifikat" in r_de.text

    # Englisch: JSON, HTML, Markdown
    r_en_json = client.get(f"/documents/{doc_id}/report", params={"format": "json", "lang": "en"}).json()
    assert r_en_json["lang"] == "en" and r_en_json["report_type"] == "Compliance Audit Certificate"
    r_en_html = client.get(f"/documents/{doc_id}/report", params={"format": "html", "lang": "en"})
    assert r_en_html.status_code == 200 and '<html lang="en">' in r_en_html.text and "Compliance Audit Certificate" in r_en_html.text
    r_es_md = client.get(f"/documents/{doc_id}/report", params={"format": "markdown", "lang": "es"})
    assert r_es_md.status_code == 200 and "Certificado de Auditoría de Cumplimiento" in r_es_md.text

    # Verfahrensdokumentation (EN / ES) und GoBD-ZIP (?lang=en)
    pd_en = client.get(f"/api/documents/{doc_id}/export/procedural-doc", params={"format": "html", "lang": "en"})
    assert pd_en.status_code == 200 and '<html lang="en">' in pd_en.text and "GoBD Procedural Documentation" in pd_en.text
    pd_es = client.get(f"/api/documents/{doc_id}/export/procedural-doc", params={"format": "markdown", "lang": "es"})
    assert pd_es.status_code == 200 and "Documentación de procedimientos GoBD" in pd_es.text
    zip_en = client.get(f"/api/documents/{doc_id}/export/gobd", params={"lang": "en"})
    assert zip_en.status_code == 200 and zip_en.headers["content-type"] == "application/zip"
    assert 'filename="AuditDataPackage_' in zip_en.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(zip_en.content)) as zf:
        assert '<html lang="en">' in zf.read(CERTIFICATE_FILE).decode("utf-8")
        assert '<html lang="en">' in zf.read(PROCEDURAL_DOC_FILE).decode("utf-8")
    assert verify_package(zip_en.content)["valid"] is True

    # Referenz-Copilot in EN & ES ohne echtes LLM
    cp_en = client.post(
        f"/documents/{doc_id}/copilot",
        json={"question": "Which mandatory fields are missing from this invoice?", "lang": "en"},
    )
    assert cp_en.status_code == 200
    assert cp_en.json()["reference"] is True and "mandatory elements" in cp_en.json()["answer"]

    cp_es = client.post(
        f"/documents/{doc_id}/copilot",
        json={"question": "¿Qué datos obligatorios faltan en esta factura?", "lang": "es"},
    )
    assert cp_es.status_code == 200
    assert cp_es.json()["reference"] is True and "datos obligatorios" in cp_es.json()["answer"].lower()

    # Alle [Z. n]-Zitate in Referenzantworten liegen innerhalb der Dokumentzeilen
    for item in seed["items"]:
        doc_detail = client.get(f"/documents/{item['id']}").json()
        lines = ((doc_detail.get("text_view") or {}).get("text") or doc_detail.get("text_preview") or "").splitlines()
        assert lines, f"{item['filename']}: Dokumenttext fehlt"
        for lang_answers in (REFERENCE_ANSWERS_EN, REFERENCE_ANSWERS_ES):
            for answer in lang_answers.get(item["filename"], ()):
                for match in re.finditer(r"\[Z\.\s*(\d+)\]", answer):
                    assert 1 <= int(match.group(1)) <= len(lines), f"{item['filename']}: {match.group(0)}"

    # Nicht-Latin-1-Dateiname (z. B. Polnisch/Tschechisch) stuerzt bei JSON/Markdown-Report nicht ab
    upload = client.post(
        "/documents/upload",
        files={"file": ("Rechnung_Łódź_2026.pdf", build_hybrid_pdf(HYBRID_INVOICE), "application/pdf")},
    )
    assert upload.status_code in (200, 201)
    lodz_id = upload.json()["id"]
    assert client.post(f"/documents/{lodz_id}/extract", params={"wait": "true"}).status_code == 200
    for fmt, lang in (("json", "en"), ("markdown", "es")):
        rep = client.get(f"/documents/{lodz_id}/report", params={"format": fmt, "lang": lang})
        assert rep.status_code == 200
        assert "inline;" in rep.headers["content-disposition"]
        assert "filename*=UTF-8''" in rep.headers["content-disposition"]

    # Heuristik-Fallback respektiert lang
    rec = client.get(f"/documents/{doc_id}").json()
    fake_rec = type("Rec", (), {"scorecard": rec.get("scorecard"), "extraction": rec.get("extraction")})()
    assert "without a language model" in heuristic_copilot_answer(fake_rec, "Q", "timeout", lang="en")
    assert "sin modelo de lenguaje" in heuristic_copilot_answer(fake_rec, "Q", "timeout", lang="es")
