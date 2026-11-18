"""Lokale KI erkennen, starten und stoppen - ohne Terminal, aus der Oberfläche heraus.

Statt "bitte 'ollama serve' im Terminal ausführen" bietet die Oberfläche an:
"Ollama ist installiert, läuft aber nicht - jetzt starten?".  Dafür erkennt
dieses Modul, welche lokale KI installiert ist (Ollama, LM Studio) und ob ihr
Port antwortet, und startet bzw. stoppt Ollama im Hintergrund.

Sicherheit: Gestartet und beendet wird ausschließlich ein Programm aus der
festen Liste unten, mit festem Aufruf.  Es gibt keinen Parameter, über den ein
Aufrufer einen eigenen Pfad, eigene Argumente oder einen Prozessnamen setzen
könnte.  Die Routen sind zusätzlich auf Anfragen direkt am Server (localhost)
beschränkt (``LOCAL_AI_CONTROL_LOCAL_ONLY``).

Im Docker-Container gibt es kein lokales Ollama-Programm: Dort meldet die
Erkennung sauber "nicht verfügbar" und verweist auf den Ollama-Dienst der
Compose-Datei.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Speicher-Einstellungen für ein hier gestartetes Ollama: 32k Kontext eines 14B-Modells
#: passen nur mit Flash Attention und 8-Bit-KV-Cache in 16 GB VRAM.  Gesetzte Werte bleiben.
OLLAMA_ENVIRONMENT = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}
START_WAIT_SECONDS = 25.0
STOP_WAIT_SECONDS = 8.0
PROBE_INTERVAL = 0.5


def _windows_paths(*parts: str) -> tuple[str, ...]:
    roots = [os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", ""), os.path.expanduser("~")]
    return tuple(os.path.join(root, *parts) for root in roots if root)


@dataclass(frozen=True)
class LocalService:
    key: str
    name: str
    port: int
    start_args: tuple[str, ...]
    programs: tuple[str, ...]
    paths: tuple[str, ...] = ()
    stop_images: tuple[str, ...] = ()


SERVICES: tuple[LocalService, ...] = (
    LocalService(
        key="ollama", name="Ollama", port=11434, start_args=("serve",),
        programs=("ollama", "ollama.exe"),
        paths=(*_windows_paths("Programs", "Ollama", "ollama.exe"), "/usr/local/bin/ollama",
               "/opt/homebrew/bin/ollama", "/usr/bin/ollama"),
        # Erst die Tray-Anwendung (sie startet den Server sonst neu), dann der Server.
        stop_images=("ollama app.exe", "ollama.exe") if sys.platform == "win32" else ("ollama",),
    ),
    LocalService(
        key="lmstudio", name="LM Studio", port=1234, start_args=(),
        programs=("lms", "lms.exe"),
        paths=(*_windows_paths(".lmstudio", "bin", "lms.exe"), os.path.expanduser("~/.lmstudio/bin/lms")),
    ),
)


def in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_CONTAINER") == "1"


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _program(service: LocalService) -> str | None:
    for name in service.programs:
        if found := shutil.which(name):
            return found
    return next((path for path in service.paths if path and os.path.isfile(path)), None)


def _is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def detect(ollama_base_url: str) -> dict[str, object]:
    """Welche lokale KI läuft, welche liegt installiert bereit - und darf sie hier gesteuert werden?"""
    found: list[dict[str, object]] = []
    for service in SERVICES:
        program = _program(service)
        running = _port_open(service.port)
        if not program and not running:
            continue
        found.append({
            "key": service.key, "name": service.name, "port": service.port, "running": running,
            "installed": bool(program),
            "startable": bool(program) and not running and bool(service.start_args),
            "stoppable": running and bool(service.stop_images),
        })
    ollama = next((item for item in found if item["key"] == "ollama"), None)
    remote = not _is_local_url(ollama_base_url)
    if in_container():
        text = "Im Container läuft Ollama als eigener Dienst (docker compose) – Start und Stopp dort."
    elif remote:
        text = f"Ollama ist als entfernter Dienst konfiguriert ({urlsplit(ollama_base_url).netloc})."
    elif ollama and ollama["running"]:
        text = "Ollama läuft."
    elif ollama and ollama["startable"]:
        text = "Ollama ist installiert, läuft aber nicht."
    elif found:
        text = f"{found[0]['name']} gefunden – bitte die Anwendung öffnen."
    else:
        text = "Keine lokale KI gefunden. Ollama (ollama.com) installieren, dann erscheint hier der Startknopf."
    return {
        "services": found,
        "running": bool(ollama and ollama["running"]),
        "startable": bool(ollama and ollama["startable"]) and not remote and not in_container(),
        "stoppable": bool(ollama and ollama["stoppable"]) and not remote and not in_container(),
        "controllable": not remote and not in_container(),
        "text": text,
    }


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    for key, value in OLLAMA_ENVIRONMENT.items():
        env.setdefault(key, value)
    return env


def start_ollama(wait: float = START_WAIT_SECONDS) -> dict[str, object]:
    """Ollama lautlos im Hintergrund starten und auf den Port warten."""
    service = SERVICES[0]
    if in_container():
        return {"ok": False, "message": "Im Container wird Ollama über docker compose gestartet."}
    if _port_open(service.port):
        return {"ok": True, "already_running": True, "message": "Ollama lief bereits."}
    program = _program(service)
    if not program:
        return {"ok": False, "message": "Ollama ist auf diesem Rechner nicht installiert (ollama.com)."}
    kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL,
        "env": _environment(),
    }
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startup.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
        kwargs["startupinfo"] = startup
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    started = time.perf_counter()
    try:
        subprocess.Popen([program, *service.start_args], **kwargs)  # noqa: S603 - fester Aufruf
    except OSError as exc:
        return {"ok": False, "message": f"Ollama liess sich nicht starten ({exc.strerror or 'Systemfehler'})."}
    while time.perf_counter() - started < wait:
        if _port_open(service.port):
            return {"ok": True, "already_running": False, "seconds": round(time.perf_counter() - started, 1),
                    "message": "Ollama läuft jetzt (Flash Attention, 8-Bit-KV-Cache)."}
        time.sleep(PROBE_INTERVAL)
    return {"ok": False, "message": f"Ollama antwortet nach {wait:.0f} s noch nicht – beim ersten Start "
                                    "dauert das Laden länger, bitte gleich erneut prüfen."}


def _running(image: str) -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(  # noqa: S603, S607 - feste Systemwerkzeuge
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            return f'"{image.lower()}"' in (out.stdout or b"").decode("ascii", errors="ignore").lower()
        return subprocess.run(["pgrep", "-x", image], capture_output=True, timeout=10).returncode == 0  # noqa: S603, S607
    except (OSError, subprocess.SubprocessError):
        return False


def _kill(image: str) -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(  # noqa: S603, S607
                ["taskkill", "/F", "/T", "/IM", image], capture_output=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
        else:
            out = subprocess.run(["pkill", "-x", image], capture_output=True, timeout=15)  # noqa: S603, S607
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def stop_ollama(wait: float = STOP_WAIT_SECONDS) -> dict[str, object]:
    """Ollama beenden und den Grafikspeicher freigeben."""
    service = SERVICES[0]
    if in_container():
        return {"ok": False, "message": "Im Container wird Ollama über docker compose gestoppt."}
    if not _port_open(service.port):
        return {"ok": True, "message": "Ollama lief nicht."}
    for image in service.stop_images:
        if _running(image):
            _kill(image)
    started = time.perf_counter()
    while time.perf_counter() - started < wait:
        if not _port_open(service.port):
            return {"ok": True, "message": "Ollama ist gestoppt – der Grafikspeicher ist wieder frei."}
        time.sleep(PROBE_INTERVAL)
    return {"ok": False, "message": f"Ollama antwortet nach {wait:.0f} s noch – läuft der Dienst unter einem "
                                    "anderen Konto oder als Windows-Dienst?"}
