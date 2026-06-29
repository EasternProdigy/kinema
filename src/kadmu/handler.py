"""The HTTP request handler — the one BaseHTTPRequestHandler subclass, its security
gate (_guard / _authed / _resolve_user / _require_admin), and the do_GET/do_POST
route chains. Pulls together every other module; nothing imports handler but app."""
from __future__ import annotations
import json
import queue
import re
import shutil
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import archive, cloud, dlna, discovery, hls, ops, rt, sources
from .const import (
    APP_NAME, APP_VERSION, FFMPEG, MATURITY_LEVELS, MATURITY_MAX, MIME,
    MP4_COPY_ACODECS, MP4_COPY_VCODECS, NATIVE_EXTS, PLAYLISTS_PATH, PUBLIC_ROUTES,
    REQUEST_TIMEOUT, SESSIONS, SESSIONS_LOCK, SUBTITLE_EXTS, TRANSCODE_LADDER,
    WEB_DIR, _REQ, _io_lock, _stream_sem, load_json, save_json,
)
from .accounts import (
    CLEAR_COOKIE, _current_uid, _db, _meta_set, _pw_check, _session_cookie,
    auth_user, create_user, db_logout, db_logout_user_sessions, db_new_session,
    db_playlists_get, db_playlists_set, db_prefs_get, db_prefs_set, db_session_user,
    delete_user, get_user, get_user_by_name, list_users, set_user_maturity,
    set_user_password, set_user_role, set_user_roots, signup_open, user_count,
)
from .store import (
    _profile_slug, clear_progress, create_profile, delete_profile, get_config,
    is_onboarded, list_profiles, load_progress, load_view_prefs, my_list_items,
    my_list_set, owning_root, preferred_genres, profile_settings, real_roots,
    resolve_within_roots, save_view_prefs, set_config, set_genre_prefs,
    set_profile_settings, set_progress, set_rating, verify_profile_pin, viewer_roots,
)
from .catalog import build_catalog, title_detail
from .recommend import recommend_for_viewer, reco_config, set_reco_weights
from . import tmdb, enrich
from .security import (
    host_allowed, is_loopback, login_check, login_fail, login_ok, new_session,
    parse_cookies, password_required, session_valid, set_lan_mode, set_password,
    verify_password,
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
    "/tmdb-logo.svg": ("tmdb-logo.svg", "image/svg+xml"),   # TMDB attribution mark
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/sw.js": ("sw.js", "application/javascript; charset=utf-8"),
}

CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       # Trailers play in an in-app lightbox via a YouTube embed (privacy-enhanced
       # youtube-nocookie). This only PERMITS the iframe — nothing loads until the user
       # clicks Trailer (which exists only when the optional TMDB layer is on), so the
       # default is still no passive phone-home.
       "frame-src https://www.youtube-nocookie.com https://www.youtube.com; "
       "form-action 'self'")
# Chromecast (opt-in --cast only): the Cast sender SDK is served from Google's gstatic
# CDN — the one place we ever allow a third-party script. The relaxation is applied
# solely when rt.CAST is on, so the default app shell keeps the strict 'self'-only CSP.
CSP_CAST = (CSP.replace("script-src 'self'", "script-src 'self' https://www.gstatic.com")
               .replace("connect-src 'self'", "connect-src 'self' https://www.gstatic.com"))


def _app_csp():
    return CSP_CAST if rt.CAST else CSP

# Phase 5 — CDN cache-busting (only active when rt.CDN, i.e. the hosted edition behind a CDN).
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
# Add ?v=APP_VERSION to the shell's own asset references so a new release busts the edge cache
# without a build step. Only local /js, /style.css, /qr.js refs — never external URLs.
_VERSIONABLE = re.compile(r'(src|href)="(/(?:js/[^"?]+\.js|style\.css|qr\.js))"')


def _cache_for_asset():
    """Cache-Control for /js, /fonts, /style.css: immutable long-cache under the CDN flag,
    else `no-cache` so the browser always revalidates — i.e. you edit a file, refresh, and
    actually see it (a bare missing header lets browsers heuristically cache and hide edits)."""
    return IMMUTABLE_CACHE if rt.CDN else "no-cache"


