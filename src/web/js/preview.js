"use strict";
/* preview.js — Netflix-style autoplay hover-previews. Brush a poster tile and, after a
   short dwell, its video starts playing muted right in the card. Strictly bounded:
   - only ONE preview plays at a time (the previous is torn down first),
   - only tiles flagged data-direct="1" preview (native files that stream straight off
     disk), so a hover never starts an ffmpeg remux,
   - skipped on touch (no hover), with reduced-motion, in TV mode (focus-based nav), and
     while the player is open.
   Tearing a preview down drops its <video> src so the byte stream stops immediately.
   Classic script sharing the global scope; loads after catalog.js/home.js. */

const PREVIEW_DWELL = 650;     // ms the pointer must rest on a tile before a preview starts
let _previewTimer = null;
let _activePreview = null;     // the live <video>, or null
let _previewCard = null;       // the card it belongs to

function _previewAllowed() {
  if (state.tvMode) return false;                                   // TV mode navigates by focus
  if (!$("#playerOverlay").classList.contains("hidden")) return false;  // not while watching
  try {
    if (matchMedia("(hover: none)").matches) return false;          // touch: no real hover
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  } catch {}
  return true;
}

function killTilePreview() {
  if (_previewTimer) { clearTimeout(_previewTimer); _previewTimer = null; }
  if (_activePreview) {
    const v = _activePreview;
    try { v.pause(); v.removeAttribute("src"); v.load(); } catch {}   // load() after src removal stops the fetch
    v.remove();
    _activePreview = null;
  }
  if (_previewCard) { _previewCard.classList.remove("previewing"); _previewCard = null; }
}

function startTilePreview(card) {
  const path = card.dataset.preview;
  if (!path || card.dataset.direct !== "1") return;
  const poster = $(".poster", card);
  if (!poster) return;
  killTilePreview();
  _previewCard = card;
  const v = document.createElement("video");
  v.className = "tile-preview";
  v.muted = true; v.defaultMuted = true; v.loop = true;
  v.playsInline = true; v.setAttribute("playsinline", "");
  v.preload = "auto";
  v.src = `/api/stream?path=${enc(path)}`;
  // Skip a touch in so we don't sit on a black cold-open frame.
  v.onloadedmetadata = () => {
    try { if (v.duration && isFinite(v.duration)) v.currentTime = Math.min(45, v.duration * 0.12); } catch {}
  };
  v.oncanplay = () => { if (_activePreview === v) card.classList.add("previewing"); };
  v.onerror = () => { if (_activePreview === v) killTilePreview(); };
  _activePreview = v;
  poster.appendChild(v);
  v.play().catch(() => {});   // autoplay can be blocked; muted should be allowed
}

// Delegated hover: mouseover/mouseout bubble (unlike mouseenter/leave), so this covers
// every tile in every rail/grid, including ones rendered after load.
document.addEventListener("mouseover", (e) => {
  if (!_previewAllowed()) return;
  const card = e.target.closest && e.target.closest(".title-card");
  if (!card || card.classList.contains("external")) return;          // external = not owned, no clip
  if (card === _previewCard) return;                                 // already previewing this one
  if (card.dataset.direct !== "1") return;
  if (_previewTimer) clearTimeout(_previewTimer);
  _previewTimer = setTimeout(() => startTilePreview(card), PREVIEW_DWELL);
});
document.addEventListener("mouseout", (e) => {
  const card = e.target.closest && e.target.closest(".title-card");
  if (!card) return;
  // Ignore moves between children of the same card; only tear down when leaving the card.
  if (e.relatedTarget && card.contains(e.relatedTarget)) return;
  if (card === _previewCard || card.contains(e.target)) killTilePreview();
});
// Drop any preview when scrolling away or opening the player, so nothing keeps streaming.
window.addEventListener("scroll", () => { if (_activePreview || _previewTimer) killTilePreview(); }, { passive: true });
