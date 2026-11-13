@echo off
rem Enterprise Compliance Agent mit einem Klick starten (Backend + Frontend im Hintergrund, Browser erst bei Bereitschaft).
setlocal

rem Liegt eine Kopie dieser Datei ausserhalb des Projekts (z. B. auf dem Desktop), wird das
rem Projekt ueber ECA_HOME oder am ueblichen Ort %USERPROFILE%\dev\enterprise-compliance-agent gesucht.
if not defined ECA_HOME set "ECA_HOME=%USERPROFILE%\dev\enterprise-compliance-agent"

set "APP_DIR=%~dp0"
if exist "%APP_DIR%Start_Compliance_Agent.ps1" (
    set "SKRIPT=%APP_DIR%Start_Compliance_Agent.ps1"
    goto :found
)
if exist "%ECA_HOME%\Start_Compliance_Agent.ps1" (
    set "APP_DIR=%ECA_HOME%"
    set "SKRIPT=%ECA_HOME%\Start_Compliance_Agent.ps1"
    goto :found
)

echo FEHLER: Start_Compliance_Agent.ps1 fehlt im aktuellen Ordner und unter %ECA_HOME%.
echo Projektordner per Umgebungsvariable ECA_HOME angeben oder die Datei im Projektordner starten.
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
