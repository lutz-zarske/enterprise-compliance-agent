<#
.SYNOPSIS
  Enterprise Compliance Agent schnell starten: Python/.venv + gecachter Next.js Production-Build,
  paralleler Start von Backend (:8001) und Frontend (:3001) sowie sofortiger Browser-Start.
#>
param(
    [switch]$NoBrowser,
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 3001,
    [int]$HealthTimeoutSeconds = 40,
    [int]$FrontendTimeoutSeconds = 60
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null
# PowerShell 5.1 blendet bei Invoke-WebRequest sonst je Anfrage einen blauen Fortschrittsbalken
# ein - im 250-ms-Takt flackert das Fenster. Ohne Fortschrittsanzeige ist die Abfrage zudem schneller.
$ProgressPreference = "SilentlyContinue"

$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$RunDir = Join-Path $AppDir ".run"
$LogDir = Join-Path $RunDir "logs"

if ($AppDir -match '\\OneDrive' -and $env:LOCALAPPDATA) {
    $LokalBasis = Join-Path $env:LOCALAPPDATA "EnterpriseComplianceAgent"
    $LogDir = Join-Path $LokalBasis "logs"
    $env:PYTHONPYCACHEPREFIX = Join-Path $LokalBasis "pycache"
    New-Item -ItemType Directory -Force -Path $env:PYTHONPYCACHEPREFIX | Out-Null
}
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Port-Belegt([int]$port) {
    try { return Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1 }
    catch { return $null }
}

function Http-Ok([string]$url, [int]$timeoutSec = 2) {
    try { return Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec }
    catch { return $null }
}

function Kill-Tree([int]$procId) {
    if (-not $procId) { return }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & taskkill.exe /PID $procId /T /F *> $null }
    catch {}
    finally { $ErrorActionPreference = $prev }
}

function Test-PyLauncher([string]$arg) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & py.exe $arg -c "exit(0)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
    finally { $ErrorActionPreference = $prev }
}

function Hash-Geaendert([string]$datei, [string]$marker) {
    $neu = (Get-FileHash -Algorithm SHA256 -Path $datei).Hash
    $alt = if (Test-Path $marker) { (Get-Content $marker -ErrorAction SilentlyContinue | Select-Object -First 1) } else { "" }
    return @{ Geaendert = ($neu -ne $alt); Hash = $neu }
}

function Frontend-Build-Hash([string]$dir) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $items = New-Object System.Collections.Generic.List[string]
        foreach ($rel in @("package.json", "package-lock.json", "next.config.ts", "tsconfig.json")) {
            $full = Join-Path $dir $rel
            if (Test-Path $full) { $items.Add($full) }
        }
        foreach ($sub in @("src", "public")) {
            $root = Join-Path $dir $sub
            if (Test-Path $root) {
                Get-ChildItem -Path $root -Recurse -File | Sort-Object FullName | ForEach-Object { $items.Add($_.FullName) }
            }
        }
        $sb = New-Object System.Text.StringBuilder
        foreach ($f in $items) {
            $h = (Get-FileHash -Algorithm SHA256 -Path $f).Hash
            [void]$sb.Append($f.Substring($dir.Length)).Append(":").Append($h).Append("`n")
        }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    } finally { $sha.Dispose() }
}

function Ensure-PortOwnOrFree([int]$port, [string]$cmdPattern, [bool]$stopIfOwned) {
    $conns = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($conns.Count -eq 0) { return $false }
    foreach ($conn in $conns) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        $cmd = [string]$p.CommandLine
        if ($cmd -notmatch $cmdPattern) {
            Write-Host "FEHLER: Port $port ist durch einen fremden Prozess belegt ($($p.Name), PID $($p.ProcessId))." -ForegroundColor Red
            exit 1
        }
        if ($stopIfOwned) { Kill-Tree $p.ProcessId }
    }
    if ($stopIfOwned) {
        for ($w = 0; $w -lt 25 -and (Port-Belegt $port); $w++) { Start-Sleep -Milliseconds 100 }
        return $false
    }
    return $true
}

