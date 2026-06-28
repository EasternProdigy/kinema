"use strict";
/* library.js — library browse/grid, search, Continue + My-List rendering
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== library rendering ===================== */
async function loadLibrary(path, opts = {}) {
  state.path = path || null;
  try { state.progress = await api("/api/progress"); } catch { state.progress = {}; }

  let data;
  try {
    data = await api(`/api/library${path ? "?path=" + enc(path) : ""}`);
  } catch (e) {
    // a remembered/stale path that no longer exists -> fall back to the root view
    if (path) { if (!opts.silent) toast(e.message, "err"); return loadLibrary(null); }
    toast(e.message, "err"); return;
  }
  // remember where we are so the next launch reopens here
  try {
    if (path) localStorage.setItem("kadmu_last_path", path);
    else localStorage.removeItem("kadmu_last_path");
  } catch {}
  state.data = data;
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  { const si = $("#searchInput"); if (si) si.value = ""; $("#searchBox")?.classList.remove("has-text"); closeSearchDD(); }   // leaving search → clear the box & dropdown
  clearSelection();
  renderBreadcrumb(data);
  renderFolders(data);
  renderVideos(data);
  if (data.isRoot) { await renderHome(); await renderContinue(); await renderMyList(); }
  else {
    $("#homeHero")?.classList.add("hidden");
    $("#recentSection")?.classList.add("hidden");
    $("#continueSection").classList.add("hidden");
    $("#mylistSection")?.classList.add("hidden");
  }
  renderEmpty(data);
  updateToolbar(data);
  window.scrollTo(0, 0);
  syncURL(state.path ? "browse" : "root", state.path);
}

/* ===================== search (live type-ahead dropdown + full results) =====================
   Typing pops a dropdown of matching shows & episodes (live, ranked by the backend).
   ↑/↓ moves the highlight, Enter opens the highlighted item — or, with nothing
   highlighted, the full results page. Esc closes the dropdown, then clears. The
   "See all results" footer and Enter-with-no-selection both fall through to
   runSearch(), which renders the classic full-page results into the library grid. */
const SEARCH_DD_FOLDERS = 6;   // shows/folders shown in the dropdown before "See all"
const SEARCH_DD_VIDEOS = 8;    // episodes/movies shown in the dropdown before "See all"
let searchTimer = null;
let searchSeq = 0;             // request counter; a stale (out-of-order) response is dropped
const sdd = { open: false, items: [], active: -1, q: "" };   // dropdown state

function searchTerms(q) {
  return (q || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
}
// Escape text for HTML, then wrap each matched query term in <mark> for the dropdown.
function highlightTerms(text, terms) {
  const safe = escapeHtml(text == null ? "" : text);
  if (!terms || !terms.length) return safe;
  const pat = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).filter(Boolean);
  if (!pat.length) return safe;
  try { return safe.replace(new RegExp("(" + pat.join("|") + ")", "gi"), "<mark>$1</mark>"); }
  catch { return safe; }
}
// "Show › Season" context line — the readable folder trail of a path's parent.
function ctxLabel(path) {
  const t = prettyTrail(parentDir(path));
  return t && t.length ? t.join(" › ") : "";
}

function onSearchInput(e) {
  const q = e.target.value;
  $("#searchBox")?.classList.toggle("has-text", !!q.trim());
  clearTimeout(searchTimer);
  if (!q.trim()) { closeSearchDD(); if (state.searchActive) exitSearch(); return; }
  searchTimer = setTimeout(() => suggest(q), 140);
}

// Fetch + render the live suggestion dropdown (debounced; stale responses ignored).
async function suggest(q) {
  q = (q || "").trim();
  if (!q) { closeSearchDD(); return; }
  const seq = ++searchSeq;
  let data;
  try { data = await api(`/api/search?q=${enc(q)}`); }
  catch { return; }                                  // a network blip leaves the dropdown as-is
  if (seq !== searchSeq) return;                     // a newer keystroke superseded this one
  if (($("#searchInput")?.value || "").trim() !== q) return;   // input changed/cleared meanwhile
  renderSearchDD(data, q);
}

