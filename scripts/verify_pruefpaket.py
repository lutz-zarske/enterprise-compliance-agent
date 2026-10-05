#!/usr/bin/env python
"""Prueft ein Pruefdatenpaket (ZIP) unabhaengig vom laufenden Server.

Geprueft werden die SHA-256 jeder Datei laut ``manifest.json`` und die
Ed25519-Signatur des Manifests.  Mit ``--fingerprint`` wird zusaetzlich der
Schluessel gegen den bekannten System-Schluessel abgeglichen
(``GET /api/audit/signing-key``) - erst das belegt die Herkunft.

Aufruf::

    python scripts/verify_pruefpaket.py Pruefdatenpaket_Rechnung.zip
    python scripts/verify_pruefpaket.py paket.zip --fingerprint a0df:3ccf:...

Exitcodes: 0 = Paket unveraendert und Signatur gueltig, 1 = Befund.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Projektwurzel in den Importpfad aufnehmen, damit "app" gefunden wird.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gobd_export import verify_package  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="Pfad zum ZIP-Archiv")
    parser.add_argument("--fingerprint", help="Erwarteter Fingerabdruck des System-Schluessels")
    args = parser.parse_args()

    result = verify_package(args.package.read_bytes(), expected_fingerprint=args.fingerprint)
    for item in result["files"]:
        print(f"[{'OK ' if item['ok'] else 'FEHLER'}] {item['path']}")
    for name in result["unexpected_files"]:
        print(f"[FEHLER] nicht im Manifest: {name}")
    print(f"Signatur: {result['signature']} (Schluessel {result['fingerprint']})")
    if not args.fingerprint:
        print("Hinweis: Ohne --fingerprint ist nur die Unveraendertheit belegt, nicht die Herkunft.")
    print("ERGEBNIS: gueltig" if result["valid"] else "ERGEBNIS: UNGUELTIG")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
