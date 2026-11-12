@echo off
rem Enterprise Compliance Agent mit einem Klick starten (Backend + Frontend im Hintergrund, Browser erst bei Bereitschaft).
setlocal

set "APP_DIR=%~dp0"
if exist "%APP_DIR%Start_Compliance_Agent.ps1" (
    set "SKRIPT=%APP_DIR%Start_Compliance_Agent.ps1"
    goto :found
)
if exist "%USERPROFILE%\dev\enterprise-compliance-agent\Start_Compliance_Agent.ps1" (
    set "APP_DIR=%USERPROFILE%\dev\enterprise-compliance-agent"
    set "SKRIPT=%USERPROFILE%\dev\enterprise-compliance-agent\Start_Compliance_Agent.ps1"
    goto :found
)

echo FEHLER: Start_Compliance_Agent.ps1 fehlt im aktuellen Ordner und unter %USERPROFILE%\dev\enterprise-compliance-agent.
pause
exit /b 1

:found
cd /d "%APP_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SKRIPT%" %*
if errorlevel 1 (
    echo.
    echo Start fehlgeschlagen - Hinweise siehe oben.
    pause
    exit /b 1
)
exit /b 0
