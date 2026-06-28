"""Integration smoke test for cloud/signaling/server.py — the handshake broker.

Stdlib only: spins the real `SignalHandler` on an ephemeral port in a background thread and
drives it over HTTP with urllib. Covers the entitlement gate (HMAC) and the host↔guest mailbox
relay — i.e. the parts that *can* be exercised without a browser or aiortc.

    python3 -m unittest discover -s cloud/tests
"""
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signaling"))
import server as srv  # noqa: E402


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return _send(req)


def _get(base, path):
    return _send(urllib.request.Request(base + path))


def _send(req):
    try:
        with urllib.request.urlopen(req) as r:      # urllib raises on 4xx, so catch & unwrap
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        finally:
            e.close()


class TestSignaling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force secured mode so the entitlement gate is real (globals are read at call time).
        srv.SECRET = b"unit-test-secret"
        srv.DEV_MODE = False
        srv.HUB = srv.Hub()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.SignalHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_healthz(self):
        status, body = _get(self.base, "/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["dev"])              # we forced secured mode

    def test_entitlement_gate_rejects_bad_token(self):
        status, body = _post(self.base, "/signal/register",
                             {"role": "host", "node": "n1", "token": "forged"})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "not entitled")

    def test_guest_before_host_is_conflict(self):
        tok = srv.mint_token("lonely")
        status, body = _post(self.base, "/signal/register",
                             {"role": "guest", "node": "lonely", "token": tok})
        self.assertEqual(status, 409)              # no host online for this node

    def test_full_handshake_relay(self):
        node = "box-42"
        tok = srv.mint_token(node)
        # Host comes online.
        st, host = _post(self.base, "/signal/register", {"role": "host", "node": node, "token": tok})
        self.assertEqual(st, 200)
        # Guest joins and is handed the host's peer id.
        st, guest = _post(self.base, "/signal/register", {"role": "guest", "node": node, "token": tok})
        self.assertEqual(st, 200)
        self.assertEqual(guest["host"], host["peer"])
        # Guest sends an offer addressed to the host.
        st, res = _post(self.base, "/signal/send",
                        {"peer": guest["peer"], "to": host["peer"], "type": "offer",
                         "data": {"sdp": "v=0..."}})
        self.assertEqual((st, res["ok"]), (200, True))
        # Host polls and receives exactly that offer (mailbox already has it → no long block).
        st, poll = _get(self.base, "/signal/poll?peer=" + host["peer"])
        self.assertEqual(st, 200)
        self.assertEqual(len(poll["messages"]), 1)
        msg = poll["messages"][0]
        self.assertEqual(msg["type"], "offer")
        self.assertEqual(msg["from"], guest["peer"])
        self.assertEqual(msg["data"]["sdp"], "v=0...")

    def test_send_to_dead_peer_is_404(self):
        node = "box-7"
        tok = srv.mint_token(node)
        _post(self.base, "/signal/register", {"role": "host", "node": node, "token": tok})
        st, res = _post(self.base, "/signal/send",
                        {"peer": "ghost", "to": "alsoghost", "type": "answer", "data": {}})
        self.assertEqual((st, res["ok"]), (404, False))

    def test_bad_message_type_rejected(self):
        st, res = _post(self.base, "/signal/send",
                        {"peer": "x", "to": "y", "type": "evil", "data": {}})
        self.assertEqual(st, 400)


if __name__ == "__main__":
    unittest.main()
