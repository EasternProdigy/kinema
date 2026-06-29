"use strict";
/* catalog.js — the Netflix-style library: a poster grid of Shows and Movies on the
   home surface, and a per-title detail page (backdrop, Resume, thumbs rating, and
   — for shows — a season switcher + episode list). Built entirely from local data
   (/api/catalog, /api/title, /api/rating); reuses openPlayer for playback.
   Part of the Kadmu frontend; classic script sharing the global scope. Loads after
   home.js (uses videoCard helpers) and is called by loadLibrary's root branch. */

/* ===================== home: Shows + Movies poster grids ===================== */
// The active browse-by-genre / filter / sort state for the catalog grids.
const catView = { genre: "", decade: "", sort: "name", watched: "all" };

// Returns true if the catalog rendered any shows or movies (so loadLibrary knows to
// suppress the raw folder/video grids in favour of this view).
async function renderCatalog() {
  const showsSec = $("#showsSection"), moviesSec = $("#moviesSection");
  if (!showsSec || !moviesSec) return false;
  let cat = null;
  try { cat = await api("/api/catalog"); } catch {}
  const shows = (cat && cat.shows) || [];
  const movies = (cat && cat.movies) || [];
  state.catalog = { shows, movies };
  state.catalogHasItems = !!(shows.length || movies.length);
  state.discover = null;                     // refetch discovery once per fresh catalog load

  buildCatalogBar(shows.concat(movies));     // genre + decade options, wired controls
  if (typeof renderHeroCarousel === "function") renderHeroCarousel();  // featured billboard
  applyCatalogView();                        // render the (filtered/sorted) grids
  renderTopTen();                            // "Top 10 in your library" rail
  renderGenreRows();                         // one rail per genre of titles you own
  renderHistory();                           // "Recently watched" rail
  renderRecommendations();                   // taste-based rows above the full grids
  // Always-on discovery: TMDB picks to watch next, beneath the owned catalog — seeded by
  // the library's taste, so it's never an empty home and sharpens as the library grows.
  if (state.catalogHasItems && typeof renderDiscover === "function") renderDiscover(true);
  fitRailsSoon();                            // show scroll arrows only where a rail overflows
  return state.catalogHasItems;
}

// Filter + sort the stored catalog by catView, then paint the Shows/Movies grids.
// The full A-to-Z grids (and the filter bar) are the "TV Shows" / "Movies" tabs —
// on Home and My List the rails do the browsing, so the grids stay hidden.
function applyCatalogView() {
  const showsSec = $("#showsSection"), moviesSec = $("#moviesSection");
  const cat = state.catalog || { shows: [], movies: [] };
  const f = state.homeFilter;
  const showGrid = (f === "show"), movieGrid = (f === "movie");
  const shows = filterSortTitles(cat.shows), movies = filterSortTitles(cat.movies);
  renderTitleGrid(showsSec, $("#showsGrid"), showGrid ? shows : []);
  renderTitleGrid(moviesSec, $("#moviesGrid"), movieGrid ? movies : []);
  const bar = $("#catalogBar");
  const barOn = (showGrid || movieGrid) && state.catalogHasItems;
  if (bar) bar.classList.toggle("hidden", !barOn);
  const count = $("#catCount");
  if (count) {
    const total = (showGrid ? shows.length : 0) + (movieGrid ? movies.length : 0);
    const filtered = catView.genre || catView.decade || catView.watched !== "all";
    count.textContent = (barOn && filtered) ? `${total} result${total === 1 ? "" : "s"}` : "";
  }
}

function filterSortTitles(items) {
  let out = (items || []).filter(it => {
    if (catView.genre && !(it.genres || []).includes(catView.genre)) return false;
    if (catView.decade) {
      const d = it.year ? Math.floor(it.year / 10) * 10 : null;
      if (String(d) !== catView.decade) return false;
    }
    if (catView.watched === "watched" && !isTitleWatched(it)) return false;
    if (catView.watched === "unwatched" && isTitleWatched(it)) return false;
    return true;
  });
  const by = catView.sort;
  out.sort((a, b) => {
    if (by === "rating") return (b.rating || 0) - (a.rating || 0) || natCmp(a.name, b.name);
    if (by === "year") return (b.year || 0) - (a.year || 0) || natCmp(a.name, b.name);
    if (by === "recent") return (b.mtime || 0) - (a.mtime || 0) || natCmp(a.name, b.name);
    return natCmp(a.name, b.name);
  });
  return out;
}

// A title counts as "watched" for the filter: a finished movie, or a show with every
// episode finished.
function isTitleWatched(it) {
  if (it.kind === "show") return it.episodeCount > 0 && (it.watched || 0) >= it.episodeCount;
  return !!it.watched;
}
function natCmp(a, b) { return String(a || "").localeCompare(String(b || ""), undefined, { numeric: true, sensitivity: "base" }); }

/* ===================== Netflix-style home: tabs, rails, category rows ===================== */
// All catalog titles (shows + movies) from the cached /api/catalog payload.
function catalogItems() {
  const c = state.catalog || { shows: [], movies: [] };
  return (c.shows || []).concat(c.movies || []);
}
// Restrict a list to the active home tab's kind (TV Shows / Movies); pass-through on Home.
function homeKind(items) {
  if (state.homeFilter === "show") return (items || []).filter(it => it.kind === "show");
  if (state.homeFilter === "movie") return (items || []).filter(it => it.kind === "movie");
  return items || [];
}

// Build a horizontal scrolling rail (poster row) with a heading + hover scroll arrows.
function makeRail(titleText, nodes) {
  const sec = el("section", "row-section rail-section poster-rail");
  const h = el("h2", "row-title");
  h.textContent = titleText;
  sec.appendChild(h);
  const wrap = el("div", "rail-wrap");
  wrap.innerHTML = `<button class="rail-arrow left" aria-label="Scroll left" type="button"></button>` +
                   `<div class="row-rail"></div>` +
                   `<button class="rail-arrow right" aria-label="Scroll right" type="button"></button>`;
  const rail = $(".row-rail", wrap);
  for (const n of nodes) rail.appendChild(n);
  sec.appendChild(wrap);
  return sec;
}
// After a render, reveal scroll arrows only on rails that actually overflow.
function fitRailsSoon() { requestAnimationFrame(() => $$(".rail-wrap").forEach(fitRail)); }
function fitRail(wrap) {
  const rail = $(".row-rail", wrap);
  if (rail) wrap.classList.toggle("scrollable", rail.scrollWidth > rail.clientWidth + 4);
}

