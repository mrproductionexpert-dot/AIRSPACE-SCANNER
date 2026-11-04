#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
if ./run.sh --background; then
  exit 0
fi

MSG="AIRSPACE Scanner failed to start.\n\nOpen logs/linux-scanner.log for details.\nYou can also run: ./run.sh"
echo -e "$MSG"
if command -v zenity >/dev/null 2>&1; then
  zenity --error --title="AIRSPACE Scanner" --text="$MSG" || true
fi
exit 1