function Box-Zeile([string]$text, [string]$farbe) { Write-Host ("   " + $text).PadRight(58) -ForegroundColor $farbe }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "             Enterprise Compliance Agent                  " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Python (.venv) und Abhängigkeiten prüfen
$VenvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[>] Lege Python-Umgebung (.venv) an..." -ForegroundColor Cyan
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $pyTarget = if (Test-PyLauncher "-3.12") { "-3.12" } elseif (Test-PyLauncher "-3.11") { "-3.11" } else { "-3" }
        & py.exe $pyTarget -m venv (Join-Path $AppDir ".venv")
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv (Join-Path $AppDir ".venv")
    } else {
        Write-Host "FEHLER: Python 3.11+ nicht gefunden (https://www.python.org/downloads/)." -ForegroundColor Red; exit 1
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Host "FEHLER: Python-Umgebung (.venv) konnte nicht angelegt werden." -ForegroundColor Red; exit 1
    }
}
$PythonExe = (Get-Item $VenvPython).FullName

$PyMarker = Join-Path $RunDir "requirements.sha256"
$py = Hash-Geaendert (Join-Path $AppDir "requirements.txt") $PyMarker
$paketeFehlen = $false
$prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
try { & $PythonExe -c "import uvicorn, fastapi" *> $null; if ($LASTEXITCODE -ne 0) { $paketeFehlen = $true } } catch { $paketeFehlen = $true }
finally { $ErrorActionPreference = $prevEap }

if ($py.Geaendert -or $paketeFehlen) {
    Write-Host "[>] Aktualisiere Python-Pakete..." -ForegroundColor Cyan
    & $PythonExe -m pip install --disable-pip-version-check --no-warn-script-location -q -r (Join-Path $AppDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { Write-Host "FEHLER: pip install fehlgeschlagen." -ForegroundColor Red; exit 1 }
    Set-Content -Path $PyMarker -Value $py.Hash -Encoding ascii
}

# 2. Node.js / npm und Frontend-Abhängigkeiten prüfen
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $npmCmd) { Write-Host "FEHLER: npm.cmd nicht gefunden (Node.js 20+ erforderlich)." -ForegroundColor Red; exit 1 }
$NpmExe = $npmCmd.Source

$FrontendDir = Join-Path $AppDir "frontend"
$NpmMarker = Join-Path $RunDir "package-lock.sha256"
$node = Hash-Geaendert (Join-Path $FrontendDir "package-lock.json") $NpmMarker
if ($node.Geaendert -or -not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "[>] Installiere Frontend-Pakete..." -ForegroundColor Cyan
    $NpmLog = Join-Path $LogDir "npm-setup.log"
    $NpmErrLog = Join-Path $LogDir "npm-setup.err.log"
    $npmProc = Start-Process -FilePath $NpmExe -ArgumentList @("install", "--silent", "--no-audit", "--no-fund") -WorkingDirectory $FrontendDir -NoNewWindow -PassThru -RedirectStandardOutput $NpmLog -RedirectStandardError $NpmErrLog
    $null = $npmProc.Handle; $npmProc.WaitForExit()
    if (Test-Path $NpmErrLog) { [System.IO.File]::AppendAllText($NpmLog, [System.IO.File]::ReadAllText($NpmErrLog)); Remove-Item $NpmErrLog -Force -ErrorAction SilentlyContinue }
    if ($npmProc.ExitCode -ne 0) { Write-Host "FEHLER: npm install fehlgeschlagen (Logs: $NpmLog)." -ForegroundColor Red; exit 1 }
    Set-Content -Path $NpmMarker -Value $node.Hash -Encoding ascii
}

# 3. Laufende veraltete Instanzen vor einem Rebuild sauber stoppen (verhindert EBUSY auf .next)
$TargetVersion = ""
$cfgText = Get-Content (Join-Path $AppDir "app\config.py") -Raw -ErrorAction SilentlyContinue
if ($cfgText -match 'APP_VERSION\s*=\s*"([^"]+)"') { $TargetVersion = $Matches[1] }