// Play a title in one click: fetch its detail and open the resume target (mid-episode,
// next up, or the first episode/movie). Falls back to the detail page if anything's off.
async function playTitle(id) {
  let d = null;
  try { d = await api(`/api/title?id=${enc(id)}`); } catch { return openTitle(id); }
  if (!d) return openTitle(id);
  const target = d.resume || d.video || null;
  if (!target) return openTitle(id);
  primeProgress(target);
  openPlayer(target);
}

// Browse-by-category rails: one horizontal row per genre of titles you OWN — the
// Netflix "for each category" surface, recommending shows already in your library,
// grouped. Gated so a tiny / un-enriched library doesn't fragment into one-item rows.
const GENRE_MIN_PER_ROW = 4;     // a genre needs at least this many owned titles to be a row
const GENRE_MIN_TITLES = 8;      // ...and the library at least this many overall
const GENRE_MAX_ROWS = 12;       // cap the number of category rails

function renderGenreRows() {
  const sec = $("#genreSection");
  if (!sec) return;
  sec.innerHTML = "";
  if (state.homeFilter === "mylist") { sec.classList.add("hidden"); return; }
  const items = homeKind(catalogItems());
  if (items.length < GENRE_MIN_TITLES) { sec.classList.add("hidden"); return; }
  const buckets = new Map();
  for (const it of items) for (const g of (it.genres || [])) {
    if (!buckets.has(g)) buckets.set(g, []);
    buckets.get(g).push(it);
  }
  const genres = [...buckets.keys()]
    .filter(g => buckets.get(g).length >= GENRE_MIN_PER_ROW)
    .sort((a, b) => buckets.get(b).length - buckets.get(a).length)
    .slice(0, GENRE_MAX_ROWS);
  if (!genres.length) { sec.classList.add("hidden"); return; }
  for (const g of genres) {
    const titles = buckets.get(g).slice()
      .sort((a, b) => (b.rating || 0) - (a.rating || 0)
                   || (b.popularity || 0) - (a.popularity || 0)
                   || natCmp(a.name, b.name))
      .slice(0, 24);
    sec.appendChild(makeRail(g, titles.map(titleCard)));
  }
  sec.classList.remove("hidden");
}

// Switch the home tab (Home / TV Shows / Movies / My List): repaint every home
// section from the cached catalog/feed. The kind filter lives inside each renderer.
function applyHomeFilter(filter) {
  if (filter) state.homeFilter = filter;
  const f = state.homeFilter;
  $$("#homeNav .home-tab").forEach(b => b.classList.toggle("active", b.dataset.home === f));
  if (typeof renderHeroCarousel === "function") renderHeroCarousel();
  if (typeof renderContinue === "function") renderContinue();
  renderRecommendations();
  renderTopTen();
  renderGenreRows();
  renderHistory();
  if (typeof paintRecent === "function") paintRecent();
  if (typeof renderMyList === "function") renderMyList();
  applyCatalogView();
  // Re-render compact discovery so it follows the active tab (movie / show / all).
  if (f !== "mylist" && typeof renderDiscover === "function") renderDiscover(true);
  else { const ds = $("#discoverSection"); if (ds) ds.classList.add("hidden"); }
  fitRailsSoon();
  window.scrollTo(0, 0);
}

