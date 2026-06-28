"use strict";
/* catalog.js — the Netflix-style library: a poster grid of Shows and Movies on the
   home surface, and a per-title detail page (backdrop, Resume, thumbs rating, and
   — for shows — a season switcher + episode list). Built entirely from local data
   (/api/catalog, /api/title, /api/rating); reuses openPlayer for playback.
   Part of the Kadmu frontend; classic script sharing the global scope. Loads after
   home.js (uses videoCard helpers) and is called by loadLibrary's root branch. */

/* ===================== home: Shows + Movies poster grids ===================== */
// Returns true if the catalog rendered any shows or movies (so loadLibrary knows to
// suppress the raw folder/video grids in favour of this view).
async function renderCatalog() {
  const showsSec = $("#showsSection"), moviesSec = $("#moviesSection");
  if (!showsSec || !moviesSec) return false;
  let cat = null;
  try { cat = await api("/api/catalog"); } catch {}
  const shows = (cat && cat.shows) || [];
  const movies = (cat && cat.movies) || [];
  state.catalogHasItems = !!(shows.length || movies.length);

  renderTitleGrid(showsSec, $("#showsGrid"), shows);
  renderTitleGrid(moviesSec, $("#moviesGrid"), movies);
  renderRecommendations();                   // taste-based rows above the full grids
  return state.catalogHasItems;
}

