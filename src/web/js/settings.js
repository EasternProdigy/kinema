"use strict";
/* settings.js — the Settings modal: status, network/LAN, shared password, roots
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== settings ===================== */
async function openSettings() {
  $("#settingsModal").classList.remove("hidden");
  renderKeybinds($("#settingsKbd"));   // same list as the "?" overlay (one source of truth)
  { const t = $("#keyHudToggle"); if (t) t.checked = state.keyHud; }
  { const t = $("#tvModeToggle"); if (t) t.checked = !!state.tvMode; }
  if (typeof renderCast === "function") renderCast();   // Chromecast status (opt-in)
  await refreshSession();   // re-check live server caps (LAN toggle, ffmpeg, …) without a page reload
  renderStatus();
  renderLan();
  renderUrls();
  // Library management is admin-only in accounts mode; hide that section for viewers.
  const libSec = $("#rootList")?.closest(".settings-section");
  if (libSec) libSec.classList.toggle("hidden", state.session.accounts && !state.session.canManage);
  if (state.session.canManage) await renderRoots();
  // Remote sources (native, no mount) — admin-only management, like library folders.
  const srcSec = $("#sourcesSection");
  if (srcSec) srcSec.classList.toggle("hidden", state.session.accounts && !state.session.canManage);
  if (typeof renderRemoteSources === "function" && state.session.canManage) await renderRemoteSources();
  if (typeof renderStorage === "function") await renderStorage();   // disk space, archiving savings, trash
  await renderTmdb();       // TMDB metadata + discovery (admins/owner only)
  renderAccount();          // your own account (accounts mode)
  await renderUsers();      // people management (admins, accounts mode)
  if (typeof renderParental === "function") await renderParental();   // parental controls
}
function closeSettings() { $("#settingsModal").classList.add("hidden"); }