$BuildMarker = Join-Path $RunDir "frontend-build.sha256"
$BuildHash = Frontend-Build-Hash $FrontendDir
$PrevBuildHash = if (Test-Path $BuildMarker) { (Get-Content $BuildMarker -ErrorAction SilentlyContinue | Select-Object -First 1) } else { "" }
$BuildChanged = ($BuildHash -ne $PrevBuildHash) -or (-not (Test-Path (Join-Path $FrontendDir ".next\BUILD_ID")))

$BackendPattern = "uvicorn.*app\.main"
$FrontendPattern = "next.*(dev|start|next-server|next\\dist)"
$BackendActive = Ensure-PortOwnOrFree $BackendPort $BackendPattern $false
$ForceFrontendRestart = $false

if ($BackendActive) {
    $stale = $true
    $h = Http-Ok "http://127.0.0.1:$BackendPort/health" 2
    if ($h -and $TargetVersion) {
        try { if (($h.Content | ConvertFrom-Json).version -eq $TargetVersion) { $stale = $false } } catch {}
    } elseif ($h) { $stale = $false }
    if ($stale) {
        Write-Host "[>] Beende veraltete Backend-Instanz auf Port $BackendPort..." -ForegroundColor Yellow
        $BackendActive = Ensure-PortOwnOrFree $BackendPort $BackendPattern $true
        $ForceFrontendRestart = $true
    }
}

$FrontendActive = Ensure-PortOwnOrFree $FrontendPort $FrontendPattern ($BuildChanged -or $ForceFrontendRestart)
if ($FrontendActive -and (-not (Http-Ok "http://127.0.0.1:$FrontendPort" 2))) {
    Write-Host "[>] Beende nicht reagierendes Frontend auf Port $FrontendPort..." -ForegroundColor Yellow
    $FrontendActive = Ensure-PortOwnOrFree $FrontendPort $FrontendPattern $true
}

# 4. Gecachter Production-Build (falls geändert)
if ($BuildChanged) {
    Write-Host "[>] Erzeuge optimierten Production-Build (einmalig je Code-Stand)..." -ForegroundColor Cyan
    $BuildLog = Join-Path $LogDir "npm-build.log"
    $BuildErr = Join-Path $LogDir "npm-build.err.log"
    $bProc = Start-Process -FilePath $NpmExe -ArgumentList @("run", "build") -WorkingDirectory $FrontendDir -NoNewWindow -PassThru -RedirectStandardOutput $BuildLog -RedirectStandardError $BuildErr
    $null = $bProc.Handle; $bProc.WaitForExit()
    if (Test-Path $BuildErr) { [System.IO.File]::AppendAllText($BuildLog, [System.IO.File]::ReadAllText($BuildErr)); Remove-Item $BuildErr -Force -ErrorAction SilentlyContinue }
    if ($bProc.ExitCode -ne 0) {
        Write-Host "FEHLER: Frontend-Build fehlgeschlagen. Letzte Zeilen:" -ForegroundColor Red
        if (Test-Path $BuildLog) { Get-Content $BuildLog -Tail 12 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
        exit 1
    }
    Set-Content -Path $BuildMarker -Value $BuildHash -Encoding ascii
    Write-Host "[OK] Production-Build erstellt." -ForegroundColor Green
} else {
    Write-Host "[OK] Production-Build aktuell (Cache)." -ForegroundColor Green
}

# 5. Backend und Frontend parallel starten
$BackendErr = Join-Path $LogDir "backend.err.log"
$FrontendErr = Join-Path $LogDir "frontend.err.log"
$BackendProc = $null
$FrontendProc = $null

if ($BackendActive) {
    Write-Host "[x] Backend läuft bereits auf Port $BackendPort." -ForegroundColor Green
} else {
    Write-Host "[>] Starte Backend (FastAPI) auf Port $BackendPort" -ForegroundColor Cyan
    $BackendProc = Start-Process -FilePath $PythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") -WorkingDirectory $AppDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogDir "backend.log") -RedirectStandardError $BackendErr
    Set-Content -Path (Join-Path $RunDir "backend.pid") -Value $BackendProc.Id -Encoding ascii
}
if ($FrontendActive) {
    Write-Host "[x] Oberfläche läuft bereits auf Port $FrontendPort." -ForegroundColor Green
} else {
    Write-Host "[>] Starte Oberfläche (Next.js) auf Port $FrontendPort" -ForegroundColor Cyan
    $startArgs = @("run", "start")
    if ($FrontendPort -ne 3001) { $startArgs += @("--", "-p", "$FrontendPort") }
    $FrontendProc = Start-Process -FilePath $NpmExe -ArgumentList $startArgs -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogDir "frontend.log") -RedirectStandardError $FrontendErr
    Set-Content -Path (Join-Path $RunDir "frontend.pid") -Value $FrontendProc.Id -Encoding ascii
}

