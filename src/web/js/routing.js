"use strict";
/* routing.js — hash-URL client-side routing
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

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
    if (seg === "watch" || seg === "browse" || seg === "title")
      return { view: seg, path: path || null, trail: null };
    return { view: "root", path: null, trail: [] };
  }
  const parts = h.split("/").filter(Boolean).map(decodeURIComponent);
  const view = parts.shift();
  if (view === "watch" || view === "browse" || view === "title")
    return { view, path: null, trail: parts };
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
        } else if (r.view === "title" && path) {
          if (!$("#playerOverlay").classList.contains("hidden")) teardownPlayer();
          await openTitle(path, { silent: true });
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

