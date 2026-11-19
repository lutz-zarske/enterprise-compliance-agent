"""System-Signatur für Prüfpakete (Ed25519).

Der Schlüssel wird beim ersten Bedarf unter ``data/.signing.key`` erzeugt
(Dateirechte 0600, nie im Repository).  Die Signatur belegt, dass ein Manifest
unverändert aus *dieser* Installation stammt.

Abgrenzung: Das ist ein selbst erzeugter Schlüssel - weder ein qualifiziertes
elektronisches Siegel nach eIDAS noch ein qualifizierter Zeitstempel.  Damit die
Signatur Beweiswert hat, muss der Prüfer den Fingerabdruck des öffentlichen
Schlüssels unabhängig vom Paket kennen (``GET /api/audit/signing-key``,
z. B. in der Verfahrensdokumentation hinterlegt).  Ein im Paket mitgelieferter
Schlüssel allein beweist nichts - ein Angreifer könnte neu signieren.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)

ALGORITHM = "Ed25519"

_LOCK = threading.Lock()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministische Serialisierung - identisch zur Hash-Kette des Ledgers."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fingerprint(public_raw: bytes) -> str:
    """Erste 128 Bit (32 Hex-Zeichen) von SHA-256 über den rohen öffentlichen Schlüssel, in Vierergruppen."""
    digest = hashlib.sha256(public_raw).hexdigest()
    return ":".join(digest[i : i + 4] for i in range(0, 32, 4))


def write_secret_file(path: Path, data: bytes) -> bytes:
    """Legt eine Schlüsseldatei atomar mit Dateirechten 0600 an; bei Rennen gewinnt die bestehende Datei."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return path.read_bytes()
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - z. B. Windows ohne POSIX-Rechte
        pass
    return data


class SystemSigner:
    """Lädt oder erzeugt den Ed25519-Schlüssel und signiert Manifeste."""

    def __init__(self, key_file: Path) -> None:
        self._key_file = key_file
        self._private: Ed25519PrivateKey | None = None

    def _key(self) -> Ed25519PrivateKey:
        with _LOCK:
            if self._private is None:
                if self._key_file.exists():
                    self._private = Ed25519PrivateKey.from_private_bytes(self._key_file.read_bytes()[:32])
                else:
                    self._private = Ed25519PrivateKey.generate()
                    raw = self._private.private_bytes(
                        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
                    )
                    stored = write_secret_file(self._key_file, raw)
                    if stored[:32] != raw:
                        self._private = Ed25519PrivateKey.from_private_bytes(stored[:32])
                    else:
                        logger.info("Neuer Signaturschlüssel erzeugt (%s).", self._key_file.name)
            return self._private

    @property
    def public_raw(self) -> bytes:
        return self._key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def public_info(self) -> dict[str, str]:
        raw = self.public_raw
        return {
            "algorithm": ALGORITHM,
            "public_key": base64.b64encode(raw).decode("ascii"),
            "fingerprint": fingerprint(raw),
        }

    def sign(self, payload: dict[str, Any]) -> dict[str, str]:
        """Signiert die kanonische Form von ``payload`` (ohne das Feld ``signature``)."""
        unsigned = {key: value for key, value in payload.items() if key != "signature"}
        return self.sign_bytes(canonical_bytes(unsigned))

    def sign_bytes(self, data: bytes) -> dict[str, str]:
        """Ed25519-Signatur über beliebige Bytes, samt öffentlichem Schlüssel und Fingerabdruck."""
        signature = self._key().sign(data)
        return {**self.public_info(), "value": base64.b64encode(signature).decode("ascii")}


def verify_signature(signature: dict[str, Any], data: bytes, *, expected_fingerprint: str | None = None) -> tuple[bool, str]:
    """Prüft eine Signatur aus ``SystemSigner.sign_bytes`` über ``data``."""
    if signature.get("algorithm") != ALGORITHM:
        return False, "Signaturverfahren fehlt oder wird nicht unterstützt."
    try:
        public_raw = base64.b64decode(signature["public_key"])
        value = base64.b64decode(signature["value"])
    except (KeyError, ValueError, TypeError):
        return False, "Signaturfelder sind unvollständig."
    if expected_fingerprint and fingerprint(public_raw) != expected_fingerprint:
        return False, "Mit einem fremden Schlüssel signiert (Fingerabdruck weicht vom System-Schlüssel ab)."
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(value, data)
    except (InvalidSignature, ValueError):
        return False, "Signatur ungültig - der Inhalt wurde verändert."
    return True, "Signatur gültig."


def verify_signed_payload(payload: dict[str, Any], *, expected_fingerprint: str | None = None) -> tuple[bool, str]:
    """Prüft die Signatur eines Manifests; optional gegen einen bekannten Fingerabdruck."""
    unsigned = {key: item for key, item in payload.items() if key != "signature"}
    ok, message = verify_signature(
        payload.get("signature") or {}, canonical_bytes(unsigned), expected_fingerprint=expected_fingerprint
    )
    if not ok and message.startswith("Signatur ungültig"):
        return False, "Signatur ungültig - das Manifest wurde verändert."
    if not ok and message.startswith("Mit einem fremden"):
        return False, "Fingerabdruck des Schlüssels weicht vom erwarteten System-Schlüssel ab."
    return ok, message
