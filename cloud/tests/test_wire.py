"""Unit tests for cloud/wire.py — the Phase 4b HTTP-over-datachannel codec.

Standard-library `unittest` only, so this runs with zero install:

    python3 -m unittest discover -s cloud/tests

This is the one part of Phase 4b that's fully deterministic (no network, no browser,
no aiortc), so it's where we pin correctness. A round-trip property test plus the
chunking math catches the framing bugs that would otherwise only show up as a wedged
video stream over a real peer connection.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wire  # noqa: E402


class TestWire(unittest.TestCase):
    def test_request_roundtrip(self):
        f = wire.decode(wire.encode_request(
            7, "GET", "/api/stream?path=%2Fa.mkv", {"Range": "bytes=0-1023", "X-Kadmu": "1"}))
        self.assertEqual(f.type, wire.REQ)
        self.assertEqual(f.stream, 7)
        self.assertEqual(f.meta["method"], "GET")
        self.assertEqual(f.meta["path"], "/api/stream?path=%2Fa.mkv")
        self.assertEqual(f.meta["headers"]["Range"], "bytes=0-1023")

    def test_response_roundtrip(self):
        f = wire.decode(wire.encode_response(
            7, 206, "Partial Content",
            {"Content-Range": "bytes 0-1023/8192", "Content-Type": "video/mp4"}))
        self.assertEqual(f.type, wire.RES)
        self.assertEqual(f.stream, 7)
        self.assertEqual(f.meta["status"], 206)
        self.assertEqual(f.meta["reason"], "Partial Content")
        self.assertEqual(f.meta["headers"]["Content-Range"], "bytes 0-1023/8192")

    def test_data_is_binary_clean(self):
        # Body bytes must survive verbatim — including bytes that would break UTF-8.
        blob = bytes(range(256)) * 8
        f = wire.decode(wire.encode_data(3, blob))
        self.assertEqual(f.type, wire.DATA)
        self.assertEqual(f.stream, 3)
        self.assertEqual(f.payload, blob)

    def test_end_and_abort(self):
        end = wire.decode(wire.encode_end(9))
        self.assertEqual((end.type, end.stream), (wire.END, 9))
        ab = wire.decode(wire.encode_abort(9, "seek"))
        self.assertEqual((ab.type, ab.stream), (wire.ABORT, 9))
        self.assertEqual(ab.meta["reason"], "seek")

    def test_split_body_chunking(self):
        body = b"x" * (wire.MAX_CHUNK * 2 + 17)
        frames = list(wire.split_body(42, body))
        self.assertEqual(len(frames), 3)                      # two full + remainder
        reassembled = b""
        for raw in frames:
            f = wire.decode(raw)
            self.assertEqual(f.type, wire.DATA)
            self.assertEqual(f.stream, 42)
            self.assertLessEqual(len(f.payload), wire.MAX_CHUNK)
            reassembled += f.payload
        self.assertEqual(reassembled, body)

    def test_split_body_empty(self):
        self.assertEqual(list(wire.split_body(1, b"")), [])

    def test_large_stream_id(self):
        f = wire.decode(wire.encode_end(0xFFFFFFFF))
        self.assertEqual(f.stream, 0xFFFFFFFF)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            wire.decode(b"\x01\x00")                           # too short
        with self.assertRaises(ValueError):
            wire.decode(wire._encode(0x7F, 1))                # unknown type
        with self.assertRaises(ValueError):
            wire.decode(wire._encode(wire.REQ, 1, b"{not json"))


if __name__ == "__main__":
    unittest.main()
