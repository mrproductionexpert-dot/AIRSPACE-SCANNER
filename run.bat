@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if errorlevel 1 (
  echo.
  echo Scanner startup failed.
  echo Press any key to close this window.
  pause >nul
)
endlocal
