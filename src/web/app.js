"use strict";

/* ===================== tiny helpers ===================== */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const enc = encodeURIComponent;

// The active viewer profile (opt-in). Sent on every request so the server scopes
// progress + My List to it; ignored server-side when profiles are disabled.
function currentProfile() {
  try { return localStorage.getItem("kadmu_profile") || "default"; } catch { return "default"; }
}
async function api(path, opts = {}) {
  opts.headers = { "X-Kadmu": "1", "X-Kadmu-Profile": currentProfile(), ...(opts.headers || {}) };
  const r = await fetch(path, opts);
  if (r.status === 401) {
    let e = {};
    try { e = await r.json(); } catch {}
    if (e.needAuth) { showLogin(); throw new Error("Authentication required"); }
  }
  if (!r.ok) {
    let e = {};
    try { e = await r.json(); } catch {}
    throw new Error(e.error || e.message || `HTTP ${r.status}`);
  }
  return r.json();
}

function fmtTime(s) {
  if (!s || isNaN(s)) s = 0;
  s = Math.floor(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}
function fmtSize(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(b < 10 && i > 0 ? 1 : 0) + " " + u[i];
}

let toastTimer;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3200);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function prettyName(name) { return name.replace(/\.[^.]+$/, ""); }
// Tidy display title the server derived from the filename (strips download slop);
// falls back to the raw filename without its extension.
const dispName = (v) => (v && v.display) || prettyName(v.name);
function parentDir(p) { return String(p).replace(/[\\/][^\\/]*$/, "") || p; }

/* ===================== inline SVG icon set (no emoji) ===================== */
const ICON = {
  play:  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.14v13.72a1 1 0 0 0 1.54.84l10.4-6.86a1 1 0 0 0 0-1.68L9.54 4.3A1 1 0 0 0 8 5.14Z" fill="currentColor"/></svg>`,
  pause: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="5" width="3.7" height="14" rx="1.2" fill="currentColor"/><rect x="13.8" y="5" width="3.7" height="14" rx="1.2" fill="currentColor"/></svg>`,
  prev:  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5.5v13a1 1 0 0 1-1.55.83L7.5 13.4v4.1a1 1 0 0 1-2 0v-11a1 1 0 0 1 2 0v4.1l8.95-5.93A1 1 0 0 1 18 5.5Z" fill="currentColor"/></svg>`,
  next:  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5.5v13a1 1 0 0 0 1.55.83L16.5 13.4v4.1a1 1 0 0 0 2 0v-11a1 1 0 0 0-2 0v4.1L7.55 4.67A1 1 0 0 0 6 5.5Z" fill="currentColor"/></svg>`,
  back10: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 4 6.5 8 11 12"/><path d="M6.5 8H13a5.5 5.5 0 1 1-5.4 6.6"/><text x="12.6" y="16" font-size="7" stroke="none" fill="currentColor" font-weight="700" text-anchor="middle">10</text></svg>`,
  fwd10:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 4 17.5 8 13 12"/><path d="M17.5 8H11a5.5 5.5 0 1 0 5.4 6.6"/><text x="11.4" y="16" font-size="7" stroke="none" fill="currentColor" font-weight="700" text-anchor="middle">10</text></svg>`,
  volHigh: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h3.6L13 19V5L7.6 9H4Z" fill="currentColor"/><path d="M16.2 8.6a4.8 4.8 0 0 1 0 6.8M18.8 6a8.3 8.3 0 0 1 0 12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
  volLow:  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h3.6L13 19V5L7.6 9H4Z" fill="currentColor"/><path d="M16.2 8.6a4.8 4.8 0 0 1 0 6.8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
  volMute: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h3.6L13 19V5L7.6 9H4Z" fill="currentColor"/><path d="M16.5 9.5l5 5M21.5 9.5l-5 5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
  loop:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 2.5 20.5 6 17 9.5"/><path d="M3.5 11V9a3 3 0 0 1 3-3h14"/><path d="M7 21.5 3.5 18 7 14.5"/><path d="M20.5 13v2a3 3 0 0 1-3 3h-14"/></svg>`,
  autoplay: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M10.2 8.4 15.5 12l-5.3 3.6Z" fill="currentColor" stroke="none"/></svg>`,
  pip:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><rect x="12" y="11" width="7" height="5.5" rx="1.2" fill="currentColor" stroke="none"/></svg>`,
  fullscreen: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9"/><path d="M20 9V5.5A1.5 1.5 0 0 0 18.5 4H15"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20H9"/><path d="M20 15v3.5A1.5 1.5 0 0 1 18.5 20H15"/></svg>`,
  fullscreenExit: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 4v3.5A1.5 1.5 0 0 1 7.5 9H4"/><path d="M15 4v3.5A1.5 1.5 0 0 0 16.5 9H20"/><path d="M9 20v-3.5A1.5 1.5 0 0 0 7.5 15H4"/><path d="M15 20v-3.5A1.5 1.5 0 0 1 16.5 15H20"/></svg>`,
  close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>`,
  list:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.6" cy="6" r="1.3" fill="currentColor" stroke="none"/><circle cx="3.6" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="3.6" cy="18" r="1.3" fill="currentColor" stroke="none"/></svg>`,
  chevronRight: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>`,
  folder: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5a2 2 0 0 1 2-2h3.7a2 2 0 0 1 1.5.7l1.1 1.3a2 2 0 0 0 1.5.7H19a2 2 0 0 1 2 2v7.1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>`,
  folderOpen: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8V6.5a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.5.7l1.1 1.3a2 2 0 0 0 1.5.7H19a2 2 0 0 1 2 2"/><path d="M3.2 9.5h17.3a1.4 1.4 0 0 1 1.36 1.77l-1.43 5.2A2 2 0 0 1 18.46 18H5.2a2 2 0 0 1-2-2Z"/></svg>`,
  film:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.2h18M3 14.8h18M8 4 6 9.2M13 4l-2 5.2M18 4l-2 5.2"/></svg>`,
  up:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V6M6 11l6-6 6 6"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.3 4.5L19 7"/></svg>`,
  rename: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7.5 18.5 3 20l1.5-4.5Z"/><path d="M14 6l4 4"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7M6.5 7l1 12.2a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4L18 7M10 11v6M14 11v6"/></svg>`,
  move: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5a2 2 0 0 1 2-2h3.7a2 2 0 0 1 1.5.7l1.1 1.3a2 2 0 0 0 1.5.7H19a2 2 0 0 1 2 2v7.1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M9 14h6M13 12l2 2-2 2"/></svg>`,
  folderPlus: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5a2 2 0 0 1 2-2h3.7a2 2 0 0 1 1.5.7l1.1 1.3a2 2 0 0 0 1.5.7H19a2 2 0 0 1 2 2v7.1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M12 11.5v4M10 13.5h4"/></svg>`,
  remove: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M8.3 12h7.4"/></svg>`,
  cog:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><path d="M12 2.6v2.3M12 19.1v2.3M21.4 12h-2.3M4.9 12H2.6M18.6 5.4 17 7M7 17l-1.6 1.6M18.6 18.6 17 17M7 7 5.4 5.4"/></svg>`,
  copy:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="1.4"/><path d="M5 15h-.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5"/></svg>`,
  devices: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="12.5" height="9" rx="1.4"/><path d="M5.5 17.5h6M8.5 14v3.5"/><rect x="16.5" y="9.5" width="5.2" height="10" rx="1.3"/><path d="M18.6 17.6h1"/></svg>`,
  info:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.8" r="1.1" fill="currentColor" stroke="none"/></svg>`,
  keyboard: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="6" width="19" height="12" rx="1.6"/><path d="M6 9.6h.01M9.5 9.6h.01M13 9.6h.01M16.5 9.6h.01M6 12.7h.01M9.5 12.7h.01M13 12.7h.01M16.5 12.7h.01M8 15.5h8"/></svg>`,
  globe: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.7 3.8 9S14.5 18.4 12 21c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3Z"/></svg>`,
  lock:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4.5" y="10.5" width="15" height="9.5" rx="1.4"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/></svg>`,
  plus:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-3.6-3.6"/></svg>`,
  cc:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.2"/><path d="M10.3 9.6a2.4 2.4 0 1 0 0 4.8M16.8 9.6a2.4 2.4 0 1 0 0 4.8" stroke-linecap="round"/></svg>`,
  audio: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h3.2L12 19V5L7.2 9H4Z" fill="currentColor" stroke="none"/><path d="M16 8.6a4.6 4.6 0 0 1 0 6.8"/><path d="M18.7 6a8 8 0 0 1 0 12"/></svg>`,
  sun:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.4M12 19.1v2.4M4.2 4.2l1.7 1.7M18.1 18.1l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.2 19.8l1.7-1.7M18.1 5.9l1.7-1.7"/></svg>`,
  moon:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13.5A8 8 0 0 1 10.5 4a7 7 0 1 0 9.5 9.5Z"/></svg>`,
  themeAuto: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18Z" fill="currentColor" stroke="none"/></svg>`,
  gridView: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1.2"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.2"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.2"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.2"/></svg>`,
  listView: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 6h12M8 12h12M8 18h12"/><rect x="3" y="4.6" width="2.6" height="2.6" rx=".5" fill="currentColor" stroke="none"/><rect x="3" y="10.6" width="2.6" height="2.6" rx=".5" fill="currentColor" stroke="none"/><rect x="3" y="16.6" width="2.6" height="2.6" rx=".5" fill="currentColor" stroke="none"/></svg>`,
  eye:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.6"/></svg>`,
  eyeOff: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4l16 16"/><path d="M9.6 5.8A9.4 9.4 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.5 3.2M6.5 7.6A15.6 15.6 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 3-.5"/><path d="M9.9 9.9a2.6 2.6 0 0 0 3.7 3.7"/></svg>`,
  audio: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h3.5L12.5 19V5L7.5 9H4Z" fill="currentColor" stroke="none"/><path d="M16 9.2a4 4 0 0 1 0 5.6M18.6 6.6a7.6 7.6 0 0 1 0 10.8"/></svg>`,
  chapters: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="4.3" rx="1.1"/><rect x="3" y="14.7" width="18" height="4.3" rx="1.1"/><path d="M9 5v4.3M15 14.7V19"/></svg>`,
  timer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.6 1.7M9.3 2.6h5.4M19 6l-1.6-1.6"/></svg>`,
};
function applyIcons(root = document) {
  $$("[data-icon]", root).forEach(n => { const k = n.dataset.icon; if (ICON[k]) n.innerHTML = ICON[k]; });
  $$("[data-icon-prefix]", root).forEach(n => {
    const k = n.dataset.iconPrefix;
    if (ICON[k] && !$(".ic-prefix", n)) n.insertAdjacentHTML("afterbegin", `<span class="ic-prefix">${ICON[k]}</span>`);
  });
}

/* ===================== state ===================== */
const state = {
  path: null,
  data: null,
  roots: [],              // [{name, path}] configured library roots — lets URLs read as folder names
  progress: {},
  session: { authRequired: false, authed: true, readonly: false, canManage: true, canBrowse: true, ffmpeg: false, lan: false, canToggleLan: false, urls: [] },
  organize: false,
  sort: "name",           // name | recent | date | size | duration  (library ordering)
  filter: "all",          // all | unwatched | watched | playable
  view: "grid",           // grid | list
  selection: new Map(),
  queue: [],
  qIndex: -1,
  autoNext: true,
  rate: 1,
  quality: "original",    // "original" | target height (240..2160)
  srcHeight: null,        // native height of the playing video (for the ladder)
  srcDuration: null,      // full duration of the source (a transcoded stream only knows its own)
  qOffset: 0,             // seconds into the source where the current transcoded stream began
  direct: true,           // original quality is a seekable file? false = a live remux/transcode stream
  audio: 0,               // selected audio-track ordinal (0 = file default)
  audios: [],             // [{ord,codec,lang,label,default}] audio tracks of the playing file
  panel: null,            // { path, data } currently shown in the side panel
  playerFolderPath: null, // folder the active queue was built from
  pendingNext: null,      // resolved "what plays next" (in-folder episode or next season)
  nextArmed: false,       // entered the end-of-clip window and surfaced the up-next card
  mylist: new Set(),      // paths pinned to My List (membership for card toggles)
  searchActive: false,    // true while showing search results instead of the library
  subs: [],               // subtitle tracks for the playing video (sidecar + embedded)
  ccLang: "off",          // remembered caption choice ("off" | lang | label)
  subOffset: 0,           // subtitle sync offset, seconds (+ = later); per-clip, reset on load
  ccSize: "md",           // subtitle size:  sm | md | lg | xl            (persisted)
  ccColor: "white",       // subtitle colour key (see CC_COLORS)          (persisted)
  ccBg: "soft",           // subtitle background box: none | soft | solid (persisted)
  autoStreak: 0,          // consecutive auto-advances (drives "Still watching?")
  audios: [],             // audio tracks for the playing video
  chapters: [],           // [{start, end, title}] chapter markers for the playing video
  storyboard: null,       // { ok, cols, rows, count, interval, duration, url } scrub-preview sprite
  storyboardFor: null,    // path the storyboard belongs to (guards async loads)
  sleep: { mode: "off", deadline: 0, episodes: 0, timer: null, tick: null }, // sleep timer
  profilesEnabled: false, // server has --profiles on
  keyHud: true,           // flash the pressed shortcut in the center of the screen
};

/* ===================== thumbnails (lazy) ===================== */
const thumbObserver = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const node = e.target;
    thumbObserver.unobserve(node);
    const p = node.dataset.vpath;
    const img = $("img", node);
    if (img && p) {
      img.src = `/api/thumb?path=${enc(p)}`;
      img.onload = () => { img.style.opacity = 1; $(".ph", node)?.remove(); };
    }
    if (node.dataset.needsMeta === "1") {
      api(`/api/meta?path=${enc(p)}`).then(m => {
        if (m && m.duration) {
          const badge = $(".dur", node);
          if (badge) badge.textContent = fmtTime(m.duration);
        }
      }).catch(() => {});
    }
  }
}, { rootMargin: "300px" });

/* ===================== client-side routing (hash URLs) =====================
   Each view gets its own link so browser Back/Forward moves between them, and the
   links read as folder names rather than an encoded absolute path:
     #/                                  library root
     #/browse/Videos/Breaking Bad        a library folder (names, relative to its root)
     #/watch/Videos/Breaking Bad/E01.mp4 the player, on a file
   The real absolute path is the source of truth — carried in history.state (which the
   browser keeps across Back/Forward *and* reload) — so the pretty trail is only ever
   re-resolved for a fresh deep link someone pasted. The fragment never reaches the
   server, so this is all client-side. loadLibrary / loadVideoElement are the single
   chokepoints that mirror the URL via syncURL(); popstate / hashchange replay it. */
let applyingRoute = false;     // true while we render *from* the URL — suppresses re-pushing
let navMode = "push";          // "push" (user nav, new entry) | "replace" (auto-advance, in place)
let lastNavHash = null;        // dedupe popstate + hashchange firing together

// The configured roots, longest path first, so the most specific one wins a prefix match.
function rootsBySpecificity() {
  return (state.roots || []).slice().sort((a, b) => b.path.length - a.path.length);
}
// Absolute path → readable trail of folder names, relative to its owning root
// (e.g. "/home/me/Videos/Breaking Bad" → ["Videos", "Breaking Bad"]). null if outside roots.
function prettyTrail(absPath) {
  for (const r of rootsBySpecificity()) {
    if (absPath === r.path) return [r.name];
    if (absPath.startsWith(r.path + "/")) {
      return [r.name, ...absPath.slice(r.path.length + 1).split("/").filter(Boolean)];
    }
  }
  return null;
}
// Readable trail → absolute path: the matching root's path + the remaining names.
// (Round-trips because each name is the real on-disk basename.) null if no root matches.
function resolvePretty(trail) {
  if (!trail || !trail.length) return null;
  const root = rootsBySpecificity().find(r => r.name === trail[0]);
  return root ? [root.path, ...trail.slice(1)].join("/") : null;
}
function hashFor(view, path) {
  if (view === "root" || !path) return "#/";
  const trail = prettyTrail(path);
  // Fall back to the explicit ?path= form if roots aren't known yet (still a valid link).
  if (!trail) return `#/${view}?path=${enc(path)}`;
  return `#/${view}/${trail.map(enc).join("/")}`;
}
function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  if (!h) return { view: "root", path: null, trail: [] };
  const q = h.indexOf("?");
  if (q >= 0) {                                   // legacy / fallback: browse?path=<abs>
    const seg = h.slice(0, q);
    const path = new URLSearchParams(h.slice(q + 1)).get("path");
    if (seg === "watch" || seg === "browse") return { view: seg, path: path || null, trail: null };
    return { view: "root", path: null, trail: [] };
  }
  const parts = h.split("/").filter(Boolean).map(decodeURIComponent);
  const view = parts.shift();
  if (view === "watch" || view === "browse") return { view, path: null, trail: parts };
  return { view: "root", path: null, trail: [] };
}
// The path for a parsed route: prefer history.state (exact), else the explicit ?path=,
// else resolve the readable trail back to an absolute path.
function pathForRoute(r) {
  const st = history.state;
  if (st && st.kadmu && st.path != null) return st.path;
  return r.path || resolvePretty(r.trail);
}
// Mirror the current view into the URL. No-op while replaying a route (the browser owns
// the URL then). Same view+path → replace; otherwise push a new entry. The absolute path
// rides along in history.state so Back/Forward/reload never need to re-resolve names.
function syncURL(view, path) {
  if (applyingRoute) return;
  const st = history.state;
  const curPath = (st && st.kadmu) ? st.path : null;
  const same = parseHash().view === view && (curPath || null) === (path || null);
  const next = { kadmu: true, view, path: path || null };
  if (same || navMode === "replace") history.replaceState(next, "", hashFor(view, path));
  else history.pushState(next, "", hashFor(view, path));
  navMode = "push";
  lastNavHash = location.hash;
}
// Deep-link / Back-Forward: find the full video object for a path so the player has metadata.
async function resolveVideo(path) {
  try {
    const data = await api(`/api/library?path=${enc(parentDir(path))}`);
    const v = (data.videos || []).find(x => x.path === path);
    if (v) return v;
  } catch {}
  return { path, name: baseName(path), playable: true };
}
// Render whatever the URL says, without touching history (that's the browser's job here).
// Serialized: if Back/Forward fire faster than a render completes, one loop drains them and
// renders the final destination (last wins), so overlapping renders can't corrupt history.
let routeRunning = false;
async function renderFromRoute() {
  if (routeRunning) return;          // a drain loop is active; it will pick up the latest hash
  routeRunning = true;
  try {
    while (location.hash !== lastNavHash) {
      lastNavHash = location.hash;
      const r = parseHash();
      const path = pathForRoute(r);
      applyingRoute = true;
      try {
        if (r.view === "watch" && path) {
          const open = !$("#playerOverlay").classList.contains("hidden");
          if (!open || !currentVideo || currentVideo.path !== path) {
            await openPlayer(await resolveVideo(path));
          }
        } else {
          if (!$("#playerOverlay").classList.contains("hidden")) teardownPlayer();
          await loadLibrary(r.view === "browse" ? path : null, { silent: true });
        }
      } finally {
        applyingRoute = false;
      }
    }
  } finally {
    routeRunning = false;
  }
}

