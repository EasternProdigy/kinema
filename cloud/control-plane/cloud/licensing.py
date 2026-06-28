"""License tokens — compact, JWT-style, HMAC-SHA256 (HS256) signed with a tenant's
per-tenant secret.

The control-plane *signs*; a tenant's self-host node *verifies* with the same
secret (handed over once at provisioning, see entitlements.provision_tenant). The
node keeps the token only as long as it's valid and honours the embedded offline
grace window when it can't reach the cloud to refresh — see src/kadmu/cloud.py,
which mirrors the verify here. The format is intentionally tiny and dependency-free
(no public-key crypto, which the stdlib lacks); a future hardening pass could move
to asymmetric keys.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time

from .const import LICENSE_TTL, OFFLINE_GRACE

HEADER = {"alg": "HS256", "typ": "KADMU-LICENSE"}


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign(payload: dict, secret: str) -> str:
    head = dict(HEADER)
    head["kid"] = payload.get("tenant", "")
    h = _b64u(json.dumps(head, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    p = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


def verify(token: str, secret: str):
    """Return the payload dict if the signature is valid (NOT checking expiry —
    callers decide what to do with iat/exp/grace), else None. Mirrored on the node."""
    try:
        h, p, s = token.split(".")
    except (ValueError, AttributeError):
        return None
    signing_input = f"{h}.{p}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        given = _b64u_decode(s)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        return json.loads(_b64u_decode(p))
    except (ValueError, TypeError):
        return None


def issue(tenant_id, secret, account_id, plan, status, period_end, features=None):
    """Build and sign a license token for an *entitled* tenant. Short-lived (exp =
    now + LICENSE_TTL) with the offline-grace policy baked in so the node can ride
    out brief cloud outages without dropping playback."""
    now = int(time.time())
    payload = {
        "tenant": tenant_id,
        "account": account_id,
        "plan": plan,
        "status": status,                 # 'active' | 'trialing' | ...
        "iat": now,
        "exp": now + LICENSE_TTL,
        "grace": OFFLINE_GRACE,           # extra seconds past exp the node may serve when offline
        "periodEnd": int(period_end or 0),
        "features": features or {"cloud": True, "remote": False},  # remote (P2P) is Phase 4b
    }
    return sign(payload, secret), payload
