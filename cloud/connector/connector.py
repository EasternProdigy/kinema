"""Kadmu Phase 4b — the home-node connector (the P2P endpoint that lives on the user's box).

This is the sidecar that makes remote-from-anywhere work without the cloud ever touching a
video byte. It runs *next to* the stdlib core node (it does not modify or import it) and:

  1. registers with the signaling broker as the **host** for a stable node id,
  2. long-polls for browser **guests** and answers each one's WebRTC offer (aiortc),
  3. on the resulting data channel, speaks the `cloud/wire.py` protocol: every framed HTTP
     request is replayed against the *local* core at `http://127.0.0.1:<port>` and the
     response — including 206 byte-range video — is streamed straight back over the channel.

Because the connector talks to the core as an ordinary localhost client (forwarding the
guest's `Range`, `Cookie`, and `X-Kadmu` headers verbatim), **the core needs zero changes**:
host allow-listing sees 127.0.0.1, CSRF sees `X-Kadmu`, auth sees the session cookie. All the
P2P/non-stdlib weight (aiortc: ICE/DTLS/SCTP) stays here in `cloud/`, off the core entirely.

Requires `aiortc` (see cloud/requirements.txt) — NOT importable by the stdlib core. Run:

    KADMU_NODE_ID=my-box KADMU_SIGNAL_URL=https://signal.example \
    KADMU_NODE_TOKEN=$(python3 ../signaling/server.py --mint my-box) \
    python3 connector.py

⚠ The aiortc transport below can only be exercised against a real browser peer over a real
network; it is structured and reviewed but not yet integration-tested (see cloud/README.md
"What's verified vs. stubbed"). The framing it depends on *is* unit-tested (cloud/wire.py).
"""
from __future__ import annotations
import asyncio
import http.client
import json
import os
import sys
import urllib.request

# wire.py lives one level up (cloud/wire.py); import it without packaging ceremony.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wire  # noqa: E402

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
except ImportError:                       # pragma: no cover - dependency lives in cloud/ only
    print("connector requires aiortc — `pip install -r cloud/requirements.txt`", file=sys.stderr)
    raise

SIGNAL_URL = os.environ.get("KADMU_SIGNAL_URL", "http://127.0.0.1:8443").rstrip("/")
NODE_ID = os.environ.get("KADMU_NODE_ID", "kadmu-node")
NODE_TOKEN = os.environ.get("KADMU_NODE_TOKEN", "dev")
LOCAL_HOST = os.environ.get("KADMU_LOCAL_HOST", "127.0.0.1")
LOCAL_PORT = int(os.environ.get("KADMU_LOCAL_PORT", "8000"))

# bufferedAmount ceiling: pause reading from disk when the channel's send buffer is this full,
# so a fast SSD + slow home uplink can't balloon memory. Resumed on 'bufferedamountlow'.
SEND_HIGH_WATER = 4 * 1024 * 1024


def _ice_servers():
    """STUN (public, free) gets ~80-90% of networks connected directly. A TURN relay is added
    only if explicitly configured — per ROADMAP §5 we never default to relaying all video, since
    relayed traffic is the one place cloud egress reappears. TURN here is the capped fallback."""
    servers = [RTCIceServer(urls=os.environ.get("KADMU_STUN", "stun:stun.l.google.com:19302"))]
    turn = os.environ.get("KADMU_TURN_URL")
    if turn:
        servers.append(RTCIceServer(urls=turn,
                                    username=os.environ.get("KADMU_TURN_USER"),
                                    credential=os.environ.get("KADMU_TURN_CRED")))
    return RTCConfiguration(iceServers=servers)


# ─────────────────────────── signaling (long-poll over stdlib http) ───────────────────────────

async def _post(path, payload):
    def _do():
        req = urllib.request.Request(SIGNAL_URL + path,
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}"), r.status
    return await asyncio.to_thread(_do)


async def _poll(peer):
    def _do():
        with urllib.request.urlopen(f"{SIGNAL_URL}/signal/poll?peer={peer}", timeout=40) as r:
            return json.loads(r.read() or b"{}").get("messages", [])
    return await asyncio.to_thread(_do)


# ─────────────────────────── the data-channel → local HTTP proxy ───────────────────────────