function renderSearchDD(data, q) {
  const dd = $("#searchDropdown");
  if (!dd) return;
  const terms = searchTerms(q);
  const folders = data.folders || [];
  const videos = data.videos || [];
  const total = folders.length + videos.length;

  dd.innerHTML = "";
  sdd.items = [];
  sdd.active = -1;
  sdd.q = q;

  if (!total) {
    dd.appendChild(el("div", "sdd-empty", `No matches for <b>${escapeHtml(q)}</b>`));
    openSearchDD();
    return;
  }

  // register a row node: give it an index, wire hover/click, remember it for keyboard nav
  const register = (node, payload) => {
    const idx = sdd.items.length;
    node.classList.add("sdd-item");
    node.setAttribute("role", "option");
    node.dataset.idx = idx;
    node.addEventListener("mousemove", () => setActive(idx));
    node.addEventListener("click", () => activateItem(idx));
    sdd.items.push({ ...payload, node });
    dd.appendChild(node);
  };

  if (folders.length) {
    dd.appendChild(el("div", "sdd-head", "Shows &amp; folders"));
    for (const f of folders.slice(0, SEARCH_DD_FOLDERS)) {
      const ctx = ctxLabel(f.path);
      const bits = [];
      if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
      if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
      const sub = [ctx, bits.join(" · ")].filter(Boolean).join("  ·  ");
      const node = el("div", "",
        `<span class="sdd-ic">${ICON.folder}</span>
         <span class="sdd-text">
           <span class="sdd-name">${highlightTerms(f.name, terms)}</span>
           <span class="sdd-sub">${escapeHtml(sub)}</span>
         </span>
         ${f.watched ? `<span class="sdd-tag">${ICON.check}${f.watched}</span>` : ""}`);
      register(node, { kind: "folder", path: f.path });
    }
  }

  if (videos.length) {
    dd.appendChild(el("div", "sdd-head", "Episodes &amp; movies"));
    for (const v of videos.slice(0, SEARCH_DD_VIDEOS)) {
      const ctx = ctxLabel(v.path);
      const dur = v.duration ? fmtTime(v.duration) : "";
      const prog = state.progress[v.path];
      const frac = prog && prog.duration ? prog.position / prog.duration : 0;
      const watched = frac >= 0.95;
      const right = watched
        ? `<span class="sdd-tag ok" title="Watched">${ICON.check}</span>`
        : (dur ? `<span class="sdd-dur">${escapeHtml(dur)}</span>` : "");
      const node = el("div", "",
        `<span class="sdd-thumb"><span class="sdd-ph">${ICON.film}</span><img alt="" loading="lazy" style="opacity:0;transition:opacity .2s" /></span>
         <span class="sdd-text">
           <span class="sdd-name">${highlightTerms(dispName(v), terms)}</span>
           <span class="sdd-sub">${escapeHtml(ctx)}${!v.playable ? ` · ${escapeHtml((v.ext || "").replace(".", ""))}` : ""}</span>
         </span>
         ${right}`);
      const img = $("img", node);
      if (img) {
        img.src = `/api/thumb?path=${enc(v.path)}`;
        img.onload = () => { img.style.opacity = 1; $(".sdd-ph", node)?.remove(); };
      }
      register(node, { kind: "video", item: v });
    }
  }

  // footer: jump to the classic full-page results
  const foot = el("button", "sdd-all",
    `<span class="sdd-all-ic">${ICON.search}</span><span>See all ${total} result${total > 1 ? "s" : ""} for “${escapeHtml(q)}”</span>`);
  const fidx = sdd.items.length;
  foot.dataset.idx = fidx;
  foot.addEventListener("mousemove", () => setActive(fidx));
  foot.addEventListener("click", () => activateItem(fidx));
  sdd.items.push({ kind: "all", node: foot });
  dd.appendChild(foot);

  openSearchDD();
}

