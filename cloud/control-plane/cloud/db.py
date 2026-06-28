"""The control-plane SQLite store: cloud-customer accounts, dashboard sessions,
subscriptions, provisioned tenants (each = one self-host node), donations, and a
processed-webhook log for idempotency. sqlite3 ships with Python — stdlib only.
"""
from __future__ import annotations
import sqlite3
import threading
import time

from .const import DB_PATH, DATA_DIR

_local = threading.local()         # one connection per worker thread
_init_lock = threading.Lock()
_write_lock = threading.Lock()     # serialize the rare shape-changing writes
_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name            TEXT NOT NULL DEFAULT '',
  pw_salt         TEXT NOT NULL,
  pw_hash         TEXT NOT NULL,
  iters           INTEGER NOT NULL DEFAULT 240000,
  stripe_customer TEXT,
  created         REAL NOT NULL DEFAULT 0,
  last_seen       REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created    REAL NOT NULL DEFAULT 0,
  expires    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
CREATE TABLE IF NOT EXISTS subscriptions (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  stripe_subscription TEXT UNIQUE,
  plan                TEXT NOT NULL DEFAULT 'monthly',
  status              TEXT NOT NULL DEFAULT 'incomplete',
  current_period_end  REAL NOT NULL DEFAULT 0,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
  updated             REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_subs_account ON subscriptions(account_id);
CREATE TABLE IF NOT EXISTS tenants (
  id         TEXT PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  secret     TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  created    REAL NOT NULL DEFAULT 0,
  last_seen  REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tenants_account ON tenants(account_id);
CREATE TABLE IF NOT EXISTS donations (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  email          TEXT NOT NULL DEFAULT '',
  amount_cents   INTEGER NOT NULL DEFAULT 0,
  currency       TEXT NOT NULL DEFAULT 'usd',
  stripe_session TEXT UNIQUE,
  status         TEXT NOT NULL DEFAULT 'pending',
  created        REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS webhook_events (
  id       TEXT PRIMARY KEY,
  type     TEXT NOT NULL DEFAULT '',
  received REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def db():
    """The current thread's SQLite connection (created on demand)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    """Create the schema (idempotent)."""
    global _ready
    with _init_lock:
        if _ready:
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = db()
        conn.executescript(SCHEMA)
        conn.commit()
        _ready = True
    purge_sessions()


def write_lock():
    """Shared lock for multi-statement writes that must not interleave."""
    return _write_lock


# ----- small key/value meta ---------------------------------------------- #
def meta_get(key, default=None):
    row = db().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key, value):
    conn = db()
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


# ----- sessions ----------------------------------------------------------- #
def purge_sessions():
    try:
        conn = db()
        conn.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
        conn.commit()
    except sqlite3.Error:
        pass


# ----- webhook idempotency ------------------------------------------------ #
def webhook_seen(event_id):
    """Record a Stripe event id; return True if it was already processed."""
    if not event_id:
        return False
    conn = db()
    try:
        conn.execute("INSERT INTO webhook_events(id,type,received) VALUES(?,?,?)",
                     (event_id, "", time.time()))
        conn.commit()
        return False
    except sqlite3.IntegrityError:
        return True
