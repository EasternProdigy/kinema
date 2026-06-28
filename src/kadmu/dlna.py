"""DLNA / UPnP MediaServer — put Kadmu on the TV with no app install. Smart TVs,
PlayStation/Xbox, and most media players discover a UPnP MediaServer on the LAN and
play straight from it, in their *native* decoder (so they handle mkv/HEVC/AC3 that a
browser can't). This is the cheapest possible living-room path: LAN-local, the node
serves the bytes directly, **zero cloud egress, zero external services, stdlib only.**

Off by default (`--dlna` / `KADMU_DLNA=1`) — it shares the library to LAN devices with
no auth (the DLNA trust model), so it's opt-in and implies network sharing.

Two halves:
  * SSDP (UDP multicast on 239.255.255.250:1900) — discovery: answer M-SEARCH and
    announce alive/byebye, pointing devices at our device description.
  * ContentDirectory (SOAP over the main HTTP server, in handler.py) — Browse the
    library as folders/items; each item's <res> URL points back at /dlna/media, which
    range-serves the raw file (reusing the existing range server).

Depends only on const/store/media (+ rt for the flag). Nothing here imports handler."""
from __future__ import annotations
import base64
import socket
import struct
import threading
import time
import uuid as _uuidlib
from html import escape as _xml
from pathlib import Path
from xml.etree import ElementTree as ET

from .const import APP_VERSION, DATA_DIR, MIME, VIDEO_EXTS
from .store import real_roots, resolve_within_roots
from .media import cache_key, _meta_snapshot

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
_DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaServer:1"
_CD_TYPE = "urn:schemas-upnp-org:service:ContentDirectory:1"

# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
def device_uuid() -> str:
    """A stable per-install UUID (persisted), so renderers remember us across restarts."""
    p = DATA_DIR / "dlna_uuid"
    try:
        if p.exists():
            v = p.read_text("utf-8").strip()
            if v:
                return v
    except OSError:
        pass
    v = str(_uuidlib.uuid4())
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(v, "utf-8")
    except OSError:
        pass
    return v


def friendly_name() -> str:
    try:
        host = socket.gethostname().split(".")[0]
    except OSError:
        host = ""
    return f"Kadmu ({host})" if host else "Kadmu"


# --------------------------------------------------------------------------- #
# Object ids: "0" is the root; everything else is the base64url of an absolute path.
# (Round-trips cleanly through XML attrs/SOAP, and re-validates via resolve_within_roots.)
# --------------------------------------------------------------------------- #
def encode_id(path) -> str:
    return base64.urlsafe_b64encode(str(path).encode("utf-8")).decode("ascii")


