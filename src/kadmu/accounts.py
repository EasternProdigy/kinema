"""Accounts & per-user state — the SQLite store (opt-in, --accounts).

When accounts mode is OFF none of this runs. When ON, every viewer signs in with
their own username + password; progress / My List / playlists / prefs are keyed by
user_id, sessions persist across restarts, management is admin-only. sqlite3 ships
with Python, so the stdlib-only promise holds.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from .const import (
    DB_PATH, DATA_DIR, SESSION_TTL, PROGRESS_PATH, MYLIST_PATH, PLAYLISTS_PATH,
    _REQ, load_json, _json_obj,
)

PBKDF2_ITERS = 240_000        # cost of one password hash (PBKDF2-HMAC-SHA256)
PW_MIN_LEN = 6
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")

_db_local = threading.local()      # one sqlite connection per worker thread
_db_init_lock = threading.Lock()
_db_write_lock = threading.Lock()  # serialize the rare account-shape writes
_db_ready = False

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  username  TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name      TEXT NOT NULL DEFAULT '',
  pw_salt   TEXT NOT NULL,
  pw_hash   TEXT NOT NULL,
  iters     INTEGER NOT NULL DEFAULT 240000,
  role      TEXT NOT NULL DEFAULT 'viewer',
  created   REAL NOT NULL DEFAULT 0,
  last_seen REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token   TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created REAL NOT NULL DEFAULT 0,
  expires REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS progress (
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  path     TEXT NOT NULL,
  position REAL NOT NULL DEFAULT 0,
  duration REAL NOT NULL DEFAULT 0,
  updated  REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, path)
);
CREATE TABLE IF NOT EXISTS mylist (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  path    TEXT NOT NULL,
  name    TEXT NOT NULL DEFAULT '',
  added   REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, path)
);
CREATE TABLE IF NOT EXISTS playlists (
  user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS prefs (
  user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def _db():
    """The current thread's SQLite connection (one per thread; created on demand)."""
    conn = getattr(_db_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")     # concurrent readers + one writer
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")      # ON DELETE CASCADE for user data
        _db_local.conn = conn
    return conn


def init_db():
    """Create the schema (idempotent). The owner account, created on first sign-up,
    inherits any existing single-password JSON state via _import_legacy_into()."""
    global _db_ready
    with _db_init_lock:
        if _db_ready:
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = _db()
        conn.executescript(DB_SCHEMA)
        conn.commit()
        _db_ready = True
    db_purge_sessions()


# ----- small key/value meta table ----------------------------------------- #
def _meta_get(key, default=None):
    row = _db().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(key, value):
    conn = _db()
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def signup_open():
    """Whether anonymous visitors may register their own (viewer) account."""
    return _meta_get("signup_open", "0") == "1"


# ----- password hashing (PBKDF2-HMAC-SHA256, per-user salt) ---------------- #
def _pw_make(password, iters=PBKDF2_ITERS):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                             bytes.fromhex(salt), iters)
    return salt, dk.hex(), iters


def _pw_check(password, salt, expected, iters):
    try:
        dk = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                 bytes.fromhex(salt), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), expected)


# ----- users -------------------------------------------------------------- #
def _user_public(row):
    """A user row stripped of its password hash, safe to return to the client."""
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"],
            "name": row["name"] or row["username"], "role": row["role"],
            "created": row["created"], "lastSeen": row["last_seen"]}


def user_count():
    return _db().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def _admin_count():
    return _db().execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'").fetchone()["n"]


