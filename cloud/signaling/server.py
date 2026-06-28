"""Kadmu Phase 4b — the signaling broker (the *only* thing the cloud runs in the hot path).

Per the roadmap's cost model (docs/ROADMAP.md §5), the cloud must **never touch the video
bytes** — it brokers only the WebRTC handshake. This is that broker: a dumb, stateless-ish
relay that passes opaque SDP offers/answers and ICE candidates between a browser **guest**
and a home **host** (the connector) so they can open a peer-to-peer connection and stream
directly. Once the data channel is up, this server sees nothing more from that session.

It is **standard-library only** (`http.server`, `hmac`, `queue`) so it deploys with zero
install and is testable here, the same no-pip ethos as the core node — even though, living
under `cloud/`, it *could* take dependencies. Transport is HTTP long-poll (one mailbox per
peer), which sails through every proxy and needs no WebSocket layer.

Routes (all JSON):
    POST /signal/register  {role, node, token}      → {peer, host?}   open a mailbox
    POST /signal/send      {peer, to, type, data}   → {ok}            relay a blob to a peer
    GET  /signal/poll?peer=…                          → {messages:[…]}  long-poll (≤25s)
    GET  /healthz                                     → {ok:true}

**Entitlement gate (the Phase 4a seam).** Every `register` carries a `token`. In production
that token is minted by the Cloud control-plane after Stripe confirms an active subscription
(`verify_entitlement`); here it's an HMAC blob signed with `KADMU_SIGNAL_SECRET` (mint one with
`python3 server.py --mint <node>`). With no secret set the server runs in **dev mode** and
accepts any token — convenient locally, never do that in prod (it would let anyone broker).
"""
from __future__ import annotations
import base64
import hmac
import json
import os
import queue
import sys
import threading
import time
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

SECRET = os.environ.get("KADMU_SIGNAL_SECRET", "").encode("utf-8")
DEV_MODE = not SECRET                    # no secret ⇒ accept any token (local dev only)
POLL_TIMEOUT = 25                        # seconds a long-poll blocks before returning empty
PEER_TTL = 60                            # drop a peer not seen (polled/sent) for this long
TOKEN_TTL = 24 * 3600                    # minted tokens are valid this long
RELAY_TYPES = {"offer", "answer", "candidate", "bye"}   # the only blobs we'll forward


# ─────────────────────────── entitlement tokens ───────────────────────────

def mint_token(node, ttl=TOKEN_TTL):
    """Issue an HMAC token binding a `node` + expiry. Stand-in for the 4a Stripe→entitlement
    mint; the real control-plane would also encode the user/plan and check it against billing."""
    if DEV_MODE:
        return "dev"
    payload = base64.urlsafe_b64encode(
        json.dumps({"node": node, "exp": int(time.time()) + ttl}).encode()).decode()
    sig = base64.urlsafe_b64encode(hmac.new(SECRET, payload.encode(), sha256).digest()).decode()
    return f"{payload}.{sig}"


def verify_entitlement(token, node):
    """True iff `token` entitles access to `node`. Pluggable Phase 4a integration point."""
    if DEV_MODE:
        return bool(token)               # any non-empty token in dev
    try:
        payload, sig = token.split(".", 1)
        expect = base64.urlsafe_b64encode(
            hmac.new(SECRET, payload.encode(), sha256).digest()).decode()
        if not hmac.compare_digest(sig, expect):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("node") == node and data.get("exp", 0) > time.time()
    except Exception:                    # any malformed/forged token ⇒ not entitled
        return False


# ─────────────────────────── the relay hub ───────────────────────────

