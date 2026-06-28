"use strict";
/* main.js — event wiring, theme / icon-size / toolbar, boot() and the init entry point
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

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
    pushPrefs();
    if (state.keyHud) flashKey(["✓"]);   // quick confirmation of the new setting
  });
  $("#addRootBtn").onclick = addRoot;
  $("#browseRootBtn").onclick = addFolder;
  { const b = $("#addRemoteBtn"); if (b) b.onclick = openRemoteStorageDialog; }
  { const b = $("#addSourceBtn"); if (b) b.onclick = openAddSourceDialog; }
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
  $("#skipIntro")?.addEventListener("click", skipIntro);
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
  $("#tuneBtn")?.addEventListener("click", toggleTune);
  $("#partyBtn")?.addEventListener("click", toggleParty);
  // free-typed playback speed (the custom box in the speed menu)
  $("#speedCustom")?.addEventListener("change", (e) => setSpeedCustom(e.target.value));
  $("#speedCustom")?.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { setSpeedCustom(e.target.value); e.target.blur(); }
  });

  // top-bar avatar: the account menu in accounts mode, else the viewer-profile chooser
  $("#profileBtn")?.addEventListener("click", () => {
    if (state.session.accounts) toggleUserMenu();
    else showProfileChooser();
  });
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
    resumeAudio();                 // Web Audio contexts start suspended — wake on play
    partyLocal("play");            // mirror to a watch-party room if hosting/joined
    showUi();
  });
  video.addEventListener("pause", () => {
    $("#playPause").innerHTML = ICON.play;
    $("#playerOverlay").classList.add("paused");
    partyLocal("pause");           // mirror to a watch-party room if hosting/joined
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
  video.addEventListener("seeked", () => { hideSpinner(); partyLocal("seek"); });
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
    if (!e.target.closest("#userMenu, #profileBtn")) hideUserMenu();
  });
  $("#settingsModal").addEventListener("click", e => { if (e.target.id === "settingsModal") closeSettings(); });
  $("#dialog").addEventListener("click", e => { if (e.target.id === "dialog") closeDialog(); });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = $("#loginError");
    errEl.textContent = "";
    const pw = $("#loginPassword").value;
    const headers = { "Content-Type": "application/json", "X-Kadmu": "1" };
    try {
      if (!state.session.accounts) {
        const r = await fetch("/api/login", { method: "POST", headers, body: JSON.stringify({ password: pw }) });
        const d = await r.json().catch(() => ({}));
        if (r.ok && d.authed) { $("#loginPassword").value = ""; hideLogin(); await boot(); }
        else errEl.textContent = d.error || "Wrong password.";
        return;
      }
      const username = $("#loginUsername").value.trim();
      const name = $("#loginName").value.trim();
      const register = loginMode === "register";
      const body = register ? { username, password: pw, name } : { username, password: pw };
      const r = await fetch(register ? "/api/register" : "/api/login",
                            { method: "POST", headers, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.authed) {
        $("#loginPassword").value = ""; $("#loginName").value = "";
        loginMode = "login";
        hideLogin();
        await boot();
      } else errEl.textContent = d.error || "Could not sign in.";
    } catch { errEl.textContent = "Could not reach the server."; }
  });
  $("#loginToggle")?.addEventListener("click",
    () => setLoginMode(loginMode === "register" ? "login" : "register"));

  // command palette (Ctrl/⌘+K)
  const pInput = $("#paletteInput");
  if (pInput) {
    let pTimer = null;
    pInput.addEventListener("input", () => {
      clearTimeout(pTimer); const q = pInput.value; pTimer = setTimeout(() => onPaletteInput(q), 90);
    });
    pInput.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "ArrowDown") { e.preventDefault(); setPaletteActive(pstate.active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setPaletteActive(pstate.active - 1); }
      else if (e.key === "Enter") { e.preventDefault(); runPalette(); }
      else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
    });
  }
  $("#paletteOverlay")?.addEventListener("click", (e) => { if (e.target.id === "paletteOverlay") closePalette(); });

  document.addEventListener("keydown", onKey);
  // Back / Forward (and pasting a #/… link into the bar) replay the route.
  window.addEventListener("popstate", renderFromRoute);
  window.addEventListener("hashchange", renderFromRoute);
  const onUnload = () => { unloading = true; saveProgress(); };
  window.addEventListener("pagehide", onUnload);
  window.addEventListener("beforeunload", onUnload);

  wireDragDrop();
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
  // The catalog home (Shows/Movies grids) has its own layout — no sort/filter bar there.
  const catalogHome = data.isRoot && !state.browseFiles && state.catalogHasItems;
  const hasItems = !catalogHome && !!((data.folders || []).length || (data.videos || []).length);
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
  if (typeof applyCloud === "function") applyCloud();   // cloud-attach entitlement (Phase 4a)
}
async function boot() {
  await refreshSession();
  // A cloud-attached instance with an inactive subscription shows the billing notice
  // ahead of the login screen (you can still sign in to reach Manage billing).
  if (state.session.cloud && state.session.entitlement && !state.session.entitlement.active) {
    applyCloud(); return;
  }
  if (state.session.authRequired && !state.session.authed) { showLogin(); return; }
  hideLogin();
  applySession();
  try { state.ccLang = localStorage.getItem("kadmu_cc") || "off"; } catch {}
  try {
    state.ccSize = localStorage.getItem("kadmu_cc_size") || "md";
    state.ccColor = localStorage.getItem("kadmu_cc_color") || "white";
    state.ccBg = localStorage.getItem("kadmu_cc_bg") || "soft";
  } catch {}
  try { state.keyHud = localStorage.getItem("kadmu_keyhud") !== "0"; } catch {}   // default on
  if (state.session.accounts) {
    // accounts mode: identity-scoped prefs that follow the user across devices
    loadAccountUi();
    try {
      const p = await api("/api/prefs");
      if (p && typeof p === "object") {
        if (p.ccSize) state.ccSize = p.ccSize;
        if (p.ccColor) state.ccColor = p.ccColor;
        if (p.ccBg) state.ccBg = p.ccBg;
        if (p.keyHud != null) state.keyHud = !!Number(p.keyHud);
      }
    } catch {}
  } else {
    await loadProfiles();          // opt-in viewer profiles (shows the chooser on first run)
  }
  applyCueStyle();
  try { state.mylist = new Set((await api("/api/mylist")).map(i => i.path)); } catch {}
  // Learn the configured roots so URLs can read as folder names (and resolve back).
  try { state.roots = ((await api("/api/library")).folders || []).map(f => ({ name: f.name, path: f.path })); }
  catch { state.roots = []; }

  // Auto-join a watch party from a shared invite link (#party=CODE).
  const pm = location.hash.match(/party=([A-Za-z0-9]{4})/i);
  if (pm) {
    try { history.replaceState(history.state, "", location.pathname + location.search); } catch {}
    setTimeout(() => joinParty(pm[1]), 400);
  }

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
  } else if (r.view === "title" && routePath) {
    navMode = "replace";                       // deep link / reload straight onto a show or movie
    await openTitle(routePath, { silent: true });
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
  // PWA: register the offline-shell service worker (best effort; HTTPS or localhost only).
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  await boot();
})();