/* ===================== library rendering ===================== */
async function loadLibrary(path, opts = {}) {
  state.path = path || null;
  try { state.progress = await api("/api/progress"); } catch { state.progress = {}; }

  let data;
  try {
    data = await api(`/api/library${path ? "?path=" + enc(path) : ""}`);
  } catch (e) {
    // a remembered/stale path that no longer exists -> fall back to the root view
    if (path) { if (!opts.silent) toast(e.message, "err"); return loadLibrary(null); }
    toast(e.message, "err"); return;
  }
  // remember where we are so the next launch reopens here
  try {
    if (path) localStorage.setItem("kadmu_last_path", path);
    else localStorage.removeItem("kadmu_last_path");
  } catch {}
  state.data = data;
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  { const si = $("#searchInput"); if (si) si.value = ""; $("#searchBox")?.classList.remove("has-text"); closeSearchDD(); }   // leaving search → clear the box & dropdown
  clearSelection();
  renderBreadcrumb(data);
  renderFolders(data);
  renderVideos(data);
  if (data.isRoot) { await renderContinue(); await renderMyList(); }
  else { $("#continueSection").classList.add("hidden"); $("#mylistSection")?.classList.add("hidden"); }
  renderEmpty(data);
  updateToolbar(data);
  window.scrollTo(0, 0);
  syncURL(state.path ? "browse" : "root", state.path);
}

/* ===================== search (live type-ahead dropdown + full results) =====================
   Typing pops a dropdown of matching shows & episodes (live, ranked by the backend).
   ↑/↓ moves the highlight, Enter opens the highlighted item — or, with nothing
   highlighted, the full results page. Esc closes the dropdown, then clears. The
   "See all results" footer and Enter-with-no-selection both fall through to
   runSearch(), which renders the classic full-page results into the library grid. */
const SEARCH_DD_FOLDERS = 6;   // shows/folders shown in the dropdown before "See all"
const SEARCH_DD_VIDEOS = 8;    // episodes/movies shown in the dropdown before "See all"
let searchTimer = null;
let searchSeq = 0;             // request counter; a stale (out-of-order) response is dropped
const sdd = { open: false, items: [], active: -1, q: "" };   // dropdown state

function searchTerms(q) {
  return (q || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
}
// Escape text for HTML, then wrap each matched query term in <mark> for the dropdown.
function highlightTerms(text, terms) {
  const safe = escapeHtml(text == null ? "" : text);
  if (!terms || !terms.length) return safe;
  const pat = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).filter(Boolean);
  if (!pat.length) return safe;
  try { return safe.replace(new RegExp("(" + pat.join("|") + ")", "gi"), "<mark>$1</mark>"); }
  catch { return safe; }
}
// "Show › Season" context line — the readable folder trail of a path's parent.
function ctxLabel(path) {
  const t = prettyTrail(parentDir(path));
  return t && t.length ? t.join(" › ") : "";
}

function onSearchInput(e) {
  const q = e.target.value;
  $("#searchBox")?.classList.toggle("has-text", !!q.trim());
  clearTimeout(searchTimer);
  if (!q.trim()) { closeSearchDD(); if (state.searchActive) exitSearch(); return; }
  searchTimer = setTimeout(() => suggest(q), 140);
}

// Fetch + render the live suggestion dropdown (debounced; stale responses ignored).
async function suggest(q) {
  q = (q || "").trim();
  if (!q) { closeSearchDD(); return; }
  const seq = ++searchSeq;
  let data;
  try { data = await api(`/api/search?q=${enc(q)}`); }
  catch { return; }                                  // a network blip leaves the dropdown as-is
  if (seq !== searchSeq) return;                     // a newer keystroke superseded this one
  if (($("#searchInput")?.value || "").trim() !== q) return;   // input changed/cleared meanwhile
  renderSearchDD(data, q);
}

function renderSearchDD(data, q) {
  const dd = $("#searchDropdown");
  if (!dd) return;
  const terms = searchTerms(q);
  const folders = data.folders || [];
  const videos = data.videos || [];
  const total = folders.length + videos.length;

  dd.innerHTML = "";
  sdd.items = [];
  sdd.active = -1;
  sdd.q = q;

  if (!total) {
    dd.appendChild(el("div", "sdd-empty", `No matches for <b>${escapeHtml(q)}</b>`));
    openSearchDD();
    return;
  }

  // register a row node: give it an index, wire hover/click, remember it for keyboard nav
  const register = (node, payload) => {
    const idx = sdd.items.length;
    node.classList.add("sdd-item");
    node.setAttribute("role", "option");
    node.dataset.idx = idx;
    node.addEventListener("mousemove", () => setActive(idx));
    node.addEventListener("click", () => activateItem(idx));
    sdd.items.push({ ...payload, node });
    dd.appendChild(node);
  };

  if (folders.length) {
    dd.appendChild(el("div", "sdd-head", "Shows &amp; folders"));
    for (const f of folders.slice(0, SEARCH_DD_FOLDERS)) {
      const ctx = ctxLabel(f.path);
      const bits = [];
      if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
      if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
      const sub = [ctx, bits.join(" · ")].filter(Boolean).join("  ·  ");
      const node = el("div", "",
        `<span class="sdd-ic">${ICON.folder}</span>
         <span class="sdd-text">
           <span class="sdd-name">${highlightTerms(f.name, terms)}</span>
           <span class="sdd-sub">${escapeHtml(sub)}</span>
         </span>
         ${f.watched ? `<span class="sdd-tag">${ICON.check}${f.watched}</span>` : ""}`);
      register(node, { kind: "folder", path: f.path });
    }
  }

  if (videos.length) {
    dd.appendChild(el("div", "sdd-head", "Episodes &amp; movies"));
    for (const v of videos.slice(0, SEARCH_DD_VIDEOS)) {
      const ctx = ctxLabel(v.path);
      const dur = v.duration ? fmtTime(v.duration) : "";
      const prog = state.progress[v.path];
      const frac = prog && prog.duration ? prog.position / prog.duration : 0;
      const watched = frac >= 0.95;
      const right = watched
        ? `<span class="sdd-tag ok" title="Watched">${ICON.check}</span>`
        : (dur ? `<span class="sdd-dur">${escapeHtml(dur)}</span>` : "");
      const node = el("div", "",
        `<span class="sdd-thumb"><span class="sdd-ph">${ICON.film}</span><img alt="" loading="lazy" style="opacity:0;transition:opacity .2s" /></span>
         <span class="sdd-text">
           <span class="sdd-name">${highlightTerms(dispName(v), terms)}</span>
           <span class="sdd-sub">${escapeHtml(ctx)}${!v.playable ? ` · ${escapeHtml((v.ext || "").replace(".", ""))}` : ""}</span>
         </span>
         ${right}`);
      const img = $("img", node);
      if (img) {
        img.src = `/api/thumb?path=${enc(v.path)}`;
        img.onload = () => { img.style.opacity = 1; $(".sdd-ph", node)?.remove(); };
      }
      register(node, { kind: "video", item: v });
    }
  }

  // footer: jump to the classic full-page results
  const foot = el("button", "sdd-all",
    `<span class="sdd-all-ic">${ICON.search}</span><span>See all ${total} result${total > 1 ? "s" : ""} for “${escapeHtml(q)}”</span>`);
  const fidx = sdd.items.length;
  foot.dataset.idx = fidx;
  foot.addEventListener("mousemove", () => setActive(fidx));
  foot.addEventListener("click", () => activateItem(fidx));
  sdd.items.push({ kind: "all", node: foot });
  dd.appendChild(foot);

  openSearchDD();
}

function openSearchDD() {
  const dd = $("#searchDropdown");
  if (!dd) return;
  dd.classList.remove("hidden");
  sdd.open = true;
}
function closeSearchDD() {
  const dd = $("#searchDropdown");
  if (dd) { dd.classList.add("hidden"); dd.innerHTML = ""; }
  sdd.open = false; sdd.items = []; sdd.active = -1;
}
function setActive(idx) {
  if (idx === sdd.active) return;
  sdd.items[sdd.active]?.node.classList.remove("active");
  sdd.active = idx;
  const it = sdd.items[idx];
  if (it) { it.node.classList.add("active"); it.node.scrollIntoView({ block: "nearest" }); }
}
function moveActive(delta) {
  if (!sdd.items.length) return;
  let i = sdd.active + delta;
  if (i < 0) i = sdd.items.length - 1;
  else if (i >= sdd.items.length) i = 0;
  setActive(i);
}
function activateItem(idx) {
  const it = sdd.items[idx];
  if (!it) return;
  const input = $("#searchInput");
  if (it.kind === "folder") { closeSearchDD(); input?.blur(); loadLibrary(it.path); }
  else if (it.kind === "video") {
    closeSearchDD(); input?.blur();
    if (!it.item.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(it.item);
  } else { closeSearchDD(); runSearch(sdd.q); }      // "See all results"
}

// Full results page — the dropdown's "See all" / Enter-with-no-selection target.
async function runSearch(q) {
  q = (q || "").trim();
  closeSearchDD();
  if (!q) { exitSearch(); return; }
  let data;
  try { data = await api(`/api/search?q=${enc(q)}`); } catch (e) { toast(e.message, "err"); return; }
  state.searchActive = true;
  document.body.classList.add("searching-mode");
  clearSelection();
  $("#continueSection").classList.add("hidden");
  $("#mylistSection")?.classList.add("hidden");
  $("#libToolbar")?.classList.add("hidden");   // sort/filter belong to browsing, not search

  const bc = $("#breadcrumb"); bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => {
    const i = $("#searchInput");
    if (i) { i.value = ""; $("#searchBox")?.classList.remove("has-text"); }
    exitSearch();
  };
  bc.appendChild(home);
  bc.appendChild(el("span", "sep", "›"));
  bc.appendChild(el("span", "crumb current", `Search: “${escapeHtml(q)}”`));

  renderFolders({ folders: data.folders, isRoot: false });
  renderVideos({ videos: data.videos });
  if (data.folders.length) $("#foldersTitle").textContent = "Shows & folders";
  if (data.videos.length) $("#videosTitle").textContent = `Episodes & movies · ${data.videos.length}`;

  const empty = $("#emptyState"); empty.innerHTML = "";
  if (!data.folders.length && !data.videos.length) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "No results"));
    empty.appendChild(el("p", "muted", `Nothing in your library matches “${q}”.`));
  } else empty.classList.add("hidden");
  window.scrollTo(0, 0);
}
function exitSearch() {
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  closeSearchDD();
  loadLibrary(state.path);
}

function renderBreadcrumb(data) {
  const bc = $("#breadcrumb");
  bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => loadLibrary(null);
  bc.appendChild(home);
  (data.breadcrumb || []).forEach((c, i, arr) => {
    bc.appendChild(el("span", "sep", "›"));
    const cr = el("span", "crumb" + (i === arr.length - 1 ? " current" : ""), escapeHtml(c.name));
    cr.onclick = () => loadLibrary(c.path);
    bc.appendChild(cr);
  });
}

// My List "+" / "✓" toggle button markup, reflecting current membership.
function myListBtn(path) {
  const on = state.mylist.has(path);
  return `<button class="mylist-btn${on ? " on" : ""}" data-mylist
            title="${on ? "Remove from My List" : "Add to My List"}">${on ? ICON.check : ICON.plus}</button>`;
}

async function toggleMyList(path, name, btn) {
  const on = !state.mylist.has(path);
  try {
    await api("/api/mylist", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, name, on }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  if (on) state.mylist.add(path); else state.mylist.delete(path);
  // reflect on every visible button for this path
  $$(`[data-mylist]`).forEach(b => {
    const card = b.closest("[data-path]");
    if (card && card.dataset.path === path) {
      b.classList.toggle("on", on); b.innerHTML = on ? ICON.check : ICON.plus;
      b.title = on ? "Remove from My List" : "Add to My List";
    }
  });
  if (btn) { btn.classList.toggle("on", on); btn.innerHTML = on ? ICON.check : ICON.plus; }
  toast(on ? "Added to My List" : "Removed from My List", "ok");
  if (state.path == null && !state.searchActive) renderMyList();   // refresh the home row
}

function folderCard(f) {
  const card = el("div", "folder-card");
  card.dataset.path = f.path;
  const bits = [];
  if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
  if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
  const watched = f.watched || 0;
  const wtag = watched
    ? `<span class="wtag" title="${watched} episode${watched > 1 ? "s" : ""} watched in here">${ICON.check}${watched} watched</span>`
    : "";
  const meta = bits.join(" · ") || (f.isFolder === false ? "" : "open");
  card.innerHTML =
    `<button class="check" data-check>${ICON.check}</button>
     <div class="folder-ic"><img class="cover" alt="" loading="lazy" />${ICON.folder}</div>
     <div class="folder-meta">
       <div class="folder-name">${escapeHtml(f.name)}</div>
       <div class="folder-sub">${meta}${watched && meta ? " · " : ""}${wtag}</div>
     </div>
     ${myListBtn(f.path)}`;
  // Lazy cover art: poster/folder/cover image, else the first episode's thumbnail.
  // On 404 / no art the <img> stays hidden and the folder glyph shows through.
  const cover = card.querySelector(".folder-ic .cover");
  if (cover) {
    cover.onload = () => { if (cover.naturalWidth) card.querySelector(".folder-ic").classList.add("has-cover"); };
    cover.onerror = () => { cover.removeAttribute("src"); };
    cover.src = `/api/cover?path=${enc(f.path)}`;
  }
  card.onclick = (ev) => {
    if (ev.target.closest("[data-mylist]")) { toggleMyList(f.path, f.name, ev.target.closest("[data-mylist]")); return; }
    if (ev.shiftKey || ev.target.closest("[data-check]")) { toggleSelect(card, f.path, f.name, true); return; }
    if (state.selection.size) clearSelection();   // a plain click clears any selection, then opens
    loadLibrary(f.path);
  };
  card.oncontextmenu = (ev) => openContextMenu(ev, { card, path: f.path, name: f.name, isFolder: true, item: f });
  if (state.selection.has(f.path)) card.classList.add("selected");
  return card;
}

function renderFolders(data) {
  const sec = $("#folderSection"), grid = $("#folderGrid");
  grid.innerHTML = "";
  const folders = sortItems(data.folders || []);
  if (!folders.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("#foldersTitle").textContent = data.isRoot ? "Library folders" : "Folders";
  for (const f of folders) grid.appendChild(folderCard(f));
}

/* ---- library sort / filter (client-side; the data already carries the fields) ---- */
const watchedFrac = (v) => { const p = state.progress[v.path]; return p && p.duration ? p.position / p.duration : 0; };
const isWatched = (v) => watchedFrac(v) >= 0.95;
function sortItems(items) {
  const arr = (items || []).slice();
  switch (state.sort) {
    case "recent":
    case "date":     arr.sort((a, b) => (b.mtime || 0) - (a.mtime || 0)); break;
    case "size":     arr.sort((a, b) => (b.size || 0) - (a.size || 0)); break;
    case "duration": arr.sort((a, b) => (b.duration || 0) - (a.duration || 0)); break;
    default: { const nm = (x) => x.display || x.name || "";   // videos: cleaned title · folders: raw name
               arr.sort((a, b) => nm(a).localeCompare(nm(b), undefined, { numeric: true, sensitivity: "base" })); }
  }
  return arr;
}
function filterVideos(vids) {
  switch (state.filter) {
    case "unwatched": return vids.filter(v => !isWatched(v));
    case "watched":   return vids.filter(v => isWatched(v));
    case "playable":  return vids.filter(v => v.playable);
    default:          return vids;
  }
}

// "My List" row on the home view (pinned shows / movies).
async function renderMyList() {
  const sec = $("#mylistSection"), grid = $("#mylistGrid");
  if (!sec) return;
  let items = [];
  try { items = await api("/api/mylist"); } catch {}
  state.mylist = new Set(items.map(i => i.path));
  if (!items.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  grid.innerHTML = "";
  for (const it of items) {
    grid.appendChild(it.isFolder
      ? folderCard({ name: it.name, path: it.path, videos: it.videos, subfolders: it.subfolders, watched: it.watched })
      : videoCard({ name: it.name, path: it.path, ext: it.ext, playable: it.playable, direct: it.direct, duration: it.duration }));
  }
}

function renderVideos(data) {
  const sec = $("#videoSection"), grid = $("#videoGrid");
  grid.innerHTML = "";
  const vids = data.videos || [];
  const sorted = sortItems(vids);
  state.queue = sorted.filter(v => v.playable);   // prev/next follows what you see
  if (!vids.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const nWatched = vids.filter(isWatched).length;
  $("#videosTitle").textContent = `Videos · ${vids.length}` + (nWatched ? ` · ${nWatched} watched` : "");
  const shown = filterVideos(sorted);
  if (!shown.length) {
    grid.appendChild(el("div", "muted small", "No videos match this filter."));
    return;
  }
  for (const v of shown) grid.appendChild(videoCard(v));
}

function videoCard(v, opts = {}) {
  const card = el("div", "video-card");
  card.dataset.vpath = v.path;
  card.dataset.path = v.path;
  const prog = state.progress[v.path];
  const frac = prog && prog.duration ? prog.position / prog.duration : 0;
  const watched = frac >= 0.95;                  // finished — show a Watched mark
  const pct = frac > 0 ? Math.min(100, frac * 100) : 0;  // orange line: how far in, every started episode
  if (watched) card.classList.add("watched");
  const durTxt = v.duration ? fmtTime(v.duration)
    : (opts.position != null ? fmtTime(opts.position) + " in" : "");
  card.innerHTML =
    `<button class="check" data-check>✓</button>
     ${opts.continueCard ? `<button class="card-dismiss" data-dismiss title="Remove from Continue watching" aria-label="Remove from Continue watching">${ICON.close}</button>` : ""}
     ${myListBtn(v.path)}
     <div class="thumb">
       <div class="ph">${ICON.film}</div>
       <img alt="" style="opacity:0;transition:opacity .2s" />
       ${!v.playable ? `<span class="badge" title="May not play natively in the browser">${escapeHtml((v.ext || "").replace(".", ""))}</span>` : ""}
       ${watched ? `<span class="watched-badge" title="You've finished watching this">${ICON.check}<span>Watched</span></span>` : ""}
       <span class="dur">${escapeHtml(durTxt)}</span>
       <div class="play-ic"><span>${ICON.play}</span></div>
       ${pct > 0 ? `<div class="resume"><i style="width:${pct}%"></i></div>` : ""}
     </div>
     <div class="vcard-foot">
       <div class="vcard-name">${escapeHtml(dispName(v))}</div>
       <div class="vcard-sub">${escapeHtml(fmtSize(v.size))}</div>
     </div>`;
  if (!v.duration) card.dataset.needsMeta = "1";
  card.onclick = (ev) => {
    if (ev.target.closest("[data-dismiss]")) { dismissContinue(v.path); return; }
    if (ev.target.closest("[data-mylist]")) { toggleMyList(v.path, v.name, ev.target.closest("[data-mylist]")); return; }
    if (ev.shiftKey || ev.target.closest("[data-check]")) { toggleSelect(card, v.path, v.name, false); return; }
    if (state.selection.size) clearSelection();   // a plain click clears any selection, then plays
    if (!v.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(v);
  };
  card.oncontextmenu = (ev) => openContextMenu(ev, { card, path: v.path, name: v.name, isFolder: false, item: v });
  if (state.selection.has(v.path)) card.classList.add("selected");
  thumbObserver.observe(card);
  return card;
}

async function renderContinue() {
  const sec = $("#continueSection"), grid = $("#continueGrid");
  let items = [];
  try { items = await api("/api/continue"); } catch {}
  if (!items.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  grid.innerHTML = "";
  for (const v of items) {
    state.progress[v.path] = { position: v.position, duration: v.duration };
    grid.appendChild(videoCard(v, { position: v.position, continueCard: true }));
  }
}

/* ---- mark watched / unwatched + dismiss a Continue-watching card (#10) ---- */
// "Watched" is otherwise derived from ≥95% progress; these let you set it by hand.
async function markWatched(path, dur) {
  const d = dur || (state.progress[path] && state.progress[path].duration) || 0;
  if (!d) { toast("Can't mark watched until its length is known.", "err"); return; }
  state.progress[path] = { position: d, duration: d };
  try {
    await api("/api/progress", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, position: d, duration: d }) });
    toast("Marked as watched", "ok");
  } catch { toast("Couldn't save that.", "err"); }
  refreshLibrary();
}
async function clearProgressFor(path) {
  delete state.progress[path];
  try {
    await api("/api/progress/clear", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }) });
  } catch { toast("Couldn't save that.", "err"); return false; }
  return true;
}
async function markUnwatched(path) {
  if (await clearProgressFor(path)) toast("Marked as unwatched", "ok");
  refreshLibrary();
}
async function dismissContinue(path) {
  if (await clearProgressFor(path)) { await renderContinue(); }
}
// Re-render the current library view in place (after a progress change).
function refreshLibrary() {
  if (state.searchActive || !state.data) return;
  renderFolders(state.data);
  renderVideos(state.data);
  if (state.data.isRoot) renderContinue();
}

