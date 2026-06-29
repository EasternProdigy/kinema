"""Process entry point: the threaded HTTP server, the cache/trash/session janitor,
browser launching, and main() (CLI args, runtime config, startup). Imports
everything; run via the src/server.py shim."""
from __future__ import annotations
import argparse
import ipaddress
import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from . import rt
from . import cloud
from .handler import Handler
from .const import (
    APP_NAME, APP_VERSION, CACHE_DIR, CACHE_MAX_BYTES, CACHE_SWEEP_INTERVAL,
    CACHE_TTL, DATA_DIR, FFMPEG, HLS_DIR, REMUX_DIR, STATE_DIR, STORYBOARD_DIR, TRASH_TTL,
)
from .accounts import (
    create_user, db_logout_user_sessions, db_purge_sessions, get_user_by_name,
    init_db, set_user_password, set_user_role, signup_open, user_count,
)
from .store import get_config, real_roots, set_config
from .security import (
    _host_part, _is_lan_ip, compute_server_urls, local_hostnames,
    password_required, peer_allowed, set_password,
)
from .media import build_demo_library, prune_cache
from .library import purge_trash, start_indexer
from . import tmdb, enrich, dlna

def _cache_janitor():
    """Background sweep: every CACHE_SWEEP_INTERVAL seconds, clear out prepared
    files no one is watching (idle past CACHE_TTL), keeping the cache to roughly
    just the current video. Also reaps long-dead trash so deletes can't fill the disk."""
    while True:
        time.sleep(CACHE_SWEEP_INTERVAL)
        try:
            prune_cache(REMUX_DIR, CACHE_MAX_BYTES, CACHE_TTL)
        except Exception:
            pass
        try:
            prune_cache(HLS_DIR, CACHE_MAX_BYTES, CACHE_TTL)   # on-demand HLS segments
        except Exception:
            pass
        try:
            # storyboards are small and worth keeping for the session — size-cap only
            prune_cache(STORYBOARD_DIR, 256 * 1024 * 1024, None)
        except Exception:
            pass
        if TRASH_TTL >= 0:
            try:
                purge_trash(TRASH_TTL)
            except Exception:
                pass
        if rt.ACCOUNTS_ENABLED:
            try:
                db_purge_sessions()      # reap expired persistent sessions
            except Exception:
                pass


def start_cache_janitor():
    t = threading.Thread(target=_cache_janitor, name="cache-janitor", daemon=True)
    t.start()



class KadmuServer(ThreadingHTTPServer):
    """Threading server built to stay up no matter what a client does. A dropped
    or misbehaving connection must never crash the process or spam tracebacks
    during a long-running session — that's the whole point of running for hours."""
    daemon_threads = True          # handler threads never block shutdown
    allow_reuse_address = True
    request_queue_size = 128       # absorb short connection bursts instead of refusing

    def verify_request(self, request, client_address):
        # Decided at accept() time, before any HTTP is read — a rejected peer's
        # connection is closed immediately. Uses the real peer IP, so it can't be
        # bypassed with a forged Host header.
        return peer_allowed(client_address[0] if client_address else "")

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        # client went away mid-request (closed tab, sleeping phone, paused
        # stream) — completely expected; stay silent and keep serving.
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError, socket.timeout)):
            return
        # anything else: a one-line note, but the server stays up.
        try:
            who = client_address[0] if client_address else "?"
            print(f"  (handled request error from {who}: {type(exc).__name__})")
        except Exception:
            pass


def _probe_kadmu(port, scheme="http"):
    """True if a Kadmu instance is already answering on this port (so a second
    launch can just open a tab instead of crashing on a port clash)."""
    ctx = None
    if scheme == "https":
        import ssl
        ctx = ssl._create_unverified_context()   # self-signed LAN certs are expected
    try:
        with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/api/session",
                                    timeout=1.5, context=ctx) as r:
            return json.loads(r.read() or b"{}").get("app") == APP_NAME
    except Exception:
        return False


def _firefox_path():
    """Locate the Firefox executable (used by the app/kiosk window modes)."""
    for name in ("firefox", "firefox-esr"):
        p = shutil.which(name)
        if p:
            return p
    guesses = []
    if sys.platform == "darwin":
        guesses = ["/Applications/Firefox.app/Contents/MacOS/firefox",
                   str(Path.home() / "Applications/Firefox.app/Contents/MacOS/firefox")]
    elif os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                guesses.append(str(Path(base) / "Mozilla Firefox" / "firefox.exe"))
    for g in guesses:
        if Path(g).exists():
            return g
    return None