/* ===================== storage (disk space · archiving · trash · sources) ===================== */
// Surfaces the storage subsystem in one place: free space per drive, how much
// archiving has reclaimed (+ any live encode job), the recoverable trash (with a
// one-click empty), the catalog size, and the remote-source count.
async function renderStorage() {
  const sec = $("#storageSection");
  if (!sec) return;
  let d = null;
  try { d = await api("/api/storage"); } catch { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const box = $("#storageControl");
  if (!box) return;
  const a = d.archive || {}, trash = d.trash || {}, cat = d.catalog || {};
  const titles = (cat.shows || 0) + (cat.movies || 0);

  const drives = (d.drives || []).map(dr => {
    const usedPct = dr.total ? Math.min(100, Math.max(2, (dr.used / dr.total) * 100)) : 0;
    const label = (dr.roots && dr.roots.length) ? dr.roots.join(", ") : dr.path;
    return `<div class="stor-drive">
        <div class="stor-drive-head"><span class="stor-drive-name">${escapeHtml(label)}</span>
          <span class="muted small"><b>${fmtSize(dr.free) || "0 B"}</b> free of ${fmtSize(dr.total) || "0 B"}</span></div>
        <div class="stor-bar" title="${fmtSize(dr.used)} used"><i style="width:${usedPct}%"></i></div>
      </div>`;
  }).join("") || `<p class="muted small">No library folders yet — add one to see disk usage.</p>`;

  const tiles = [
    ["archive", fmtSize(a.bytesSaved) || "0 B", "reclaimed by archiving"],
    ["film", String(a.filesArchived || 0), `file${a.filesArchived === 1 ? "" : "s"} archived`],
    ["film", String(titles), `title${titles === 1 ? "" : "s"} in your library`],
    ["trash", `${trash.items || 0}`, `in trash · ${fmtSize(trash.bytes) || "0 B"}`],
    ["globe", String(d.sources || 0), `remote source${d.sources === 1 ? "" : "s"}`],
  ].map(([ic, num, lbl]) =>
    `<div class="stor-tile"><span class="stor-ic" data-icon="${ic}"></span>
       <div><div class="stor-num">${escapeHtml(num)}</div><div class="stor-lbl muted small">${escapeHtml(lbl)}</div></div></div>`
  ).join("");

  // Archive status / live job line.
  let archLine = "";
  if (!a.available) {
    archLine = `<p class="muted small">Archiving needs ffmpeg with an efficient encoder (AV1/HEVC/H.264). It re-compresses titles you've finished, keeping them watchable, to reclaim disk.</p>`;
  } else {
    const job = a.active;
    if (job && (job.state === "running" || job.state === "queued")) {
      const pct = Math.round(job.percent || 0);
      archLine = `<p class="stor-job"><span class="stor-spin"></span> ${escapeHtml(job.name || "Archiving")} — ${job.state === "queued" ? "queued" : `compressing ${(job.doneCount || 0) + 1} of ${job.total || "?"} · ${pct}%`}${a.queue ? ` <span class="muted small">(+${a.queue} queued)</span>` : ""}</p>`;
    } else {
      archLine = `<p class="muted small">Encoder: <b>${escapeHtml(a.encoder || a.codec || "ready")}</b>. Originals are kept in <code>${escapeHtml(a.keepOriginal === "delete" ? "deleted" : a.keepOriginal === "keep" ? "kept" : "trash (recoverable)")}</code>. Archive a finished title from its page (⋯ menu) to reclaim space.</p>`;
    }
  }

  box.innerHTML = `<div class="stor-drives">${drives}</div>
    <div class="stor-tiles">${tiles}</div>
    ${archLine}
    <div class="stor-actions"></div>`;

  const actions = $(".stor-actions", box);
  if ((trash.items || 0) > 0 && state.session.canManage) {
    const empty = el("button", "btn ghost", `${ICON.trash}<span>Empty trash (${fmtSize(trash.bytes) || trash.items})</span>`);
    empty.onclick = () => emptyTrash();
    actions.appendChild(empty);
  }
  applyIcons(box);
}

// Permanently clear the per-root .kadmu-trash folders (after a confirm), then refresh.
function emptyTrash() {
  openDialog("Empty trash",
    `<p>Permanently delete everything in the library's <code>.kadmu-trash</code> folders?</p>
     <p class="muted small">This can't be undone. (Deleted items move to trash first and auto-purge on their own after a while.)</p>`,
    async () => {
      try {
        const r = await api("/api/op", { method: "POST", body: JSON.stringify({ action: "empty-trash" }) });
        toast(r && r.message ? r.message : "Trash emptied", "ok");
      } catch (e) { toast(e.message, "err"); }
      renderStorage();
      return true;
    });
}

function renderUrls() {
  const list = $("#urlList");
  list.innerHTML = "";
  const urls = state.session.urls || [];
  // one link only: the network address for other devices (fall back to localhost)
  const shareUrl = urls.find(u => !u.includes("127.0.0.1")) || urls[0];
  const onNetwork = !!shareUrl && !shareUrl.includes("127.0.0.1");
  if (!onNetwork) {
    list.appendChild(el("p", "muted small lan-note", state.session.canToggleLan
      ? `Just this computer for now. Turn on <b>Share on your network</b> above to get a link for your phone or TV.`
      : `Localhost only. Restart Kadmu with <code>--lan</code> to watch from your phone or TV on the same Wi-Fi.`));
  } else {
    const card = el("div", "url-qr");
    let svg = "";
    try { if (typeof KadmuQR !== "undefined") svg = KadmuQR.svg(shareUrl); } catch { svg = ""; }
    if (svg) { const fig = el("div", "qr-img"); fig.innerHTML = svg; card.appendChild(fig); }
    const meta = el("div", "qr-meta");
    meta.appendChild(el("span", "qr-hint", "Point your phone camera here"));
    const a = el("a", "url-link", escapeHtml(shareUrl));
    a.href = shareUrl; a.target = "_blank"; a.rel = "noopener";
    meta.appendChild(a);
    const copy = el("button", "btn qr-copy", "Copy link");
    copy.type = "button";
    copy.onclick = (e) => { e.preventDefault(); copyText(shareUrl); };
    meta.appendChild(copy);
    card.appendChild(meta);
    list.appendChild(card);
  }
  renderPasswordControl(list);   // set / change / remove the access password, right here
  applyIcons(list);
}

async function renderRoots() {
  let cfg;
  try { cfg = await api("/api/config"); } catch { cfg = { roots: [] }; }
  const list = $("#rootList");
  list.innerHTML = "";
  const roots = cfg.roots || [];
  const countEl = $("#rootCount");
  if (countEl) countEl.textContent = roots.length ? `${roots.length} folder${roots.length === 1 ? "" : "s"}` : "";
  if (!roots.length) {
    list.innerHTML = `<div class="root-empty muted small">No folders yet — add one below to start watching.</div>`;
    return;
  }
  for (const r of roots) {
    const name = r.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || r;
    const row = el("div", "root-row");
    row.innerHTML =
      `<span class="root-ic" data-icon="folder"></span>` +
      `<span class="root-meta"><span class="root-name">${escapeHtml(name)}</span>` +
      `<span class="root-path">${escapeHtml(r)}</span></span>`;
    if (state.session.canManage) {
      const rm = el("button", "rm");
      rm.dataset.icon = "close";
      rm.title = "Remove from library";
      rm.onclick = async () => {
        const next = roots.filter(x => x !== r);
        await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
        await refreshSession();
        await renderRoots();
        loadLibrary(null);
      };
      row.appendChild(rm);
    }
    list.appendChild(row);
  }
  applyIcons(list);
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

/* ----- settings: TMDB metadata + discovery ----- */
// The optional metadata layer: paste a TMDB key, match the library, watch progress.
// Owner/admin only (it sets an instance-wide key and makes outbound calls).
async function renderTmdb() {
  const sec = $("#tmdbSection");
  if (!sec) return;
  const canManage = state.session.canManage;
  sec.classList.toggle("hidden", !canManage);
  if (!canManage) return;
  let st = null;
  try { st = await api("/api/tmdb/status"); } catch { st = null; }
  renderTmdbControl(st);
}

function renderTmdbControl(st) {
  const box = $("#tmdbControl");
  if (!box) return;
  st = st || {};
  const enabled = !!st.enabled;
  const pct = (enabled && st.total) ? Math.round((st.matched / st.total) * 100) : 0;
  const countEl = $("#tmdbCount");
  if (countEl) countEl.textContent = (enabled && st.ready) ? `${st.matched}/${st.total} matched` : "";
  const statusLine = enabled
    ? (st.ready
        ? `${st.matched} of ${st.total} titles matched${st.building ? " · matching now…" : (st.unmatched ? " · " + st.unmatched + " to go" : " · all set")}`
        : "Connected — waiting for your library to finish indexing…")
    : "No key yet — recommendations use your ratings + filenames only.";
  box.innerHTML = `
    <div class="tmdb-status">
      <span class="tmdb-dot ${enabled ? "on" : "off"}"></span>
      <span class="tmdb-state">${enabled ? "TMDB connected" : "TMDB off"}</span>
      <span class="muted small">— ${escapeHtml(statusLine)}</span>
    </div>
    ${(enabled && st.total) ? `<div class="tmdb-bar"><i style="width:${pct}%"></i></div>` : ""}
    <div class="tmdb-form">
      <input type="password" id="tmdbKeyInput" autocomplete="off" spellcheck="false"
             placeholder="${enabled ? "Replace TMDB API key" : "Paste your TMDB API key (v3 key or v4 token)"}" />
      <button class="btn primary" id="tmdbKeySave">Save key</button>
      ${enabled ? `<button class="btn ghost" id="tmdbKeyClear">Remove</button>` : ""}
    </div>
    <p class="muted small">Get a free key at <a href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener">themoviedb.org</a> — it's stored on this server only and never shared.</p>
    ${enabled ? `<div class="tmdb-actions">
      <button class="btn" id="tmdbMatch">Match my library</button>
      <button class="btn ghost" id="tmdbRematch">Re-match everything</button>
      <span id="tmdbMsg" class="muted small"></span>
    </div>` : ""}
    ${enabled ? tmdbAttribution() : ""}`;
  $("#tmdbKeySave").onclick = () => saveTmdbKey($("#tmdbKeyInput").value);
  $("#tmdbKeyInput").addEventListener("keydown", e => { if (e.key === "Enter") saveTmdbKey(e.target.value); });
  const clr = $("#tmdbKeyClear"); if (clr) clr.onclick = () => saveTmdbKey("");
  const m = $("#tmdbMatch"); if (m) m.onclick = () => triggerEnrich(false);
  const rm = $("#tmdbRematch"); if (rm) rm.onclick = () => triggerEnrich(true);
}

async function saveTmdbKey(key) {
  key = (key || "").trim();
  try {
    const r = await api("/api/tmdb/key", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    if (r && r.ok === false) { toast(r.error || "Couldn't save key.", "err"); return; }
    toast(key ? "TMDB key saved — matching your library…" : "TMDB key removed", "ok");
    await refreshSession();
    renderTmdbControl(r.status);
    if (key) pollTmdb();
  } catch (e) { toast(e.message, "err"); }
}

async function triggerEnrich(force) {
  const msg = $("#tmdbMsg"); if (msg) msg.textContent = force ? "Re-matching everything…" : "Matching…";
  try {
    await api("/api/tmdb/enrich", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: !!force }),
    });
    pollTmdb();
  } catch (e) { toast(e.message, "err"); }
}

