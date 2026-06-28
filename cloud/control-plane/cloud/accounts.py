"""Cloud-customer accounts + dashboard sessions. PBKDF2-HMAC-SHA256 password
hashing (per-account salt), persistent sessions in SQLite. Mirrors the node's
accounts module so the two read alike, but this store is the *billing* customer,
not a library viewer."""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
import sqlite3
import time

from .const import PBKDF2_ITERS, PW_MIN_LEN, SESSION_TTL, SESSION_COOKIE
from .db import db, write_lock

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ----- password hashing --------------------------------------------------- #
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


# ----- accounts ----------------------------------------------------------- #
def account_public(row):
    """An account row stripped of its password hash, safe for templates/JSON."""
    if row is None:
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"] or row["email"],
            "stripeCustomer": row["stripe_customer"], "created": row["created"]}


def get_account(aid):
    return _row_to_public(db().execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone())


def get_account_row(aid):
    return db().execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()


def get_account_by_email(email):
    return db().execute("SELECT * FROM accounts WHERE email=? COLLATE NOCASE",
                        (email,)).fetchone()


def _row_to_public(row):
    return account_public(row)


def create_account(email, password, name=""):
    """Create a cloud customer. Returns (account_public, None) or (None, error)."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return None, "Enter a valid email address."
    if len(str(password or "")) < PW_MIN_LEN:
        return None, f"Password must be at least {PW_MIN_LEN} characters."
    salt, h, iters = _pw_make(password)
    now = time.time()
    conn = db()
    try:
        with write_lock():
            cur = conn.execute(
                "INSERT INTO accounts(email,name,pw_salt,pw_hash,iters,created,last_seen) "
                "VALUES(?,?,?,?,?,?,?)",
                (email, (name or "").strip()[:80], salt, h, iters, now, now))
            conn.commit()
            aid = cur.lastrowid
    except sqlite3.IntegrityError:
        return None, "An account with that email already exists."
    return get_account(aid), None


def auth_account(email, password):
    """Verify credentials; returns the account row (full, incl. id) or None."""
    row = get_account_by_email(email)
    if row is None:
        _pw_check(password, "00", "x" * 64, PBKDF2_ITERS)   # blunt enumeration timing
        return None
    if not _pw_check(password, row["pw_salt"], row["pw_hash"], row["iters"]):
        return None
    conn = db()
    conn.execute("UPDATE accounts SET last_seen=? WHERE id=?", (time.time(), row["id"]))
    conn.commit()
    return row


def set_stripe_customer(aid, customer_id):
    conn = db()
    conn.execute("UPDATE accounts SET stripe_customer=? WHERE id=?", (customer_id, aid))
    conn.commit()


def account_by_stripe_customer(customer_id):
    if not customer_id:
        return None
    return db().execute("SELECT * FROM accounts WHERE stripe_customer=?",
                        (customer_id,)).fetchone()


# ----- sessions ----------------------------------------------------------- #
def new_session(aid):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    conn = db()
    conn.execute("INSERT INTO sessions(token,account_id,created,expires) VALUES(?,?,?,?)",
                 (tok, aid, now, now + SESSION_TTL))
    conn.commit()
    return tok


def session_account(token):
    if not token:
        return None
    row = db().execute("SELECT account_id, expires FROM sessions WHERE token=?",
                       (token,)).fetchone()
    if row is None:
        return None
    if row["expires"] <= time.time():
        logout(token)
        return None
    return row["account_id"]


def logout(token):
    if not token:
        return
    conn = db()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def session_cookie(tok):
    return (f"{SESSION_COOKIE}={tok}; HttpOnly; SameSite=Lax; "
            f"Path=/; Max-Age={int(SESSION_TTL)}")


CLEAR_COOKIE = f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