function renderEmpty(data) {
  const empty = $("#emptyState");
  empty.innerHTML = "";
  const nothing = !(data.folders || []).length && !(data.videos || []).length;
  if (data.isRoot && !(data.folders || []).length) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "No library folders yet"));
    empty.appendChild(el("p", "muted", state.session.canManage
      ? "Add a folder that holds your shows and movies to get started."
      : "This instance has no shared folders."));
    if (state.session.canManage) {
      const btn = el("button", "btn primary", `${ICON.folderOpen}<span>Add a folder</span>`);
      btn.onclick = addFolder;
      empty.appendChild(btn);
    }
  } else if (nothing) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "Nothing here"));
    empty.appendChild(el("p", "muted", "This folder has no videos or subfolders."));
  } else {
    empty.classList.add("hidden");
  }
}

/* ===================== multi-select (Shift+click) ===================== */
// Shift+click (or a card's checkbox) selects items; right-click acts on the whole
// selection via the context menu. No mode toggle — selecting starts the moment you
// Shift+click something and ends when you plain-click, press Esc, or clear it.
function toggleSelect(card, path, name, isFolder) {
  if (!state.session.canManage) return;          // read-only can't select/manage
  if (state.selection.has(path)) { state.selection.delete(path); card.classList.remove("selected"); }
  else { state.selection.set(path, { name, isFolder }); card.classList.add("selected"); }
  updateSelectionUI();
}
function clearSelection() {
  state.selection.clear();
  $$(".video-card.selected, .folder-card.selected").forEach(c => c.classList.remove("selected"));
  updateSelectionUI();
}
// Replace the whole selection with a single item (standard right-click behavior).
function selectOnly(card, path, name, isFolder) {
  state.selection.clear();
  $$(".video-card.selected, .folder-card.selected").forEach(c => c.classList.remove("selected"));
  state.selection.set(path, { name, isFolder });
  if (card) card.classList.add("selected");
  updateSelectionUI();
}
function updateSelectionUI() {
  // Checkboxes + selected styling show whenever at least one item is selected.
  document.body.classList.toggle("selecting", state.selection.size > 0);
}

/* ===================== right-click context menu ===================== */
function closeContextMenu() { $("#ctxMenu")?.classList.add("hidden"); }

function openContextMenu(ev, target) {
  ev.preventDefault();
  ev.stopPropagation();
  closeContextMenu();
  const canManage = state.session.canManage;
  const isRoot = !!(state.data && state.data.isRoot);

  // figure out what the actions operate on
  let multi = false;
  if (target) {
    if (state.selection.has(target.path) && state.selection.size > 1) multi = true;   // act on the whole selection
    else selectOnly(target.card, target.path, target.name, target.isFolder);
  }
  const n = state.selection.size;

  const items = [];
  if (target && !multi) {
    if (target.isFolder) items.push({ icon: "folderOpen", label: "Open", fn: () => loadLibrary(target.path) });
    else items.push({ icon: "play", label: "Play", fn: () => openPlayer(target.item) });
  }
  // Mark watched / unwatched — personal state, allowed even in read-only.
  if (target && !multi && !target.isFolder) {
    const w = isWatched(target.item);
    items.push({ icon: w ? "eyeOff" : "eye", label: w ? "Mark as unwatched" : "Mark as watched",
      fn: () => w ? markUnwatched(target.path) : markWatched(target.path, target.item && target.item.duration) });
  }
  if (canManage) {
    if (isRoot) {
      if (target) {
        if (items.length) items.push({ sep: true });
        items.push({ icon: "remove", danger: true, fn: doRemoveRoots,
          label: n > 1 ? `Remove ${n} from library` : "Remove from library" });
      }
    } else {
      if (target) {
        if (items.length) items.push({ sep: true });
        if (n === 1) items.push({ icon: "rename", label: "Rename", fn: doRename });
        items.push({ icon: "move", label: n > 1 ? `Move ${n}…` : "Move…", fn: doMove });
        items.push({ icon: "trash", danger: true, fn: doDelete, label: n > 1 ? `Delete ${n}` : "Delete" });
      }
      items.push({ sep: true });
      items.push({ icon: "folderPlus", label: "New folder", fn: doNewFolder });
    }
  }
  // drop a leading/trailing separator if it has nothing useful around it
  while (items.length && items[0].sep) items.shift();
  while (items.length && items[items.length - 1].sep) items.pop();
  if (!items.length) return;

  const menu = $("#ctxMenu");
  menu.innerHTML = "";
  for (const it of items) {
    if (it.sep) { menu.appendChild(el("div", "ctx-sep")); continue; }
    const b = el("button", it.danger ? "danger" : "", `${ICON[it.icon] || ""}<span>${escapeHtml(it.label)}</span>`);
    b.onclick = () => { closeContextMenu(); it.fn(); };
    menu.appendChild(b);
  }
  menu.style.left = ev.clientX + "px";
  menu.style.top = ev.clientY + "px";
  menu.classList.remove("hidden");
  // keep it on-screen
  const r = menu.getBoundingClientRect();
  if (r.right > window.innerWidth - 8) menu.style.left = Math.max(8, window.innerWidth - r.width - 8) + "px";
  if (r.bottom > window.innerHeight - 8) menu.style.top = Math.max(8, window.innerHeight - r.height - 8) + "px";
}

