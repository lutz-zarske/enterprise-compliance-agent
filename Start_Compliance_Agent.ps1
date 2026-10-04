<#
.SYNOPSIS
  Enterprise Compliance Agent mit 1 Klick starten: Backend (FastAPI, Port 8001) und
  Frontend (Next.js, Port 3001) im Hintergrund starten, auf Bereitschaft pruefen und
  erst danach http://localhost:3001 im Standard-Browser oeffnen.
#>
param(
    [switch]$NoBrowser,
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 3001,
    [int]$HealthTimeoutSeconds = 40,
    [int]$FrontendTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$RunDir = Join-Path $AppDir ".run"
$LogDir = Join-Path $RunDir "logs"
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
Write-Host "   Enterprise Compliance Agent -- Institutional Launcher   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Voraussetzungen pruefen
$VenvItem = Get-Item (Join-Path $AppDir ".venv\Scripts\python.exe") -ErrorAction SilentlyContinue
if (-not $VenvItem) {
    Write-Host "FEHLER: Python Virtual Environment (.venv) nicht gefunden unter: .venv\Scripts\python.exe" -ForegroundColor Red
    exit 1
}
$PythonExe = $VenvItem.FullName

$FrontendDir = Join-Path $AppDir "frontend"
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "Installiere Frontend-Abhaengigkeiten (npm install)..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    try {
        & npm.cmd install
    } finally {
        Pop-Location
    }
}

$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $npmCmd) {
    Write-Host "FEHLER: npm.cmd wurde nicht gefunden." -ForegroundColor Red
    exit 1
}
$NpmExe = $npmCmd.Source

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
    
    Write-Host "    Pruefe Backend-Bereitschaft (/health)..." -ForegroundColor DarkGray
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
    $proc = Start-Process -FilePath $NpmExe `
        -ArgumentList @("run", "dev", "--", "-p", "$FrontendPort") `
        -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErr
    Set-Content -Path $FrontendPidFile -Value $proc.Id -Encoding ascii
    
    Write-Host "    Pruefe Frontend-Bereitschaft (Port $FrontendPort)..." -ForegroundColor DarkGray
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

# 4. Ollama Status pruefen
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "[OK] Lokale Ollama-Engine ist aktiv." -ForegroundColor Green
} catch {
    Write-Host "[i] Hinweis: Lokale Ollama-Engine ist nicht aktiv." -ForegroundColor Yellow
    Write-Host "    (Fuer lokale 14B-Inferenz bei Bedarf 'ollama serve' starten." -ForegroundColor DarkGray
    Write-Host "     Cloud-Modelle [Gemini/Claude/GPT] sowie Musterdaten-Audits funktionieren sofort.)" -ForegroundColor DarkGray
}

# 5. Browser oeffnen
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "   Enterprise Compliance Agent ist vollstaendig online!   " -ForegroundColor Green
Write-Host "   URL: http://localhost:$FrontendPort                     " -ForegroundColor Green
Write-Host "   Beenden: Stop_Compliance_Agent.bat                     " -ForegroundColor DarkGray
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

if (-not $NoBrowser) {
    Start-Process "http://localhost:$FrontendPort"
}

Start-Sleep -Seconds 1
exit 0
