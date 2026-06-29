"use strict";
/* state.js — the shared state object + lazy-thumbnail IntersectionObserver
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== state ===================== */
const state = {
  path: null,
  data: null,
  roots: [],              // [{name, path}] configured library roots — lets URLs read as folder names
  progress: {},
  session: { authRequired: false, authed: true, readonly: false, canManage: true, canBrowse: true, ffmpeg: false, lan: false, canToggleLan: false, urls: [], accounts: false, user: null, role: null, cloud: false, entitlement: null },
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
  deinterlace: false,     // yadif deinterlace on (Tune toggle) — forces a live ffmpeg pass
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
  abA: null,              // A-B loop: loop start (seconds), or null
  abB: null,              // A-B loop: loop end (seconds), or null
  audios: [],             // audio tracks for the playing video
  chapters: [],           // [{start, end, title}] chapter markers for the playing video
  storyboard: null,       // { ok, cols, rows, count, interval, duration, url } scrub-preview sprite
  storyboardFor: null,    // path the storyboard belongs to (guards async loads)
  sleep: { mode: "off", deadline: 0, episodes: 0, timer: null, tick: null }, // sleep timer
  profilesEnabled: false, // server has --profiles on
  keyHud: true,           // flash the pressed shortcut in the center of the screen
  browseFiles: false,     // root view: false = Shows/Movies catalog, true = classic folder browser
  catalogHasItems: false, // the catalog returned at least one show or movie (drives the home layout)
  homeFilter: "all",      // home tab: all | show | movie | mylist  (Netflix-style top nav)
  catalog: null,          // cached {shows, movies} from /api/catalog (re-filtered on tab switch, no refetch)
  reco: null,             // cached /api/recommendations payload
  history: null,          // cached /api/history items
  discover: null,         // cached /api/discover payload (empty-library "what to watch")
  discoverShown: false,   // the discover home is currently rendered (no owned catalog yet)
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