async function runOp(payload) {
  return api("/api/op", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function openRenameDialog(path, name) {
  openDialog("Rename", `<label>New name</label><input type="text" id="dlgInput" value="${escapeHtml(name)}" />`,
    async () => {
      const nn = $("#dlgInput").value.trim();
      if (!nn) return false;
      const r = await runOp({ action: "rename", path, name: nn });
      if (r.ok) { toast("Renamed", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => { const i = $("#dlgInput"); if (i) { i.focus(); i.setSelectionRange(0, prettyName(name).length); } }, 50);
}
function doRename() {
  const [path, info] = [...state.selection.entries()][0];
  openRenameDialog(path, info.name);
}

function openDeleteDialog(items) {
  const names = items.slice(0, 6).map(i => i.name).join(", ") + (items.length > 6 ? `, +${items.length - 6} more` : "");
  openDialog("Delete to trash",
    `<p>Move <b>${items.length}</b> item(s) to the library's <code>.kadmu-trash</code> folder?</p>
     <p class="muted small">${escapeHtml(names)}</p>
     <p class="muted small">Nothing is permanently erased — you can restore from the trash folder on disk.</p>`,
    async () => {
      let ok = 0, fail = 0;
      for (const it of items) {
        const r = await runOp({ action: "delete", path: it.path });
        r.ok ? ok++ : fail++;
      }
      toast(`Moved ${ok} to trash${fail ? `, ${fail} failed` : ""}`, fail ? "err" : "ok");
      loadLibrary(state.path); return true;
    });
}
function doDelete() {
  openDeleteDialog([...state.selection.entries()].map(([path, info]) => ({ path, name: info.name })));
}

function openNewFolderDialog(parentPath) {
  if (!parentPath) { toast("Open a library folder first, then create folders inside it.", "err"); return; }
  openDialog("New folder", `<label>Folder name</label><input type="text" id="dlgInput" placeholder="Season 1" />`,
    async () => {
      const name = $("#dlgInput").value.trim();
      if (!name) return false;
      const r = await runOp({ action: "mkdir", path: parentPath, name });
      if (r.ok) { toast("Folder created", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => $("#dlgInput")?.focus(), 50);
}
function doNewFolder() { openNewFolderDialog(state.path); }

function openMoveDialog(paths) {
  let pickerPath = state.path;
  openDialog("Move to…", `<div id="pickerWrap"></div>`, async () => {
    if (!pickerPath) { toast("Pick a destination folder.", "err"); return false; }
    let ok = 0, fail = 0;
    for (const path of paths) {
      if (path === pickerPath) { fail++; continue; }
      const r = await runOp({ action: "move", path, dest: pickerPath });
      r.ok ? ok++ : fail++;
    }
    toast(`Moved ${ok}${fail ? `, ${fail} failed` : ""}`, fail ? "err" : "ok");
    loadLibrary(state.path); return true;
  });

  async function drawPicker(p) {
    pickerPath = p;
    const wrap = $("#pickerWrap");
    let data;
    try { data = await api(`/api/library${p ? "?path=" + enc(p) : ""}`); }
    catch (e) { wrap.innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`; return; }
    const picker = el("div", "picker");
    if (!data.isRoot) {
      const parent = data.breadcrumb.length > 1 ? data.breadcrumb[data.breadcrumb.length - 2].path : null;
      const up = el("div", "p-row up", `${ICON.up}<span>Up one level</span>`);
      up.onclick = () => drawPicker(parent);
      picker.appendChild(up);
    }
    for (const f of data.folders) {
      const row = el("div", "p-row", `${ICON.folder}<span>${escapeHtml(f.name)}</span>`);
      row.onclick = () => drawPicker(f.path);
      picker.appendChild(row);
    }
    if (data.isRoot && !data.folders.length) picker.appendChild(el("div", "p-row up", "No library folders"));
    wrap.innerHTML = "";
    wrap.appendChild(picker);
    wrap.appendChild(el("div", "picker-cur", data.isRoot
      ? "Pick a folder to move into…" : `Destination: <b>${escapeHtml(data.path)}</b>`));
    $("#dialogOk").disabled = data.isRoot;
  }
  drawPicker(pickerPath);
}
function doMove() { openMoveDialog([...state.selection.keys()]); }

/* ===================== remove library roots ===================== */
async function doRemoveRoots() {
  const paths = [...state.selection.keys()];
  if (!paths.length) return;
  try {
    const cfg = await api("/api/config");
    const next = (cfg.roots || []).filter(r => !paths.includes(r));
    await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
    await refreshSession();
    toast(`Removed ${paths.length} folder${paths.length > 1 ? "s" : ""} from library`, "ok");
    state.selection.clear();
    loadLibrary(null);
  } catch (e) { toast(e.message, "err"); }
}

/* ===================== add a folder (native OS chooser, with fallback) ===================== */
async function addFolder() {
  if (state.session.nativePicker) {
    try {
      const r = await api("/api/pick-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (r.cancelled) return;
      if (!r.ok) { toast(r.error || "Could not open the folder chooser.", "err"); return; }
      await addRootPath(r.path);
    } catch (e) { toast(e.message, "err"); }
  } else {
    openFolderPicker();   // fallback in-browser picker (e.g. when accessed remotely)
  }
}
async function addRootPath(path) {
  const cfg = await api("/api/config");
  const next = [...new Set([...(cfg.roots || []), path])];
  await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
  await refreshSession();
  await renderRoots();
  toast("Folder added", "ok");
  loadLibrary(null);
}

/* ===================== drag-and-drop folders ===================== */
async function addPaths(paths) {
  try {
    const r = await api("/api/add-paths", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths }) });
    if (r.added && r.added.length) {
      toast(`Added ${r.added.length} folder${r.added.length > 1 ? "s" : ""} to your library`, "ok");
      await refreshSession();
      loadLibrary(null);
    } else {
      toast("Couldn't read a folder from that drop. Drag a folder from your file manager.", "err");
    }
  } catch (e) { toast(e.message, "err"); }
}
function wireDragDrop() {
  const hint = $("#dropHint");
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || [])
    .some(t => t === "Files" || t === "text/uri-list");
  window.addEventListener("dragenter", (e) => {
    if (!state.session.canManage || !hasFiles(e)) return;
    depth++; hint.classList.remove("hidden");
  });
  window.addEventListener("dragover", (e) => {
    if (state.session.canManage && hasFiles(e)) e.preventDefault();
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    depth--; if (depth <= 0) { depth = 0; hint.classList.add("hidden"); }
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();                 // stop Firefox from opening the dropped file
    depth = 0; hint.classList.add("hidden");
    if (!state.session.canManage) return;
    const dt = e.dataTransfer;
    const raw = (dt.getData("text/uri-list") || dt.getData("text/plain") || "");
    const paths = raw.split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith("#"));
    if (!paths.length) { toast("Couldn't read a folder path from that drop.", "err"); return; }
    addPaths(paths);
  });
}

/* ===================== generic dialog ===================== */
let dialogOkHandler = null;
function openDialog(title, bodyHtml, onOk) {
  $("#dialogTitle").textContent = title;
  $("#dialogBody").innerHTML = bodyHtml;
  $("#dialogOk").disabled = false;
  $("#dialogOk").textContent = "OK";
  dialogOkHandler = onOk;
  $("#dialog").classList.remove("hidden");
  const input = $("#dlgInput");
  if (input) input.addEventListener("keydown", e => { if (e.key === "Enter") $("#dialogOk").click(); });
}
function closeDialog() { $("#dialog").classList.add("hidden"); dialogOkHandler = null; }

/* ===================== folder picker (first-run / add folder) ===================== */
async function openFolderPicker() {
  if (!state.session.canBrowse) { toast("Folder browsing is disabled on this instance.", "err"); return; }
  let cur = null;
  openDialog("Choose a library folder", `<div id="fpWrap" class="fp-wrap"></div>`, async () => {
    if (!cur) return false;
    try {
      const cfg = await api("/api/config");
      const next = [...new Set([...(cfg.roots || []), cur])];
      await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
      toast("Folder added", "ok");
      await refreshSession();
      await renderRoots();
      loadLibrary(null);
      return true;
    } catch (e) { toast(e.message, "err"); return false; }
  });
  $("#dialogOk").textContent = "Add this folder";

  async function draw(p) {
    let data;
    try { data = await api(`/api/browse${p ? "?path=" + enc(p) : ""}`); }
    catch (e) { $("#fpWrap").innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`; return; }
    cur = data.path;
    const wrap = $("#fpWrap");
    wrap.innerHTML = "";

    if (data.shortcuts?.length) {
      const sc = el("div", "fp-shortcuts");
      data.shortcuts.forEach(s => {
        const b = el("button", "chip", escapeHtml(s.name));
        b.onclick = () => draw(s.path);
        sc.appendChild(b);
      });
      wrap.appendChild(sc);
    }
    const picker = el("div", "picker");
    if (data.parent) {
      const up = el("div", "p-row up", `${ICON.up}<span>Up</span>`);
      up.onclick = () => draw(data.parent);
      picker.appendChild(up);
    }
    for (const d of data.dirs) {
      const row = el("div", "p-row",
        `${ICON.folder}<span>${escapeHtml(d.name)}${d.videos ? ` <span class="muted small">· ${d.videos} videos</span>` : ""}</span>`);
      row.onclick = () => draw(d.path);
      picker.appendChild(row);
    }
    if (!data.dirs.length) picker.appendChild(el("div", "p-row up", "(no subfolders here)"));
    wrap.appendChild(picker);
    wrap.appendChild(el("div", "picker-cur", `Add: <b>${escapeHtml(data.path)}</b>`));
  }
  draw(null);
}

/* ===================== settings ===================== */
async function openSettings() {
  $("#settingsModal").classList.remove("hidden");
  renderKeybinds($("#settingsKbd"));   // same list as the "?" overlay (one source of truth)
  { const t = $("#keyHudToggle"); if (t) t.checked = state.keyHud; }
  await refreshSession();   // re-check live server caps (LAN toggle, ffmpeg, …) without a page reload
  renderStatus();
  renderLan();
  renderUrls();
  await renderRoots();
}
function closeSettings() { $("#settingsModal").classList.add("hidden"); }

function renderUrls() {
  const list = $("#urlList");
  list.innerHTML = "";
  const urls = state.session.urls || [];
  // one link only: the network address for other devices (fall back to localhost)
  const shareUrl = urls.find(u => !u.includes("127.0.0.1")) || urls[0];
  const onNetwork = !!shareUrl && !shareUrl.includes("127.0.0.1");
  if (!onNetwork) {
    list.appendChild(el("p", "muted small lan-note", state.session.canToggleLan
      ? `Just this computer for now. Turn on <b>Share on your network</b> above to get a link for your phone or TV.`
      : `Localhost only. Restart Kadmu with <code>--lan</code> to watch from your phone or TV on the same Wi-Fi.`));
  } else {
    const card = el("div", "url-qr");
    let svg = "";
    try { if (typeof KadmuQR !== "undefined") svg = KadmuQR.svg(shareUrl); } catch { svg = ""; }
    if (svg) { const fig = el("div", "qr-img"); fig.innerHTML = svg; card.appendChild(fig); }
    const meta = el("div", "qr-meta");
    meta.appendChild(el("span", "qr-hint", "Point your phone camera here"));
    const a = el("a", "url-link", escapeHtml(shareUrl));
    a.href = shareUrl; a.target = "_blank"; a.rel = "noopener";
    meta.appendChild(a);
    const copy = el("button", "btn qr-copy", "Copy link");
    copy.type = "button";
    copy.onclick = (e) => { e.preventDefault(); copyText(shareUrl); };
    meta.appendChild(copy);
    card.appendChild(meta);
    list.appendChild(card);
  }
  renderPasswordControl(list);   // set / change / remove the access password, right here
  applyIcons(list);
}

async function renderRoots() {
  let cfg;
  try { cfg = await api("/api/config"); } catch { cfg = { roots: [] }; }
  const list = $("#rootList");
  list.innerHTML = "";
  const roots = cfg.roots || [];
  const countEl = $("#rootCount");
  if (countEl) countEl.textContent = roots.length ? `${roots.length} folder${roots.length === 1 ? "" : "s"}` : "";
  if (!roots.length) {
    list.innerHTML = `<div class="root-empty muted small">No folders yet — add one below to start watching.</div>`;
    return;
  }
  for (const r of roots) {
    const name = r.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || r;
    const row = el("div", "root-row");
    row.innerHTML =
      `<span class="root-ic" data-icon="folder"></span>` +
      `<span class="root-meta"><span class="root-name">${escapeHtml(name)}</span>` +
      `<span class="root-path">${escapeHtml(r)}</span></span>`;
    if (state.session.canManage) {
      const rm = el("button", "rm");
      rm.dataset.icon = "close";
      rm.title = "Remove from library";
      rm.onclick = async () => {
        const next = roots.filter(x => x !== r);
        await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
        await refreshSession();
        await renderRoots();
        loadLibrary(null);
      };
      row.appendChild(rm);
    }
    list.appendChild(row);
  }
  applyIcons(list);
}

async function addRoot() {
  const input = $("#rootInput");
  const p = input.value.trim();
  if (!p) return;
  try {
    const cfg = await api("/api/config");
    const next = [...new Set([...cfg.roots, p])];
    const res = await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
    if ((res.roots || []).some(r => r === p || r.endsWith(p.replace(/[\/\\]+$/, "").split(/[\/\\]/).pop()))) {
      $("#settingsStatus").textContent = ""; input.value = "";
    } else {
      $("#settingsStatus").textContent = `Could not add "${p}" — is it a valid folder path on the server?`;
    }
    await renderRoots();
    loadLibrary(null);
  } catch (e) { $("#settingsStatus").textContent = e.message; }
}

/* ----- settings: server status tiles ----- */
function statTile(icon, label, value, tone) {
  const dot = tone ? `<i class="stat-dot tone-${tone}"></i>` : "";
  return `<div class="stat-tile">` +
    `<span class="stat-ic" data-icon="${icon}"></span>` +
    `<span class="stat-text"><span class="stat-label">${label}</span>` +
    `<span class="stat-value">${dot}${value}</span></span></div>`;
}

function renderStatus() {
  const s = state.session;
  const ver = escapeHtml(s.version || "1.0.0");
  const verEl = $("#settingsVersion");
  if (verEl) verEl.textContent = ver;
  const lan = !!s.lan;
  const tiles = [
    statTile("info", "Version", `Kadmu ${ver}`, ""),
    statTile("film", "Media engine", s.ffmpeg ? "ffmpeg ready" : "ffmpeg not found", s.ffmpeg ? "ok" : "off"),
    s.readonly
      ? statTile("lock", "Library", "Read-only", "warn")
      : statTile("rename", "Library", "Read &amp; write", "ok"),
    statTile("globe", "Network", lan ? "Shared on your network" : "This computer only", lan ? "warn" : "ok"),
    statTile("lock", "Password", s.authRequired ? "Protected" : "Off", s.authRequired ? "ok" : "off"),
  ];
  const grid = $("#statGrid");
  if (grid) { grid.innerHTML = tiles.join(""); applyIcons(grid); }
}

function copyText(t) {
  const ok = () => toast("Link copied", "ok");
  const fail = () => toast("Couldn\'t copy — select the link and copy it manually.", "err");
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(ok, fail);
    } else { fail(); }
  } catch { fail(); }
}

/* ----- settings: network sharing (LAN) toggle ----- */
function renderLan() {
  const box = $("#lanControl");
  if (!box) return;
  box.innerHTML = "";
  const s = state.session;
  if (!s.canToggleLan) return;   // explicit --host bind, or no management rights
  const on = !!s.lan;
  const row = el("div", "lan-row");
  row.innerHTML =
    `<span class="lan-ic" data-icon="globe"></span>` +
    `<span class="lan-text"><span class="lan-title">Share on your network</span>` +
    `<span class="lan-desc">${on
      ? "On — anyone on your Wi-Fi can open the links below."
      : "Off — only this computer can watch right now."}</span></span>`;
  const sw = el("button", "switch" + (on ? " on" : ""));
  sw.type = "button";
  sw.setAttribute("role", "switch");
  sw.setAttribute("aria-checked", on ? "true" : "false");
  sw.title = on ? "Turn network sharing off" : "Turn network sharing on";
  sw.innerHTML = `<span class="knob"></span>`;
  sw.onclick = () => toggleLan(!on);
  row.appendChild(sw);
  box.appendChild(row);
  if (on && !s.authRequired) {
    box.appendChild(el("p", "lan-warn small",
      `Heads up: no password is set, so anyone on your network can also rename, move and delete files. Set one below to lock that down.`));
  }
  applyIcons(box);
}

async function toggleLan(on) {
  const box = $("#lanControl");
  try {
    const r = await api("/api/lan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    });
    if (r && r.ok === false) { toast(r.error || "Could not change network sharing.", "err"); return; }
    await refreshSession();
    renderStatus(); renderLan(); renderUrls();
    toast(on ? "Network sharing is on" : "Network sharing is off", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ----- settings: access password (set / change / remove inline) ----- */
function renderPasswordControl(host) {
  if (!state.session.canSetPassword) return;
  const on = !!state.session.authRequired;
  const box = el("div", "net-auth");
  box.innerHTML =
    `<div class="net-auth-head">
       <span class="net-auth-ic" data-icon="lock"></span>
       <span class="net-auth-text">
         <span class="net-auth-title">Password</span>
         <span class="net-auth-desc">${on
           ? "On — anyone opening a link must enter it."
           : "Off — anyone with a link can watch &amp; manage."}</span>
       </span>
       <span class="net-auth-pill${on ? " on" : ""}">${on ? "Protected" : "Open"}</span>
     </div>
     <div class="net-auth-form">
       <input type="password" id="netPwInput" autocomplete="new-password"
              placeholder="${on ? "New password" : "Set a password"}" />
       <button class="btn primary" id="netPwSet">${on ? "Update" : "Set"}</button>
       ${on ? `<button class="btn ghost" id="netPwClear">Remove</button>` : ""}
     </div>`;
  host.appendChild(box);
  $("#netPwSet").onclick = () => setNetworkPassword($("#netPwInput").value);
  const clr = $("#netPwClear");
  if (clr) clr.onclick = () => setNetworkPassword("");
  $("#netPwInput").addEventListener("keydown", e => { if (e.key === "Enter") setNetworkPassword(e.target.value); });
}

async function setNetworkPassword(pw) {
  pw = pw || "";
  try {
    const r = await api("/api/password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    if (r && r.ok === false) { toast(r.error || "Could not update the password.", "err"); return; }
    await refreshSession();
    renderStatus(); renderLan(); renderUrls();
    toast(pw ? "Password set" : "Password removed", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ===================== login ===================== */
function showLogin() { $("#loginOverlay").classList.remove("hidden"); setTimeout(() => $("#loginPassword")?.focus(), 50); }
function hideLogin() { $("#loginOverlay").classList.add("hidden"); }

/* ===================== player ===================== */
const video = $("#video");
let saveTimer = null, idleTimer = null, currentVideo = null, unloading = false;

/* ---------- unified loading / preparing indicator (every file type) ----------
   Native files load instantly; non-native ones (.mkv, .avi, …) are remuxed on the
   first request, which can take a few seconds. One spinner driven by the standard
   media events makes both behave identically instead of showing a blank stage.
   Self-injects so it works regardless of the surrounding player markup. */
let spinnerDelay = null;
function ensureSpinner() {
  let s = $("#playerSpinner");
  if (!s) {
    const stage = $("#playerStage");
    if (!stage) return null;
    s = el("div", "player-spinner hidden");
    s.id = "playerSpinner";
    s.setAttribute("aria-live", "polite");
    s.innerHTML = `<span class="spinner-ring" aria-hidden="true"></span><span class="spinner-label" id="spinnerLabel">Loading…</span>`;
    stage.appendChild(s);
  }
  return s;
}
function showSpinner(label, delay = 300) {
  const s = ensureSpinner();
  if (!s) return;
  if (label) { const l = $("#spinnerLabel"); if (l) l.textContent = label; }
  clearTimeout(spinnerDelay);
  spinnerDelay = setTimeout(() => s.classList.remove("hidden"), delay);  // brief delay so instant loads don't flash
}
function hideSpinner() {
  clearTimeout(spinnerDelay);
  $("#playerSpinner")?.classList.add("hidden");
}

// Swap the <video> source to a new clip and start playing (shared by every
// entry point: library, queue prev/next, side-panel, next-up card).
function loadVideoElement(v) {
  currentVideo = v;
  advancing = false;
  hideNextCard();
  syncURL("watch", v.path);        // each file gets its own link; navMode set by the caller
  resetQuality(v);                 // native quality + audio tracks + chapter markers
  setupSubs(v);                    // discover & attach sidecar + embedded captions
  resetStoryboard(v);              // drop the previous clip's scrub-preview sprite
  $("#playerTitle").textContent = dispName(v);
  document.title = dispName(v) + " · Kadmu";
  state.qOffset = 0;
  state.direct = true;             // assume seekable; confirmed once metadata loads
  video.src = `/api/stream?path=${enc(v.path)}${audioQuery()}`;   // audio reset to 0 by resetQuality
  video.load();

  const resume = state.progress[v.path];
  const resumePos = (resume && resume.position > 5 && resume.duration &&
                     resume.position < resume.duration * 0.97) ? resume.position : 0;
  video.onloadedmetadata = () => {
    // A native file arrives as a seekable byte-range download (finite duration); a
    // non-native one is piped live as a fragmented MP4 (no finite duration). Detect
    // which so seeking and resume use the right mechanism.
    state.direct = isFinite(video.duration) && video.duration > 0;
    if (resumePos > 0 && !state.direct) {
      startStreamAt(resumePos);    // live stream isn't seekable -> restart the encode at the offset...
      startPlayback();             // ...the initial play() above ran against a now-stale src
      return;
    }
    if (resumePos > 0) { try { video.currentTime = resumePos; } catch {} }
    video.playbackRate = state.rate;
    renderChapterTicks();          // ticks need the now-known duration
    updateTime();
  };
  // Fire play() synchronously so the click that opened the player still counts as the
  // user gesture browsers require for autoplay (the metadata callback is too late).
  startPlayback();
}

// Start playback; if the browser blocks autoplay, surface the center play button.
function startPlayback() {
  video.play().then(() => maybeCoachPip())
    .catch(() => { if (video.paused) $("#playerOverlay").classList.add("paused"); });
}

async function openPlayer(v) {
  state.autoStreak = 0;            // a fresh, user-initiated session
  const ov = $("#playerOverlay");
  ov.classList.remove("hidden", "idle", "nextup", "paused");
  // restore the user's last panel preference
  let collapsed = false;
  try { collapsed = localStorage.getItem("kadmu_panel_collapsed") === "1"; } catch {}
  if (window.matchMedia && window.matchMedia("(max-width: 920px)").matches) collapsed = true;
  setPanelCollapsed(collapsed);

  loadVideoElement(v);
  showUi();
  await loadPlayerFolder(parentDir(v.path), v.path);
}

// Build the queue + side panel from the folder that contains `currentPath`.
async function loadPlayerFolder(folder, currentPath) {
  let data = null;
  try { data = await api(`/api/library?path=${enc(folder)}`); } catch {}
  if (data && data.videos) {
    state.queue = data.videos.filter(x => x.playable);
    state.qIndex = state.queue.findIndex(x => x.path === currentPath);
    state.playerFolderPath = data.path || folder;
    state.panel = { path: state.playerFolderPath, data };
  } else {
    state.queue = currentVideo ? [currentVideo] : [];
    state.qIndex = 0;
    state.playerFolderPath = folder;
    state.panel = { path: folder, data: { folders: [], videos: state.queue, breadcrumb: [], isRoot: false } };
  }
  renderPanel();
}

// Tear the player down without navigating (used when Back/Forward leaves the watch URL).
function teardownPlayer() {
  saveProgress(true);
  hideNextCard();
  clearSleepTimers();                     // stop any running sleep countdown
  state.sleep.mode = "off"; state.sleep.deadline = 0;
  updateSleepButton();
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("#playerOverlay").classList.add("hidden");
  $("#playerOverlay").classList.remove("paused", "nextup");
  document.title = "Kadmu";
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
// The ✕ / Escape: leave the player for its folder. The folder gets its own entry, so Back
// reopens the file you were on — regardless of how many episodes you flipped through.
function closePlayer() {
  teardownPlayer();
  loadLibrary(state.playerFolderPath || state.path);
}

function playIndex(i) {
  if (i < 0 || i >= state.queue.length) return;
  state.autoStreak = 0;            // a manual jump — reset the "still watching?" streak
  saveProgress(true);
  loadVideoElement(state.queue[i]);
  state.qIndex = i;
  renderPanel();
  showUi();
}

/* ---------- side panel: browse seasons / episodes without leaving ---------- */
function setPanelCollapsed(collapsed) {
  $("#playerOverlay").classList.toggle("panel-collapsed", collapsed);
  // the toggle button stays visible in both states; CSS fills it orange when the
  // episodes list is open (overlay not collapsed) and leaves it plain when closed.
  $("#queueOpen").classList.remove("hidden");
  try { localStorage.setItem("kadmu_panel_collapsed", collapsed ? "1" : "0"); } catch {}
}
// The #queueOpen handle flips the episodes/seasons panel open or shut.
function togglePanel() {
  setPanelCollapsed(!$("#playerOverlay").classList.contains("panel-collapsed"));
}

async function panelBrowse(path) {
  let data;
  try { data = await api(`/api/library${path ? "?path=" + enc(path) : ""}`); }
  catch (e) { toast(e.message, "err"); return; }
  state.panel = { path: path || null, data };
  renderPanel();
}

function playFromPanel(v, data) {
  if (!v.playable) { toast("This file may not play in the browser. Try MP4/WebM.", "err"); }
  state.autoStreak = 0;            // manual pick from the side panel
  saveProgress(true);
  state.queue = (data.videos || []).filter(x => x.playable);
  state.qIndex = state.queue.findIndex(x => x.path === v.path);
  if (state.qIndex < 0) { state.queue = [v]; state.qIndex = 0; }
  state.playerFolderPath = data.path || parentDir(v.path);
  loadVideoElement(v);
  renderPanel();
  showUi();
}

function renderPanel() {
  const panel = state.panel || {};
  const data = panel.data || { folders: [], videos: [], breadcrumb: [] };
  const onCurrentFolder = (data.path || null) === (state.playerFolderPath || null);

  // title
  const last = (data.breadcrumb && data.breadcrumb.length) ? data.breadcrumb[data.breadcrumb.length - 1].name : null;
  $("#queueTitle").textContent = data.isRoot ? "Library" : (last || "Up next");

  // breadcrumb nav
  const nav = $("#queueNav");
  nav.innerHTML = "";
  const home = el("button", "q-crumb", "Library");
  home.onclick = () => panelBrowse(null);
  nav.appendChild(home);
  (data.breadcrumb || []).forEach((c, i, arr) => {
    nav.appendChild(el("span", "q-sep", "›"));
    const cr = el("button", "q-crumb" + (i === arr.length - 1 ? " current" : ""), escapeHtml(c.name));
    cr.onclick = () => panelBrowse(c.path);
    nav.appendChild(cr);
  });

  // folders (other seasons / shows)
  const fwrap = $("#queueFolders");
  fwrap.innerHTML = "";
  for (const f of (data.folders || [])) {
    const bits = [];
    if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
    if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
    const row = el("button", "q-folder",
      `<span class="q-folder-ic">${ICON.folder}</span>
       <span class="q-folder-meta"><span class="q-folder-name">${escapeHtml(f.name)}</span>
       <span class="q-folder-sub">${bits.join(" · ") || "empty"}</span></span>
       <span class="q-folder-go">${ICON.chevronRight}</span>`);
    row.onclick = () => panelBrowse(f.path);
    fwrap.appendChild(row);
  }
  fwrap.classList.toggle("hidden", !(data.folders || []).length);

  // episodes
  const list = $("#queueList");
  list.innerHTML = "";
  const vids = data.videos || [];
  if (!vids.length && !(data.folders || []).length) {
    list.appendChild(el("div", "q-empty", "Nothing to play in this folder."));
  }
  vids.forEach((v, i) => {
    const isCurrent = onCurrentFolder && currentVideo && v.path === currentVideo.path;
    const item = el("div", "q-item" + (isCurrent ? " current" : "") + (v.playable ? "" : " disabled"));
    const prog = state.progress[v.path];
    const pct = prog && prog.duration ? Math.min(100, (prog.position / prog.duration) * 100) : 0;
    item.innerHTML =
      `<div class="q-thumb"><img src="/api/thumb?path=${enc(v.path)}" alt="" loading="lazy" />
         <span class="q-num">${i + 1}</span>
         ${isCurrent ? `<span class="q-now">${ICON.play}</span>` : ""}
         ${pct > 0 ? `<span class="q-prog"><i style="width:${pct}%"></i></span>` : ""}</div>
       <div class="q-name">${escapeHtml(dispName(v))}</div>`;
    item.onclick = () => playFromPanel(v, data);
    list.appendChild(item);
  });
  $(".q-item.current")?.scrollIntoView({ block: "nearest" });
}

/* ---------- "what plays next" — in-folder episode, then next season ---------- */
// Folder/season name detection so end-of-season can roll into the next season.
// Matches "Season 4", "S04", "Saison 2", "Series 3", "Vol 1", a bare "4", etc.
const SEASON_RE = /(?:^|[^a-z0-9])(?:season|saison|staffel|stagione|temporada|sezon|seizoen|series|serie|book|chapter|volume|vol|part|cour|s)\s*\.?\s*\d+/i;
function baseName(p) { return String(p || "").split(/[\\/]/).filter(Boolean).pop() || ""; }
function looksLikeSeason(name) {
  const n = String(name || "").trim();
  return /^\d+$/.test(n) || SEASON_RE.test(n);
}

// Resolve what should play after the current clip:
//   • the next episode in this folder, or
//   • the first episode of the next season (sibling folder) when this one ends.
async function resolveNext() {
  if (state.qIndex >= 0 && state.qIndex + 1 < state.queue.length) {
    return { video: state.queue[state.qIndex + 1], inFolder: true };
  }
  return findNextSeason();
}

// Look one level up, find the folder we're playing from among its siblings, and
// return the first playable episode of the next season-like sibling that has any.
// Guarded so it only crosses out of a season-like folder (never show → show).
async function findNextSeason() {
  const folder = state.playerFolderPath;
  if (!folder || !looksLikeSeason(baseName(folder))) return null;
  const parent = parentDir(folder);
  if (!parent || parent === folder) return null;

  let pdata;
  try { pdata = await api(`/api/library?path=${enc(parent)}`); } catch { return null; }
  const sibs = pdata.folders || [];
  const idx = sibs.findIndex(f => f.path === folder);
  if (idx < 0) return null;

  for (let j = idx + 1; j < sibs.length; j++) {
    const f = sibs[j];
    if (!f.videos || !looksLikeSeason(f.name)) continue;   // next season that actually has episodes
    let sdata;
    try { sdata = await api(`/api/library?path=${enc(f.path)}`); } catch { continue; }
    const eps = (sdata.videos || []).filter(v => v.playable);
    if (!eps.length) continue;
    return { video: eps[0], inFolder: false, folderPath: sdata.path || f.path, data: sdata, season: f.name };
  }
  return null;
}

// Switch to a resolved "next", swapping the queue/panel when it's another season.
function playResolved(nxt) {
  if (!nxt || !nxt.video) return false;
  saveProgress(true);
  if (!nxt.inFolder && nxt.data) {
    state.queue = (nxt.data.videos || []).filter(v => v.playable);
    state.playerFolderPath = nxt.folderPath;
    state.panel = { path: nxt.folderPath, data: nxt.data };
  }
  let i = state.queue.findIndex(v => v.path === nxt.video.path);
  if (i < 0) { state.queue = [nxt.video]; i = 0; }
  state.qIndex = i;
  loadVideoElement(nxt.video);
  renderPanel();
  showUi();
  return true;
}

// Manual "next" (button / Shift+N): advance, crossing into the next season at the end.
async function goNext() {
  state.autoStreak = 0;
  const nxt = await resolveNext();
  if (nxt) playResolved(nxt);
}

/* ---------- Netflix-style next-up countdown + "Still watching?" ---------- */
const STILL_WATCHING_AFTER = 3;       // ask after this many unattended auto-advances
const NEXT_LEAD  = 8;                 // surface the up-next card this many seconds before the end
const NEXT_GUARD = 0.6;               // …and roll into the next episode this far before the *true*
                                      // end. Swapping the source before "ended" ever fires is what
                                      // keeps Firefox Picture-in-Picture alive across episodes —
                                      // Firefox tears its PiP window down the moment a clip ends.
let advancing = false;                // guards the hand-off against firing twice

function nextAsks() { return state.autoNext && state.autoStreak >= STILL_WATCHING_AFTER; }

function hideNextCard() {
  state.pendingNext = null;
  state.nextArmed = false;
  $("#nextCard").classList.remove("ask");
  $("#nextCard").classList.add("hidden");
  $("#playerOverlay").classList.remove("nextup");
}

// Runs on every timeupdate. As the clip nears its end we resolve what's next and show the
// card; the countdown tracks real playback (so pause / seek / speed all behave); then we
// hand off to the next episode a hair early so PiP carries over instead of closing.
function tickAutoNext() {
  if (video.loop || !currentVideo || !state.autoNext) return;
  // Sleep timer set to stop at this episode/video: let it end naturally, no up-next.
  if (state.sleep.mode === "ep" || state.sleep.mode === "end") { if (state.nextArmed) hideNextCard(); return; }
  const total = totalDuration();
  if (!total || !isFinite(total)) return;
  const remaining = total - currentPlayPos();

  // Seeked back out of the end window — retract so we can re-arm later.
  if (remaining > NEXT_LEAD + 1) { if (state.nextArmed) hideNextCard(); return; }

  // First moment inside the window: arm. "Still watching?" deliberately holds its prompt
  // for the real end, so we don't surface a card early in that case.
  if (!state.nextArmed && remaining <= NEXT_LEAD) {
    state.nextArmed = true;
    if (!nextAsks()) showNextCard("count");
    return;
  }

  // Live countdown + the hand-off itself.
  if (state.pendingNext && !nextAsks()) {
    if (remaining <= NEXT_GUARD) { autoAdvance(); return; }
    const nxt = state.pendingNext;
    const left = Math.max(1, Math.ceil(remaining - NEXT_GUARD));
    const seasonTag = !nxt.inFolder && nxt.season ? `${nxt.season} · ` : "";
    $("#nextSub").textContent = `${seasonTag}starting in ${left}s`;
    $("#nextBarFill").style.width =
      `${Math.max(0, Math.min(100, ((remaining - NEXT_GUARD) / (NEXT_LEAD - NEXT_GUARD)) * 100))}%`;
  }
}

// Unattended roll-over — this is what accrues toward "still watching?". Update the URL in
// place (replace, not push) so a long binge doesn't bury earlier pages under Back.
function autoAdvance() { if (advancing) return; advancing = true; navMode = "replace"; state.autoStreak++; playNext(); }
function playNext() {
  const n = state.pendingNext;
  hideNextCard();                                 // clears pendingNext; n is already captured
  if (n) playResolved(n);
  else playIndex(state.qIndex + 1);               // fallback (shouldn't happen)
}
// user clicked Play-now / Continue — fresh attention, reset the streak
function confirmNext() { state.autoStreak = 0; playNext(); }

// Render the up-next card. mode "count" = live pre-end countdown (autoplay rolling over);
// mode "end" = terminal card once the clip has fully ended (autoplay off / "still watching?").
async function showNextCard(mode) {
  const forVideo = currentVideo;
  const nxt = await resolveNext();
  // user moved on / closed the player while we were resolving
  if (currentVideo !== forVideo || $("#playerOverlay").classList.contains("hidden")) return;
  if (!nxt || !nxt.video) { state.pendingNext = null; return; }  // nothing after this — let it end
  state.pendingNext = nxt;
  const nv = nxt.video;
  const crossing = !nxt.inFolder;
  const seasonTag = crossing && nxt.season ? `${nxt.season} · ` : "";
  const ask = mode === "end" && nextAsks();       // only the terminal card pauses to check in
  $("#nextThumb").src = `/api/thumb?path=${enc(nv.path)}`;
  $("#nextTitle").textContent = dispName(nv);
  const lbl = $("#nextCard .next-label");
  if (lbl) lbl.textContent = ask ? "Still watching?" : (crossing ? "Next season" : "Up next");
  const playBtn = $("#nextPlayBtn");
  if (playBtn && playBtn.lastChild) playBtn.lastChild.textContent = ask ? " I’m still here" : " Play now";
  $("#nextCard").classList.toggle("ask", ask);
  $("#nextCard").classList.remove("hidden");
  $("#playerOverlay").classList.add("nextup");

  const fill = $("#nextBarFill");
  if (mode === "count") {
    fill.style.transition = "width .25s linear";  // tickAutoNext drains the width from here
    fill.style.width = "100%";
    $("#nextSub").textContent = `${seasonTag}starting…`;
  } else if (ask) {
    fill.style.transition = "none"; fill.style.width = "0%";
    $("#nextSub").textContent = "Autoplay paused — still there?";
  } else {
    fill.style.transition = "none"; fill.style.width = "0%";
    $("#nextSub").textContent = crossing ? `${seasonTag}autoplay is off` : "Autoplay is off";
  }
}

function saveProgress() {
  if (!currentVideo) return;
  const _dur = totalDuration();
  if (!_dur || !isFinite(_dur)) return;   // live stream before its true duration is known
  const body = JSON.stringify({ path: currentVideo.path, position: currentPlayPos(), duration: _dur });
  // sendBeacon can't set the X-Kadmu header, so only use it during real page
  // unload (best effort); every in-app save goes through fetch with the header.
  if (unloading && navigator.sendBeacon) {
    navigator.sendBeacon("/api/progress", new Blob([body], { type: "application/json" }));
  } else {
    fetch("/api/progress", { method: "POST", headers: { "Content-Type": "application/json", "X-Kadmu": "1", "X-Kadmu-Profile": currentProfile() }, body, keepalive: true }).catch(() => {});
  }
}

function togglePlay() { video.paused ? video.play() : video.pause(); }

// Paint the filled portion of a range input orange (works in Firefox + WebKit).
function paintRange(input) {
  const min = +input.min || 0, max = +input.max || 100, val = +input.value;
  const pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
  input.style.setProperty("--p", pct.toFixed(2) + "%");
}
// The source position currently shown = where the transcoded stream began + how
// far into that stream we are. For original quality qOffset is 0 (1:1 mapping).
function currentPlayPos() { return (state.qOffset || 0) + (video.currentTime || 0); }
function totalDuration() { return state.srcDuration || video.duration || 0; }
// Begin a live stream at `pos` seconds into the source. At original quality that's
// the on-the-fly remux/transcode (/api/stream); otherwise the downscaled ladder
// (/api/transcode). Either way it's a fragmented MP4 that isn't byte-seekable, so we
// relaunch from a new offset to seek instead of setting currentTime.
// `&audio=N` rides on every stream URL when a non-default track is picked (track 0
// is the file default and needs no param). Picking a non-default track forces a live
// remux even for an otherwise-seekable native file — see canSeekNow().
function audioQuery() { return (state.audio || 0) ? `&audio=${state.audio}` : ""; }
// The current source is a seekable byte-range file only at original quality, on a
// native file, playing its default audio track. Anything else is a live stream.
function canSeekNow() { return state.quality === "original" && state.direct && (state.audio || 0) === 0; }

function startStreamAt(pos) {
  state.qOffset = Math.max(0, pos || 0);
  const t = state.qOffset.toFixed(2);
  video.src = state.quality === "original"
    ? `/api/stream?path=${enc(currentVideo.path)}&t=${t}${audioQuery()}`
    : `/api/transcode?path=${enc(currentVideo.path)}&height=${state.quality}&t=${t}${audioQuery()}`;
  video.load();
  video.onloadedmetadata = () => { video.playbackRate = state.rate; applyCaption(pickCaptionIndex()); updateTime(); };
}
// Seek to an absolute source position. A seekable file just sets currentTime; a live
// stream (downscaled, swapped audio, or a non-native file) relaunches the encode.
function seekTo(abs) {
  const total = totalDuration();
  abs = Math.max(0, abs);
  if (total) abs = Math.min(abs, total - 0.4);
  if (canSeekNow()) {
    video.currentTime = abs;
  } else {
    const wasPlaying = !video.paused && !video.ended;
    startStreamAt(abs);
    if (wasPlaying) video.play().catch(() => {});
  }
  showUi();
}
function updateTime() {
  const total = totalDuration();
  const cur = total ? Math.min(currentPlayPos(), total) : currentPlayPos();
  $("#timeCur").textContent = fmtTime(cur);
  $("#timeDur").textContent = fmtTime(total);
  const s = $("#seek");
  if (total) s.value = Math.round((cur / total) * 1000);
  paintRange(s);
  if ((state.chapters || []).length) highlightChapter();
}
function setSpeed(rate) {
  state.rate = rate;
  video.playbackRate = rate;
  $("#speedBtn").textContent = rate + "×";
  $$("#speedMenu button").forEach(b => b.classList.toggle("active", +b.dataset.rate === rate));
  $("#speedMenu").classList.add("hidden");
}

/* ---------- quality / resolution picker ---------- */
const QUALITY_HEIGHTS = [240, 360, 480, 720, 1080, 2160];
const qLabel = (h) => (h >= 2160 ? "4K" : h + "p");
let qualitySeq = 0;   // guards against stale /api/meta responses

// Called whenever a new clip loads: reset to native quality, then (async) learn
// the source resolution so we can offer only the lower rungs of the ladder.
async function resetQuality(v) {
  state.quality = "original";
  state.srcHeight = null;
  state.srcDuration = (v && v.duration) ? v.duration : null;
  state.qOffset = 0;
  state.audio = 0;
  state.audios = [];
  state.chapters = [];
  buildQualityMenu();
  buildAudioMenu();
  renderChapters();
  // The encoder capability comes from the session; if it hasn't loaded yet (or a
  // boot fetch missed it) refresh once so the picker still appears — matters for
  // files that always transcode, e.g. HEVC inside .m4v / .mp4.
  if (!state.session.ffmpeg) { try { await refreshSession(); } catch {} }
  if (!state.session.ffmpeg) return;                              // genuinely no encoder
  if (!currentVideo || currentVideo.path !== v.path) return;     // user moved on
  const seq = ++qualitySeq;
  api(`/api/meta?path=${enc(v.path)}`).then(m => {
    if (seq !== qualitySeq || !currentVideo || currentVideo.path !== v.path) return;  // path-based: survives queue re-fetch
    state.srcHeight = (m && m.height) ? m.height : null;
    if (m && m.duration) state.srcDuration = m.duration;
    state.audios = (m && m.audios) || [];
    state.chapters = (m && m.chapters) || [];   // chapter markers -> ticks + jump menu
    buildQualityMenu();
    buildAudioMenu();
    renderChapters();
  }).catch(() => {});
}

// Tier badge for a height: UHD / FHD / HD / SD (purely cosmetic labelling).
const qTier = (h) => h >= 2160 ? { t: "UHD", c: "uhd" }
  : h >= 1080 ? { t: "FHD", c: "hd" }
  : h >= 720 ? { t: "HD", c: "hd" }
  : { t: "SD", c: "" };
const qCheckIcon = () => (typeof ICON !== "undefined" && ICON.check) ? ICON.check : "✓";

function buildQualityMenu() {
  const wrap = $("#qualityWrap"), menu = $("#qualityMenu");
  if (!wrap || !menu) return;
  const lower = state.srcHeight ? QUALITY_HEIGHTS.filter(h => h < state.srcHeight) : [];
  const show = state.session.ffmpeg && state.srcHeight && lower.length > 0;
  wrap.classList.toggle("hidden", !show);
  if (!show) return;
  menu.classList.add("q-menu");
  menu.innerHTML = "";
  menu.appendChild(el("div", "q-head", "Quality"));

  const row = (q, label, sub, badge) => {
    const b = el("button", "q-item" + (state.quality === q ? " active" : ""));
    const main = el("div", "q-main");
    main.appendChild(el("span", "q-label", escapeHtml(label)));
    if (sub) main.appendChild(el("span", "q-sub", escapeHtml(sub)));
    b.appendChild(main);
    if (badge) b.appendChild(el("span", "q-badge" + (badge.c ? " " + badge.c : ""), badge.t));
    b.appendChild(el("span", "q-check", qCheckIcon()));
    b.onclick = () => setQuality(q);
    menu.appendChild(b);
  };

  row("original", "Original", `${qLabel(state.srcHeight)} · best quality`, qTier(state.srcHeight));
  lower.slice().reverse().forEach(h => row(h, qLabel(h), h <= 360 ? "Data saver" : "", qTier(h)));
  updateQualityButton();
}

function updateQualityButton() {
  const b = $("#qualityBtn");
  if (!b) return;
  const changed = state.quality !== "original";
  b.textContent = changed ? qLabel(state.quality)
    : (state.srcHeight ? qLabel(state.srcHeight) : "Auto");
  b.classList.toggle("changed", changed);
  b.title = changed ? `Quality · ${qLabel(state.quality)}` : "Video quality";
}

// Swap to the chosen quality, keeping the current position and play state.
function setQuality(q) {
  $("#qualityMenu").classList.add("hidden");
  if (q === state.quality || !currentVideo) return;
  const pos = currentPlayPos();
  const playing = !video.paused && !video.ended;
  state.quality = q;
  buildQualityMenu();
  if (canSeekNow()) {
    // Native file, default audio: the seekable original maps currentTime 1:1.
    state.qOffset = 0;
    video.src = `/api/stream?path=${enc(currentVideo.path)}${audioQuery()}`;
    video.load();
    video.onloadedmetadata = () => {
      try { if (pos > 0) video.currentTime = pos; } catch {}
      video.playbackRate = state.rate;
      applyCaption(pickCaptionIndex());   // tracks survive the source swap; re-show the chosen one
      updateTime();
    };
  } else {
    startStreamAt(pos);                   // live stream (downscale, swapped audio, or non-native) -> ~1-2s
  }
  if (playing) video.play().catch(() => {});
}

/* ---------- audio-track picker ---------- */
const audioTrackLabel = (a, i) =>
  a.label || (a.lang && a.lang !== "und" ? a.lang.toUpperCase() : "") ||
  (a.codec ? a.codec.toUpperCase() : "") || `Track ${i + 1}`;

function buildAudioMenu() {
  const wrap = $("#audioWrap"), menu = $("#audioMenu");
  if (!wrap || !menu) return;
  const tracks = state.audios || [];
  wrap.classList.toggle("hidden", tracks.length < 2);   // only offer it when there's a choice
  if (tracks.length < 2) { updateAudioButton(); return; }
  menu.classList.add("q-menu");
  menu.innerHTML = "";
  menu.appendChild(el("div", "q-head", "Audio"));
  tracks.forEach((a, i) => {
    const ord = (a.ord != null) ? a.ord : i;
    const b = el("button", "q-item" + ((state.audio || 0) === ord ? " active" : ""));
    b.dataset.audio = String(ord);
    const sub = [a.lang && a.lang !== "und" ? a.lang.toUpperCase() : "",
                 a.codec ? a.codec.toUpperCase() : ""].filter(Boolean).join(" · ");
    b.innerHTML = `<div class="q-main"><span class="q-label">${escapeHtml(audioTrackLabel(a, i))}</span>` +
                  (sub ? `<span class="q-sub">${escapeHtml(sub)}</span>` : "") + `</div>` +
                  `<span class="q-check">${qCheckIcon()}</span>`;
    b.onclick = () => setAudio(ord);
    menu.appendChild(b);
  });
  updateAudioButton();
}
function updateAudioButton() {
  $("#audioBtn")?.classList.toggle("on", (state.audio || 0) !== 0);
}
// Switch the active audio track, keeping position + play state. Swapping to a
// non-default track forces a live remux (the server re-muxes to make it the active
// stream), so seeking becomes restart-based — canSeekNow() handles that transparently.
function setAudio(ord) {
  $("#audioMenu")?.classList.add("hidden");
  ord = ord || 0;
  if (ord === (state.audio || 0) || !currentVideo) return;
  const pos = currentPlayPos();
  const playing = !video.paused && !video.ended;
  state.audio = ord;
  buildAudioMenu();
  if (canSeekNow()) {
    state.qOffset = 0;
    video.src = `/api/stream?path=${enc(currentVideo.path)}${audioQuery()}`;
    video.load();
    video.onloadedmetadata = () => {
      try { if (pos > 0) video.currentTime = pos; } catch {}
      video.playbackRate = state.rate;
      applyCaption(pickCaptionIndex());
      updateTime();
    };
  } else {
    startStreamAt(pos);
  }
  if (playing) video.play().catch(() => {});
}

/* ---------- subtitles / closed captions (sidecar + embedded) ---------- */
// Subtitle look (persisted globally) and sync offset (per-clip). The look is applied
// to the native <track> rendering via a generated `#video::cue` rule; sync works by
// shifting cue times. Only WebVTT cues reach the browser (the server converts srt/ass
// and embedded text tracks to VTT), so these overrides always apply cleanly.
const CC_SIZES  = { sm: "2.6vh", md: "3.4vh", lg: "4.4vh", xl: "5.8vh" };
const CC_COLORS = { white: "#ffffff", yellow: "#f5e642", cyan: "#76e0ff", green: "#5ef58a" };
const CC_BGS    = { none: "transparent", soft: "rgba(0,0,0,.55)", solid: "rgba(0,0,0,.92)" };

function applyCueStyle() {
  let st = document.getElementById("kadmuCueStyle");
  if (!st) { st = document.createElement("style"); st.id = "kadmuCueStyle"; document.head.appendChild(st); }
  const size = CC_SIZES[state.ccSize] || CC_SIZES.md;
  const color = CC_COLORS[state.ccColor] || CC_COLORS.white;
  const bg = CC_BGS[state.ccBg] || CC_BGS.soft;
  const shadow = state.ccBg === "none" ? "text-shadow:0 1px 2px #000,0 0 6px rgba(0,0,0,.95);" : "";
  st.textContent = `#video::cue{font-size:${size};line-height:1.3;color:${color};` +
                   `background-color:${bg};${shadow}}`;
}
// Persist the global look (size/colour/box); the sync offset is deliberately per-clip.
function persistCc() {
  try {
    localStorage.setItem("kadmu_cc_size", state.ccSize);
    localStorage.setItem("kadmu_cc_color", state.ccColor);
    localStorage.setItem("kadmu_cc_bg", state.ccBg);
  } catch {}
}
// Shift every loaded cue by the current offset. Each cue's original times are stashed
// once (_o0/_o1) so repeated nudges stay absolute and never drift.
function applyCueOffset() {
  const off = state.subOffset || 0;
  const tracks = video.textTracks;
  for (let i = 0; i < tracks.length; i++) {
    const cues = tracks[i].cues;
    if (!cues) continue;
    for (let j = 0; j < cues.length; j++) {
      const c = cues[j];
      if (c._o0 == null) { c._o0 = c.startTime; c._o1 = c.endTime; }
      c.startTime = Math.max(0, c._o0 + off);
      c.endTime = Math.max(0, c._o1 + off);
    }
  }
}
const fmtOffset = (s) => ((s = +(s || 0)) > 0 ? "+" : "") + s.toFixed(1) + "s";
function setSubOffset(delta, absolute) {
  const next = absolute != null ? +absolute : (state.subOffset || 0) + delta;
  state.subOffset = Math.max(-30, Math.min(30, +next.toFixed(2)));
  applyCueOffset();
  const sv = document.getElementById("ccSyncVal");
  if (sv) sv.textContent = fmtOffset(state.subOffset);
}

async function setupSubs(v) {
  $$("#video track").forEach(t => t.remove());          // drop the previous clip's tracks
  for (const tt of video.textTracks) tt.mode = "disabled";
  state.subs = [];
  state.subOffset = 0;            // sync resets per clip; the look (size/colour/box) is global
  buildCcMenu();
  let subs = [];
  try { subs = await api(`/api/subs?path=${enc(v.path)}`); } catch {}
  if (currentVideo !== v) return;                        // user moved on while we fetched
  state.subs = subs || [];
  for (const s of state.subs) {
    const tr = document.createElement("track");
    tr.kind = "subtitles"; tr.label = s.label; tr.srclang = s.lang || "und"; tr.src = s.url;
    tr.addEventListener("load", applyCueOffset);   // cues exist now → re-apply any sync offset
    video.appendChild(tr);
  }
  buildCcMenu();
  applyCaption(pickCaptionIndex());
}
function pickCaptionIndex() {
  if (state.ccLang === "off" || !state.subs.length) return null;
  const i = state.subs.findIndex(s => (s.lang && s.lang === state.ccLang) || s.label === state.ccLang);
  return i >= 0 ? i : null;
}
function applyCaption(idx) {
  const tracks = video.textTracks;
  for (let i = 0; i < tracks.length; i++) tracks[i].mode = (i === idx ? "showing" : "disabled");
  applyCueOffset();   // re-show with the current sync offset in place
  $("#ccBtn")?.classList.toggle("on", idx != null);
  $$("#ccMenu [data-cc]").forEach(b => b.classList.toggle("active", (+b.dataset.cc) === (idx == null ? -1 : idx)));
}
function setCaption(idx) {
  $("#ccMenu").classList.add("hidden");
  state.ccLang = (idx == null) ? "off" : (state.subs[idx].lang || state.subs[idx].label);
  try { localStorage.setItem("kadmu_cc", state.ccLang); } catch {}
  applyCaption(idx);
}
// keyboard "C": Off → 1st track → 2nd … → Off
function cycleCaption() {
  if (!state.subs.length) { toast("No subtitles for this video", ""); return; }
  const cur = pickCaptionIndex();
  const next = cur == null ? 0 : (cur + 1 >= state.subs.length ? null : cur + 1);
  setCaption(next);
  toast(next == null ? "Subtitles off" : `Subtitles: ${state.subs[next].label}`, "");
}
function buildCcMenu() {
  const wrap = $("#ccWrap"), menu = $("#ccMenu");
  if (!wrap || !menu) return;
  const has = state.subs.length > 0;
  wrap.classList.toggle("hidden", !has);
  if (!has) return;
  menu.classList.add("q-menu");
  menu.innerHTML = "";
  menu.appendChild(el("div", "q-head", "Subtitles"));
  const row = (idx, label) => {
    const b = el("button", "q-item"); b.dataset.cc = String(idx == null ? -1 : idx);
    b.innerHTML = `<div class="q-main"><span class="q-label">${escapeHtml(label)}</span></div>` +
                  `<span class="q-check">${qCheckIcon()}</span>`;
    b.onclick = () => setCaption(idx);
    menu.appendChild(b);
  };
  row(null, "Off");
  state.subs.forEach((s, i) => row(i, s.label));
  buildCcSettings(menu);
  applyCaption(pickCaptionIndex());
}

/* A label + a segmented row of choices (used for size / colour / box). */
function ccSeg(label, options, activeKey, onPick) {
  const rowEl = el("div", "cc-row");
  rowEl.appendChild(el("span", "cc-row-label", label));
  const seg = el("div", "cc-seg");
  options.forEach(o => {
    const b = el("button", "cc-seg-btn" + (o.key === activeKey ? " active" : ""));
    b.type = "button";
    if (o.swatch) { b.classList.add("cc-swatch"); b.style.setProperty("--sw", o.swatch); }
    else b.textContent = o.label;
    b.title = o.title || o.label;
    b.onclick = () => {
      $$(".cc-seg-btn", seg).forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      onPick(o.key);
    };
    seg.appendChild(b);
  });
  rowEl.appendChild(seg);
  return rowEl;
}
// Subtitle look (size/colour/box — persisted) + sync nudge (per-clip), appended
// under the track list so all caption controls live in one place.
function buildCcSettings(menu) {
  menu.appendChild(el("div", "cc-sep"));
  menu.appendChild(el("div", "q-head", "Subtitle settings"));

  const sync = el("div", "cc-row");
  sync.appendChild(el("span", "cc-row-label", "Sync"));
  const sc = el("div", "cc-sync");
  const mk = (txt, title, fn) => { const b = el("button", "cc-step", txt); b.type = "button"; b.title = title; b.onclick = fn; return b; };
  const val = el("span", "cc-sync-val"); val.id = "ccSyncVal"; val.textContent = fmtOffset(state.subOffset);
  sc.appendChild(mk("−", "Subtitles earlier (G)", () => setSubOffset(-0.1)));
  sc.appendChild(val);
  sc.appendChild(mk("+", "Subtitles later (H)", () => setSubOffset(0.1)));
  sc.appendChild(mk("⟲", "Reset sync", () => setSubOffset(0, 0)));
  sync.appendChild(sc);
  menu.appendChild(sync);

  menu.appendChild(ccSeg("Size",
    [{ key: "sm", label: "S" }, { key: "md", label: "M" }, { key: "lg", label: "L" }, { key: "xl", label: "XL" }],
    state.ccSize, (k) => { state.ccSize = k; persistCc(); applyCueStyle(); }));

  menu.appendChild(ccSeg("Color",
    Object.keys(CC_COLORS).map(k => ({ key: k, swatch: CC_COLORS[k], title: k[0].toUpperCase() + k.slice(1) })),
    state.ccColor, (k) => { state.ccColor = k; persistCc(); applyCueStyle(); }));

  menu.appendChild(ccSeg("Box",
    [{ key: "none", label: "Off" }, { key: "soft", label: "Soft" }, { key: "solid", label: "Solid" }],
    state.ccBg, (k) => { state.ccBg = k; persistCc(); applyCueStyle(); }));
}
// keyboard "a": cycle to the next audio track (no-op with fewer than two)
function cycleAudio() {
  const a = state.audios || [];
  if (a.length < 2) return;
  const ords = a.map(x => x.ord);
  const cur = ords.indexOf(state.audio || 0);
  setAudio(ords[(cur + 1) % ords.length]);
}

/* ---------- chapters (ffprobe markers -> seek-bar ticks + jump menu) ---------- */
function chapterAt(t) {
  const ch = state.chapters || [];
  for (let i = ch.length - 1; i >= 0; i--) if (t >= ch[i].start - 0.01) return ch[i];
  return null;
}
function renderChapterTicks() {
  const ticks = $("#chapterTicks");
  if (!ticks) return;
  ticks.innerHTML = "";
  const total = totalDuration();
  if (!total) return;
  for (const c of (state.chapters || [])) {
    if (c.start <= 0) continue;
    const t = el("i", "chapter-tick");
    t.style.left = Math.min(100, (c.start / total) * 100) + "%";
    t.title = c.title || "";
    ticks.appendChild(t);
  }
}
function renderChapters() {
  renderChapterTicks();
  const wrap = $("#chaptersWrap"), menu = $("#chaptersMenu");
  if (!wrap || !menu) return;
  const ch = state.chapters || [];
  wrap.classList.toggle("hidden", ch.length < 1);
  if (!ch.length) return;
  menu.classList.add("q-menu", "chapters-menu");
  menu.innerHTML = "";
  menu.appendChild(el("div", "q-head", `Chapters · ${ch.length}`));
  ch.forEach((c, i) => {
    const b = el("button", "q-item");
    b.dataset.chap = String(i);
    b.innerHTML = `<div class="q-main"><span class="q-label">${escapeHtml(c.title || ("Chapter " + (i + 1)))}</span>` +
                  `<span class="q-sub">${fmtTime(c.start)}</span></div>` +
                  `<span class="q-check">${qCheckIcon()}</span>`;
    b.onclick = () => { $("#chaptersMenu").classList.add("hidden"); seekTo(c.start); };
    menu.appendChild(b);
  });
  highlightChapter();
}
function highlightChapter() {
  if (!(state.chapters || []).length) return;
  const cur = chapterAt(currentPlayPos());
  const ci = cur ? state.chapters.indexOf(cur) : -1;
  $$("#chaptersMenu [data-chap]").forEach(b => b.classList.toggle("active", +b.dataset.chap === ci));
}
// jump to the next / previous chapter (prev first rewinds to the current one's start)
function skipChapter(dir) {
  const ch = state.chapters || [];
  if (!ch.length) return;                 // harmless no-op when the file has no chapters
  const pos = currentPlayPos();
  let target = null;
  if (dir > 0) {
    target = ch.find(c => c.start > pos + 0.5);
  } else {
    const cur = chapterAt(pos), idx = cur ? ch.indexOf(cur) : -1;
    target = (cur && pos - cur.start > 3) ? cur : (idx > 0 ? ch[idx - 1] : ch[0]);
  }
  if (target) { seekTo(target.start); toast(target.title || "Chapter", ""); }
}

/* ---------- storyboard scrub previews (sprite sheet) ---------- */
let sbLoading = false;
function resetStoryboard(v) {
  state.storyboard = null;
  state.storyboardFor = v ? v.path : null;
  sbLoading = false;
  const img = $("#sbImg"); if (img) img.style.backgroundImage = "";
}
// Lazily fetch + preload the sprite sheet the first time the user scrubs.
async function ensureStoryboard() {
  if (!currentVideo || state.storyboard || sbLoading) return;
  if (!state.session.ffmpeg) { state.storyboard = { ok: false }; return; }
  sbLoading = true;
  const forPath = currentVideo.path;
  try {
    const info = await api(`/api/storyboard?path=${enc(forPath)}`);
    if (!currentVideo || currentVideo.path !== forPath) return;
    if (info && info.ok && info.count) {
      info.url = `/api/storyboard.jpg?path=${enc(forPath)}`;
      const img = new Image();
      img.onload = () => {
        if (currentVideo && currentVideo.path === forPath) {
          info.tw = img.naturalWidth / info.cols;
          info.th = img.naturalHeight / info.rows;
          state.storyboard = info;
        }
      };
      img.onerror = () => { if (currentVideo && currentVideo.path === forPath) state.storyboard = { ok: false }; };
      img.src = info.url;
      state.storyboard = info;          // tw/th fill in on image load
    } else {
      state.storyboard = { ok: false };
    }
  } catch { state.storyboard = { ok: false }; }
  finally { sbLoading = false; }
}
// Update the hover preview at fraction `pct` of the seek bar: rich sprite tile when
// the storyboard is ready, otherwise the plain time bubble. Both carry the chapter name.
function updateScrubPreview(pct) {
  const total = totalDuration();
  const t = pct * total;
  const sb = state.storyboard;
  const wrap = $("#seekWrap"), tip = $("#seekTip"), prev = $("#sbPreview");
  const chap = chapterAt(t);
  if (sb && sb.ok && sb.tw) {
    const idx = Math.max(0, Math.min(sb.count - 1, Math.floor(t / sb.interval)));
    const col = idx % sb.cols, row = Math.floor(idx / sb.cols);
    const img = $("#sbImg");
    img.style.width = sb.tw + "px";
    img.style.height = sb.th + "px";
    img.style.backgroundImage = `url("${sb.url}")`;
    img.style.backgroundSize = `${sb.cols * sb.tw}px ${sb.rows * sb.th}px`;
    img.style.backgroundPosition = `-${col * sb.tw}px -${row * sb.th}px`;
    $("#sbTime").textContent = fmtTime(t);
    const sc = $("#sbChap");
    sc.textContent = chap ? (chap.title || "") : "";
    sc.classList.toggle("hidden", !(chap && chap.title));
    prev.style.left = (pct * 100) + "%";
    wrap.classList.add("sb-on");
  } else {
    tip.textContent = fmtTime(t) + (chap && chap.title ? ` · ${chap.title}` : "");
    tip.style.left = (pct * 100) + "%";
    wrap.classList.remove("sb-on");
  }
}

/* ---------- sleep timer / stop-after-episode ---------- */
const SLEEP_OPTS = [
  { id: "off", label: "Off" },
  { id: "ep", label: "After this episode" },
  { id: "15", label: "15 minutes", mins: 15 },
  { id: "30", label: "30 minutes", mins: 30 },
  { id: "45", label: "45 minutes", mins: 45 },
  { id: "60", label: "1 hour", mins: 60 },
  { id: "end", label: "End of this video" },
];
const sleepLabel = (id) => (SLEEP_OPTS.find(o => o.id === id) || {}).label || "";
function buildSleepMenu() {
  const menu = $("#sleepMenu");
  if (!menu) return;
  menu.classList.add("q-menu");
  menu.innerHTML = "";
  menu.appendChild(el("div", "q-head", "Sleep timer"));
  SLEEP_OPTS.forEach(o => {
    const b = el("button", "q-item" + (state.sleep.mode === o.id ? " active" : ""));
    b.innerHTML = `<div class="q-main"><span class="q-label">${escapeHtml(o.label)}</span></div>` +
                  `<span class="q-check">${qCheckIcon()}</span>`;
    b.onclick = () => setSleep(o.id);
    menu.appendChild(b);
  });
}
function clearSleepTimers() {
  if (state.sleep.timer) { clearTimeout(state.sleep.timer); state.sleep.timer = null; }
  if (state.sleep.tick) { clearInterval(state.sleep.tick); state.sleep.tick = null; }
}
function setSleep(id) {
  $("#sleepMenu").classList.add("hidden");
  clearSleepTimers();
  const opt = SLEEP_OPTS.find(o => o.id === id) || SLEEP_OPTS[0];
  state.sleep.mode = id;
  state.sleep.deadline = 0;
  if (opt.mins) {
    state.sleep.deadline = nowMs() + opt.mins * 60000;
    state.sleep.timer = setTimeout(sleepFire, opt.mins * 60000);
    state.sleep.tick = setInterval(updateSleepButton, 1000);
    toast(`Sleep timer: ${opt.label}`, "ok");
  } else if (id === "end") {
    toast("Sleep: stopping at the end of this video", "ok");
  } else if (id === "ep") {
    toast("Sleep: stopping after this episode", "ok");
  } else {
    toast("Sleep timer off", "");
  }
  buildSleepMenu();
  updateSleepButton();
}
function nowMs() { return (typeof performance !== "undefined" && performance.timeOrigin)
  ? performance.timeOrigin + performance.now() : +new Date(); }
function updateSleepButton() {
  const btn = $("#sleepBtn");
  if (!btn) return;
  const on = state.sleep.mode !== "off";
  btn.classList.toggle("on", on);
  let left = "";
  if (state.sleep.deadline) {
    const ms = Math.max(0, state.sleep.deadline - nowMs());
    left = " · " + fmtTime(ms / 1000);
  }
  btn.title = on ? `Sleep timer: ${sleepLabel(state.sleep.mode)}${left}` : "Sleep timer";
}
function sleepFire() {                  // a timed countdown elapsed -> pause now
  clearSleepTimers();
  state.sleep.mode = "off"; state.sleep.deadline = 0;
  buildSleepMenu(); updateSleepButton();
  hideNextCard();
  try { video.pause(); } catch {}
  toast("Sleep timer — paused", "ok");
}
// At end-of-video: should we stop instead of advancing? "After this episode" and
// "End of this video" are one-shot — they consume themselves and block autoplay.
function sleepStopsAtEnd() {
  if (state.sleep.mode === "ep" || state.sleep.mode === "end") {
    clearSleepTimers();
    state.sleep.mode = "off"; state.sleep.deadline = 0;
    buildSleepMenu(); updateSleepButton();
    return true;
  }
  return false;
}

/* ---------- viewer profiles (opt-in) ---------- */
async function loadProfiles() {
  let data = { enabled: false, profiles: [] };
  try { data = await api("/api/profiles"); } catch {}
  state.profilesEnabled = !!data.enabled;
  const btn = $("#profileBtn");
  if (!state.profilesEnabled) { btn?.classList.add("hidden"); return; }
  state.profileList = data.profiles || [];
  const cur = currentProfile();
  const known = state.profileList.find(p => p.id === cur) || { id: "default", name: "Default" };
  updateProfileButton(known);
  btn?.classList.remove("hidden");
  let chosen = false;
  try { chosen = localStorage.getItem("kadmu_profile_chosen") === "1"; } catch {}
  if (!chosen) showProfileChooser();
}
function updateProfileButton(p) {
  const ava = $("#profileAva");
  if (ava) ava.textContent = ((p && p.name) || "?").trim().charAt(0).toUpperCase() || "?";
  const btn = $("#profileBtn");
  if (btn) btn.title = `Profile: ${(p && (p.name || p.id)) || "Default"} — switch`;
}
async function showProfileChooser() {
  const ov = $("#profileOverlay"), grid = $("#profileGrid");
  if (!ov || !grid) return;
  let list = state.profileList || [];
  try { const d = await api("/api/profiles"); list = d.profiles || list; state.profileList = list; } catch {}
  grid.innerHTML = "";
  for (const p of list) {
    const b = el("button", "profile-tile" + (p.id === currentProfile() ? " current" : ""));
    b.innerHTML = `<span class="profile-ava big">${escapeHtml((p.name || "?").charAt(0).toUpperCase())}</span>` +
                  `<span class="profile-name">${escapeHtml(p.name || p.id)}</span>`;
    b.onclick = () => selectProfile(p);
    grid.appendChild(b);
  }
  applyIcons(ov);
  ov.classList.remove("hidden");
}
function hideProfileChooser() { $("#profileOverlay")?.classList.add("hidden"); }
async function selectProfile(p) {
  try { localStorage.setItem("kadmu_profile", p.id); localStorage.setItem("kadmu_profile_chosen", "1"); } catch {}
  updateProfileButton(p);
  hideProfileChooser();
  try { state.mylist = new Set((await api("/api/mylist")).map(i => i.path)); } catch {}
  try { state.progress = await api("/api/progress"); } catch {}
  loadLibrary(state.searchActive ? null : state.path);
  toast(`Watching as ${p.name || p.id}`, "ok");
}
async function addProfile(name) {
  name = (name || "").trim();
  if (!name) return;
  try {
    const r = await api("/api/profiles", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (r && r.ok) { state.profileList = r.profiles || []; selectProfile(r.profile); }
  } catch (e) { toast(e.message, "err"); }
}

function showUi() {
  $("#playerOverlay").classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!video.paused) $("#playerOverlay").classList.add("idle"); }, 2600);
}

/* ---- player touch gestures (#13): double-tap to seek, swipe to scrub, tap for UI ---- */
let _flashEl = null, _flashTimer = null;
function gestureFlash(txt, autoHide) {
  const stage = $("#playerStage"); if (!stage) return;
  if (!_flashEl) { _flashEl = el("div", "gesture-flash"); stage.appendChild(_flashEl); }
  _flashEl.textContent = txt;
  _flashEl.classList.add("show");
  clearTimeout(_flashTimer);
  if (autoHide) _flashTimer = setTimeout(() => _flashEl && _flashEl.classList.remove("show"), 600);
}
function gestureFlashHide() { if (_flashEl) _flashEl.classList.remove("show"); }
function initPlayerGestures() {
  const stage = $("#playerStage");
  if (!stage) return;
  // never hijack a tap that lands on a real control
  const onCtrl = (t) => t && t.closest && t.closest(".player-ui, .player-top, .next-card, .queue, .menu, .q-menu, .big-play, .queue-open, .pip-hint");
  const DOUBLE_MS = 320, SWIPE_MIN = 36;
  let lastTap = 0, lastSide = "", tapTimer = null;
  let sx = 0, sy = 0, swiping = false, swiped = false, startPos = 0, target = 0;

  stage.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || onCtrl(e.target)) { swiping = swiped = false; return; }
    const t = e.touches[0];
    sx = t.clientX; sy = t.clientY; swiping = swiped = false; startPos = currentPlayPos();
  }, { passive: true });

  stage.addEventListener("touchmove", (e) => {
    if (e.touches.length !== 1 || !currentVideo || onCtrl(e.target)) return;
    const t = e.touches[0], dx = t.clientX - sx, dy = t.clientY - sy;
    if (!swiping && Math.abs(dx) > SWIPE_MIN && Math.abs(dx) > Math.abs(dy) * 1.4) { swiping = true; showUi(); }
    if (swiping) {
      swiped = true;
      const total = totalDuration() || 0;
      const span = stage.clientWidth || window.innerWidth || 1;
      const reach = total ? total * 0.5 : 120;          // a full-width drag ≈ half the video
      target = startPos + (dx / span) * reach;
      target = Math.max(0, total ? Math.min(target, total - 0.4) : target);
      gestureFlash((dx < 0 ? "◀ " : "▶ ") + fmtTime(target) + (total ? " / " + fmtTime(total) : ""));
      e.preventDefault();
    }
  }, { passive: false });

  stage.addEventListener("touchend", (e) => {
    if (onCtrl(e.target)) return;
    if (swiped) { seekTo(target); gestureFlashHide(); e.preventDefault(); return; }
    const w = stage.clientWidth || window.innerWidth || 1;
    const x = (e.changedTouches[0] || {}).clientX || 0;
    const side = x < w * 0.4 ? "L" : x > w * 0.6 ? "R" : "C";
    const now = Date.now();
    if (now - lastTap < DOUBLE_MS && side === lastSide && side !== "C") {
      clearTimeout(tapTimer); lastTap = 0;
      if (side === "L") { seekTo(currentPlayPos() - 10); gestureFlash("◀ 10s", true); }
      else { seekTo(currentPlayPos() + 10); gestureFlash("10s ▶", true); }
      e.preventDefault();
      return;
    }
    lastTap = now; lastSide = side;
    e.preventDefault();        // we own video taps on touch — suppress the synthetic click
    clearTimeout(tapTimer);
    tapTimer = setTimeout(() => {
      const ov = $("#playerOverlay");
      if (ov.classList.contains("idle")) showUi();   // hidden controls -> reveal
      else togglePlay();                             // visible -> play/pause
    }, DOUBLE_MS);
  }, { passive: false });
}

async function togglePip() {
  try {
    if (document.pictureInPictureElement) { await document.exitPictureInPicture(); return; }
    if (document.pictureInPictureEnabled && video.requestPictureInPicture) {
      await video.requestPictureInPicture();
      return;
    }
    throw new Error("no-api");
  } catch { showPipHint(); }
}
function showPipHint() {
  const h = $("#pipHint");
  h.innerHTML = `<b>Pop out over your tabs</b><br>
    In Firefox, hover the video and click the <b>Picture-in-Picture</b> toggle it shows,
    or right-click ▸ Picture-in-Picture. Keyboard: <b>Ctrl</b>+<b>Shift</b>+<b>]</b>.
    The video then floats over everything while you work.`;
  h.classList.remove("hidden");
  clearTimeout(h._t);
  h._t = setTimeout(() => h.classList.add("hidden"), 7000);
}
function maybeCoachPip() {
  if (localStorage.getItem("kadmu_pip_seen")) return;
  localStorage.setItem("kadmu_pip_seen", "1");
  setTimeout(showPipHint, 900);
}

function toggleFs() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("#playerOverlay").requestFullscreen().catch(() => {});
}

/* ===================== events ===================== */
function wire() {
  $("#brand").onclick = () => loadLibrary(null);
  $("#refreshBtn").onclick = () => loadLibrary(state.path);
  $("#settingsBtn").onclick = openSettings;
  $("#settingsClose").onclick = closeSettings;
  $("#shortcutsBtn")?.addEventListener("click", openShortcuts);
  $("#shortcutsClose")?.addEventListener("click", closeShortcuts);
  $("#shortcutsModal")?.addEventListener("click", e => { if (e.target.id === "shortcutsModal") closeShortcuts(); });
  $("#keyHudToggle")?.addEventListener("change", (e) => {
    state.keyHud = e.target.checked;
    try { localStorage.setItem("kadmu_keyhud", state.keyHud ? "1" : "0"); } catch {}
    if (state.keyHud) flashKey(["✓"]);   // quick confirmation of the new setting
  });
  $("#addRootBtn").onclick = addRoot;
  $("#browseRootBtn").onclick = addFolder;
  $("#rootInput").addEventListener("keydown", e => { if (e.key === "Enter") addRoot(); });

  // Shift+click is our multi-select gesture — stop the browser from turning it into
  // a text/range selection while picking cards. preventDefault on mousedown blocks
  // the selection but still lets the click event through to toggle the item.
  $("#library").addEventListener("mousedown", (e) => {
    if (e.shiftKey && e.target.closest(".video-card, .folder-card")) e.preventDefault();
  });

  // right-click anywhere in the library background (not on a card) -> "New folder"
  $("#library").addEventListener("contextmenu", (e) => {
    if (e.target.closest(".video-card, .folder-card")) return;   // cards handle their own
    openContextMenu(e, null);
  });
  // dismiss the context menu on any click, scroll, or resize
  document.addEventListener("click", (e) => { if (!e.target.closest("#ctxMenu")) closeContextMenu(); });
  document.addEventListener("click", (e) => { if (sdd.open && !e.target.closest("#searchBox")) closeSearchDD(); });
  window.addEventListener("scroll", closeContextMenu, true);
  window.addEventListener("resize", closeContextMenu);

  $("#dialogClose").onclick = closeDialog;
  $("#dialogCancel").onclick = closeDialog;
  $("#dialogOk").onclick = async () => {
    if (!dialogOkHandler) return closeDialog();
    const res = await dialogOkHandler();
    if (res !== false) closeDialog();
  };

  $("#playerClose").onclick = closePlayer;
  $("#playPause").onclick = togglePlay;
  $("#bigPlay").onclick = togglePlay;
  $("#back10").onclick = () => seekTo(currentPlayPos() - 10);
  $("#fwd10").onclick = () => seekTo(currentPlayPos() + 10);
  $("#prevBtn").onclick = () => playIndex(state.qIndex - 1);
  $("#nextBtn").onclick = goNext;
  $("#muteBtn").onclick = () => { video.muted = !video.muted; };
  $("#loopBtn").onclick = () => { video.loop = !video.loop; $("#loopBtn").classList.toggle("on", video.loop); };
  $("#pipBtn").onclick = togglePip;
  $("#fsBtn").onclick = toggleFs;
  $("#autoNext").onclick = () => {
    state.autoNext = !state.autoNext;
    $("#autoNext").classList.toggle("on", state.autoNext);
    $("#autoNext").title = state.autoNext ? "Autoplay next episode: on" : "Autoplay next episode: off";
    if (!state.autoNext) hideNextCard();          // drop any running countdown
  };
  $("#autoNext").classList.add("on");

  // side panel collapse / browse
  $("#queueCollapse").onclick = () => setPanelCollapsed(true);
  $("#queueOpen").onclick = togglePanel;

  // next-up card  (Play-now / Continue resets the "still watching?" streak)
  $("#nextPlayBtn").onclick = confirmNext;
  $("#nextThumb").onclick = confirmNext;
  $("#nextCancelBtn").onclick = hideNextCard;

  // null-safe: a menu button that isn't in the DOM yet (e.g. a feature still being
  // wired up) must not throw and abort the rest of init().
  $("#speedBtn")?.addEventListener("click", () => $("#speedMenu")?.classList.toggle("hidden"));
  $$("#speedMenu button").forEach(b => b.onclick = () => setSpeed(+b.dataset.rate));
  $("#qualityBtn")?.addEventListener("click", () => $("#qualityMenu")?.classList.toggle("hidden"));
  $("#audioBtn")?.addEventListener("click", () => $("#audioMenu")?.classList.toggle("hidden"));
  $("#ccBtn")?.addEventListener("click", () => $("#ccMenu")?.classList.toggle("hidden"));
  $("#audioBtn")?.addEventListener("click", () => $("#audioMenu")?.classList.toggle("hidden"));
  $("#chaptersBtn")?.addEventListener("click", () => $("#chaptersMenu")?.classList.toggle("hidden"));
  $("#sleepBtn")?.addEventListener("click", () => { buildSleepMenu(); $("#sleepMenu")?.classList.toggle("hidden"); });

  // viewer profiles (opt-in): topbar avatar opens the chooser; the chooser adds/switches
  $("#profileBtn")?.addEventListener("click", showProfileChooser);
  $("#profileAddForm")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = $("#profileNewName");
    addProfile(inp.value); inp.value = "";
  });
  $("#profileOverlay")?.addEventListener("click", (e) => { if (e.target.id === "profileOverlay") hideProfileChooser(); });

  // search (top bar) — live dropdown + keyboard nav
  const searchInput = $("#searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", onSearchInput);
    searchInput.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!sdd.open && searchInput.value.trim()) suggest(searchInput.value); else moveActive(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); moveActive(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (sdd.open && sdd.active >= 0) activateItem(sdd.active);
        else if (searchInput.value.trim()) runSearch(searchInput.value);
      } else if (e.key === "Escape") {
        if (sdd.open) closeSearchDD();
        else { searchInput.value = ""; $("#searchBox")?.classList.remove("has-text"); exitSearch(); searchInput.blur(); }
      }
    });
    searchInput.addEventListener("focus", () => {
      if (searchInput.value.trim() && !sdd.open) suggest(searchInput.value);
    });
    $("#searchClear").onclick = () => {
      searchInput.value = ""; $("#searchBox")?.classList.remove("has-text");
      closeSearchDD(); exitSearch(); searchInput.focus();
    };
  }

  // seek-bar hover preview: storyboard sprite tile (lazy-loaded) + time + chapter,
  // falling back to the plain time bubble until the sprite is ready / if unavailable.
  const seekWrap = $("#seekWrap");
  if (seekWrap) {
    seekWrap.addEventListener("mousemove", e => {
      const total = totalDuration();
      if (!total) return;
      ensureStoryboard();                       // kick off the lazy sprite fetch on first scrub
      const r = seekWrap.getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      updateScrubPreview(pct);
      seekWrap.classList.add("scrubbing");
    });
    seekWrap.addEventListener("mouseleave", () => seekWrap.classList.remove("scrubbing", "sb-on"));
  }

  $("#seek").addEventListener("input", e => {
    const total = totalDuration();
    // Seekable file: scrub live as the slider moves. Live stream: just update the
    // label; the actual seek (an encode restart) fires once on release ("change").
    if (canSeekNow() && video.duration) video.currentTime = (e.target.value / 1000) * video.duration;
    if (total) $("#timeCur").textContent = fmtTime((e.target.value / 1000) * total);
    paintRange(e.target);
  });
  $("#seek").addEventListener("change", e => {
    if (canSeekNow()) return;   // handled live above
    const total = totalDuration();
    if (total) seekTo((e.target.value / 1000) * total);
  });
  $("#volume").addEventListener("input", e => {
    video.volume = +e.target.value; video.muted = false;
    localStorage.setItem("kadmu_volume", e.target.value);
    paintRange(e.target);
  });

  video.addEventListener("timeupdate", () => {
    updateTime();
    tickAutoNext();
    if (!saveTimer) saveTimer = setTimeout(() => { saveProgress(false); saveTimer = null; }, 5000);
  });
  video.addEventListener("play", () => {
    $("#playPause").innerHTML = ICON.pause;
    $("#playerOverlay").classList.remove("paused");
    showUi();
  });
  video.addEventListener("pause", () => {
    $("#playPause").innerHTML = ICON.play;
    $("#playerOverlay").classList.add("paused");
    saveProgress(true); showUi();
  });
  video.addEventListener("volumechange", () => {
    const v = video.muted ? 0 : video.volume;
    $("#muteBtn").innerHTML = v === 0 ? ICON.volMute : (v < 0.5 ? ICON.volLow : ICON.volHigh);
    $("#volume").value = v;
    paintRange($("#volume"));
  });
  video.addEventListener("ended", () => {
    saveProgress(true);
    if (video.loop) return;
    // Sleep timer "after this episode" / "end of this video": stop here, don't advance.
    if (sleepStopsAtEnd()) { hideNextCard(); toast("Sleep timer — stopped", "ok"); return; }
    // Autoplay normally hands off ~NEXT_GUARD before this fires, so PiP survives. If we still
    // land here with a next queued — a clip shorter than the lead, a throttled background tab —
    // roll over anyway (best effort); otherwise show the terminal card.
    if (state.pendingNext && state.autoNext && !nextAsks()) { autoAdvance(); return; }
    showNextCard("end");
  });
  video.addEventListener("durationchange", () => { if ((state.chapters || []).length) renderChapterTicks(); });
  video.addEventListener("error", () => {
    hideSpinner();
    if ($("#playerOverlay").classList.contains("hidden")) return;   // ignore the error from clearing src on close
    if (!currentVideo || !video.currentSrc) return;
    const err = video.error;
    const msg = (err && err.code === err.MEDIA_ERR_SRC_NOT_SUPPORTED)
      ? "This video couldn't be prepared for the browser. Try converting it to MP4 (H.264) or WebM."
      : "Couldn't play this video — it may have been moved, deleted, or is unreadable.";
    toast(msg, "err");
  });
  // Drive the loading indicator off the standard media events so every file type —
  // instant native or freshly-remuxed — shows the same brief 'preparing' state.
  video.addEventListener("loadstart", () => {
    if ($("#playerOverlay").classList.contains("hidden")) return;
    let label = "Loading…";
    if (state.quality && state.quality !== "original") label = `Preparing ${qLabel(state.quality)}…`;
    else if (currentVideo && currentVideo.direct === false) label = "Preparing this video…";
    showSpinner(label);
  });
  video.addEventListener("playing", hideSpinner);
  video.addEventListener("canplay", hideSpinner);
  video.addEventListener("seeked", hideSpinner);
  video.addEventListener("waiting", () => showSpinner("Loading…"));
  video.addEventListener("stalled", () => showSpinner("Loading…"));
  document.addEventListener("fullscreenchange", () => {
    $("#fsBtn").innerHTML = document.fullscreenElement ? ICON.fullscreenExit : ICON.fullscreen;
  });

  const vol = localStorage.getItem("kadmu_volume");
  if (vol != null) { video.volume = +vol; $("#volume").value = vol; }
  paintRange($("#volume"));

  const overlay = $("#playerOverlay");
  overlay.addEventListener("mousemove", showUi);
  $("#playerStage").addEventListener("click", (e) => { if (e.target === video) togglePlay(); });
  initPlayerGestures();

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#speedBtn, #speedMenu")) $("#speedMenu").classList.add("hidden");
    if (!e.target.closest("#qualityBtn, #qualityMenu")) $("#qualityMenu").classList.add("hidden");
    if (!e.target.closest("#audioBtn, #audioMenu")) $("#audioMenu").classList.add("hidden");
    if (!e.target.closest("#ccBtn, #ccMenu")) $("#ccMenu").classList.add("hidden");
    if (!e.target.closest("#audioBtn, #audioMenu")) $("#audioMenu")?.classList.add("hidden");
    if (!e.target.closest("#chaptersBtn, #chaptersMenu")) $("#chaptersMenu")?.classList.add("hidden");
    if (!e.target.closest("#sleepBtn, #sleepMenu")) $("#sleepMenu")?.classList.add("hidden");
  });
  $("#settingsModal").addEventListener("click", e => { if (e.target.id === "settingsModal") closeSettings(); });
  $("#dialog").addEventListener("click", e => { if (e.target.id === "dialog") closeDialog(); });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = $("#loginPassword").value;
    $("#loginError").textContent = "";
    try {
      const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Kadmu": "1" }, body: JSON.stringify({ password: pw }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.authed) { hideLogin(); $("#loginPassword").value = ""; await boot(); }
      else { $("#loginError").textContent = d.error || "Wrong password."; }
    } catch { $("#loginError").textContent = "Could not reach the server."; }
  });

  document.addEventListener("keydown", onKey);
  // Back / Forward (and pasting a #/… link into the bar) replay the route.
  window.addEventListener("popstate", renderFromRoute);
  window.addEventListener("hashchange", renderFromRoute);
  const onUnload = () => { unloading = true; saveProgress(); };
  window.addEventListener("pagehide", onUnload);
  window.addEventListener("beforeunload", onUnload);

  wireDragDrop();
}

