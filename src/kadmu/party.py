"""Watch party — LAN/self-host synced playback. A tiny in-memory room registry
that brokers play/pause/seek/load between everyone watching the same room over
Server-Sent Events. No database, no third-party deps: rooms live only in this
process and evaporate when empty. The handler owns the actual SSE socket loop;
this module owns the rooms, the subscriber queues, and the broadcast fan-out."""
from __future__ import annotations
import queue
import random
import threading
import time

# code -> room dict. A room:
#   {code, created, activity, state: {...}, subs: set[Queue], host}
_rooms: dict[str, dict] = {}
_lock = threading.Lock()

ROOM_TTL = 6 * 3600          # drop an empty room after this long idle
MAX_ROOMS = 200
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no easily-confused chars


def _new_code():
    return "".join(random.choice(_ALPHABET) for _ in range(4))


def _prune_locked():
    now = time.time()
    dead = [c for c, r in _rooms.items()
            if not r["subs"] and now - r["activity"] > ROOM_TTL]
    for c in dead:
        _rooms.pop(c, None)


def create_room(host_name="", path=None):
    """Make a fresh room and return its code (or None if we're at capacity)."""
    with _lock:
        _prune_locked()
        if len(_rooms) >= MAX_ROOMS:
            return None
        for _ in range(20):
            code = _new_code()
            if code not in _rooms:
                break
        else:
            return None
        _rooms[code] = {
            "code": code, "created": time.time(), "activity": time.time(),
            "host": (host_name or "Host")[:40],
            "state": {"path": path, "position": 0.0, "paused": True,
                      "rate": 1.0, "updated": time.time()},
            "subs": set(),
        }
        return code


def room_exists(code):
    with _lock:
        return (code or "").upper() in _rooms


def room_snapshot(code):
    """Current play state + member count for a room, or None."""
    with _lock:
        r = _rooms.get((code or "").upper())
        if not r:
            return None
        return {"state": dict(r["state"]), "members": len(r["subs"]),
                "host": r["host"], "code": r["code"]}


def subscribe(code):
    """Register an SSE listener. Returns (Queue, room) or (None, None)."""
    code = (code or "").upper()
    with _lock:
        r = _rooms.get(code)
        if not r:
            return None, None
        q: "queue.Queue" = queue.Queue(maxsize=64)
        r["subs"].add(q)
        r["activity"] = time.time()
        return q, r


def unsubscribe(code, q):
    code = (code or "").upper()
    with _lock:
        r = _rooms.get(code)
        if r:
            r["subs"].discard(q)
            r["activity"] = time.time()
            if not r["subs"] and time.time() - r["activity"] > ROOM_TTL:
                _rooms.pop(code, None)


def _broadcast_locked(r, event):
    for q in list(r["subs"]):
        try:
            q.put_nowait(event)
        except queue.Full:
            pass            # a wedged listener just misses an update; never block


def update_room(code, patch, kind="control"):
    """Merge a control update into the room state and fan it out to listeners.
    Returns the member count, or None if the room is gone."""
    code = (code or "").upper()
    with _lock:
        r = _rooms.get(code)
        if not r:
            return None
        st = r["state"]
        for k in ("path", "position", "paused", "rate"):
            if k in patch and patch[k] is not None:
                st[k] = patch[k]
        st["updated"] = time.time()
        r["activity"] = time.time()
        ev = {"type": kind, **st}
        if "by" in patch:
            ev["by"] = str(patch["by"])[:40]
        _broadcast_locked(r, ev)
        return len(r["subs"])


def member_count(code):
    with _lock:
        r = _rooms.get((code or "").upper())
        return len(r["subs"]) if r else 0
