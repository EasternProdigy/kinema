#!/usr/bin/env bash
# Try Kinema instantly with auto-generated sample videos (read-only).
cd "$(dirname "$0")" || exit 1
exec python3 server.py --demo "$@"
