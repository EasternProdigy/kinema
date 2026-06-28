"""Kadmu Phase 4b — the HTTP-over-datachannel wire protocol.

A WebRTC data channel is a *message-oriented*, optionally-reliable pipe (SCTP under
the hood). Phase 4b tunnels the home node's ordinary HTTP — crucially the byte-range
video streaming (`/api/stream`, status 206, `Content-Range`) — over that pipe so
seeking and the existing playback pipeline survive end-to-end. This module is the
framing codec both peers speak: the Python **connector** imports it directly, and
the browser **remote.js** reimplements the exact same byte layout in JS.

It is deliberately **standard-library only** (`json` + `struct`) and has no idea what
a data channel, aiortc, or a browser is — it just turns frames into `bytes` and back.
That keeps the correctness-critical part of Phase 4b unit-testable with zero install
(see `cloud/tests/test_wire.py`), while the transport shells around it stay thin.

Wire format — every frame is one data-channel message:

    byte 0        frame type tag (see below)
    bytes 1..4    stream id, uint32 big-endian (one HTTP exchange = one stream id)
    bytes 5..     payload:
                    · control frames (REQ/RES/ABORT) → a UTF-8 JSON header blob
                    · DATA frames                    → raw body bytes (no JSON tax)
                    · END frames                     → empty

A request is: REQ [DATA…] END. A response is: RES [DATA…] END. Either side may send
ABORT to tear a stream down early (the browser sends it when the user seeks and the
in-flight range is now stale). Bodies are split into DATA frames no larger than
`MAX_CHUNK` so a single 4 GiB movie range never becomes one giant message.
"""
from __future__ import annotations
import json
import struct

# Frame type tags (byte 0).
REQ = 0x01      # request head:  {method, path, headers}
DATA = 0x02     # a body chunk (request or response), raw bytes
END = 0x03      # end of this stream's body
RES = 0x04      # response head: {status, reason, headers}
ABORT = 0x05    # tear this stream down early: {reason}

_HEAD = struct.Struct(">BI")        # type tag + stream id
HEADER_LEN = _HEAD.size             # 5 bytes

# Keep individual DATA frames comfortably under typical SCTP message limits. 64 KiB
# is the safe interop ceiling across browsers/aiortc for a single reliable message;
# the node's own file streaming already works in 256 KiB reads, so we re-chunk here.
MAX_CHUNK = 64 * 1024


class Frame:
    """A decoded frame. `meta` is set for REQ/RES/ABORT, `payload` for DATA."""
    __slots__ = ("type", "stream", "meta", "payload")

    def __init__(self, ftype, stream, meta=None, payload=b""):
        self.type = ftype
        self.stream = stream
        self.meta = meta
        self.payload = payload

    def __repr__(self):
        if self.type == DATA:
            return f"<Frame DATA s={self.stream} {len(self.payload)}B>"
        names = {REQ: "REQ", END: "END", RES: "RES", ABORT: "ABORT"}
        return f"<Frame {names.get(self.type, self.type)} s={self.stream} {self.meta}>"


def _encode(ftype, stream, payload=b""):
    return _HEAD.pack(ftype, stream) + payload


def _encode_json(ftype, stream, meta):
    return _encode(ftype, stream, json.dumps(meta, separators=(",", ":")).encode("utf-8"))


def encode_request(stream, method, path, headers):
    """Frame the head of a request. Body (if any) follows as DATA frames then END."""
    return _encode_json(REQ, stream, {"method": method, "path": path, "headers": dict(headers)})


def encode_response(stream, status, reason, headers):
    """Frame the head of a response. Body follows as DATA frames then END."""
    return _encode_json(RES, stream, {"status": int(status), "reason": reason,
                                      "headers": dict(headers)})


def encode_data(stream, payload):
    """Frame one body chunk. Caller must keep `payload` ≤ MAX_CHUNK (see split_body)."""
    return _encode(DATA, stream, payload)


def encode_end(stream):
    """Frame end-of-body for `stream`."""
    return _encode(END, stream)


def encode_abort(stream, reason=""):
    """Frame an early teardown of `stream` (e.g. the user seeked; range is stale)."""
    return _encode_json(ABORT, stream, {"reason": reason})


def split_body(stream, body, max_chunk=MAX_CHUNK):
    """Yield DATA frames covering `body`, each ≤ max_chunk. Does NOT emit END."""
    mv = memoryview(body)
    for off in range(0, len(mv), max_chunk):
        yield encode_data(stream, bytes(mv[off:off + max_chunk]))


def decode(frame):
    """Parse one data-channel message into a Frame. Raises ValueError on garbage."""
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise ValueError("frame must be bytes")
    frame = bytes(frame)
    if len(frame) < HEADER_LEN:
        raise ValueError("frame too short")
    ftype, stream = _HEAD.unpack(frame[:HEADER_LEN])
    rest = frame[HEADER_LEN:]
    if ftype == DATA:
        return Frame(DATA, stream, payload=rest)
    if ftype == END:
        return Frame(END, stream)
    if ftype in (REQ, RES, ABORT):
        try:
            meta = json.loads(rest.decode("utf-8")) if rest else {}
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"bad control payload: {e}") from e
        return Frame(ftype, stream, meta=meta)
    raise ValueError(f"unknown frame type {ftype:#x}")
