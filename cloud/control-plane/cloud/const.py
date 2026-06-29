"""Constants, paths, env config, and the plan/pricing catalog for the control-plane.

Everything here is read once at import. Secrets and tunables come from the
environment (see ``cloud/.env.example``); nothing sensitive is hard-coded.
"""
from __future__ import annotations
import os
import threading
from pathlib import Path

APP_NAME = "Kadmu Cloud"
APP_VERSION = "0.1.0"

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# This file is cloud/control-plane/cloud/const.py, so APP_DIR (the control-plane
# dir) is two levels up. Web assets sit next to the package; the SQLite DB lives
# under a writable data/ dir alongside it.
APP_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = APP_DIR / "web"
DATA_DIR = Path(os.environ.get("KADMU_CLOUD_DATA") or (APP_DIR / "data"))
DB_PATH = DATA_DIR / "cloud.db"

# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
HOST = os.environ.get("KADMU_CLOUD_HOST", "127.0.0.1")
try:
    PORT = int(os.environ.get("KADMU_CLOUD_PORT", "8787"))
except ValueError:
    PORT = 8787
# Public base URL — used to build Stripe redirect URLs and the dashboard links.
# Behind a reverse proxy in production this is your https://… origin.
BASE_URL = os.environ.get("KADMU_CLOUD_BASE_URL", f"http://{HOST}:{PORT}").rstrip("/")

# --------------------------------------------------------------------------- #
# Stripe (reached over REST with urllib — see stripe_client.py). All optional:
# with no secret key the control-plane runs in MOCK mode and simulates Checkout
# + webhooks locally, so the full flow works with zero Stripe setup.
# --------------------------------------------------------------------------- #
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_API_BASE = "https://api.stripe.com/v1"

# MOCK is on when there's no real key, or forced via KADMU_CLOUD_MODE=mock.
_mode = os.environ.get("KADMU_CLOUD_MODE", "").strip().lower()
if _mode == "live":
    MOCK = False
elif _mode == "mock":
    MOCK = True
else:
    MOCK = not STRIPE_SECRET_KEY

# --------------------------------------------------------------------------- #
# Plan / pricing catalog. price_cents is for display only; the real charge is the
# Stripe Price referenced by `stripe_price` (its env var). In MOCK mode the
# Stripe price is irrelevant — the simulator just records the chosen plan.
# --------------------------------------------------------------------------- #
# Phase 5: each plan carries its relay budget. `relay_cap_bytes` is the monthly TURN-relay
# egress a tenant on this plan may use before the credential endpoint starts refusing relay
# (P2P still works — see cloud/metering/caps.py); 0 ⇒ the plan grants no relay. `relay_max_height`
# is the quality ceiling the connector clamps to on a relay candidate pair (cloud/metering/caps.py).
_GiB = 1024 ** 3

# Tiered feature sets minted into each license (see licensing.issue + features_for_plan).
# The node reads these to light up cloud-delivered conveniences (src/kadmu/cloud.feature):
#   remote        — watch from anywhere (P2P)
#   share_link    — private, time-limited link to one title
#   relay         — TURN relay fallback for hostile NATs (metered + capped, see relay_cap_bytes)
#   backup        — off-site backup of settings/history
#   metadata      — managed TMDB (no key) ·  subtitles — managed subtitle fetch
#   homes         — how many home nodes one account may attach
#   priority_support
# LOCAL player features are NEVER gated here — only cloud conveniences. Free self-host has none
# of these (no cloud), and that's fine: those features simply require the hosted connection.
_PLUS = {"cloud": True, "remote": True, "share_link": True, "relay": True,
         "backup": True, "metadata": True, "subtitles": True, "homes": 1, "priority_support": False}
_FAMILY = {**_PLUS, "homes": 3}
_PRO = {**_PLUS, "homes": 5, "priority_support": True}

