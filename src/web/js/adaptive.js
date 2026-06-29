"use strict";
/* adaptive.js — HLS adaptive-bitrate playback (the player's "Auto" quality). The
   vendored hls.js is loaded **lazily**, only the first time Auto is picked, so normal
   playback pays nothing for it. Safari/iOS play HLS natively (no library). Anything
   unsupported / erroring falls back to the existing fixed-quality pipeline.
   Talks to /api/hls/master.m3u8. Classic script sharing the global scope; loads after
   player.js (it calls player globals: video, currentVideo, state, startPlayback, …). */

let hlsPlayer = null;           // the active hls.js instance, or null (native/Off)
let _hlsLibPromise = null;

// Lazy-load the vendored hls.js exactly once. Resolves to true if window.Hls is ready.
function loadHlsLib() {
  if (window.Hls) return Promise.resolve(true);
  if (_hlsLibPromise) return _hlsLibPromise;
  _hlsLibPromise = new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "/js/hls.min.js";
    s.onload = () => resolve(!!window.Hls);
    s.onerror = () => { _hlsLibPromise = null; resolve(false); };
    document.head.appendChild(s);
  });
  return _hlsLibPromise;
}

function teardownHls() {
  if (hlsPlayer) { try { hlsPlayer.destroy(); } catch {} hlsPlayer = null; }
}

// Switch the <video> to the adaptive HLS stream, resuming at `pos` seconds.
async function startHls(pos) {
  if (!currentVideo) return;
  const v = currentVideo;                                   // guard against navigation mid-load
  teardownHls();
  const master = `/api/hls/master.m3u8?path=${enc(v.path)}`;
  const resume = () => {
    try { if (pos > 0) video.currentTime = pos; } catch {}
    if (typeof applyRate === "function") applyRate();
    if (typeof updateTime === "function") updateTime();
    if (typeof startPlayback === "function") startPlayback(); else video.play().catch(() => {});
  };

  // Native HLS (Safari / iOS) — no library needed.
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = master;
    video.onloadedmetadata = resume;
    video.load();
    return;
  }

  const ok = await loadHlsLib();
  if (currentVideo !== v) return;                           // user moved on while loading
  if (!ok || !window.Hls || !window.Hls.isSupported()) {
    toast("Adaptive quality isn't supported here — using a fixed quality.", "err");
    if (typeof setQuality === "function") setQuality("original");
    return;
  }
  hlsPlayer = new window.Hls({ maxBufferLength: 30 });
  hlsPlayer.on(window.Hls.Events.MANIFEST_PARSED, resume);
  hlsPlayer.on(window.Hls.Events.ERROR, (_e, data) => {
    if (data && data.fatal) {
      teardownHls();
      toast("Adaptive playback failed — switching to a fixed quality.", "err");
      if (typeof setQuality === "function") setQuality("original");
    }
  });
  video.removeAttribute("src");
  hlsPlayer.loadSource(master);
  hlsPlayer.attachMedia(video);
}
