"""The HTTP request handler — the one BaseHTTPRequestHandler subclass, its security
gate (_guard / _authed / _resolve_user / _require_admin), and the do_GET/do_POST
route chains. Pulls together every other module; nothing imports handler but app."""
from __future__ import annotations
import json
import queue
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import rt
from .const import (
    APP_NAME, APP_VERSION, FFMPEG, MIME, MP4_COPY_ACODECS, MP4_COPY_VCODECS,
    NATIVE_EXTS, PLAYLISTS_PATH, PUBLIC_ROUTES, SESSIONS, SESSIONS_LOCK,
    SUBTITLE_EXTS, TRANSCODE_LADDER, WEB_DIR, _REQ, _io_lock, _stream_sem,
    load_json, save_json,
)
from .accounts import (
    CLEAR_COOKIE, _current_uid, _db, _meta_set, _pw_check, _session_cookie,
    auth_user, create_user, db_logout, db_logout_user_sessions, db_new_session,
    db_playlists_get, db_playlists_set, db_prefs_get, db_prefs_set, db_session_user,
    delete_user, get_user, get_user_by_name, list_users, set_user_password,
    set_user_role, signup_open, user_count,
)
from .store import (
    _profile_slug, clear_progress, create_profile, get_config, list_profiles,
    load_progress, my_list_items, my_list_set, owning_root, resolve_within_roots,
    set_config, set_progress,
)
from .security import (
    host_allowed, login_check, login_fail, login_ok, new_session, parse_cookies,
    password_required, session_valid, set_lan_mode, set_password, verify_password,
)
from .media import (
    _h264_encoder, browser_playable, build_storyboard, embedded_subtitle_vtt,
    folder_cover, generate_thumb, probe_meta, read_subtitle_as_vtt,
    storyboard_image, subtitle_tracks,
)
from .library import (
    _picker_tool, _uri_to_path, browse_dir, continue_watching, home_feed,
    list_directory, list_roots, native_pick_folder, op_delete, op_mkdir, op_move,
    op_rename, purge_trash, request_reindex, search_library, trash_info,
)
from .party import (
    create_room, member_count, room_snapshot, subscribe, unsubscribe, update_room,
)

# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/qr.js": ("qr.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
}

CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{APP_VERSION}"
    # Reclaim idle keep-alive connections so sleeping tabs/phones can't slowly
    # accumulate handler threads across a multi-hour session. A live transfer
    # resets this on every chunk; only a truly stalled socket trips it.
    timeout = 120

    def log_message(self, fmt, *args):
        pass

    # -- inject security headers on every response -------------------------- #
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    # -- response helpers --------------------------------------------------- #
    def _send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_bytes(self, data, ctype, status=200, cache=True):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 2_000_000:   # JSON bodies are tiny; cap them
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    # -- security gate ------------------------------------------------------ #
    def _resolve_user(self):
        """Identify the signed-in user from the session cookie (accounts mode) and
        memoize it on the request thread. Returns the user dict, or None."""
        if getattr(_REQ, "_user_done", False):
            return getattr(_REQ, "user", None)
        _REQ._user_done = True
        _REQ.user = None
        if rt.ACCOUNTS_ENABLED:
            tok = parse_cookies(self.headers.get("Cookie", "")).get("kadmu_session")
            uid = db_session_user(tok) if tok else None
            if uid is not None:
                _REQ.user = get_user(uid)
        return _REQ.user

    def _authed(self):
        if rt.ACCOUNTS_ENABLED:
            return self._resolve_user() is not None
        if not password_required():
            return True
        tok = parse_cookies(self.headers.get("Cookie", "")).get("kadmu_session")
        return session_valid(tok)

    def _is_admin(self):
        u = self._resolve_user()
        return bool(u and u.get("role") == "admin")

    def _origin_ok(self):
        """For state-changing requests: require a positive same-site signal (CSRF)."""
        # The X-Kadmu header can only be set by our same-origin JS; a cross-site
        # page cannot add a custom header without a CORS preflight we never grant.
        if self.headers.get("X-Kadmu"):
            return True
        origin = self.headers.get("Origin")
        if origin is not None:
            return host_allowed(origin)
        ref = self.headers.get("Referer")
        if ref:
            return host_allowed(ref)
        # No same-site signal at all -> treat as cross-site and reject.
        return False

    def _guard(self, route, mutating):
        """Returns True if the request may proceed; else sends an error."""
        if not host_allowed(self.headers.get("Host", "")):
            self._send_json({"error": "Host not allowed"}, 403)
            return False
        if mutating and not self._origin_ok():
            self._send_json({"error": "Cross-site request blocked"}, 403)
            return False
        is_public = (route in PUBLIC_ROUTES or route.startswith("/fonts/")
                     or route.startswith("/js/"))
        if not is_public and not self._authed():
            self._send_json({"error": "Authentication required", "needAuth": True}, 401)
            return False
        return True

    def _require_writable(self):
        if rt.READONLY:
            self._send_json({"error": "This instance is read-only."}, 403)
            return False
        return True

    def _require_admin(self):
        """Library/instance management. In accounts mode it's admins only; in
        single-password mode any signed-in user already cleared _guard."""
        if rt.ACCOUNTS_ENABLED and not self._is_admin():
            self._send_json({"error": "Admins only."}, 403)
            return False
        return True

    # -- live, piped ffmpeg streaming --------------------------------------- #
    def _pipe_ffmpeg(self, cmd):
        """Run ffmpeg and pipe its stdout straight to the client as a fragmented
        MP4. There's no Content-Length (we read until ffmpeg exits) and no byte
        ranges (Accept-Ranges: none) — the player re-requests with a new `t` to
        seek. Playback starts in ~1-2s instead of waiting for a whole-file convert."""
        # Cap concurrent live encodes (see _stream_sem). A short wait smooths bursts,
        # but never hang a client forever — tell them we're busy so they can retry.
        if not _stream_sem.acquire(timeout=20):
            return self._send_json({"error": "Server busy — too many videos are being "
                                    "prepared right now. Try again in a moment."}, 503)
        try:
            self.close_connection = True       # no Content-Length -> read until close
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "none")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            except OSError:
                return
            try:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass                            # client switched quality / closed the tab
            finally:
                try: proc.stdout.close()
                except OSError: pass
                try: proc.kill()
                except OSError: pass
                try: proc.wait(timeout=5)
                except (subprocess.SubprocessError, OSError): pass
        finally:
            _stream_sem.release()

    def _stream_remux(self, path: Path, start: float, audio: int = 0):
        """Make a non-native file (an .mkv, or HEVC/x265 inside an .mp4, …) playable
        live, beginning at `start` seconds. Stream-copies the video and audio when
        they're already codecs MP4 can carry in the browser (fast, lossless) and
        transcodes to H.264/AAC only what isn't — at the source resolution, so this
        is 'Original' quality. `audio` selects which audio track to include (its
        ordinal among the file's audio streams). Seeking re-requests with a new `t`."""
        if not FFMPEG:
            return self._send_json({"error": "Can't prepare this video (ffmpeg unavailable)."}, 415)
        meta = probe_meta(path)
        vc = (meta.get("vcodec") or "").lower()
        # codec of the *selected* audio track (not just the first), so copy-vs-encode
        # is decided correctly when switching to, say, an AC3 commentary track.
        auds = meta.get("audios") or []
        if auds:
            sel = next((a for a in auds if a.get("ord") == audio), auds[0])
            ac = (sel.get("codec") or "").lower()
        else:
            ac = (meta.get("acodec") or "").lower()
        if vc and vc in MP4_COPY_VCODECS:
            v_args = ["-c:v", "copy"]            # already MP4-friendly: no re-encode
        else:
            enc = _h264_encoder()                # libx264, or libopenh264 where x264 is absent
            if not enc:
                return self._send_json({"error": "No H.264 encoder available to convert this video."}, 415)
            if enc == "libx264":
                v_args = ["-c:v", enc, "-preset", "veryfast", "-tune", "zerolatency",
                          "-crf", "23", "-pix_fmt", "yuv420p"]
            else:
                # libopenh264 wants an explicit bitrate; scale it to the source height
                h = meta.get("height") or 1080
                br = next((TRANSCODE_LADDER[k][0] for k in sorted(TRANSCODE_LADDER) if h <= k),
                          TRANSCODE_LADDER[max(TRANSCODE_LADDER)][0])
                v_args = ["-c:v", enc, "-b:v", br, "-maxrate", br, "-pix_fmt", "yuv420p"]
        a_args = (["-c:a", "copy"] if (ac and ac in MP4_COPY_ACODECS)
                  else ["-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        cmd = [FFMPEG, "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-i", str(path),
               "-map", "0:v:0", "-map", f"0:a:{max(0, audio)}?", "-sn", *v_args, *a_args,
               "-movflags", "frag_keyframe+empty_moov+default_base_moof",
               "-f", "mp4", "pipe:1"]
        self._pipe_ffmpeg(cmd)

    # -- on-the-fly quality downscale, streamed live ------------------------ #
    def _stream_transcode(self, path: Path, height: int, start: float, audio: int = 0):
        """Downscale `path` to `height` lines and pipe it to the client live,
        beginning at `start` seconds. Like _stream_remux but always re-encodes to a
        smaller, lower-bitrate rendition (the quality picker). `audio` selects which
        audio track to carry."""
        enc = _h264_encoder()
        if not FFMPEG or not enc or height not in TRANSCODE_LADDER:
            return self._send_json({"error": "unsupported quality"}, 400)
        bitrate, bufsize = TRANSCODE_LADDER[height]
        v_args = ["-c:v", enc, "-vf", f"scale=-2:{height}",
                  "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bufsize, "-pix_fmt", "yuv420p"]
        if enc == "libx264":
            v_args += ["-preset", "veryfast", "-tune", "zerolatency"]
        # -ss before -i = fast keyframe seek; fragmented mp4 = streamable without
        # rewriting the moov, so the first bytes flow almost immediately.
        cmd = [FFMPEG, "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-i", str(path),
               "-map", "0:v:0", "-map", f"0:a:{max(0, audio)}?", "-sn",
               *v_args, "-c:a", "aac", "-b:a", "160k", "-ac", "2",
               "-movflags", "frag_keyframe+empty_moov+default_base_moof",
               "-f", "mp4", "pipe:1"]
        self._pipe_ffmpeg(cmd)

    # -- range-aware file streaming ----------------------------------------- #
    def _serve_file_with_range(self, filepath: Path, ctype):
        try:
            file_size = filepath.stat().st_size
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        range_header = self.headers.get("Range")
        start, end, status = 0, file_size - 1, 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                if not m.group(1) and m.group(2):       # suffix: bytes=-N
                    start = max(0, file_size - int(m.group(2)))
                    end = file_size - 1
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        self._stream(filepath, start, length)

    def _stream(self, filepath: Path, start, length):
        chunk, remaining = 256 * 1024, length
        try:
            with open(filepath, "rb") as f:
                f.seek(start)
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_static(self, route):
        name, ctype = STATIC_FILES[route]
        fp = WEB_DIR / name
        if not fp.exists():
            self._send_json({"error": "missing asset"}, 404)
            return
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if route in ("/", "/index.html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _placeholder_thumb(self):
        gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!"
               b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
               b"\x00\x00\x02\x02D\x01\x00;")
        self._send_bytes(gif, "image/gif", cache=False)

    def _breadcrumb(self, path: Path):
        root = owning_root(path)
        if root is None:
            return []
        crumbs = [{"name": root.name or str(root), "path": str(root)}]
        cur = root
        for part in path.relative_to(root).parts:
            cur = cur / part
            crumbs.append({"name": part, "path": str(cur)})
        return crumbs

    def _session_state(self):
        authed = self._authed()
        # who may manage the library / instance: everyone signed in (single-password
        # mode) or only admins (accounts mode).
        admin = self._is_admin() if rt.ACCOUNTS_ENABLED else authed
        manage = (not rt.READONLY) and authed and admin
        st = {
            "app": APP_NAME, "version": APP_VERSION,
            "authRequired": rt.ACCOUNTS_ENABLED or password_required(),
            "authed": authed,
            "readonly": rt.READONLY,
            "canManage": manage,
            "canBrowse": rt.ALLOW_BROWSE and manage,
            "nativePicker": bool(_picker_tool()) and manage,
            "ffmpeg": bool(FFMPEG),
            "urls": rt.SERVER_URLS,
            "lan": rt.LAN_MODE,
            "canToggleLan": rt.LAN_TOGGLEABLE and manage,
            "canSetPassword": (not rt.ACCOUNTS_ENABLED) and (not rt.READONLY) and authed,
            "profiles": rt.PROFILES_ENABLED and not rt.ACCOUNTS_ENABLED,
            "accounts": rt.ACCOUNTS_ENABLED,
            "user": None, "role": None,
        }
        if rt.ACCOUNTS_ENABLED:
            u = self._resolve_user()
            st["user"] = u
            st["role"] = (u or {}).get("role")
            st["signupOpen"] = signup_open()
            st["needsSetup"] = user_count() == 0
        return st

    # -- per-request viewer profile (opt-in) -------------------------------- #
    def _set_profile(self):
        """Stash the active viewer profile (from X-Kadmu-Profile) on the request
        thread so progress/My-List helpers can scope to it. A no-op when profiles
        are off — everything stays on the single shared store."""
        _REQ.profile = (_profile_slug(self.headers.get("X-Kadmu-Profile", ""))
                        if rt.PROFILES_ENABLED else "default")

    # -- watch party (Server-Sent Events) ----------------------------------- #
    def _sse(self, obj):
        return ("data: " + json.dumps(obj) + "\n\n").encode("utf-8")

    def _serve_party_events(self, code):
        """Hold an SSE connection open and stream a watch-party room's play state.
        Blocks this handler thread for the life of the connection (fine on the
        threaded server); a heartbeat every 15s also detects a dropped client."""
        q, _room = subscribe(code)
        if q is None:
            return self._send_json({"error": "No such room."}, 404)
        self.close_connection = True              # open-ended stream: read until close
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            snap = room_snapshot(code)
            if snap:
                self.wfile.write(self._sse({"type": "load", **snap["state"],
                                            "members": snap["members"]}))
                self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    ev = {"type": "ping", "members": member_count(code)}
                self.wfile.write(self._sse(ev))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                  # client closed the tab / left the party
        finally:
            unsubscribe(code, q)

    # -- verbs -------------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        route, qs = parsed.path, parse_qs(parsed.query)

        _REQ.user = None            # reset per-request identity (threads are reused)
        _REQ._user_done = False
        if not self._guard(route, mutating=False):
            return
        self._set_profile()

        if route in STATIC_FILES:
            return self._serve_static(route)

        if route.startswith("/fonts/") and route.endswith(".woff2"):
            name = route[len("/fonts/"):]
            if "/" in name or ".." in name:
                return self._send_json({"error": "not found"}, 404)
            fp = WEB_DIR / "fonts" / name
            if fp.is_file():
                return self._send_bytes(fp.read_bytes(), "font/woff2")
            return self._send_json({"error": "not found"}, 404)

        # The frontend is a set of ordered classic scripts under web/js/.
        if route.startswith("/js/") and route.endswith(".js"):
            name = route[len("/js/"):]
            if "/" in name or ".." in name:
                return self._send_json({"error": "not found"}, 404)
            fp = WEB_DIR / "js" / name
            if fp.is_file():
                return self._send_bytes(fp.read_bytes(),
                                        "application/javascript; charset=utf-8", cache=False)
            return self._send_json({"error": "not found"}, 404)

        if route == "/api/session":
            return self._send_json(self._session_state())

        if route == "/api/config":
            cfg = get_config()
            cfg.pop("auth", None)        # never expose the password hash to the client
            return self._send_json(cfg)

        if route == "/api/library":
            raw = qs.get("path", [None])[0]
            if not raw:
                return self._send_json({"path": None, "isRoot": True,
                                        "folders": list_roots(), "videos": [],
                                        "breadcrumb": []})
            path = resolve_within_roots(unquote(raw))
            if not path or not path.is_dir():
                return self._send_json({"error": "Folder not found or outside library."}, 404)
            data = list_directory(path)
            data.update(path=str(path), isRoot=False, breadcrumb=self._breadcrumb(path))
            return self._send_json(data)

        if route == "/api/browse":
            if not (rt.ALLOW_BROWSE and not rt.READONLY):
                return self._send_json({"error": "Browsing disabled."}, 403)
            if rt.ACCOUNTS_ENABLED and not self._is_admin():
                return self._send_json({"error": "Admins only."}, 403)
            return self._send_json(browse_dir(unquote(qs.get("path", [""])[0])))

        if route == "/api/meta":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            return self._send_json(probe_meta(path))

        if route == "/api/thumb":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._placeholder_thumb()
            t = generate_thumb(path)
            if t and t.exists():
                return self._send_bytes(t.read_bytes(), "image/jpeg")
            return self._placeholder_thumb()

        if route == "/api/cover":
            folder = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not folder or not folder.is_dir():
                return self._send_json({"error": "not found"}, 404)
            cov, mime = folder_cover(folder)
            if cov and cov.exists():
                try:
                    return self._send_bytes(cov.read_bytes(), mime)
                except OSError:
                    pass
            return self._send_json({"error": "no cover"}, 404)

        if route == "/api/storyboard":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"ok": False})
            return self._send_json(build_storyboard(path))

        if route == "/api/storyboard.jpg":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if path and path.is_file():
                data = storyboard_image(path)
                if data:
                    return self._send_bytes(data, "image/jpeg")
            return self._placeholder_thumb()

        if route == "/api/stream":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            ext = path.suffix.lower()
            try:
                audio = max(0, int(qs.get("audio", ["0"])[0]))   # selected audio track ordinal
            except (TypeError, ValueError):
                audio = 0
            # A native, browser-decodable file is served straight off disk (fully
            # byte-seekable) — unless the viewer picked a non-default audio track,
            # which requires a remux to swap the active stream.
            if ext in NATIVE_EXTS and browser_playable(path) and audio == 0:
                return self._serve_file_with_range(path, MIME.get(ext, "application/octet-stream"))
            # non-native container (.mkv …) OR a native container whose codec the
            # browser can't decode (e.g. HEVC/x265 inside an .m4v) OR a swapped audio
            # track: pipe it live, remuxing/transcoding on the fly so playback starts
            # in ~1-2s. Not byte-seekable; the player re-requests with `t` to seek.
            try:
                start = float(qs.get("t", ["0"])[0])
            except (TypeError, ValueError):
                start = 0.0
            return self._stream_remux(path, max(0.0, start), audio)

        if route == "/api/transcode":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            try:
                height = int(qs.get("height", ["0"])[0])
            except (TypeError, ValueError):
                return self._send_json({"error": "bad height"}, 400)
            if height not in TRANSCODE_LADDER:
                return self._send_json({"error": "unsupported quality"}, 400)
            try:
                start = float(qs.get("t", ["0"])[0])
            except (TypeError, ValueError):
                start = 0.0
            try:
                audio = max(0, int(qs.get("audio", ["0"])[0]))
            except (TypeError, ValueError):
                audio = 0
            return self._stream_transcode(path, height, start, audio)

        if route == "/api/progress":
            return self._send_json(load_progress())

        if route == "/api/continue":
            return self._send_json(continue_watching())

        if route == "/api/home":
            return self._send_json(home_feed())

        if route == "/api/party/state":
            snap = room_snapshot(qs.get("code", [""])[0])
            if not snap:
                return self._send_json({"error": "no room"}, 404)
            return self._send_json(snap)

        if route == "/api/party/events":
            return self._serve_party_events(qs.get("code", [""])[0])

        if route == "/api/search":
            return self._send_json(search_library(unquote(qs.get("q", [""])[0])))

        if route == "/api/mylist":
            return self._send_json(my_list_items())

        if route == "/api/profiles":
            return self._send_json({"enabled": rt.PROFILES_ENABLED,
                                    "profiles": list_profiles() if rt.PROFILES_ENABLED else []})

        if route == "/api/users":
            if not rt.ACCOUNTS_ENABLED:
                return self._send_json({"users": []})
            if not self._is_admin():
                return self._send_json({"error": "Admins only."}, 403)
            return self._send_json({"users": list_users(), "signupOpen": signup_open()})

        if route == "/api/subs":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json([])
            return self._send_json(subtitle_tracks(path))

        if route == "/api/sub":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            track = qs.get("track", [None])[0]
            if track is not None:                # text track embedded in the video
                try:
                    ordn = int(track)
                except (TypeError, ValueError):
                    return self._send_json({"error": "bad track"}, 400)
                data = embedded_subtitle_vtt(path, ordn)
                if data is None:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_bytes(data, "text/vtt; charset=utf-8")
            if path.suffix.lower() not in SUBTITLE_EXTS:
                return self._send_json({"error": "not found"}, 404)
            try:
                return self._send_bytes(read_subtitle_as_vtt(path), "text/vtt; charset=utf-8")
            except OSError:
                return self._send_json({"error": "could not read subtitle"}, 500)

        if route == "/api/playlists":
            if rt.ACCOUNTS_ENABLED:
                uid = _current_uid()
                return self._send_json(db_playlists_get(uid) if uid else {})
            return self._send_json(load_json(PLAYLISTS_PATH, {}))

        if route == "/api/prefs":
            # per-user preferences (accounts mode); empty otherwise (the client keeps
            # its own prefs in localStorage when there are no accounts).
            if rt.ACCOUNTS_ENABLED:
                uid = _current_uid()
                return self._send_json(db_prefs_get(uid) if uid else {})
            return self._send_json({})

        if route == "/api/trash":
            return self._send_json(trash_info())

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path

        _REQ.user = None            # reset per-request identity (threads are reused)
        _REQ._user_done = False
        if not self._guard(route, mutating=True):
            return
        self._set_profile()
        body = self._read_body()

        if route == "/api/profiles":
            # create (or look up) a viewer profile; selection itself is client-side
            if not rt.PROFILES_ENABLED:
                return self._send_json({"ok": False, "error": "Profiles are disabled."}, 400)
            prof = create_profile(str(body.get("name", "")))
            return self._send_json({"ok": True, "profile": prof, "profiles": list_profiles()})

        if route == "/api/login":
            ip = self.client_address[0] if self.client_address else "?"
            if rt.ACCOUNTS_ENABLED:
                allowed, retry = login_check(ip)
                if not allowed:
                    return self._send_json(
                        {"ok": False, "error": f"Too many attempts. Try again in {retry}s."},
                        429, extra_headers={"Retry-After": str(retry)})
                user = auth_user(str(body.get("username", "")), str(body.get("password", "")))
                if user:
                    login_ok(ip)
                    tok = db_new_session(user["id"])
                    return self._send_json({"ok": True, "authed": True, "user": user},
                                           extra_headers={"Set-Cookie": _session_cookie(tok)})
                login_fail(ip)
                return self._send_json({"ok": False, "error": "Wrong username or password."}, 401)
            if not password_required():
                return self._send_json({"ok": True, "authed": True})
            allowed, retry = login_check(ip)
            if not allowed:
                return self._send_json(
                    {"ok": False, "error": f"Too many attempts. Try again in {retry}s."},
                    429, extra_headers={"Retry-After": str(retry)})
            supplied = str(body.get("password", ""))
            if verify_password(supplied):
                login_ok(ip)
                tok = new_session()
                return self._send_json({"ok": True, "authed": True},
                                       extra_headers={"Set-Cookie": _session_cookie(tok)})
            login_fail(ip)
            return self._send_json({"ok": False, "error": "Wrong password."}, 401)

        if route == "/api/register":
            # Accounts mode only. The first account becomes the owner (admin) and is
            # always allowed; after that, self-registration depends on the signup flag.
            if not rt.ACCOUNTS_ENABLED:
                return self._send_json({"ok": False, "error": "Accounts are disabled."}, 400)
            ip = self.client_address[0] if self.client_address else "?"
            allowed, retry = login_check(ip)
            if not allowed:
                return self._send_json(
                    {"ok": False, "error": f"Too many attempts. Try again in {retry}s."},
                    429, extra_headers={"Retry-After": str(retry)})
            first = user_count() == 0
            if not first and not signup_open():
                return self._send_json(
                    {"ok": False, "error": "Sign-ups are closed. Ask an admin for an account."}, 403)
            user, err = create_user(str(body.get("username", "")),
                                    str(body.get("password", "")),
                                    role="viewer", name=str(body.get("name", "")))
            if err:
                login_fail(ip)
                return self._send_json({"ok": False, "error": err}, 400)
            login_ok(ip)
            tok = db_new_session(user["id"])
            return self._send_json({"ok": True, "authed": True, "user": user},
                                   extra_headers={"Set-Cookie": _session_cookie(tok)})

        if route == "/api/logout":
            tok = parse_cookies(self.headers.get("Cookie", "")).get("kadmu_session")
            if tok:
                if rt.ACCOUNTS_ENABLED:
                    db_logout(tok)
                with SESSIONS_LOCK:
                    SESSIONS.pop(tok, None)
            return self._send_json({"ok": True}, extra_headers={"Set-Cookie": CLEAR_COOKIE})

        if route == "/api/account":
            # Change your own display name and/or password (accounts mode).
            if not rt.ACCOUNTS_ENABLED:
                return self._send_json({"ok": False, "error": "Accounts are disabled."}, 400)
            u = self._resolve_user()
            if not u:
                return self._send_json({"error": "Authentication required", "needAuth": True}, 401)
            new_pw = body.get("newPassword")
            if new_pw:
                row = get_user_by_name(u["username"])
                if not row or not _pw_check(str(body.get("currentPassword", "")),
                                            row["pw_salt"], row["pw_hash"], row["iters"]):
                    return self._send_json({"ok": False, "error": "Current password is wrong."}, 403)
                ok, err = set_user_password(u["id"], str(new_pw))
                if not ok:
                    return self._send_json({"ok": False, "error": err}, 400)
            name = body.get("name")
            if isinstance(name, str) and name.strip():
                _db().execute("UPDATE users SET name=? WHERE id=?",
                              (name.strip()[:64], u["id"]))
                _db().commit()
            return self._send_json({"ok": True, "user": get_user(u["id"])})

        if route == "/api/users":
            # Admin-only user management (accounts mode).
            if not rt.ACCOUNTS_ENABLED:
                return self._send_json({"ok": False, "error": "Accounts are disabled."}, 400)
            if not self._require_admin():
                return
            me = self._resolve_user()
            action = body.get("action")
            if action == "create":
                user, err = create_user(str(body.get("username", "")),
                                        str(body.get("password", "")),
                                        role=str(body.get("role", "viewer")),
                                        name=str(body.get("name", "")))
                if err:
                    return self._send_json({"ok": False, "error": err}, 400)
                return self._send_json({"ok": True, "user": user, "users": list_users()})
            try:
                uid = int(body.get("id"))
            except (TypeError, ValueError):
                if action == "signup":
                    _meta_set("signup_open", "1" if body.get("open") else "0")
                    return self._send_json({"ok": True, "signupOpen": signup_open()})
                return self._send_json({"ok": False, "error": "Which user?"}, 400)
            if action == "signup":
                _meta_set("signup_open", "1" if body.get("open") else "0")
                return self._send_json({"ok": True, "signupOpen": signup_open()})
            if action == "setRole":
                if uid == me["id"] and str(body.get("role")) == "viewer":
                    return self._send_json({"ok": False, "error": "You can't demote yourself."}, 400)
                ok, err = set_user_role(uid, str(body.get("role", "viewer")))
            elif action == "resetPassword":
                ok, err = set_user_password(uid, str(body.get("password", "")))
                if ok:
                    db_logout_user_sessions(uid)   # force re-login with the new password
            elif action == "delete":
                if uid == me["id"]:
                    return self._send_json({"ok": False, "error": "You can't delete yourself."}, 400)
                ok, err = delete_user(uid)
            else:
                ok, err = False, "Unknown action."
            if not ok:
                return self._send_json({"ok": False, "error": err}, 400)
            return self._send_json({"ok": True, "users": list_users()})

        if route == "/api/progress":
            p = resolve_within_roots(body.get("path"), must_exist=False)
            if not p:
                return self._send_json({"error": "outside library"}, 400)
            try:
                pos = float(body.get("position", 0))
                dur = float(body.get("duration", 0) or 0)
            except (TypeError, ValueError):
                return self._send_json({"error": "bad payload"}, 400)
            set_progress(str(p), {"position": pos, "duration": dur, "updated": time.time()})
            return self._send_json({"ok": True})

        if route == "/api/progress/clear":
            path = body.get("path")
            if path:
                p = resolve_within_roots(path, must_exist=False)
                clear_progress(str(p) if p else path)
            else:
                clear_progress(None)
            return self._send_json({"ok": True})

        if route == "/api/mylist":
            # personal watchlist state — like progress, allowed even in read-only
            keys = my_list_set(body.get("path"), bool(body.get("on", True)),
                               str(body.get("name", "")))
            if keys is None:
                return self._send_json({"error": "outside library"}, 400)
            return self._send_json({"ok": True, "paths": keys})

        # ---- watch party: synced playback state (not a library write) ---- #
        if route == "/api/party/create":
            code = create_room(path=body.get("path"))
            if not code:
                return self._send_json({"ok": False, "error": "Too many active parties right now."}, 503)
            return self._send_json({"ok": True, "code": code})

        if route == "/api/party/join":
            snap = room_snapshot(str(body.get("code", "")))
            if not snap:
                return self._send_json({"ok": False, "error": "No watch party with that code."}, 404)
            return self._send_json({"ok": True, "snapshot": snap})

        if route == "/api/party/update":
            patch = {k: body.get(k) for k in ("path", "position", "paused", "rate") if k in body}
            kind = "load" if body.get("kind") == "load" else "control"
            n = update_room(str(body.get("code", "")), patch, kind=kind)
            if n is None:
                return self._send_json({"ok": False, "error": "No such room."}, 404)
            return self._send_json({"ok": True, "members": n})

        if route == "/api/lan":
            # network-sharing toggle: a server setting, not a library write, but we
            # still gate it behind management rights so a read-only/demo instance
            # can never be flipped open by a visitor.
            if not self._require_writable() or not self._require_admin():
                return
            if not rt.LAN_TOGGLEABLE:
                return self._send_json(
                    {"ok": False, "error": "Network sharing isn't available for this "
                     "bind address. Start Kadmu without an explicit --host (or with "
                     "--lan) to enable it."}, 400)
            set_lan_mode(bool(body.get("on")))
            return self._send_json({"ok": True, "lan": rt.LAN_MODE, "urls": rt.SERVER_URLS})

        if route == "/api/password":
            # Set / change / clear the shared access password at runtime (persisted,
            # hashed). Gated like the LAN toggle so a read-only/demo instance can't be
            # locked. Meaningless in accounts mode — each user has their own password.
            if rt.ACCOUNTS_ENABLED:
                return self._send_json(
                    {"ok": False, "error": "This instance uses accounts; manage them in "
                     "Settings instead of a shared password."}, 400)
            if not self._require_writable():
                return
            new_pw = str(body.get("password", ""))
            if len(new_pw) > 256:
                return self._send_json({"ok": False, "error": "That password is too long."}, 400)
            set_password(new_pw)
            extra = {}
            if password_required():
                tok = new_session()          # keep whoever just set it signed in on this device
                extra["Set-Cookie"] = _session_cookie(tok)
            else:
                extra["Set-Cookie"] = CLEAR_COOKIE
            return self._send_json({"ok": True, "authRequired": password_required()},
                                   extra_headers=extra)

        if route == "/api/prefs":
            # per-user preferences blob (accounts mode); a no-op otherwise.
            if rt.ACCOUNTS_ENABLED:
                uid = _current_uid()
                if uid:
                    prefs = body.get("prefs")
                    db_prefs_set(uid, prefs if isinstance(prefs, dict) else {})
            return self._send_json({"ok": True})

        # ---- everything below mutates the library: writable + (accounts) admin ---- #
        if route == "/api/config":
            if not self._require_writable() or not self._require_admin():
                return
            cfg = get_config()
            roots = body.get("roots")
            if isinstance(roots, list):
                clean = []
                for r in roots[:64]:
                    try:
                        p = Path(str(r)).expanduser().resolve()
                    except OSError:
                        continue
                    if p.is_dir() and str(p) not in clean:
                        clean.append(str(p))
                cfg["roots"] = clean
                set_config(cfg)
                request_reindex()       # roots changed -> rebuild the search catalog
            return self._send_json(get_config())

        if route == "/api/playlists":
            # personal playlists — per-user in accounts mode, shared otherwise.
            if not self._require_writable():
                return
            if rt.ACCOUNTS_ENABLED:
                uid = _current_uid()
                if uid:
                    pls = body.get("playlists")
                    db_playlists_set(uid, pls if isinstance(pls, dict) else {})
            else:
                with _io_lock:
                    save_json(PLAYLISTS_PATH, body.get("playlists", {}))
            return self._send_json({"ok": True})

        if route == "/api/pick-folder":
            if not self._require_writable() or not self._require_admin():
                return
            if not _picker_tool():
                return self._send_json({"ok": False, "error": "No native folder picker on this machine."})
            sel = native_pick_folder(body.get("start"))
            if sel is None:
                return self._send_json({"ok": False, "error": "The folder picker could not open."})
            if sel == "":
                return self._send_json({"ok": False, "cancelled": True})
            p = Path(sel).expanduser()
            if not p.is_dir():
                return self._send_json({"ok": False, "error": "That isn't a folder."})
            return self._send_json({"ok": True, "path": str(p.resolve())})

        if route == "/api/add-paths":
            if not self._require_writable() or not self._require_admin():
                return
            cfg = get_config()
            roots = list(cfg.get("roots", []))
            added = []
            for u in (body.get("paths") or [])[:64]:
                p = _uri_to_path(u)
                if not p:
                    continue
                if p.is_file():
                    p = p.parent
                if p.is_dir():
                    sp = str(p.resolve())
                    if sp not in roots:
                        roots.append(sp)
                        added.append(sp)
            cfg["roots"] = roots
            set_config(cfg)
            if added:
                request_reindex()       # new roots -> rebuild the search catalog
            return self._send_json({"ok": True, "added": added, "roots": roots})

        if route == "/api/op":
            if not self._require_writable() or not self._require_admin():
                return
            action = body.get("action")
            if action == "rename":
                ok, msg = op_rename(body.get("path"), body.get("name"))
            elif action == "move":
                ok, msg = op_move(body.get("path"), body.get("dest"))
            elif action == "mkdir":
                ok, msg = op_mkdir(body.get("path"), body.get("name"))
            elif action == "delete":
                ok, msg = op_delete(body.get("path"))
            elif action == "empty-trash":
                n, freed = purge_trash(None)     # permanently delete everything trashed
                ok, msg = True, f"Emptied trash ({n} item{'s' if n != 1 else ''} removed)."
            else:
                ok, msg = False, "Unknown action."
            if ok and action in ("rename", "move", "mkdir", "delete"):
                request_reindex()       # library layout changed -> refresh the catalog
            return self._send_json({"ok": ok, "message": msg}, 200 if ok else 400)

        return self._send_json({"error": "not found"}, 404)


