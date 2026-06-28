#!/usr/bin/env bash
# Kadmu dev mode.
#   - Frontend (src/web/*): just edit and refresh the browser tab. No restart needed.
#   - Backend (src/server.py): this script auto-restarts the server when you save it.
# Any extra args pass through to src/server.py, e.g.:  ./dev.sh --lan
cd "$(dirname "$0")/.." || exit 1

PORT="${KADMU_PORT:-8000}"
PY="$(command -v python3 || command -v python)"

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

echo "Kadmu dev server on http://127.0.0.1:${PORT}  (Ctrl+C to stop)"
echo "Edit src/web/* -> just refresh the tab.  Edit src/server.py -> auto-restarts."

cleanup() { [ -n "$PID" ] && kill "$PID" 2>/dev/null; exit 0; }
trap cleanup INT TERM

while true; do
  "$PY" src/server.py --port "$PORT" --no-open "$@" &
  PID=$!
  LAST="$(mtime src/server.py)"
  while kill -0 "$PID" 2>/dev/null; do
    sleep 1
    NOW="$(mtime src/server.py)"
    if [ "$NOW" != "$LAST" ]; then
      echo ">> src/server.py changed — restarting backend..."
      kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
      break
    fi
  done
  # if the server died on its own (e.g. syntax error), wait for the next save
  if [ "$(mtime src/server.py)" = "$LAST" ] && ! kill -0 "$PID" 2>/dev/null; then
    echo ">> server exited; waiting for the next save to src/server.py..."
    while [ "$(mtime src/server.py)" = "$LAST" ]; do sleep 1; done
  fi
done
