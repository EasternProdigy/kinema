#!/usr/bin/env bash
# Kinema launcher for Linux / macOS.
#
# Starts Kinema and opens it in your browser. If Kinema is already running it
# just opens it again (the server handles that itself), so this is safe to
# double-click any time. All arguments pass through, e.g.:
#   ./kinema.sh --app                 # open in a dedicated Kinema window
#   ./kinema.sh --kiosk               # fullscreen cinema mode
#   ./kinema.sh --lan --password pw   # share on your home network
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" || exit 1

# Works as a source checkout (src/server.py) OR a release bundle (a self-contained
# `kinema` binary, no Python needed).
if [ -f "$DIR/src/server.py" ]; then
  PY="$(command -v python3 || command -v python || true)"
  if [ -z "$PY" ]; then
    echo "Python 3 is required but was not found."
    echo "Install it from https://www.python.org/downloads/ and try again."
    read -r -p "Press Enter to close..." _ || true
    exit 1
  fi
  exec "$PY" src/server.py "$@"
elif [ -x "$DIR/kinema" ]; then
  exec "$DIR/kinema" "$@"
elif command -v kinema >/dev/null 2>&1; then
  exec kinema "$@"
else
  echo "Could not find Kinema (neither src/server.py nor a kinema binary)."
  read -r -p "Press Enter to close..." _ || true
  exit 1
fi