def get_user(uid):
    return _user_public(_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def get_user_by_name(username):
    return _db().execute("SELECT * FROM users WHERE username=? COLLATE NOCASE",
                         (username,)).fetchone()


def list_users():
    return [_user_public(r) for r in
            _db().execute("SELECT * FROM users ORDER BY id").fetchall()]


def create_user(username, password, role="viewer", name=""):
    """Create an account. The very first account is forced to 'admin' (the owner)
    and inherits the shared single-password history. Returns (user, None) or
    (None, error_message)."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        return None, "Username must be 1-32 letters, numbers, dot, dash or underscore."
    if len(str(password or "")) < PW_MIN_LEN:
        return None, f"Password must be at least {PW_MIN_LEN} characters."
    if role not in ("admin", "viewer"):
        role = "viewer"
    salt, h, iters = _pw_make(password)
    now = time.time()
    conn = _db()
    try:
        with _db_write_lock:
            first = user_count() == 0
            cur = conn.execute(
                "INSERT INTO users(username,name,pw_salt,pw_hash,iters,role,created,last_seen) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (username, (name or username).strip()[:64], salt, h, iters,
                 "admin" if first else role, now, now))
            conn.commit()
            uid = cur.lastrowid
            if first:
                _import_legacy_into(uid)
    except sqlite3.IntegrityError:
        return None, "That username is already taken."
    return get_user(uid), None


def auth_user(username, password):
    """Verify credentials; returns the public user dict or None."""
    row = get_user_by_name(username)
    if row is None:
        _pw_check(password, "00", "x" * 64, PBKDF2_ITERS)   # blunt user-enumeration timing
        return None
    if not _pw_check(password, row["pw_salt"], row["pw_hash"], row["iters"]):
        return None
    conn = _db()
    conn.execute("UPDATE users SET last_seen=? WHERE id=?", (time.time(), row["id"]))
    conn.commit()
    return get_user(row["id"])


def set_user_password(uid, password):
    if len(str(password or "")) < PW_MIN_LEN:
        return False, f"Password must be at least {PW_MIN_LEN} characters."
    salt, h, iters = _pw_make(password)
    conn = _db()
    conn.execute("UPDATE users SET pw_salt=?, pw_hash=?, iters=? WHERE id=?",
                 (salt, h, iters, uid))
    conn.commit()
    return True, None


def set_user_role(uid, role):
    if role not in ("admin", "viewer"):
        return False, "Unknown role."
    with _db_write_lock:
        row = _db().execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if row is None:
            return False, "No such user."
        if row["role"] == "admin" and role == "viewer" and _admin_count() <= 1:
            return False, "Can't remove the last admin."
        _db().execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        _db().commit()
    return True, None


def delete_user(uid):
    with _db_write_lock:
        row = _db().execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if row is None:
            return False, "No such user."
        if row["role"] == "admin" and _admin_count() <= 1:
            return False, "Can't delete the last admin."
        _db().execute("DELETE FROM users WHERE id=?", (uid,))   # cascades to all their data
        _db().commit()
    return True, None


# ----- persistent sessions ------------------------------------------------ #
def db_new_session(uid):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    conn = _db()
    conn.execute("INSERT INTO sessions(token,user_id,created,expires) VALUES(?,?,?,?)",
                 (tok, uid, now, now + SESSION_TTL))
    conn.commit()
    return tok


def db_session_user(token):
    if not token:
        return None
    row = _db().execute("SELECT user_id, expires FROM sessions WHERE token=?",
                        (token,)).fetchone()
    if row is None:
        return None
    if row["expires"] <= time.time():
        db_logout(token)
        return None
    return row["user_id"]


def db_logout(token):
    if not token:
        return
    conn = _db()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def db_logout_user_sessions(uid):
    """Invalidate every session for a user (e.g. after an admin resets their pw)."""
    conn = _db()
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.commit()


def db_purge_sessions():
    try:
        conn = _db()
        conn.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
        conn.commit()
    except sqlite3.Error:
        pass


# ----- per-user resume / My List / playlists / prefs ---------------------- #
def db_progress_all(uid):
    rows = _db().execute(
        "SELECT path, position, duration, updated FROM progress WHERE user_id=?",
        (uid,)).fetchall()
    return {r["path"]: {"position": r["position"], "duration": r["duration"],
                        "updated": r["updated"]} for r in rows}


def db_set_progress(uid, path, rec):
    conn = _db()
    conn.execute(
        "INSERT INTO progress(user_id,path,position,duration,updated) VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id,path) DO UPDATE SET "
        "position=excluded.position, duration=excluded.duration, updated=excluded.updated",
        (uid, path, float(rec.get("position", 0)), float(rec.get("duration", 0)),
         float(rec.get("updated", 0))))
    conn.commit()


def db_clear_progress(uid, path):
    conn = _db()
    if path is None:
        conn.execute("DELETE FROM progress WHERE user_id=?", (uid,))
    else:
        conn.execute("DELETE FROM progress WHERE user_id=? AND path=?", (uid, path))
    conn.commit()


def db_mylist_all(uid):
    rows = _db().execute("SELECT path, name, added FROM mylist WHERE user_id=?",
                         (uid,)).fetchall()
    return {r["path"]: {"name": r["name"], "added": r["added"]} for r in rows}


def db_mylist_set(uid, path, name, on):
    conn = _db()
    if on:
        conn.execute(
            "INSERT INTO mylist(user_id,path,name,added) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,path) DO UPDATE SET name=excluded.name",
            (uid, path, name, time.time()))
    else:
        conn.execute("DELETE FROM mylist WHERE user_id=? AND path=?", (uid, path))
    conn.commit()
    return [r["path"] for r in
            _db().execute("SELECT path FROM mylist WHERE user_id=?", (uid,)).fetchall()]


def db_playlists_get(uid):
    row = _db().execute("SELECT data FROM playlists WHERE user_id=?", (uid,)).fetchone()
    return _json_obj(row["data"]) if row else {}


def db_playlists_set(uid, data):
    conn = _db()
    conn.execute("INSERT INTO playlists(user_id,data) VALUES(?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                 (uid, json.dumps(data)))
    conn.commit()


def db_prefs_get(uid):
    row = _db().execute("SELECT data FROM prefs WHERE user_id=?", (uid,)).fetchone()
    return _json_obj(row["data"]) if row else {}


def db_prefs_set(uid, data):
    conn = _db()
    conn.execute("INSERT INTO prefs(user_id,data) VALUES(?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                 (uid, json.dumps(data)))
    conn.commit()


def db_migrate_path(old: Path, new: Path):
    """Re-key resume + My List entries when a file/folder is renamed or moved, for
    every user at once (file ops are admin-wide). Mirrors _migrate_progress()."""
    old_s, new_s = str(old), str(new)
    like = old_s + "/%"
    cut = len(old_s) + 1     # sqlite substr() is 1-indexed; +1 drops the old prefix
    conn = _db()
    for tbl in ("progress", "mylist"):
        conn.execute(f"UPDATE OR IGNORE {tbl} SET path=? WHERE path=?", (new_s, old_s))
        conn.execute(f"UPDATE OR IGNORE {tbl} SET path=? || substr(path,?) WHERE path LIKE ?",
                     (new_s, cut, like))
    conn.commit()


def _import_legacy_into(uid):
    """One-time: pull the shared single-password JSON state (progress / My List /
    playlists) into the owner account so enabling accounts mode keeps your history.
    Runs once, gated by a meta flag; the JSON files are left in place as a backup."""
    if _meta_get("legacy_imported") == "1":
        return
    prog = load_json(PROGRESS_PATH, {})
    if isinstance(prog, dict):
        for path, rec in prog.items():
            if isinstance(rec, dict):
                db_set_progress(uid, path, rec)
    ml = load_json(MYLIST_PATH, {})
    if isinstance(ml, dict):
        conn = _db()
        for path, rec in ml.items():
            if isinstance(rec, dict):
                conn.execute(
                    "INSERT OR IGNORE INTO mylist(user_id,path,name,added) VALUES(?,?,?,?)",
                    (uid, path, rec.get("name", ""), rec.get("added", 0)))
        conn.commit()
    pls = load_json(PLAYLISTS_PATH, {})
    if isinstance(pls, dict) and pls:
        db_playlists_set(uid, pls)
    _meta_set("legacy_imported", "1")


def current_user():
    """The signed-in user for the request being handled (dict), or None."""
    return getattr(_REQ, "user", None)


def _current_uid():
    u = current_user()
    return u["id"] if u else None


def _session_cookie(tok):
    return (f"kadmu_session={tok}; HttpOnly; SameSite=Strict; "
            f"Path=/; Max-Age={int(SESSION_TTL)}")


CLEAR_COOKIE = "kadmu_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
