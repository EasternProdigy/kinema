#!/usr/bin/env bash
# Kadmu "live from source" launcher — what the `dev` desktop icon runs.
#
# Starts scripts/dev.sh in the background (backend auto-restarts when you save
# src/server.py or src/kadmu/*; frontend edits just need a refresh) unless it's
# already up, then opens Kadmu in its own app window. Safe to click any time.
#   ./kadmu-dev.sh          # start (if needed) + open
#   ./kadmu-dev.sh --stop   # stop the background dev server
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" || exit 1

PORT="${KADMU_PORT:-8000}"
PY="$(command -v python3 || command -v python)"
LOG="$DIR/cache/dev.log"
DEV="$DIR/scripts/dev.sh"

if [ "$1" = "--stop" ]; then
  pkill -f "$DEV" 2>/dev/null
  exit 0
fi

up() { curl -fs -m 2 "http://127.0.0.1:$PORT/api/session" 2>/dev/null | grep -q '"Kadmu"'; }
port_taken() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }
fail() {
  notify-send -i "$DIR/launchers/kadmu.png" "Kadmu didn't start" "$1" 2>/dev/null || echo "$1" >&2
  exit 1
}

if ! up; then
  # Start exactly one dev loop. If one is already running, the server is just
  # mid-restart (or waiting on a fixed save) — don't start a second one.
  if ! pgrep -f "$DEV" >/dev/null; then
    port_taken && fail "Port $PORT is in use by something else. Set KADMU_PORT or free the port."
    mkdir -p "$DIR/cache"
    setsid nohup bash "$DEV" >"$LOG" 2>&1 < /dev/null &
  fi
  for _ in $(seq 1 40); do up && break; sleep 0.5; done
  up || fail "The server isn't responding — probably a backend error. See $LOG"
fi

# The server sees itself already running and just opens the window, then exits.
exec "$PY" src/server.py --port "$PORT" --app
