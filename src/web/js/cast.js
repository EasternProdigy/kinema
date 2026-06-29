"use strict";
/* cast.js — Chromecast sender (opt-in). Inert unless the server runs with --cast, which
   is the ONE place Kadmu loads a third-party script (Google's Cast SDK from gstatic) and
   the only reason the app-shell CSP is ever relaxed — both strictly gated on rt.CAST.
   DLNA stays the privacy-pure "play on the TV" path; this is for households already living
   in the Google/Chrome ecosystem.

   The Chromecast pulls the video straight from this node over the LAN, so — like DLNA — it
   needs an open (no-password) LAN reached by the machine's network address, not 127.0.0.1.
   Casting is a Chrome/Edge feature; on browsers without Cast the button simply never shows. */

let castReady = false;
let castLoading = false;

function castOn() { return !!(state.session && state.session.cast); }
function _castLoopback() { return /^(localhost|127\.|0\.0\.0\.0|\[::1?\]?)/i.test(location.hostname); }

function initCast() {
  if (!castOn() || castLoading || castReady) return;
  castLoading = true;
  // The SDK invokes this global once it's ready (must exist before the script loads).
  window.__onGCastApiAvailable = function (available) {
    if (available) { try { setupCastContext(); } catch (e) { /* SDK shape changed */ } }
  };
  const s = document.createElement("script");
  s.src = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
  s.onerror = () => { castLoading = false; };   // offline / blocked: stay silent, button hidden
  document.head.appendChild(s);
}

function setupCastContext() {
  if (typeof cast === "undefined" || !cast.framework || typeof chrome === "undefined") return;
  const ctx = cast.framework.CastContext.getInstance();
  ctx.setOptions({
    receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
    autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
  });
  castReady = true;
  ctx.addEventListener(cast.framework.CastContextEventType.CAST_STATE_CHANGED, updateCastButton);
  updateCastButton();
}

// "NO_DEVICES_AVAILABLE" | "NOT_CONNECTED" | "CONNECTING" | "CONNECTED"
function castState() {
  try { return cast.framework.CastContext.getInstance().getCastState(); }
  catch { return "NO_DEVICES_AVAILABLE"; }
}
// Show the player's cast button only when a receiver is actually on the network.
function updateCastButton() {
  const btn = $("#castBtn");
  if (btn) {
    const avail = castReady && castState() !== "NO_DEVICES_AVAILABLE";
    btn.classList.toggle("hidden", !avail);
    btn.classList.toggle("on", castReady && castState() === "CONNECTED");
  }
  if (typeof renderCast === "function" && !$("#settingsModal").classList.contains("hidden")) renderCast();
}

function _castContentType() {
  return ((currentVideo && currentVideo.path) || "").toLowerCase().endsWith(".webm")
    ? "video/webm" : "video/mp4";
}

// Start (or reuse) a cast session and load the current video on the TV.
function castCurrent() {
  if (!castReady || !currentVideo) return;
  if (_castLoopback()) {
    toast("Open Kadmu by its network address (not localhost) to cast", "err");
    return;
  }
  const ctx = cast.framework.CastContext.getInstance();
  ctx.requestSession().then(() => {
    const session = ctx.getCurrentSession();
    if (!session) return;
    const url = location.origin + `/api/stream?path=${enc(currentVideo.path)}`;
    const info = new chrome.cast.media.MediaInfo(url, _castContentType());
    info.metadata = new chrome.cast.media.GenericMediaMetadata();
    info.metadata.title = (typeof dispName === "function") ? dispName(currentVideo) : currentVideo.path;
    const req = new chrome.cast.media.LoadRequest(info);
    try { req.currentTime = currentPlayPos() || 0; } catch {}
    session.loadMedia(req).then(
      () => { try { video.pause(); } catch {} toast("Casting to your TV", "ok"); },
      () => toast("Couldn't cast — the TV must be able to reach this computer", "err")
    );
  }).catch(() => {});   // user dismissed the device picker
}

// Settings → "On a TV or big screen": a short status line under the TV-mode toggle.
function renderCast() {
  const box = $("#castControl");
  if (!box) return;
  if (!castOn()) { box.innerHTML = ""; box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const note = _castLoopback()
    ? "Open Kadmu by its network address (the link above) so the Chromecast can reach it."
    : (castState() !== "NO_DEVICES_AVAILABLE"
        ? "A Chromecast is on your network — use the cast button in the player."
        : "Looking for a Chromecast on your Wi-Fi… (casting needs Chrome or Edge).");
  box.innerHTML = `<p class="muted small">📺 Chromecast is <b>on</b> for this server. ${escapeHtml(note)} `
    + `Works best on an open (no-password) LAN; <b>DLNA</b> is the private alternative.</p>`;
}
