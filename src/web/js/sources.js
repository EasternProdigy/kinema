"use strict";
/* sources.js — Tier-2 remote sources (native, no mounting). Register an HTTP/WebDAV
   server in Settings; Kadmu lists it (/api/sources, /api/rbrowse) and range-proxies
   playback (/api/stream handles the kadmu-remote:// ref). Browsing happens in a small
   modal; playing a native file reuses openPlayer. Classic script sharing the global
   scope; loads after archive.js. Admin-only management, like library folders. */

/* ===================== settings: the source list ===================== */
async function renderRemoteSources() {
  const list = $("#sourcesList");
  if (!list) return;
  let data;
  try { data = await api("/api/sources"); } catch { data = { sources: [] }; }
  const srcs = data.sources || [];
  const countEl = $("#sourcesCount");
  if (countEl) countEl.textContent = srcs.length ? `${srcs.length} server${srcs.length === 1 ? "" : "s"}` : "";
  list.innerHTML = "";
  if (!srcs.length) {
    list.innerHTML = `<div class="root-empty muted small">No remote servers yet — connect one below to stream without mounting.</div>`;
    return;
  }
  for (const s of srcs) {
    const row = el("div", "root-row");
    row.innerHTML =
      `<span class="root-ic" data-icon="globe"></span>` +
      `<span class="root-meta"><span class="root-name">${escapeHtml(s.name)} <span class="src-type">${escapeHtml(s.type)}</span></span>` +
      `<span class="root-path">${escapeHtml(s.url)}</span></span>`;
    const browse = el("button", "btn ghost mini", "Browse");
    browse.onclick = () => openRemoteBrowser(s);
    row.appendChild(browse);
    if (state.session.canManage) {
      const rm = el("button", "rm");
      rm.dataset.icon = "close"; rm.title = "Remove this server";
      rm.onclick = () => removeRemoteSource(s.id);
      row.appendChild(rm);
    }
    list.appendChild(row);
  }
  applyIcons(list);
}

async function removeRemoteSource(id) {
  try {
    await api("/api/sources", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "remove", id }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  toast("Server removed", "ok");
  renderRemoteSources();
}

/* ===================== connect-a-server dialog ===================== */
function openAddSourceDialog() {
  if (!state.session.canManage) { toast("Only an admin can add a server.", "err"); return; }
  const body =
    `<p class="muted small remote-intro">Point Kadmu at a server that lists files over <b>HTTP</b>
       (nginx/Apache autoindex, or <code>python3 -m http.server</code>) or <b>WebDAV</b>. For seeking
       to work, the server must support HTTP range requests (most do). Native files (mp4/webm…) play
       directly; other containers need a mounted source for now.</p>
     <label class="remote-label">Name</label>
     <input type="text" id="srcName" placeholder="My home server" />
     <label class="remote-label">Type</label>
     <select id="srcType" class="lib-select">
       <option value="http">HTTP server (directory listing)</option>
       <option value="webdav">WebDAV</option>
     </select>
     <label class="remote-label">Base URL</label>
     <input type="text" id="srcUrl" placeholder="https://media.example.com/movies/" />
     <details class="advanced-add"><summary class="muted small">Needs a username / password?</summary>
       <div class="add-root"><input type="text" id="srcUser" placeholder="Username" autocomplete="off" />
       <input type="password" id="srcPass" placeholder="Password" autocomplete="new-password" /></div>
     </details>
     <div id="srcTestOut" class="settings-status muted small"></div>`;
  openDialog("Connect a server", body, async () => {
    const payload = readSourceForm();
    if (!payload.url) { toast("Enter the server's base URL.", "err"); return false; }
    let r;
    try {
      r = await api("/api/sources", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ action: "add" }, payload)),
      });
    } catch (e) { toast(e.message, "err"); return false; }
    if (!r.ok) { toast(r.error || "Couldn't add that server.", "err"); return false; }
    toast("Server connected", "ok");
    renderRemoteSources();
    return true;
  });
  // Replace the single OK with Test + Add (Test runs inline, doesn't close the dialog).
  $("#dialogOk").textContent = "Add";
  const test = el("button", "btn ghost dlg-extra", "Test");
  test.type = "button";
  test.onclick = testSource;
  $("#dialogOk").insertAdjacentElement("beforebegin", test);
  setTimeout(() => { const i = $("#srcName"); if (i) i.focus(); }, 50);
}

