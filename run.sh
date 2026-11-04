#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MODE="${1:-foreground}"
if [[ "$MODE" != "foreground" && "$MODE" != "--background" ]]; then
  echo "Usage: ./run.sh [--background]"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ and retry."
  exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. Install NetworkManager (network-manager package)."
  exit 1
fi

mkdir -p "$ROOT_DIR/logs"
mkdir -p "$ROOT_DIR/.cache"

download_get_pip() {
  local target="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://bootstrap.pypa.io/get-pip.py" -o "$target" && return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q "https://bootstrap.pypa.io/get-pip.py" -O "$target" && return 0
  fi
  python3 - <<PY
import urllib.request
urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", r"$target")
PY
}

ensure_pip() {
  local py="$1"
  local install_mode="$2" # "venv" or "user"

  if "$py" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  "$py" -m ensurepip --upgrade >/dev/null 2>&1 || true
  if "$py" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  local gp="$ROOT_DIR/.cache/get-pip.py"
  download_get_pip "$gp"
  if [[ "$install_mode" == "user" ]]; then
    "$py" "$gp" --user >/dev/null
  else
    "$py" "$gp" >/dev/null
  fi
  "$py" -m pip --version >/dev/null 2>&1
}

check_health() {
  python3 - <<'PY' >/dev/null 2>&1
import urllib.request, sys
try:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=1.2) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

if check_health; then
  echo "Scanner is already running at http://127.0.0.1:8765"
  if [[ "$MODE" == "--background" ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:8765" >/dev/null 2>&1 || true
  fi
  exit 0
fi

PY_CMD=()
if python3 -c "import venv" >/dev/null 2>&1; then
  if [[ ! -x ".venv-linux/bin/python" ]]; then
    echo "Creating Linux virtual environment (.venv-linux)..."
    python3 -m venv .venv-linux
  fi
  PY_CMD=( ".venv-linux/bin/python" )
  if ! ensure_pip "${PY_CMD[0]}" "venv"; then
    echo "Failed to bootstrap pip inside .venv-linux."
    echo "Try: sudo apt install python3-venv python3-pip"
    exit 1
  fi
  "${PY_CMD[@]}" -m pip install --upgrade pip >/dev/null
  "${PY_CMD[@]}" -m pip install -r requirements.txt
else
  # No python3-venv available; use a project-local user site without sudo.
  export PYTHONUSERBASE="$ROOT_DIR/.pyuser"
  export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
  mkdir -p "$PYTHONUSERBASE"
  if ! ensure_pip "python3" "user"; then
    echo "Failed to bootstrap pip for user install mode."
    echo "Install one of these packages if possible: python3-pip or python3-venv"
    exit 1
  fi
  python3 -m pip install --user --upgrade pip >/dev/null
  python3 -m pip install --user -r requirements.txt
  export PATH="$PYTHONUSERBASE/bin:$PATH"
  PY_CMD=( "python3" )
fi

if [[ "$MODE" == "--background" ]]; then
  LOG_FILE="$ROOT_DIR/logs/linux-scanner.log"
  nohup "${PY_CMD[@]}" -m app.main >"$LOG_FILE" 2>&1 &
  for _ in $(seq 1 50); do
    if check_health; then
      echo "Scanner started in background at http://127.0.0.1:8765"
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:8765" >/dev/null 2>&1 || true
      fi
      exit 0
    fi
    sleep 0.2
  done
  echo "Scanner did not become ready. Check logs/linux-scanner.log"
  exit 1
fi

echo "Starting Wi-Fi Airspace Scanner on http://127.0.0.1:8765"
exec "${PY_CMD[@]}" -m app.main

