@echo off
REM ---------------------------------------------------------------------------
REM Enterprise Compliance Agent - Ein-Klick-Start fuer Windows
REM   Backend  : http://localhost:8001  (Swagger: /docs)
REM   Frontend : http://localhost:3001
REM Voraussetzungen: Python 3.11+ und Node.js 20+ im PATH.
REM Ollama ist optional - die Musterdaten funktionieren ohne Sprachmodell.
REM ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Python wurde nicht gefunden. Bitte Python 3.11+ installieren: https://www.python.org/downloads/
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] Node.js/npm wurde nicht gefunden. Bitte Node.js 20+ installieren: https://nodejs.org/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Lege virtuelle Python-Umgebung an ...
  python -m venv .venv || goto :error
)
echo [2/4] Pruefe Python-Abhaengigkeiten ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error

if not exist "frontend\node_modules" (
  echo [3/4] Installiere Frontend-Abhaengigkeiten ^(einmalig, ca. 1 Minute^) ...
  pushd frontend
  call npm ci --no-audit --no-fund || (popd & goto :error)
  popd
) else (
  echo [3/4] Frontend-Abhaengigkeiten vorhanden.
)

REM Ollama nur starten, wenn installiert und noch nicht erreichbar.
curl -s -o nul http://127.0.0.1:11434/api/tags
if errorlevel 1 (
  where ollama >nul 2>nul
  if not errorlevel 1 (
    echo       Starte Ollama im Hintergrundfenster ...
    start "Ollama" /min ollama serve
  ) else (
    echo       Hinweis: Ollama ist nicht installiert. Musterdaten, Zertifikat und Siegel funktionieren trotzdem;
    echo       fuer Live-Analysen Ollama installieren oder in der Oberflaeche einen Cloud-Provider waehlen.
  )
)

echo [4/4] Starte Backend (Port 8001) und Frontend (Port 3001) ...
start "Compliance Agent API :8001" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8001"
start "Compliance Agent UI :3001" cmd /k "cd /d frontend && npm run dev"

echo Warte auf den Start ...
timeout /t 8 /nobreak >nul
start "" http://localhost:3001
echo.
echo Laeuft. Zum Beenden die beiden Konsolenfenster schliessen.
echo Im Browser oben rechts "Musterdaten laden" klicken - funktioniert auch ohne KI-Modell.
endlocal
exit /b 0

:error
echo.
echo [FEHLER] Der Start ist fehlgeschlagen. Die Meldung oben nennt die Ursache.
pause
exit /b 1
