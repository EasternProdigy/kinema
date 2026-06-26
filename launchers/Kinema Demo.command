#!/usr/bin/env bash
# macOS: double-click to try Kinema with auto-generated sample videos (read-only).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/kinema.sh" --demo