/* ===================== keyboard shortcuts (single source of truth) =====================
   This array drives BOTH the actual key handling notes and the help UI (the topbar
   "?" overlay and the Settings panel), so the docs can never drift from the binds. */
const KEYBINDS = [
  { group: "Playback", items: [
    { keys: ["Space", "K"], desc: "Play / pause" },
    { keys: ["←", "→"], desc: "Seek 10 seconds" },
    { keys: ["Shift", "←", "→"], desc: "Seek 5 seconds (fine)" },
    { keys: ["J"], desc: "Jump back 30 seconds" },
    { keys: ["0–9"], desc: "Jump to 0–90% of the video" },
    { keys: ["Home", "End"], desc: "Jump to start / near the end" },
    { keys: ["[", "]"], desc: "Slower / faster playback" },
    { keys: ["L"], desc: "Loop this video" },
  ]},
  { group: "Volume", items: [
    { keys: ["↑", "↓"], desc: "Volume up / down" },
    { keys: ["M"], desc: "Mute / unmute" },
  ]},
  { group: "Audio & subtitles", items: [
    { keys: ["A"], desc: "Cycle audio track" },
    { keys: ["C"], desc: "Cycle subtitles / captions" },
    { keys: ["G", "H"], desc: "Subtitle sync earlier / later" },
  ]},
  { group: "Chapters", items: [
    { keys: [",", "."], desc: "Previous / next chapter" },
  ]},
  { group: "Episodes & player", items: [
    { keys: ["Shift", "N"], desc: "Next episode" },
    { keys: ["Shift", "P"], desc: "Previous episode" },
    { keys: ["E"], desc: "Toggle the episodes panel" },
    { keys: ["F"], desc: "Fullscreen" },
    { keys: ["P"], desc: "Picture-in-Picture" },
    { keys: ["S"], desc: "Sleep timer (after this episode)" },
    { keys: ["Esc"], desc: "Close the player" },
  ]},
  { group: "Library & general", items: [
    { keys: ["/"], desc: "Jump to search" },
    { keys: ["?"], desc: "Show this shortcuts list" },
    { keys: ["Esc"], desc: "Close menus / clear selection" },
  ]},
];