function openSearchDD() {
  const dd = $("#searchDropdown");
  if (!dd) return;
  dd.classList.remove("hidden");
  sdd.open = true;
}
function closeSearchDD() {
  const dd = $("#searchDropdown");
  if (dd) { dd.classList.add("hidden"); dd.innerHTML = ""; }
  sdd.open = false; sdd.items = []; sdd.active = -1;
}
function setActive(idx) {
  if (idx === sdd.active) return;
  sdd.items[sdd.active]?.node.classList.remove("active");
  sdd.active = idx;
  const it = sdd.items[idx];
  if (it) { it.node.classList.add("active"); it.node.scrollIntoView({ block: "nearest" }); }
}
function moveActive(delta) {
  if (!sdd.items.length) return;
  let i = sdd.active + delta;
  if (i < 0) i = sdd.items.length - 1;
  else if (i >= sdd.items.length) i = 0;
  setActive(i);
}
function activateItem(idx) {
  const it = sdd.items[idx];
  if (!it) return;
  const input = $("#searchInput");
  if (it.kind === "folder") { closeSearchDD(); input?.blur(); loadLibrary(it.path); }
  else if (it.kind === "video") {
    closeSearchDD(); input?.blur();
    if (!it.item.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(it.item);
  } else { closeSearchDD(); runSearch(sdd.q); }      // "See all results"
}

// Full results page — the dropdown's "See all" / Enter-with-no-selection target.
async function runSearch(q) {
  q = (q || "").trim();
  closeSearchDD();
  if (!q) { exitSearch(); return; }
  let data;
  try { data = await api(`/api/search?q=${enc(q)}`); } catch (e) { toast(e.message, "err"); return; }
  state.searchActive = true;
  document.body.classList.add("searching-mode");
  clearSelection();
  $("#continueSection").classList.add("hidden");
  $("#mylistSection")?.classList.add("hidden");
  $("#libToolbar")?.classList.add("hidden");   // sort/filter belong to browsing, not search

  const bc = $("#breadcrumb"); bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => {
    const i = $("#searchInput");
    if (i) { i.value = ""; $("#searchBox")?.classList.remove("has-text"); }
    exitSearch();
  };
  bc.appendChild(home);
  bc.appendChild(el("span", "sep", "›"));
  bc.appendChild(el("span", "crumb current", `Search: “${escapeHtml(q)}”`));

  renderFolders({ folders: data.folders, isRoot: false });
  renderVideos({ videos: data.videos });
  if (data.folders.length) $("#foldersTitle").textContent = "Shows & folders";
  if (data.videos.length) $("#videosTitle").textContent = `Episodes & movies · ${data.videos.length}`;

  const empty = $("#emptyState"); empty.innerHTML = "";
  if (!data.folders.length && !data.videos.length) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "No results"));
    empty.appendChild(el("p", "muted", `Nothing in your library matches “${q}”.`));
  } else empty.classList.add("hidden");
  window.scrollTo(0, 0);
}
function exitSearch() {
  state.searchActive = false;
  document.body.classList.remove("searching-mode");
  closeSearchDD();
  loadLibrary(state.path);
}

function renderBreadcrumb(data) {
  const bc = $("#breadcrumb");
  bc.innerHTML = "";
  const home = el("span", "crumb", "Library");
  home.onclick = () => loadLibrary(null);
  bc.appendChild(home);
  (data.breadcrumb || []).forEach((c, i, arr) => {
    bc.appendChild(el("span", "sep", "›"));
    const cr = el("span", "crumb" + (i === arr.length - 1 ? " current" : ""), escapeHtml(c.name));
    cr.onclick = () => loadLibrary(c.path);
    bc.appendChild(cr);
  });
}

// My List "+" / "✓" toggle button markup, reflecting current membership.
function myListBtn(path) {
  const on = state.mylist.has(path);
  return `<button class="mylist-btn${on ? " on" : ""}" data-mylist
            title="${on ? "Remove from My List" : "Add to My List"}">${on ? ICON.check : ICON.plus}</button>`;
}