class Hub:
    """Thread-safe registry of peers and per-node host election. Pure in-memory; a peer is
    a mailbox (Queue) plus bookkeeping. Multiple guests can share a node — each does its own
    1:1 handshake with the single host, addressed by peer id."""

    def __init__(self):
        self._lock = threading.Lock()
        self._peers = {}                 # peer_id -> {node, role, box: Queue, seen}
        self._hosts = {}                 # node -> host peer_id
        self._seq = 0

    def _new_id(self, role):
        self._seq += 1
        return f"{role[0]}{self._seq:x}{int(time.time() * 1000) & 0xffff:04x}"

    def register(self, role, node):
        with self._lock:
            self._reap_locked()
            pid = self._new_id(role)
            self._peers[pid] = {"node": node, "role": role,
                                "box": queue.Queue(maxsize=256), "seen": time.time()}
            host = None
            if role == "host":
                self._hosts[node] = pid
            else:
                host = self._hosts.get(node)
            return pid, host

    def send(self, frm, to, msg):
        """Relay `msg` from peer `frm` to peer `to`. Returns False if `to` is gone."""
        with self._lock:
            src = self._peers.get(frm)
            dst = self._peers.get(to)
            if src:
                src["seen"] = time.time()
            if not dst:
                return False
            envelope = {"from": frm, "role": src["role"] if src else "?", **msg}
            try:
                dst["box"].put_nowait(envelope)
            except queue.Full:
                return False
            return True

    def box_for(self, peer):
        with self._lock:
            p = self._peers.get(peer)
            if p:
                p["seen"] = time.time()
                return p["box"]
            return None

    def drop(self, peer):
        with self._lock:
            p = self._peers.pop(peer, None)
            if p and p["role"] == "host" and self._hosts.get(p["node"]) == peer:
                self._hosts.pop(p["node"], None)

    def _reap_locked(self):
        now = time.time()
        for pid in [p for p, v in self._peers.items() if now - v["seen"] > PEER_TTL]:
            v = self._peers.pop(pid, None)
            if v and v["role"] == "host" and self._hosts.get(v["node"]) == pid:
                self._hosts.pop(v["node"], None)


HUB = Hub()


# ─────────────────────────── HTTP surface ───────────────────────────

class SignalHandler(BaseHTTPRequestHandler):
    server_version = "KadmuSignal/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):           # quiet by default; wire to real logging in prod
        pass

    def _cors(self):
        # The hosted app shell lives on a different origin than this broker. Only opaque,
        # entitlement-gated SDP blobs cross here — never video or library data — so a
        # permissive CORS policy on the signaling API alone is acceptable. Lock to the
        # app-shell origin in production via KADMU_SIGNAL_ORIGIN.
        self.send_header("Access-Control-Allow-Origin", os.environ.get("KADMU_SIGNAL_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/healthz":
            return self._json(200, {"ok": True, "dev": DEV_MODE})
        if url.path == "/signal/poll":
            peer = (parse_qs(url.query).get("peer") or [""])[0]
            box = HUB.box_for(peer)
            if box is None:
                return self._json(404, {"error": "unknown peer"})
            msgs = []
            try:
                msgs.append(box.get(timeout=POLL_TIMEOUT))   # block until something or timeout
                while True:                                   # then drain whatever else queued
                    msgs.append(box.get_nowait())
            except queue.Empty:
                pass
            return self._json(200, {"messages": msgs})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        data = self._body()
        if url.path == "/signal/register":
            node = str(data.get("node", ""))[:128]
            role = "host" if data.get("role") == "host" else "guest"
            if not node:
                return self._json(400, {"error": "node required"})
            if not verify_entitlement(str(data.get("token", "")), node):
                return self._json(403, {"error": "not entitled"})
            pid, host = HUB.register(role, node)
            if role == "guest" and not host:
                HUB.drop(pid)
                return self._json(409, {"error": "host offline"})
            return self._json(200, {"peer": pid, "host": host})
        if url.path == "/signal/send":
            frm, to = str(data.get("peer", "")), str(data.get("to", ""))
            mtype = str(data.get("type", ""))
            if mtype not in RELAY_TYPES:
                return self._json(400, {"error": "bad message type"})
            ok = HUB.send(frm, to, {"type": mtype, "data": data.get("data")})
            return self._json(200 if ok else 404, {"ok": ok})
        return self._json(404, {"error": "not found"})


def main(argv):
    if len(argv) >= 2 and argv[1] == "--mint":
        node = argv[2] if len(argv) > 2 else "node"
        print(mint_token(node))
        return
    port = int(os.environ.get("KADMU_SIGNAL_PORT", "8443"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), SignalHandler)
    mode = "DEV (accepts any token)" if DEV_MODE else "secured (HMAC tokens)"
    print(f"Kadmu signaling broker on :{port} — {mode}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv)
