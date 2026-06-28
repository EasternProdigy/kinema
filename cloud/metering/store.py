"""The relay-usage store — one SQLite table, ``relay_usage`` (one row per tenant per
billing month, plus running counters). stdlib ``sqlite3`` only.

Per docs/PHASE_5_DESIGN.md §10.2 the recommended deployment points this at the **same**
``cloud.db`` the 4a control-plane uses, so there's a single DB to back up (Litestream→R2).
It can equally open its own file for isolated testing. Either way the table is created on
demand, so adding metering never requires a migration step on the control-plane.
"""
from __future__ import annotations
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS relay_usage (
  tenant   TEXT NOT NULL,
  period   TEXT NOT NULL,                 -- 'YYYY-MM' billing month
  bytes    INTEGER NOT NULL DEFAULT 0,    -- relayed bytes attributed this period
  sessions INTEGER NOT NULL DEFAULT 0,    -- relay sessions seen this period
  updated  REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant, period)
);
"""


class MeterStore:
    """A thin, thread-safe wrapper over the ``relay_usage`` table. One connection per
    thread (SQLite connections aren't shareable across threads); writes are serialized
    by a process lock so concurrent collector samples don't lose an increment."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._ready = False

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def init(self):
        """Create the table (idempotent; safe to call against the shared control-plane DB)."""
        with self._init_lock:
            if self._ready:
                return
            conn = self._conn()
            conn.executescript(SCHEMA)
            conn.commit()
            self._ready = True
        return self

    # ----- writes --------------------------------------------------------- #
    def add(self, tenant, period, delta_bytes, now, delta_sessions=0):
        """Add ``delta_bytes`` (and optionally session count) to a tenant's period row,
        creating it if needed. ``delta_bytes`` may be 0 (e.g. just bumping ``updated``)."""
        delta_bytes = max(0, int(delta_bytes))
        delta_sessions = max(0, int(delta_sessions))
        with self._write_lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO relay_usage(tenant, period, bytes, sessions, updated) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(tenant, period) DO UPDATE SET "
                "  bytes = bytes + excluded.bytes, "
                "  sessions = sessions + excluded.sessions, "
                "  updated = excluded.updated",
                (tenant, period, delta_bytes, delta_sessions, float(now)))
            conn.commit()

    # ----- reads ---------------------------------------------------------- #
    def bytes_this_period(self, tenant, period):
        row = self._conn().execute(
            "SELECT bytes FROM relay_usage WHERE tenant=? AND period=?",
            (tenant, period)).fetchone()
        return int(row["bytes"]) if row else 0

    def rows_for_period(self, period):
        return self._conn().execute(
            "SELECT tenant, bytes, sessions FROM relay_usage WHERE period=?",
            (period,)).fetchall()

    def totals_for_period(self, period):
        """``(total_bytes, total_sessions, tenant_count)`` across all tenants this period."""
        row = self._conn().execute(
            "SELECT COALESCE(SUM(bytes),0) b, COALESCE(SUM(sessions),0) s, COUNT(*) n "
            "FROM relay_usage WHERE period=?", (period,)).fetchone()
        return int(row["b"]), int(row["s"]), int(row["n"])