// Render the keybinds into a target element (used by the overlay and Settings).
function renderKeybinds(target) {
  if (!target) return;
  target.innerHTML = "";
  for (const sec of KEYBINDS) {
    const g = el("div", "kbd-group");
    g.appendChild(el("h5", "kbd-group-title", escapeHtml(sec.group)));
    const grid = el("div", "kbd-grid");
    for (const it of sec.items) {
      const row = el("div", "kbd-row");
      const keys = el("span", "keys");
      keys.innerHTML = it.keys.map(k => `<kbd>${escapeHtml(k)}</kbd>`).join("");
      row.appendChild(keys);
      row.appendChild(el("span", "kbd-act", escapeHtml(it.desc)));
      grid.appendChild(row);
    }
    g.appendChild(grid);
    target.appendChild(g);
  }
}
function openShortcuts() { renderKeybinds($("#shortcutsBody")); $("#shortcutsModal")?.classList.remove("hidden"); }
function closeShortcuts() { $("#shortcutsModal")?.classList.add("hidden"); }
function toggleShortcuts() {
  $("#shortcutsModal")?.classList.contains("hidden") ? openShortcuts() : closeShortcuts();
}

/* ---------- key-press HUD (quick center flash of the shortcut you pressed) ---------- */
const KEY_SYMBOLS = { " ": "Space", "ArrowLeft": "←", "ArrowRight": "→", "ArrowUp": "↑",
                      "ArrowDown": "↓", "Escape": "Esc" };
