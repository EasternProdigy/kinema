"use strict";
/* onboard.js — the first-run taste picker. On first launch (with the TMDB metadata
   layer on, for an unrestricted viewer who hasn't chosen yet) we ask which genres
   they love, so the discover home + recommendations are good from the very start.
   Saved per-viewer via POST /api/genres. Classic script sharing the global scope. */

let onboardSel = new Set();

// Show the picker automatically on first run (no-op if it isn't the right moment).
async function maybeOnboard() {
  // Pointless without the metadata layer, and blocked for maturity-restricted
  // viewers (discovery is off for them). Never interrupt a deep link / a video.
  if (!state.session || !state.session.tmdb || state.session.kid) return;
  if (state.searchActive || !$("#playerOverlay")?.classList.contains("hidden")) return;
  let prefs = null;
  try { prefs = await api("/api/prefs"); } catch {}
  if (prefs && prefs.onboarded) return;              // already picked (or skipped)
  await openTastePicker(true);
}

// Open the picker on demand (from the discover banner or settings). `firstRun`
// tweaks the copy; either way it saves the same way.
async function openTastePicker(firstRun) {
  let g = null;
  try { g = await api("/api/genres"); } catch {}
  if (!g || !g.enabled || !(g.genres || []).length) {
    if (!firstRun) toast("Genres need the TMDB metadata layer (add a key in Settings).", "err");
    return;
  }
  renderOnboard(g.genres, new Set(g.selected || []), !!firstRun);
}

function renderOnboard(genres, selected, firstRun) {
  const ov = $("#onboardOverlay"), card = $("#onboardCard");
  if (!ov || !card) return;
  onboardSel = new Set(selected || []);
  const chips = genres.map(g =>
    `<button type="button" class="onb-chip${onboardSel.has(g.name) ? " on" : ""}" data-g="${escapeHtml(g.name)}">${escapeHtml(g.name)}</button>`
  ).join("");
  card.innerHTML = `
    <div class="onb-brand">Kadmu</div>
    <h2 class="onb-h">${firstRun ? "What do you love to watch?" : "Update your tastes"}</h2>
    <p class="onb-sub">Pick a few favourites and we'll line up great things to watch — including standout titles you don't have yet. You can change these anytime in Settings.</p>
    <div class="onb-chips" id="onbChips">${chips}</div>
    <div class="onb-actions">
      <button class="btn primary" id="onbGo" type="button">Show me</button>
      <button class="btn ghost" id="onbSkip" type="button">${firstRun ? "Skip for now" : "Cancel"}</button>
    </div>`;
  ov.classList.remove("hidden");
  $("#onbChips").addEventListener("click", (e) => {
    const c = e.target.closest(".onb-chip");
    if (!c) return;
    const g = c.dataset.g;
    if (onboardSel.has(g)) { onboardSel.delete(g); c.classList.remove("on"); }
    else { onboardSel.add(g); c.classList.add("on"); }
    updateOnbGo();
  });
  $("#onbGo").onclick = () => finishOnboard([...onboardSel], firstRun);
  $("#onbSkip").onclick = () => { ov.classList.add("hidden"); if (firstRun) finishOnboard([], true, true); };
  updateOnbGo();
}

function updateOnbGo() {
  const go = $("#onbGo");
  if (!go) return;
  go.textContent = onboardSel.size
    ? `Show me ${onboardSel.size} pick${onboardSel.size === 1 ? "" : "s"}`
    : "Show me what's popular";
}

async function finishOnboard(genres, firstRun, skip) {
  try {
    await api("/api/genres", { method: "POST", body: JSON.stringify({ genres, onboarded: true }) });
  } catch {}
  $("#onboardOverlay")?.classList.add("hidden");
  if (!skip) {
    // Apply the picks immediately wherever discovery is showing (the empty-library
    // home, and the discover rails if the catalog page is up).
    try { if (typeof renderDiscover === "function" && state.discoverShown) await renderDiscover(); } catch {}
    if (genres.length) toast("Tastes saved — your picks are in.", "ok");
  }
}
