"use strict";
/* discover.js — the streaming-style "discover" home shown when the library is empty
   (or has nothing yet): a featured billboard + rails of great titles to GET, pulled
   from TMDB and seeded by the viewer's picked genres. No playback — each card opens
   an info sheet (synopsis + a link to find it). Reuses externalCard / makeRail /
   openDiscover from catalog.js. Classic script sharing the global scope. */

// Render the discover surface into #discoverSection. Returns true if it showed
// something (so the caller can suppress the bare "add a folder" empty state).
//   compact=false → the full empty-library home: intro banner + hero + every rail.
//   compact=true  → "more to explore" rails beneath an owned catalog: no intro/hero,
//                    filtered to the active Home tab's kind, capped, and re-rendered on
//                    tab switches from the cached payload (state.discover).
const COMPACT_DISCOVER_ROWS = 5;
async function renderDiscover(compact) {
  const sec = $("#discoverSection");
  if (!sec) return false;
  let data = state.discover;
  if (!data) { try { data = await api("/api/discover"); } catch {} }
  const rows = (data && data.rows) || [];
  if (!data || !data.enabled || !data.ok || !rows.length) {
    sec.classList.add("hidden");
    sec.innerHTML = "";
    return false;
  }
  state.discover = data;
  sec.innerHTML = "";
  sec.classList.toggle("compact", !!compact);

  if (!compact) {
    sec.appendChild(discoverIntro(data));
    // A featured billboard: the most popular pick that has a cinematic backdrop.
    const all = rows.flatMap(r => r.items || []);
    const hero = all.filter(it => it.backdrop).sort((a, b) => (b.popularity || 0) - (a.popularity || 0))[0];
    if (hero) sec.appendChild(discoverHero(hero));
  } else {
    sec.appendChild(el("h2", "discover-rails-head", compactDiscoverHeading()));
  }

  const kind = compact ? discoverKindFilter() : null;   // movie / show / null(all)
  let shown = 0;
  for (const row of rows) {
    let items = row.items || [];
    if (kind) items = items.filter(it => it.kind === kind);
    const nodes = items.map(it => externalCard(it));
    if (nodes.length) { sec.appendChild(makeRail(row.title, nodes)); shown++; }
    if (compact && shown >= COMPACT_DISCOVER_ROWS) break;   // keep the home from running on forever
  }
  sec.classList.toggle("hidden", shown === 0);
  if (typeof fitRailsSoon === "function") fitRailsSoon();
  return shown > 0;
}

// Compact discovery follows the active Home tab so the Movies / TV Shows tabs are never
// empty even before you own much.
function discoverKindFilter() {
  if (state.homeFilter === "movie") return "movie";
  if (state.homeFilter === "show") return "show";
  return null;
}
function compactDiscoverHeading() {
  if (state.homeFilter === "movie") return "Movies to discover";
  if (state.homeFilter === "show") return "Shows to discover";
  return "More to explore";
}

// The intro banner above the rails: what's going on + the calls to action (add your
// own folders so the library takes over; pick / refine tastes).
function discoverIntro(data) {
  const wrap = el("section", "discover-intro");
  const picks = data.genres || [];
  const lead = picks.length
    ? `Based on your taste for ${picks.slice(0, 3).map(escapeHtml).join(", ")}${picks.length > 3 ? " and more" : ""} — plus what's trending.`
    : `Trending and popular picks to get you started.`;
  wrap.innerHTML = `
    <div class="discover-intro-text">
      <h1>Find something to watch</h1>
      <p class="muted">${lead} Add your own folders and your library takes over.</p>
    </div>
    <div class="discover-intro-actions"></div>`;
  const actions = $(".discover-intro-actions", wrap);
  if (state.session.canManage && typeof addFolder === "function") {
    const add = el("button", "btn primary", `${ICON.folderOpen}<span>Add your folders</span>`);
    add.onclick = addFolder;
    actions.appendChild(add);
  }
  if (state.session.tmdb && !state.session.kid && typeof openTastePicker === "function") {
    const taste = el("button", "btn ghost", `${ICON.tune}<span>${picks.length ? "Edit tastes" : "Pick your tastes"}</span>`);
    taste.onclick = () => openTastePicker(false);
    actions.appendChild(taste);
  }
  return wrap;
}

// A billboard for a not-owned title (mirrors the home hero, minus Play — it can't be
// played, so the one action opens the info sheet).
function discoverHero(it) {
  const sec = el("section", "home-hero discover-hero single");
  const meta = [it.year ? String(it.year) : "", it.kind === "show" ? "Series" : "Movie",
                it.vote ? `★ ${it.vote}` : ""].filter(Boolean).join("  ·  ");
  sec.innerHTML = `
    <div class="hero-slide on">
      <div class="hero-backdrop"><img alt="" /></div>
      <div class="hero-scrim"></div>
      <div class="hero-content">
        <div class="hero-eyebrow">Trending now</div>
        <h1 class="hero-title">${escapeHtml(it.name)}</h1>
        <div class="hero-sub">${escapeHtml(meta)}</div>
        ${it.genres && it.genres.length ? `<div class="hero-chips"><span class="hero-genres">${it.genres.slice(0, 3).map(escapeHtml).join(" · ")}</span></div>` : ""}
        ${it.overview ? `<p class="hero-overview">${escapeHtml(it.overview)}</p>` : ""}
        <div class="hero-actions">
          <button class="btn primary disc-hero-info" type="button"><span data-icon="info"></span> More info</button>
        </div>
      </div>
    </div>`;
  const bd = $(".hero-backdrop", sec), img = $(".hero-backdrop img", sec);
  if (img) { img.onerror = () => bd && bd.classList.add("noimg"); img.src = it.backdrop || it.poster || ""; }
  $(".disc-hero-info", sec)?.addEventListener("click", () => openDiscover(it));
  if (typeof applyIcons === "function") applyIcons(sec);
  return sec;
}