// "For you" rows (Keep watching / Top picks / Because you liked X), from /api/recommendations
// — built from the viewer's own thumbs ratings + watch history (+ TMDB genres when enabled).
// Each row reuses titleCard(), so a recommendation tile behaves exactly like a catalog tile.
async function renderRecommendations() {
  const sec = $("#recoSection");
  if (!sec) return;
  let data = null;
  try { data = await api("/api/recommendations"); } catch { /* leave hidden */ }
  const rows = (data && data.rows) || [];
  if (!rows.length) { sec.classList.add("hidden"); sec.innerHTML = ""; return; }
  sec.innerHTML = "";

  // A "how it works / tune it" entry point above the rows — the transparency panel.
  const head = el("div", "reco-head");
  const tune = el("button", "btn ghost reco-tune");
  tune.innerHTML = `${ICON.tune}<span>How recommendations work</span>`;
  tune.onclick = openRecoPanel;
  head.appendChild(tune);
  sec.appendChild(head);

  for (const row of rows) {
    const wrap = el("section", "row-section reco-row");
    const h = el("h2", "row-title");
    h.textContent = row.title;
    wrap.appendChild(h);
    const grid = el("div", "grid title-grid");
    for (const it of row.items) {
      const card = titleCard(it);
      if (it.why) card.title = `${it.name} — ${it.why}`;   // hover hint on why it's here
      grid.appendChild(card);
    }
    wrap.appendChild(grid);
    sec.appendChild(wrap);
  }
  // TMDB attribution — required wherever we show their data/images (genres, posters,
  // discovery). Only shown when the metadata layer is actually on.
  if (data && data.tmdb) {
    const foot = el("div", "reco-foot");
    foot.innerHTML = tmdbAttribution();
    sec.appendChild(foot);
  }
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
  const poster = isShow
    ? `/api/cover?path=${enc(it.id)}`        // folder poster, else first-episode thumb
    : `/api/thumb?path=${enc(it.path)}`;
  const sub = isShow
    ? `${it.seasonCount} season${it.seasonCount === 1 ? "" : "s"} · ${it.episodeCount} ep${it.episodeCount === 1 ? "" : "s"}`
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
    img.onload = () => { if (img.naturalWidth) { img.style.opacity = 1; $(".ph", card)?.remove(); } };
    img.onerror = () => { img.removeAttribute("src"); };
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
  "#homeHero", "#continueSection", "#recentSection", "#mylistSection",
  "#recoSection", "#showsSection", "#moviesSection", "#homeBar", "#libToolbar",
  "#folderSection", "#videoSection", "#emptyState",
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
  const poster = isShow ? `/api/cover?path=${enc(d.id)}`
                        : `/api/thumb?path=${enc((d.video && d.video.path) || d.id)}`;
  const metaBits = isShow
    ? [`${d.seasonCount} season${d.seasonCount === 1 ? "" : "s"}`,
       `${d.episodeCount} episode${d.episodeCount === 1 ? "" : "s"}`,
       d.watched ? `${d.watched} watched` : ""]
    : [d.year ? String(d.year) : "",
       d.video && d.video.duration ? fmtTime(d.video.duration) : "",
       d.video && d.video.watched ? "Watched" : ""];
  const sub = metaBits.filter(Boolean).join("  ·  ");
  const onList = state.mylist.has(d.id);

  view.innerHTML =
    `<div class="title-hero">
       <div class="title-hero-bg"><img alt="" /></div>
       <div class="title-hero-scrim"></div>
       <button class="btn ghost title-back">${ICON.up}<span>Back</span></button>
       <div class="title-hero-content">
         <div class="title-eyebrow">${isShow ? "Series" : "Movie"}</div>
         <h1 class="title-hero-name">${escapeHtml(d.name)}</h1>
         <div class="title-hero-sub">${escapeHtml(sub)}</div>
         <div class="title-actions">
           <button class="btn primary title-resume"></button>
           <button class="btn ghost title-mylist" data-mylist>${onList ? ICON.check : ICON.plus}<span>${onList ? "On My List" : "My List"}</span></button>
           <span class="rate-group" role="group" aria-label="Rate this">
             <button class="rate-btn up" data-rate="1" title="I like this">${ICON.thumbUp}</button>
             <button class="rate-btn down" data-rate="-1" title="Not for me">${ICON.thumbDown}</button>
           </span>
         </div>
       </div>
     </div>
     <div class="title-body">
       ${isShow ? `<div class="season-bar">
            <label class="season-label" for="seasonSelect">Episodes</label>
            <select id="seasonSelect" class="lib-select"></select>
          </div>
          <div class="ep-list" id="episodeList"></div>` : `<div class="movie-note muted"></div>`}
     </div>`;

  // backdrop
  const bg = $(".title-hero-bg img", view);
  const heroBox = $(".title-hero-bg", view);
  if (bg) {
    bg.onerror = () => heroBox && heroBox.classList.add("noimg");
    bg.src = poster;
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

  if (isShow) buildSeasons(view, d);
  // Archive (reclaim disk) control — appended to the actions row when the server has
  // an encoder. No-op if archive.js didn't load.
  if (typeof renderArchiveControls === "function") renderArchiveControls(view, d);
}

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

function renderEpisodes(view, season) {
  const list = $("#episodeList", view);
  if (!list || !season) return;
  list.innerHTML = "";
  for (const ep of season.episodes) {
    primeProgress(ep);
    list.appendChild(episodeRow(ep));
  }
}

function episodeRow(ep) {
  const row = el("div", "ep-row");
  row.dataset.path = ep.path;
  const frac = (ep.position && ep.duration) ? Math.min(100, (ep.position / ep.duration) * 100) : 0;
  const num = ep.episode != null ? ep.episode : "•";
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
         <span class="ep-title">${escapeHtml(epTitleText(ep))}</span>
         <span class="ep-dur">${ep.duration ? escapeHtml(fmtTime(ep.duration)) : ""}</span>
       </div>
       <div class="ep-meta">${ep.watched ? "Watched" : (frac > 0 ? `${Math.round(frac)}% watched` : (ep.playable ? "" : escapeHtml((ep.ext || "").replace(".", ""))))}</div>
     </div>`;
  const img = $("img", row);
  if (img) {
    img.onload = () => { if (img.naturalWidth) { img.style.opacity = 1; $(".ph", row)?.remove(); } };
    img.src = `/api/thumb?path=${enc(ep.path)}`;
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
