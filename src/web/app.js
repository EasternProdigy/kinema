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

async function api(path, opts = {}) {
  opts.headers = { "X-Kinema": "1", ...(opts.headers || {}) };
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
  progress: {},
  session: { authRequired: false, authed: true, readonly: false, canManage: true, canBrowse: true, ffmpeg: false, lan: false, canToggleLan: false, urls: [] },
  organize: false,
  selection: new Map(),
  queue: [],
  qIndex: -1,
  autoNext: true,
  rate: 1,
  quality: "original",    // "original" | target height (240..2160)
  srcHeight: null,        // native height of the playing video (for the ladder)
  srcDuration: null,      // full duration of the source (a transcoded stream only knows its own)
  qOffset: 0,             // seconds into the source where the current transcoded stream began
  panel: null,            // { path, data } currently shown in the side panel
  playerFolderPath: null, // folder the active queue was built from
  pendingNext: null,      // resolved "what plays next" (in-folder episode or next season)
  mylist: new Set(),      // paths pinned to My List (membership for card toggles)
  searchActive: false,    // true while showing search results instead of the library
  subs: [],               // subtitle tracks for the playing video
  ccLang: "off",          // remembered caption choice ("off" | lang | label)
  autoStreak: 0,          // consecutive auto-advances (drives "Still watching?")
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
    if (path) localStorage.setItem("kinema_last_path", path);
    else localStorage.removeItem("kinema_last_path");
  } catch {}
  state.data = data;
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  { const si = $("#searchInput"); if (si) si.value = ""; }   // leaving search → clear the box
  clearSelection();
  renderBreadcrumb(data);
  renderFolders(data);
  renderVideos(data);
  if (data.isRoot) { await renderContinue(); await renderMyList(); }
  else { $("#continueSection").classList.add("hidden"); $("#mylistSection")?.classList.add("hidden"); }
  renderEmpty(data);
  window.scrollTo(0, 0);
}

/* ===================== search (type to find shows & episodes) ===================== */
let searchTimer = null;
function onSearchInput(e) {
  const q = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(q), 250);
}
async function runSearch(q) {
  q = (q || "").trim();
  if (!q) { exitSearch(); return; }
  let data;
  try { data = await api(`/api/search?q=${enc(q)}`); } catch (e) { toast(e.message, "err"); return; }
  state.searchActive = true;
  document.body.classList.add("searching-mode");
  clearSelection();
  $("#continueSection").classList.add("hidden");
  $("#mylistSection")?.classList.add("hidden");

  const bc = $("#breadcrumb"); bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => { const i = $("#searchInput"); if (i) i.value = ""; exitSearch(); };
  bc.appendChild(home);
  bc.appendChild(el("span", "sep", "›"));
  bc.appendChild(el("span", "crumb current", `Search: “${escapeHtml(q)}”`));

  renderFolders({ folders: data.folders, isRoot: false });
  renderVideos({ videos: data.videos });
  if (data.folders.length) $("#foldersTitle").textContent = "Folders";
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
     <div class="folder-ic">${ICON.folder}</div>
     <div class="folder-meta">
       <div class="folder-name">${escapeHtml(f.name)}</div>
       <div class="folder-sub">${meta}${watched && meta ? " · " : ""}${wtag}</div>
     </div>
     ${myListBtn(f.path)}`;
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
  const folders = data.folders || [];
  if (!folders.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("#foldersTitle").textContent = data.isRoot ? "Library folders" : "Folders";
  for (const f of folders) grid.appendChild(folderCard(f));
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
  state.queue = vids.filter(v => v.playable);
  if (!vids.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const nWatched = vids.filter(v => {
    const p = state.progress[v.path];
    return p && p.duration && p.position / p.duration >= 0.95;
  }).length;
  $("#videosTitle").textContent = `Videos · ${vids.length}` + (nWatched ? ` · ${nWatched} watched` : "");
  for (const v of vids) grid.appendChild(videoCard(v));
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
    grid.appendChild(videoCard(v, { position: v.position }));
  }
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
    `<p>Move <b>${items.length}</b> item(s) to the library's <code>.kinema-trash</code> folder?</p>
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
      : `Localhost only. Restart Kinema with <code>--lan</code> to watch from your phone or TV on the same Wi-Fi.`));
  } else {
    const card = el("div", "url-qr");
    let svg = "";
    try { if (typeof KinemaQR !== "undefined") svg = KinemaQR.svg(shareUrl); } catch { svg = ""; }
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
    statTile("info", "Version", `Kinema ${ver}`, ""),
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
  hideNextCard();
  resetQuality(v);                 // back to native quality; learn its resolution
  setupSubs(v);                    // discover & attach sidecar captions
  $("#playerTitle").textContent = dispName(v);
  document.title = dispName(v) + " · Kinema";
  video.src = `/api/stream?path=${enc(v.path)}`;
  video.load();

  const resume = state.progress[v.path];
  video.onloadedmetadata = () => {
    if (resume && resume.position > 5 && resume.duration && resume.position < resume.duration * 0.97) {
      video.currentTime = resume.position;
    }
    video.playbackRate = state.rate;
    updateTime();
  };
  // start playing; if the browser blocks autoplay, surface the center play button
  video.play().then(() => maybeCoachPip())
    .catch(() => { if (video.paused) $("#playerOverlay").classList.add("paused"); });
}