async function toggleMyList(path, name, btn) {
  const on = !state.mylist.has(path);
  try {
    await api("/api/mylist", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, name, on }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  if (on) state.mylist.add(path); else state.mylist.delete(path);
  // reflect on every visible button for this path
  $$(`[data-mylist]`).forEach(b => {
    const card = b.closest("[data-path]");
    if (card && card.dataset.path === path) {
      b.classList.toggle("on", on); b.innerHTML = on ? ICON.check : ICON.plus;
      b.title = on ? "Remove from My List" : "Add to My List";
    }
  });
  if (btn) { btn.classList.toggle("on", on); btn.innerHTML = on ? ICON.check : ICON.plus; }
  toast(on ? "Added to My List" : "Removed from My List", "ok");
  if (state.path == null && !state.searchActive) renderMyList();   // refresh the home row
}

function folderCard(f) {
  const card = el("div", "folder-card");
  card.dataset.path = f.path;
  const bits = [];
  if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
  if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
  const watched = f.watched || 0;
  const wtag = watched
    ? `<span class="wtag" title="${watched} episode${watched > 1 ? "s" : ""} watched in here">${ICON.check}${watched} watched</span>`
    : "";
  const meta = bits.join(" · ") || (f.isFolder === false ? "" : "open");
  card.innerHTML =
    `<button class="check" data-check>${ICON.check}</button>
     <div class="folder-ic"><img class="cover" alt="" loading="lazy" />${ICON.folder}</div>
     <div class="folder-meta">
       <div class="folder-name">${escapeHtml(f.name)}</div>
       <div class="folder-sub">${meta}${watched && meta ? " · " : ""}${wtag}</div>
     </div>
     ${myListBtn(f.path)}`;
  // Lazy cover art: poster/folder/cover image, else the first episode's thumbnail.
  // On 404 / no art the <img> stays hidden and the folder glyph shows through.
  const cover = card.querySelector(".folder-ic .cover");
  if (cover) {
    cover.onload = () => { if (cover.naturalWidth) card.querySelector(".folder-ic").classList.add("has-cover"); };
    cover.onerror = () => { cover.removeAttribute("src"); };
    cover.src = `/api/cover?path=${enc(f.path)}`;
  }
  card.onclick = (ev) => {
    if (ev.target.closest("[data-mylist]")) { toggleMyList(f.path, f.name, ev.target.closest("[data-mylist]")); return; }
    if (ev.shiftKey || ev.target.closest("[data-check]")) { toggleSelect(card, f.path, f.name, true); return; }
    if (state.selection.size) clearSelection();   // a plain click clears any selection, then opens
    loadLibrary(f.path);
  };
  card.oncontextmenu = (ev) => openContextMenu(ev, { card, path: f.path, name: f.name, isFolder: true, item: f });
  if (state.selection.has(f.path)) card.classList.add("selected");
  return card;
}

function renderFolders(data) {
  const sec = $("#folderSection"), grid = $("#folderGrid");
  grid.innerHTML = "";
  const folders = sortItems(data.folders || []);
  if (!folders.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("#foldersTitle").textContent = data.isRoot ? "Library folders" : "Folders";
  for (const f of folders) grid.appendChild(folderCard(f));
}

/* ---- library sort / filter (client-side; the data already carries the fields) ---- */
const watchedFrac = (v) => { const p = state.progress[v.path]; return p && p.duration ? p.position / p.duration : 0; };
const isWatched = (v) => watchedFrac(v) >= 0.95;
function sortItems(items) {
  const arr = (items || []).slice();
  switch (state.sort) {
    case "recent":
    case "date":     arr.sort((a, b) => (b.mtime || 0) - (a.mtime || 0)); break;
    case "size":     arr.sort((a, b) => (b.size || 0) - (a.size || 0)); break;
    case "duration": arr.sort((a, b) => (b.duration || 0) - (a.duration || 0)); break;
    default: { const nm = (x) => x.display || x.name || "";   // videos: cleaned title · folders: raw name
               arr.sort((a, b) => nm(a).localeCompare(nm(b), undefined, { numeric: true, sensitivity: "base" })); }
  }
  return arr;
}
function filterVideos(vids) {
  switch (state.filter) {
    case "unwatched": return vids.filter(v => !isWatched(v));
    case "watched":   return vids.filter(v => isWatched(v));
    case "playable":  return vids.filter(v => v.playable);
    default:          return vids;
  }
}

// "My List" row on the home view (pinned shows / movies).
async function renderMyList() {
  const sec = $("#mylistSection"), grid = $("#mylistGrid");
  if (!sec) return;
  let items = [];
  try { items = await api("/api/mylist"); } catch {}
  state.mylist = new Set(items.map(i => i.path));
  if (!items.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  grid.innerHTML = "";
  for (const it of items) {
    grid.appendChild(it.isFolder
      ? folderCard({ name: it.name, path: it.path, videos: it.videos, subfolders: it.subfolders, watched: it.watched })
      : videoCard({ name: it.name, path: it.path, ext: it.ext, playable: it.playable, direct: it.direct, duration: it.duration }));
  }
}

function renderVideos(data) {
  const sec = $("#videoSection"), grid = $("#videoGrid");
  grid.innerHTML = "";
  const vids = data.videos || [];
  const sorted = sortItems(vids);
  state.queue = sorted.filter(v => v.playable);   // prev/next follows what you see
  if (!vids.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const nWatched = vids.filter(isWatched).length;
  $("#videosTitle").textContent = `Videos · ${vids.length}` + (nWatched ? ` · ${nWatched} watched` : "");
  const shown = filterVideos(sorted);
  if (!shown.length) {
    grid.appendChild(el("div", "muted small", "No videos match this filter."));
    return;
  }
  for (const v of shown) grid.appendChild(videoCard(v));
}

function videoCard(v, opts = {}) {
  const card = el("div", "video-card");
  card.dataset.vpath = v.path;
  card.dataset.path = v.path;
  const prog = state.progress[v.path];
  const frac = prog && prog.duration ? prog.position / prog.duration : 0;
  const watched = frac >= 0.95;                  // finished — show a Watched mark
  const pct = frac > 0 ? Math.min(100, frac * 100) : 0;  // orange line: how far in, every started episode
  if (watched) card.classList.add("watched");
  const durTxt = v.duration ? fmtTime(v.duration)
    : (opts.position != null ? fmtTime(opts.position) + " in" : "");
  card.innerHTML =
    `<button class="check" data-check>✓</button>
     ${opts.continueCard ? `<button class="card-dismiss" data-dismiss title="Remove from Continue watching" aria-label="Remove from Continue watching">${ICON.close}</button>` : ""}
     ${myListBtn(v.path)}
     <div class="thumb">
       <div class="ph">${ICON.film}</div>
       <img alt="" style="opacity:0;transition:opacity .2s" />
       ${!v.playable ? `<span class="badge" title="May not play natively in the browser">${escapeHtml((v.ext || "").replace(".", ""))}</span>` : ""}
       ${watched ? `<span class="watched-badge" title="You've finished watching this">${ICON.check}<span>Watched</span></span>` : ""}
       <span class="dur">${escapeHtml(durTxt)}</span>
       <div class="play-ic"><span>${ICON.play}</span></div>
       ${pct > 0 ? `<div class="resume"><i style="width:${pct}%"></i></div>` : ""}
     </div>
     <div class="vcard-foot">
       <div class="vcard-name">${escapeHtml(dispName(v))}</div>
       <div class="vcard-sub">${escapeHtml(fmtSize(v.size))}</div>
     </div>`;
  if (!v.duration) card.dataset.needsMeta = "1";
  card.onclick = (ev) => {
    if (ev.target.closest("[data-dismiss]")) { dismissContinue(v.path); return; }
    if (ev.target.closest("[data-mylist]")) { toggleMyList(v.path, v.name, ev.target.closest("[data-mylist]")); return; }
    if (ev.shiftKey || ev.target.closest("[data-check]")) { toggleSelect(card, v.path, v.name, false); return; }
    if (state.selection.size) clearSelection();   // a plain click clears any selection, then plays
    if (!v.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(v);
  };
  card.oncontextmenu = (ev) => openContextMenu(ev, { card, path: v.path, name: v.name, isFolder: false, item: v });
  if (state.selection.has(v.path)) card.classList.add("selected");
  thumbObserver.observe(card);
  attachHoverPreview(card, v);                     // storyboard preview-on-hover
  return card;
}

async function renderContinue() {
  const sec = $("#continueSection"), grid = $("#continueGrid");
  let items = [];
  try { items = await api("/api/continue"); } catch {}
  if (!items.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  grid.innerHTML = "";
  for (const v of items) {
    state.progress[v.path] = { position: v.position, duration: v.duration };
    grid.appendChild(videoCard(v, { position: v.position, continueCard: true }));
  }
}

/* ---- mark watched / unwatched + dismiss a Continue-watching card (#10) ---- */
// "Watched" is otherwise derived from ≥95% progress; these let you set it by hand.
async function markWatched(path, dur) {
  const d = dur || (state.progress[path] && state.progress[path].duration) || 0;
  if (!d) { toast("Can't mark watched until its length is known.", "err"); return; }
  state.progress[path] = { position: d, duration: d };
  try {
    await api("/api/progress", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, position: d, duration: d }) });
    toast("Marked as watched", "ok");
  } catch { toast("Couldn't save that.", "err"); }
  refreshLibrary();
}
async function clearProgressFor(path) {
  delete state.progress[path];
  try {
    await api("/api/progress/clear", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }) });
  } catch { toast("Couldn't save that.", "err"); return false; }
  return true;
}
async function markUnwatched(path) {
  if (await clearProgressFor(path)) toast("Marked as unwatched", "ok");
  refreshLibrary();
}
async function dismissContinue(path) {
  if (await clearProgressFor(path)) { await renderContinue(); }
}
// Re-render the current library view in place (after a progress change).
function refreshLibrary() {
  if (state.searchActive || !state.data) return;
  renderFolders(state.data);
  renderVideos(state.data);
  if (state.data.isRoot) renderContinue();
}

function renderEmpty(data) {
  const empty = $("#emptyState");
  empty.innerHTML = "";
  const nothing = !(data.folders || []).length && !(data.videos || []).length;
  if (data.isRoot && !(data.folders || []).length) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "No library folders yet"));
    empty.appendChild(el("p", "muted", state.session.canManage
      ? "Add a folder that holds your shows and movies to get started."
      : "This instance has no shared folders."));
    if (state.session.canManage) {
      const btn = el("button", "btn primary", `${ICON.folderOpen}<span>Add a folder</span>`);
      btn.onclick = addFolder;
      empty.appendChild(btn);
    }
  } else if (nothing) {
    empty.classList.remove("hidden");
    empty.appendChild(el("h2", null, "Nothing here"));
    empty.appendChild(el("p", "muted", "This folder has no videos or subfolders."));
  } else {
    empty.classList.add("hidden");
  }
}