def _version_shell_html(data: bytes) -> bytes:
    """Append ?v=APP_VERSION to the shell's local asset refs (CDN mode only)."""
    return _VERSIONABLE.sub(rf'\1="\2?v={APP_VERSION}"', data.decode("utf-8")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{APP_VERSION}"
    # Reclaim idle keep-alive connections so sleeping tabs/phones can't slowly
    # accumulate handler threads across a multi-hour session — and a slow-loris
    # backstop. A live transfer resets this on every chunk; only a stalled socket
    # trips it. Tunable via KADMU_REQUEST_TIMEOUT.
    timeout = REQUEST_TIMEOUT

    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        # Capture the final status for metrics/access logging; suppress the noisy
        # default per-line logging (we emit our own structured line in _finish).
        try:
            self._status = int(code)
        except (TypeError, ValueError):
            pass

    def send_response(self, code, message=None):
        # Track that the response has started so an error mid-route knows whether
        # it can still send a clean 500 (vs. having to drop the connection).
        self._response_started = True
        super().send_response(code, message)

    # -- inject security headers on every response -------------------------- #
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    # -- accounting / identity --------------------------------------------- #
    def _identity(self):
        """The bandwidth/quota identity for this request: the signed-in user in
        accounts mode, else the peer IP. Cached on the request thread."""
        ident = getattr(_REQ, "identity", None)
        if ident is not None:
            return ident
        if rt.ACCOUNTS_ENABLED:
            u = self._resolve_user()
            if u:
                ident = f"user:{u['id']}"
        if ident is None:
            ip = self.client_address[0] if self.client_address else "?"
            ident = f"ip:{ip}"
        _REQ.identity = ident
        return ident

    def _wrote(self, n):
        """Account n response-body bytes against this request + the bandwidth meter."""
        if n <= 0:
            return
        _REQ.bytes_out = getattr(_REQ, "bytes_out", 0) + n
        ops.add_bytes(self._identity(), n)

    def _log_user(self):
        if rt.ACCOUNTS_ENABLED:
            u = self._resolve_user()
            if u:
                return u.get("username")
        return None

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
            self._wrote(len(body))

    def _send_bytes(self, data, ctype, status=200, cache=True):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # cache: True → the normal private day cache; False → no header (self-host default);
        # a string → that exact Cache-Control (Phase 5 CDN passes the immutable long-cache).
        if isinstance(cache, str):
            self.send_header("Cache-Control", cache)
        elif cache:
            self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
            self._wrote(len(data))

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

    def _read_raw_body(self, cap=1_000_000):
        """Raw request-body bytes (for non-JSON payloads like DLNA's SOAP XML)."""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return b""
        if length <= 0 or length > cap:
            return b""
        return self.rfile.read(length)

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
        # Cloud-attach (Phase 4a): an instance whose subscription is inactive serves
        # the app shell + /api/session (so the UI can show the inactive notice and the
        # owner can still sign in), but nothing else. Self-host is never gated here.
        if rt.CLOUD_ENABLED and not is_public and not cloud.entitlement_active():
            self._send_json({"error": "Kadmu Cloud subscription inactive.",
                             "entitlement": cloud.entitlement_state(), "needSub": True}, 402)
            return False
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
        # Per-identity concurrency cap (quota): one viewer/IP can't tie up every
        # live encode. Checked before the global pool so the message is accurate.
        ident = self._identity()
        if not ops.stream_acquire(ident):
            ops.note_stream_rejected()
            return self._send_json({"error": "You have too many videos playing at once. "
                                    "Stop one and try again."}, 429)
        # Cap concurrent live encodes (see _stream_sem). A short wait smooths bursts,
        # but never hang a client forever — tell them we're busy so they can retry.
        if not _stream_sem.acquire(timeout=20):
            ops.stream_release(ident)
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
                    self._wrote(len(chunk))
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
            ops.stream_release(ident)

    def _stream_remux(self, path: Path, start: float, audio: int = 0, deint: bool = False):
        """Make a non-native file (an .mkv, or HEVC/x265 inside an .mp4, …) playable
        live, beginning at `start` seconds. Stream-copies the video and audio when
        they're already codecs MP4 can carry in the browser (fast, lossless) and
        transcodes to H.264/AAC only what isn't — at the source resolution, so this
        is 'Original' quality. `audio` selects which audio track to include (its
        ordinal among the file's audio streams). `deint` applies a yadif deinterlace
        filter — which forces a video re-encode (you can't copy a filtered stream).
        Seeking re-requests with a new `t`."""
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
        vf = ["-vf", "yadif"] if deint else []   # deinterlace forces a re-encode below
        if vc and vc in MP4_COPY_VCODECS and not deint:
            v_args = ["-c:v", "copy"]            # already MP4-friendly: no re-encode
        else:
            enc = _h264_encoder()                # libx264, or libopenh264 where x264 is absent
            if not enc:
                return self._send_json({"error": "No H.264 encoder available to convert this video."}, 415)
            if enc == "libx264":
                v_args = ["-c:v", enc, *vf, "-preset", "veryfast", "-tune", "zerolatency",
                          "-crf", "23", "-pix_fmt", "yuv420p"]
            else:
                # libopenh264 wants an explicit bitrate; scale it to the source height
                h = meta.get("height") or 1080
                br = next((TRANSCODE_LADDER[k][0] for k in sorted(TRANSCODE_LADDER) if h <= k),
                          TRANSCODE_LADDER[max(TRANSCODE_LADDER)][0])
                v_args = ["-c:v", enc, *vf, "-b:v", br, "-maxrate", br, "-pix_fmt", "yuv420p"]
        a_args = (["-c:a", "copy"] if (ac and ac in MP4_COPY_ACODECS)
                  else ["-c:a", "aac", "-b:a", "192k", "-ac", "2"])
        cmd = [FFMPEG, "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-i", str(path),
               "-map", "0:v:0", "-map", f"0:a:{max(0, audio)}?", "-sn", *v_args, *a_args,
               "-movflags", "frag_keyframe+empty_moov+default_base_moof",
               "-f", "mp4", "pipe:1"]
        self._pipe_ffmpeg(cmd)

    # -- on-the-fly quality downscale, streamed live ------------------------ #
    def _stream_transcode(self, path: Path, height: int, start: float, audio: int = 0,
                          deint: bool = False):
        """Downscale `path` to `height` lines and pipe it to the client live,
        beginning at `start` seconds. Like _stream_remux but always re-encodes to a
        smaller, lower-bitrate rendition (the quality picker). `audio` selects which
        audio track to carry; `deint` prepends a yadif deinterlace to the scale."""
        enc = _h264_encoder()
        if not FFMPEG or not enc or height not in TRANSCODE_LADDER:
            return self._send_json({"error": "unsupported quality"}, 400)
        bitrate, bufsize = TRANSCODE_LADDER[height]
        vf = (f"yadif,scale=-2:{height}" if deint else f"scale=-2:{height}")
        v_args = ["-c:v", enc, "-vf", vf,
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
    def _serve_file_with_range(self, filepath: Path, ctype, extra_headers=None):
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
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
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
                    self._wrote(len(data))
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_remote_stream(self, ref):
        """Range-proxy a Tier-2 remote file: open a (ranged) GET upstream and relay the
        status + headers + body to the client. The node pulls; the bytes pass through us
        (model A) but are never stored. Forwards the client's Range so seeking works for
        servers that honour it."""
        try:
            resp, status, hd = sources.open_stream(ref, self.headers.get("Range"))
        except sources.SourceError as e:
            return self._send_json({"error": str(e)}, 502)
        if status == 416:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            self.send_response(status)
            for k, v in hd.items():
                self.send_header(k, v)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command == "HEAD":
                return
            while True:
                data = resp.read(256 * 1024)
                if not data:
                    break
                self.wfile.write(data)
                self._wrote(len(data))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                            # client seeked / closed the tab
        finally:
            try:
                resp.close()
            except (OSError, AttributeError):
                pass

    # -- DLNA / UPnP MediaServer (opt-in; LAN-only, no auth) ----------------- #
    def _dlna_xml(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
            self._wrote(len(data))

    def _dlna_base_url(self):
        host = self.headers.get("Host") or f"127.0.0.1:{rt.PORT}"
        return f"http://{host}"

    def _serve_dlna_get(self, route, qs):
        if route == "/dlna/device.xml":
            return self._dlna_xml(dlna.device_xml())
        if route == "/dlna/cd.xml":
            return self._dlna_xml(dlna.CONTENT_DIRECTORY_SCPD)
        if route == "/dlna/cm.xml":
            return self._dlna_xml(dlna.CONNECTION_MANAGER_SCPD)
        if route == "/dlna/media":
            path = resolve_within_roots(unquote(dlna.decode_id(qs.get("id", [""])[0]) or ""))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
            # DLNA renderers want these to accept the stream + seek.
            extra = {"transferMode.dlna.org": "Streaming",
                     "contentFeatures.dlna.org": dlna._dlna_pn(path.suffix.lower())}
            return self._serve_file_with_range(path, ctype, extra_headers=extra)
        return self._send_json({"error": "not found"}, 404)

    def _serve_dlna_post(self, route):
        body = self._read_raw_body()
        if route == "/dlna/control/ContentDirectory":
            action, args = dlna.parse_soap_action(body)
            if action == "Browse":
                didl, num, total = dlna.browse(
                    args.get("ObjectID", "0"), args.get("BrowseFlag", "BrowseDirectChildren"),
                    args.get("StartingIndex", 0), args.get("RequestedCount", 0),
                    self._dlna_base_url())
                return self._dlna_xml(dlna.browse_soap_response(didl, num, total))
            if action == "GetSortCapabilities":
                return self._dlna_xml(dlna.simple_soap_response(dlna._CD_TYPE, action, {"SortCaps": ""}))
            if action == "GetSearchCapabilities":
                return self._dlna_xml(dlna.simple_soap_response(dlna._CD_TYPE, action, {"SearchCaps": ""}))
            if action == "GetSystemUpdateID":
                return self._dlna_xml(dlna.simple_soap_response(dlna._CD_TYPE, action, {"Id": "1"}))
        elif route == "/dlna/control/ConnectionManager":
            action, args = dlna.parse_soap_action(body)
            cm = "urn:schemas-upnp-org:service:ConnectionManager:1"
            if action == "GetProtocolInfo":
                return self._dlna_xml(dlna.simple_soap_response(cm, action,
                                      {"Source": "http-get:*:*:*", "Sink": ""}))
            if action == "GetCurrentConnectionIDs":
                return self._dlna_xml(dlna.simple_soap_response(cm, action, {"ConnectionIDs": ""}))
        # unknown/unsupported action
        data = dlna.soap_fault()
        self.send_response(500)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
            self._wrote(len(data))

    def _serve_static(self, route):
        name, ctype = STATIC_FILES[route]
        fp = WEB_DIR / name
        if not fp.exists():
            self._send_json({"error": "missing asset"}, 404)
            return
        data = fp.read_bytes()
        is_shell = route in ("/", "/index.html")
        if is_shell and rt.CDN:
            data = _version_shell_html(data)         # ?v=APP_VERSION on asset refs (CDN busting)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # The shell (and favicon/manifest/sw) stay short-cached so a release is picked up; under
        # the CDN flag, style.css joins the immutable long-cache (its ?v= changes per release).
        if route == "/style.css" and rt.CDN:
            self.send_header("Cache-Control", IMMUTABLE_CACHE)
        else:
            self.send_header("Cache-Control", "no-cache")
        if is_shell:
            self.send_header("Content-Security-Policy", _app_csp())
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
            self._wrote(len(data))

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
            "profiles": rt.PROFILES_ENABLED,
            "household": rt.ACCOUNTS_ENABLED and rt.PROFILES_ENABLED,
            "accounts": rt.ACCOUNTS_ENABLED,
            "tmdb": tmdb.enabled(),     # metadata layer on → discovery + sharper recs
            "dlna": rt.DLNA,            # UPnP/DLNA MediaServer advertised for TVs/consoles
            "dlnaName": dlna.friendly_name() if rt.DLNA else "",
            "tv": rt.TV,                # default the UI into 10-foot mode (--tv)
            "cast": rt.CAST,            # Chromecast sender enabled (--cast); loads Google's SDK
            "user": None, "role": None,
        }
        # parental controls: the active viewer's maturity ceiling (+ the level labels
        # so the settings UI can render the picker). MATURITY_MAX = no restriction.
        ceiling, _hide = discovery.viewer_ceiling()
        st["maturity"] = ceiling
        st["kid"] = ceiling < MATURITY_MAX
        st["maturityLevels"] = MATURITY_LEVELS
        if rt.ACCOUNTS_ENABLED:
            u = self._resolve_user()
            st["user"] = u
            st["role"] = (u or {}).get("role")
            st["signupOpen"] = signup_open()
            st["needsSetup"] = user_count() == 0
        st["cloud"] = rt.CLOUD_ENABLED
        if rt.CLOUD_ENABLED:
            st["entitlement"] = cloud.entitlement_state()
        return st

    # -- storage overview (Settings → Storage) ------------------------------ #
    def _storage_overview(self):
        """Consolidated storage view: free space per drive, what archiving has
        reclaimed (+ any live job), the trash, remote-source count and catalog size.
        Cheap — disk_usage is O(1) per filesystem; the trash/archive reads are small,
        and the catalog index is already built."""
        # One entry per distinct filesystem the library roots live on, so two roots on
        # the same drive don't double-count its free space.
        drives, by_dev = [], {}
        for r in viewer_roots():
            try:
                dev = r.stat().st_dev
            except OSError:
                continue
            if dev in by_dev:
                by_dev[dev]["roots"].append(r.name)
                continue
            try:
                u = shutil.disk_usage(str(r))
            except OSError:
                continue
            entry = {"roots": [r.name], "path": str(r),
                     "total": u.total, "used": u.used, "free": u.free}
            by_dev[dev] = entry
            drives.append(entry)
        a = archive.status()
        totals = a.get("totals") or {}
        arch = {
            "available": a.get("available", False),
            "codec": a.get("codec", ""), "encoder": a.get("encoder", ""),
            "keepOriginal": a.get("keepOriginal", ""),
            "filesArchived": totals.get("filesArchived", 0),
            "bytesSaved": totals.get("bytesSaved", 0),
            "active": a.get("active"), "queue": len(a.get("queue") or []),
        }
        cat = build_catalog()
        counts = ({"shows": len(cat.get("shows", [])), "movies": len(cat.get("movies", []))}
                  if cat.get("ready") else {"shows": 0, "movies": 0})
        return {
            "drives": drives, "archive": arch, "trash": trash_info(),
            "sources": len(sources.list_sources()), "catalog": counts,
        }

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

    # -- request lifecycle (metrics, rate-limit, logging, error capture) ---- #
    def _begin(self):
        """Reset per-request state — handler threads are reused, so clear it all."""
        self._t0 = time.time()
        self._status = 200
        self._response_started = False
        _REQ.user = None
        _REQ._user_done = False
        _REQ.identity = None
        _REQ.bytes_out = 0

    def _finish(self):
        ops.record_request(getattr(self, "_status", 200))
        try:
            ops.access_log(
                self.command, self.path, getattr(self, "_status", 200),
                getattr(_REQ, "bytes_out", 0),
                int((time.time() - getattr(self, "_t0", time.time())) * 1000),
                self.client_address[0] if self.client_address else "?",
                self._log_user(),
            )
        except Exception:
            pass

    def _on_route_error(self):
        exc = sys.exc_info()[1]
        # client vanished mid-request (closed tab, sleeping phone) — expected, not ours.
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError, socket.timeout)):
            self.close_connection = True
            return
        ops.record_error()
        ops.error_log(self.command, self.path, exc)
        # If nothing has gone out yet we can still return a clean 500; otherwise the
        # only safe move is to drop the (partly-written) connection.
        if not getattr(self, "_response_started", False):
            try:
                self._send_json({"error": "Internal server error"}, 500)
                return
            except Exception:
                pass
        self.close_connection = True

    def _pre(self, route):
        """Checks common to every verb, run before the security gate: health checks
        (which bypass all gating so monitors always work) and per-IP rate limiting
        (loopback is exempt). Returns False if the request was handled/rejected here."""
        if route == "/healthz" and self.command in ("GET", "HEAD"):
            self._send_healthz()
            return False
        ip = self.client_address[0] if self.client_address else ""
        if not is_loopback(ip):
            ok, retry = ops.rate_ok(ip)
            if not ok:
                ops.note_rate_limited()
                self._send_json({"error": "Too many requests. Slow down."}, 429,
                                extra_headers={"Retry-After": str(retry)})
                return False
        return True

    def _send_healthz(self):
        self._send_json({"status": "ok", "app": APP_NAME,
                         "version": APP_VERSION, "uptime": round(ops.uptime(), 1)})

    def _serve_metrics(self):
        """Prometheus metrics. Host-checked like everything else; readable without a
        session from loopback (so a local scraper / `curl` just works), but otherwise
        requires auth (admin in accounts mode) so it isn't world-readable on the LAN."""
        if not host_allowed(self.headers.get("Host", "")):
            return self._send_json({"error": "Host not allowed"}, 403)
        ip = self.client_address[0] if self.client_address else ""
        allowed = is_loopback(ip)
        if not allowed:
            allowed = self._is_admin() if rt.ACCOUNTS_ENABLED else self._authed()
        if not allowed:
            return self._send_json({"error": "Authentication required", "needAuth": True}, 401)
        self._send_bytes(ops.render_metrics().encode("utf-8"),
                         "text/plain; version=0.0.4; charset=utf-8", cache=False)

    # -- verbs -------------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._begin()
        try:
            route = urlparse(self.path).path
            if not self._pre(route):
                return
            self._route_get()
        except Exception:
            self._on_route_error()
        finally:
            self._finish()

    def do_POST(self):
        self._begin()
        try:
            route = urlparse(self.path).path
            if not self._pre(route):
                return
            self._route_post()
        except Exception:
            self._on_route_error()
        finally:
            self._finish()

    def _route_get(self):
        parsed = urlparse(self.path)
        route, qs = parsed.path, parse_qs(parsed.query)

        # DLNA/UPnP (opt-in) — a separate, LAN-only trust domain with no cookies, so it
        # runs before the auth gate. Peer IP is already restricted by verify_request.
        if rt.DLNA and route.startswith("/dlna/"):
            return self._serve_dlna_get(route, qs)

        if route == "/metrics":
            return self._serve_metrics()
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
                return self._send_bytes(fp.read_bytes(), "font/woff2",
                                        cache=(IMMUTABLE_CACHE if rt.CDN else True))
            return self._send_json({"error": "not found"}, 404)

        # The frontend is a set of ordered classic scripts under web/js/.
        if route.startswith("/js/") and route.endswith(".js"):
            name = route[len("/js/"):]
            if "/" in name or ".." in name:
                return self._send_json({"error": "not found"}, 404)
            fp = WEB_DIR / "js" / name
            if fp.is_file():
                return self._send_bytes(fp.read_bytes(),
                                        "application/javascript; charset=utf-8",
                                        cache=_cache_for_asset())
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
            raw_path = unquote(qs.get("path", [""])[0])
            if sources.is_ref(raw_path):       # a Tier-2 remote source: range-proxy it
                return self._serve_remote_stream(raw_path)
            path = resolve_within_roots(raw_path)
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            if not discovery.path_allowed(str(path)):     # parental controls: hard play gate
                return self._send_json({"error": "Restricted by parental controls.",
                                        "restricted": True}, 403)
            ext = path.suffix.lower()
            try:
                audio = max(0, int(qs.get("audio", ["0"])[0]))   # selected audio track ordinal
            except (TypeError, ValueError):
                audio = 0
            deint = qs.get("deint", ["0"])[0] == "1"             # yadif deinterlace (Tune toggle)
            # A native, browser-decodable file is served straight off disk (fully
            # byte-seekable) — unless the viewer picked a non-default audio track or
            # asked to deinterlace, either of which needs a live ffmpeg pass.
            if ext in NATIVE_EXTS and browser_playable(path) and audio == 0 and not deint:
                return self._serve_file_with_range(path, MIME.get(ext, "application/octet-stream"))
            # non-native container (.mkv …) OR a native container whose codec the
            # browser can't decode (e.g. HEVC/x265 inside an .m4v) OR a swapped audio
            # track OR deinterlace: pipe it live, remuxing/transcoding on the fly so
            # playback starts in ~1-2s. Not byte-seekable; the player re-requests `t` to seek.
            try:
                start = float(qs.get("t", ["0"])[0])
            except (TypeError, ValueError):
                start = 0.0
            return self._stream_remux(path, max(0.0, start), audio, deint=deint)

        if route == "/api/transcode":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            if not discovery.path_allowed(str(path)):     # parental controls
                return self._send_json({"error": "Restricted by parental controls.",
                                        "restricted": True}, 403)
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
            deint = qs.get("deint", ["0"])[0] == "1"
            return self._stream_transcode(path, height, start, audio, deint=deint)

        # Adaptive-bitrate HLS (the "Auto" quality). Playlists are computed; segments
        # are transcoded on demand + cached. Same parental-controls gate as /api/stream.
        if route in ("/api/hls/master.m3u8", "/api/hls/media.m3u8", "/api/hls/seg.ts"):
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            if not discovery.path_allowed(str(path)):
                return self._send_json({"error": "Restricted by parental controls.",
                                        "restricted": True}, 403)
            if route == "/api/hls/master.m3u8":
                pl = hls.master(path)
                if pl is None:
                    return self._send_json({"error": "unavailable"}, 415)
                return self._send_bytes(pl.encode("utf-8"), "application/vnd.apple.mpegurl", cache=False)
            try:
                height = int(qs.get("height", ["0"])[0])
            except (TypeError, ValueError):
                return self._send_json({"error": "bad height"}, 400)
            if route == "/api/hls/media.m3u8":
                pl = hls.media(path, height)
                if pl is None:
                    return self._send_json({"error": "unavailable"}, 415)
                return self._send_bytes(pl.encode("utf-8"), "application/vnd.apple.mpegurl", cache=False)
            try:
                i = int(qs.get("i", ["-1"])[0])
            except (TypeError, ValueError):
                return self._send_json({"error": "bad segment"}, 400)
            data = hls.segment(path, height, i)
            if data is None:
                return self._send_json({"error": "not found"}, 404)
            return self._send_bytes(data, "video/mp2t", cache=True)

        if route == "/api/progress":
            return self._send_json(load_progress())

        if route == "/api/continue":
            gate = discovery.play_gate()          # parental controls
            return self._send_json([it for it in continue_watching() if gate(it.get("path", ""))])

        if route == "/api/home":
            data = home_feed()
            gate = discovery.play_gate()          # parental controls
            if isinstance(data, dict):
                if isinstance(data.get("recent"), list):
                    data["recent"] = [it for it in data["recent"] if gate(it.get("path", ""))]
                if data.get("hero") and not gate((data["hero"] or {}).get("path", "")):
                    data["hero"] = None
            return self._send_json(data)

        if route == "/api/catalog":
            # overlay TMDB facets (genre/year/rating/popularity), then drop anything
            # above the active viewer's parental-controls ceiling
            return self._send_json(discovery.filter_maturity(discovery.attach_facets(build_catalog())))

        if route == "/api/history":
            try:
                limit = max(1, min(200, int(qs.get("limit", ["80"])[0])))
            except (TypeError, ValueError):
                limit = 80
            return self._send_json({"items": discovery.watch_history(limit)})

        if route == "/api/archive":
            return self._send_json(archive.status())

        if route == "/api/sources":               # Tier-2 remote sources (list; no secrets)
            return self._send_json({"sources": sources.list_sources()})

        if route == "/api/rbrowse":               # browse one folder of a remote source
            sid = qs.get("src", [""])[0]
            rel = unquote(qs.get("path", [""])[0])
            data = sources.browse(sid, rel)
            if data is None:
                return self._send_json({"error": "unknown source"}, 404)
            return self._send_json(data)

        if route == "/api/recommendations":
            data = recommend_for_viewer()
            gate = discovery.play_gate()          # parental controls
            restricted = discovery.viewer_ceiling()[0] < MATURITY_MAX
            for row in (data.get("rows", []) if isinstance(data, dict) else []):
                kept = []
                for it in row.get("items", []):
                    if it.get("external"):
                        if not restricted:        # can't verify an unowned title's rating → hide from kids
                            kept.append(it)
                    elif gate(it.get("id") or it.get("path", "")):
                        kept.append(it)
                row["items"] = kept
            if isinstance(data, dict):
                data["rows"] = [r for r in data.get("rows", []) if r.get("items")]
            return self._send_json(data)

        if route == "/api/reco/config":
            return self._send_json(reco_config())

        if route == "/api/tmdb/status":
            return self._send_json(enrich.enrich_status())

        if route == "/api/tmdb/img":
            # Server-side poster proxy: keeps the browser same-origin (strict CSP) and
            # caches TMDB images on disk. path/size are validated inside fetch_image.
            got = tmdb.fetch_image(unquote(qs.get("path", [""])[0]),
                                   qs.get("size", ["w342"])[0])
            if not got:
                return self._send_json({"error": "not found"}, 404)
            data, ctype = got
            return self._send_bytes(data, ctype, cache=IMMUTABLE_CACHE)

        if route == "/api/title":
            raw = qs.get("id", [None])[0] or qs.get("path", [None])[0]
            if not raw:
                return self._send_json({"error": "missing id"}, 400)
            detail = title_detail(unquote(raw))
            if detail is None:
                return self._send_json({"error": "not found"}, 404)
            # parental controls: don't reveal a restricted title's episodes/play target
            if not discovery.title_allowed(detail["id"]):
                return self._send_json({"id": detail["id"], "kind": detail.get("kind"),
                                        "name": detail.get("name"), "restricted": True})
            discovery.attach_title_detail(detail)      # TMDB synopsis / cast / cover art
            detail["archive"] = archive.title_archive_state(detail["id"])
            return self._send_json(detail)

        if route == "/api/episodes":
            raw = qs.get("id", [None])[0]
            if not raw:
                return self._send_json({"error": "missing id"}, 400)
            sid = unquote(raw)
            # scope to an owned show folder, and respect parental controls
            target = resolve_within_roots(sid, must_exist=True)
            if target is None or not target.is_dir():
                return self._send_json({"error": "not found"}, 404)
            if not discovery.title_allowed(sid):
                return self._send_json({"episodes": {}, "restricted": True})
            try:
                season = int(qs.get("season", ["0"])[0])
            except (TypeError, ValueError):
                season = 0
            return self._send_json(enrich.season_episodes(sid, season))

        if route == "/api/party/state":
            snap = room_snapshot(qs.get("code", [""])[0])
            if not snap:
                return self._send_json({"error": "no room"}, 404)
            return self._send_json(snap)

        if route == "/api/party/events":
            return self._serve_party_events(qs.get("code", [""])[0])

        if route == "/api/search":
            res = search_library(unquote(qs.get("q", [""])[0]))
            gate = discovery.play_gate()          # parental controls
            if isinstance(res, dict):
                for key in ("folders", "videos"):
                    if isinstance(res.get(key), list):
                        res[key] = [it for it in res[key] if gate(it.get("path", ""))]
            return self._send_json(res)

        if route == "/api/search/external":
            q = unquote(qs.get("q", [""])[0])
            items = enrich.search_external(q) if discovery.external_suggestions_ok() else []
            return self._send_json({"items": items})

        if route == "/api/genres":
            # the genre list for the first-run taste picker (merged movie + TV), plus
            # whatever this viewer already picked. Empty when the metadata layer is off.
            return self._send_json({
                "enabled": tmdb.enabled(),
                "genres": tmdb.genres_combined() if tmdb.enabled() else [],
                "selected": preferred_genres(),
            })

        if route == "/api/discover":
            # rows of titles you DON'T own — the empty-library home + "more to watch".
            # Seeded by the viewer's picked genres; off for maturity-restricted viewers
            # (unowned titles carry no certification to filter on) and without a key.
            ok = discovery.external_suggestions_ok()
            # Seed the rails with the viewer's picked genres AND the genres their library
            # already leans into — so suggestions are present from title one and sharpen
            # as the collection grows ("recommendations always, better as we have more").
            seed = list(dict.fromkeys(list(preferred_genres() or []) + enrich.owned_genres()))
            data = enrich.discover_catalog(seed) if ok else {"enabled": tmdb.enabled(), "rows": [], "genres": []}
            data["ok"] = ok
            data["onboarded"] = is_onboarded()
            return self._send_json(data)

        if route == "/api/mylist":
            gate = discovery.play_gate()          # parental controls
            return self._send_json([it for it in my_list_items() if gate(it.get("path", ""))])

        if route == "/api/profiles":
            profs = list_profiles() if rt.PROFILES_ENABLED else []
            # fold in each profile's parental-controls settings (maturity/kid/pin-set)
            profs = [dict(p, **profile_settings(p["id"])) for p in profs]
            return self._send_json({"enabled": rt.PROFILES_ENABLED, "profiles": profs})

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
            # per-viewer preferences (genres, onboarding, mirrored display prefs).
            # Server-backed in both modes now: per-user in accounts mode, a profile-
            # scoped JSON file otherwise (so taste picks survive a new device).
            return self._send_json(load_view_prefs())

        if route == "/api/trash":
            return self._send_json(trash_info())

        if route == "/api/storage":
            return self._send_json(self._storage_overview())

        return self._send_json({"error": "not found"}, 404)

    def _route_post(self):
        route = urlparse(self.path).path
        # DLNA SOAP control (opt-in) — no cookies, runs before the auth gate (see _route_get).
        if rt.DLNA and route.startswith("/dlna/"):
            return self._serve_dlna_post(route)
        if not self._guard(route, mutating=True):
            return
        self._set_profile()
        body = self._read_body()

        if route == "/api/profiles":
            # create a profile, set a profile's parental controls, or verify a PIN to
            # enter one. Profiles are a family trust model (no inter-profile auth).
            if not rt.PROFILES_ENABLED:
                return self._send_json({"ok": False, "error": "Profiles are disabled."}, 400)
            action = body.get("action")
            if action == "settings":
                ok = set_profile_settings(_profile_slug(str(body.get("id", ""))),
                                          maturity=body.get("maturity"), kid=body.get("kid"),
                                          pin=body.get("pin"), roots=body.get("roots"))
                return self._send_json({"ok": ok})
            if action == "verify":
                ok = verify_profile_pin(_profile_slug(str(body.get("id", ""))), str(body.get("pin", "")))
                return self._send_json({"ok": ok})
            if action == "delete":
                ok = delete_profile(str(body.get("id", "")))
                return self._send_json({"ok": ok, "profiles": list_profiles()})
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
            elif action == "setMaturity":
                ok, err = set_user_maturity(uid, body.get("maturity"))   # parental controls
            elif action == "setRoots":
                ok, err = set_user_roots(uid, body.get("roots") or [])    # library scoping
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

        if route == "/api/rating":
            # personal thumbs-up/down on a show or movie — like progress/My List,
            # allowed even in read-only (it's per-viewer data, not a library write).
            p = resolve_within_roots(body.get("id") or body.get("path"), must_exist=True)
            if not p:
                return self._send_json({"error": "outside library"}, 400)
            try:
                val = int(body.get("value", 0))
            except (TypeError, ValueError):
                return self._send_json({"error": "bad value"}, 400)
            return self._send_json({"ok": True, "value": set_rating(str(p), val)})

        if route == "/api/reco/config":
            # personal recommendation dials — per-viewer prefs, allowed read-only.
            # {"reset": true} (or no weights) returns to automatic/defaults.
            weights = None if body.get("reset") else body.get("weights")
            set_reco_weights(weights)
            return self._send_json(reco_config())

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
            # per-viewer preferences blob — MERGES (preserves keys this client didn't
            # send, e.g. the genre picker's tastes vs. the player's caption prefs).
            # Server-backed in both modes. Not a library write → allowed read-only.
            prefs = body.get("prefs")
            save_view_prefs(prefs if isinstance(prefs, dict) else {})
            return self._send_json({"ok": True})

        if route == "/api/genres":
            # save the viewer's first-run taste picks (+ mark onboarding done). A
            # per-viewer pref, not a library write → allowed even read-only.
            set_genre_prefs(body.get("genres") or [], onboarded=bool(body.get("onboarded", True)))
            return self._send_json({"ok": True, "genres": preferred_genres()})

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

        if route == "/api/tmdb/key":
            # Owner sets the TMDB API key (persisted in config.json; env still wins).
            if not self._require_writable() or not self._require_admin():
                return
            key = str(body.get("key", "")).strip()
            cfg = get_config()
            if key:
                cfg["tmdbKey"] = key
            else:
                cfg.pop("tmdbKey", None)
            set_config(cfg)
            tmdb.set_key(key)
            if tmdb.enabled():
                enrich.request_enrich()     # got a key → start matching the library now
            return self._send_json({"ok": True, "enabled": tmdb.enabled(),
                                    "status": enrich.enrich_status()})

        if route == "/api/tmdb/enrich":
            # Kick (or force a full re-match of) the TMDB enrichment worker.
            if not self._require_writable() or not self._require_admin():
                return
            if not tmdb.enabled():
                return self._send_json({"ok": False, "error": "Add a TMDB API key first."}, 400)
            enrich.request_enrich(force=bool(body.get("force")))
            return self._send_json({"ok": True, "status": enrich.enrich_status()})

        if route == "/api/tmdb/match":
            # Owner override: pin one library title to a specific TMDB id.
            if not self._require_writable() or not self._require_admin():
                return
            cid = resolve_within_roots(body.get("id") or body.get("path"), must_exist=True)
            if not cid:
                return self._send_json({"ok": False, "error": "outside library"}, 400)
            res = enrich.set_manual_match(str(cid), str(body.get("kind", "")),
                                          body.get("tmdbId"))
            if not res:
                return self._send_json({"ok": False, "error": "Couldn't match that title."}, 400)
            return self._send_json({"ok": True, "match": res})

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

        # Archive a finished title (re-encode to reclaim disk). Library-management, so
        # writable + admin like /api/op. The actual encoding runs on the background worker.
        if route == "/api/archive":
            if not self._require_writable() or not self._require_admin():
                return
            tid = body.get("id") or body.get("path")
            if not tid:
                return self._send_json({"ok": False, "error": "missing id"}, 400)
            return self._send_json(archive.enqueue(str(tid)))

        if route == "/api/archive/cancel":
            if not self._require_writable() or not self._require_admin():
                return
            return self._send_json(archive.cancel(body.get("id")))

        # Manage Tier-2 remote sources (add / remove / test). Library config → admin + writable.
        if route == "/api/sources":
            if not self._require_writable() or not self._require_admin():
                return
            action = body.get("action")
            if action == "add":
                return self._send_json(sources.add_source(
                    body.get("name"), body.get("type"), body.get("url"),
                    body.get("username", ""), body.get("password", "")))
            if action == "remove":
                return self._send_json(sources.remove_source(body.get("id")))
            if action == "test":
                return self._send_json(sources.test_source({
                    "type": body.get("type"), "url": (body.get("url") or "").strip().rstrip("/") + "/",
                    "username": body.get("username", ""), "password": body.get("password", "")}))
            return self._send_json({"ok": False, "error": "Unknown action."}, 400)

        return self._send_json({"error": "not found"}, 404)


