#!/usr/bin/env bash
# macOS double-click launcher. Right-click > Open the first time if Gatekeeper warns.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/kadmu.sh"
