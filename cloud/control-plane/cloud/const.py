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
# is the quality ceiling the connector clamps to on a relay candidate pair (cloud/metering caps §2.4).
_GiB = 1024 ** 3
PLANS = {
    "monthly": {
        "id": "monthly",
        "name": "Kadmu Cloud",
        "cadence": "monthly",
        "price_cents": 500,
        "interval": "month",
        "stripe_price": os.environ.get("STRIPE_PRICE_MONTHLY", ""),
        "blurb": "Accounts, billing, and managed convenience. Cancel anytime.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_MONTHLY_GIB", "100")) * _GiB,
        "relay_max_height": 720,
    },
    "yearly": {
        "id": "yearly",
        "name": "Kadmu Cloud",
        "cadence": "yearly",
        "price_cents": 5000,
        "interval": "year",
        "stripe_price": os.environ.get("STRIPE_PRICE_YEARLY", ""),
        "blurb": "Two months free vs. monthly.",
        "relay_cap_bytes": int(os.environ.get("KADMU_RELAY_CAP_YEARLY_GIB", "100")) * _GiB,
        "relay_max_height": 720,
    },
}
DEFAULT_PLAN = "monthly"

# Map of plan id → monthly relay-byte cap, handed to the metering layer so a pricing change
# here needs no metering redeploy (cloud/metering/caps.relay_allowed).
PLAN_RELAY_CAPS = {pid: p.get("relay_cap_bytes", 0) for pid, p in PLANS.items()}

# --------------------------------------------------------------------------- #
# TURN relay (Phase 5). The relay itself lives in cloud/relay/ (coturn); the
# control-plane only *mints* short-lived, entitlement-bound credentials it can
# validate (coturn shares TURN_SECRET). All optional: with no TURN_URLS the relay
# endpoint returns STUN-only and the browser stays P2P-only. See PHASE_5_DESIGN §2.
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
