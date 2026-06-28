"use strict";
/* palette.js — the command palette (Ctrl/⌘+K): one box to run any action or jump
   to anything in the library. Commands are context-aware (player vs. library);
   typing also searches the library (folders + episodes) via /api/search and merges
   the hits in. Subsequence fuzzy-matching ranks both.
   Part of the Kadmu frontend; classic script sharing the global scope. */

const pstate = { open: false, items: [], active: 0, q: "", seq: 0 };

// Context-aware action list. Each: { title, hint, icon, run() }.
function paletteCommands() {
  const playerOpen = !$("#playerOverlay")?.classList.contains("hidden");
  const cmds = [];
  const add = (title, icon, run, hint) => cmds.push({ kind: "cmd", title, icon, run, hint });

  add("Go to library home", ICON.folder, () => loadLibrary(null), "Browse");
  add("Search the library", ICON.search, () => { const i = $("#searchInput"); if (i) { i.focus(); i.select(); } }, "Find");
  add("Open settings", ICON.cog, openSettings, "App");
  add("Keyboard shortcuts", ICON.keyboard, openShortcuts, "Help");
  add("Toggle theme (dark / light / auto)", ICON.themeAuto,
      () => applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(themePref) + 1) % THEME_ORDER.length]), "App");
  add("Refresh", ICON.cog, () => loadLibrary(state.path), "App");

  if (playerOpen) {
    add(video && video.paused ? "Play" : "Pause", ICON.play, togglePlay, "Player");
    add("Next episode", ICON.next, goNext, "Player");
    add("Previous episode", ICON.prev, () => playIndex(state.qIndex - 1), "Player");
    add("Tune — video & audio", ICON.tune, openTune, "Player");
    add("Save a screenshot", ICON.camera, screenshot, "Player");
    add("A-B loop", ICON.loop, cycleAbLoop, "Player");
    add("Toggle fullscreen", ICON.fullscreen, toggleFs, "Player");
    add("Picture-in-Picture", ICON.pip, togglePip, "Player");
    add("Cycle audio track", ICON.audio, cycleAudio, "Player");
    add("Cycle subtitles", ICON.cc, cycleCaption, "Player");
    add("Watch party", ICON.party, openParty, "Player");
    add("Sleep timer (after this episode)", ICON.timer, () => setSleep(state.sleep.mode === "off" ? "ep" : "off"), "Player");
    add("Close the player", ICON.close, closePlayer, "Player");
  }
  return cmds;
}

// subsequence score: every char of q must appear in order; tighter + earlier wins.
function fuzzy(q, text) {
  const t = text.toLowerCase();
  let ti = 0, score = 0, streak = 0, first = -1;
  for (const ch of q) {
    const at = t.indexOf(ch, ti);
    if (at < 0) return -1;
    if (first < 0) first = at;
    streak = (at === ti) ? streak + 2 : 0;
    score += 4 + streak - Math.min(3, at - ti);
    ti = at + 1;
  }
  return score - first * 0.3 - t.length * 0.02;
}

function openPalette() {
  pstate.open = true;
  $("#paletteOverlay")?.classList.remove("hidden");
  const inp = $("#paletteInput");
  if (inp) { inp.value = ""; inp.focus(); }
  pstate.q = "";
  renderPalette([], "");
}
function closePalette() {
  pstate.open = false;
  $("#paletteOverlay")?.classList.add("hidden");
  pstate.items = []; pstate.active = 0;
}
function togglePalette() { pstate.open ? closePalette() : openPalette(); }

async function onPaletteInput(q) {
  pstate.q = q;
  const cmds = paletteCommands();
  let items;
  if (!q.trim()) {
    items = cmds.slice(0, 8);
  } else {
    const ranked = cmds.map(c => ({ ...c, s: fuzzy(q.toLowerCase(), c.title) }))
      .filter(c => c.s >= 0).sort((a, b) => b.s - a.s).slice(0, 6);
    items = ranked;
    // also fold in live library results
    const seq = ++pstate.seq;
    try {
      const data = await api(`/api/search?q=${enc(q)}`);
      if (seq !== pstate.seq || pstate.q !== q) return;          // superseded
      for (const f of (data.folders || []).slice(0, 4)) {
        items.push({ kind: "folder", title: f.name, hint: "Folder", icon: ICON.folder, run: () => loadLibrary(f.path) });
      }
      for (const v of (data.videos || []).slice(0, 6)) {
        items.push({ kind: "video", title: v.display || v.name, hint: "Play", icon: ICON.play, run: () => openPlayer(v) });
      }
    } catch {}
  }
  renderPalette(items, q);
}

function renderPalette(items, q) {
  const list = $("#paletteList");
  if (!list) return;
  pstate.items = items;
  pstate.active = 0;
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("div", "palette-empty", q.trim() ? `No matches for “${escapeHtml(q)}”` : "Type to search…"));
    return;
  }
  items.forEach((it, i) => {
    const row = el("button", "palette-item" + (i === 0 ? " active" : ""));
    row.type = "button";
    row.innerHTML =
      `<span class="palette-item-ic">${it.icon || ICON.play}</span>
       <span class="palette-item-title">${escapeHtml(it.title)}</span>
       ${it.hint ? `<span class="palette-item-hint">${escapeHtml(it.hint)}</span>` : ""}`;
    row.addEventListener("mousemove", () => setPaletteActive(i));
    row.addEventListener("click", () => runPalette(i));
    list.appendChild(row);
  });
}
function setPaletteActive(i) {
  const rows = $$("#paletteList .palette-item");
  if (!rows.length) return;
  pstate.active = (i + rows.length) % rows.length;
  rows.forEach((r, k) => r.classList.toggle("active", k === pstate.active));
  rows[pstate.active]?.scrollIntoView({ block: "nearest" });
}
function runPalette(i) {
  const it = pstate.items[i != null ? i : pstate.active];
  if (!it) return;
  closePalette();
  try { it.run(); } catch (e) { toast("Couldn't run that.", "err"); }
}
