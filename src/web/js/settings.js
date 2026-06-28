"use strict";
/* settings.js — the Settings modal: status, network/LAN, shared password, roots
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== settings ===================== */
async function openSettings() {
  $("#settingsModal").classList.remove("hidden");
  renderKeybinds($("#settingsKbd"));   // same list as the "?" overlay (one source of truth)
  { const t = $("#keyHudToggle"); if (t) t.checked = state.keyHud; }
  await refreshSession();   // re-check live server caps (LAN toggle, ffmpeg, …) without a page reload
  renderStatus();
  renderLan();
  renderUrls();
  // Library management is admin-only in accounts mode; hide that section for viewers.
  const libSec = $("#rootList")?.closest(".settings-section");
  if (libSec) libSec.classList.toggle("hidden", state.session.accounts && !state.session.canManage);
  if (state.session.canManage) await renderRoots();
  renderAccount();          // your own account (accounts mode)
  await renderUsers();      // people management (admins, accounts mode)
}
function closeSettings() { $("#settingsModal").classList.add("hidden"); }

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

