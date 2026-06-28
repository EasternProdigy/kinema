"use strict";
/* player.js — video player, queue panel, next-episode/autoplay, quality/audio/subtitles/chapters/storyboard
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

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
  clearAbLoop();                   // A-B loop is per clip
  hideNextCard();
  syncURL("watch", v.path);        // each file gets its own link; navMode set by the caller
  const fp = loadFilePrefs(v.path);          // per-file memory (audio/sub/speed/sync)
  if (fp && fp.rate) state.rate = fp.rate;   // sticky otherwise; restore the remembered speed
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
    applyRate();
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

/* ---------- per-file memory (remembered audio / subtitle / speed / sync) ----------
   Kept in localStorage so it works in every mode (a bounded LRU map of path ->
   prefs). Restores what you last chose for a clip; saved whenever you change one. */
const FILE_PREFS_KEY = "kadmu_file_prefs";
const FILE_PREFS_MAX = 400;
function _allFilePrefs() {
  try { const d = JSON.parse(localStorage.getItem(FILE_PREFS_KEY) || "{}"); return d && typeof d === "object" ? d : {}; }
  catch { return {}; }
}
function loadFilePrefs(path) { return _allFilePrefs()[path] || null; }
function rememberFilePref(path, patch) {
  if (!path) return;
  try {
    const all = _allFilePrefs();
    const rec = Object.assign({}, all[path], patch, { _t: Date.now() });
    all[path] = rec;
    const keys = Object.keys(all);
    if (keys.length > FILE_PREFS_MAX) {                 // evict oldest by timestamp
      keys.sort((a, b) => (all[a]._t || 0) - (all[b]._t || 0));
      for (const k of keys.slice(0, keys.length - FILE_PREFS_MAX)) delete all[k];
    }
    localStorage.setItem(FILE_PREFS_KEY, JSON.stringify(all));
  } catch {}
}

/* ---------- frame step / A-B loop / screenshot / custom speed ---------- */
const FRAME = 1 / 25;          // we can't read the true fps; ~25fps is a sane nudge
function frameStep(dir) {
  if (!currentVideo) return;
  if (!canSeekNow()) { toast("Frame step needs original quality on a native file", ""); return; }
  video.pause();
  try { video.currentTime = Math.max(0, video.currentTime + dir * FRAME); } catch {}
  showUi();
}
// A-B loop: 1st press sets A, 2nd sets B (loops A→B), 3rd clears.
function cycleAbLoop() {
  const pos = currentPlayPos();
  if (state.abA == null) { state.abA = pos; toast("Loop start set — press again to set end", "ok"); }
  else if (state.abB == null) {
    if (pos <= state.abA + 0.3) { toast("Loop end must be after the start", "err"); }
    else { state.abB = pos; toast("A-B loop on", "ok"); }
  } else { state.abA = state.abB = null; toast("A-B loop cleared", ""); }
  updateAbButton();
}
function clearAbLoop() { state.abA = state.abB = null; updateAbButton(); }
function updateAbButton() {
  const b = $("#abLoopBtn");
  if (b) b.classList.toggle("on", state.abA != null);
  const ticks = $("#chapterTicks");           // reuse the seek-bar tick layer for A/B marks
  $$(".ab-mark", ticks || document).forEach(n => n.remove());
  if (!ticks) return;
  const total = totalDuration();
  if (!total) return;
  const mark = (t, cls) => { const i = el("i", "ab-mark " + cls); i.style.left = Math.min(100, (t / total) * 100) + "%"; ticks.appendChild(i); };
  if (state.abA != null) mark(state.abA, "a");
  if (state.abB != null) mark(state.abB, "b");
}
// Called from updateTime() on every frame: jump back to A once we pass B.
function checkAbLoop() {
  if (state.abA == null || state.abB == null) return;
  if (currentPlayPos() >= state.abB) seekTo(state.abA);
}
function screenshot() {
  if (!currentVideo || !video.videoWidth) { toast("Nothing to capture yet", ""); return; }
  try {
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    c.toBlob(b => {
      if (!b) { toast("Couldn't capture this frame", "err"); return; }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = `${dispName(currentVideo)} @ ${fmtTime(currentPlayPos()).replace(/:/g, "·")}.png`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast("Frame saved", "ok");
    }, "image/png");
  } catch { toast("Screenshot blocked by the browser", "err"); }
}
// Free-typed speed (the speed menu's custom box). Clamped to a sane 0.1–4×.
function setSpeedCustom(val) {
  let r = parseFloat(val);
  if (!isFinite(r)) return;
  r = Math.max(0.1, Math.min(4, Math.round(r * 100) / 100));
  setSpeed(r);
}

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
  video.onloadedmetadata = () => { applyRate(); applyCaption(pickCaptionIndex()); updateTime(); };
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
  checkAbLoop();
}
function setSpeed(rate) {
  state.rate = rate;
  video.playbackRate = rate;
  $("#speedBtn").textContent = rate + "×";
  $$("#speedMenu button[data-rate]").forEach(b => b.classList.toggle("active", +b.dataset.rate === rate));
  const ci = $("#speedCustom"); if (ci && document.activeElement !== ci) ci.value = rate;
  $("#speedMenu").classList.add("hidden");
  if (currentVideo) rememberFilePref(currentVideo.path, { rate });
}
// Apply state.rate to the element and reflect it on the speed button (used on
// every (re)load so a remembered/sticky speed survives source swaps and seeks).
function applyRate() {
  applyRate();
  const b = $("#speedBtn"); if (b) b.textContent = state.rate + "×";
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
    // Per-file memory: restore a remembered, still-valid audio track for this clip.
    const fp = loadFilePrefs(v.path);
    if (fp && fp.audio && (state.audios || []).some(a => a.ord === fp.audio)) setAudio(fp.audio);
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
      applyRate();
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
  rememberFilePref(currentVideo.path, { audio: ord });   // per-file memory
  buildAudioMenu();
  if (canSeekNow()) {
    state.qOffset = 0;
    video.src = `/api/stream?path=${enc(currentVideo.path)}${audioQuery()}`;
    video.load();
    video.onloadedmetadata = () => {
      try { if (pos > 0) video.currentTime = pos; } catch {}
      applyRate();
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
  pushPrefs();
}

// In accounts mode, mirror display prefs to the server so they follow you between
// devices. A no-op without accounts (the browser's localStorage is the store).
function pushPrefs() {
  if (!state.session || !state.session.accounts || !state.session.user) return;
  const prefs = { ccSize: state.ccSize, ccColor: state.ccColor, ccBg: state.ccBg,
                  keyHud: state.keyHud ? 1 : 0 };
  api("/api/prefs", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prefs }),
  }).catch(() => {});
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
  if (currentVideo) rememberFilePref(currentVideo.path, { subOffset: state.subOffset });   // per-file memory
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
  // Per-file memory: restore the remembered caption choice + sync offset for this clip.
  const fp = loadFilePrefs(v.path);
  if (fp && fp.ccLang) state.ccLang = fp.ccLang;
  for (const s of state.subs) {
    const tr = document.createElement("track");
    tr.kind = "subtitles"; tr.label = s.label; tr.srclang = s.lang || "und"; tr.src = s.url;
    tr.addEventListener("load", applyCueOffset);   // cues exist now → re-apply any sync offset
    video.appendChild(tr);
  }
  buildCcMenu();
  applyCaption(pickCaptionIndex());
  if (fp && fp.subOffset) setSubOffset(0, fp.subOffset);
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
  if (currentVideo) rememberFilePref(currentVideo.path, { ccLang: state.ccLang });   // per-file memory
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

