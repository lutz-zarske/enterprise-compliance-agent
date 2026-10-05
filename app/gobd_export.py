"""Prüfdatenpaket als ZIP-Archiv (GoBD-orientiert).

Inhalt
------
1. ``original/<Dateiname>``   Originalbeleg, bitgenau wie empfangen (PDF oder XML)
2. ``<anhang>.xml``           eingebetteter E-Rechnungs-Datensatz (nur hybride PDFs)
3. ``ledger_audit_trail.json`` alle Ledger-Eintraege des Dokuments + Kettenpruefung
4. ``audit_certificate.html``  druckfertiges A4-Pruefzertifikat
5. ``manifest.json``           SHA-256 je Datei, Pruefzeitstempel, System-Signatur

Einordnung
----------
Das Paket unterstuetzt Nachvollziehbarkeit und Unveraenderbarkeit (GoBD
Rz. 58 ff.) fuer *einen* Beleg - etwa zur Vorlage bei einer Betriebspruefung
oder zur Uebergabe an ein Archivsystem.  Es ist **kein** Datentraeger nach dem
"Beschreibungsstandard fuer die Datentraegerueberlassung" (index.xml) und ersetzt
weder revisionssichere Archivierung noch die Verfahrensdokumentation.

Jeder Ledger-Eintrag ist einzeln nachpruefbar: ``entry_hash`` ist SHA-256
ueber das kanonische JSON aller Felder ausser ``seq`` und ``entry_hash``.
Die Verkettung (``previous_hash``) laesst sich nur gegen das Gesamtprotokoll
pruefen - dafuer stehen Kopf-Hash und Ergebnis der Gesamtpruefung im Manifest.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime
from typing import Any

from app.audit_ledger import ChainVerification, LedgerEntry, compute_entry_hash
from app.config import APP_TITLE, APP_VERSION
from app.db import DocumentRecord, utcnow
from app.signing import SystemSigner

PACKAGE_FORMAT = "eca-pruefdatenpaket/1.0"

LEDGER_FILE = "ledger_audit_trail.json"
CERTIFICATE_FILE = "audit_certificate.html"
MANIFEST_FILE = "manifest.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def build_ledger_document(
    record: DocumentRecord, entries: list[LedgerEntry], verification: ChainVerification
) -> dict[str, Any]:
    """Ledger-Auszug des Dokuments, aelteste Eintraege zuerst, je Eintrag nachgerechnet."""
    ordered = sorted(entries, key=lambda entry: entry.seq or 0)
    return {
        "document_id": record.id,
        "document_sha256": record.sha256,
        "hash_algorithm": "SHA-256 über kanonisches JSON (sortierte Schlüssel, ohne Leerzeichen, UTF-8)",
        "hashed_fields": "alle Felder eines Eintrags außer seq und entry_hash",
        "entries": [
            {**entry.to_dict(), "entry_hash_recomputed_ok": compute_entry_hash(entry.hashed_content()) == entry.entry_hash}
            for entry in ordered
        ],
        "chain_verification": verification.to_dict(),
    }


def build_gobd_package(
    record: DocumentRecord,
    *,
    original: bytes,
    embedded_xml: tuple[str, bytes] | None,
    entries: list[LedgerEntry],
    verification: ChainVerification,
    certificate_html: str,
    signer: SystemSigner,
    created_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Erzeugt das ZIP und liefert (ZIP-Bytes, Manifest)."""
    created = created_at or utcnow()
    original_path = f"original/{record.original_filename}"
    files: list[tuple[str, bytes, str]] = [
        (original_path, original, "Originalbeleg, bitgenau wie empfangen"),
    ]
    if embedded_xml is not None:
        name, data = embedded_xml
        files.append((name, data, "Eingebetteter E-Rechnungs-Datensatz (maßgeblich bei hybriden Rechnungen)"))
    ledger = build_ledger_document(record, entries, verification)
    files.append((LEDGER_FILE, _json_bytes(ledger), "Prüfprotokoll des Dokuments mit SHA-256-Hash-Kette"))
    files.append((CERTIFICATE_FILE, certificate_html.encode("utf-8"), "Druckfertiges A4-Prüfzertifikat"))

    scorecard = record.scorecard or {}
    sign_off = record.sign_off or {}
    analysis = max(
        (entry for entry in entries if entry.event_type == "analysis"), key=lambda entry: entry.seq or 0, default=None
    )
    manifest: dict[str, Any] = {
        "package_format": PACKAGE_FORMAT,
        "generator": f"{APP_TITLE} v{APP_VERSION}",
        "created_at": created.isoformat(),
        "document": {
            "id": record.id,
            "filename": record.original_filename,
            "content_type": record.content_type,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
            "uploaded_at": record.created_at.isoformat(),
        },
        "audit": {
            "audited_at": record.extracted_at.isoformat() if record.extracted_at else None,
            "model": record.model,
            "provider": record.provider,
            "compliance_score": scorecard.get("score"),
            "band": scorecard.get("band"),
            "release_recommendation": scorecard.get("release_recommendation"),
            "ruleset_version": scorecard.get("ruleset_version"),
            "einvoice_profile": (record.einvoice or {}).get("profile"),
            "analysis_entry_hash": analysis.entry_hash if analysis else None,
            "sign_off": (
                {
                    "status": sign_off.get("status"),
                    "auditor_name": sign_off.get("auditor_name"),
                    "sealed_at": sign_off.get("sealed_at"),
                    "ledger_entry_hash": sign_off.get("ledger_entry_hash"),
                }
                if sign_off
                else None
            ),
        },
        "ledger": {
            "chain_valid": verification.valid,
            "chain_entries": verification.entries,
            "head_hash": verification.head_hash,
            "verified_at": verification.verified_at,
        },
        "files": [
            {"path": path, "sha256": _sha256(data), "size_bytes": len(data), "description": description}
            for path, data, description in files
        ],
        "verification": [
            "1. SHA-256 jeder Datei mit files[].sha256 vergleichen (z. B. sha256sum / Get-FileHash).",
            "2. Signatur prüfen: Ed25519 über das kanonische JSON dieses Manifests ohne das Feld 'signature' "
            "(sortierte Schlüssel, Trennzeichen ',' und ':', UTF-8).",
            "3. Fingerabdruck des Schlüssels mit dem unabhängig hinterlegten System-Schlüssel vergleichen "
            "(GET /api/audit/signing-key) - ein im Paket enthaltener Schlüssel allein beweist nichts.",
            "4. ledger.head_hash mit einem extern verankerten Kopf-Hash abgleichen (GET /api/audit/head).",
            "Werkzeug: python scripts/verify_pruefpaket.py <paket.zip> [--fingerprint <fp>]",
        ],
        "legal_note": (
            "Prüfdatenpaket zur Nachvollziehbarkeit eines Einzelbelegs (GoBD Rz. 58 ff.). Kein Datenträger nach "
            "dem Beschreibungsstandard für die Datenträgerüberlassung und kein Ersatz für revisionssichere "
            "Archivierung. Die System-Signatur ist kein qualifiziertes elektronisches Siegel und kein "
            "qualifizierter Zeitstempel nach eIDAS."
        ),
    }
    manifest["signature"] = signer.sign(manifest)

    stamp = created.timetuple()[:6]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data, _ in [*files, (MANIFEST_FILE, _json_bytes(manifest), "")]:
            info = zipfile.ZipInfo(path, date_time=stamp)  # type: ignore[arg-type]
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue(), manifest


def verify_package(data: bytes, *, expected_fingerprint: str | None = None) -> dict[str, Any]:
    """Prueft ein Paket vollstaendig: Datei-Hashes und Signatur des Manifests."""
    from app.signing import verify_signed_payload

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read(MANIFEST_FILE))
        names = set(archive.namelist())
        file_results = []
        for item in manifest.get("files", []):
            present = item["path"] in names
            actual = _sha256(archive.read(item["path"])) if present else None
            file_results.append({"path": item["path"], "ok": present and actual == item["sha256"]})
    signature_ok, signature_message = verify_signed_payload(manifest, expected_fingerprint=expected_fingerprint)
    unexpected = sorted(names - {item["path"] for item in manifest.get("files", [])} - {MANIFEST_FILE})
    return {
        "valid": signature_ok and all(result["ok"] for result in file_results) and not unexpected,
        "signature": signature_message,
        "files": file_results,
        "unexpected_files": unexpected,
        "fingerprint": (manifest.get("signature") or {}).get("fingerprint"),
    }
