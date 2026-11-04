#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ and retry."
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. Install NetworkManager (network-manager package)."
  exit 1
fi

if [[ ! -d ".venv-linux" ]]; then
  echo "Creating Linux virtual environment (.venv-linux)..."
  python3 -m venv .venv-linux
fi

source .venv-linux/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo "Starting Wi-Fi Airspace Scanner on http://127.0.0.1:8765"
python -m app.main

