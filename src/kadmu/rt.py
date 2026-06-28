"""Mutable runtime configuration, populated once in app.main() (and by a couple of
runtime setters). Kept in a single module and always referenced as ``rt.NAME`` so
that every reader sees the live value — never a stale copy from ``from rt import X``."""

# Access password (salted SHA-256). Both None => no shared password required.
PW_SALT = None
PW_HASH = None
READONLY = False          # disables all write/file operations (demo / kiosk)
ALLOW_BROWSE = True       # server-side directory picker enabled
LAN_MODE = False          # allow private-IP Host headers
ALLOW_ANY_HOST = False    # escape hatch: disable Host allow-listing
DEMO_ROOT = None          # when set (--demo), the only library root, served read-only
LAUNCH_MODE = "tab"       # how to open the browser: "tab" | "app" | "kiosk"
PROFILES_ENABLED = False  # opt-in per-viewer progress + My List (--profiles)
ACCOUNTS_ENABLED = False  # opt-in real multi-user accounts backed by SQLite (--accounts)
ALLOWED_HOSTS = set()     # hostnames accepted in the Host header
PORT = 8000               # port we serve on (used to build the share URLs)
BIND_HOST = "0.0.0.0"     # socket bind address
LAN_TOGGLEABLE = False    # True when the bind address can reach the LAN (wildcard bind)
SERVER_URLS = []          # URLs shown in Settings, reflecting the sharing state

# Phase 3 — public-hardening & ops
SCHEME = "http"           # "https" once built-in TLS is on (--tls); drives every URL we build
TLS = False               # built-in HTTPS enabled (cert+key supplied via --tls / env)
RATE_LIMIT = True         # per-IP request rate limiting on (loopback always exempt)
LOG_REQUESTS = False      # emit one structured JSON log line per request
ACCESS_LOG_PATH = None    # optional file the structured access log is appended to (else stdout)
