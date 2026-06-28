#!/usr/bin/env python3
"""Kadmu launcher.

The backend used to be this one big file; it now lives in the ``kadmu`` package
right next to it (``src/kadmu/``), split by concern but still pure standard
library with no build step. This thin shim keeps every existing entry point
working unchanged — ``python3 src/server.py [args]``, the launchers/scripts, the
Docker image, and the PyInstaller build all still target this file.

See ``src/kadmu/__init__.py`` for the module layout.
"""
import sys
from pathlib import Path

# Make the package importable whether launched as `python3 src/server.py`, frozen
# by PyInstaller, or imported from elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kadmu.app import main

if __name__ == "__main__":
    main()