let _tmdbPoll = null;
// Refresh the matched-count + progress bar while the worker is busy (stops when it's
// idle, the modal closes, or after a sane number of ticks).
function pollTmdb() {
  if (_tmdbPoll) { clearTimeout(_tmdbPoll); _tmdbPoll = null; }
  let tries = 0;
  const tick = async () => {
    let st = null;
    try { st = await api("/api/tmdb/status"); } catch { /* ignore */ }
    if (st) renderTmdbControl(st);
    tries++;
    const open = !$("#settingsModal").classList.contains("hidden");
    const working = st && (st.building || (st.ready && st.matched < st.total));
    if (open && working && tries < 90) _tmdbPoll = setTimeout(tick, 2000);
  };
  tick();
}

/* ----- settings: server status tiles ----- */
function statTile(icon, label, value, tone) {
  const dot = tone ? `<i class="stat-dot tone-${tone}"></i>` : "";
  return `<div class="stat-tile">` +
    `<span class="stat-ic" data-icon="${icon}"></span>` +
    `<span class="stat-text"><span class="stat-label">${label}</span>` +
    `<span class="stat-value">${dot}${value}</span></span></div>`;
}

function renderStatus() {
  const s = state.session;
  const ver = escapeHtml(s.version || "1.0.0");
  const verEl = $("#settingsVersion");
  if (verEl) verEl.textContent = ver;
  const lan = !!s.lan;
  const tiles = [
    statTile("info", "Version", `Kadmu ${ver}`, ""),
    statTile("film", "Media engine", s.ffmpeg ? "ffmpeg ready" : "ffmpeg not found", s.ffmpeg ? "ok" : "off"),
    s.readonly
      ? statTile("lock", "Library", "Read-only", "warn")
      : statTile("rename", "Library", "Read &amp; write", "ok"),
    statTile("globe", "Network", lan ? "Shared on your network" : "This computer only", lan ? "warn" : "ok"),
    s.accounts
      ? statTile("user", "Account",
          s.user ? `${escapeHtml(s.user.name || s.user.username)} · ${s.role === "admin" ? "Admin" : "Viewer"}` : "Signed out",
          "ok")
      : statTile("lock", "Password", s.authRequired ? "Protected" : "Off", s.authRequired ? "ok" : "off"),
  ];
  if (s.dlna) {
    tiles.push(statTile("devices", "Play on TV (DLNA)",
      `On — find “${escapeHtml(s.dlnaName || "Kadmu")}” on your TV`, "ok"));
  }
  const grid = $("#statGrid");
  if (grid) { grid.innerHTML = tiles.join(""); applyIcons(grid); }
}

