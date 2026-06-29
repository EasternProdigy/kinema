"""A thin Stripe client over the REST API using urllib (no SDK → stdlib only),
plus webhook-signature verification, plus a **mock simulator**.

When ``const.MOCK`` is true (the default with no ``STRIPE_SECRET_KEY``) every call
here is faked locally: Checkout "redirects" straight back to our own success URL
and a synthetic ``checkout.session.completed`` event is what the success handler
replays through the real webhook path. That means the whole signup → pay → license
flow runs end-to-end with zero Stripe setup, exercising the same code that handles
real events in live mode.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import const


class StripeError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Form encoding — Stripe wants nested params as a[b][c]=v and lists as a[0][b]=v.
# --------------------------------------------------------------------------- #
def _flatten(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}[{k}]" if prefix else str(k)
            out.extend(_flatten(v, key))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(_flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, bool):
        out.append((prefix, "true" if obj else "false"))
    elif obj is None:
        pass
    else:
        out.append((prefix, str(obj)))
    return out


def _encode(params):
    return urllib.parse.urlencode(_flatten(params)).encode("utf-8")


def _request(method, path, params=None):
    """Authenticated Stripe REST call. Never used in MOCK mode."""
    if not const.STRIPE_SECRET_KEY:
        raise StripeError("No STRIPE_SECRET_KEY configured.")
    url = f"{const.STRIPE_API_BASE}{path}"
    data = _encode(params or {}) if method == "POST" else None
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(_flatten(params))
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {const.STRIPE_SECRET_KEY}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
            msg = (body.get("error") or {}).get("message") or str(e)
        except Exception:
            msg = str(e)
        raise StripeError(msg)
    except urllib.error.URLError as e:
        raise StripeError(f"Could not reach Stripe: {e}")


# --------------------------------------------------------------------------- #
# Checkout — subscription (signup) and one-time payment (donation)
# --------------------------------------------------------------------------- #
def create_subscription_checkout(plan, account_email, customer_id, success_url, cancel_url):
    """Start a pay-first subscription Checkout. Returns (checkout_url, session_id)."""
    if const.MOCK:
        sid = "cs_mock_" + secrets.token_hex(12)
        # Mock "Checkout": go straight to success, which replays a synthetic webhook.
        # Carry the chosen plan so the simulator provisions the right tier.
        url = f"{success_url}{'&' if '?' in success_url else '?'}session_id={sid}&plan={plan['id']}&mock=1"
        return url, sid
    line_item = {"price": plan.get("stripe_price"), "quantity": 1}
    if not line_item["price"]:
        raise StripeError(f"No Stripe price configured for the {plan['id']} plan "
                          f"(set STRIPE_PRICE_{plan['id'].upper()}).")
    params = {
        "mode": "subscription",
        "line_items": [line_item],
        "success_url": success_url + ("&" if "?" in success_url else "?") + "session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
        "client_reference_id": plan["id"],
        "subscription_data": {"metadata": {"plan": plan["id"]}},
    }
    if customer_id:
        params["customer"] = customer_id
    elif account_email:
        params["customer_email"] = account_email
    sess = _request("POST", "/checkout/sessions", params)
    return sess.get("url"), sess.get("id")


def create_onetime_checkout(plan, account_email, customer_id, success_url, cancel_url):
    """Start a one-time (mode=payment) Checkout for a lifetime plan. The plan id rides
    in metadata so the webhook can tell it apart from a donation. Returns (url, sid)."""
    if const.MOCK:
        sid = "cs_mock_life_" + secrets.token_hex(12)
        url = f"{success_url}{'&' if '?' in success_url else '?'}session_id={sid}&plan={plan['id']}&mock=1"
        return url, sid
    price = plan.get("stripe_price")
    if not price:
        raise StripeError(f"No Stripe price configured for the {plan['id']} plan "
                          f"(set STRIPE_PRICE_{plan['id'].upper()}).")
    params = {
        "mode": "payment",
        "line_items": [{"price": price, "quantity": 1}],
        "success_url": success_url + ("&" if "?" in success_url else "?") + "session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
        "client_reference_id": plan["id"],
        "metadata": {"plan": plan["id"]},
        "payment_intent_data": {"metadata": {"plan": plan["id"]}},
    }
    if customer_id:
        params["customer"] = customer_id
    elif account_email:
        params["customer_email"] = account_email
    sess = _request("POST", "/checkout/sessions", params)
    return sess.get("url"), sess.get("id")


def create_donation_checkout(amount_cents, email, success_url, cancel_url):
    """One-time donation Checkout. Returns (checkout_url, session_id)."""
    if const.MOCK:
        sid = "cs_mock_don_" + secrets.token_hex(12)
        url = (f"{success_url}{'&' if '?' in success_url else '?'}"
               f"session_id={sid}&amount={int(amount_cents)}&mock=1")
        return url, sid
    params = {
        "mode": "payment",
        "line_items": [{
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": int(amount_cents),
                "product_data": {"name": "Kadmu — donation (supports the open-source project)"},
            },
        }],
        "success_url": success_url + ("&" if "?" in success_url else "?") + "session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
        "submit_type": "donate",
    }
    if email:
        params["customer_email"] = email
    sess = _request("POST", "/checkout/sessions", params)
    return sess.get("url"), sess.get("id")


def retrieve_checkout_session(session_id):
    if const.MOCK:
        return {"id": session_id, "mock": True}
    return _request("GET", f"/checkout/sessions/{session_id}",
                    {"expand": ["subscription", "customer"]})


def retrieve_subscription(sub_id):
    if const.MOCK or not sub_id:
        return {}
    return _request("GET", f"/subscriptions/{sub_id}")


def billing_portal_url(customer_id, return_url):
    """A Stripe-hosted 'manage billing' link. In MOCK mode, a local stub page."""
    if const.MOCK or not customer_id:
        return f"{const.BASE_URL}/dashboard?portal=mock"
    sess = _request("POST", "/billing_portal/sessions",
                    {"customer": customer_id, "return_url": return_url})
    return sess.get("url") or return_url


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
def verify_webhook(payload_bytes, sig_header):
    """Verify a Stripe webhook signature (HMAC-SHA256 over '<t>.<payload>') and
    return the parsed event, or None if it can't be trusted. In MOCK mode we accept
    events the control-plane synthesized itself (marked livemode:false + mock:true).
    """
    try:
        event = json.loads(payload_bytes or b"{}")
    except (ValueError, TypeError):
        return None
    if const.MOCK:
        return event if event.get("mock") is True else None
    if not const.STRIPE_WEBHOOK_SECRET or not sig_header:
        return None
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts, v1 = parts.get("t"), parts.get("v1")
    if not ts or not v1:
        return None
    # Reject events older than 5 minutes (replay protection).
    try:
        if abs(time.time() - int(ts)) > 300:
            return None
    except ValueError:
        return None
    signed = f"{ts}.".encode("utf-8") + payload_bytes
    expected = hmac.new(const.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
                        signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        return None
    return event


def synth_event(event_type, obj):
    """Build a synthetic event for MOCK mode (replayed through the webhook path so
    the same handler runs as for real Stripe events)."""
    return {
        "id": "evt_mock_" + secrets.token_hex(10),
        "type": event_type,
        "livemode": False,
        "mock": True,
        "created": int(time.time()),
        "data": {"object": obj},
    }
