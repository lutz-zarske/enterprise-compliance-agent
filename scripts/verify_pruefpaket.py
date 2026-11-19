#!/usr/bin/env python
"""Prüft ein GoBD-Prüfdatenpaket (ZIP) vollständig eigenständig und offline.

Benötigt außer der Python-Standardbibliothek nur ``cryptography`` – keine
Backend-Installation, keine Datenbank, kein Netzwerk.

Geprüft werden:
- Pfadsicherheit (kein Zip Slip) und Eindeutigkeit aller ZIP-Einträge
- SHA-256 jeder Datei laut ``manifest.json`` sowie Abgleich mit ``document.sha256``
- Ed25519-Signatur des Manifests (kanonisches JSON mit ``sort_keys=True``,
  ``separators=(",", ":")``, ``ensure_ascii=False``, UTF-8)
- Optional mit ``--fingerprint``: Abgleich des 128-Bit-Schlüssel-Fingerabdrucks
  gegen den unabhängig hinterlegten System-Schlüssel (``GET /api/audit/signing-key``)

Aufruf::

    python scripts/verify_pruefpaket.py Pruefdatenpaket_Rechnung.zip
    python scripts/verify_pruefpaket.py paket.zip --fingerprint a0df:3ccf:...

Exitcodes: 0 = Paket unverändert und Signatur gültig, 1 = Befund oder Lesefehler.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST_FILE = "manifest.json"
ALGORITHM = "Ed25519"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fingerprint(public_raw: bytes) -> str:
    digest = hashlib.sha256(public_raw).hexdigest()
    return ":".join(digest[i : i + 4] for i in range(0, 32, 4))


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _is_unsafe_path(path: str) -> bool:
    if not path or "\\" in path or path.startswith("/"):
        return True
    return any(part in {"", ".", ".."} for part in path.split("/"))


def _verify_signature(
    manifest: dict[str, Any], *, expected_fingerprint: str | None = None
) -> tuple[bool, str]:
    signature = manifest.get("signature") or {}
    if not isinstance(signature, dict) or signature.get("algorithm") != ALGORITHM:
        return False, "Signaturverfahren fehlt oder wird nicht unterstützt."
    try:
        public_raw = base64.b64decode(signature["public_key"])
        sig_bytes = base64.b64decode(signature["value"])
    except (KeyError, ValueError, TypeError):
        return False, "Signaturfelder sind unvollständig."
    if expected_fingerprint and _fingerprint(public_raw) != expected_fingerprint:
        return False, "Mit einem fremden Schlüssel signiert (Fingerabdruck weicht vom System-Schlüssel ab)."
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(sig_bytes, _canonical_bytes(unsigned))
    except (InvalidSignature, ValueError):
        return False, "Signatur ungültig - der Inhalt wurde verändert."
    return True, "Signatur gültig."


def verify_package_bytes(data: bytes, *, expected_fingerprint: str | None = None) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        raw_names = archive.namelist()
        duplicates = sorted({name for name in raw_names if raw_names.count(name) > 1})
        unsafe_paths = sorted({name for name in raw_names if _is_unsafe_path(name)})
        manifest = json.loads(archive.read(MANIFEST_FILE))
        names = set(raw_names)
        doc_info = manifest.get("document") or {}
        expected_doc_sha = doc_info.get("sha256")
        expected_orig = f"original/{doc_info.get('filename', '')}" if doc_info.get("filename") else None
        original_sha_ok = True
        file_results: list[dict[str, Any]] = []
        for item in manifest.get("files", []):
            path = str(item.get("path", ""))
            present = path in names and path not in duplicates and path not in unsafe_paths
            actual = _sha256(archive.read(path)) if present else None
            ok = present and actual == item.get("sha256")
            if expected_orig and path == expected_orig and expected_doc_sha and actual != expected_doc_sha:
                ok = False
                original_sha_ok = False
            file_results.append({"path": path, "ok": ok})
    signature_ok, signature_message = _verify_signature(manifest, expected_fingerprint=expected_fingerprint)
    unexpected = sorted(names - {str(item.get("path", "")) for item in manifest.get("files", [])} - {MANIFEST_FILE})
    valid = (
        signature_ok
        and original_sha_ok
        and not duplicates
        and not unsafe_paths
        and all(item["ok"] for item in file_results)
        and not unexpected
    )
    return {
        "valid": valid,
        "signature": signature_message,
        "files": file_results,
        "unexpected_files": unexpected,
        "duplicate_files": duplicates,
        "unsafe_paths": unsafe_paths,
        "fingerprint": (manifest.get("signature") or {}).get("fingerprint"),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="Pfad zum ZIP-Archiv")
    parser.add_argument("--fingerprint", help="Erwarteter Fingerabdruck des System-Schlüssels")
    args = parser.parse_args()

    try:
        result = verify_package_bytes(args.package.read_bytes(), expected_fingerprint=args.fingerprint)
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"[FEHLER] Archiv nicht prüfbar: {exc}", file=sys.stderr)
        print("ERGEBNIS: UNGÜLTIG")
        return 1

    for item in result["files"]:
        print(f"[{'OK ' if item['ok'] else 'FEHLER'}] {item['path']}")
    for name in result["unexpected_files"]:
        print(f"[FEHLER] nicht im Manifest: {name}")
    for name in result["duplicate_files"]:
        print(f"[FEHLER] doppelter Archiveintrag: {name}")
    for name in result["unsafe_paths"]:
        print(f"[FEHLER] unzulässiger Archivpfad: {name}")
    print(f"Signatur: {result['signature']} (Schlüssel {result['fingerprint']})")
    if not args.fingerprint:
        print("Hinweis: Ohne --fingerprint ist nur die Unverändertheit belegt, nicht die Herkunft.")
    print("ERGEBNIS: gültig" if result["valid"] else "ERGEBNIS: UNGÜLTIG")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