def decode_id(oid):
    if not oid or oid == "0":
        return None
    try:
        return base64.urlsafe_b64decode(oid.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


# --------------------------------------------------------------------------- #
# Device description + service descriptions (served at /dlna/*.xml)
# --------------------------------------------------------------------------- #
def device_xml() -> bytes:
    u = device_uuid()
    return (f"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0">
 <specVersion><major>1</major><minor>0</minor></specVersion>
 <device>
  <deviceType>{_DEVICE_TYPE}</deviceType>
  <friendlyName>{_xml(friendly_name())}</friendlyName>
  <manufacturer>Pentarosa Co.</manufacturer>
  <manufacturerURL>https://kadmu.app</manufacturerURL>
  <modelName>Kadmu</modelName>
  <modelNumber>{APP_VERSION}</modelNumber>
  <dlna:X_DLNADOC>DMS-1.50</dlna:X_DLNADOC>
  <UDN>uuid:{u}</UDN>
  <serviceList>
   <service>
    <serviceType>{_CD_TYPE}</serviceType>
    <serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
    <SCPDURL>/dlna/cd.xml</SCPDURL>
    <controlURL>/dlna/control/ContentDirectory</controlURL>
    <eventSubURL>/dlna/event/ContentDirectory</eventSubURL>
   </service>
   <service>
    <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
    <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
    <SCPDURL>/dlna/cm.xml</SCPDURL>
    <controlURL>/dlna/control/ConnectionManager</controlURL>
    <eventSubURL>/dlna/event/ConnectionManager</eventSubURL>
   </service>
  </serviceList>
 </device>
</root>""").encode("utf-8")


# Minimal-but-valid SCPDs. Renderers fetch these to learn the actions/arguments.
CONTENT_DIRECTORY_SCPD = b"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
 <specVersion><major>1</major><minor>0</minor></specVersion>
 <actionList>
  <action><name>GetSearchCapabilities</name><argumentList>
   <argument><name>SearchCaps</name><direction>out</direction><relatedStateVariable>SearchCapabilities</relatedStateVariable></argument>
  </argumentList></action>
  <action><name>GetSortCapabilities</name><argumentList>
   <argument><name>SortCaps</name><direction>out</direction><relatedStateVariable>SortCapabilities</relatedStateVariable></argument>
  </argumentList></action>
  <action><name>GetSystemUpdateID</name><argumentList>
   <argument><name>Id</name><direction>out</direction><relatedStateVariable>SystemUpdateID</relatedStateVariable></argument>
  </argumentList></action>
  <action><name>Browse</name><argumentList>
   <argument><name>ObjectID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable></argument>
   <argument><name>BrowseFlag</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_BrowseFlag</relatedStateVariable></argument>
   <argument><name>Filter</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable></argument>
   <argument><name>StartingIndex</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable></argument>
   <argument><name>RequestedCount</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
   <argument><name>SortCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable></argument>
   <argument><name>Result</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable></argument>
   <argument><name>NumberReturned</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
   <argument><name>TotalMatches</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
   <argument><name>UpdateID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_UpdateID</relatedStateVariable></argument>
  </argumentList></action>
 </actionList>
 <serviceStateTable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_ObjectID</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_Result</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_BrowseFlag</name><dataType>string</dataType>
   <allowedValueList><allowedValue>BrowseMetadata</allowedValue><allowedValue>BrowseDirectChildren</allowedValue></allowedValueList></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_Filter</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_SortCriteria</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_Index</name><dataType>ui4</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_Count</name><dataType>ui4</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>A_ARG_TYPE_UpdateID</name><dataType>ui4</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>SearchCapabilities</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="no"><name>SortCapabilities</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="yes"><name>SystemUpdateID</name><dataType>ui4</dataType></stateVariable>
 </serviceStateTable>
</scpd>"""

CONNECTION_MANAGER_SCPD = b"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
 <specVersion><major>1</major><minor>0</minor></specVersion>
 <actionList>
  <action><name>GetProtocolInfo</name><argumentList>
   <argument><name>Source</name><direction>out</direction><relatedStateVariable>SourceProtocolInfo</relatedStateVariable></argument>
   <argument><name>Sink</name><direction>out</direction><relatedStateVariable>SinkProtocolInfo</relatedStateVariable></argument>
  </argumentList></action>
  <action><name>GetCurrentConnectionIDs</name><argumentList>
   <argument><name>ConnectionIDs</name><direction>out</direction><relatedStateVariable>CurrentConnectionIDs</relatedStateVariable></argument>
  </argumentList></action>
 </actionList>
 <serviceStateTable>
  <stateVariable sendEvents="yes"><name>SourceProtocolInfo</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="yes"><name>SinkProtocolInfo</name><dataType>string</dataType></stateVariable>
  <stateVariable sendEvents="yes"><name>CurrentConnectionIDs</name><dataType>string</dataType></stateVariable>
 </serviceStateTable>
</scpd>"""


# --------------------------------------------------------------------------- #
# Browse — turn library folders/files into DIDL-Lite
# --------------------------------------------------------------------------- #
def _dlna_pn(ext):
    return "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"


def _duration_str(path: Path):
    """H:MM:SS from the *cached* probe only (never probe during a browse — keep it cheap)."""
    key = cache_key(path)
    if not key:
        return None
    dur = (_meta_snapshot().get(key) or {}).get("duration")
    if not dur:
        return None
    s = int(dur)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}.000"


def _container_xml(path: Path, parent_id: str, title=None) -> str:
    return (f'<container id="{encode_id(path)}" parentID="{parent_id}" restricted="1">'
            f'<dc:title>{_xml(title or path.name)}</dc:title>'
            f'<upnp:class>object.container.storageFolder</upnp:class></container>')


def _item_xml(path: Path, parent_id: str, base_url: str) -> str:
    ext = path.suffix.lower()
    mime = MIME.get(ext, "video/mpeg")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    res_url = f"{base_url}/dlna/media?id={encode_id(path)}"
    dur = _duration_str(path)
    dur_attr = f' duration="{dur}"' if dur else ""
    proto = f"http-get:*:{mime}:{_dlna_pn(ext)}"
    return (f'<item id="{encode_id(path)}" parentID="{parent_id}" restricted="1">'
            f'<dc:title>{_xml(path.stem)}</dc:title>'
            f'<upnp:class>object.item.videoItem</upnp:class>'
            f'<res protocolInfo="{_xml(proto)}" size="{size}"{dur_attr}>{_xml(res_url)}</res>'
            f'</item>')


def _children(target):
    """(containers, items) under a directory (or the roots when target is None)."""
    if target is None:                       # the virtual root: each library root is a folder
        roots = real_roots()
        return [(r, r.name) for r in roots], []
    dirs, files = [], []
    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return [], []
    for p in entries:
        if p.name.startswith(".") or p.name == ".kadmu-trash":
            continue
        try:
            if p.is_dir():
                dirs.append((p, p.name))
            elif p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                files.append(p)
        except OSError:
            continue
    return dirs, files


def _parent_id_of(target):
    if target is None:
        return "-1"
    root_paths = {str(r) for r in real_roots()}
    if str(target) in root_paths:
        return "0"
    return encode_id(target.parent)


def browse(object_id, browse_flag, start, count, base_url):
    """Return (didl_xml, number_returned, total_matches) for a ContentDirectory Browse."""
    raw = decode_id(object_id)
    target = None if raw is None else resolve_within_roots(raw, must_exist=True)
    head = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">')
    tail = "</DIDL-Lite>"

    if browse_flag == "BrowseMetadata":
        # Describe the object itself (renderers do this before drilling in).
        if target is None:
            body = (f'<container id="0" parentID="-1" restricted="1">'
                    f'<dc:title>{_xml(friendly_name())}</dc:title>'
                    f'<upnp:class>object.container.storageFolder</upnp:class></container>')
        elif target.is_dir():
            body = _container_xml(target, _parent_id_of(target))
        else:
            body = _item_xml(target, _parent_id_of(target), base_url)
        return head + body + tail, 1, 1

    # BrowseDirectChildren
    if raw is not None and target is None:
        return head + tail, 0, 0           # gone / outside roots
    dirs, files = _children(target)
    parent_for_children = "0" if target is None else encode_id(target)
    total = len(dirs) + len(files)
    try:
        start = max(0, int(start))
    except (TypeError, ValueError):
        start = 0
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        count = total
    window = (list(("c", d, t) for d, t in dirs) + list(("i", f, None) for f in files))[start:start + count]
    parts = []
    for kind, p, title in window:
        if kind == "c":
            parts.append(_container_xml(p, parent_for_children, title))
        else:
            parts.append(_item_xml(p, parent_for_children, base_url))
    return head + "".join(parts) + tail, len(window), total


# --------------------------------------------------------------------------- #
# SOAP envelopes
# --------------------------------------------------------------------------- #
def browse_soap_response(didl, num_returned, total) -> bytes:
    return (f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body><u:BrowseResponse xmlns:u="{_CD_TYPE}">
<Result>{_xml(didl)}</Result>
<NumberReturned>{num_returned}</NumberReturned>
<TotalMatches>{total}</TotalMatches>
<UpdateID>1</UpdateID>
</u:BrowseResponse></s:Body></s:Envelope>""").encode("utf-8")


def simple_soap_response(service_type, action, args) -> bytes:
    body = "".join(f"<{k}>{_xml(str(v))}</{k}>" for k, v in args.items())
    return (f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body><u:{action}Response xmlns:u="{service_type}">{body}</u:{action}Response></s:Body></s:Envelope>""").encode("utf-8")


def soap_fault() -> bytes:
    return (b'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            b'<s:Body><s:Fault><faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring>'
            b'<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
            b'<errorCode>401</errorCode><errorDescription>Invalid Action</errorDescription>'
            b'</UPnPError></detail></s:Fault></s:Body></s:Envelope>')


def _localname(tag):
    return tag.rsplit("}", 1)[-1]


def parse_soap_action(body: bytes):
    """(action_name, {arg: value}) from a SOAP control request; (None, {}) if unparseable."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None, {}
    soap_body = next((c for c in root.iter() if _localname(c.tag) == "Body"), None)
    if soap_body is None:
        return None, {}
    action_el = next((c for c in list(soap_body) if len(c.tag)), None)
    if action_el is None:
        return None, {}
    action = _localname(action_el.tag)
    args = {_localname(c.tag): (c.text or "") for c in action_el}
    return action, args


# --------------------------------------------------------------------------- #
# SSDP discovery responder (UDP multicast)
# --------------------------------------------------------------------------- #
def _lan_ip(toward="10.255.255.255"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((toward, 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _msearch_header(text, name):
    for line in text.split("\r\n"):
        k, sep, v = line.partition(":")
        if sep and k.strip().lower() == name.lower():
            return v.strip().strip('"')
    return ""


class SSDPResponder(threading.Thread):
    """Answers M-SEARCH discovery and periodically announces presence, so LAN
    renderers find Kadmu. One daemon thread; stops cleanly with a byebye."""
    def __init__(self, http_port):
        super().__init__(name="kadmu-ssdp", daemon=True)
        self.http_port = http_port
        self.uuid = device_uuid()
        self._stop = threading.Event()
        self._sock = None
        self.ok = False

    def _location(self, ip):
        return f"http://{ip}:{self.http_port}/dlna/device.xml"

    def _targets(self):
        return ("upnp:rootdevice", _DEVICE_TYPE, _CD_TYPE,
                "urn:schemas-upnp-org:service:ConnectionManager:1")

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", SSDP_PORT))
            mreq = struct.pack("=4sl", socket.inet_aton(SSDP_ADDR), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            # 1900 already taken (another DLNA server) — discovery off, HTTP still works.
            return
        sock.settimeout(1.0)
        self._sock = sock
        self.ok = True
        self._announce(alive=True)
        last = time.time()
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                if time.time() - last > 600:
                    self._announce(alive=True)
                    last = time.time()
                continue
            except OSError:
                break
            self._reply(data, addr)
        try:
            self._announce(alive=False)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _reply(self, data, addr):
        try:
            text = data.decode("utf-8", "ignore")
        except Exception:
            return
        if not text.upper().startswith("M-SEARCH"):
            return
        st = _msearch_header(text, "ST")
        match = st in self._targets() or st == "ssdp:all" or st == "upnp:rootdevice" \
            or st == f"uuid:{self.uuid}"
        if not match:
            return
        ip = _lan_ip(addr[0])
        sts = list(self._targets()) if st in ("ssdp:all",) else [st if st != f"uuid:{self.uuid}" else f"uuid:{self.uuid}"]
        for reply_st in sts:
            usn = f"uuid:{self.uuid}" if reply_st.startswith("uuid:") else f"uuid:{self.uuid}::{reply_st}"
            msg = ("HTTP/1.1 200 OK\r\n"
                   "CACHE-CONTROL: max-age=1800\r\n"
                   f"LOCATION: {self._location(ip)}\r\n"
                   "SERVER: Kadmu UPnP/1.0 DLNADOC/1.50\r\n"
                   f"ST: {reply_st}\r\n"
                   f"USN: {usn}\r\n"
                   "EXT:\r\n\r\n")
            try:
                self._sock.sendto(msg.encode("utf-8"), addr)
            except OSError:
                pass

    def _announce(self, alive):
        if not self._sock:
            return
        ip = _lan_ip()
        nts = "ssdp:alive" if alive else "ssdp:byebye"
        notes = [("upnp:rootdevice", f"uuid:{self.uuid}::upnp:rootdevice"),
                 (f"uuid:{self.uuid}", f"uuid:{self.uuid}")]
        for t in self._targets()[1:]:
            notes.append((t, f"uuid:{self.uuid}::{t}"))
        for nt, usn in notes:
            lines = ["NOTIFY * HTTP/1.1", f"HOST: {SSDP_ADDR}:{SSDP_PORT}",
                     "CACHE-CONTROL: max-age=1800", f"NT: {nt}", f"NTS: {nts}",
                     f"USN: {usn}", "SERVER: Kadmu UPnP/1.0 DLNADOC/1.50"]
            if alive:
                lines.insert(3, f"LOCATION: {self._location(ip)}")
            msg = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
            try:
                self._sock.sendto(msg, (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass

    def stop(self):
        self._stop.set()


_responder: SSDPResponder | None = None


def start(http_port):
    """Start SSDP discovery. Returns True if the responder bound 1900."""
    global _responder
    if _responder and _responder.is_alive():
        return _responder.ok
    _responder = SSDPResponder(http_port)
    _responder.start()
    time.sleep(0.2)              # let it bind so we can report status
    return _responder.ok


def stop():
    global _responder
    if _responder:
        _responder.stop()
        _responder = None
