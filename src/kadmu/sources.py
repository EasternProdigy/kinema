"""Remote sources (Tier 2 of "stream media you keep elsewhere") — point Kadmu at an
HTTP server, a WebDAV share, or your own box, *without* mounting it. The node lists
the source and range-proxies the bytes to your browser, so the video still flows
through your machine, never anyone else's (model A; egress stays yours).

Stdlib only (`urllib`), no third-party SDKs. Kept in its own lane: nothing here
touches `resolve_within_roots` or the local catalog — a remote file is addressed by
an opaque ref (``kadmu-remote://<source-id>/<relpath>``) that only this module + the
remote routes understand, so the local-path security boundary is unchanged.

Providers in this cut: **http** (a directory-autoindex server: nginx/apache/`python
-m http.server`) and **webdav**. S3-compatible and OAuth providers (Drive/Dropbox)
are the planned next providers; MEGA stays mount-only (E2E-encrypted, stdlib has no
AES). Playback here is native-container only (mp4/webm/…); a non-native remote file
is listed but flagged (it'd need a remote remux, the next increment)."""
from __future__ import annotations
import base64
import re
import socket
import ipaddress
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib import request as urlrequest
from urllib.parse import quote, unquote, urlsplit, urljoin

from .const import VIDEO_EXTS, NATIVE_EXTS
from .store import get_config, set_config

REF_PREFIX = "kadmu-remote://"
_TIMEOUT = 30
_CHUNK = 256 * 1024
SOURCE_TYPES = ("http", "webdav")


# --------------------------------------------------------------------------- #
# Config (sources live in config.json under "sources"; passwords never leave here)
# --------------------------------------------------------------------------- #
def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")
    return s[:32] or "source"


def _all() -> list:
    cfg = get_config()
    srcs = cfg.get("sources")
    return srcs if isinstance(srcs, list) else []


def _public(rec: dict) -> dict:
    """A source as the client may see it — never the stored password."""
    return {"id": rec.get("id"), "name": rec.get("name"), "type": rec.get("type"),
            "url": rec.get("url"), "hasAuth": bool(rec.get("username"))}


def list_sources() -> list:
    return [_public(r) for r in _all()]


def get_source(sid: str):
    return next((r for r in _all() if r.get("id") == sid), None)


def add_source(name, stype, url, username="", password=""):
    stype = (stype or "http").strip().lower()
    url = (url or "").strip()
    if stype not in SOURCE_TYPES:
        return {"ok": False, "error": f"Unknown source type '{stype}'."}
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return {"ok": False, "error": "Enter a full http(s):// URL."}
    if not url.endswith("/"):
        url += "/"                      # a base directory always ends in /
    rec = {"id": "", "name": (name or parts.hostname)[:60], "type": stype, "url": url,
           "username": (username or "").strip(), "password": password or ""}
    base = _slug(rec["name"])
    # set_config does its own locking; admin-only config edits, so a read-modify-write
    # here (no extra lock) is fine — wrapping it in _io_lock would deadlock set_config.
    cfg = get_config()
    srcs = cfg.get("sources")
    if not isinstance(srcs, list):
        srcs = []
    sid, n = base, 2
    existing = {s.get("id") for s in srcs}
    while sid in existing:
        sid = f"{base}-{n}"; n += 1
    rec["id"] = sid
    srcs.append(rec)
    cfg["sources"] = srcs
    set_config(cfg)
    return {"ok": True, "source": _public(rec)}


def remove_source(sid: str):
    cfg = get_config()
    cfg["sources"] = [s for s in (cfg.get("sources") or []) if s.get("id") != sid]
    set_config(cfg)
    return {"ok": True}


def test_source(rec: dict):
    """Try to list the root of a (possibly not-yet-saved) source. Returns counts."""
    try:
        dirs, files = _list_dir(rec, "")
    except SourceError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Couldn't reach it: {e}"}
    return {"ok": True, "folders": len(dirs), "videos": len(files)}


