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
  return state.catalogHasItems;
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
  "#showsSection", "#moviesSection", "#homeBar", "#libToolbar",
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
