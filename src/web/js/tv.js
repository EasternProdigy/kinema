"use strict";
/* tv.js — 10-foot "TV mode": a bigger interface plus spatial (D-pad / arrow-key)
   navigation, so Kadmu is usable from the couch with a TV remote. Pure client-side,
   classic script sharing the global scope. Off by default — opt in from Settings,
   the `V` key, or boot the server with --tv to default it on.

   How it works: in TV mode, arrow keys move focus to the nearest card/button in that
   direction (geometry-based), Enter activates it. Inside the player we step aside so
   the existing arrow shortcuts (seek / volume) keep working; Enter there toggles play. */

const TV_KEY = "kadmu_tv";
// Everything a remote should be able to land on: native controls + the app's clickable cards.
const TV_FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select, ' +
  '[tabindex]:not([tabindex="-1"]), ' +
  '.title-card, .video-card, .folder-card, .ep-row, .collection-card, .profile-card';

function tvEnabled() { return !!state.tvMode; }

// localStorage wins; otherwise the server hint (--tv / KADMU_TV) sets the initial default.
function initTvMode() {
  let on = null;
  try { const v = localStorage.getItem(TV_KEY); if (v != null) on = v === "1"; } catch {}
  if (on == null) on = !!(state.session && state.session.tv);
  state.tvMode = on;
  applyTvMode(false);
}
function applyTvMode(persist) {
  document.body.classList.toggle("tv-mode", !!state.tvMode);
  const t = $("#tvModeToggle"); if (t) t.checked = !!state.tvMode;
  if (persist) { try { localStorage.setItem(TV_KEY, state.tvMode ? "1" : "0"); } catch {} }
  if (state.tvMode) setTimeout(focusFirst, 60);
}
function toggleTvMode(on) {
  state.tvMode = (on == null) ? !state.tvMode : !!on;
  applyTvMode(true);
  if (typeof toast === "function") toast(state.tvMode ? "TV mode on" : "TV mode off", "ok");
}

// On-screen, sized, and not inside a hidden subtree.
function tvVisible(elm) {
  if (!elm || elm.closest(".hidden")) return false;
  const r = elm.getBoundingClientRect();
  if (r.width < 4 || r.height < 4) return false;
  if (r.bottom < -2 || r.top > window.innerHeight + 2) return false;
  if (r.right < -2 || r.left > window.innerWidth + 2) return false;
  return elm.offsetParent !== null || getComputedStyle(elm).position === "fixed";
}
function tvCandidates() {
  const out = [];
  document.querySelectorAll(TV_FOCUSABLE).forEach(elm => {
    if (!tvVisible(elm)) return;
    if (!elm.hasAttribute("tabindex")) elm.tabIndex = 0;   // make clickable cards focusable
    out.push(elm);
  });
  return out;
}
const _center = r => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 });

// Move focus to the nearest candidate in `dir`. Scores by distance along the travel
// axis plus a heavy penalty for cross-axis misalignment, so focus tracks in a line.
function moveFocus(dir) {
  const cands = tvCandidates();
  if (!cands.length) return;
  const cur = (document.activeElement && cands.indexOf(document.activeElement) !== -1)
    ? document.activeElement : null;
  if (!cur) { cands[0].focus(); cands[0].scrollIntoView({ block: "center" }); return; }
  const cc = _center(cur.getBoundingClientRect());
  let best = null, bestScore = Infinity;
  for (const e of cands) {
    if (e === cur) continue;
    const c = _center(e.getBoundingClientRect());
    const dx = c.x - cc.x, dy = c.y - cc.y;
    let primary, cross;
    if (dir === "left")       { if (dx > -4) continue; primary = -dx; cross = Math.abs(dy); }
    else if (dir === "right") { if (dx <  4) continue; primary =  dx; cross = Math.abs(dy); }
    else if (dir === "up")    { if (dy > -4) continue; primary = -dy; cross = Math.abs(dx); }
    else                      { if (dy <  4) continue; primary =  dy; cross = Math.abs(dx); }
    const score = primary + cross * 2;
    if (score < bestScore) { bestScore = score; best = e; }
  }
  if (best) { best.focus(); best.scrollIntoView({ block: "nearest", inline: "nearest" }); }
}
// Land on a primary content card (or the search box) when entering a view.
function focusFirst() {
  if (!tvEnabled()) return;
  const cands = tvCandidates();
  const pref = cands.find(e => e.matches(".title-card, .video-card, .folder-card, .ep-row"))
    || cands.find(e => e.id === "searchInput") || cands[0];
  if (pref) pref.focus();
}

const _isCard = a => a && (a.tagName === "BUTTON" || a.tagName === "A" ||
  a.classList.contains("title-card") || a.classList.contains("video-card") ||
  a.classList.contains("folder-card") || a.classList.contains("ep-row") ||
  a.classList.contains("collection-card") || a.classList.contains("profile-card"));

function onTvKey(e) {
  if (!tvEnabled() || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
  const playerOpen = !$("#playerOverlay").classList.contains("hidden");
  if (e.key === "Enter") {
    const a = document.activeElement;
    if (_isCard(a) && a !== document.body) {
      e.preventDefault(); a.click();
      // Activating a card often swaps the view out from under focus — re-seat it.
      setTimeout(() => { if (!document.activeElement || document.activeElement === document.body) focusFirst(); }, 130);
      return;
    }
    if (playerOpen && typeof togglePlay === "function") { e.preventDefault(); togglePlay(); }
    return;
  }
  if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
    if (playerOpen) return;   // in the player, arrows seek / change volume (keys.js owns them)
    e.preventDefault();
    moveFocus(e.key === "ArrowLeft" ? "left" : e.key === "ArrowRight" ? "right"
            : e.key === "ArrowUp" ? "up" : "down");
  }
}
document.addEventListener("keydown", onTvKey);
