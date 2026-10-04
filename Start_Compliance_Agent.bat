@echo off
rem Enterprise Compliance Agent mit einem Klick starten (Backend + Frontend im Hintergrund, Browser erst bei Bereitschaft).
setlocal
set "SKRIPT=%~dp0Start_Compliance_Agent.ps1"
if not exist "%SKRIPT%" (
    echo FEHLER: Start_Compliance_Agent.ps1 fehlt neben Start_Compliance_Agent.bat.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SKRIPT%" %*
if errorlevel 1 (
    echo.
    echo Start fehlgeschlagen - Hinweise siehe oben.
    pause
    exit /b 1
)
exit /b 0
