"""Public-hardening & ops (Phase 3): in-memory metrics, structured request logging,
a per-IP request rate limiter, per-identity concurrent-stream accounting, and a
bandwidth meter. Stdlib only; depends on const + rt and nothing else in the package,
so it sits low in the import graph (handler imports it). Everything degrades to a
cheap no-op when its feature flag is off."""
from __future__ import annotations
import json
import sys
import threading
import time

from . import rt
from .const import (
    APP_VERSION, RATE_BURST, RATE_LIMIT_MAX_IPS, RATE_RPS, USER_MAX_STREAMS,
)

_START = time.time()        # process start (module import) — basis for uptime


def uptime() -> float:
    return time.time() - _START


# --------------------------------------------------------------------------- #
# Metrics (a handful of counters, exposed in Prometheus text format at /metrics)
# --------------------------------------------------------------------------- #
_metrics_lock = threading.Lock()
_requests_total = 0
_responses_by_class = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
_bytes_sent_total = 0
_errors_total = 0
_rate_limited_total = 0
_stream_rejected_total = 0
# Per-identity bytes served — the bandwidth meter. Keyed by "user:<id>" in accounts
# mode or "ip:<addr>" otherwise. Only surfaced per-label in /metrics when accounts
# are on (a bounded set); IP identities would be unbounded label cardinality.
_id_bytes: dict[str, int] = {}


def record_request(status: int) -> None:
    global _requests_total
    cls = f"{status // 100}xx"
    with _metrics_lock:
        _requests_total += 1
        if cls in _responses_by_class:
            _responses_by_class[cls] += 1


def record_error() -> None:
    global _errors_total
    with _metrics_lock:
        _errors_total += 1


def note_rate_limited() -> None:
    global _rate_limited_total
    with _metrics_lock:
        _rate_limited_total += 1


def note_stream_rejected() -> None:
    global _stream_rejected_total
    with _metrics_lock:
        _stream_rejected_total += 1


def add_bytes(identity: str, n: int) -> None:
    """Count bytes written for a response body — the live bandwidth meter. Called
    as data is streamed, so the per-identity total reflects in-flight transfers too."""
    global _bytes_sent_total
    if n <= 0:
        return
    with _metrics_lock:
        _bytes_sent_total += n
        if identity:
            # bound the table in IP mode so a flood of distinct peers can't grow it
            if len(_id_bytes) > RATE_LIMIT_MAX_IPS:
                _id_bytes.clear()
            _id_bytes[identity] = _id_bytes.get(identity, 0) + n


