"""Cloud-attach entitlement client (Phase 4a).

When this node is run as a **Kadmu Cloud tenant** — given a cloud URL, a tenant id,
and the tenant secret (env ``KADMU_CLOUD_*`` or ``--cloud``/``--tenant``) — this
module polls the control-plane for a short-lived, signed **license token**, verifies
it locally, and caches it (on disk) with an **offline grace window** so brief cloud
outages, and even node restarts during one, don't stop playback.

Default self-host (no cloud config) never enables any of this and stays fully
unlocked — ``entitlement_state()`` reports ``self-host`` and the gate is a no-op.

Standard library only. The HMAC-SHA256 verify here mirrors the signer in
``cloud/control-plane/cloud/licensing.py``; the secret never crosses the wire (the
node proves possession by HMAC-signing ``<tenant>.<ts>``).
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

from . import rt
from .const import CLOUD_LICENSE_PATH, load_json, save_json

# How often to refresh while healthy, and how soon to retry after a failure.
REFRESH_OK = 6 * 3600
REFRESH_RETRY = 300
HTTP_TIMEOUT = 12

_lock = threading.Lock()
# Cached license + last-poll status. token/payload come from the cloud; `online`
# reflects whether the *last* attempt reached the cloud; `explicit_inactive` is set
# only when the cloud told us, online, that there's no active subscription.
_state = {
    "token": None, "payload": None, "fetched": 0.0,
    "online": False, "explicit_inactive": False, "last_error": "", "checked": 0.0,
}


# --------------------------------------------------------------------------- #
# Token verification (mirror of the cloud signer)
# --------------------------------------------------------------------------- #
def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify(token: str, secret: str):
    """Return the license payload if the HS256 signature checks out, else None.
    Does not check expiry — entitlement_state() interprets iat/exp/grace."""
    try:
        h, p, sig = token.split(".")
    except (ValueError, AttributeError):
        return None
    signing_input = f"{h}.{p}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        given = _b64u_decode(sig)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        return json.loads(_b64u_decode(p))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Config + cache persistence
# --------------------------------------------------------------------------- #
def configure():
    """Load any persisted license so offline grace survives a restart. Called from
    app.main() after rt.CLOUD_* are set; a no-op when cloud-attach is off."""
    if not rt.CLOUD_ENABLED:
        return
    cached = load_json(CLOUD_LICENSE_PATH, None)
    if isinstance(cached, dict) and cached.get("token"):
        payload = verify(cached["token"], rt.CLOUD_SECRET)
        if payload and payload.get("tenant") == rt.CLOUD_TENANT:
            with _lock:
                _state["token"] = cached["token"]
                _state["payload"] = payload
                _state["fetched"] = float(cached.get("fetched", 0))


def _persist():
    try:
        save_json(CLOUD_LICENSE_PATH, {
            "token": _state["token"], "fetched": _state["fetched"],
            "tenant": rt.CLOUD_TENANT,
        })
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Polling the control-plane
# --------------------------------------------------------------------------- #
def fetch_once():
    """One license refresh. Updates _state; returns True if the cloud was reached
    (regardless of entitlement), False on a network error."""
    ts = str(int(time.time()))
    sig = hmac.new(rt.CLOUD_SECRET.encode("utf-8"),
                   f"{rt.CLOUD_TENANT}.{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
    body = json.dumps({"tenant": rt.CLOUD_TENANT, "ts": ts, "sig": sig}).encode("utf-8")
    req = urllib.request.Request(f"{rt.CLOUD_URL}/api/license", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            data = json.loads(r.read() or b"{}")
        return _apply_response(200, data)
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except (ValueError, TypeError):
            data = {}
        return _apply_response(e.code, data)
    except (urllib.error.URLError, OSError, ValueError) as e:
        with _lock:
            _state["online"] = False
            _state["last_error"] = str(e)
            _state["checked"] = time.time()
        return False


def _apply_response(code, data):
    now = time.time()
    with _lock:
        _state["checked"] = now
        _state["online"] = True
        _state["last_error"] = ""
        if code == 200 and data.get("ok") and data.get("license"):
            payload = verify(data["license"], rt.CLOUD_SECRET)
            if payload and payload.get("tenant") == rt.CLOUD_TENANT:
                _state["token"] = data["license"]
                _state["payload"] = payload
                _state["fetched"] = now
                _state["explicit_inactive"] = False
                _persist()
                return True
            _state["last_error"] = "license failed verification"
            return True
        if code == 402:
            # The cloud told us, online, that there's no active subscription.
            _state["explicit_inactive"] = True
            return True
        _state["last_error"] = data.get("error") or f"HTTP {code}"
        return True


def _poller():
    while rt.CLOUD_ENABLED:
        ok = fetch_once()
        active = entitlement_active()
        time.sleep(REFRESH_OK if (ok and active) else REFRESH_RETRY)


def start_poller():
    """Kick off an immediate fetch, then refresh in the background. The first fetch
    is synchronous (short) so a healthy node isn't briefly gated at startup; if the
    cloud is unreachable, any persisted license + grace covers the gap."""
    if not rt.CLOUD_ENABLED:
        return
    try:
        fetch_once()
    except Exception:
        pass
    threading.Thread(target=_poller, name="cloud-license", daemon=True).start()


# --------------------------------------------------------------------------- #
# Entitlement state (read by the gate + /api/session)
# --------------------------------------------------------------------------- #
def entitlement_state():
    """A small dict describing whether this instance may serve the Cloud experience.
    Self-host (cloud off) is always active. Cloud-attached: active while the cached
    license is unexpired; active-in-grace while expired-but-within-grace AND the cloud
    is currently unreachable (so we can't confirm a cancellation); otherwise inactive."""
    if not rt.CLOUD_ENABLED:
        return {"active": True, "status": "self-host", "cloud": False}
    now = time.time()
    with _lock:
        st = dict(_state)
    if st["explicit_inactive"]:
        return {"active": False, "status": "inactive", "cloud": True,
                "reason": "no_active_subscription", "manageUrl": rt.CLOUD_URL + "/dashboard"}
    payload = st["payload"]
    if not payload:
        # Never got a license (cold start, cloud unreachable, or bad config).
        return {"active": False, "status": "pending" if not st["checked"] else "unverified",
                "cloud": True, "reason": st["last_error"] or "no license yet",
                "manageUrl": rt.CLOUD_URL + "/dashboard"}
    exp = float(payload.get("exp", 0))
    grace = float(payload.get("grace", 0))
    feats = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    base = {"cloud": True, "plan": payload.get("plan"), "features": feats,
            "until": exp, "manageUrl": rt.CLOUD_URL + "/dashboard"}
    if now < exp:
        return {**base, "active": True, "status": payload.get("status", "active")}
    if now < exp + grace and not st["online"]:
        # Expired, but the cloud is unreachable — ride the offline grace window.
        return {**base, "active": True, "status": "grace", "grace": True,
                "graceUntil": exp + grace}
    return {**base, "active": False,
            "status": "expired" if not st["online"] else "inactive",
            "reason": "license expired"}


def entitlement_active():
    return entitlement_state()["active"]


def feature(name, default=False):
    """Whether the active license grants a named cloud feature (e.g. 'remote',
    'share_link', 'backup'). Self-host (cloud off) returns `default` — local features
    are never gated this way; this only governs cloud-delivered conveniences."""
    st = entitlement_state()
    if not st.get("cloud"):
        return default
    if not st.get("active"):
        return False
    feats = st.get("features") or {}
    return bool(feats.get(name, default))


def plan_label():
    """A human label for the current plan ('Self-host' when not cloud-attached)."""
    st = entitlement_state()
    if not st.get("cloud"):
        return "Self-host"
    return (st.get("plan") or "Kadmu Cloud").replace("_", " ").title()