async function openPlayer(v) {
  state.autoStreak = 0;            // a fresh, user-initiated session
  const ov = $("#playerOverlay");
  ov.classList.remove("hidden", "idle", "nextup", "paused");
  // restore the user's last panel preference
  let collapsed = false;
  try { collapsed = localStorage.getItem("kinema_panel_collapsed") === "1"; } catch {}
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

function closePlayer() {
  saveProgress(true);
  hideNextCard();
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("#playerOverlay").classList.add("hidden");
  $("#playerOverlay").classList.remove("paused", "nextup");
  document.title = "Kinema";
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
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
  try { localStorage.setItem("kinema_panel_collapsed", collapsed ? "1" : "0"); } catch {}
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
let nextTimer = null, nextInterval = null;
function clearNextTimers() { clearTimeout(nextTimer); clearInterval(nextInterval); nextTimer = nextInterval = null; }
function hideNextCard() {
  clearNextTimers();
  state.pendingNext = null;
  $("#nextCard").classList.remove("ask");
  $("#nextCard").classList.add("hidden");
  $("#playerOverlay").classList.remove("nextup");
}
// the countdown firing on its own — this is what accrues toward "still watching?"
function autoAdvance() { state.autoStreak++; playNext(); }
function playNext() {
  const n = state.pendingNext;
  clearNextTimers(); hideNextCard();              // hideNextCard clears pendingNext; n is already captured
  if (n) playResolved(n);
  else playIndex(state.qIndex + 1);               // fallback (shouldn't happen)
}
// user clicked Play-now / Continue — fresh attention, reset the streak
function confirmNext() { state.autoStreak = 0; playNext(); }
async function showNextCard() {
  const forVideo = currentVideo;
  const nxt = await resolveNext();
  // user moved on / closed the player while we were resolving
  if (currentVideo !== forVideo || $("#playerOverlay").classList.contains("hidden")) return;
  if (!nxt || !nxt.video) return;                 // nothing after this — let playback end
  state.pendingNext = nxt;
  const nv = nxt.video;
  const crossing = !nxt.inFolder;
  const seasonTag = crossing && nxt.season ? `${nxt.season} · ` : "";
  const ask = state.autoNext && state.autoStreak >= STILL_WATCHING_AFTER;   // pause autoplay, check in
  $("#nextThumb").src = `/api/thumb?path=${enc(nv.path)}`;
  $("#nextTitle").textContent = dispName(nv);
  const lbl = $("#nextCard .next-label");
  if (lbl) lbl.textContent = ask ? "Still watching?" : (crossing ? "Next season" : "Up next");
  const playBtn = $("#nextPlayBtn");
  if (playBtn && playBtn.lastChild) playBtn.lastChild.textContent = ask ? " I’m still here" : " Play now";
  $("#nextCard").classList.toggle("ask", ask);
  $("#nextCard").classList.remove("hidden");
  $("#playerOverlay").classList.add("nextup");
  clearNextTimers();

  const fill = $("#nextBarFill");
  if (ask) {
    $("#nextSub").textContent = "Autoplay paused — still there?";
    fill.style.transition = "none"; fill.style.width = "0%";
  } else if (state.autoNext) {
    let n = 5;
    $("#nextSub").textContent = `${seasonTag}starting in ${n}s`;
    fill.style.transition = "none"; fill.style.width = "100%";
    void fill.offsetWidth;                              // reflow so the transition runs
    fill.style.transition = "width 5s linear"; fill.style.width = "0%";
    nextInterval = setInterval(() => {
      n--; $("#nextSub").textContent = n > 0 ? `${seasonTag}starting in ${n}s` : "Starting…";
    }, 1000);
    nextTimer = setTimeout(autoAdvance, 5000);
  } else {
    $("#nextSub").textContent = crossing ? `${seasonTag}autoplay is off` : "Autoplay is off";
    fill.style.transition = "none"; fill.style.width = "0%";
  }
}

function saveProgress() {
  if (!currentVideo) return;
  const _dur = totalDuration();
  if (!_dur) return;
  const body = JSON.stringify({ path: currentVideo.path, position: currentPlayPos(), duration: _dur });
  // sendBeacon can't set the X-Kinema header, so only use it during real page
  // unload (best effort); every in-app save goes through fetch with the header.
  if (unloading && navigator.sendBeacon) {
    navigator.sendBeacon("/api/progress", new Blob([body], { type: "application/json" }));
  } else {
    fetch("/api/progress", { method: "POST", headers: { "Content-Type": "application/json", "X-Kinema": "1" }, body, keepalive: true }).catch(() => {});
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
// Begin a live, downscaled stream at `pos` seconds into the source.
function startTranscodeAt(height, pos) {
  state.qOffset = Math.max(0, pos || 0);
  video.src = `/api/transcode?path=${enc(currentVideo.path)}&height=${height}&t=${state.qOffset.toFixed(2)}`;
  video.load();
  video.onloadedmetadata = () => { video.playbackRate = state.rate; applyCaption(pickCaptionIndex()); updateTime(); };
}
// Seek to an absolute source position. Transcoded streams aren't byte-seekable,
// so we relaunch the encode at the new offset instead of setting currentTime.
function seekTo(abs) {
  const total = totalDuration();
  abs = Math.max(0, abs);
  if (total) abs = Math.min(abs, total - 0.4);
  if (state.quality === "original") {
    video.currentTime = abs;
  } else {
    const wasPlaying = !video.paused && !video.ended;
    startTranscodeAt(state.quality, abs);
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
  buildQualityMenu();
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
    buildQualityMenu();
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

// Swap to the chosen quality, keeping the current position and play state. The
// cached MP4 has the same duration as the source, so currentTime maps 1:1 — no
// special timeline handling needed.
function setQuality(q) {
  $("#qualityMenu").classList.add("hidden");
  if (q === state.quality || !currentVideo) return;
  const pos = currentPlayPos();
  const playing = !video.paused && !video.ended;
  state.quality = q;
  buildQualityMenu();
  if (q === "original") {
    state.qOffset = 0;
    video.src = `/api/stream?path=${enc(currentVideo.path)}`;
    video.load();
    video.onloadedmetadata = () => {
      try { if (pos > 0) video.currentTime = pos; } catch {}
      video.playbackRate = state.rate;
      applyCaption(pickCaptionIndex());   // tracks survive the source swap; re-show the chosen one
      updateTime();
    };
  } else {
    startTranscodeAt(q, pos);             // streams live -> starts in ~1-2s
  }
  if (playing) video.play().catch(() => {});
}

/* ---------- subtitles / closed captions (sidecar .srt/.vtt) ---------- */
async function setupSubs(v) {
  $$("#video track").forEach(t => t.remove());          // drop the previous clip's tracks
  for (const tt of video.textTracks) tt.mode = "disabled";
  state.subs = [];
  buildCcMenu();
  let subs = [];
  try { subs = await api(`/api/subs?path=${enc(v.path)}`); } catch {}
  if (currentVideo !== v) return;                        // user moved on while we fetched
  state.subs = subs || [];
  for (const s of state.subs) {
    const tr = document.createElement("track");
    tr.kind = "subtitles"; tr.label = s.label; tr.srclang = s.lang || "und"; tr.src = s.url;
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
  $("#ccBtn")?.classList.toggle("on", idx != null);
  $$("#ccMenu [data-cc]").forEach(b => b.classList.toggle("active", (+b.dataset.cc) === (idx == null ? -1 : idx)));
}
function setCaption(idx) {
  $("#ccMenu").classList.add("hidden");
  state.ccLang = (idx == null) ? "off" : (state.subs[idx].lang || state.subs[idx].label);
  try { localStorage.setItem("kinema_cc", state.ccLang); } catch {}
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
  applyCaption(pickCaptionIndex());
}

function showUi() {
  $("#playerOverlay").classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!video.paused) $("#playerOverlay").classList.add("idle"); }, 2600);
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
  if (localStorage.getItem("kinema_pip_seen")) return;
  localStorage.setItem("kinema_pip_seen", "1");
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
  $("#ccBtn")?.addEventListener("click", () => $("#ccMenu")?.classList.toggle("hidden"));

  // search (top bar)
  const searchInput = $("#searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", onSearchInput);
    searchInput.addEventListener("keydown", e => {
      if (e.key === "Escape") { searchInput.value = ""; exitSearch(); searchInput.blur(); }
    });
    $("#searchClear").onclick = () => { searchInput.value = ""; exitSearch(); searchInput.focus(); };
  }

  // seek-bar hover preview (Netflix-style time bubble)
  const seekWrap = $("#seekWrap");
  if (seekWrap) {
    seekWrap.addEventListener("mousemove", e => {
      const total = totalDuration();
      if (!total) return;
      const r = seekWrap.getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const tip = $("#seekTip");
      tip.textContent = fmtTime(pct * total);
      tip.style.left = (pct * 100) + "%";
      seekWrap.classList.add("scrubbing");
    });
    seekWrap.addEventListener("mouseleave", () => seekWrap.classList.remove("scrubbing"));
  }

  $("#seek").addEventListener("input", e => {
    const total = totalDuration();
    if (state.quality === "original" && video.duration) video.currentTime = (e.target.value / 1000) * video.duration;
    if (total) $("#timeCur").textContent = fmtTime((e.target.value / 1000) * total);
    paintRange(e.target);
  });
  $("#seek").addEventListener("change", e => {
    if (state.quality === "original") return;          // handled live above
    const total = totalDuration();
    if (total) seekTo((e.target.value / 1000) * total);
  });
  $("#volume").addEventListener("input", e => {
    video.volume = +e.target.value; video.muted = false;
    localStorage.setItem("kinema_volume", e.target.value);
    paintRange(e.target);
  });

  video.addEventListener("timeupdate", () => {
    updateTime();
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
    showNextCard();
  });
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

  const vol = localStorage.getItem("kinema_volume");
  if (vol != null) { video.volume = +vol; $("#volume").value = vol; }
  paintRange($("#volume"));

  const overlay = $("#playerOverlay");
  overlay.addEventListener("mousemove", showUi);
  $("#playerStage").addEventListener("click", (e) => { if (e.target === video) togglePlay(); });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#speedBtn, #speedMenu")) $("#speedMenu").classList.add("hidden");
    if (!e.target.closest("#qualityBtn, #qualityMenu")) $("#qualityMenu").classList.add("hidden");
    if (!e.target.closest("#ccBtn, #ccMenu")) $("#ccMenu").classList.add("hidden");
  });
  $("#settingsModal").addEventListener("click", e => { if (e.target.id === "settingsModal") closeSettings(); });
  $("#dialog").addEventListener("click", e => { if (e.target.id === "dialog") closeDialog(); });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = $("#loginPassword").value;
    $("#loginError").textContent = "";
    try {
      const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Kinema": "1" }, body: JSON.stringify({ password: pw }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.authed) { hideLogin(); $("#loginPassword").value = ""; await boot(); }
      else { $("#loginError").textContent = d.error || "Wrong password."; }
    } catch { $("#loginError").textContent = "Could not reach the server."; }
  });

  document.addEventListener("keydown", onKey);
  const onUnload = () => { unloading = true; saveProgress(); };
  window.addEventListener("pagehide", onUnload);
  window.addEventListener("beforeunload", onUnload);

  wireDragDrop();
}

function onKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
    if (e.key === "Escape") { closeDialog(); closeSettings(); }
    return;
  }
  const playerOpen = !$("#playerOverlay").classList.contains("hidden");
  if (e.key === "Escape") {
    if (!$("#ctxMenu").classList.contains("hidden")) return closeContextMenu();
    if (!$("#dialog").classList.contains("hidden")) return closeDialog();
    if (!$("#settingsModal").classList.contains("hidden")) return closeSettings();
    if (playerOpen && !$("#nextCard").classList.contains("hidden")) return hideNextCard();
    if (playerOpen) return closePlayer();
    if (state.selection.size) return clearSelection();
  }
  if (!playerOpen) return;
  switch (e.key) {
    case " ": case "k": e.preventDefault(); togglePlay(); break;
    case "ArrowLeft": seekTo(currentPlayPos() - 10); break;
    case "ArrowRight": seekTo(currentPlayPos() + 10); break;
    case "j": seekTo(currentPlayPos() - 30); break;
    case "l": video.loop = !video.loop; $("#loopBtn").classList.toggle("on", video.loop); break;
    case "ArrowUp": e.preventDefault(); video.volume = Math.min(1, video.volume + 0.05); video.muted = false; break;
    case "ArrowDown": e.preventDefault(); video.volume = Math.max(0, video.volume - 0.05); break;
    case "m": video.muted = !video.muted; break;
    case "c": cycleCaption(); break;
    case "f": toggleFs(); break;
    case "p": togglePip(); break;
    case "N": goNext(); break;
    case "P": playIndex(state.qIndex - 1); break;
    case "[": setSpeed(Math.max(0.25, +(video.playbackRate - 0.25).toFixed(2))); break;
    case "]": setSpeed(Math.min(3, +(video.playbackRate + 0.25).toFixed(2))); break;
  }
}

/* ===================== icon size (small / medium / large) ===================== */
const ICON_SIZES = ["small", "medium", "large"];
function applyIconSize(size) {
  if (!ICON_SIZES.includes(size)) size = "medium";
  document.body.dataset.size = size;
  $$("#sizeToggle .size-btn").forEach(b => b.classList.toggle("active", b.dataset.size === size));
  try { localStorage.setItem("kinema_icon_size", size); } catch {}
}
function initIconSize() {
  let size = "medium";
  try { size = localStorage.getItem("kinema_icon_size") || "medium"; } catch {}
  $$("#sizeToggle .size-btn").forEach(b => b.onclick = () => applyIconSize(b.dataset.size));
  applyIconSize(size);
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
  try { state.ccLang = localStorage.getItem("kinema_cc") || "off"; } catch {}
  try { state.mylist = new Set((await api("/api/mylist")).map(i => i.path)); } catch {}
  let last = null;
  try { last = localStorage.getItem("kinema_last_path"); } catch {}
  await loadLibrary(last || null, { silent: true });
}
(async function init() {
  applyIcons();
  initIconSize();
  wire();
  await boot();
})();
