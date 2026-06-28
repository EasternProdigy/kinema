"use strict";
/* accounts.js — login/sign-up, viewer profiles, the account menu, Account & People settings
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== login / sign-up ===================== */
let loginMode = "login";   // "login" | "register" (accounts mode only)

function showLogin() {
  renderLoginForm();
  $("#loginOverlay").classList.remove("hidden");
  setTimeout(() => (state.session.accounts ? $("#loginUsername") : $("#loginPassword"))?.focus(), 50);
}
function hideLogin() { $("#loginOverlay").classList.add("hidden"); }

// Configure the one login card for the active auth model: a shared password, an
// account sign-in, the first-run "create the owner" screen, or self-registration.
function renderLoginForm() {
  const s = state.session || {};
  const acc = !!s.accounts;
  const setup = acc && !!s.needsSetup;
  const uname = $("#loginUsername"), name = $("#loginName"), pw = $("#loginPassword");
  const title = $("#loginTitle"), hint = $("#loginHint");
  const submit = $("#loginSubmit"), toggle = $("#loginToggle");
  $("#loginError").textContent = "";
  if (!acc) {                                   // single shared password (original behaviour)
    uname.classList.add("hidden"); name.classList.add("hidden");
    title.classList.add("hidden"); toggle.classList.add("hidden");
    hint.textContent = "This library is password-protected.";
    pw.autocomplete = "current-password";
    submit.textContent = "Unlock";
    return;
  }
  if (setup) loginMode = "register";
  const reg = loginMode === "register";
  uname.classList.remove("hidden");
  name.classList.toggle("hidden", !reg);
  title.classList.remove("hidden");
  title.textContent = setup ? "Welcome to Kadmu" : (reg ? "Create your account" : "Sign in");
  hint.textContent = setup
    ? "Create the owner account — it manages the library and everyone who can sign in."
    : (reg ? "Pick a username and a password." : "Sign in to your account.");
  pw.autocomplete = reg ? "new-password" : "current-password";
  submit.textContent = setup ? "Create owner account" : (reg ? "Create account" : "Sign in");
  // offer the login/register switch only when self-sign-up is open (never during setup)
  if (setup || (!reg && !s.signupOpen)) {
    toggle.classList.add("hidden");
  } else {
    toggle.classList.remove("hidden");
    toggle.textContent = reg ? "← Back to sign in" : "Create an account";
  }
}

function setLoginMode(m) {
  loginMode = m;
  renderLoginForm();
  setTimeout(() => $("#loginUsername")?.focus(), 30);
}


