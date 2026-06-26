"use strict";

/* ===================== tiny helpers ===================== */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const enc = encodeURIComponent;

async function api(path, opts = {}) {
  opts.headers = { "X-Kinema": "1", ...(opts.headers || {}) };
  const r = await fetch(path, opts);
  if (r.status === 401) {
    let e = {};
    try { e = await r.json(); } catch {}
    if (e.needAuth) { showLogin(); throw new Error("Authentication required"); }
  }
  if (!r.ok) {
    let e = {};
    try { e = await r.json(); } catch {}
    throw new Error(e.error || e.message || `HTTP ${r.status}`);
  }
  return r.json();
}

function fmtTime(s) {
  if (!s || isNaN(s)) s = 0;
  s = Math.floor(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
}
function fmtSize(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(b < 10 && i > 0 ? 1 : 0) + " " + u[i];
}

let toastTimer;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3200);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function prettyName(name) { return name.replace(/\.[^.]+$/, ""); }

/* ===================== state ===================== */
const state = {
  path: null,
  data: null,
  progress: {},
  session: { authRequired: false, authed: true, readonly: false, canManage: true, canBrowse: true, ffmpeg: false, urls: [] },
  organize: false,
  selection: new Map(),
  queue: [],
  qIndex: -1,
  autoNext: true,
};

/* ===================== thumbnails (lazy) ===================== */
const thumbObserver = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const node = e.target;
    thumbObserver.unobserve(node);
    const p = node.dataset.vpath;
    const img = $("img", node);
    if (img && p) {
      img.src = `/api/thumb?path=${enc(p)}`;
      img.onload = () => { img.style.opacity = 1; $(".ph", node)?.remove(); };
    }
    if (node.dataset.needsMeta === "1") {
      api(`/api/meta?path=${enc(p)}`).then(m => {
        if (m && m.duration) {
          const badge = $(".dur", node);
          if (badge) badge.textContent = fmtTime(m.duration);
        }
      }).catch(() => {});
    }
  }
}, { rootMargin: "300px" });