// Populate the genre + decade dropdowns from the data and wire the controls (once).
function buildCatalogBar(items) {
  const gSel = $("#catGenre"), dSel = $("#catDecade"), sSel = $("#catSort"), chips = $("#catWatched");
  if (!gSel) return;
  const genres = new Set(), decades = new Set();
  for (const it of items) {
    (it.genres || []).forEach(g => genres.add(g));
    if (it.year) decades.add(Math.floor(it.year / 10) * 10);
  }
  const gList = [...genres].sort();
  gSel.innerHTML = `<option value="">All genres</option>` +
    gList.map(g => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`).join("");
  gSel.value = catView.genre;
  gSel.parentElement && gSel.classList.toggle("hidden", gList.length === 0);
  const dList = [...decades].sort((a, b) => b - a);
  dSel.innerHTML = `<option value="">Any year</option>` +
    dList.map(d => `<option value="${d}">${d}s</option>`).join("");
  dSel.value = catView.decade;
  dSel.classList.toggle("hidden", dList.length === 0);
  if (sSel) sSel.value = catView.sort;

  if (!gSel.dataset.wired) {
    gSel.onchange = () => { catView.genre = gSel.value; applyCatalogView(); };
    dSel.onchange = () => { catView.decade = dSel.value; applyCatalogView(); };
    if (sSel) sSel.onchange = () => { catView.sort = sSel.value; applyCatalogView(); };
    if (chips) chips.onclick = (e) => {
      const b = e.target.closest("[data-w]");
      if (!b) return;
      catView.watched = b.dataset.w;
      $$("[data-w]", chips).forEach(x => x.classList.toggle("active", x === b));
      applyCatalogView();
    };
    gSel.dataset.wired = "1";
  }
}

// "Top 10 in your library" — ranked by TMDB popularity (cached). Hidden when there's
// no popularity signal (TMDB off), so it never shows a meaningless list.
function renderTopTen() {
  const sec = $("#topSection"), rail = $("#topRail");
  if (!sec || !rail) return;
  if (state.homeFilter === "mylist") { sec.classList.add("hidden"); rail.innerHTML = ""; return; }
  const ranked = homeKind(catalogItems()).filter(it => it.popularity)
    .sort((a, b) => (b.popularity || 0) - (a.popularity || 0)).slice(0, 10);
  if (ranked.length < 5) { sec.classList.add("hidden"); rail.innerHTML = ""; return; }
  rail.innerHTML = "";
  ranked.forEach((it, i) => {
    const card = titleCard(it);
    const poster = card.querySelector(".poster");
    if (poster) poster.appendChild(el("span", "top-rank", String(i + 1)));
    rail.appendChild(card);
  });
  sec.classList.remove("hidden");
}

// "Recently watched" — the viewer's finished titles, newest first (from /api/history).
async function renderHistory() {
  const sec = $("#historySection"), rail = $("#historyRail");
  if (!sec || !rail) return;
  if (state.homeFilter !== "all") { sec.classList.add("hidden"); rail.innerHTML = ""; return; }
  let items = [];
  try { items = (await api("/api/history?limit=24")).items || []; } catch { items = []; }
  if (!items.length) { sec.classList.add("hidden"); rail.innerHTML = ""; return; }
  rail.innerHTML = "";
  for (const it of items) {
    const card = titleCard(it);
    const when = it.when ? relTime(it.when) : "";
    card.title = [it.episode ? `Finished ${it.episode}` : "Watched", when].filter(Boolean).join(" · ");
    rail.appendChild(card);
  }
  sec.classList.remove("hidden");
}

// Compact relative time ("3d ago", "2w ago") for the history hover hint.
function relTime(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  if (s < 604800) return Math.floor(s / 86400) + "d ago";
  return Math.floor(s / 604800) + "w ago";
}

// "For you" rows (Keep watching / Top picks / Because you liked X), from /api/recommendations
// — built from the viewer's own thumbs ratings + watch history (+ TMDB genres when enabled).
// Each row reuses titleCard(), so a recommendation tile behaves exactly like a catalog tile.
async function renderRecommendations() {
  const sec = $("#recoSection");
  if (!sec) return;
  sec.innerHTML = "";
  if (state.homeFilter === "mylist") { sec.classList.add("hidden"); return; }
  let data = null;
  try { data = await api("/api/recommendations"); } catch { /* leave hidden */ }
  const rows = (data && data.rows) || [];

  // Build each row as a horizontal rail, dropping items that don't match the active
  // tab's kind (and any row that empties out as a result).
  const railNodes = [];
  for (const row of rows) {
    const items = homeKind(row.items || []);
    if (!items.length) continue;
    const nodes = items.map(it => {
      const card = titleCard(it);
      if (it.why) card.title = `${it.name} — ${it.why}`;   // hover hint on why it's here
      return card;
    });
    const rail = makeRail(row.title, nodes);
    rail.classList.add("reco-row");
    railNodes.push(rail);
  }
  if (!railNodes.length) { sec.classList.add("hidden"); return; }

  // A "how it works / tune it" entry point above the rows — the transparency panel.
  const head = el("div", "reco-head");
  const tune = el("button", "btn ghost reco-tune");
  tune.innerHTML = `${ICON.tune}<span>How recommendations work</span>`;
  tune.onclick = openRecoPanel;
  head.appendChild(tune);
  sec.appendChild(head);
  railNodes.forEach(n => sec.appendChild(n));
  sec.classList.remove("hidden");
}

// The TMDB attribution block (official logo + the disclaimer TMDB requires). Reused
// on the recommendation rail, the discover dialog, and the settings panel.
function tmdbAttribution() {
  return `<a class="tmdb-attrib" href="https://www.themoviedb.org/" target="_blank" rel="noopener" title="Powered by TMDB">
      <img class="tmdb-attrib-logo" src="/tmdb-logo.svg" alt="TMDB" />
      <span class="muted small">This product uses the TMDB API but is not endorsed or certified by TMDB.</span>
    </a>`;
}

/* ===================== recommendation transparency + tuning panel ===================== */
// Shows how the recommender works (from your own ratings + watch history), what you're
// being recommended and why, lets you reweight the dials, or return to automatic.
async function openRecoPanel() {
  const panel = $("#recoPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  const body = $("#recoBody");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  let cfg = null, recs = null;
  try { [cfg, recs] = await Promise.all([api("/api/reco/config"), api("/api/recommendations")]); }
  catch (e) { body.innerHTML = `<p class="muted">Couldn't load: ${escapeHtml(e.message)}</p>`; return; }
  renderRecoPanel(cfg, recs);
}

function closeRecoPanel() { $("#recoPanel")?.classList.add("hidden"); }

function renderRecoPanel(cfg, recs) {
  const body = $("#recoBody");
  if (!body || !cfg) return;
  const p = cfg.profile || {}, w = cfg.weights || {};
  const stats = [
    `${p.ratedUp || 0} liked`, `${p.ratedDown || 0} not for me`, `${p.finished || 0} finished`,
    (p.topGenres && p.topGenres.length) ? `Top genres: ${p.topGenres.map(escapeHtml).join(", ")}`
      : (p.hasGenres ? "" : "genres off"),
  ].filter(Boolean);

  body.innerHTML = `
    <p class="reco-explain">${escapeHtml(cfg.explain)}</p>
    <div class="reco-stats">${stats.map(s => `<span class="chip">${s}</span>`).join("")}</div>
    ${p.hasSignal ? "" : `<p class="muted small">Rate a few titles thumbs-up / thumbs-down (or just watch them) and these get personal. Until then you'll see what's new.</p>`}
    <h3 class="reco-h">Weight it your way</h3>
    <div class="reco-dials" id="recoDials"></div>
    <div class="reco-actions">
      <button class="btn primary" id="recoSave">Save</button>
      <button class="btn ghost" id="recoReset">Return to automatic</button>
      <span id="recoSaved" class="muted small"></span>
    </div>
    <h3 class="reco-h">What you're being recommended &amp; why</h3>
    <div class="reco-explainList" id="recoExplainList"></div>`;

  const dials = $("#recoDials");
  for (const info of (cfg.info || [])) {
    const val = Number(w[info.key] ?? 1);
    const row = el("div", "reco-dial");
    row.innerHTML =
      `<div class="reco-dial-head"><label>${escapeHtml(info.label)}</label><output>${val.toFixed(1)}×</output></div>
       <input type="range" min="${cfg.min}" max="${cfg.max}" step="${cfg.step}" value="${val}" data-key="${info.key}" aria-label="${escapeHtml(info.label)}">
       <div class="reco-dial-help muted small">${escapeHtml(info.help)}</div>`;
    const out = $("output", row), input = $("input", row);
    input.oninput = () => { out.textContent = parseFloat(input.value).toFixed(1) + "×"; };
    dials.appendChild(row);
  }

  const list = $("#recoExplainList");
  const rows = (recs && recs.rows) || [];
  if (!rows.length) { list.innerHTML = `<p class="muted">No recommendations yet.</p>`; }
  for (const r of rows) {
    const g = el("div", "reco-exp-row");
    g.innerHTML = `<div class="reco-exp-title">${escapeHtml(r.title)}</div>`;
    const ul = el("ul", "reco-exp-items");
    for (const it of r.items.slice(0, 6)) {
      const li = el("li");
      li.innerHTML = `<span class="reco-exp-name">${escapeHtml(it.name)}</span><span class="reco-exp-why muted">${escapeHtml(it.why || "")}</span>`;
      ul.appendChild(li);
    }
    g.appendChild(ul);
    list.appendChild(g);
  }

  $("#recoSave").onclick = async () => {
    const weights = {};
    $$("#recoDials input").forEach(i => { weights[i.dataset.key] = parseFloat(i.value); });
    try {
      await api("/api/reco/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weights }),
      });
      $("#recoSaved").textContent = "Saved";
      renderRecommendations();              // refresh the rows with the new weighting
    } catch (e) { toast(e.message, "err"); }
  };
  $("#recoReset").onclick = async () => {
    try {
      const cfg2 = await api("/api/reco/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset: true }),
      });
      renderRecoPanel(cfg2, recs);
      $("#recoSaved").textContent = "Back to automatic";
      renderRecommendations();
    } catch (e) { toast(e.message, "err"); }
  };
  applyIcons(body);
}

