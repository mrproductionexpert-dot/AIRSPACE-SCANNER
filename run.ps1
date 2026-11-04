$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSCommandPath
$portablePy = Join-Path $root "runtime\python\python.exe"
$launcher = Join-Path $root "start_scanner.py"
$appUrl = "http://127.0.0.1:8765"

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

try {
    # If already running, just open the UI.
    $existing = Invoke-WebRequest -Uri "$appUrl/api/health" -UseBasicParsing -TimeoutSec 1
    if ($existing.StatusCode -eq 200) {
        Start-Process $appUrl | Out-Null
        exit 0
    }
} catch {}

$quotedLauncher = '"' + $launcher + '"'
$proc = Start-Process -FilePath $portablePy -ArgumentList @($quotedLauncher) -WorkingDirectory $root -WindowStyle Hidden -PassThru
if (-not $proc) {
    Write-Host "Failed to start scanner process." -ForegroundColor Red
    exit 1
}

# Wait briefly for server readiness, then open browser automatically.
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 300
    if ($proc.HasExited) {
        break
    }
    try {
        $health = Invoke-WebRequest -Uri "$appUrl/api/health" -UseBasicParsing -TimeoutSec 1
        if ($health.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
}

if ($ready) {
    Start-Process $appUrl | Out-Null
    exit 0
}

if ($proc.HasExited) {
    Write-Host "Scanner process exited early. Run '.\runtime\python\python.exe .\start_scanner.py' for diagnostics." -ForegroundColor Red
    exit 1
}

# Server may still be warming up; open UI anyway.
Start-Process $appUrl | Out-Null
exit 0

