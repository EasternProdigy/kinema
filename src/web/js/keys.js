"use strict";
/* keys.js — keyboard shortcuts: KEYBINDS, the reference modal, onKey
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

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
    { keys: ["B"], desc: "A-B loop (set A, then B, then clear)" },
  ]},
  { group: "Volume", items: [
    { keys: ["↑", "↓"], desc: "Volume up / down" },
    { keys: ["M"], desc: "Mute / unmute" },
  ]},
  { group: "Audio & subtitles", items: [
    { keys: ["A"], desc: "Cycle audio track" },
    { keys: ["C"], desc: "Cycle subtitles / captions" },
    { keys: ["G", "H"], desc: "Subtitle sync earlier / later" },
    { keys: ["T"], desc: "Tune — video filters & audio EQ/boost" },
  ]},
  { group: "Chapters & frames", items: [
    { keys: [",", "."], desc: "Previous / next chapter (frame-step when paused)" },
  ]},
  { group: "Episodes & player", items: [
    { keys: ["Shift", "N"], desc: "Next episode" },
    { keys: ["Shift", "P"], desc: "Previous episode" },
    { keys: ["E"], desc: "Toggle the episodes panel" },
    { keys: ["F"], desc: "Fullscreen" },
    { keys: ["P"], desc: "Picture-in-Picture" },
    { keys: ["I"], desc: "Save the current frame (screenshot)" },
    { keys: ["S"], desc: "Sleep timer (after this episode)" },
    { keys: ["Esc"], desc: "Close the player" },
  ]},
  { group: "Library & general", items: [
    { keys: ["Ctrl/⌘", "K"], desc: "Command palette" },
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
  "ArrowDown", "m", "a", "c", "e", "f", "p", "s", "t", "b", "i", "N", "P", "[", "]", ".", ",", "Home", "End"]);
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
  // Command palette: Ctrl/⌘+K from anywhere (even while a field is focused).
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault(); togglePalette(); return;
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
    if (e.key === "Escape") { closeDialog(); closeSettings(); }
    return;
  }
  const playerOpen = !$("#playerOverlay").classList.contains("hidden");
  if (e.key === "Escape") {
    if (!$("#paletteOverlay")?.classList.contains("hidden")) return closePalette();
    if (!$("#shortcutsModal").classList.contains("hidden")) return closeShortcuts();
    if (!$("#ctxMenu").classList.contains("hidden")) return closeContextMenu();
    if (!$("#userMenu")?.classList.contains("hidden")) return hideUserMenu();
    if (!$("#dialog").classList.contains("hidden")) return closeDialog();
    if (!$("#settingsModal").classList.contains("hidden")) return closeSettings();
    if (state.profilesEnabled && !$("#profileOverlay").classList.contains("hidden")) return hideProfileChooser();
    if (playerOpen && !$("#tuneSheet")?.classList.contains("hidden")) return closeTune();
    if (playerOpen && !$("#partyPanel")?.classList.contains("hidden")) return closeParty();
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
    // paused: nudge a single frame (YouTube-style); playing: jump chapters
    case ".": video.paused ? frameStep(1) : skipChapter(1); break;
    case ",": video.paused ? frameStep(-1) : skipChapter(-1); break;
    case "t": toggleTune(); break;                                          // tune sheet
    case "b": cycleAbLoop(); break;                                         // A-B loop
    case "i": screenshot(); break;                                          // save a frame
    case "Home": seekTo(0); break;
    case "End": { const t = totalDuration(); if (t) seekTo(t - 5); break; }
    default:
      if (/^[0-9]$/.test(e.key)) { const t = totalDuration(); if (t) seekTo(t * (+e.key) / 10); }
  }
}