function renderTitleGrid(sec, grid, items) {
  if (!sec || !grid) return;
  if (!items.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  grid.innerHTML = "";
  for (const it of items) grid.appendChild(titleCard(it));
}

// A poster tile for one show or movie. Clicking opens its detail page.
function titleCard(it) {
  if (it.external) return externalCard(it);   // a TMDB suggestion you don't own yet
  const card = el("div", "title-card");
  card.dataset.id = it.id;
  card.dataset.path = it.id;                 // lets toggleMyList sync this card too
  const isShow = it.kind === "show";
  // Prefer the real TMDB portrait poster (so owned titles look like a streaming
  // service); fall back to the folder cover / a video frame when there's no match.
  const localPoster = isShow
    ? `/api/cover?path=${enc(it.id)}`        // folder poster, else first-episode thumb
    : `/api/thumb?path=${enc(it.path || it.id)}`;
  const posterSources = [it.poster, localPoster].filter(Boolean);
  const poster = posterSources[0];
  const sub = isShow
    ? (it.episodeCount != null
        ? `${it.seasonCount} season${it.seasonCount === 1 ? "" : "s"} · ${it.episodeCount} ep${it.episodeCount === 1 ? "" : "s"}`
        : (it.episode || "Series"))   // history/minimal cards carry an episode tag, not counts
    : [it.year ? String(it.year) : "", it.duration ? fmtTime(it.duration) : ""].filter(Boolean).join(" · ");
  const frac = (!isShow && it.position && it.duration) ? Math.min(100, (it.position / it.duration) * 100) : 0;
  card.innerHTML =
    `<div class="poster">
       <div class="ph">${ICON.film}</div>
       <img alt="" loading="lazy" style="opacity:0;transition:opacity .2s" />
       <span class="kind-badge">${isShow ? "Series" : "Movie"}</span>
       ${ratingFlag(it.rating)}
       ${it.suggestArchive && typeof archiveSuggestFlag === "function" ? archiveSuggestFlag() : ""}
       ${it.watched ? `<span class="seen-flag" title="Watched">${ICON.check}</span>` : ""}
       <div class="play-ic"><span>${ICON.play}</span></div>
       ${frac > 0 ? `<div class="resume"><i style="width:${frac}%"></i></div>` : ""}
     </div>
     <div class="title-foot">
       <div class="title-name">${escapeHtml(it.name)}</div>
       <div class="title-sub">${escapeHtml(sub)}</div>
     </div>`;
  const img = $("img", card);
  if (img) {
    let si = 0;
    img.onload = () => { if (img.naturalWidth) { img.style.opacity = 1; $(".ph", card)?.remove(); } };
    img.onerror = () => { si++; if (si < posterSources.length) img.src = posterSources[si]; else img.removeAttribute("src"); };
    img.src = poster;
  }
  card.onclick = () => openTitle(it.id);
  return card;
}

// A poster tile for a TMDB suggestion that ISN'T in the library. No playback — it
// opens an info card with the synopsis and a link to find it (then watch it here).
function externalCard(it) {
  const card = el("div", "title-card external");
  card.dataset.id = it.id;
  const sub = [it.year ? String(it.year) : "", it.vote ? `★ ${it.vote}` : ""].filter(Boolean).join(" · ");
  card.innerHTML =
    `<div class="poster">
       <div class="ph">${ICON.film}</div>
       <img alt="" loading="lazy" style="opacity:0;transition:opacity .2s" />
       <span class="kind-badge discover-badge">${it.kind === "show" ? "Series" : "Movie"} · TMDB</span>
       <div class="play-ic discover-ic"><span>${ICON.plus}</span></div>
     </div>
     <div class="title-foot">
       <div class="title-name">${escapeHtml(it.name)}</div>
       <div class="title-sub">${escapeHtml(sub || "Not in your library")}</div>
     </div>`;
  const img = $("img", card);
  if (img && it.poster) {
    img.onload = () => { if (img.naturalWidth) { img.style.opacity = 1; $(".ph", card)?.remove(); } };
    img.onerror = () => { img.removeAttribute("src"); };
    img.src = it.poster;
  }
  card.onclick = () => openDiscover(it);
  return card;
}

// Info card for an external (TMDB) suggestion: synopsis, why it's here, and a link
// out to TMDB so the viewer can find it through their own channels and add it.
function openDiscover(it) {
  const poster = it.poster
    ? `<img class="discover-poster" alt="" src="${escapeHtml(it.poster)}" />` : "";
  const meta = [it.year ? String(it.year) : "", it.vote ? `★ ${it.vote} on TMDB` : "",
                it.kind === "show" ? "Series" : "Movie"].filter(Boolean).join("  ·  ");
  openDialog(it.name, `
    <div class="discover-dlg">
      ${poster}
      <div class="discover-meta">
        <div class="muted small">${escapeHtml(meta)}</div>
        ${it.why ? `<div class="discover-why">${escapeHtml(it.why)}</div>` : ""}
        ${it.overview ? `<p class="discover-overview">${escapeHtml(it.overview)}</p>` : ""}
        <p class="muted small">Not in your library yet. Find it through your usual channels, add the file to a Kadmu folder, and it'll play here.</p>
        ${tmdbAttribution()}
      </div>
    </div>`, () => {
    if (it.tmdbUrl) window.open(it.tmdbUrl, "_blank", "noopener");
    return true;
  });
  const ok = $("#dialogOk");
  if (ok) ok.textContent = it.tmdbUrl ? "View on TMDB →" : "OK";
}

// Small corner flag showing a thumbs rating on a poster (nothing when unrated).
function ratingFlag(rating) {
  if (rating === 1) return `<span class="rating-flag up" title="You liked this">${ICON.thumbUp}</span>`;
  if (rating === -1) return `<span class="rating-flag down" title="Not for you">${ICON.thumbDown}</span>`;
  return "";
}

/* ===================== title detail page ===================== */
// The title currently shown on the detail page (id, rating, resume target, seasons).
let titleNow = null;

const HOME_AND_LIB_SECTIONS = [
  "#homeNav", "#homeHero", "#continueSection", "#topSection", "#genreSection",
  "#recentSection", "#historySection", "#mylistSection", "#recoSection", "#catalogBar",
  "#showsSection", "#moviesSection", "#discoverSection", "#homeBar", "#libToolbar",
  "#folderSection", "#videoSection", "#searchExtSection", "#emptyState",
];

async function openTitle(id, opts = {}) {
  const view = $("#titleView");
  if (!view) return;
  if (!$("#playerOverlay").classList.contains("hidden")) teardownPlayer();
  let d = null;
  try { d = await api(`/api/title?id=${enc(id)}`); }
  catch (e) { if (!opts.silent) toast(e.message, "err"); return loadLibrary(null); }
  if (!d) { if (!opts.silent) toast("That title is no longer in your library.", "err"); return loadLibrary(null); }

  titleNow = d;
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  HOME_AND_LIB_SECTIONS.forEach(s => $(s)?.classList.add("hidden"));
  view.classList.remove("hidden");
  renderTitleDetail(d);
  renderTitleBreadcrumb(d);
  window.scrollTo(0, 0);
  document.title = `${d.name} · Kadmu`;
  syncURL("title", id);
}

function renderTitleBreadcrumb(d) {
  const bc = $("#breadcrumb");
  if (!bc) return;
  bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => loadLibrary(null);
  bc.appendChild(home);
  bc.appendChild(el("span", "sep", "›"));
  bc.appendChild(el("span", "crumb current", escapeHtml(d.name)));
}

function renderTitleDetail(d) {
  const view = $("#titleView");
  const isShow = d.kind === "show";
  // Cinematic backdrop (TMDB landscape) with a graceful fallback to the local cover/frame.
  const localArt = isShow ? `/api/cover?path=${enc(d.id)}`
                          : `/api/thumb?path=${enc((d.video && d.video.path) || d.id)}`;
  const bgSources = [d.backdrop, localArt].filter(Boolean);

  const metaBits = isShow
    ? [d.year ? String(d.year) : "",
       `${d.seasonCount} season${d.seasonCount === 1 ? "" : "s"}`,
       `${d.episodeCount} episode${d.episodeCount === 1 ? "" : "s"}`,
       d.watched ? `${d.watched} watched` : ""]
    : [d.year ? String(d.year) : "",
       d.video && d.video.duration ? fmtTime(d.video.duration) : "",
       d.video && d.video.watched ? "Watched" : ""];
  if (d.rating) metaBits.push(`★ ${d.rating}`);
  const sub = metaBits.filter(Boolean).join("  ·  ");
  const onList = state.mylist.has(d.id);

  // Chips (maturity + genres), the synopsis (shown inside the hero card), and the
  // cast / creator credits (below the hero).
  const chips = [];
  if (d.maturity) chips.push(`<span class="meta-chip mat">${escapeHtml(d.maturity)}</span>`);
  (d.genres || []).slice(0, 4).forEach(g => chips.push(`<span class="meta-chip">${escapeHtml(g)}</span>`));
  const overview = d.overview
    ? `<p class="title-hero-overview">${escapeHtml(d.overview)}</p>` : "";
  const creators = (d.creators && d.creators.length)
    ? `<div class="title-people"><span class="tp-label">${isShow ? "Creator" : "Director"}</span> ${d.creators.map(escapeHtml).join(", ")}</div>` : "";
  const cast = (d.cast && d.cast.length)
    ? `<div class="title-people"><span class="tp-label">Cast</span> ${d.cast.slice(0, 6).map(escapeHtml).join(", ")}</div>` : "";
  const credits = (creators || cast)
    ? `<div class="title-credits">${creators}${cast}</div>` : "";   // shown inside the hero card

  view.innerHTML =
    `<button class="btn ghost title-back">${ICON.up}<span>Back</span></button>
     <div class="title-hero">
       <div class="title-hero-bg"><img alt="" /></div>
       <div class="title-hero-scrim"></div>
       <div class="title-hero-content">
         <div class="title-eyebrow">${isShow ? "Series" : "Movie"}</div>
         <h1 class="title-hero-name">${escapeHtml(d.name)}</h1>
         <div class="title-hero-sub">${escapeHtml(sub)}</div>
         ${chips.length ? `<div class="title-chips">${chips.join("")}</div>` : ""}
         ${overview}
         <div class="title-actions">
           <button class="btn primary title-resume"></button>
           <button class="btn ghost title-mylist" data-mylist>${onList ? ICON.check : ICON.plus}<span>${onList ? "On My List" : "My List"}</span></button>
           ${d.trailer ? `<button class="btn ghost title-trailer" type="button" title="Watch the trailer on YouTube (opens a new tab)">${ICON.film}<span>Trailer</span></button>` : ""}
           <span class="rate-group" role="group" aria-label="Rate this">
             <button class="rate-btn up" data-rate="1" title="I like this">${ICON.thumbUp}</button>
             <button class="rate-btn down" data-rate="-1" title="Not for me">${ICON.thumbDown}</button>
           </span>
           <div class="title-more">
             <button class="btn ghost title-more-btn" type="button" aria-haspopup="true" aria-expanded="false" title="Options" aria-label="Options">
               <span class="more-ic"><svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg></span>
             </button>
             <div class="title-menu hidden" role="menu"></div>
           </div>
         </div>
       </div>
       ${credits}
     </div>
     <div class="title-body">
       ${isShow ? `<div class="season-bar">
            <label class="season-label" for="seasonSelect">Episodes</label>
            <select id="seasonSelect" class="lib-select"></select>
          </div>
          <div class="ep-list" id="episodeList"></div>` : `<div class="movie-note muted"></div>`}
       <div class="title-collection hidden" id="titleCollection"></div>
     </div>`;

  // backdrop (TMDB → local fallback chain)
  const bg = $(".title-hero-bg img", view);
  const heroBox = $(".title-hero-bg", view);
  if (bg) {
    let bi = 0;
    bg.onerror = () => { bi++; if (bi < bgSources.length) bg.src = bgSources[bi]; else heroBox && heroBox.classList.add("noimg"); };
    if (bgSources.length) bg.src = bgSources[0]; else heroBox && heroBox.classList.add("noimg");
  }
  applyIcons(view);

  // Resume / Play button — its target is computed server-side (the episode you're
  // mid-way through, the next one up, or episode one).
  wireResumeButton(view, d);
  $(".title-back", view).onclick = () => loadLibrary(null);

  // My List + thumbs rating
  $(".title-mylist", view).onclick = (ev) => {
    ev.preventDefault();
    toggleTitleMyList(d.id, d.name, view);
  };
  paintRating(view, d.rating);
  $$(".rate-btn", view).forEach(b => {
    b.onclick = () => rateTitle(d.id, parseInt(b.dataset.rate, 10), view);
  });

  // Trailer — plays in an in-app YouTube lightbox (privacy-enhanced youtube-nocookie).
  // Needs an internet connection; nothing loads until clicked.
  const tBtn = $(".title-trailer", view);
  if (tBtn && d.trailer) tBtn.onclick = () => openTrailer(d.trailer, d.name);

  if (isShow) buildSeasons(view, d);
  renderCollectionRail(view, d);   // "More from this collection" (owned franchise members)
  // The "Options" dropdown (mark watched / open folder / archive) in the actions row.
  buildTitleMenu(view, d);
}

/* ---- Trailer lightbox: an in-app YouTube (no-cookie) embed ----
   Opens only on an explicit click; clearing the iframe on close stops playback and
   ends any contact with YouTube. Falls back to a new tab if the id can't be parsed. */
function _ytId(url) {
  try {
    const u = new URL(url);
    if (u.hostname.endsWith("youtube.com")) return u.searchParams.get("v") || "";
    if (u.hostname === "youtu.be") return u.pathname.slice(1);
  } catch {}
  return "";
}
function openTrailer(url, title) {
  const id = _ytId(url), modal = $("#trailerModal"), frame = $("#trailerFrame");
  if (!id || !modal || !frame) { if (url) window.open(url, "_blank", "noopener"); return; }
  frame.innerHTML = "";
  const iframe = document.createElement("iframe");
  iframe.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0&modestbranding=1&playsinline=1`;
  iframe.allow = "autoplay; encrypted-media; fullscreen; picture-in-picture";
  iframe.allowFullscreen = true;
  iframe.referrerPolicy = "strict-origin-when-cross-origin";
  iframe.setAttribute("title", (title || "Trailer") + " — trailer");
  frame.appendChild(iframe);
  $("#trailerTitle").textContent = title || "Trailer";
  const yt = $("#trailerYt"); if (yt) yt.href = url;
  modal.classList.remove("hidden");
  $("#trailerClose")?.focus();
}
function closeTrailer() {
  const modal = $("#trailerModal");
  if (!modal || modal.classList.contains("hidden")) return false;
  modal.classList.add("hidden");
  const frame = $("#trailerFrame"); if (frame) frame.innerHTML = "";   // stop playback + drop the connection
  return true;
}

// Franchise rail under a movie: the other owned titles in the same TMDB collection,
// oldest-first. The server already parental-gated + de-duplicated the list.
function renderCollectionRail(view, d) {
  const box = $("#titleCollection", view);
  if (!box) return;
  const coll = d.collection;
  if (!coll || !(coll.items || []).length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML = `<h3 class="collection-head">${escapeHtml(coll.name || "Collection")}</h3>`;
  const rail = el("div", "collection-rail");
  coll.items.forEach(it => {
    const card = el("button", "collection-card");
    card.type = "button";
    const poster = el("div", "collection-poster" + (it.poster ? "" : " noimg"));
    if (it.poster) { const im = new Image(); im.alt = ""; im.loading = "lazy"; im.src = it.poster; poster.appendChild(im); }
    card.appendChild(poster);
    const label = escapeHtml(it.name || "") + (it.year ? ` <span class="cc-year">${it.year}</span>` : "");
    card.appendChild(el("div", "collection-name", label));
    card.onclick = () => openTitle(it.id);
    rail.appendChild(card);
  });
  box.appendChild(rail);
}

/* ---- "Options" dropdown on the title detail page (opens on hover or click) ---- */
function menuItem(iconHtml, label, onClick, cls) {
  const b = el("button", "menu-item" + (cls ? " " + cls : ""));
  b.type = "button";
  b.innerHTML = `${iconHtml || ""}<span>${escapeHtml(label)}</span>`;
  b.onclick = () => { closeTitleMenu(); onClick(); };
  return b;
}

function buildTitleMenu(view, d) {
  const menu = $(".title-menu", view), wrap = $(".title-more", view);
  if (!menu || !wrap) return;
  menu.innerHTML = "";
  const isShow = d.kind === "show";

  // Mark watched / unwatched
  if (isShow) {
    menu.appendChild(menuItem(ICON.check, "Mark all as watched", () => setTitleWatched(d, true)));
    menu.appendChild(menuItem(ICON.eyeOff, "Mark all as unwatched", () => setTitleWatched(d, false)));
  } else {
    const w = !!(d.video && d.video.watched);
    menu.appendChild(menuItem(w ? ICON.eyeOff : ICON.check,
      w ? "Mark as unwatched" : "Mark as watched", () => setTitleWatched(d, !w)));
  }
  // Open the underlying folder in the classic file browser (rename / move / delete files)
  if (state.session && state.session.canBrowse) {
    const folder = isShow ? d.id : parentDir((d.video && d.video.path) || d.id);
    menu.appendChild(menuItem(ICON.folder, "Open folder", () => loadLibrary(folder)));
  }
  // Archive (reclaim disk) — renders its own states into the menu when the server has
  // an encoder. No-op if archive.js didn't load / no encoder.
  if (typeof renderArchiveControls === "function") renderArchiveControls(view, d);

  wireTitleMenu(wrap, menu);
}

function wireTitleMenu(wrap, menu) {
  const btn = $(".title-more-btn", wrap);
  let closeT = null;
  const open = () => { clearTimeout(closeT); menu.classList.remove("hidden"); btn?.setAttribute("aria-expanded", "true"); };
  const close = () => { menu.classList.add("hidden"); btn?.setAttribute("aria-expanded", "false"); };
  wrap.onmouseenter = open;
  wrap.onmouseleave = () => { closeT = setTimeout(close, 200); };   // delay bridges the button↔menu gap
  if (btn) btn.onclick = (e) => { e.stopPropagation(); menu.classList.contains("hidden") ? open() : close(); };
}
function closeTitleMenu() { const m = $(".title-menu"); if (m) m.classList.add("hidden"); }

// Mark a whole show (every episode) or a movie watched / unwatched, then refresh the page.
async function setTitleWatched(d, watched) {
  const targets = d.kind === "show"
    ? (d.seasons || []).flatMap(s => s.episodes || [])
    : (d.video ? [d.video] : []);
  await Promise.all(targets.map(ep => {
    if (!ep || !ep.path) return Promise.resolve();
    if (watched) {
      const dur = ep.duration || (state.progress[ep.path] && state.progress[ep.path].duration);
      if (!dur) return Promise.resolve();
      return api("/api/progress", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: ep.path, position: dur, duration: dur }) }).catch(() => {});
    }
    return api("/api/progress/clear", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: ep.path }) }).catch(() => {});
  }));
  toast(watched ? "Marked as watched" : "Marked as unwatched", "ok");
  openTitle(d.id, { silent: true });    // re-render the detail with the new state
}

// Close the Options menu on an outside click or Escape (wired once).
(function wireTitleMenuGlobal() {
  document.addEventListener("click", (e) => { if (!e.target.closest(".title-more")) closeTitleMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeTitleMenu(); });
})();

function syncMyListLabel(view, id) {
  const btn = $(".title-mylist", view);
  if (!btn) return;
  const on = state.mylist.has(id);
  btn.innerHTML = `${on ? ICON.check : ICON.plus}<span>${on ? "On My List" : "My List"}</span>`;
}

// My List toggle for the detail page's labelled button (toggleMyList only repaints
// cards that carry a [data-path]; this awaits the call and repaints our pill itself).
async function toggleTitleMyList(id, name, view) {
  const on = !state.mylist.has(id);
  try {
    await api("/api/mylist", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: id, name, on }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  if (on) state.mylist.add(id); else state.mylist.delete(id);
  syncMyListLabel(view, id);
  toast(on ? "Added to My List" : "Removed from My List", "ok");
}

function wireResumeButton(view, d) {
  const btn = $(".title-resume", view);
  if (!btn) return;
  const r = d.resume;
  let label = "Play";
  if (r) {
    if (r.mode === "resume") label = d.kind === "show" ? `Resume ${epShort(r)}` : "Resume";
    else if (r.mode === "next") label = `Play ${epShort(r)}`;
    else if (r.mode === "replay") label = "Watch again";
    else label = d.kind === "show" ? `Play ${epShort(r)}` : "Play";
  }
  btn.innerHTML = `${ICON.play}<span>${escapeHtml(label)}</span>`;
  applyIcons(btn);
  btn.onclick = () => {
    const target = r || (d.video || null);
    if (!target) { toast("Nothing to play here yet.", "err"); return; }
    primeProgress(target);
    openPlayer(target);
  };
}

// "S4E2" style short tag for a resume/next episode (empty for a movie).
function epShort(ep) {
  if (ep.season == null || ep.episode == null) return "";
  return `S${ep.season}E${ep.episode}`;
}
// Episode title with the leading "S4E1 ·" stripped (the season list already shows numbers).
function epTitleText(ep) {
  const d = dispName(ep);
  const m = d.match(/^S\d+\s*E\d+\s*·\s*(.+)$/i);
  return m ? m[1] : d;
}
// Seed state.progress so openPlayer resumes at the right spot for a freshly-fetched episode.
function primeProgress(ep) {
  if (ep && ep.path && ep.duration) {
    state.progress[ep.path] = { position: ep.position || 0, duration: ep.duration };
  }
}

/* ---- season switcher + episode list ---- */
function buildSeasons(view, d) {
  const sel = $("#seasonSelect", view);
  const seasons = d.seasons || [];
  if (!sel || !seasons.length) return;
  sel.innerHTML = "";
  seasons.forEach((s, i) => {
    const o = el("option", null, escapeHtml(`${s.label} · ${s.episodes.length} ep${s.episodes.length === 1 ? "" : "s"}`));
    o.value = String(i);
    sel.appendChild(o);
  });
  // default to the season that holds the resume target, else the first
  let start = 0;
  if (d.resume) {
    const idx = seasons.findIndex(s => s.episodes.some(e => e.path === d.resume.path));
    if (idx >= 0) start = idx;
  }
  sel.value = String(start);
  sel.onchange = () => renderEpisodes(view, seasons[parseInt(sel.value, 10)]);
  renderEpisodes(view, seasons[start]);
}

// Episodes paint twice: instantly from local data, then again once TMDB season
// metadata (titles, stills, synopses) arrives — so the list never blocks on the network.
let episodesSeq = 0;
async function renderEpisodes(view, season) {
  const list = $("#episodeList", view);
  if (!list || !season) return;
  const seq = ++episodesSeq;
  paintEpisodes(list, season, null);                  // instant: local names + frames
  if (!titleNow || !titleNow.id || season.season == null) return;
  let map = null;
  try { map = (await api(`/api/episodes?id=${enc(titleNow.id)}&season=${season.season}`)).episodes; }
  catch { return; }
  if (seq !== episodesSeq) return;                     // a newer season selection won
  if (map && Object.keys(map).length) paintEpisodes(list, season, map);   // overlay TMDB
}

function paintEpisodes(list, season, map) {
  list.innerHTML = "";
  for (const ep of season.episodes) {
    primeProgress(ep);
    const te = (map && ep.episode != null) ? map[String(ep.episode)] : null;
    list.appendChild(episodeRow(ep, te));
  }
}

function episodeRow(ep, te) {
  const row = el("div", "ep-row");
  row.dataset.path = ep.path;
  const frac = (ep.position && ep.duration) ? Math.min(100, (ep.position / ep.duration) * 100) : 0;
  const num = ep.episode != null ? ep.episode : "•";
  const title = (te && te.name) ? te.name : epTitleText(ep);   // prefer the real TMDB title
  // Thumb: TMDB still when we have one, else the local extracted frame.
  const thumbSources = [te && te.still, `/api/thumb?path=${enc(ep.path)}`].filter(Boolean);
  const stateMeta = ep.watched ? "Watched" : (frac > 0 ? `${Math.round(frac)}% watched`
    : (ep.playable ? "" : escapeHtml((ep.ext || "").replace(".", ""))));
  const air = (te && te.air_date) ? te.air_date.slice(0, 4) : "";
  const meta = [air, stateMeta].filter(Boolean).join("  ·  ");
  row.innerHTML =
    `<div class="ep-num">${escapeHtml(String(num))}</div>
     <div class="ep-thumb">
       <div class="ph">${ICON.film}</div>
       <img alt="" loading="lazy" style="opacity:0;transition:opacity .2s" />
       <div class="play-ic"><span>${ICON.play}</span></div>
       ${ep.watched ? `<span class="ep-seen" title="Watched">${ICON.check}</span>` : ""}
       ${frac > 0 ? `<div class="resume"><i style="width:${frac}%"></i></div>` : ""}
     </div>
     <div class="ep-info">
       <div class="ep-line">
         <span class="ep-title">${escapeHtml(title)}</span>
         <span class="ep-dur">${ep.duration ? escapeHtml(fmtTime(ep.duration)) : ""}</span>
       </div>
       <div class="ep-meta">${escapeHtml(meta)}</div>
       ${te && te.overview ? `<p class="ep-overview">${escapeHtml(te.overview)}</p>` : ""}
     </div>`;
  const img = $("img", row);
  if (img) {
    let si = 0;
    img.onload = () => { if (img.naturalWidth) { img.style.opacity = 1; $(".ph", row)?.remove(); } };
    img.onerror = () => { si++; if (si < thumbSources.length) img.src = thumbSources[si]; else img.removeAttribute("src"); };
    img.src = thumbSources[0];
  }
  row.onclick = () => {
    if (!ep.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(ep);
  };
  return row;
}

/* ---- thumbs rating ---- */
async function rateTitle(id, value, view) {
  const cur = titleNow && titleNow.id === id ? (titleNow.rating || 0) : 0;
  const next = cur === value ? 0 : value;                 // click the active thumb to clear
  let res;
  try {
    res = await api("/api/rating", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, value: next }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  if (titleNow && titleNow.id === id) titleNow.rating = res.value;
  paintRating(view, res.value);
  toast(res.value === 1 ? "Glad you like it" : res.value === -1 ? "Noted — not for you" : "Rating cleared", "ok");
}

function paintRating(view, value) {
  const up = $(".rate-btn.up", view), down = $(".rate-btn.down", view);
  if (up) up.classList.toggle("on", value === 1);
  if (down) down.classList.toggle("on", value === -1);
}

/* ===================== home / file-browser toggle ===================== */
// Keep the classic folder browser one click away (the show view is the default home).
function renderHomeBar(browseFiles) {
  const bar = $("#homeBar");
  if (!bar) return;
  bar.classList.remove("hidden");
  bar.innerHTML = "";
  const btn = el("button", "btn ghost mini",
    browseFiles ? `${ICON.up}<span>Back to Home</span>` : `${ICON.folder}<span>Browse files</span>`);
  btn.onclick = () => { state.browseFiles = !browseFiles; loadLibrary(null); };
  bar.appendChild(btn);
  applyIcons(bar);
}

// Close affordances for the recommendations panel (mirrors the settings modal).
(function wireRecoPanel() {
  const panel = $("#recoPanel");
  if (!panel) return;
  $("#recoClose")?.addEventListener("click", closeRecoPanel);
  panel.addEventListener("click", (e) => { if (e.target === panel) closeRecoPanel(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.classList.contains("hidden")) closeRecoPanel();
  });
})();
