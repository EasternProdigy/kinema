"use strict";
/* filters.js — non-destructive video adjustments applied as CSS on the <video>:
   brightness / contrast / saturation, rotate, horizontal & vertical flip, zoom,
   and the fit mode (contain / cover / stretch). Pure presentation — the file on
   disk and the decoded stream are never touched. These are session-global (like
   VLC's video adjustments), not per-file.
   Part of the Kadmu frontend; classic script sharing the global scope. */

const FIT_MODES = [
  { id: "contain", label: "Fit",     css: "contain" },
  { id: "cover",   label: "Crop",    css: "cover" },
  { id: "fill",    label: "Stretch", css: "fill" },
];

const filtersState = {
  brightness: 1,    // 0.4 .. 1.6
  contrast: 1,      // 0.4 .. 1.6
  saturation: 1,    // 0 .. 2
  rotate: 0,        // 0 | 90 | 180 | 270
  flipH: false,
  flipV: false,
  zoom: 1,          // 1 .. 2
  fit: "contain",
};

function filtersActive() {
  const s = filtersState;
  return s.brightness !== 1 || s.contrast !== 1 || s.saturation !== 1 ||
    s.rotate !== 0 || s.flipH || s.flipV || s.zoom !== 1 || s.fit !== "contain";
}

function applyFilters() {
  if (!video) return;
  const s = filtersState;
  video.style.filter =
    `brightness(${s.brightness}) contrast(${s.contrast}) saturate(${s.saturation})`;
  const sx = s.zoom * (s.flipH ? -1 : 1);
  const sy = s.zoom * (s.flipV ? -1 : 1);
  video.style.transform = `rotate(${s.rotate}deg) scale(${sx}, ${sy})`;
  video.style.objectFit = (FIT_MODES.find(m => m.id === s.fit) || FIT_MODES[0]).css;
}

function setAdjust(key, val) {
  if (!(key in filtersState)) return;
  filtersState[key] = +val;
  applyFilters();
}
function rotateBy(deg) {
  filtersState.rotate = ((filtersState.rotate + deg) % 360 + 360) % 360;
  applyFilters();
}
function setRotate(deg) { filtersState.rotate = ((deg % 360) + 360) % 360; applyFilters(); }
function toggleFlip(axis) {
  if (axis === "h") filtersState.flipH = !filtersState.flipH;
  else filtersState.flipV = !filtersState.flipV;
  applyFilters();
}
function setZoom(z) { filtersState.zoom = Math.max(1, Math.min(2, +z || 1)); applyFilters(); }
function setFit(id) { filtersState.fit = FIT_MODES.some(m => m.id === id) ? id : "contain"; applyFilters(); }
function resetFilters() {
  Object.assign(filtersState, {
    brightness: 1, contrast: 1, saturation: 1, rotate: 0,
    flipH: false, flipV: false, zoom: 1, fit: "contain",
  });
  applyFilters();
}
