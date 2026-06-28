#!/usr/bin/env bash
# Try Kadmu instantly with auto-generated sample videos (read-only).
cd "$(dirname "$0")/.." || exit 1
exec python3 src/server.py --demo "$@"
