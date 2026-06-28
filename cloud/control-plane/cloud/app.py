"""Process entry point for the control-plane: the threaded HTTP server, a small
session janitor, and main(). Run via the cloud/control-plane/server.py shim."""
from __future__ import annotations
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer

from . import const
from .db import init_db, purge_sessions
from .handler import Handler


class CloudServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError, socket.timeout)):
            return
        try:
            who = client_address[0] if client_address else "?"
            print(f"  (handled request error from {who}: {type(exc).__name__})")
        except Exception:
            pass


def _janitor():
    while True:
        time.sleep(3600)
        try:
            purge_sessions()
        except Exception:
            pass


def main():
    init_db()
    threading.Thread(target=_janitor, name="cloud-janitor", daemon=True).start()

    print("=" * 64)
    print(f"  {const.APP_NAME} {const.APP_VERSION}  -  control-plane (Phase 4a)")
    print("  by Pentarosa Co.")
    print("=" * 64)
    print(f"  Listening: http://{const.HOST}:{const.PORT}")
    print(f"  Base URL:  {const.BASE_URL}")
    print(f"  Stripe:    {'MOCK (no real charges — set STRIPE_SECRET_KEY to go live)' if const.MOCK else 'LIVE'}")
    print(f"  Database:  {const.DB_PATH}")
    print("  Press Ctrl+C to stop.")
    print("=" * 64)

    try:
        httpd = CloudServer((const.HOST, const.PORT), Handler)
    except OSError as e:
        print(f"  Couldn't start on port {const.PORT}: {e}")
        sys.exit(1)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {const.APP_NAME} stopped. Bye!")
    finally:
        httpd.server_close()