/* ===================== library rendering ===================== */
async function loadLibrary(path) {
  state.path = path || null;
  try { state.progress = await api("/api/progress"); } catch { state.progress = {}; }

  let data;
  try {
    data = await api(`/api/library${path ? "?path=" + enc(path) : ""}`);
  } catch (e) { toast(e.message, "err"); return; }
  state.data = data;
  clearSelection();
  renderBreadcrumb(data);
  renderFolders(data);
  renderVideos(data);
  if (data.isRoot) await renderContinue();
  else $("#continueSection").classList.add("hidden");
  renderEmpty(data);
  window.scrollTo(0, 0);
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

function renderFolders(data) {
  const sec = $("#folderSection"), grid = $("#folderGrid");
  grid.innerHTML = "";
  const folders = data.folders || [];
  if (!folders.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("#foldersTitle").textContent = data.isRoot ? "Library folders" : "Folders";
  for (const f of folders) {
    const card = el("div", "folder-card");
    const bits = [];
    if (f.videos) bits.push(`${f.videos} video${f.videos > 1 ? "s" : ""}`);
    if (f.subfolders) bits.push(`${f.subfolders} folder${f.subfolders > 1 ? "s" : ""}`);
    card.innerHTML =
      `<button class="check" data-check>✓</button>
       <div class="folder-ic">📁</div>
       <div class="folder-meta">
         <div class="folder-name">${escapeHtml(f.name)}</div>
         <div class="folder-sub">${bits.join(" · ") || "empty"}</div>
       </div>`;
    card.onclick = (ev) => {
      if (state.organize && ev.target.closest("[data-check]")) {
        toggleSelect(card, f.path, f.name, true);
      } else { loadLibrary(f.path); }
    };
    if (state.selection.has(f.path)) card.classList.add("selected");
    grid.appendChild(card);
  }
}

function renderVideos(data) {
  const sec = $("#videoSection"), grid = $("#videoGrid");
  grid.innerHTML = "";
  const vids = data.videos || [];
  state.queue = vids.filter(v => v.playable);
  if (!vids.length) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("#videosTitle").textContent = `Videos · ${vids.length}`;
  for (const v of vids) grid.appendChild(videoCard(v));
}

function videoCard(v, opts = {}) {
  const card = el("div", "video-card");
  card.dataset.vpath = v.path;
  const prog = state.progress[v.path];
  const pct = prog && prog.duration ? Math.min(100, (prog.position / prog.duration) * 100) : 0;
  const durTxt = v.duration ? fmtTime(v.duration)
    : (opts.position != null ? fmtTime(opts.position) + " in" : "");
  card.innerHTML =
    `<button class="check" data-check>✓</button>
     <div class="thumb">
       <div class="ph">🎬</div>
       <img alt="" style="opacity:0;transition:opacity .2s" />
       ${!v.playable ? `<span class="badge" title="May not play natively in the browser">${escapeHtml(v.ext.replace(".", ""))}</span>` : ""}
       <span class="dur">${escapeHtml(durTxt)}</span>
       <div class="play-ic"><span>▶</span></div>
       ${pct > 0 ? `<div class="resume"><i style="width:${pct}%"></i></div>` : ""}
     </div>
     <div class="vcard-foot">
       <div class="vcard-name">${escapeHtml(prettyName(v.name))}</div>
       <div class="vcard-sub">${escapeHtml(fmtSize(v.size))}</div>
     </div>`;
  if (!v.duration) card.dataset.needsMeta = "1";
  card.onclick = () => {
    if (state.organize) { toggleSelect(card, v.path, v.name, false); return; }
    if (!v.playable) toast("This file type may not play in the browser. Try converting to MP4/WebM.", "err");
    openPlayer(v);
  };
  if (state.selection.has(v.path)) card.classList.add("selected");
  thumbObserver.observe(card);
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
    grid.appendChild(videoCard(v, { position: v.position }));
  }
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
      const btn = el("button", "btn primary", "📂 Add a folder");
      btn.onclick = () => { openSettings(); if (state.session.canBrowse) openFolderPicker(); };
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

/* ===================== organize mode ===================== */
function toggleOrganize() {
  if (!state.session.canManage) return;
  state.organize = !state.organize;
  document.body.classList.toggle("organize", state.organize);
  $("#organizebar").classList.toggle("hidden", !state.organize);
  $("#organizeToggle").classList.toggle("active", state.organize);
  clearSelection();
}
function toggleSelect(card, path, name, isFolder) {
  if (state.selection.has(path)) { state.selection.delete(path); card.classList.remove("selected"); }
  else { state.selection.set(path, { name, isFolder }); card.classList.add("selected"); }
  updateOrganizeBar();
}
function clearSelection() {
  state.selection.clear();
  $$(".video-card.selected, .folder-card.selected").forEach(c => c.classList.remove("selected"));
  updateOrganizeBar();
}
function updateOrganizeBar() {
  const n = state.selection.size;
  $("#selCount").textContent = `${n} selected`;
  $("#opRename").disabled = n !== 1;
  $("#opMove").disabled = n === 0;
  $("#opDelete").disabled = n === 0;
}

async function runOp(payload) {
  return api("/api/op", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function doRename() {
  const [path, info] = [...state.selection.entries()][0];
  const cur = info.name;
  openDialog("Rename", `<label>New name</label><input type="text" id="dlgInput" value="${escapeHtml(cur)}" />`,
    async () => {
      const name = $("#dlgInput").value.trim();
      if (!name) return false;
      const r = await runOp({ action: "rename", path, name });
      if (r.ok) { toast("Renamed", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => { const i = $("#dlgInput"); i.focus(); i.setSelectionRange(0, prettyName(cur).length); }, 50);
}

async function doDelete() {
  const items = [...state.selection.values()];
  const names = items.slice(0, 6).map(i => i.name).join(", ") + (items.length > 6 ? `, +${items.length - 6} more` : "");
  openDialog("Delete to trash",
    `<p>Move <b>${items.length}</b> item(s) to the library's <code>.kinema-trash</code> folder?</p>
     <p class="muted small">${escapeHtml(names)}</p>
     <p class="muted small">Nothing is permanently erased — you can restore from the trash folder on disk.</p>`,
    async () => {
      let ok = 0, fail = 0;
      for (const [path] of state.selection) {
        const r = await runOp({ action: "delete", path });
        r.ok ? ok++ : fail++;
      }
      toast(`Moved ${ok} to trash${fail ? `, ${fail} failed` : ""}`, fail ? "err" : "ok");
      loadLibrary(state.path); return true;
    });
}

async function doNewFolder() {
  if (state.data?.isRoot) { toast("Open a library folder first, then create folders inside it.", "err"); return; }
  openDialog("New folder", `<label>Folder name</label><input type="text" id="dlgInput" placeholder="Season 1" />`,
    async () => {
      const name = $("#dlgInput").value.trim();
      if (!name) return false;
      const r = await runOp({ action: "mkdir", path: state.path, name });
      if (r.ok) { toast("Folder created", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => $("#dlgInput")?.focus(), 50);
}

async function doMove() {
  let pickerPath = state.path;
  openDialog("Move to…", `<div id="pickerWrap"></div>`, async () => {
    if (!pickerPath) { toast("Pick a destination folder.", "err"); return false; }
    let ok = 0, fail = 0;
    for (const [path] of state.selection) {
      if (path === pickerPath) { fail++; continue; }
      const r = await runOp({ action: "move", path, dest: pickerPath });
      r.ok ? ok++ : fail++;
    }
    toast(`Moved ${ok}${fail ? `, ${fail} failed` : ""}`, fail ? "err" : "ok");
    loadLibrary(state.path); return true;
  });

  async function drawPicker(p) {
    pickerPath = p;
    const wrap = $("#pickerWrap");
    let data;
    try { data = await api(`/api/library${p ? "?path=" + enc(p) : ""}`); }
    catch (e) { wrap.innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`; return; }
    const picker = el("div", "picker");
    if (!data.isRoot) {
      const parent = data.breadcrumb.length > 1 ? data.breadcrumb[data.breadcrumb.length - 2].path : null;
      const up = el("div", "p-row up", "⬆ Up one level");
      up.onclick = () => drawPicker(parent);
      picker.appendChild(up);
    }
    for (const f of data.folders) {
      const row = el("div", "p-row", `📁 ${escapeHtml(f.name)}`);
      row.onclick = () => drawPicker(f.path);
      picker.appendChild(row);
    }
    if (data.isRoot && !data.folders.length) picker.appendChild(el("div", "p-row up", "No library folders"));
    wrap.innerHTML = "";
    wrap.appendChild(picker);
    wrap.appendChild(el("div", "picker-cur", data.isRoot
      ? "Pick a folder to move into…" : `Destination: <b>${escapeHtml(data.path)}</b>`));
    $("#dialogOk").disabled = data.isRoot;
  }
  drawPicker(pickerPath);
}

/* ===================== generic dialog ===================== */
let dialogOkHandler = null;
function openDialog(title, bodyHtml, onOk) {
  $("#dialogTitle").textContent = title;
  $("#dialogBody").innerHTML = bodyHtml;
  $("#dialogOk").disabled = false;
  $("#dialogOk").textContent = "OK";
  dialogOkHandler = onOk;
  $("#dialog").classList.remove("hidden");
  const input = $("#dlgInput");
  if (input) input.addEventListener("keydown", e => { if (e.key === "Enter") $("#dialogOk").click(); });
}
function closeDialog() { $("#dialog").classList.add("hidden"); dialogOkHandler = null; }

/* ===================== folder picker (first-run / add folder) ===================== */
async function openFolderPicker() {
  if (!state.session.canBrowse) { toast("Folder browsing is disabled on this instance.", "err"); return; }
  let cur = null;
  openDialog("Choose a library folder", `<div id="fpWrap" class="fp-wrap"></div>`, async () => {
    if (!cur) return false;
    try {
      const cfg = await api("/api/config");
      const next = [...new Set([...(cfg.roots || []), cur])];
      await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
      toast("Folder added", "ok");
      await refreshSession();
      await renderRoots();
      loadLibrary(null);
      return true;
    } catch (e) { toast(e.message, "err"); return false; }
  });
  $("#dialogOk").textContent = "Add this folder";

  async function draw(p) {
    let data;
    try { data = await api(`/api/browse${p ? "?path=" + enc(p) : ""}`); }
    catch (e) { $("#fpWrap").innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`; return; }
    cur = data.path;
    const wrap = $("#fpWrap");
    wrap.innerHTML = "";

    if (data.shortcuts?.length) {
      const sc = el("div", "fp-shortcuts");
      data.shortcuts.forEach(s => {
        const b = el("button", "chip", escapeHtml(s.name));
        b.onclick = () => draw(s.path);
        sc.appendChild(b);
      });
      wrap.appendChild(sc);
    }
    const picker = el("div", "picker");
    if (data.parent) {
      const up = el("div", "p-row up", "⬆ Up");
      up.onclick = () => draw(data.parent);
      picker.appendChild(up);
    }
    for (const d of data.dirs) {
      const row = el("div", "p-row",
        `📁 ${escapeHtml(d.name)}${d.videos ? ` <span class="muted small">· ${d.videos} videos</span>` : ""}`);
      row.onclick = () => draw(d.path);
      picker.appendChild(row);
    }
    if (!data.dirs.length) picker.appendChild(el("div", "p-row up", "(no subfolders here)"));
    wrap.appendChild(picker);
    wrap.appendChild(el("div", "picker-cur", `Add: <b>${escapeHtml(data.path)}</b>`));
  }
  draw(null);
}

/* ===================== settings ===================== */
async function openSettings() {
  $("#settingsModal").classList.remove("hidden");
  renderUrls();
  await renderRoots();
}
function closeSettings() { $("#settingsModal").classList.add("hidden"); }

function renderUrls() {
  const list = $("#urlList");
  list.innerHTML = "";
  const urls = state.session.urls || [];
  if (urls.length <= 1) {
    list.innerHTML = `<p class="muted small">Localhost only. Restart Kinema with <code>--lan</code> to watch from your phone or TV.</p>`;
  }
  for (const u of urls) {
    const row = el("div", "url-row");
    const a = el("a", null, escapeHtml(u));
    a.href = u; a.target = "_blank"; a.rel = "noopener";
    row.appendChild(a);
    list.appendChild(row);
  }
}

async function renderRoots() {
  let cfg;
  try { cfg = await api("/api/config"); } catch { cfg = { roots: [] }; }
  const list = $("#rootList");
  list.innerHTML = "";
  if (!cfg.roots.length) list.innerHTML = `<p class="muted small">No folders added yet.</p>`;
  for (const r of cfg.roots) {
    const row = el("div", "root-row");
    row.innerHTML = `<span class="path">${escapeHtml(r)}</span>`;
    if (state.session.canManage) {
      const rm = el("button", "rm", "✕");
      rm.title = "Remove";
      rm.onclick = async () => {
        const next = cfg.roots.filter(x => x !== r);
        await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
        await refreshSession();
        await renderRoots();
        loadLibrary(null);
      };
      row.appendChild(rm);
    }
    list.appendChild(row);
  }
}

async function addRoot() {
  const input = $("#rootInput");
  const p = input.value.trim();
  if (!p) return;
  try {
    const cfg = await api("/api/config");
    const next = [...new Set([...cfg.roots, p])];
    const res = await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
    if ((res.roots || []).some(r => r === p || r.endsWith(p.replace(/[\/\\]+$/, "").split(/[\/\\]/).pop()))) {
      $("#settingsStatus").textContent = ""; input.value = "";
    } else {
      $("#settingsStatus").textContent = `Could not add "${p}" — is it a valid folder path on the server?`;
    }
    await renderRoots();
    loadLibrary(null);
  } catch (e) { $("#settingsStatus").textContent = e.message; }
}

/* ===================== login ===================== */
function showLogin() { $("#loginOverlay").classList.remove("hidden"); setTimeout(() => $("#loginPassword")?.focus(), 50); }
function hideLogin() { $("#loginOverlay").classList.add("hidden"); }

/* ===================== player ===================== */
const video = $("#video");
let saveTimer = null, idleTimer = null, currentVideo = null, unloading = false;

function openPlayer(v) {
  currentVideo = v;
  state.qIndex = state.queue.findIndex(x => x.path === v.path);
  if (state.qIndex < 0) { state.queue = [v]; state.qIndex = 0; }

  $("#playerOverlay").classList.remove("hidden");
  $("#playerTitle").textContent = prettyName(v.name);
  document.title = prettyName(v.name) + " · Kinema";
  video.src = `/api/stream?path=${enc(v.path)}`;
  video.load();

  const resume = state.progress[v.path];
  video.onloadedmetadata = () => {
    if (resume && resume.position > 5 && resume.duration && resume.position < resume.duration * 0.97) {
      video.currentTime = resume.position;
    }
    updateTime();
  };
  video.play().then(() => maybeCoachPip()).catch(() => {});
  renderQueue();
  showUi();
}

function closePlayer() {
  saveProgress(true);
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("#playerOverlay").classList.add("hidden");
  document.title = "Kinema";
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  loadLibrary(state.path);
}

function playIndex(i) {
  if (i < 0 || i >= state.queue.length) return;
  saveProgress(true);
  openPlayer(state.queue[i]);
}

function renderQueue() {
  const list = $("#queueList");
  list.innerHTML = "";
  state.queue.forEach((v, i) => {
    const item = el("div", "q-item" + (i === state.qIndex ? " current" : ""));
    item.innerHTML = `<div class="q-thumb"><img src="/api/thumb?path=${enc(v.path)}" alt="" /></div>
      <div class="q-name">${escapeHtml(prettyName(v.name))}</div>`;
    item.onclick = () => playIndex(i);
    list.appendChild(item);
  });
  $(".q-item.current")?.scrollIntoView({ block: "nearest" });
}

function saveProgress() {
  if (!currentVideo || !video.duration) return;
  const body = JSON.stringify({ path: currentVideo.path, position: video.currentTime, duration: video.duration });
  // sendBeacon can't set the X-Kinema header, so only use it during real page
  // unload (best effort); every in-app save goes through fetch with the header.
  if (unloading && navigator.sendBeacon) {
    navigator.sendBeacon("/api/progress", new Blob([body], { type: "application/json" }));
  } else {
    fetch("/api/progress", { method: "POST", headers: { "Content-Type": "application/json", "X-Kinema": "1" }, body, keepalive: true }).catch(() => {});
  }
}

function togglePlay() { video.paused ? video.play() : video.pause(); }
function updateTime() {
  const cur = video.currentTime || 0, dur = video.duration || 0;
  $("#timeLabel").textContent = `${fmtTime(cur)} / ${fmtTime(dur)}`;
  if (dur) $("#seek").value = Math.round((cur / dur) * 1000);
}
function setSpeed(rate) {
  video.playbackRate = rate;
  $("#speedBtn").textContent = rate + "×";
  $$("#speedMenu button").forEach(b => b.classList.toggle("active", +b.dataset.rate === rate));
  $("#speedMenu").classList.add("hidden");
}
function showUi() {
  $("#playerOverlay").classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!video.paused) $("#playerOverlay").classList.add("idle"); }, 2600);
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
  if (localStorage.getItem("kinema_pip_seen")) return;
  localStorage.setItem("kinema_pip_seen", "1");
  setTimeout(showPipHint, 900);
}

function toggleFs() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("#playerOverlay").requestFullscreen().catch(() => {});
}

/* ===================== events ===================== */
function wire() {
  $("#brand").onclick = () => loadLibrary(null);
  $("#refreshBtn").onclick = () => loadLibrary(state.path);
  $("#settingsBtn").onclick = openSettings;
  $("#settingsClose").onclick = closeSettings;
  $("#organizeToggle").onclick = toggleOrganize;
  $("#addRootBtn").onclick = addRoot;
  $("#browseRootBtn").onclick = openFolderPicker;
  $("#rootInput").addEventListener("keydown", e => { if (e.key === "Enter") addRoot(); });

  $("#opNewFolder").onclick = doNewFolder;
  $("#opRename").onclick = doRename;
  $("#opMove").onclick = doMove;
  $("#opDelete").onclick = doDelete;
  $("#opClear").onclick = clearSelection;

  $("#dialogClose").onclick = closeDialog;
  $("#dialogCancel").onclick = closeDialog;
  $("#dialogOk").onclick = async () => {
    if (!dialogOkHandler) return closeDialog();
    const res = await dialogOkHandler();
    if (res !== false) closeDialog();
  };

  $("#playerClose").onclick = closePlayer;
  $("#playPause").onclick = togglePlay;
  $("#back10").onclick = () => { video.currentTime = Math.max(0, video.currentTime - 10); };
  $("#fwd10").onclick = () => { video.currentTime = Math.min(video.duration || 1e9, video.currentTime + 10); };
  $("#prevBtn").onclick = () => playIndex(state.qIndex - 1);
  $("#nextBtn").onclick = () => playIndex(state.qIndex + 1);
  $("#muteBtn").onclick = () => { video.muted = !video.muted; };
  $("#loopBtn").onclick = () => { video.loop = !video.loop; $("#loopBtn").classList.toggle("on", video.loop); };
  $("#pipBtn").onclick = togglePip;
  $("#fsBtn").onclick = toggleFs;
  $("#autoNext").onclick = () => {
    state.autoNext = !state.autoNext;
    $("#autoNext").classList.toggle("on", state.autoNext);
    $("#autoNext").textContent = state.autoNext ? "Auto ▶" : "Auto ✕";
  };
  $("#autoNext").classList.add("on");

  $("#speedBtn").onclick = () => $("#speedMenu").classList.toggle("hidden");
  $$("#speedMenu button").forEach(b => b.onclick = () => setSpeed(+b.dataset.rate));

  $("#seek").addEventListener("input", e => { if (video.duration) video.currentTime = (e.target.value / 1000) * video.duration; });
  $("#volume").addEventListener("input", e => {
    video.volume = +e.target.value; video.muted = false;
    localStorage.setItem("kinema_volume", e.target.value);
  });

  video.addEventListener("timeupdate", () => {
    updateTime();
    if (!saveTimer) saveTimer = setTimeout(() => { saveProgress(false); saveTimer = null; }, 5000);
  });
  video.addEventListener("play", () => { $("#playPause").textContent = "❚❚"; showUi(); });
  video.addEventListener("pause", () => { $("#playPause").textContent = "▶"; saveProgress(true); showUi(); });
  video.addEventListener("volumechange", () => {
    $("#muteBtn").textContent = video.muted || video.volume === 0 ? "🔇" : "🔊";
    $("#volume").value = video.muted ? 0 : video.volume;
  });
  video.addEventListener("ended", () => {
    saveProgress(true);
    if (state.autoNext && state.qIndex < state.queue.length - 1) playIndex(state.qIndex + 1);
  });
  video.addEventListener("error", () => {
    if (currentVideo && !currentVideo.playable)
      toast("Browser can't decode this file. Convert it to MP4 (H.264) or WebM.", "err");
  });

  const vol = localStorage.getItem("kinema_volume");
  if (vol != null) { video.volume = +vol; $("#volume").value = vol; }

  const overlay = $("#playerOverlay");
  overlay.addEventListener("mousemove", showUi);
  overlay.addEventListener("click", (e) => { if (e.target === video) togglePlay(); });

  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) $("#speedMenu").classList.add("hidden"); });
  $("#settingsModal").addEventListener("click", e => { if (e.target.id === "settingsModal") closeSettings(); });
  $("#dialog").addEventListener("click", e => { if (e.target.id === "dialog") closeDialog(); });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = $("#loginPassword").value;
    $("#loginError").textContent = "";
    try {
      const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json", "X-Kinema": "1" }, body: JSON.stringify({ password: pw }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.authed) { hideLogin(); $("#loginPassword").value = ""; await boot(); }
      else { $("#loginError").textContent = d.error || "Wrong password."; }
    } catch { $("#loginError").textContent = "Could not reach the server."; }
  });

  document.addEventListener("keydown", onKey);
  const onUnload = () => { unloading = true; saveProgress(); };
  window.addEventListener("pagehide", onUnload);
  window.addEventListener("beforeunload", onUnload);
}

function onKey(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
    if (e.key === "Escape") { closeDialog(); closeSettings(); }
    return;
  }
  const playerOpen = !$("#playerOverlay").classList.contains("hidden");
  if (e.key === "Escape") {
    if (!$("#dialog").classList.contains("hidden")) return closeDialog();
    if (!$("#settingsModal").classList.contains("hidden")) return closeSettings();
    if (playerOpen) return closePlayer();
    if (state.organize) return toggleOrganize();
  }
  if (!playerOpen) return;
  switch (e.key) {
    case " ": case "k": e.preventDefault(); togglePlay(); break;
    case "ArrowLeft": video.currentTime = Math.max(0, video.currentTime - 10); showUi(); break;
    case "ArrowRight": video.currentTime = Math.min(video.duration || 1e9, video.currentTime + 10); showUi(); break;
    case "j": video.currentTime = Math.max(0, video.currentTime - 30); break;
    case "l": video.loop = !video.loop; $("#loopBtn").classList.toggle("on", video.loop); break;
    case "ArrowUp": e.preventDefault(); video.volume = Math.min(1, video.volume + 0.05); video.muted = false; break;
    case "ArrowDown": e.preventDefault(); video.volume = Math.max(0, video.volume - 0.05); break;
    case "m": video.muted = !video.muted; break;
    case "f": toggleFs(); break;
    case "p": togglePip(); break;
    case "N": playIndex(state.qIndex + 1); break;
    case "P": playIndex(state.qIndex - 1); break;
    case "[": setSpeed(Math.max(0.25, +(video.playbackRate - 0.25).toFixed(2))); break;
    case "]": setSpeed(Math.min(3, +(video.playbackRate + 0.25).toFixed(2))); break;
  }
}

/* ===================== boot ===================== */
async function refreshSession() {
  try { state.session = await api("/api/session"); } catch {}
}
function applySession() {
  const s = state.session;
  document.body.classList.toggle("readonly", !s.canManage);
  $("#organizeToggle").classList.toggle("hidden", !s.canManage);
}
async function boot() {
  await refreshSession();
  if (state.session.authRequired && !state.session.authed) { showLogin(); return; }
  hideLogin();
  applySession();
  await loadLibrary(null);
}
(async function init() {
  wire();
  await boot();
})();
