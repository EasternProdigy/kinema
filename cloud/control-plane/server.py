#!/usr/bin/env python3
"""Kadmu Cloud control-plane launcher.

The hosted layer (NOT shipped to self-hosters). Thin shim → cloud.app.main().
Standard library only; Stripe is reached over REST. Runs in MOCK mode by default
(no Stripe keys needed) so the whole funnel works locally. See cloud/README.md.

    python3 cloud/control-plane/server.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloud.app import main

if __name__ == "__main__":
    main()
