#!/usr/bin/env bash
# Kadmu dev mode.
#   - Frontend (src/web/*): just edit and refresh the browser tab. No restart needed.
#   - Backend (src/server.py + src/kadmu/*.py): auto-restarts the server when you save.
# Any extra args pass through to src/server.py, e.g.:  ./dev.sh --lan
cd "$(dirname "$0")/.." || exit 1

PORT="${KADMU_PORT:-8000}"
PY="$(command -v python3 || command -v python)"

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }
# A signature over every backend file, so a change to any package module restarts.
backend_sig() { for f in src/server.py src/kadmu/*.py; do mtime "$f"; done; }

echo "Kadmu dev server on http://127.0.0.1:${PORT}  (Ctrl+C to stop)"
echo "Edit src/web/* -> just refresh the tab.  Edit src/server.py or src/kadmu/* -> auto-restarts."

cleanup() { [ -n "$PID" ] && kill "$PID" 2>/dev/null; exit 0; }
trap cleanup INT TERM

while true; do
  "$PY" src/server.py --port "$PORT" --no-open "$@" &
  PID=$!
  LAST="$(backend_sig)"
  while kill -0 "$PID" 2>/dev/null; do
    sleep 1
    NOW="$(backend_sig)"
    if [ "$NOW" != "$LAST" ]; then
      echo ">> backend changed — restarting..."
      kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
      break
    fi
  done
  # if the server died on its own (e.g. syntax error), wait for the next save
  if [ "$(backend_sig)" = "$LAST" ] && ! kill -0 "$PID" 2>/dev/null; then
    echo ">> server exited; waiting for the next save to the backend..."
    while [ "$(backend_sig)" = "$LAST" ]; do sleep 1; done
  fi
done