# --------------------------------------------------------------------------- #
# Refs:  kadmu-remote://<source-id>/<relpath>
# --------------------------------------------------------------------------- #
class SourceError(Exception):
    pass


def is_ref(s: str) -> bool:
    return isinstance(s, str) and s.startswith(REF_PREFIX)


def make_ref(sid: str, relpath: str) -> str:
    return REF_PREFIX + sid + "/" + relpath.lstrip("/")


def parse_ref(ref: str):
    """(source_id, relpath) from a ref, or (None, None). relpath is sanitised: no
    '..' escape, no scheme/host — it can only address within the source's base URL."""
    if not is_ref(ref):
        return None, None
    rest = ref[len(REF_PREFIX):]
    sid, _, relpath = rest.partition("/")
    relpath = unquote(relpath)
    if not sid:
        return None, None
    # containment: reject anything that could climb out of the base
    if relpath.startswith(("/", "\\")) or ".." in relpath.replace("\\", "/").split("/"):
        return None, None
    if "://" in relpath:
        return None, None
    return sid, relpath


# --------------------------------------------------------------------------- #
# HTTP layer — auth + an opener that refuses cross-host redirects (anti-SSRF: a
# remote server can't bounce our proxy onto a different/internal host). Only an
# authenticated admin can configure a source, so the base URL itself is trusted.
# --------------------------------------------------------------------------- #
class _NoCrossHostRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            old = (urlsplit(req.full_url).hostname or "").lower()
            new = (urlsplit(newurl).hostname or "").lower()
        except ValueError:
            return None
        if new != old:
            return None                 # block the redirect entirely
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urlrequest.build_opener(_NoCrossHostRedirect())