PLANS = {
    # --- Plus (the entry plan; ids kept as monthly/yearly for Stripe/webhook continuity) ---
    "monthly": {
        "id": "monthly", "name": "Plus", "tier": "plus", "cadence": "monthly",
        "price_cents": 500, "interval": "month",
        "stripe_price": os.environ.get("STRIPE_PRICE_MONTHLY", ""),
        "blurb": "Watch from anywhere. One home. Cancel anytime.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_MONTHLY_GIB", "100")) * _GiB,
        "relay_max_height": 720, "features": _PLUS,
    },
    "yearly": {
        "id": "yearly", "name": "Plus", "tier": "plus", "cadence": "yearly",
        "price_cents": 5000, "interval": "year",
        "stripe_price": os.environ.get("STRIPE_PRICE_YEARLY", ""),
        "blurb": "Two months free vs. monthly.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_YEARLY_GIB", "100")) * _GiB,
        "relay_max_height": 720, "features": _PLUS,
    },
    # --- Family (multiple homes, 1080p relay, bigger cap) ---
    "family_monthly": {
        "id": "family_monthly", "name": "Family", "tier": "family", "cadence": "monthly",
        "price_cents": 900, "interval": "month",
        "stripe_price": os.environ.get("STRIPE_PRICE_FAMILY_MONTHLY", ""),
        "blurb": "Up to 3 homes, sharp 1080p relay, more headroom.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_FAMILY_GIB", "250")) * _GiB,
        "relay_max_height": 1080, "features": _FAMILY,
    },
    "family_yearly": {
        "id": "family_yearly", "name": "Family", "tier": "family", "cadence": "yearly",
        "price_cents": 9000, "interval": "year",
        "stripe_price": os.environ.get("STRIPE_PRICE_FAMILY_YEARLY", ""),
        "blurb": "Two months free vs. monthly.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_FAMILY_GIB", "250")) * _GiB,
        "relay_max_height": 1080, "features": _FAMILY,
    },
    # --- Pro (power users / many nodes, highest relay, priority support) ---
    "pro_monthly": {
        "id": "pro_monthly", "name": "Pro", "tier": "pro", "cadence": "monthly",
        "price_cents": 1500, "interval": "month",
        "stripe_price": os.environ.get("STRIPE_PRICE_PRO_MONTHLY", ""),
        "blurb": "Up to 5 homes, top relay quality + cap, priority support.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_PRO_GIB", "500")) * _GiB,
        "relay_max_height": 1080, "features": _PRO,
    },
    "pro_yearly": {
        "id": "pro_yearly", "name": "Pro", "tier": "pro", "cadence": "yearly",
        "price_cents": 15000, "interval": "year",
        "stripe_price": os.environ.get("STRIPE_PRICE_PRO_YEARLY", ""),
        "blurb": "Two months free vs. monthly.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_PRO_GIB", "500")) * _GiB,
        "relay_max_height": 1080, "features": _PRO,
    },
    # --- Lifetime (one-time). Relay is deliberately modest: lifetime + uncapped relay is a
    # margin trap, so it leans P2P-first with a small relay allowance. Billed as a one-time
    # Stripe payment (mode=payment) → a perpetual entitlement (see webhooks). ---
    "lifetime": {
        "id": "lifetime", "name": "Lifetime", "tier": "plus", "cadence": "once",
        "price_cents": 14900, "interval": "once", "one_time": True,
        "stripe_price": os.environ.get("STRIPE_PRICE_LIFETIME", ""),
        "blurb": "Pay once. Watch from anywhere forever (P2P-first, modest relay).",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_LIFETIME_GIB", "50")) * _GiB,
        "relay_max_height": 720, "features": {**_PLUS, "lifetime": True},
    },
}
DEFAULT_PLAN = "monthly"

# Plans shown on the public /pricing page, in order (Plus/Family/Pro toggle monthly↔yearly
# in the UI; lifetime stands alone).
PRICING_TIERS = ["plus", "family", "pro"]
PRICING_LIFETIME = "lifetime"


