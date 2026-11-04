$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$portablePy = Join-Path $root "runtime\python\python.exe"
$launcher = Join-Path $root "start_scanner.py"

if (-not (Test-Path $portablePy)) {
    Write-Host "Portable Python not found at runtime\python\python.exe" -ForegroundColor Red
    Write-Host "Clone/download the full repository including the runtime folder."
    exit 1
}

Write-Host "Using portable Python:"
& $portablePy -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Portable Python failed to start." -ForegroundColor Red
    exit 1
}

& $portablePy -c "import fastapi,uvicorn,psutil,pydantic; print('runtime dependencies: OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Portable runtime is incomplete (missing Python modules)." -ForegroundColor Red
    Write-Host "Please re-download or git pull the latest repository contents."
    exit 1
}

Write-Host "Starting Wi-Fi Airspace Scanner on http://127.0.0.1:8765"
& $portablePy $launcher
exit $LASTEXITCODE

