"""Network security: Host allow-listing + CSRF/origin checks, the legacy shared-
password sessions and login throttle, the password hash, and the LAN-sharing
toggle + share-URL computation. Depends on const, rt, store."""
from __future__ import annotations
import hashlib
import hmac
import ipaddress
import secrets
import socket
import time
from urllib.parse import urlparse

from . import rt
from .const import (
    SESSIONS, SESSIONS_LOCK, SESSION_TTL, SESSION_MAX,
    LOGIN_LOCK, LOGIN_LOCK_GUARD, LOGIN_MAX_FAILS,
)
from .store import get_config, set_config

# --------------------------------------------------------------------------- #
# Host / Origin / auth helpers (CSRF + DNS-rebinding protection)
# --------------------------------------------------------------------------- #
def local_hostnames():
    names = {"localhost", "127.0.0.1", "::1"}
    try:
        host = socket.gethostname()
        names.add(host.lower())
        for info in socket.getaddrinfo(host, None):
            names.add(str(info[4][0]).lower())
    except OSError:
        pass
    # primary outbound interface IP (best-effort, no traffic actually sent)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # TEST-NET-1, unroutable
        names.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return {n for n in names if n}


def _host_part(value: str):
    """Extract a lowercase hostname from a Host/Origin/Referer value."""
    if not value:
        return ""
    v = value.strip()
    if "://" in v:                       # Origin / Referer
        v = urlparse(v).hostname or ""
        return v.lower()
    # Host header: strip port, handle [::1]:8000
    if v.startswith("["):
        return v[1:v.index("]")].lower() if "]" in v else v.lower()
    return v.rsplit(":", 1)[0].strip().lower()


def host_allowed(host_header: str):
    if rt.ALLOW_ANY_HOST:
        return True
    h = _host_part(host_header)
    if not h:
        return False
    if h in rt.ALLOWED_HOSTS:
        return True
    if rt.LAN_MODE:
        try:
            ip = ipaddress.ip_address(h)
            if ip.is_loopback:
                return True
            # real private LAN addresses only — not 0.0.0.0 or link-local noise
            if ip.is_private and not ip.is_unspecified and not ip.is_link_local:
                return True
        except ValueError:
            pass
    return False


def peer_allowed(ip):
    """Network-level gate, checked at accept() time on the REAL TCP peer address
    (unspoofable, unlike the Host header). Loopback is always allowed; private-LAN
    peers only while network sharing is on; everything when Host allow-listing is
    disabled. This is what lets the in-app LAN toggle take effect without rebinding
    the socket: we always bind 0.0.0.0 and decide here who actually gets served."""
    if rt.ALLOW_ANY_HOST:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if rt.LAN_MODE and addr.is_private and not addr.is_unspecified and not addr.is_link_local:
        return True
    return False


def parse_cookies(header: str):
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out


def new_session():
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with SESSIONS_LOCK:
        # evict expired tokens, then enforce the cap
        for t in [t for t, exp in SESSIONS.items() if exp <= now]:
            SESSIONS.pop(t, None)
        if len(SESSIONS) >= SESSION_MAX:
            SESSIONS.pop(min(SESSIONS, key=SESSIONS.get), None)
        SESSIONS[tok] = now + SESSION_TTL
    return tok


def session_valid(tok):
    if not tok:
        return False
    now = time.time()
    with SESSIONS_LOCK:
        exp = SESSIONS.get(tok)
        if exp is None:
            return False
        if exp <= now:
            SESSIONS.pop(tok, None)
            return False
        return True


def login_check(ip):
    """Returns (allowed, retry_after_seconds)."""
    now = time.time()
    with LOGIN_LOCK_GUARD:
        rec = LOGIN_LOCK.get(ip)
        if rec and rec["until"] > now:
            return False, int(rec["until"] - now) + 1
    return True, 0


def login_fail(ip):
    now = time.time()
    with LOGIN_LOCK_GUARD:
        if len(LOGIN_LOCK) > 4096:
            LOGIN_LOCK.clear()
        rec = LOGIN_LOCK.get(ip) or {"fails": 0, "until": 0}
        rec["fails"] += 1
        if rec["fails"] >= LOGIN_MAX_FAILS:
            rec["until"] = now + min(2 ** (rec["fails"] - LOGIN_MAX_FAILS), 300)
        LOGIN_LOCK[ip] = rec


def login_ok(ip):
    with LOGIN_LOCK_GUARD:
        LOGIN_LOCK.pop(ip, None)



def is_loopback(ip):
    """True for a loopback peer (the box owner, or a same-host reverse proxy)."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def compute_server_urls():
    """The URLs shown in Settings, reflecting the current network-sharing state.
    Uses rt.SCHEME so they read https:// once built-in TLS is on."""
    urls = [f"{rt.SCHEME}://127.0.0.1:{rt.PORT}"]
    if rt.LAN_MODE:
        for ip in sorted(h for h in local_hostnames() if _is_lan_ip(h)):
            urls.append(f"{rt.SCHEME}://{ip}:{rt.PORT}")
    return urls


def set_lan_mode(on):
    """Flip network sharing at runtime (no restart) and remember the choice so the
    next launch keeps it. The socket is already bound to 0.0.0.0; peer_allowed()
    reads rt.LAN_MODE on every new connection, so this takes effect immediately."""
    rt.LAN_MODE = bool(on)
    rt.SERVER_URLS = compute_server_urls()
    cfg = get_config()
    cfg["lan"] = rt.LAN_MODE
    set_config(cfg)



def _hash_pw(salt, pw):
    return hashlib.sha256(("kadmu$" + salt + "$" + pw).encode("utf-8")).hexdigest()


def password_required():
    return rt.PW_HASH is not None


def verify_password(pw):
    if rt.PW_HASH is None:
        return True
    return hmac.compare_digest(_hash_pw(rt.PW_SALT, str(pw or "")), rt.PW_HASH)


def set_password(pw, persist=True):
    """Set, change, or (with an empty value) clear the access password at runtime.
    Stored salted + hashed in config.json so it survives restarts; takes effect for
    new requests immediately. CLI/env passwords pass persist=False (in-memory only)."""
    pw = pw or ""
    if not pw:
        rt.PW_SALT, rt.PW_HASH = None, None
    else:
        rt.PW_SALT = secrets.token_hex(16)
        rt.PW_HASH = _hash_pw(rt.PW_SALT, pw)
    if persist:
        cfg = get_config()
        if rt.PW_HASH:
            cfg["auth"] = {"salt": rt.PW_SALT, "hash": rt.PW_HASH}
        else:
            cfg.pop("auth", None)
        set_config(cfg)



def _is_lan_ip(h):
    try:
        ip = ipaddress.ip_address(h)
        return ip.version == 4 and ip.is_private and not ip.is_loopback
    except ValueError:
        return False
