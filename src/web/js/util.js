"use strict";
/* util.js — tiny DOM + format helpers and the api() fetch wrapper
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */


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

// The active viewer profile (opt-in). Sent on every request so the server scopes
// progress + My List to it; ignored server-side when profiles are disabled.
function currentProfile() {
  try { return localStorage.getItem("kadmu_profile") || "default"; } catch { return "default"; }
}
async function api(path, opts = {}) {
  opts.headers = { "X-Kadmu": "1", "X-Kadmu-Profile": currentProfile(), ...(opts.headers || {}) };
  const r = await fetch(path, opts);
  if (r.status === 401) {
    let e = {};
    try { e = await r.json(); } catch {}
    if (e.needAuth) { showLogin(); throw new Error("Authentication required"); }
  }
  if (r.status === 402) {
    let e = {};
    try { e = await r.json(); } catch {}
    if (e.needSub) {
      if (typeof showCloudInactive === "function") showCloudInactive(e.entitlement);
      throw new Error("Subscription inactive");
    }
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
// Tidy display title the server derived from the filename (strips download slop);
// falls back to the raw filename without its extension.
const dispName = (v) => (v && v.display) || prettyName(v.name);
function parentDir(p) { return String(p).replace(/[\\/][^\\/]*$/, "") || p; }