function copyText(t) {
  const ok = () => toast("Link copied", "ok");
  const fail = () => toast("Couldn\'t copy — select the link and copy it manually.", "err");
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(ok, fail);
    } else { fail(); }
  } catch { fail(); }
}

/* ----- settings: network sharing (LAN) toggle ----- */
function renderLan() {
  const box = $("#lanControl");
  if (!box) return;
  box.innerHTML = "";
  const s = state.session;
  if (!s.canToggleLan) return;   // explicit --host bind, or no management rights
  const on = !!s.lan;
  const row = el("div", "lan-row");
  row.innerHTML =
    `<span class="lan-ic" data-icon="globe"></span>` +
    `<span class="lan-text"><span class="lan-title">Share on your network</span>` +
    `<span class="lan-desc">${on
      ? "On — anyone on your Wi-Fi can open the links below."
      : "Off — only this computer can watch right now."}</span></span>`;
  const sw = el("button", "switch" + (on ? " on" : ""));
  sw.type = "button";
  sw.setAttribute("role", "switch");
  sw.setAttribute("aria-checked", on ? "true" : "false");
  sw.title = on ? "Turn network sharing off" : "Turn network sharing on";
  sw.innerHTML = `<span class="knob"></span>`;
  sw.onclick = () => toggleLan(!on);
  row.appendChild(sw);
  box.appendChild(row);
  if (on && !s.authRequired) {
    box.appendChild(el("p", "lan-warn small",
      `Heads up: no password is set, so anyone on your network can also rename, move and delete files. Set one below to lock that down.`));
  }
  applyIcons(box);
}