def _launch_browser(port):
    """Open Kadmu in the browser according to rt.LAUNCH_MODE:
      tab    - a new tab in your normal browser (Firefox preferred) [default]
      app    - a dedicated Kadmu window (its own Firefox profile, not a tab)
      kiosk  - fullscreen with no browser chrome (TV / cinema mode)
    app/kiosk fall back to a normal tab if Firefox can't be located."""
    url = f"{rt.SCHEME}://127.0.0.1:{port}"
    if rt.LAUNCH_MODE in ("app", "kiosk"):
        ff = _firefox_path()
        if ff:
            try:
                profile = STATE_DIR / "app-profile"
                profile.mkdir(parents=True, exist_ok=True)
                cmd = [ff, "--no-remote", "--profile", str(profile),
                       "--kiosk" if rt.LAUNCH_MODE == "kiosk" else "--new-window", url]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass  # fall back to a normal tab below
    try:
        try:
            webbrowser.get("firefox").open_new_tab(url)
        except webbrowser.Error:
            webbrowser.open_new_tab(url)
    except Exception:
        pass



def main():

    parser = argparse.ArgumentParser(
        prog="kadmu", description=f"{APP_NAME} - a personal cinema in a browser tab")
    parser.add_argument("roots", nargs="*", help="library folder(s) to add")
    parser.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("KADMU_PORT", 8000)))
    parser.add_argument("--lan", action="store_true",
                        help="serve on your whole local network (binds 0.0.0.0)")
    parser.add_argument("--password", default=os.environ.get("KADMU_PASSWORD"),
                        help="require this password to access (recommended with --lan)")
    parser.add_argument("--read-only", action="store_true",
                        default=os.environ.get("KADMU_READONLY") in ("1", "true", "yes"),
                        help="disable all file management (demo / kiosk mode)")
    parser.add_argument("--demo", action="store_true",
                        help="try Kadmu instantly: auto-generate sample videos, serve read-only")
    parser.add_argument("--no-browse", action="store_true",
                        help="disable the server-side folder picker")
    parser.add_argument("--allowed-host", action="append", default=[],
                        help="extra hostname/domain allowed in the Host header (repeatable)")
    parser.add_argument("--allow-any-host", action="store_true",
                        help="disable Host allow-listing (NOT recommended)")
    parser.add_argument("--app", action="store_true",
                        help="open in a dedicated Kadmu window (its own app window, not a browser tab)")
    parser.add_argument("--kiosk", action="store_true",
                        help="open fullscreen with no browser chrome (TV / cinema mode)")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    parser.add_argument("--profiles", action="store_true",
                        default=os.environ.get("KADMU_PROFILES") in ("1", "true", "yes"),
                        help="enable opt-in per-viewer profiles (separate resume + My List)")
    parser.add_argument("--accounts", action="store_true",
                        default=os.environ.get("KADMU_ACCOUNTS") in ("1", "true", "yes"),
                        help="enable real multi-user accounts (sign-in, per-user data, roles)")
    parser.add_argument("--reset-password", metavar="USERNAME", default=None,
                        help="reset (or create, as admin) an account's password, then exit. "
                             "Uses KADMU_NEW_PASSWORD if set, else prints a random one.")
    parser.add_argument("--tls", nargs=2, metavar=("CERT", "KEY"), default=None,
                        help="serve HTTPS with this PEM certificate and private key "
                             "(else KADMU_TLS_CERT / KADMU_TLS_KEY)")
    parser.add_argument("--log-requests", action="store_true",
                        default=os.environ.get("KADMU_LOG_REQUESTS") in ("1", "true", "yes"),
                        help="emit one structured JSON log line per request")
    parser.add_argument("--no-rate-limit", action="store_true",
                        default=os.environ.get("KADMU_RATE_LIMIT") in ("0", "false", "no"),
                        help="disable per-IP request rate limiting (LAN peers only; "
                             "loopback is always exempt)")
    parser.add_argument("--cloud", metavar="URL", default=os.environ.get("KADMU_CLOUD_URL"),
                        help="run as a Kadmu Cloud tenant: the control-plane base URL "
                             "(also needs --tenant and KADMU_CLOUD_SECRET)")
    parser.add_argument("--tenant", metavar="ID", default=os.environ.get("KADMU_CLOUD_TENANT"),
                        help="this node's Kadmu Cloud tenant id (from your dashboard)")
    parser.add_argument("--cdn", action="store_true",
                        default=os.environ.get("KADMU_CDN") in ("1", "true", "yes"),
                        help="emit immutable long-cache headers + ?v=APP_VERSION on the static "
                             "app shell (for serving behind a CDN; off for normal self-host)")
    parser.add_argument("--dlna", action="store_true",
                        default=os.environ.get("KADMU_DLNA") in ("1", "true", "yes"),
                        help="advertise a DLNA/UPnP MediaServer so smart TVs / consoles can "
                             "play your library natively (LAN-local; implies network sharing)")
    parser.add_argument("--tv", action="store_true",
                        default=os.environ.get("KADMU_TV") in ("1", "true", "yes"),
                        help="default the interface into 10-foot 'TV mode' (bigger UI + "
                             "arrow-key / D-pad navigation) — for a couch / set-top install")
    parser.add_argument("--cast", action="store_true",
                        default=os.environ.get("KADMU_CAST") in ("1", "true", "yes"),
                        help="enable the Chromecast sender (loads Google's Cast SDK in the "
                             "browser; off by default — the only feature that fetches a 3rd-party "
                             "script). Best on an open LAN; DLNA stays the privacy-pure path")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args()

    mode_env = os.environ.get("KADMU_LAUNCH_MODE", "").strip().lower()
    rt.LAUNCH_MODE = ("kiosk" if (args.kiosk or mode_env == "kiosk")
                   else "app" if (args.app or mode_env == "app")
                   else "tab")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    rt.ACCOUNTS_ENABLED = bool(args.accounts) or bool(args.reset_password)
    rt.PROFILES_ENABLED = bool(args.profiles)
    # Household mode: --accounts + --profiles together = one login, multiple sub-profiles
    # (the account's own data is the "Me" profile; sub-profiles store theirs in JSON under
    # data/accounts/<uid>/, so the accounts DB is untouched). Either flag alone is unchanged.
    if rt.ACCOUNTS_ENABLED:
        init_db()

    # Recovery escape hatch: reset (or create, as admin) an account from the console,
    # for when the only admin is locked out. Local console access == box owner.
    if args.reset_password:
        uname = args.reset_password
        new_pw = os.environ.get("KADMU_NEW_PASSWORD") or secrets.token_urlsafe(9)
        row = get_user_by_name(uname)
        if row:
            ok, err = set_user_password(row["id"], new_pw)
            if not ok:
                print(f"  Couldn't reset '{uname}': {err}")
                sys.exit(1)
            db_logout_user_sessions(row["id"])
            set_user_role(row["id"], "admin")
            print(f"  Reset password for '{uname}' (now an admin).")
        else:
            user, err = create_user(uname, new_pw, role="admin")
            if err:
                print(f"  Couldn't create '{uname}': {err}")
                sys.exit(1)
            set_user_role(user["id"], "admin")
            print(f"  Created admin account '{uname}'.")
        print(f"  Temporary password: {new_pw}")
        print("  Sign in, then change it in Settings → Account.")
        return

    start_cache_janitor()   # regularly clears prepared files you're no longer watching

    # ops / hardening flags (Phase 3)
    rt.RATE_LIMIT = not args.no_rate_limit
    rt.LOG_REQUESTS = bool(args.log_requests)
    rt.CDN = bool(args.cdn)
    rt.ACCESS_LOG_PATH = os.environ.get("KADMU_ACCESS_LOG") or None

    # Optional built-in TLS: cert+key from --tls or KADMU_TLS_CERT/KADMU_TLS_KEY.
    # We set the scheme now (so every URL we build/probe is correct) and build the
    # SSL context here, failing fast on a bad cert; the socket is wrapped once the
    # server is created below. A reverse proxy (see deploy/Caddyfile) stays the
    # recommended path for public HTTPS; this is for direct LAN serving.
    tls_cert = (args.tls[0] if args.tls else os.environ.get("KADMU_TLS_CERT")) or None
    tls_key = (args.tls[1] if args.tls else os.environ.get("KADMU_TLS_KEY")) or None
    rt.TLS = bool(tls_cert and tls_key)
    rt.SCHEME = "https" if rt.TLS else "http"
    ssl_ctx = None
    if rt.TLS:
        import ssl
        if not (Path(tls_cert).is_file() and Path(tls_key).is_file()):
            print(f"  TLS cert/key not found — check '{tls_cert}' and '{tls_key}'.")
            sys.exit(1)
        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
        except (ssl.SSLError, OSError) as e:
            print(f"  Couldn't load the TLS certificate/key: {e}")
            sys.exit(1)

    # Already running? Act like a normal desktop app: just open a new tab and
    # exit, instead of crashing trying to re-bind the port. This makes every
    # entry point (the .exe, the `kadmu` command, double-clicking a launcher
    # twice) idempotent.
    if _probe_kadmu(args.port, rt.SCHEME):
        print(f"  {APP_NAME} is already running at {rt.SCHEME}://127.0.0.1:{args.port}")
        if not args.no_open:
            print("  Opening it in your browser...")
            _launch_browser(args.port)
        return

    # roots from CLI -> config (skipped in demo mode, which uses its own root)
    if args.roots and not args.demo:
        cfg = get_config()
        existing = list(cfg.get("roots", []))
        for r in args.roots:
            try:
                p = Path(r).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and str(p) not in existing:
                existing.append(str(p))
            elif not p.is_dir():
                print(f"  (skipping '{r}': not a folder)")
        cfg["roots"] = existing
        set_config(cfg)

    # security config
    rt.PORT = args.port
    # Always bind 0.0.0.0 so network sharing can be switched on from the app
    # without a restart; peer_allowed() (via KadmuServer.verify_request) keeps it
    # loopback-only until sharing is actually on. An explicit --host is still honoured.
    # DLNA is inherently a LAN feature (TVs/consoles on your network), so enabling it
    # turns on network sharing too. Off by default; opt-in via --dlna / KADMU_DLNA.
    rt.DLNA = bool(args.dlna)
    rt.TV = bool(args.tv)            # UI hint: the frontend defaults into 10-foot mode
    rt.CAST = bool(args.cast)        # opt-in Chromecast sender (relaxes CSP for the Cast SDK)
    rt.LAN_MODE = bool(args.lan) or bool(args.dlna) or bool(get_config().get("lan"))
    bind_host = args.host or "0.0.0.0"
    rt.BIND_HOST = bind_host
    try:
        rt.LAN_TOGGLEABLE = ipaddress.ip_address(_host_part(bind_host) or bind_host).is_unspecified
    except ValueError:
        rt.LAN_TOGGLEABLE = False
    # CLI/env --password wins for this run (in-memory only); otherwise restore a
    # password set earlier from the app itself (persisted, hashed, in config.json).
    # The single shared password is bypassed entirely in accounts mode (each user
    # has their own), so don't bother restoring it there.
    if not rt.ACCOUNTS_ENABLED:
        if args.password:
            set_password(args.password, persist=False)
        else:
            _saved = get_config().get("auth")
            if isinstance(_saved, dict) and _saved.get("salt") and _saved.get("hash"):
                rt.PW_SALT, rt.PW_HASH = _saved["salt"], _saved["hash"]
    rt.READONLY = bool(args.read_only)
    rt.ALLOW_BROWSE = not args.no_browse
    rt.ALLOW_ANY_HOST = args.allow_any_host

    # Cloud-attach (Phase 4a): become a Kadmu Cloud tenant when URL + tenant + secret
    # are all present. The secret is read only from the environment, never from argv.
    cloud_secret = os.environ.get("KADMU_CLOUD_SECRET", "")
    if args.cloud and args.tenant and cloud_secret:
        rt.CLOUD_ENABLED = True
        rt.CLOUD_URL = args.cloud.rstrip("/")
        rt.CLOUD_TENANT = args.tenant
        rt.CLOUD_SECRET = cloud_secret
        cloud.configure()      # load any persisted license so offline grace survives a restart
    elif args.cloud or args.tenant or cloud_secret:
        print("  NOTE: cloud-attach needs --cloud URL + --tenant ID + KADMU_CLOUD_SECRET "
              "all set — running as plain self-host (fully unlocked).")

    if args.demo:
        demo_dir = STATE_DIR / "demo-library"
        print("  Preparing demo library (generating sample clips, one moment)...")
        if not build_demo_library(demo_dir):
            print("  WARNING: couldn't generate demo clips (is ffmpeg available?).")
        rt.DEMO_ROOT = demo_dir.resolve()
        rt.READONLY = True
        rt.ALLOW_BROWSE = False

    env_hosts = os.environ.get("KADMU_ALLOWED_HOSTS", "")
    extra = set(args.allowed_host) | {h.strip() for h in env_hosts.split(",") if h.strip()}
    rt.ALLOWED_HOSTS = {h.lower() for h in (local_hostnames() | extra)}
    bh = _host_part(bind_host) or bind_host
    try:
        # never allow-list a wildcard bind address (0.0.0.0 / ::)
        if not ipaddress.ip_address(bh).is_unspecified:
            rt.ALLOWED_HOSTS.add(bh)
    except ValueError:
        rt.ALLOWED_HOSTS.add(bh)

    rt.SERVER_URLS = compute_server_urls()
    lan_ips = sorted(h for h in local_hostnames() if _is_lan_ip(h)) if rt.LAN_MODE else []

    print("=" * 64)
    print(f"  {APP_NAME} {APP_VERSION}  -  a personal cinema in a browser tab")
    print("  by Pentarosa Co.  -  MIT licensed")
    print("=" * 64)
    print(f"  Local:   {rt.SCHEME}://127.0.0.1:{args.port}")
    for ip in lan_ips:
        print(f"  Network: {rt.SCHEME}://{ip}:{args.port}   (open this on your phone/TV)")
    roots = real_roots()
    if roots:
        print("  Library:")
        for r in roots:
            print(f"    - {r}")
    else:
        print("  No library folders yet - add one in Settings (gear icon).")
    if rt.ACCOUNTS_ENABLED:
        n_users = user_count()
        if n_users == 0:
            print("  Login:   accounts mode — open the page to create the owner account")
        else:
            print(f"  Login:   accounts mode ({n_users} user{'s' if n_users != 1 else ''}; "
                  f"sign-ups {'open' if signup_open() else 'closed'})")
    else:
        print(f"  Login:   {'password required' if password_required() else 'none (anyone on an allowed host)'}")
    if rt.CLOUD_ENABLED:
        print(f"  Cloud:   tenant {rt.CLOUD_TENANT} @ {rt.CLOUD_URL} (subscription-gated)")
        if not rt.ACCOUNTS_ENABLED:
            print("           (tip: Kadmu Cloud is built for accounts — add --accounts)")
    print(f"  Mode:    {'DEMO (read-only)' if args.demo else ('READ-ONLY' if rt.READONLY else 'full control')}")
    print(f"  ffmpeg:  {FFMPEG or 'NOT found (thumbnails disabled)'}")
    if rt.TLS:
        print("  TLS:     on (built-in HTTPS)")
    if rt.LOG_REQUESTS:
        print(f"  Logging: structured request log -> {rt.ACCESS_LOG_PATH or 'stdout'}")
    if rt.LAN_MODE and not rt.ACCOUNTS_ENABLED and not password_required():
        print("  NOTE: sharing is on with no password — anyone on your network can watch & manage. Set one in Settings.")
    print("  Press Ctrl+C to stop.")
    print("=" * 64)

    mimetypes.init()
    try:
        httpd = KadmuServer((bind_host, args.port), Handler)
    except OSError as e:
        print(f"  Couldn't start on port {args.port}: {e}")
        print("  Another program may be using it — try a different --port.")
        sys.exit(1)
    httpd.daemon_threads = True
    if ssl_ctx is not None:
        # Wrap the listening socket so every accepted connection speaks TLS.
        httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)

    # Build the search catalog in the background now that the roots are finalized,
    # so the first search is instant and complete.
    start_indexer()

    # TMDB metadata layer (optional): load the saved key (env still wins) and start
    # the enrichment worker, which matches the library to TMDB once the index is up.
    tmdb.set_key(get_config().get("tmdbKey"))
    enrich.start_enricher()
    if tmdb.enabled():
        enrich.request_enrich()

    # DLNA/UPnP (opt-in): advertise a MediaServer so smart TVs / consoles find Kadmu on
    # the LAN and play natively. LAN-local — the node serves the bytes directly, zero
    # cloud egress. The HTTP /dlna/* endpoints are live via rt.DLNA; this is discovery.
    if rt.DLNA:
        if dlna.start(args.port):
            print("  DLNA:    on — look for "
                  f"'{dlna.friendly_name()}' in your TV / console media player")
        else:
            print("  DLNA:    endpoints live, but SSDP discovery couldn't start "
                  "(port 1900 busy — another DLNA server?). TVs may not auto-find it.")

    # Cloud-attach: do an initial license check, then keep it fresh in the background.
    cloud.start_poller()

    if not args.no_open:
        def _open():
            time.sleep(0.6)
            _launch_browser(args.port)
        threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {APP_NAME} stopped. Bye!")
    finally:
        if rt.DLNA:
            dlna.stop()          # send the SSDP byebye so renderers drop us cleanly
        httpd.server_close()

