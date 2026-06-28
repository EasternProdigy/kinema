#!/usr/bin/env bash
# Kadmu launcher for Linux / macOS.
#
# Starts Kadmu and opens it in your browser. If Kadmu is already running it
# just opens it again (the server handles that itself), so this is safe to
# double-click any time. All arguments pass through, e.g.:
#   ./kadmu.sh --app                 # open in a dedicated Kadmu window
#   ./kadmu.sh --kiosk               # fullscreen cinema mode
#   ./kadmu.sh --lan --password pw   # share on your home network
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" || exit 1

# Works as a source checkout (src/server.py) OR a release bundle (a self-contained
# `kadmu` binary, no Python needed).
if [ -f "$DIR/src/server.py" ]; then
  PY="$(command -v python3 || command -v python || true)"
  if [ -z "$PY" ]; then
    echo "Python 3 is required but was not found."
    echo "Install it from https://www.python.org/downloads/ and try again."
    read -r -p "Press Enter to close..." _ || true
    exit 1
  fi
  exec "$PY" src/server.py "$@"
elif [ -x "$DIR/kadmu" ]; then
  exec "$DIR/kadmu" "$@"
elif command -v kadmu >/dev/null 2>&1; then
  exec kadmu "$@"
else
  echo "Could not find Kadmu (neither src/server.py nor a kadmu binary)."
  read -r -p "Press Enter to close..." _ || true
  exit 1
fi
