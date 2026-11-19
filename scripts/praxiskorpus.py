"""Praxistest mit öffentlichen E-Rechnungs-Testbelegen (optional, braucht Internet).

Lädt die Testbelege der Projekte Mustangproject (ZUGFeRD/Factur-X, inkl. der
offiziellen ZUGFeRD-2.5.2-Beispiele), KoSIT (XRechnung-Testsuite) und
EU-Kommission (EN-16931-Beispiele) von GitHub – nur Daten, nichts wird
ausgeführt – und schickt jeden Beleg ohne Sprachmodell durch den Agenten.

Ausgewertet werden je Beleg: Annahme oder Ablehnung, Score und Abzüge, der
Abgleich XML ↔ PDF-Bildteil und – bei hybriden Rechnungen – ob das Regelwerk
Netto, Umsatzsteuer und Gesamtbetrag aus dem Bildteil genauso liest wie der
XML-Datensatz.

    python scripts/praxiskorpus.py <zielordner>

Ergebnis: <zielordner>/results.json und eine Zusammenfassung auf der Konsole.
Die Belege stehen unter den Lizenzen ihrer Projekte (Apache 2.0 bzw. EUPL 1.2)
und werden nicht ins Repository übernommen.
"""

from __future__ import annotations

import json
import logging
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from decimal import Decimal

import httpx
from fastapi import Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.heuristics import heuristic_extraction  # noqa: E402
from app.llm import OllamaClient  # noqa: E402
from app.main import create_app, get_llm, get_service  # noqa: E402
from app.pdf_reader import extract_text  # noqa: E402
from app.scoring import complete_amounts  # noqa: E402
from app.services import DocumentService  # noqa: E402

REPOS = {
    "ZUGFeRD/mustangproject": ("library/src/test/resources/", "validator/src/test/resources/"),
    "itplr-kosit/xrechnung-testsuite": ("src/test/business-cases/",),
    "ConnectingEurope/eInvoicing-EN16931": ("cii/examples/", "ubl/examples/"),
}
MAX_BYTES = 3_000_000


def _gh(path: str) -> dict:
    """GitHub-API über die gh-CLI (falls vorhanden) oder anonym."""
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(out.stdout)
    except (OSError, subprocess.CalledProcessError):
        with urllib.request.urlopen(f"https://api.github.com/{path}", timeout=60) as response:  # noqa: S310
            return json.loads(response.read())


def fetch(target: pathlib.Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for repo, prefixes in REPOS.items():
        branch = _gh(f"repos/{repo}")["default_branch"]
        sha = _gh(f"repos/{repo}/commits/{branch}")["sha"]
        tree = _gh(f"repos/{repo}/git/trees/{sha}?recursive=1")["tree"]
        files = [
            item for item in tree
            if item["type"] == "blob" and item["path"].lower().endswith((".pdf", ".xml"))
            and item["path"].startswith(prefixes) and item.get("size", 0) <= MAX_BYTES
        ]
        short = repo.split("/")[1][:12]
        print(f"{repo}@{sha[:8]}: {len(files)} Belege", flush=True)
        for number, item in enumerate(files):
            name = pathlib.PurePosixPath(item["path"]).name
            path = target / short / f"{number:04d}_{name[-80:]}"  # kurze Pfade (Windows)
            index[str(path.relative_to(target))] = f"{repo}@{sha[:8]}:{item['path']}"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://raw.githubusercontent.com/{repo}/{sha}/{urllib.parse.quote(item['path'])}"
                with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - feste GitHub-Quelle
                    path.write_bytes(response.read())
    return index


def _offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("kein Sprachmodell", request=request)


def run(target: pathlib.Path, index: dict[str, str]) -> list[dict]:
    work = pathlib.Path(tempfile.mkdtemp(prefix="eca_praxiskorpus_"))
    settings = Settings(
        _env_file=None, app_env="test", api_key=None, log_json=False, llm_retry_delays="0,0",
        database_url=f"sqlite:///{(work / 'korpus.db').as_posix()}", upload_dir=work / "uploads",
        max_upload_bytes=20 * 1024 * 1024, rate_limit_upload_per_minute=0, rate_limit_extract_per_minute=0,
        rate_limit_settings_per_minute=0,
    )
    llm = OllamaClient(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(_offline)))
    app = create_app(settings)

    def service(request: Request) -> DocumentService:
        return DocumentService(settings, request.app.state.repository, llm, ledger=request.app.state.ledger)

    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_service] = service
    rows: list[dict] = []
    with TestClient(app) as client:
        for rel, source in sorted(index.items()):
            path = target / rel
            data = path.read_bytes()
            ctype = "application/pdf" if path.suffix.lower() == ".pdf" else "application/xml"
            row: dict = {"file": rel, "source": source}
            upload = client.post("/documents/upload", files={"file": (path.name, data, ctype)})
            row["upload"] = upload.status_code
            if upload.status_code != 201:
                row["reason"] = (upload.json().get("error") or {}).get("message", "")[:160]
                rows.append(row)
                continue
            document_id = upload.json()["id"]
            body = client.post(f"/documents/{document_id}/extract?wait=true").json()
            card = body["scorecard"]
            einvoice = client.get(f"/documents/{document_id}").json().get("einvoice") or {}
            row.update(
                provider=body["provider"], score=card["score"], recommendation=card["release_recommendation"],
                profile=einvoice.get("profile"),
                deductions=[(c["id"], c["deduction"], (c.get("detail") or "")[:140])
                            for t in card["tiles"] for c in t["checks"] if c["deduction"]],
                visual_mismatch=[(v["bt"], v["xml_value"], v.get("visual_value"))
                                 for v in einvoice.get("visual_check") or [] if v["status"] == "mismatch"],
            )
            if ctype == "application/pdf" and einvoice.get("grand_total") is not None and not einvoice.get("error"):
                text = extract_text(data).text
                read = complete_amounts(heuristic_extraction(text), text, rule_based=True)
                got = {"net_total": read.net_amount, "tax_total": read.tax_amount, "grand_total": read.total_amount}
                row["text_vs_xml"] = {}
                for key, value in got.items():
                    if einvoice.get(key) is None:
                        continue
                    xml = Decimal(str(einvoice[key]))
                    row["text_vs_xml"][key] = (
                        "ok" if value is not None and abs(value - xml) <= Decimal("0.02")
                        else "leer" if value is None else f"falsch {value} statt {xml}"
                    )
            rows.append(row)
    return rows


def main() -> None:
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "praxiskorpus").resolve()
    logging.disable(logging.CRITICAL)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows-Konsole (cp1252) kennt „↔“ nicht
    index = fetch(target)
    rows = run(target, index)
    (target / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    checked = [r for r in rows if "score" in r]
    print(f"Belege: {len(rows)} · geprüft: {len(checked)} · abgewiesen: {len(rows) - len(checked)}")
    print("Abweisungsgründe:", Counter(r["reason"][:60] for r in rows if "reason" in r).most_common(4))
    print("Scores:", sorted(Counter(r["score"] for r in checked).items(), reverse=True))
    print("Abweichung XML ↔ PDF:", sum(1 for r in checked if r["visual_mismatch"]))
    print("Bildteil gegen XML (Beträge):",
          Counter(v.split(" ")[0] for r in checked for v in (r.get("text_vs_xml") or {}).values()))


if __name__ == "__main__":
    main()