class Session:
    """One guest = one RTCPeerConnection + one data channel. Demuxes wire frames into local
    HTTP calls and streams responses back, honouring ABORT (the browser seeked) and channel
    backpressure."""

    def __init__(self, pc, channel):
        self.pc = pc
        self.ch = channel
        self.aborted = set()              # stream ids the guest cancelled
        self.ch.on("message", self._on_message)

    def _on_message(self, raw):
        try:
            frame = wire.decode(raw)
        except ValueError:
            return
        if frame.type == wire.REQ:
            asyncio.ensure_future(self._handle_request(frame.stream, frame.meta))
        elif frame.type == wire.ABORT:
            self.aborted.add(frame.stream)
        # request-body DATA/END frames would be demuxed here; the core's read APIs are all
        # bodyless GETs, and mutating POSTs carry their small body inline — left for later.

    async def _drain(self):
        """Wait until the channel send buffer drops below the high-water mark."""
        while getattr(self.ch, "bufferedAmount", 0) > SEND_HIGH_WATER:
            await asyncio.sleep(0.02)

    async def _handle_request(self, sid, meta):
        try:
            status, reason, headers, resp = await asyncio.to_thread(self._local_request, meta)
        except Exception as e:               # local node down / refused
            self.ch.send(wire.encode_response(sid, 502, "Bad Gateway", {}))
            self.ch.send(wire.encode_data(sid, str(e).encode()[:512]))
            self.ch.send(wire.encode_end(sid))
            return
        self.ch.send(wire.encode_response(sid, status, reason, headers))
        try:
            while sid not in self.aborted:
                chunk = await asyncio.to_thread(resp.read, wire.MAX_CHUNK)
                if not chunk:
                    break
                await self._drain()
                self.ch.send(wire.encode_data(sid, chunk))
        finally:
            resp.close()
            self.aborted.discard(sid)
            self.ch.send(wire.encode_end(sid))

    def _local_request(self, meta):
        """Replay a framed request against the local core. Returns (status, reason, headers,
        open response) — the response is streamed by the caller, not buffered."""
        headers = dict(meta.get("headers") or {})
        headers["Host"] = f"{LOCAL_HOST}:{LOCAL_PORT}"       # satisfy host allow-listing
        conn = http.client.HTTPConnection(LOCAL_HOST, LOCAL_PORT, timeout=30)
        conn.request(meta.get("method", "GET"), meta.get("path", "/"), headers=headers)
        resp = conn.getresponse()
        # Forward only headers the browser side needs to reconstruct the response; hop-by-hop
        # and length headers are recomputed by the MSE/fetch layer from the framed body.
        fwd = {k: v for k, v in resp.getheaders()
               if k.lower() in ("content-type", "content-range", "content-length",
                                "accept-ranges", "cache-control", "set-cookie", "x-kadmu-error")}
        return resp.status, resp.reason, fwd, resp


# ─────────────────────────── per-guest peer connection ───────────────────────────

async def _serve_guest(host_peer, offer_msg):
    guest = offer_msg["from"]
    pc = RTCPeerConnection(_ice_servers())

    @pc.on("datachannel")
    def _on_dc(channel):
        Session(pc, channel)

    @pc.on("iceconnectionstatechange")
    async def _on_state():
        if pc.iceConnectionState in ("failed", "closed", "disconnected"):
            await pc.close()

    await pc.setRemoteDescription(RTCSessionDescription(offer_msg["data"]["sdp"], "offer"))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    # aiortc gathers ICE before localDescription resolves, so the answer is already complete —
    # we can ship it in one shot rather than trickling (simplest interop with browser peers).
    await _post("/signal/send", {"peer": host_peer, "to": guest, "type": "answer",
                                 "data": {"sdp": pc.localDescription.sdp}})
    return pc


async def run():
    reg, status = await _post("/signal/register",
                              {"role": "host", "node": NODE_ID, "token": NODE_TOKEN})
    if status != 200:
        print(f"register failed ({status}): {reg.get('error')}", file=sys.stderr)
        return
    host_peer = reg["peer"]
    print(f"connector up — node={NODE_ID!r} peer={host_peer} → local {LOCAL_HOST}:{LOCAL_PORT}")
    live = []
    while True:
        try:
            for msg in await _poll(host_peer):
                if msg.get("type") == "offer":
                    live.append(await _serve_guest(host_peer, msg))
            live = [pc for pc in live if pc.connectionState not in ("closed", "failed")]
        except Exception as e:               # signaling blip — back off and re-register if needed
            print(f"poll error: {e}", file=sys.stderr)
            await asyncio.sleep(2)
            reg, status = await _post("/signal/register",
                                      {"role": "host", "node": NODE_ID, "token": NODE_TOKEN})
            if status == 200:
                host_peer = reg["peer"]


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