def _esc_label(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_metrics() -> str:
    """Prometheus text exposition (v0.0.4). Plain text, no deps."""
    with _metrics_lock:
        reqs = _requests_total
        classes = dict(_responses_by_class)
        sent = _bytes_sent_total
        errs = _errors_total
        rl = _rate_limited_total
        sr = _stream_rejected_total
        per_user = dict(_id_bytes) if rt.ACCOUNTS_ENABLED else {}
    out: list[str] = []

    def metric(name, typ, help_, samples):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        out.extend(samples)

    metric("kadmu_build_info", "gauge", "Build/version info.",
           [f'kadmu_build_info{{version="{_esc_label(APP_VERSION)}"}} 1'])
    metric("kadmu_uptime_seconds", "gauge", "Seconds since process start.",
           [f"kadmu_uptime_seconds {uptime():.0f}"])
    metric("kadmu_requests_total", "counter", "HTTP requests handled.",
           [f"kadmu_requests_total {reqs}"])
    metric("kadmu_responses_total", "counter", "HTTP responses by status class.",
           [f'kadmu_responses_total{{class="{c}"}} {n}' for c, n in classes.items()])
    metric("kadmu_bytes_sent_total", "counter", "Response body bytes served.",
           [f"kadmu_bytes_sent_total {sent}"])
    metric("kadmu_errors_total", "counter", "Unhandled route errors (5xx).",
           [f"kadmu_errors_total {errs}"])
    metric("kadmu_rate_limited_total", "counter", "Requests rejected by the rate limiter.",
           [f"kadmu_rate_limited_total {rl}"])
    metric("kadmu_stream_rejected_total", "counter",
           "Live streams rejected by the per-user concurrency cap.",
           [f"kadmu_stream_rejected_total {sr}"])
    metric("kadmu_active_streams", "gauge", "Live transcode/remux streams in flight.",
           [f"kadmu_active_streams {active_streams()}"])
    if per_user:
        metric("kadmu_user_bytes_sent_total", "counter",
               "Response body bytes served per identity (accounts mode).",
               [f'kadmu_user_bytes_sent_total{{id="{_esc_label(k)}"}} {v}'
                for k, v in per_user.items()])
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Per-IP request rate limiting (token bucket)
# --------------------------------------------------------------------------- #
_rl_lock = threading.Lock()
_rl: dict[str, tuple] = {}      # ip -> (tokens, last_refill_ts)


def rate_ok(ip: str):
    """Token-bucket gate for one request. Returns (allowed, retry_after_seconds).
    A no-op (always allowed) when rt.RATE_LIMIT is off. Callers exempt loopback
    before calling, so this only ever sees LAN/public peers."""
    if not rt.RATE_LIMIT:
        return True, 0
    now = time.time()
    with _rl_lock:
        if len(_rl) > RATE_LIMIT_MAX_IPS:
            _rl.clear()                      # crude bound; refills within a second
        tokens, last = _rl.get(ip, (float(RATE_BURST), now))
        tokens = min(float(RATE_BURST), tokens + (now - last) * RATE_RPS)
        if tokens < 1.0:
            _rl[ip] = (tokens, now)
            retry = int((1.0 - tokens) / RATE_RPS) + 1
            return False, retry
        _rl[ip] = (tokens - 1.0, now)
        return True, 0


# --------------------------------------------------------------------------- #
# Per-identity concurrent-stream accounting (quotas)
# --------------------------------------------------------------------------- #
_stream_lock = threading.Lock()
_stream_counts: dict[str, int] = {}


def stream_acquire(identity: str) -> bool:
    """Reserve a live-stream slot for this identity. False if they're already at
    USER_MAX_STREAMS. Always succeeds when the cap is 0 (disabled)."""
    if USER_MAX_STREAMS <= 0:
        return True
    with _stream_lock:
        n = _stream_counts.get(identity, 0)
        if n >= USER_MAX_STREAMS:
            return False
        _stream_counts[identity] = n + 1
        return True


def stream_release(identity: str) -> None:
    if USER_MAX_STREAMS <= 0:
        return
    with _stream_lock:
        n = _stream_counts.get(identity, 0)
        if n <= 1:
            _stream_counts.pop(identity, None)
        else:
            _stream_counts[identity] = n - 1


def active_streams() -> int:
    with _stream_lock:
        return sum(_stream_counts.values())


# --------------------------------------------------------------------------- #
# Structured logging (access + error)
# --------------------------------------------------------------------------- #
_log_lock = threading.Lock()


def _emit(line: str) -> None:
    with _log_lock:
        path = rt.ACCESS_LOG_PATH
        if path:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return
            except OSError:
                pass                         # fall back to stdout on a bad path
        print(line, file=sys.stdout, flush=True)


def access_log(method, path, status, n_bytes, dur_ms, ip, user=None) -> None:
    """One structured JSON line per request — only when rt.LOG_REQUESTS is on."""
    if not rt.LOG_REQUESTS:
        return
    rec = {"t": round(time.time(), 3), "ip": ip, "m": method, "path": path,
           "status": status, "bytes": n_bytes, "ms": dur_ms}
    if user:
        rec["user"] = user
    _emit(json.dumps(rec, separators=(",", ":")))


def error_log(method, path, exc) -> None:
    """Record an unhandled route error. Emits structured JSON when request logging
    is on, otherwise a single concise stderr line so crashes are never silent."""
    msg = f"{type(exc).__name__}: {exc}"
    if rt.LOG_REQUESTS:
        _emit(json.dumps({"t": round(time.time(), 3), "level": "error",
                          "m": method, "path": path, "error": msg},
                         separators=(",", ":")))
    else:
        print(f"  (route error {method} {path}: {msg})", file=sys.stderr, flush=True)
