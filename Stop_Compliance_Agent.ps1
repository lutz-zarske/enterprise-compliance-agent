<#
.SYNOPSIS
  Beendet die mit Start_Compliance_Agent.bat gestarteten Hintergrundprozesse (Backend und Frontend).
#>
param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 3001
)

$AppDir = $PSScriptRoot
$RunDir = Join-Path $AppDir ".run"
$beendet = 0

function Baum-Beenden([int]$prozessId, [string]$was) {
    if (-not (Get-Process -Id $prozessId -ErrorAction SilentlyContinue)) { return $false }
    & taskkill.exe /PID $prozessId /T /F *> $null
    Write-Host "Beendet: $was (PID $prozessId)" -ForegroundColor Green
    return $true
}

# 1. Beenden ueber PID-Dateien
foreach ($eintrag in @(@("backend.pid", "FastAPI Backend"), @("frontend.pid", "Next.js Frontend"))) {
    $datei = Join-Path $RunDir $eintrag[0]
    if (Test-Path $datei) {
        $prozessId = 0
        if ([int]::TryParse((Get-Content $datei -ErrorAction SilentlyContinue | Select-Object -First 1), [ref]$prozessId) -and $prozessId -gt 0) {
            if (Baum-Beenden $prozessId $eintrag[1]) { $beendet++ }
        }
        Remove-Item $datei -ErrorAction SilentlyContinue
    }
}

# 2. Beenden ueber Ports, falls manuell oder verwaist gestartet
foreach ($port in @($BackendPort, $FrontendPort)) {
    $verbindungen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($v in $verbindungen) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId = $($v.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        $kommando = [string]$p.CommandLine
        $passt = ($kommando -match "uvicorn" -and $kommando -match "app\.main") -or ($kommando -match "next" -and ($kommando -match "dev|start|next-server|next\\dist"))
        if ($passt -and (Baum-Beenden $p.ProcessId "Port $port ($($p.Name))")) { $beendet++ }
        elseif (-not $passt) {
            Write-Host "Port $port gehoert einem fremden Prozess ($($p.Name), PID $($p.ProcessId)) -- nicht angefasst." -ForegroundColor Yellow
        }
    }
}

if ($beendet -eq 0) {
    Write-Host "Kein laufender Enterprise Compliance Agent gefunden." -ForegroundColor Gray
} else {
    Write-Host "Enterprise Compliance Agent sauber beendet." -ForegroundColor Green
}
exit 0
