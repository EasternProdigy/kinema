"""coturn ephemeral TURN credentials — the standard TURN REST API / ``use-auth-secret``
scheme, reused as Phase 5's cap-enforcement point.

The control-plane mints a short-lived credential bound to a tenant *only after*
``caps.relay_allowed`` passes; coturn then validates it **locally** with the shared
``static-auth-secret`` (no per-call lookup back to us — the relay stays dumb and cheap).
Because the credential expires in seconds, an over-budget / unsubscribed tenant simply
never receives one, so it can never open a relay allocation. The cap is enforced *before*
bytes flow, not reconciled after.

Wire format (must match cloud/relay/turnserver.conf):
    username = "<expiry-unix-timestamp>:<tenant-id>"
    password = base64( HMAC-SHA1( static-auth-secret, username ) )

stdlib only (``hmac``/``hashlib``/``base64``) — same no-pip ethos as the rest of the core.
"""
from __future__ import annotations
import base64
import hashlib
import hmac

DEFAULT_TTL = 120          # seconds — short on purpose; the browser fetches creds right before connecting


def make_credential(tenant_id: str, secret: str, now: float, ttl: int = DEFAULT_TTL):
    """Return ``(username, password, expiry)`` for ``tenant_id``.

    ``now`` is passed in (not read from the clock) so the minting is pure and unit-testable
    and so the caller controls the time source. ``expiry = int(now) + ttl``.
    """
    if not secret:
        raise ValueError("a TURN static-auth-secret is required to mint credentials")
    ttl = max(1, int(ttl))
    expiry = int(now) + ttl
    username = f"{expiry}:{tenant_id}"
    digest = hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
    password = base64.b64encode(digest).decode("ascii")
    return username, password, expiry


def parse_tenant(username: str):
    """Extract the tenant id from a TURN username (``<exp>:<tenant>``); the inverse coturn's
    Prometheus exporter labels sessions with the username, so the collector recovers the tenant
    from it. Returns ``None`` if the username isn't in our format."""
    if not username or ":" not in username:
        return None
    exp, _, tenant = username.partition(":")
    if not exp.isdigit() or not tenant:
        return None
    return tenant


def verify(username: str, password: str, secret: str, now: float) -> bool:
    """Validate a credential the way coturn does — used by tests (and any future
    self-check). Constant-time compare; rejects expired usernames."""
    if not username or ":" not in username:
        return False
    exp, _, _tenant = username.partition(":")
    try:
        if int(exp) < int(now):
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
    try:
        given = base64.b64decode(password)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, given)


def ice_servers(tenant_id, secret, turn_urls, now, ttl=DEFAULT_TTL, stun_urls=None):
    """Build a WebRTC ``iceServers`` list: STUN (always, free, the default path) plus a TURN
    entry per configured URL sharing one short-lived credential. Returns ``(servers, expiry)``."""
    servers = []
    for s in (stun_urls or ["stun:stun.l.google.com:19302"]):
        servers.append({"urls": s})
    expiry = int(now) + max(1, int(ttl))
    if turn_urls and secret:
        username, password, expiry = make_credential(tenant_id, secret, now, ttl)
        servers.append({
            "urls": list(turn_urls),
            "username": username,
            "credential": password,
        })
    return servers, expiry
