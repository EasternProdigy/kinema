"""Process Stripe events (real, or synthesized by the mock simulator) into our
subscription/donation/tenant state. One ``process_event`` entry point so the live
webhook route and the mock success-redirect path run identical logic."""
from __future__ import annotations
import time

from . import accounts, entitlements
from .db import db, webhook_seen


def _plan_from(obj, default="monthly"):
    md = (obj.get("metadata") or {}) if isinstance(obj, dict) else {}
    return md.get("plan") or obj.get("client_reference_id") or default


def _account_for_session(sess):
    """Find (or skip) the account this checkout session belongs to. Accounts are
    created at signup keyed by email, so we match on customer_email, falling back
    to an already-linked Stripe customer id."""
    email = sess.get("customer_email") or (sess.get("customer_details") or {}).get("email")
    row = accounts.get_account_by_email(email) if email else None
    if row is None and sess.get("customer"):
        row = accounts.account_by_stripe_customer(sess.get("customer"))
    return row


def process_event(event):
    """Apply one Stripe event. Idempotent: a re-delivered event id is a no-op.
    Returns a short string describing what happened (for logs/mock responses)."""
    if not isinstance(event, dict):
        return "ignored"
    eid = event.get("id")
    if eid and webhook_seen(eid):
        return "duplicate"
    etype = event.get("type", "")
    obj = ((event.get("data") or {}).get("object")) or {}

    if etype == "checkout.session.completed":
        if obj.get("mode") == "payment":          # a donation
            _complete_donation(obj)
            return "donation_recorded"
        return _complete_subscription_checkout(obj)

    if etype in ("customer.subscription.updated", "customer.subscription.created"):
        entitlements.set_subscription_status(
            obj.get("id"), obj.get("status", "active"),
            period_end=obj.get("current_period_end", 0),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")))
        # Created-before-checkout-completed race: ensure a row exists.
        _ensure_subscription_row(obj)
        return "subscription_synced"

    if etype == "customer.subscription.deleted":
        entitlements.set_subscription_status(obj.get("id"), "canceled",
                                             period_end=obj.get("current_period_end", 0))
        return "subscription_canceled"

    if etype == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        if sub_id:
            entitlements.set_subscription_status(sub_id, "past_due")
        return "payment_failed"

    return "ignored"


def _complete_subscription_checkout(sess):
    row = _account_for_session(sess)
    if row is None:
        return "no_account"
    aid = row["id"]
    customer_id = sess.get("customer")
    if customer_id and not row["stripe_customer"]:
        accounts.set_stripe_customer(aid, customer_id)
    plan = _plan_from(sess)
    sub_id = sess.get("subscription")
    period_end = sess.get("_period_end") or (time.time() + (365 if plan == "yearly" else 30) * 86400)
    entitlements.upsert_subscription(aid, sub_id, plan, "active", period_end=period_end)
    entitlements.provision_tenant(aid)
    return "subscription_active"


def _ensure_subscription_row(obj):
    customer_id = obj.get("customer")
    acct = accounts.account_by_stripe_customer(customer_id)
    if acct is None:
        return
    if db().execute("SELECT 1 FROM subscriptions WHERE stripe_subscription=?",
                    (obj.get("id"),)).fetchone():
        return
    entitlements.upsert_subscription(
        acct["id"], obj.get("id"), _plan_from(obj), obj.get("status", "active"),
        period_end=obj.get("current_period_end", 0),
        cancel_at_period_end=bool(obj.get("cancel_at_period_end")))
    entitlements.provision_tenant(acct["id"])


def _complete_donation(sess):
    sid = sess.get("id")
    amount = sess.get("amount_total") or sess.get("_amount") or 0
    email = sess.get("customer_email") or (sess.get("customer_details") or {}).get("email") or ""
    conn = db()
    try:
        conn.execute(
            "INSERT INTO donations(email,amount_cents,currency,stripe_session,status,created) "
            "VALUES(?,?,?,?,?,?)",
            (email, int(amount), sess.get("currency", "usd"), sid, "completed", time.time()))
        conn.commit()
    except Exception:
        # already recorded (unique stripe_session) — fine.
        conn.execute("UPDATE donations SET status='completed' WHERE stripe_session=?", (sid,))
        conn.commit()