# 6. Gemeinsame Bereitschaftsprüfung (250 ms Takt, isolierte Fehlerzuordnung)
$BackendReady = $BackendActive
$FrontendReady = $FrontendActive
$BackendExited = $false
$FrontendExited = $false
$MaxTicks = [Math]::Max($HealthTimeoutSeconds, $FrontendTimeoutSeconds) * 4

for ($i = 0; $i -lt $MaxTicks -and (-not ($BackendReady -and $FrontendReady)); $i++) {
    if (-not $BackendReady -and -not $BackendExited) {
        if ($BackendProc -and -not (Get-Process -Id $BackendProc.Id -ErrorAction SilentlyContinue)) { $BackendExited = $true }
        else {
            $bh = Http-Ok "http://127.0.0.1:$BackendPort/health" 2
            if ($bh -and ($bh.StatusCode -eq 200 -or $bh.StatusCode -eq 503)) { $BackendReady = $true }
        }
    }
    if (-not $FrontendReady -and -not $FrontendExited) {
        if ($FrontendProc -and -not (Get-Process -Id $FrontendProc.Id -ErrorAction SilentlyContinue)) { $FrontendExited = $true }
        else {
            $fh = Http-Ok "http://127.0.0.1:$FrontendPort" 2
            if ($fh -and $fh.StatusCode -ge 200 -and $fh.StatusCode -lt 400) { $FrontendReady = $true }
        }
    }
    if ($BackendExited -and $FrontendExited) { break }
    if ($BackendExited -and -not $FrontendReady -and -not $FrontendProc) { break }
    if ($FrontendExited -and -not $BackendReady -and -not $BackendProc) { break }
    if (-not ($BackendReady -and $FrontendReady)) { Start-Sleep -Milliseconds 250 }
}

if (-not $BackendReady -or -not $FrontendReady) {
    if ($BackendProc) { Kill-Tree $BackendProc.Id }
    if ($FrontendProc) { Kill-Tree $FrontendProc.Id }
    if (-not $BackendReady) {
        Write-Host "FEHLER: Backend antwortet nicht (Log: $BackendErr)." -ForegroundColor Red
        if (Test-Path $BackendErr) { Get-Content $BackendErr -Tail 8 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    }
    if (-not $FrontendReady) {
        Write-Host "FEHLER: Frontend antwortet nicht (Log: $FrontendErr)." -ForegroundColor Red
        if (Test-Path $FrontendErr) { Get-Content $FrontendErr -Tail 8 | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow } }
    }
    exit 1
}

Write-Host "[OK] Backend bereit (http://127.0.0.1:$BackendPort)" -ForegroundColor Green
Write-Host "[OK] Oberfläche bereit (http://127.0.0.1:$FrontendPort)" -ForegroundColor Green

$ver = if ($TargetVersion) { " v$TargetVersion" } else { "" }
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Box-Zeile "Enterprise Compliance Agent$ver ist bereit" Green
Box-Zeile "URL:     http://127.0.0.1:$FrontendPort" Green
Box-Zeile "Logs:    $LogDir" DarkGray
Box-Zeile "Beenden: Stop_Compliance_Agent.bat" DarkGray
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
# Kurze Lesepause für die Statusbox, danach schließt sich das Fenster von selbst.
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$FrontendPort"; Start-Sleep -Seconds 2 }
exit 0
