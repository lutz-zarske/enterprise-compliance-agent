"""Release-Assistent (seit v2.4): neue Versionen pruefen und kontrolliert einspielen.

Grundsaetze - kein unkontrolliertes Auto-Pulling:

* **Pruefen** liest die Tags ueber ``git fetch --tags`` mit den Git-Zugangsdaten
  des Rechners (kein Token, funktioniert auch bei privaten Repositories) und
  meldet den hoechsten SemVer-Tag ueber der laufenden Version samt Commit-Hash,
  Tag-Signatur und Aenderungen.
* **Einspielen** nur nach ausdruecklicher Bestaetigung des exakten Commit-Hashes,
  nur als Fast-Forward (keine Merges, kein Ueberschreiben lokaler Aenderungen),
  nur ohne laufende Analyse und standardmaessig nur von ``localhost``.  Vorher
  entsteht eine Sicherungskopie von ``data/agent.db``; der Wechsel wird im
  Ledger protokolliert.  Abhaengigkeiten und Frontend-Build aktualisiert danach
  der Neustart ueber ``Start_Compliance_Agent.bat``.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_GIT_TIMEOUT = 45


class ReleaseError(Exception):
    """Update nicht moeglich; ``code`` und Meldung gehen an die Oberflaeche."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_TAG.match(value if value.startswith("v") else f"v{value}")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


@dataclass(slots=True)
class ReleaseManager:
    repo_dir: Path
    current_version: str
    busy: bool = False

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        result = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["git", "-C", str(self.repo_dir), *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT, env=env, check=False,
        )
        if check and result.returncode != 0:
            raise ReleaseError("git_failed", f"git {args[0]} fehlgeschlagen: {result.stderr.strip()[:300]}")
        return result

    def _is_checkout(self) -> bool:
        try:
            return self._git("rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError):
            return False

    def _signature(self, tag: str) -> str:
        """``valid`` (geprueft), ``invalid`` (Signatur passt nicht) oder ``unsigned``."""
        raw = self._git("cat-file", "-p", tag, check=False).stdout
        if "BEGIN PGP SIGNATURE" not in raw and "BEGIN SSH SIGNATURE" not in raw:
            return "unsigned"
        return "valid" if self._git("verify-tag", tag, check=False).returncode == 0 else "invalid"

    def latest(self) -> dict[str, Any] | None:
        """Hoechster SemVer-Tag ueber der laufenden Version (ohne Netzwerk)."""
        running = semver(self.current_version) or (0, 0, 0)
        tags = [
            tag for tag in self._git("tag", "--list", "v*").stdout.split()
            if (version := semver(tag)) is not None and version > running
        ]
        if not tags:
            return None
        tag = max(tags, key=lambda name: semver(name) or (0, 0, 0))
        commit = self._git("rev-list", "-n", "1", tag).stdout.strip()
        changelog = self._git("log", "--format=%h %s", "--max-count=30", f"HEAD..{tag}").stdout.splitlines()
        return {
            "tag": tag,
            "version": tag.removeprefix("v"),
            "commit": commit,
            "signature": self._signature(tag),
            "message": self._git("tag", "--list", "--format=%(contents:subject)", tag).stdout.strip(),
            "changelog": changelog,
            "fast_forward": self._git("merge-base", "--is-ancestor", "HEAD", tag, check=False).returncode == 0,
        }

    def status(self, *, fetch: bool) -> dict[str, Any]:
        base: dict[str, Any] = {
            "git": False, "current_version": self.current_version, "current_commit": None,
            "latest": None, "update_available": False, "dirty": False, "busy": self.busy,
            "checked_at": datetime.now(UTC).isoformat(), "message": None,
        }
        if not self._is_checkout():
            return {**base, "message": "Keine Git-Arbeitskopie (z. B. Docker-Image) - Update über ein neues Image."}
        message = None
        if fetch:
            fetched = self._git("fetch", "--tags", "--quiet", "origin", check=False)
            if fetched.returncode != 0:
                message = f"Server nicht erreichbar: {fetched.stderr.strip()[:200]}"
        latest = self.latest()
        return {
            **base,
            "git": True,
            "current_commit": self._git("rev-parse", "HEAD").stdout.strip(),
            "latest": latest,
            "update_available": latest is not None,
            "dirty": bool(self._git("status", "--porcelain", "--untracked-files=no").stdout.strip()),
            "message": message,
        }

    def backup_database(self, database_file: Path | None, backup_dir: Path, label: str) -> Path | None:
        """Konsistente SQLite-Kopie ueber die Backup-API (auch bei offenem WAL)."""
        if database_file is None or not database_file.exists():
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"agent-{stamp}-{label}.db"
        with sqlite3.connect(database_file) as source, sqlite3.connect(target) as copy:
            source.backup(copy)
        return target

    def preflight(self, tag: str, confirm_commit: str, *, active_analyses: int) -> dict[str, Any]:
        """Prueft alle Vorbedingungen; liefert das Release oder wirft ``ReleaseError``."""
        if self.busy:
            raise ReleaseError("release_update_running", "Ein Update läuft bereits.")
        if active_analyses:
            raise ReleaseError("analysis_running", f"{active_analyses} Analyse(n) laufen noch - bitte abwarten.")
        if not self._is_checkout():
            raise ReleaseError("no_git_checkout", "Keine Git-Arbeitskopie - Update über ein neues Image.")
        latest = self.latest()
        if latest is None or latest["tag"] != tag:
            raise ReleaseError("release_not_found", f"{tag} ist nicht die neueste verfügbare Version.")
        if latest["commit"] != confirm_commit:
            raise ReleaseError("hash_mismatch", "Der bestätigte Commit-Hash passt nicht zum Release-Tag.")
        if latest["signature"] == "invalid":
            raise ReleaseError("signature_invalid", "Die Signatur des Release-Tags ist ungültig.")
        if not latest["fast_forward"]:
            raise ReleaseError("not_fast_forward", "Lokaler Stand ist abgezweigt - kein Fast-Forward möglich.")
        if self._git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise ReleaseError("dirty_worktree", "Lokale Änderungen vorhanden - Update abgebrochen.")
        return latest

    def fast_forward(self, tag: str) -> str:
        """Spielt ``tag`` ein (nur Fast-Forward); liefert den vorherigen Commit."""
        self.busy = True
        try:
            previous = self._git("rev-parse", "HEAD").stdout.strip()
            self._git("merge", "--ff-only", "--quiet", tag)
            return previous
        finally:
            self.busy = False
