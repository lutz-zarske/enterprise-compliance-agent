@echo off
rem Beendet die von Start_Compliance_Agent.bat gestarteten Hintergrundprozesse.
setlocal

set "APP_DIR=%~dp0"
if exist "%APP_DIR%Stop_Compliance_Agent.ps1" (
    set "SKRIPT=%APP_DIR%Stop_Compliance_Agent.ps1"
    goto :found
)
if exist "%USERPROFILE%\dev\enterprise-compliance-agent\Stop_Compliance_Agent.ps1" (
    set "APP_DIR=%USERPROFILE%\dev\enterprise-compliance-agent"
    set "SKRIPT=%USERPROFILE%\dev\enterprise-compliance-agent\Stop_Compliance_Agent.ps1"
    goto :found
)

echo FEHLER: Stop_Compliance_Agent.ps1 fehlt im aktuellen Ordner und unter %USERPROFILE%\dev\enterprise-compliance-agent.
pause
exit /b 1

:found
cd /d "%APP_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SKRIPT%" %*
ping -n 3 127.0.0.1 >nul
exit /b 0