function readSourceForm() {
  return {
    name: ($("#srcName")?.value || "").trim(),
    type: $("#srcType")?.value || "http",
    url: ($("#srcUrl")?.value || "").trim(),
    username: ($("#srcUser")?.value || "").trim(),
    password: $("#srcPass")?.value || "",
  };
}

async function testSource() {
  const out = $("#srcTestOut");
  const p = readSourceForm();
  if (!p.url) { if (out) out.textContent = "Enter a URL first."; return; }
  if (out) out.textContent = "Testing…";
  let r;
  try {
    r = await api("/api/sources", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ action: "test" }, p)),
    });
  } catch (e) { if (out) out.textContent = e.message; return; }
  if (out) out.textContent = r.ok
    ? `Connected — ${r.folders} folder${r.folders === 1 ? "" : "s"}, ${r.videos} video${r.videos === 1 ? "" : "s"} here.`
    : (r.error || "Couldn't reach it.");
}

/* ===================== remote browse modal ===================== */
function openRemoteBrowser(source) {
  let rel = "";
  openDialog(`Browse · ${source.name}`, `<div id="rbWrap" class="rb-wrap"></div>`, null);
  $("#dialogOk").classList.add("hidden");        // browse modal has no confirm action

  async function draw(path) {
    rel = path;
    const wrap = $("#rbWrap");
    wrap.innerHTML = `<div class="muted small">Loading…</div>`;
    let data;
    try { data = await api(`/api/rbrowse?src=${enc(source.id)}&path=${enc(path)}`); }
    catch (e) { wrap.innerHTML = `<p class="muted">${escapeHtml(e.message)}</p>`; return; }
    if (data.error) { wrap.innerHTML = `<p class="muted">${escapeHtml(data.error)}</p>`; return; }
    const picker = el("div", "picker");
    if (rel) {
      const parent = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "";
      const up = el("div", "p-row up", `${ICON.up}<span>Up one level</span>`);
      up.onclick = () => draw(parent);
      picker.appendChild(up);
    }
    for (const d of (data.dirs || [])) {
      const row = el("div", "p-row", `${ICON.folder}<span>${escapeHtml(d.name)}</span>`);
      row.onclick = () => draw(refRel(d.path, source.id));
      picker.appendChild(row);
    }
    for (const f of (data.files || [])) {
      const row = el("div", "p-row rb-file" + (f.playable ? "" : " disabled"),
        `${ICON.film}<span>${escapeHtml(f.name)}</span>${f.playable ? `<span class="rb-play">${ICON.play}</span>` : `<span class="muted small">needs mount</span>`}`);
      if (f.playable) row.onclick = () => { closeDialog(); openPlayer(remoteItem(f, source)); };
      picker.appendChild(row);
    }
    if (!(data.dirs || []).length && !(data.files || []).length) {
      picker.appendChild(el("div", "p-row up", "(nothing playable here)"));
    }
    wrap.innerHTML = "";
    wrap.appendChild(picker);
    applyIcons(wrap);
  }
  draw("");
}

// The relpath portion of a kadmu-remote:// ref (strip the prefix + source id).
function refRel(ref, sid) {
  const head = `kadmu-remote://${sid}/`;
  return ref.startsWith(head) ? ref.slice(head.length) : "";
}

// A player item for a remote file. openPlayer falls back to a single-item queue when
// it can't read the (remote) parent folder, and /api/stream proxies the bytes by ref.
function remoteItem(f, source) {
  return {
    path: f.path, name: f.name, display: f.name,
    ext: f.ext, playable: true, direct: f.direct, remote: true,
    duration: null, position: 0,
  };
}
