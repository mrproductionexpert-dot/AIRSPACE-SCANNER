# Rebuild runtime\python (Windows amd64 embeddable + app deps).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root 'runtime'
$pyDir = Join-Path $runtime 'python'
$zip = Join-Path $runtime 'python-embed.zip'

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (Test-Path $pyDir) { Remove-Item -Recurse -Force $pyDir }

$url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
Write-Host "Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $pyDir -Force
Remove-Item $zip -Force

$pth = Get-ChildItem $pyDir -Filter 'python*._pth' | Select-Object -First 1
@"
python312.zip
.
Lib\site-packages
import site
"@ | Set-Content -Path $pth.FullName -Encoding ASCII

$getPip = Join-Path $runtime 'get-pip.py'
Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
& (Join-Path $pyDir 'python.exe') $getPip --no-warn-script-location
Remove-Item $getPip -Force

& (Join-Path $pyDir 'python.exe') -m pip install --no-warn-script-location -r (Join-Path $root 'requirements.txt')
Get-ChildItem -Path $pyDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -Path $pyDir -Recurse -File -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force
& (Join-Path $pyDir 'python.exe') -c "import fastapi, uvicorn, psutil, pydantic, sys; print('ok', sys.version)"
