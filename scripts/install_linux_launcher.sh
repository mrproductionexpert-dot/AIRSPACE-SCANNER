#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER_DIR="$HOME/.local/share/applications"
LAUNCHER_PATH="$LAUNCHER_DIR/airspace-scanner.desktop"

mkdir -p "$LAUNCHER_DIR"
chmod +x "$ROOT_DIR/run.sh" "$ROOT_DIR/run-linux-gui.sh"

cat >"$LAUNCHER_PATH" <<EOF
[Desktop Entry]
Name=AIRSPACE Scanner
Comment=Hidden Wi-Fi Camera & Drone Detector
Type=Application
Terminal=false
Exec=$ROOT_DIR/run-linux-gui.sh
Path=$ROOT_DIR
Categories=Utility;Network;
StartupNotify=true
EOF

chmod +x "$LAUNCHER_PATH"
update-desktop-database "$LAUNCHER_DIR" >/dev/null 2>&1 || true

echo "Launcher installed:"
echo "  $LAUNCHER_PATH"
echo
echo "Open your app menu and search for: AIRSPACE Scanner"

