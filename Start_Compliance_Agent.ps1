<#
.SYNOPSIS
  Enterprise Compliance Agent mit 1 Klick starten: Backend (FastAPI, Port 8001) und
  Frontend (Next.js, Port 3001) im Hintergrund starten, auf Bereitschaft prüfen und
  erst danach http://127.0.0.1:3001 im Standard-Browser öffnen.
#>
param(
    [switch]$NoBrowser,
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 3001,
    [int]$HealthTimeoutSeconds = 40,
    [int]$FrontendTimeoutSeconds = 60
)

# Saubere Umlaute in der Konsole (die Datei selbst ist UTF-8 mit BOM gespeichert,
# sonst liest Windows PowerShell 5.1 sie als ANSI).
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$RunDir = Join-Path $AppDir ".run"
$LogDir = Join-Path $RunDir "logs"

# Liegt das Projekt in einem OneDrive-Ordner (z. B. auf einem Zweitrechner), wandern
# Logs und Python-Bytecode nach %LOCALAPPDATA%: Sonst synchronisiert OneDrive bei jedem
# Start Hunderte kurzlebiger Dateien. Die PID-Dateien bleiben in .run (Stop-Skript).
if ($AppDir -match '\\OneDrive' -and $env:LOCALAPPDATA) {
    $LokalBasis = Join-Path $env:LOCALAPPDATA "EnterpriseComplianceAgent"
    $LogDir = Join-Path $LokalBasis "logs"
    $env:PYTHONPYCACHEPREFIX = Join-Path $LokalBasis "pycache"
    New-Item -ItemType Directory -Force -Path $env:PYTHONPYCACHEPREFIX | Out-Null
}
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Schreibe([string]$text, [string]$farbe = "Gray") { Write-Host $text -ForegroundColor $farbe }

function Port-Belegt([int]$port) {
    try {
        $verb = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1
        return $verb
    } catch {
        return $null
    }
}

function Http-Ok([string]$url, [int]$timeoutSec = 3) {
    try {
        $antwort = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
        return $antwort
    } catch {
        return $null
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Enterprise Compliance Agent Launcher   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Voraussetzungen prüfen und Abhängigkeiten aktuell halten
#    Abgleich über Datei-Hashes: Nach einem git pull mit neuen Paketen
#    (z. B. cryptography, Schriftpakete) wird automatisch nachinstalliert.
function Hash-Geaendert([string]$datei, [string]$marker) {
    $neu = (Get-FileHash -Algorithm SHA256 -Path $datei).Hash
    $alt = if (Test-Path $marker) { (Get-Content $marker -ErrorAction SilentlyContinue | Select-Object -First 1) } else { "" }
    return @{ Geaendert = ($neu -ne $alt); Hash = $neu }
}

$VenvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[>] Lege Python-Umgebung (.venv) an (einmalig)..." -ForegroundColor Cyan
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        # Bevorzuge stabile Python-Versionen (3.12 / 3.11), fuer die fertige pre-built Wheels existieren
        $pyTarget = "-3"
        try {
            & py.exe -3.12 -c "exit(0)" 2>$null
            if ($LASTEXITCODE -eq 0) { $pyTarget = "-3.12" }
            else {
                & py.exe -3.11 -c "exit(0)" 2>$null
                if ($LASTEXITCODE -eq 0) { $pyTarget = "-3.11" }
            }
        } catch {}
        & py.exe $pyTarget -m venv (Join-Path $AppDir ".venv")
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv (Join-Path $AppDir ".venv")
    } else {
        Write-Host "FEHLER: Python 3.11+ wurde nicht gefunden (https://www.python.org/downloads/)." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Host "FEHLER: Die Python-Umgebung konnte nicht angelegt werden." -ForegroundColor Red
        exit 1
    }
}
$PythonExe = (Get-Item $VenvPython).FullName

$PyMarker = Join-Path $RunDir "requirements.sha256"
$py = Hash-Geaendert (Join-Path $AppDir "requirements.txt") $PyMarker
$paketeFehlen = $false
try {
    & $PythonExe -c "import uvicorn, fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) { $paketeFehlen = $true }
} catch { $paketeFehlen = $true }

if ($py.Geaendert -or $paketeFehlen) {
    Write-Host "[>] Installiere bzw. aktualisiere Python-Abhängigkeiten..." -ForegroundColor Cyan
    & $PythonExe -m pip install --disable-pip-version-check --no-warn-script-location -q -r (Join-Path $AppDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FEHLER: pip install ist fehlgeschlagen (siehe Ausgabe oben)." -ForegroundColor Red
        exit 1
    }
    Set-Content -Path $PyMarker -Value $py.Hash -Encoding ascii
}

$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $npmCmd) {
    Write-Host "FEHLER: npm.cmd wurde nicht gefunden. Bitte Node.js 20+ installieren (https://nodejs.org/)." -ForegroundColor Red
    exit 1
}
$NpmExe = $npmCmd.Source

