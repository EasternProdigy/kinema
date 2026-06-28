"""Subscription state → entitlement, tenant provisioning, and the machine-to-machine
license issuance the node's poller calls. This is the bridge between 'they paid'
(subscriptions, kept in sync by Stripe webhooks) and 'their node may serve the
Cloud experience' (a signed license token)."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time

from . import licensing
from .const import LICENSE_PROOF_SKEW
from .db import db, write_lock

ACTIVE_STATUSES = ("active", "trialing")


# ----- subscriptions ------------------------------------------------------ #
def active_subscription(account_id):
    """The account's current entitling subscription row, or None. A subscription
    counts while Stripe says active/trialing; we also keep honouring one that's
    been cancelled-at-period-end until that period actually ends."""
    rows = db().execute(
        "SELECT * FROM subscriptions WHERE account_id=? ORDER BY updated DESC",
        (account_id,)).fetchall()
    now = time.time()
    for r in rows:
        if r["status"] in ACTIVE_STATUSES:
            return r
        if r["status"] == "canceled" and r["current_period_end"] > now:
            return r
    return None


def is_entitled(account_id):
    return active_subscription(account_id) is not None


def upsert_subscription(account_id, stripe_sub_id, plan, status,
                        period_end=0, cancel_at_period_end=False):
    """Insert/update a subscription from a Stripe event (or the mock simulator).
    Keyed by the Stripe subscription id when we have one."""
    now = time.time()
    conn = db()
    with write_lock():
        existing = None
        if stripe_sub_id:
            existing = conn.execute(
                "SELECT id FROM subscriptions WHERE stripe_subscription=?",
                (stripe_sub_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE subscriptions SET account_id=?, plan=?, status=?, "
                "current_period_end=?, cancel_at_period_end=?, updated=? WHERE id=?",
                (account_id, plan, status, float(period_end or 0),
                 1 if cancel_at_period_end else 0, now, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO subscriptions(account_id,stripe_subscription,plan,status,"
                "current_period_end,cancel_at_period_end,updated) VALUES(?,?,?,?,?,?,?)",
                (account_id, stripe_sub_id, plan, status, float(period_end or 0),
                 1 if cancel_at_period_end else 0, now))
        conn.commit()


def set_subscription_status(stripe_sub_id, status, period_end=None, cancel_at_period_end=None):
    """Patch an existing subscription's status (e.g. webhook: updated/deleted)."""
    row = db().execute("SELECT * FROM subscriptions WHERE stripe_subscription=?",
                       (stripe_sub_id,)).fetchone()
    if not row:
        return False
    pe = row["current_period_end"] if period_end is None else float(period_end)
    cap = row["cancel_at_period_end"] if cancel_at_period_end is None else (1 if cancel_at_period_end else 0)
    conn = db()
    conn.execute("UPDATE subscriptions SET status=?, current_period_end=?, "
                 "cancel_at_period_end=?, updated=? WHERE id=?",
                 (status, pe, cap, time.time(), row["id"]))
    conn.commit()
    return True


# ----- tenants (each = one provisioned self-host node) -------------------- #
def provision_tenant(account_id, label="My Kadmu"):
    """Ensure the account has at least one tenant; return its public dict (incl.
    the secret, which the dashboard shows so the owner can configure their node)."""
    with write_lock():
        row = db().execute(
            "SELECT * FROM tenants WHERE account_id=? ORDER BY created LIMIT 1",
            (account_id,)).fetchone()
        if row:
            return _tenant_public(row)
        tid = "ten_" + secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        now = time.time()
        db().execute(
            "INSERT INTO tenants(id,account_id,secret,label,created,last_seen) "
            "VALUES(?,?,?,?,?,?)", (tid, account_id, secret, label, now, 0))
        db().commit()
    return _tenant_public(get_tenant(tid))


def get_tenant(tenant_id):
    return db().execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()


def tenants_for(account_id):
    return [_tenant_public(r) for r in db().execute(
        "SELECT * FROM tenants WHERE account_id=? ORDER BY created", (account_id,)).fetchall()]


def _tenant_public(row):
    if row is None:
        return None
    return {"id": row["id"], "secret": row["secret"], "label": row["label"],
            "created": row["created"], "lastSeen": row["last_seen"]}


def touch_tenant(tenant_id):
    conn = db()
    conn.execute("UPDATE tenants SET last_seen=? WHERE id=?", (time.time(), tenant_id))
    conn.commit()


# ----- machine-to-machine license issuance ------------------------------- #
def verify_tenant_proof(tenant_id, ts, sig):
    """A node proves it holds the tenant secret by HMAC-signing '<tenant>.<ts>'
    (the secret itself never crosses the wire). Returns the tenant row or None."""
    row = get_tenant(tenant_id)
    if row is None:
        return None
    try:
        if abs(time.time() - int(ts)) > LICENSE_PROOF_SKEW:
            return None
    except (TypeError, ValueError):
        return None
    expected = hmac.new(row["secret"].encode("utf-8"),
                        f"{tenant_id}.{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(sig or "")):
        return None
    return row


def license_for_tenant(tenant_row):
    """Issue a signed license for a tenant IF its owning account is entitled.
    Returns (token, payload) on success, or (None, reason) when not entitled."""
    sub = active_subscription(tenant_row["account_id"])
    if sub is None:
        return None, "no_active_subscription"
    touch_tenant(tenant_row["id"])
    token, payload = licensing.issue(
        tenant_row["id"], tenant_row["secret"], tenant_row["account_id"],
        sub["plan"], sub["status"], sub["current_period_end"])
    return token, payload
