@echo off
rem Beendet die von Start_Compliance_Agent.bat gestarteten Hintergrundprozesse.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop_Compliance_Agent.ps1" %*
ping -n 3 127.0.0.1 >nul
exit /b 0