$FrontendDir = Join-Path $AppDir "frontend"
$NpmMarker = Join-Path $RunDir "package-lock.sha256"
$node = Hash-Geaendert (Join-Path $FrontendDir "package-lock.json") $NpmMarker
if ($node.Geaendert -or -not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    # Ruhige Konsole: Die npm-Ausgabe (inkl. "npm warn ...") landet im Log, nicht im Fenster.
    $NpmLog = Join-Path $LogDir "npm-setup.log"
    $NpmErrLog = Join-Path $LogDir "npm-setup.err.log"
    Write-Host "[>] Installiere bzw. aktualisiere Frontend-Abhängigkeiten (npm install, 1-3 Minuten)..." -ForegroundColor Cyan
    $npmProc = Start-Process -FilePath $NpmExe `
        -ArgumentList @("install", "--silent", "--no-audit", "--no-fund") `
        -WorkingDirectory $FrontendDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $NpmLog -RedirectStandardError $NpmErrLog
    $null = $npmProc.Handle   # ohne Handle bleibt ExitCode unter PowerShell 5.1 leer
    $npmProc.WaitForExit()
    $npmExit = $npmProc.ExitCode
    if (Test-Path $NpmErrLog) {
        [System.IO.File]::AppendAllText($NpmLog, [System.IO.File]::ReadAllText($NpmErrLog))
        Remove-Item $NpmErrLog -Force -ErrorAction SilentlyContinue
    }
    if ($npmExit -ne 0) {
        Write-Host "FEHLER: npm install ist fehlgeschlagen (Exit-Code $npmExit)." -ForegroundColor Red
        Write-Host "       Protokoll: $NpmLog" -ForegroundColor Yellow
        if (Test-Path $NpmLog) { Get-Content $NpmLog -Tail 10 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
        exit 1
    }
    Set-Content -Path $NpmMarker -Value $node.Hash -Encoding ascii
}

# 2. Backend starten
$BackendLog = Join-Path $LogDir "backend.log"
$BackendErr = Join-Path $LogDir "backend.err.log"
$BackendPidFile = Join-Path $RunDir "backend.pid"

$backendBereit = $false
if (Port-Belegt $BackendPort) {
    Write-Host "[x] Port $BackendPort ist bereits aktiv -- verwende laufende Instanz." -ForegroundColor Green
    $backendBereit = $true
} else {
    Write-Host "[>] Starte FastAPI Compliance Backend auf Port $BackendPort..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $AppDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErr
    Set-Content -Path $BackendPidFile -Value $proc.Id -Encoding ascii
    
    Write-Host "    Prüfe Backend-Bereitschaft (/health)..." -ForegroundColor DarkGray
    $versuche = [Math]::Max(1, [int]($HealthTimeoutSeconds * 2))
    for ($i = 0; $i -lt $versuche; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
        $h = Http-Ok "http://127.0.0.1:$BackendPort/health" 3
        if ($h -and ($h.StatusCode -eq 200 -or $h.StatusCode -eq 503)) {
            $backendBereit = $true
            break
        }
    }
}

if (-not $backendBereit) {
    Write-Host "FEHLER: Backend antwortet nicht innerhalb von $HealthTimeoutSeconds Sekunden." -ForegroundColor Red
    if (Test-Path $BackendErr) { Get-Content $BackendErr -Tail 10 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    exit 1
}
Write-Host "[OK] Backend ist bereit (http://127.0.0.1:$BackendPort/health)." -ForegroundColor Green

# 3. Frontend starten
$FrontendLog = Join-Path $LogDir "frontend.log"
$FrontendErr = Join-Path $LogDir "frontend.err.log"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"

$frontendBereit = $false
if (Port-Belegt $FrontendPort) {
    Write-Host "[x] Port $FrontendPort ist bereits aktiv -- verwende laufendes Frontend." -ForegroundColor Green
    $frontendBereit = $true
} else {
    Write-Host "[>] Starte Next.js Compliance Frontend auf Port $FrontendPort..." -ForegroundColor Cyan
    # "dev" setzt in package.json bereits -p 3001; nur ein abweichender Port wird angehängt.
    $devArgs = @("run", "dev")
    if ($FrontendPort -ne 3001) { $devArgs += @("--", "-p", "$FrontendPort") }
    $proc = Start-Process -FilePath $NpmExe `
        -ArgumentList $devArgs `
        -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErr
    Set-Content -Path $FrontendPidFile -Value $proc.Id -Encoding ascii
    
    Write-Host "    Prüfe Frontend-Bereitschaft (Port $FrontendPort)..." -ForegroundColor DarkGray
    $versuche = [Math]::Max(1, [int]($FrontendTimeoutSeconds * 2))
    for ($i = 0; $i -lt $versuche; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { break }
        $h = Http-Ok "http://127.0.0.1:$FrontendPort" 2
        if ($h -and $h.StatusCode -ge 200 -and $h.StatusCode -lt 400) {
            $frontendBereit = $true
            break
        }
    }
}

if (-not $frontendBereit) {
    Write-Host "FEHLER: Frontend antwortet nicht innerhalb von $FrontendTimeoutSeconds Sekunden." -ForegroundColor Red
    if (Test-Path $FrontendErr) { Get-Content $FrontendErr -Tail 10 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    exit 1
}
Write-Host "[OK] Frontend ist bereit (http://127.0.0.1:$FrontendPort)." -ForegroundColor Green

# Den Status der lokalen KI zeigt die Oberfläche (Hinweis "Lokale KI aus" mit Start-Knopf).

# 4. Browser öffnen (127.0.0.1 statt localhost: Windows löst localhost zuerst nach ::1 auf)
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   Enterprise Compliance Agent ist vollständig online!   " -ForegroundColor Green
Write-Host "   URL: http://127.0.0.1:$FrontendPort                     " -ForegroundColor Green
Write-Host "   Logs: $LogDir" -ForegroundColor DarkGray
Write-Host "   Beenden: Stop_Compliance_Agent.bat                     " -ForegroundColor DarkGray
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}

# Das grüne [OK] noch 3 Sekunden sichtbar lassen, bevor sich das Fenster schließt.
Start-Sleep -Seconds 3
exit 0
