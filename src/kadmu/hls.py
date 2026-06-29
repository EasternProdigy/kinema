"""On-demand HLS (HTTP Live Streaming) — adaptive-bitrate VOD for smooth playback on
mobile / remote / flaky networks. We don't pre-segment the file: the media playlist is
*computed* from the duration, and each MPEG-TS segment is transcoded only when the
player requests it (then cached on disk and reaped by the cache janitor). The browser
picks the right rung of the quality ladder and switches as bandwidth changes — via
hls.js (Firefox/Chrome) or native HLS (Safari/iOS).

Stdlib + ffmpeg only; degrades to nothing without ffmpeg / an H.264 encoder. The
segments are H.264/AAC in MPEG-TS, the broadly-compatible HLS shape. Depends on
const/media; nothing here imports handler."""
from __future__ import annotations
import hashlib
import math
import subprocess
from urllib.parse import quote

from .const import FFMPEG, TRANSCODE_LADDER, HLS_DIR, _ffmpeg_sem
from .media import probe_meta, cache_key, _h264_encoder

SEG_DUR = 6.0                       # target seconds per segment


def available():
    return bool(FFMPEG) and _h264_encoder() is not None


def _dims(src):
    m = probe_meta(src)
    return (m.get("width") or 0), (m.get("height") or 0), (m.get("duration") or 0)


def _rungs(src_h):
    """Ladder heights to offer: downscale-only rungs ≤ the source height (or the
    smallest rung for a tiny source)."""
    rs = [k for k in sorted(TRANSCODE_LADDER) if k <= (src_h or 10 ** 9)]
    return rs or [min(TRANSCODE_LADDER)]


def master(src):
    """The master playlist: one variant per ladder rung (relative media-playlist URIs,
    resolved by the player against /api/hls/). None if the source has no duration."""
    w, h, dur = _dims(src)
    if not dur:
        return None
    pq = quote(str(src))
    out = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for ht in _rungs(h):
        br = TRANSCODE_LADDER[ht][0]
        bw = int(br.rstrip("k")) * 1000 + 160000          # video + ~audio headroom
        vw = (round(ht * (w / h) / 2) * 2) if (w and h) else round(ht * 16 / 9)
        out.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bw},RESOLUTION={vw}x{ht}")
        out.append(f"media.m3u8?path={pq}&height={ht}")
    return "\n".join(out) + "\n"


def media(src, height):
    """The per-variant VOD playlist: N computed segments (no transcoding happens here —
    each segment is produced on demand when fetched)."""
    if height not in TRANSCODE_LADDER:
        return None
    dur = _dims(src)[2]
    if not dur:
        return None
    pq = quote(str(src))
    n = max(1, math.ceil(dur / SEG_DUR))
    out = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:VOD",
           f"#EXT-X-TARGETDURATION:{int(math.ceil(SEG_DUR))}", "#EXT-X-MEDIA-SEQUENCE:0"]
    for i in range(n):
        seg = min(SEG_DUR, dur - i * SEG_DUR)
        if seg <= 0:
            break
        out.append(f"#EXTINF:{seg:.3f},")
        out.append(f"seg.ts?path={pq}&height={height}&i={i}")
    out.append("#EXT-X-ENDLIST")
    return "\n".join(out) + "\n"


def segment(src, height, i):
    """The i-th MPEG-TS segment at `height`, transcoded on demand and cached (keyed by
    path+mtime+size, like every other prepared asset). Returns bytes, or None."""
    if not available() or height not in TRANSCODE_LADDER or i < 0:
        return None
    ck = cache_key(src)
    if not ck:
        return None
    digest = hashlib.sha1(f"{ck}|h{height}|s{i}".encode("utf-8")).hexdigest()
    out = HLS_DIR / f"{digest}.ts"
    try:
        if out.exists() and out.stat().st_size > 0:
            return out.read_bytes()
    except OSError:
        pass
    start = i * SEG_DUR
    dur = _dims(src)[2]
    if dur and start >= dur:
        return None
    enc = _h264_encoder()
    bitrate, bufsize = TRANSCODE_LADDER[height]
    v_args = ["-c:v", enc, "-vf", f"scale=-2:{height}", "-b:v", bitrate,
              "-maxrate", bitrate, "-bufsize", bufsize, "-pix_fmt", "yuv420p"]
    if enc == "libx264":
        # veryfast keeps per-segment latency low; force a keyframe at the segment start
        # so segments are self-contained and switch cleanly across variants.
        v_args += ["-preset", "veryfast", "-force_key_frames", f"expr:gte(t,{start})"]
    cmd = [FFMPEG, "-nostdin", "-v", "error",
           "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{SEG_DUR:.3f}",
           "-map", "0:v:0", "-map", "0:a:0?", *v_args,
           "-c:a", "aac", "-b:a", "128k", "-ac", "2",
           "-output_ts_offset", f"{start:.3f}", "-muxdelay", "0", "-muxpreload", "0",
           "-f", "mpegts", "pipe:1"]
    HLS_DIR.mkdir(parents=True, exist_ok=True)
    with _ffmpeg_sem:                         # cap concurrent ffmpeg (anti fork-bomb)
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=120)
        except (subprocess.SubprocessError, OSError):
            return None
    data = res.stdout or b""
    if not data:
        return None
    try:
        out.write_bytes(data)
    except OSError:
        pass
    return data
