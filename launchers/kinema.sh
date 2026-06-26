#!/usr/bin/env bash
# Kinema launcher for Linux / macOS.
# Starts the local server and opens Kinema in your browser.
# Any arguments are passed straight through to server.py, e.g.:
#   ./kinema.sh --lan --password hunter2
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "Python 3 is required but was not found."
  echo "Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close..." _ || true
  exit 1
fi

exec "$PY" server.py "$@"