def _auth_header(rec: dict):
    u, p = rec.get("username"), rec.get("password")
    if not u:
        return {}
    token = base64.b64encode(f"{u}:{p}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + token}


def _abs_url(rec: dict, relpath: str) -> str:
    """The absolute URL for relpath under the source's base, re-checked to still sit
    under the base (defence in depth on top of parse_ref's sanitising)."""
    base = rec["url"]
    full = urljoin(base, "/".join(quote(seg) for seg in relpath.split("/") if seg))
    if not full.startswith(base.rsplit("/", 1)[0]):
        raise SourceError("Path escapes the source.")
    return full


def _request(rec, relpath, method="GET", headers=None, body=None):
    url = _abs_url(rec, relpath)
    h = dict(_auth_header(rec))
    h.update(headers or {})
    req = urlrequest.Request(url, method=method, headers=h, data=body)
    try:
        return _opener.open(req, timeout=_TIMEOUT)
    except urlrequest.HTTPError:
        raise
    except (urlrequest.URLError, socket.timeout, ValueError) as e:
        raise SourceError(f"{getattr(e, 'reason', e)}")


# --------------------------------------------------------------------------- #
# Directory listing — HTTP autoindex (parse <a href>) or WebDAV (PROPFIND XML)
# --------------------------------------------------------------------------- #
class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def _is_video(name: str) -> bool:
    dot = name.rfind(".")
    return dot != -1 and name[dot:].lower() in VIDEO_EXTS


def _entry(rec, relpath, name, is_dir, size=None):
    ref = make_ref(rec["id"], (relpath + "/" + name).strip("/"))
    if is_dir:
        return {"name": name, "path": ref, "isDir": True}
    ext = name[name.rfind("."):].lower() if "." in name else ""
    native = ext in NATIVE_EXTS
    return {"name": name, "path": ref, "isDir": False, "ext": ext, "size": size,
            # only native containers can be range-played as-is; others need a remux (next increment)
            "playable": native, "direct": native, "remote": True}


def _list_http(rec, relpath):
    resp = _request(rec, relpath)
    ctype = resp.headers.get("Content-Type", "")
    html = resp.read(4 * 1024 * 1024).decode("utf-8", "ignore")
    resp.close()
    parser = _LinkParser()
    parser.feed(html)
    dirs, files, seen = [], [], set()
    for href in parser.hrefs:
        if not href or href.startswith(("?", "#", "/")) or "://" in href:
            continue
        href = href.split("?", 1)[0].split("#", 1)[0]
        is_dir = href.endswith("/")
        name = unquote(href.rstrip("/"))
        if not name or name in ("..", ".") or name in seen:
            continue
        seen.add(name)
        if is_dir:
            dirs.append(_entry(rec, relpath, name, True))
        elif _is_video(name):
            files.append(_entry(rec, relpath, name, False))
    return dirs, files


_DAV_NS = {"d": "DAV:"}


def _list_webdav(rec, relpath):
    body = (b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            b'<d:resourcetype/><d:getcontentlength/></d:prop></d:propfind>')
    resp = _request(rec, relpath, method="PROPFIND",
                    headers={"Depth": "1", "Content-Type": "application/xml"}, body=body)
    raw = resp.read(8 * 1024 * 1024)
    resp.close()
    root = ET.fromstring(raw)
    base_path = urlsplit(rec["url"]).path
    here = (base_path + relpath).rstrip("/") + "/"
    dirs, files = [], []
    for r in root.findall("d:response", _DAV_NS):
        href_el = r.find("d:href", _DAV_NS)
        if href_el is None or not href_el.text:
            continue
        path = urlsplit(href_el.text).path
        if path.rstrip("/") == here.rstrip("/"):
            continue                       # the directory itself
        name = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        if not name:
            continue
        is_dir = r.find(".//d:collection", _DAV_NS) is not None
        if is_dir:
            dirs.append(_entry(rec, relpath, name, True))
        elif _is_video(name):
            length = r.find(".//d:getcontentlength", _DAV_NS)
            size = int(length.text) if (length is not None and (length.text or "").isdigit()) else None
            files.append(_entry(rec, relpath, name, False, size))
    return dirs, files


def _list_dir(rec, relpath):
    if rec.get("type") == "webdav":
        return _list_webdav(rec, relpath)
    return _list_http(rec, relpath)


def browse(sid: str, relpath: str):
    """List one folder of a source. Returns the standard browse payload (dirs +
    playable videos), or None if the source is unknown."""
    rec = get_source(sid)
    if rec is None:
        return None
    try:
        dirs, files = _list_dir(rec, relpath.strip("/"))
    except (SourceError, urlrequest.HTTPError) as e:
        return {"error": str(e), "dirs": [], "files": []}
    dirs.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())
    return {"source": _public(rec), "relpath": relpath.strip("/"),
            "dirs": dirs, "files": files}


# --------------------------------------------------------------------------- #
# Range proxy — open a (ranged) GET upstream so the handler can relay the bytes.
# --------------------------------------------------------------------------- #
def open_stream(ref: str, range_header=None):
    """Open the upstream file for a remote ref, forwarding a Range header. Returns
    (response, status, headers_dict) — caller relays + closes — or raises SourceError."""
    sid, relpath = parse_ref(ref)
    if sid is None:
        raise SourceError("Bad remote reference.")
    rec = get_source(sid)
    if rec is None:
        raise SourceError("Unknown source.")
    headers = {}
    if range_header:
        headers["Range"] = range_header
    try:
        resp = _request(rec, relpath, headers=headers)
    except urlrequest.HTTPError as e:
        if e.code == 416:               # range not satisfiable — relay it
            return None, 416, {}
        raise SourceError(f"Upstream error {e.code}")
    status = getattr(resp, "status", 200) or 200
    hd = {
        "Content-Type": resp.headers.get("Content-Type") or "application/octet-stream",
        "Content-Length": resp.headers.get("Content-Length"),
        "Content-Range": resp.headers.get("Content-Range"),
        "Accept-Ranges": resp.headers.get("Accept-Ranges") or "bytes",
    }
    return resp, status, {k: v for k, v in hd.items() if v is not None}
