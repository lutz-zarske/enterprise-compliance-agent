<#
.SYNOPSIS
  Beendet die mit Start_Compliance_Agent.bat gestarteten Hintergrundprozesse (Backend und Frontend).
#>
param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 3001
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null
$ProgressPreference = "SilentlyContinue"

$AppDir = $PSScriptRoot
$RunDir = Join-Path $AppDir ".run"
$beendet = 0

function Baum-Beenden([int]$prozessId, [string]$was) {
    if (-not (Get-Process -Id $prozessId -ErrorAction SilentlyContinue)) { return $false }
    & taskkill.exe /PID $prozessId /T /F *> $null
    Write-Host "Beendet: $was (PID $prozessId)" -ForegroundColor Green
    return $true
}

function Ist-Eigener-Prozess([int]$prozessId, [string]$muster) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId = $prozessId" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $cmd = [string]$p.CommandLine
    return ($cmd -match $muster)
}

# 1. Beenden über PID-Dateien (nur wenn die Kommandozeile zum eigenen Prozess passt)
foreach ($eintrag in @(
    @("backend.pid", "FastAPI Backend", "uvicorn.*app\.main"),
    @("frontend.pid", "Next.js Frontend", "(next|npm).*(start|dev|next-server|next\\dist)")
)) {
    $datei = Join-Path $RunDir $eintrag[0]
    if (Test-Path $datei) {
        $prozessId = 0
        if ([int]::TryParse((Get-Content $datei -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$prozessId) -and $prozessId -gt 0) {
            if (Ist-Eigener-Prozess $prozessId $eintrag[2]) {
                if (Baum-Beenden $prozessId $eintrag[1]) { $beendet++ }
            }
        }
        Remove-Item $datei -ErrorAction SilentlyContinue
    }
}

# 2. Beenden über Ports, falls manuell oder verwaist gestartet
foreach ($port in @($BackendPort, $FrontendPort)) {
    $verbindungen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($v in $verbindungen) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $($v.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        $kommando = [string]$p.CommandLine
        $passt = ($kommando -match "uvicorn" -and $kommando -match "app\.main") -or ($kommando -match "next" -and ($kommando -match "dev|start|next-server|next\\dist"))
        if ($passt -and (Baum-Beenden $p.ProcessId "Port $port ($($p.Name))")) { $beendet++ }
        elseif (-not $passt) {
            Write-Host "Port $port gehört einem fremden Prozess ($($p.Name), PID $($p.ProcessId)) -- nicht angefasst." -ForegroundColor Yellow
        }
    }
}

if ($beendet -eq 0) {
    Write-Host "Kein laufender Enterprise Compliance Agent gefunden." -ForegroundColor Gray
} else {
    Write-Host "Enterprise Compliance Agent sauber beendet." -ForegroundColor Green
}
exit 0
