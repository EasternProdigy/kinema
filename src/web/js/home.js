"use strict";
/* home.js — the Netflix-style home surface shown at the library root: a hero
   (resume what you were watching, or a recently-added pick) and a "Recently
   added" rail. Built entirely from LOCAL data (the background index + your
   resume history) — no metadata service, no outbound calls. Also wires the
   storyboard-driven preview-on-hover used by every video card.
   Part of the Kadmu frontend; classic script sharing the global scope. */

// The last /api/home payload (hero pick + recently-added), cached so the recent rail
// and the hero carousel can repaint on a tab switch without re-fetching.
let homeFeed = null;

async function renderHome() {
  let home = null;
  try { home = await api("/api/home"); } catch {}
  homeFeed = home || { hero: null, recent: [] };
  state.homeFeed = homeFeed;
  paintRecent();
  // The hero carousel needs the catalog (rich title cards) — it's built by
  // renderHeroCarousel(), called from renderCatalog once the catalog has loaded.
}

// "Recently added" rail — only on the Home tab (it's an all-kinds rail).
function paintRecent() {
  const sec = $("#recentSection"), rail = $("#recentRail");
  if (!sec || !rail) return;
  const recent = (homeFeed && homeFeed.recent) || [];
  if (state.homeFilter !== "all" || !recent.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  rail.innerHTML = "";
  for (const v of recent) rail.appendChild(videoCard(v));
}

/* ---------- hero carousel (Netflix-style click-through billboard) ---------- */
let heroTimer = null;          // auto-advance interval
let heroIdx = 0;               // active slide
let heroSlides = 0;            // slide count for wrap-around

// Pick the featured titles for the current tab: in-progress first (so "Continue
// watching" leads), then the most popular / best rated / freshest. Built from the
// cached catalog so each slide is a real title (Play + More info both work).
function heroCandidates() {
  const cat = state.catalog || { shows: [], movies: [] };
  let items = (cat.shows || []).concat(cat.movies || []);
  if (state.homeFilter === "show") items = items.filter(it => it.kind === "show");
  else if (state.homeFilter === "movie") items = items.filter(it => it.kind === "movie");
  const prog = (it) => (it.kind === "show")
    ? (it.watched > 0 && it.watched < it.episodeCount)
    : (it.position > 0 && !it.watched);
  const score = (it) => (prog(it) ? 1e9 : 0) + (it.popularity || 0) * 1000 + (it.rating || 0) * 10 + ((it.mtime || 0) / 1e9);
  return items.slice().sort((a, b) => score(b) - score(a)).slice(0, 6);
}

function renderHeroCarousel() {
  const sec = $("#homeHero");
  if (!sec) return;
  if (heroTimer) { clearInterval(heroTimer); heroTimer = null; }
  if (state.homeFilter === "mylist") { sec.classList.add("hidden"); sec.innerHTML = ""; return; }
  const cands = heroCandidates();
  if (!cands.length) { sec.classList.add("hidden"); sec.innerHTML = ""; return; }
  sec.classList.remove("hidden");
  sec.classList.toggle("single", cands.length === 1);
  heroIdx = 0; heroSlides = cands.length;
  sec.innerHTML =
    `<div class="hero-track">${cands.map((it, i) => heroSlide(it, i)).join("")}</div>
     ${cands.length > 1 ? `<button class="hero-nav prev" aria-label="Previous"></button>
       <button class="hero-nav next" aria-label="Next"></button>
       <div class="hero-dots">${cands.map((_, i) => `<button class="hero-dot${i === 0 ? " on" : ""}" data-i="${i}" aria-label="Slide ${i + 1}"></button>`).join("")}</div>` : ""}`;

  // wire each slide's backdrop + buttons
  cands.forEach((it, i) => {
    const slide = sec.querySelector(`.hero-slide[data-i="${i}"]`);
    if (!slide) return;
    const bd = $(".hero-backdrop", slide), img = $(".hero-backdrop img", slide);
    if (img) { img.onerror = () => bd && bd.classList.add("noimg"); img.src = heroBackdrop(it); }
    $(".hero-play", slide)?.addEventListener("click", () => playTitle(it.id));
    $(".hero-open", slide)?.addEventListener("click", () => openTitle(it.id));
  });
  applyIcons(sec);

  if (cands.length > 1) {
    $(".hero-nav.prev", sec).onclick = () => heroGo(heroIdx - 1);
    $(".hero-nav.next", sec).onclick = () => heroGo(heroIdx + 1);
    $$(".hero-dot", sec).forEach(d => d.onclick = () => heroGo(parseInt(d.dataset.i, 10)));
    heroStart();
    sec.onmouseenter = () => { if (heroTimer) { clearInterval(heroTimer); heroTimer = null; } };
    sec.onmouseleave = heroStart;
  }
}

// Prefer the cinematic TMDB backdrop (landscape); fall back to the folder cover / a frame.
function heroBackdrop(it) {
  return it.backdrop || (it.kind === "show" ? `/api/cover?path=${enc(it.id)}` : `/api/thumb?path=${enc(it.path || it.id)}`);
}

function heroSlide(it, i) {
  const isShow = it.kind === "show";
  const inProgress = isShow ? (it.watched > 0 && it.watched < it.episodeCount) : (it.position > 0 && !it.watched);
  const eyebrow = inProgress ? "Continue watching"
    : ((it.genres && it.genres[0]) ? it.genres[0] : (isShow ? "Series" : "Movie"));
  const meta = isShow
    ? [`${it.seasonCount} season${it.seasonCount === 1 ? "" : "s"}`, `${it.episodeCount} ep${it.episodeCount === 1 ? "" : "s"}`]
    : [it.year ? String(it.year) : "", it.duration ? fmtTime(it.duration) : ""];
  if (it.rating) meta.push(`★ ${it.rating}`);
  const chips = [];
  if (it.maturity) chips.push(`<span class="hero-mat">${escapeHtml(it.maturity)}</span>`);
  if (it.genres && it.genres.length) {
    chips.push(`<span class="hero-genres">${it.genres.slice(0, 3).map(escapeHtml).join(" · ")}</span>`);
  }
  const overview = it.overview
    ? `<p class="hero-overview">${escapeHtml(it.overview)}</p>` : "";
  return `<div class="hero-slide${i === 0 ? " on" : ""}" data-i="${i}">
       <div class="hero-backdrop"><img alt="" /></div>
       <div class="hero-scrim"></div>
       <div class="hero-content">
         <div class="hero-eyebrow">${escapeHtml(eyebrow)}</div>
         <h1 class="hero-title">${escapeHtml(it.name)}</h1>
         <div class="hero-sub">${escapeHtml(meta.filter(Boolean).join("  ·  "))}</div>
         ${chips.length ? `<div class="hero-chips">${chips.join("")}</div>` : ""}
         ${overview}
         <div class="hero-actions">
           <button class="btn primary hero-play"><span data-icon="play"></span> ${inProgress ? "Resume" : "Play"}</button>
           <button class="btn ghost hero-open"><span data-icon="info"></span> More info</button>
         </div>
       </div>
     </div>`;
}

function heroGo(i) {
  const sec = $("#homeHero");
  if (!sec || heroSlides < 1) return;
  heroIdx = ((i % heroSlides) + heroSlides) % heroSlides;
  $$(".hero-slide", sec).forEach((s, n) => s.classList.toggle("on", n === heroIdx));
  $$(".hero-dot", sec).forEach((d, n) => d.classList.toggle("on", n === heroIdx));
}

function heroStart() {
  if (heroTimer) clearInterval(heroTimer);
  if (heroSlides > 1) heroTimer = setInterval(() => heroGo(heroIdx + 1), 7000);
}

/* ---------- preview-on-hover (storyboard frames cycled in the card) ---------- */
function attachHoverPreview(card, v) {
  if (!state.session || !state.session.ffmpeg || !v.playable) return;
  const thumb = card.querySelector(".thumb");
  if (!thumb) return;
  let timer = null, cycle = null, loaded = false;

  card.addEventListener("mouseenter", () => {
    timer = setTimeout(async () => {
      try {
        const info = await api(`/api/storyboard?path=${enc(v.path)}`);
        if (!info || !info.ok || !info.count) return;
        let ov = thumb.querySelector(".hover-prev");
        if (!ov) { ov = el("div", "hover-prev"); thumb.appendChild(ov); }
        const url = `/api/storyboard.jpg?path=${enc(v.path)}`;
        const im = new Image();
        im.onload = () => {
          if (!card.matches(":hover")) return;             // moved on while loading
          ov.style.backgroundImage = `url("${url}")`;
          ov.style.backgroundSize = `${info.cols * 100}% ${info.rows * 100}%`;
          ov.classList.add("on");
          loaded = true;
          let frame = Math.floor(info.count * 0.12);
          const show = () => {
            const col = frame % info.cols, row = Math.floor(frame / info.cols);
            ov.style.backgroundPosition =
              `${(col / Math.max(1, info.cols - 1)) * 100}% ${(row / Math.max(1, info.rows - 1)) * 100}%`;
            frame = (frame + 1) % info.count;
          };
          show();
          cycle = setInterval(show, 750);
        };
        im.src = url;
      } catch {}
    }, 450);
  });
  card.addEventListener("mouseleave", () => {
    clearTimeout(timer);
    if (cycle) { clearInterval(cycle); cycle = null; }
    if (loaded) { const ov = thumb.querySelector(".hover-prev"); if (ov) ov.classList.remove("on"); }
  });
}
