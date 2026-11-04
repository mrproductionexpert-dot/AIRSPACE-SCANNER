@echo off
setlocal
cd /d "%~dp0"

set "PORTABLE_PY=%~dp0runtime\python\python.exe"

if not exist "%PORTABLE_PY%" (
  echo Portable Python not found at runtime\python\python.exe
  echo Clone/download the full repository including the runtime folder.
  pause
  exit /b 1
)

echo Using portable Python:
"%PORTABLE_PY%" -c "import sys; print(sys.version)"
if errorlevel 1 (
  echo Portable Python failed to start.
  pause
  exit /b 1
)

REM Do not depend on pip at runtime. Just verify required modules exist.
"%PORTABLE_PY%" -c "import fastapi,uvicorn,psutil,pydantic; print('runtime dependencies: OK')"
if errorlevel 1 (
  echo Portable runtime is incomplete (missing Python modules).
  echo Please re-download or git pull the latest repository contents.
  pause
  exit /b 1
)

echo.
echo Starting Wi-Fi Airspace Scanner at http://127.0.0.1:8765
echo Plug in a USB Wi-Fi adapter (e.g. WNP-UA1300-02), or enable Simulation Mode.
echo.
start "" "http://127.0.0.1:8765"
"%PORTABLE_PY%" -m app.main
endlocal