async function toggleLan(on) {
  const box = $("#lanControl");
  try {
    const r = await api("/api/lan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    });
    if (r && r.ok === false) { toast(r.error || "Could not change network sharing.", "err"); return; }
    await refreshSession();
    renderStatus(); renderLan(); renderUrls();
    toast(on ? "Network sharing is on" : "Network sharing is off", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ----- settings: access password (set / change / remove inline) ----- */
function renderPasswordControl(host) {
  if (!state.session.canSetPassword) return;
  const on = !!state.session.authRequired;
  const box = el("div", "net-auth");
  box.innerHTML =
    `<div class="net-auth-head">
       <span class="net-auth-ic" data-icon="lock"></span>
       <span class="net-auth-text">
         <span class="net-auth-title">Password</span>
         <span class="net-auth-desc">${on
           ? "On — anyone opening a link must enter it."
           : "Off — anyone with a link can watch &amp; manage."}</span>
       </span>
       <span class="net-auth-pill${on ? " on" : ""}">${on ? "Protected" : "Open"}</span>
     </div>
     <div class="net-auth-form">
       <input type="password" id="netPwInput" autocomplete="new-password"
              placeholder="${on ? "New password" : "Set a password"}" />
       <button class="btn primary" id="netPwSet">${on ? "Update" : "Set"}</button>
       ${on ? `<button class="btn ghost" id="netPwClear">Remove</button>` : ""}
     </div>`;
  host.appendChild(box);
  $("#netPwSet").onclick = () => setNetworkPassword($("#netPwInput").value);
  const clr = $("#netPwClear");
  if (clr) clr.onclick = () => setNetworkPassword("");
  $("#netPwInput").addEventListener("keydown", e => { if (e.key === "Enter") setNetworkPassword(e.target.value); });
}

async function setNetworkPassword(pw) {
  pw = pw || "";
  try {
    const r = await api("/api/password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    if (r && r.ok === false) { toast(r.error || "Could not update the password.", "err"); return; }
    await refreshSession();
    renderStatus(); renderLan(); renderUrls();
    toast(pw ? "Password set" : "Password removed", "ok");
  } catch (e) { toast(e.message, "err"); }
}


/* ----- settings: parental controls (per-profile / per-user maturity ceiling) ----- */
// Profiles mode: anyone managing can set each kid profile's limit + PIN (family trust
// model). Accounts mode: admins set each user's limit. Levels come from /api/session.
async function renderParental() {
  const sec = $("#parentalSection"), box = $("#parentalControl");
  if (!sec || !box) return;
  const s = state.session;
  // When profiles are on (household or pure-profiles) ANY viewer manages their own
  // sub-profiles (the parent sets the kids' limits). In pure-accounts mode the section
  // sets per-USER limits, which stays admin-only.
  const show = !!(s.profiles || (s.accounts && s.canManage));
  sec.classList.toggle("hidden", !show);
  if (!show) { box.innerHTML = ""; return; }
  const levels = s.maturityLevels || [];
  const optsFor = (cur) => levels.map(l => {
    const [lvl, label, covers] = l;
    return `<option value="${lvl}"${Number(cur) === lvl ? " selected" : ""}>${escapeHtml(label)}${covers ? " — " + escapeHtml(covers) : ""}</option>`;
  }).join("");

  // the full library list, so a profile/user can be scoped to a subset of folders
  let allRoots = [];
  try { allRoots = (await api("/api/config")).roots || []; } catch {}

  box.innerHTML = "";
  if (!s.tmdb) {
    box.appendChild(el("p", "muted small", "Turn on the TMDB metadata layer above to get content ratings — without it, a kids limit hides everything unrated. (Library scoping below works regardless.)"));
  }

  if (s.profiles) {
    let data; try { data = await api("/api/profiles"); } catch { data = { profiles: [] }; }
    const profs = (data.profiles || []).filter(p => p.id !== "default");
    if (!profs.length) {
      box.appendChild(el("p", "muted small", "Add a profile (avatar, top-right) — then set its maturity limit, libraries and an optional PIN here."));
      return;
    }
    for (const p of profs) {
      const row = el("div", "parental-row");
      row.innerHTML =
        `<span class="parental-name">${escapeHtml(p.name)}</span>
         <select class="lib-select" data-pid="${escapeHtml(p.id)}" aria-label="Maturity for ${escapeHtml(p.name)}">${optsFor(p.maturity)}</select>
         <input type="password" class="parental-pin" data-pid="${escapeHtml(p.id)}" autocomplete="new-password" inputmode="numeric" maxlength="12"
                placeholder="${p.pin ? "PIN set — type to change" : "Set a PIN (optional)"}" />
         ${p.pin ? `<button class="btn ghost mini parental-pin-clear" type="button" data-pid="${escapeHtml(p.id)}">Clear PIN</button>` : ""}
         <button class="btn ghost mini parental-remove" type="button" data-pid="${escapeHtml(p.id)}" data-name="${escapeHtml(p.name)}" title="Remove this profile">${ICON.trash || "Remove"}</button>
         ${libsControl(allRoots, p.roots, "pid", p.id)}`;
      box.appendChild(row);
    }
    box.onchange = (e) => {
      const sel = e.target.closest("select[data-pid]");
      if (sel) return saveParentalProfile(sel.dataset.pid, { maturity: parseInt(sel.value, 10) });
      const libs = e.target.closest(".parental-libs[data-pid]");
      if (libs) saveParentalProfile(libs.dataset.pid, { roots: collectLibs(libs, allRoots) });
    };
    $$(".parental-pin", box).forEach(inp => inp.addEventListener("keydown", e => {
      if (e.key === "Enter") saveParentalProfile(inp.dataset.pid, { pin: inp.value }).then(() => { inp.value = ""; renderParental(); });
    }));
    $$(".parental-pin-clear", box).forEach(b => b.onclick = () => saveParentalProfile(b.dataset.pid, { pin: "" }).then(renderParental));
    $$(".parental-remove", box).forEach(b => b.onclick = () => removeProfile(b.dataset.pid, b.dataset.name));
    applyIcons(box);
  } else if (s.accounts) {
    let data; try { data = await api("/api/users"); } catch { data = { users: [] }; }
    for (const u of (data.users || [])) {
      const row = el("div", "parental-row");
      row.innerHTML =
        `<span class="parental-name">${escapeHtml(u.name || u.username)}${u.role === "admin" ? ' <span class="muted small">· admin</span>' : ""}</span>
         <select class="lib-select" data-uid="${u.id}" aria-label="Maturity for ${escapeHtml(u.username)}">${optsFor(u.maturity)}</select>
         ${libsControl(allRoots, u.libScope, "uid", u.id)}`;
      box.appendChild(row);
    }
    box.onchange = (e) => {
      const sel = e.target.closest("select[data-uid]");
      if (sel) return saveParentalUser(sel.dataset.uid, { maturity: parseInt(sel.value, 10) });
      const libs = e.target.closest(".parental-libs[data-uid]");
      if (libs) saveParentalUser(libs.dataset.uid, { roots: collectLibs(libs, allRoots) });
    };
  }
}

// A compact "which libraries can this profile/user see" checklist (only when there's
// more than one root — scoping a single library is meaningless). An empty scope = all.
function libsControl(allRoots, scope, attr, id) {
  if (!allRoots || allRoots.length < 2) return "";
  const allowed = new Set(scope && scope.length ? scope : allRoots);   // empty = all
  const boxes = allRoots.map(r => {
    const name = r.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || r;
    return `<label class="lib-check"><input type="checkbox" value="${escapeHtml(r)}"${allowed.has(r) ? " checked" : ""} /> ${escapeHtml(name)}</label>`;
  }).join("");
  return `<div class="parental-libs" data-${attr}="${escapeHtml(String(id))}"><span class="muted small">Libraries:</span>${boxes}</div>`;
}
// Collected scope = checked roots; if everything is checked it's "all" → [] (no restriction).
function collectLibs(container, allRoots) {
  const checked = $$("input[type=checkbox]", container).filter(c => c.checked).map(c => c.value);
  return checked.length === allRoots.length ? [] : checked;
}

async function saveParentalProfile(id, fields) {
  try {
    await api("/api/profiles", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ action: "settings", id }, fields)) });
    toast("Parental controls updated", "ok");
  } catch (e) { toast(e.message, "err"); }
}
// fields: { maturity } or { roots }
async function saveParentalUser(uid, fields) {
  const action = ("roots" in fields) ? "setRoots" : "setMaturity";
  try {
    await api("/api/users", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ action, id: Number(uid) }, fields)) });
    toast("Parental controls updated", "ok");
  } catch (e) { toast(e.message, "err"); }
}

// Remove a sub-profile (and its resume/My-List/ratings/settings). Confirms first.
function removeProfile(id, name) {
  openDialog("Remove profile",
    `<p>Remove the profile <b>${escapeHtml(name || id)}</b>? Its resume points, My List, ratings and limits are deleted.</p>
     <p class="muted small">The account itself is not affected.</p>`,
    async () => {
      try {
        await api("/api/profiles", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "delete", id }) });
      } catch (e) { toast(e.message, "err"); return false; }
      // if we were watching as that profile, fall back to the default identity
      try { if (typeof currentProfile === "function" && currentProfile() === id) localStorage.removeItem("kadmu_profile"); } catch {}
      toast("Profile removed", "ok");
      renderParental();
      if (typeof loadProfiles === "function") loadProfiles();   // refresh the chooser + button
      return true;
    });
}