/* ---------- viewer profiles (opt-in) ---------- */
async function loadProfiles() {
  let data = { enabled: false, profiles: [] };
  try { data = await api("/api/profiles"); } catch {}
  state.profilesEnabled = !!data.enabled;
  const btn = $("#profileBtn");
  if (!state.profilesEnabled) { btn?.classList.add("hidden"); return; }
  state.profileList = data.profiles || [];
  const cur = currentProfile();
  const known = state.profileList.find(p => p.id === cur) || { id: "default", name: "Default" };
  updateProfileButton(known);
  btn?.classList.remove("hidden");
  let chosen = false;
  try { chosen = localStorage.getItem("kadmu_profile_chosen") === "1"; } catch {}
  if (!chosen) showProfileChooser();
}
function updateProfileButton(p) {
  const ava = $("#profileAva");
  if (ava) ava.textContent = ((p && p.name) || "?").trim().charAt(0).toUpperCase() || "?";
  const btn = $("#profileBtn");
  if (btn) btn.title = `Profile: ${(p && (p.name || p.id)) || "Default"} — switch`;
}
async function showProfileChooser() {
  const ov = $("#profileOverlay"), grid = $("#profileGrid");
  if (!ov || !grid) return;
  let list = state.profileList || [];
  try { const d = await api("/api/profiles"); list = d.profiles || list; state.profileList = list; } catch {}
  grid.innerHTML = "";
  for (const p of list) {
    const b = el("button", "profile-tile" + (p.id === currentProfile() ? " current" : ""));
    b.innerHTML = `<span class="profile-ava big">${escapeHtml((p.name || "?").charAt(0).toUpperCase())}</span>` +
                  `<span class="profile-name">${escapeHtml(p.name || p.id)}</span>`;
    b.onclick = () => selectProfile(p);
    grid.appendChild(b);
  }
  applyIcons(ov);
  ov.classList.remove("hidden");
}
function hideProfileChooser() { $("#profileOverlay")?.classList.add("hidden"); }
async function selectProfile(p) {
  try { localStorage.setItem("kadmu_profile", p.id); localStorage.setItem("kadmu_profile_chosen", "1"); } catch {}
  updateProfileButton(p);
  hideProfileChooser();
  try { state.mylist = new Set((await api("/api/mylist")).map(i => i.path)); } catch {}
  try { state.progress = await api("/api/progress"); } catch {}
  loadLibrary(state.searchActive ? null : state.path);
  toast(`Watching as ${p.name || p.id}`, "ok");
}
async function addProfile(name) {
  name = (name || "").trim();
  if (!name) return;
  try {
    const r = await api("/api/profiles", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (r && r.ok) { state.profileList = r.profiles || []; selectProfile(r.profile); }
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- accounts: top-bar user button + menu ---------- */
function userInitial() {
  const u = state.session.user;
  return (((u && (u.name || u.username)) || "?").trim().charAt(0).toUpperCase()) || "?";
}
// In accounts mode the top-bar avatar is the account button (it opens the user
// menu); the viewer-profiles chooser is unused.
function loadAccountUi() {
  if (!state.session.accounts) return;
  const btn = $("#profileBtn"), ava = $("#profileAva"), u = state.session.user || {};
  if (ava) ava.textContent = userInitial();
  if (btn) {
    btn.classList.remove("hidden");
    btn.title = `${u.name || u.username || "Account"} — account`;
    btn.setAttribute("aria-label", "Account menu");
  }
}
function buildUserMenu() {
  const m = $("#userMenu");
  if (!m) return;
  const u = state.session.user || {};
  const role = u.role === "admin" ? "Admin" : "Viewer";
  m.innerHTML =
    `<div class="um-head"><span class="um-ava">${escapeHtml(userInitial())}</span>` +
    `<span class="um-id"><b>${escapeHtml(u.name || u.username || "—")}</b>` +
    `<span class="muted small">@${escapeHtml(u.username || "")} · ${role}</span></span></div>`;
  const acct = el("button", "um-item");
  acct.type = "button";
  acct.innerHTML = `<span class="um-ic" data-icon="user"></span><span>Account settings</span>`;
  acct.onclick = async () => {
    hideUserMenu();
    await openSettings();
    $("#accountSection")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  m.appendChild(acct);
  const out = el("button", "um-item");
  out.type = "button";
  out.innerHTML = `<span class="um-ic" data-icon="logout"></span><span>Sign out</span>`;
  out.onclick = () => { hideUserMenu(); signOut(); };
  m.appendChild(out);
  applyIcons(m);
}
function toggleUserMenu() {
  const m = $("#userMenu");
  if (!m) return;
  if (m.classList.contains("hidden")) { buildUserMenu(); m.classList.remove("hidden"); }
  else hideUserMenu();
}
function hideUserMenu() { $("#userMenu")?.classList.add("hidden"); }
async function signOut() {
  try { await fetch("/api/logout", { method: "POST", headers: { "X-Kadmu": "1" } }); } catch {}
  try { localStorage.removeItem("kadmu_last_path"); } catch {}
  location.reload();
}

/* ---------- settings: your account ---------- */
function renderAccount() {
  const sec = $("#accountSection");
  if (!sec) return;
  if (!state.session.accounts || !state.session.user) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const u = state.session.user;
  const who = $("#accountWho");
  if (who) who.textContent = `${u.name || u.username} (@${u.username})`;
  const box = $("#accountControl");
  box.innerHTML =
    `<div class="acct-row"><label class="acct-label" for="acctName">Display name</label>` +
    `<div class="acct-line"><input type="text" id="acctName" maxlength="64" value="${escapeHtml(u.name || "")}" />` +
    `<button class="btn" id="acctNameSave" type="button">Save</button></div></div>` +
    `<div class="acct-row"><label class="acct-label" for="acctNew">Change password</label>` +
    `<div class="acct-line"><input type="password" id="acctCur" placeholder="Current password" autocomplete="current-password" /></div>` +
    `<div class="acct-line"><input type="password" id="acctNew" placeholder="New password" autocomplete="new-password" />` +
    `<button class="btn primary" id="acctPwSave" type="button">Update</button></div></div>`;
  $("#acctNameSave").onclick = () => saveAccount({ name: $("#acctName").value.trim() });
  $("#acctPwSave").onclick = () => {
    const cur = $("#acctCur").value, nw = $("#acctNew").value;
    if (!nw) { toast("Enter a new password.", "err"); return; }
    saveAccount({ currentPassword: cur, newPassword: nw });
  };
}
async function saveAccount(payload) {
  try {
    const r = await api("/api/account", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r && r.ok === false) { toast(r.error || "Could not update your account.", "err"); return; }
    await refreshSession();
    loadAccountUi(); renderAccount(); renderStatus();
    toast(payload.newPassword ? "Password updated" : "Saved", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- settings: people / users (admin) ---------- */
async function renderUsers() {
  const sec = $("#usersSection");
  if (!sec) return;
  if (!state.session.accounts || state.session.role !== "admin") { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  const box = $("#usersControl");
  let data = { users: [], signupOpen: false };
  try { data = await api("/api/users"); }
  catch (e) { box.innerHTML = `<p class="muted small">${escapeHtml(e.message)}</p>`; return; }
  const me = state.session.user || {};
  const users = data.users || [];
  const cnt = $("#userCount"); if (cnt) cnt.textContent = users.length;
  box.innerHTML = "";

  const sgn = el("label", "pref-toggle");
  sgn.innerHTML = `<input type="checkbox" id="signupToggle"${data.signupOpen ? " checked" : ""} />` +
    `<span>Let anyone create their own account <span class="muted small">— off means only admins add people below</span></span>`;
  box.appendChild(sgn);
  $("#signupToggle").onchange = (e) => usersAction({ action: "signup", open: e.target.checked });

  const list = el("div", "user-list");
  for (const u of users) {
    const isMe = u.id === me.id;
    const row = el("div", "user-row");
    row.innerHTML =
      `<span class="user-ava">${escapeHtml((u.name || u.username || "?").charAt(0).toUpperCase())}</span>` +
      `<span class="user-id"><b>${escapeHtml(u.name || u.username)}</b>` +
      `<span class="muted small">@${escapeHtml(u.username)}${isMe ? " · you" : ""}</span></span>`;
    const actions = el("div", "user-actions");
    const sel = el("select", "user-role");
    sel.innerHTML = `<option value="viewer"${u.role === "viewer" ? " selected" : ""}>Viewer</option>` +
                    `<option value="admin"${u.role === "admin" ? " selected" : ""}>Admin</option>`;
    sel.disabled = isMe;                         // can't change your own role here
    sel.title = isMe ? "You can't change your own role" : "Role";
    sel.onchange = () => usersAction({ action: "setRole", id: u.id, role: sel.value });
    actions.appendChild(sel);
    const rb = el("button", "btn ghost mini");
    rb.type = "button"; rb.textContent = "Reset password";
    rb.onclick = () => resetUserPassword(u);
    actions.appendChild(rb);
    if (!isMe) {
      const db = el("button", "btn ghost mini danger");
      db.type = "button"; db.textContent = "Remove";
      db.onclick = () => removeUser(u);
      actions.appendChild(db);
    }
    row.appendChild(actions);
    list.appendChild(row);
  }
  box.appendChild(list);

  const add = el("form", "user-add");
  add.innerHTML =
    `<input type="text" id="newUserName" placeholder="Username" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="32" />` +
    `<input type="password" id="newUserPw" placeholder="Password" autocomplete="new-password" />` +
    `<select id="newUserRole" aria-label="Role"><option value="viewer">Viewer</option><option value="admin">Admin</option></select>` +
    `<button class="btn primary" type="submit" data-icon-prefix="plus">Add</button>`;
  add.onsubmit = (e) => {
    e.preventDefault();
    const username = $("#newUserName").value.trim();
    const password = $("#newUserPw").value;
    if (!username || !password) { toast("Enter a username and a password.", "err"); return; }
    usersAction({ action: "create", username, password, role: $("#newUserRole").value }, "Account created");
  };
  box.appendChild(add);
  applyIcons(box);
}
async function usersAction(payload, okToast) {
  try {
    const r = await api("/api/users", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r && r.ok === false) { toast(r.error || "Could not apply that change.", "err"); }
    else if (okToast) toast(okToast, "ok");
  } catch (e) { toast(e.message, "err"); }
  await renderUsers();
}
function resetUserPassword(u) {
  openDialog(`Reset password — ${u.name || u.username}`,
    `<label for="dlgInput">New password</label>` +
    `<input type="password" id="dlgInput" placeholder="New password" autocomplete="new-password" />` +
    `<p class="muted small">They'll be signed out everywhere and must use the new password.</p>`,
    async () => {
      const pw = $("#dlgInput").value;
      if (!pw) { toast("Enter a new password.", "err"); return false; }
      await usersAction({ action: "resetPassword", id: u.id, password: pw }, "Password reset");
    });
}
function removeUser(u) {
  openDialog(`Remove ${u.name || u.username}?`,
    `<p>This deletes <b>@${escapeHtml(u.username)}</b> and all of their resume points, ` +
    `My List and playlists. The library files are untouched.</p>`,
    async () => { await usersAction({ action: "delete", id: u.id }, "Account removed"); });
}