def features_for_plan(plan_id):
    """The feature set to mint into a tenant's license for a given plan. Falls back to
    the default plan's features for an unknown id."""
    p = PLANS.get(plan_id) or PLANS.get(DEFAULT_PLAN) or {}
    return dict(p.get("features") or {"cloud": True, "remote": False})


# Map of plan id → monthly relay-byte cap, handed to the metering layer so a pricing change
# here needs no metering redeploy (cloud/metering/caps.relay_allowed).
PLAN_RELAY_CAPS = {pid: p.get("relay_cap_bytes", 0) for pid, p in PLANS.items()}

# --------------------------------------------------------------------------- #
# TURN relay (Phase 5). The relay itself lives in cloud/relay/ (coturn); the
# control-plane only *mints* short-lived, entitlement-bound credentials it can
# validate (coturn shares TURN_SECRET). All optional: with no TURN_URLS the relay
# endpoint returns STUN-only and the browser stays P2P-only. See cloud/README.md (Scale & cost control).
# --------------------------------------------------------------------------- #
TURN_SECRET = os.environ.get("KADMU_TURN_SECRET", "")
TURN_URLS = [u.strip() for u in os.environ.get("KADMU_TURN_URLS", "").split(",") if u.strip()]
STUN_URLS = [u.strip() for u in os.environ.get(
    "KADMU_STUN_URLS", "stun:stun.l.google.com:19302").split(",") if u.strip()]
try:
    RELAY_CRED_TTL = max(30, int(os.environ.get("KADMU_RELAY_CRED_TTL", "120")))
except ValueError:
    RELAY_CRED_TTL = 120

# Suggested one-time donation amounts (cents) for the OSS side.
DONATION_PRESETS_CENTS = [500, 1500, 5000]
DONATION_MIN_CENTS = 100
DONATION_MAX_CENTS = 1_000_000

# --------------------------------------------------------------------------- #
# Licensing. The control-plane signs short-lived HS256 license tokens with each
# tenant's per-tenant secret; the node verifies them with the same secret (the
# secret is handed to the node once, at provisioning, and never crosses the wire
# afterwards — the node proves possession by HMAC, see entitlements/handler).
# --------------------------------------------------------------------------- #
# How long an issued license token is valid. Kept short so a cancellation an
# online node sees on its next refresh takes effect quickly.
try:
    LICENSE_TTL = max(300, int(os.environ.get("KADMU_CLOUD_LICENSE_TTL", str(24 * 3600))))
except ValueError:
    LICENSE_TTL = 24 * 3600
# Offline grace: how long past a token's expiry the node may keep serving when it
# *cannot reach* the cloud to refresh (brief outages shouldn't stop playback).
# Embedded in the token so the node honours the cloud's policy. Default 7 days.
try:
    OFFLINE_GRACE = max(0, int(os.environ.get("KADMU_CLOUD_OFFLINE_GRACE", str(7 * 86400))))
except ValueError:
    OFFLINE_GRACE = 7 * 86400
# Clock skew the node tolerates against a request's timestamp on the /api/license
# proof (replay window). Small.
LICENSE_PROOF_SKEW = 300

SESSION_TTL = 30 * 24 * 3600          # cloud dashboard sign-in cookie lifetime
SESSION_COOKIE = "kadmu_cloud_session"

# Per-IP login throttle (online brute-force protection on the dashboard sign-in).
LOGIN_MAX_FAILS = 5

PBKDF2_ITERS = 240_000
PW_MIN_LEN = 8

# Routes reachable without a dashboard session (everything the funnel needs before
# you have an account, plus the machine-to-machine + webhook endpoints).
PUBLIC_ROUTES = {
    "/", "/index.html", "/pricing", "/donate", "/login", "/signup",
    "/style.css", "/favicon.svg", "/healthz",
    "/api/signup", "/api/login", "/api/donate",
    "/api/webhook/stripe", "/api/license",
    "/checkout/success", "/checkout/cancel", "/donate/thanks",
}

_lock = threading.Lock()
