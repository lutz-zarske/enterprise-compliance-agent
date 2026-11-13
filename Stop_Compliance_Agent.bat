@echo off
rem Beendet die von Start_Compliance_Agent.bat gestarteten Hintergrundprozesse.
setlocal

rem Kopien ausserhalb des Projekts finden es ueber ECA_HOME oder am ueblichen Ort (siehe Start_Compliance_Agent.bat).
if not defined ECA_HOME set "ECA_HOME=%USERPROFILE%\dev\enterprise-compliance-agent"

set "APP_DIR=%~dp0"
if exist "%APP_DIR%Stop_Compliance_Agent.ps1" (
    set "SKRIPT=%APP_DIR%Stop_Compliance_Agent.ps1"
    goto :found
)
if exist "%ECA_HOME%\Stop_Compliance_Agent.ps1" (
    set "APP_DIR=%ECA_HOME%"
    set "SKRIPT=%ECA_HOME%\Stop_Compliance_Agent.ps1"
    goto :found
)

echo FEHLER: Stop_Compliance_Agent.ps1 fehlt im aktuellen Ordner und unter %ECA_HOME%.
pause
exit /b 1

:found
cd /d "%APP_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SKRIPT%" %*
ping -n 3 127.0.0.1 >nul
exit /b 0