// e.key values we actually act on while the player is open (numbers handled separately).
const PLAYER_KEYS = new Set([" ", "k", "ArrowLeft", "ArrowRight", "j", "l", "ArrowUp",
  "ArrowDown", "m", "a", "c", "e", "f", "p", "s", "N", "P", "[", "]", ".", ",", "Home", "End"]);
// Turn a keyboard event into display chips, e.g. ["Shift","→"] or ["Space"] or ["?"].
function keyChips(e) {
  const chips = [];
  if (e.ctrlKey) chips.push("Ctrl");
  if (e.altKey) chips.push("Alt");
  if (e.metaKey) chips.push("Cmd");
  const isArrow = e.key.startsWith("Arrow");
  const isLetter = /^[a-zA-Z]$/.test(e.key);
  if (e.shiftKey && (isArrow || isLetter)) chips.push("Shift");   // shift as a modifier (not for "?", "<", …)
  chips.push(KEY_SYMBOLS[e.key] || (isLetter ? e.key.toUpperCase() : e.key));
  return chips;
}
let keyHudTimer = null;
function flashKey(chips) {
  if (!state.keyHud) return;                  // disabled in settings
  const hud = $("#keyHud");
  if (!hud || !chips.length) return;
  hud.innerHTML = chips.map((c, i) =>
    (i ? `<span class="kh-plus">+</span>` : "") + `<kbd>${escapeHtml(c)}</kbd>`).join("");
  hud.classList.remove("show");
  void hud.offsetWidth;                        // reflow so the animation restarts on rapid presses
  hud.classList.add("show");
  clearTimeout(keyHudTimer);
  keyHudTimer = setTimeout(() => hud.classList.remove("show"), 760);
}

function onKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
    if (e.key === "Escape") { closeDialog(); closeSettings(); }
    return;
  }
  const playerOpen = !$("#playerOverlay").classList.contains("hidden");
  if (e.key === "Escape") {
    if (!$("#shortcutsModal").classList.contains("hidden")) return closeShortcuts();
    if (!$("#ctxMenu").classList.contains("hidden")) return closeContextMenu();
    if (!$("#dialog").classList.contains("hidden")) return closeDialog();
    if (!$("#settingsModal").classList.contains("hidden")) return closeSettings();
    if (state.profilesEnabled && !$("#profileOverlay").classList.contains("hidden")) return hideProfileChooser();
    if (playerOpen && !$("#nextCard").classList.contains("hidden")) return hideNextCard();
    if (playerOpen) return closePlayer();
    if (state.selection.size) return clearSelection();
  }
  // Flash the pressed combo in the center for recognised shortcuts (toggleable).
  const recognised = (e.key === "?") || (!playerOpen && e.key === "/")
    || (playerOpen && (PLAYER_KEYS.has(e.key) || /^[0-9]$/.test(e.key)));
  if (recognised) flashKey(keyChips(e));
  // "?" opens the shortcuts list from anywhere.
  if (e.key === "?") { e.preventDefault(); toggleShortcuts(); return; }
  if (!playerOpen) {
    // "/" jumps to search from the library.
    if (e.key === "/") { e.preventDefault(); const si = $("#searchInput"); if (si) { si.focus(); si.select(); } }
    return;
  }
  switch (e.key) {
    case " ": case "k": e.preventDefault(); togglePlay(); break;
    case "ArrowLeft": seekTo(currentPlayPos() - (e.shiftKey ? 5 : 10)); break;
    case "ArrowRight": seekTo(currentPlayPos() + (e.shiftKey ? 5 : 10)); break;
    case "j": seekTo(currentPlayPos() - 30); break;
    case "l": video.loop = !video.loop; $("#loopBtn").classList.toggle("on", video.loop); break;
    case "ArrowUp": e.preventDefault(); video.volume = Math.min(1, video.volume + 0.05); video.muted = false; break;
    case "ArrowDown": e.preventDefault(); video.volume = Math.max(0, video.volume - 0.05); break;
    case "m": video.muted = !video.muted; break;
    case "a": cycleAudio(); break;                                          // audio track
    case "c": cycleCaption(); break;                                        // subtitles
    case "e": togglePanel(); break;                                         // episodes panel
    case "g": if (state.subs.length) { setSubOffset(-0.1); toast("Subtitle sync " + fmtOffset(state.subOffset), ""); } break;
    case "h": if (state.subs.length) { setSubOffset(0.1); toast("Subtitle sync " + fmtOffset(state.subOffset), ""); } break;
    case "f": toggleFs(); break;
    case "p": togglePip(); break;
    case "s": setSleep(state.sleep.mode === "off" ? "ep" : "off"); break;   // sleep timer
    case "N": goNext(); break;
    case "P": playIndex(state.qIndex - 1); break;
    case "[": setSpeed(Math.max(0.25, +(video.playbackRate - 0.25).toFixed(2))); break;
    case "]": setSpeed(Math.min(3, +(video.playbackRate + 0.25).toFixed(2))); break;
    case ".": skipChapter(1); break;                                        // next chapter
    case ",": skipChapter(-1); break;                                       // previous chapter
    case "Home": seekTo(0); break;
    case "End": { const t = totalDuration(); if (t) seekTo(t - 5); break; }
    default:
      if (/^[0-9]$/.test(e.key)) { const t = totalDuration(); if (t) seekTo(t * (+e.key) / 10); }
  }
}

/* ===================== icon size (small / medium / large) ===================== */
const ICON_SIZES = ["small", "medium", "large"];
function applyIconSize(size) {
  if (!ICON_SIZES.includes(size)) size = "medium";
  document.body.dataset.size = size;
  $$("#sizeToggle .size-btn").forEach(b => b.classList.toggle("active", b.dataset.size === size));
  try { localStorage.setItem("kadmu_icon_size", size); } catch {}
}
function initIconSize() {
  let size = "medium";
  try { size = localStorage.getItem("kadmu_icon_size") || "medium"; } catch {}
  $$("#sizeToggle .size-btn").forEach(b => b.onclick = () => applyIconSize(b.dataset.size));
  applyIconSize(size);
}

/* ===================== theme (light / dark / auto)  (#7) ===================== */
// pref: "auto" follows the OS (no data-theme attr, CSS handles it); "light"/"dark"
// force a choice. The button cycles auto → dark → light → auto.
const THEME_ORDER = ["auto", "dark", "light"];
const THEME_ICON = { auto: "themeAuto", dark: "moon", light: "sun" };
const THEME_LABEL = { auto: "Theme: match system", dark: "Theme: dark", light: "Theme: light" };
let themePref = "auto";
function applyTheme(pref) {
  themePref = THEME_ORDER.includes(pref) ? pref : "auto";
  if (themePref === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", themePref);
  const btn = $("#themeBtn");
  if (btn) { btn.innerHTML = ICON[THEME_ICON[themePref]] || ""; btn.title = THEME_LABEL[themePref]; }
  try { localStorage.setItem("kadmu_theme", themePref); } catch {}
}
function initTheme() {
  let pref = "auto";
  try { pref = localStorage.getItem("kadmu_theme") || "auto"; } catch {}
  applyTheme(pref);
  const btn = $("#themeBtn");
  if (btn) btn.onclick = () => applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(themePref) + 1) % THEME_ORDER.length]);
}

/* ===================== library toolbar: sort / filter / view  (#11) ============ */
function applyView(view) {
  state.view = view === "list" ? "list" : "grid";
  document.body.classList.toggle("view-list", state.view === "list");
  $$("#viewToggle .view-btn").forEach(b => b.classList.toggle("active", b.dataset.view === state.view));
  try { localStorage.setItem("kadmu_view", state.view); } catch {}
}
// Show the toolbar when the current folder has things to sort; reflect current state.
function updateToolbar(data) {
  const bar = $("#libToolbar");
  if (!bar) return;
  const hasItems = !!((data.folders || []).length || (data.videos || []).length);
  bar.classList.toggle("hidden", !hasItems);
  const sel = $("#sortSelect"); if (sel) sel.value = state.sort;
  $$("#filterChips .chip").forEach(c => c.classList.toggle("active", c.dataset.filter === state.filter));
}
function reRenderLibrary() {
  if (state.searchActive || !state.data) return;
  renderFolders(state.data);
  renderVideos(state.data);
}
function initToolbar() {
  try { state.sort = localStorage.getItem("kadmu_sort") || "name"; } catch {}
  try { state.filter = localStorage.getItem("kadmu_filter") || "all"; } catch {}
  let view = "grid";
  try { view = localStorage.getItem("kadmu_view") || "grid"; } catch {}
  applyView(view);
  const sel = $("#sortSelect");
  if (sel) {
    sel.value = state.sort;
    sel.onchange = () => { state.sort = sel.value; try { localStorage.setItem("kadmu_sort", state.sort); } catch {} reRenderLibrary(); };
  }
  $$("#filterChips .chip").forEach(c => c.onclick = () => {
    state.filter = c.dataset.filter;
    try { localStorage.setItem("kadmu_filter", state.filter); } catch {}
    $$("#filterChips .chip").forEach(x => x.classList.toggle("active", x === c));
    reRenderLibrary();
  });
  $$("#viewToggle .view-btn").forEach(b => b.onclick = () => applyView(b.dataset.view));
}

/* ===================== boot ===================== */
async function refreshSession() {
  try { state.session = await api("/api/session"); } catch {}
}
function applySession() {
  const s = state.session;
  document.body.classList.toggle("readonly", !s.canManage);
}
async function boot() {
  await refreshSession();
  if (state.session.authRequired && !state.session.authed) { showLogin(); return; }
  hideLogin();
  applySession();
  try { state.ccLang = localStorage.getItem("kadmu_cc") || "off"; } catch {}
  try {
    state.ccSize = localStorage.getItem("kadmu_cc_size") || "md";
    state.ccColor = localStorage.getItem("kadmu_cc_color") || "white";
    state.ccBg = localStorage.getItem("kadmu_cc_bg") || "soft";
  } catch {}
  applyCueStyle();
  try { state.keyHud = localStorage.getItem("kadmu_keyhud") !== "0"; } catch {}   // default on
  await loadProfiles();          // opt-in viewer profiles (shows the chooser on first run)
  try { state.mylist = new Set((await api("/api/mylist")).map(i => i.path)); } catch {}
  // Learn the configured roots so URLs can read as folder names (and resolve back).
  try { state.roots = ((await api("/api/library")).folders || []).map(f => ({ name: f.name, path: f.path })); }
  catch { state.roots = []; }

  const r = parseHash();
  const routePath = pathForRoute(r);           // history.state (reload) or the resolved trail
  if (r.view === "watch" && routePath) {
    if (history.state && history.state.kadmu) {
      await renderFromRoute();                 // reload of a file URL: state already in place
    } else {
      // Fresh deep link to a file: seed the folder underneath so Back returns to it, then open.
      const folder = parentDir(routePath);
      history.replaceState({ kadmu: true, view: "browse", path: folder }, "", hashFor("browse", folder));
      history.pushState({ kadmu: true, view: "watch", path: routePath }, "", hashFor("watch", routePath));
      await renderFromRoute();
    }
  } else if (r.view === "browse" && routePath) {
    navMode = "replace";                       // tag this entry without stacking a duplicate
    await loadLibrary(routePath, { silent: true });
  } else {
    let last = null;
    try { last = localStorage.getItem("kadmu_last_path"); } catch {}
    navMode = "replace";
    await loadLibrary(last || null, { silent: true });
  }
}
(async function init() {
  applyIcons();
  initTheme();
  initIconSize();
  initToolbar();
  wire();
  await boot();
})();
