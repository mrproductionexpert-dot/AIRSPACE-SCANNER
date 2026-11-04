@echo off
setlocal
cd /d "%~dp0"
start "" /b powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0run.ps1"
endlocal
