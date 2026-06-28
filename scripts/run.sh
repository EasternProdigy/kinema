#!/usr/bin/env bash
# Kadmu launcher.
# Usage:
#   ./run.sh                       # start with whatever library folders are saved
#   ./run.sh /path/to/Videos       # add a folder and start
#   ./run.sh --lan --password pw   # serve on your home network with a password
cd "$(dirname "$0")/.." || exit 1
exec python3 src/server.py "$@"
