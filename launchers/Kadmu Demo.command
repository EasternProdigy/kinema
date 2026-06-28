#!/usr/bin/env bash
# macOS: double-click to try Kadmu with auto-generated sample videos (read-only).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/kadmu.sh" --demo
