"use strict";
/* playerui.js — sleep timer, on-screen UI/gestures, Picture-in-Picture, fullscreen
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

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

