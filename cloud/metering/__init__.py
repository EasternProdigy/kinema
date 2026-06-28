"""Kadmu Phase 5 — relay usage metering + per-plan caps (stdlib only).

The discrete, fully-testable core of Phase 5's cost control. Nothing here imports the
open-source node (`src/kadmu/`) or the control-plane; the control-plane imports *this* (by
adding `cloud/` to the path, the same way the connector imports `wire`) to make the relay
allow/deny decision and mint TURN credentials, and the collector feeds it coturn usage.

See docs/PHASE_5_DESIGN.md §2.
"""
from . import caps, turncreds          # noqa: F401  (convenience re-exports)
from .meter import Meter               # noqa: F401
from .store import MeterStore          # noqa: F401

__all__ = ["caps", "turncreds", "Meter", "MeterStore"]
