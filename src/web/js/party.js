"use strict";
/* party.js — watch party / synced playback over Server-Sent Events. One person
   starts a room (gets a short code); everyone who joins stays in lockstep —
   play, pause, seek and episode changes mirror to the whole room. Anyone in the
   room can drive (collaborative). LAN-first and free; the backend brokers state
   only (party.py), never the video.
   Part of the Kadmu frontend; classic script sharing the global scope. */

const party = { code: null, role: null, es: null, applying: false, members: 0, poll: null };

function partyActive() { return !!party.code; }

function toggleParty() { $("#partyPanel")?.classList.contains("hidden") ? openParty() : closeParty(); }
function openParty() {
  buildPartyPanel();
  $("#partyPanel")?.classList.remove("hidden");
  $("#playerOverlay")?.classList.add("party-open");
  showUi();
}
function closeParty() {
  $("#partyPanel")?.classList.add("hidden");
  $("#playerOverlay")?.classList.remove("party-open");
}
function updatePartyButton() {
  $("#partyBtn")?.classList.toggle("on", partyActive());
}

function buildPartyPanel() {
  const p = $("#partyPanel");
  if (!p) return;
  p.innerHTML = "";
  const head = el("div", "party-head");
  head.appendChild(el("span", "party-title", "Watch party"));
  const x = el("button", "icon-round", ICON.close); x.title = "Close"; x.onclick = closeParty;
  head.appendChild(x);
  p.appendChild(head);
  const body = el("div", "party-body");
  p.appendChild(body);

  if (!partyActive()) {
    body.appendChild(el("p", "party-note", "Watch in sync with friends on your network. Start a room and share the code — play, pause and seek stay together for everyone."));
    const start = el("button", "btn primary party-start", `${ICON.party}<span>Start a watch party</span>`);
    start.onclick = startParty;
    body.appendChild(start);
    const join = el("form", "party-join");
    join.innerHTML = `<input type="text" id="partyCode" maxlength="4" placeholder="Code" autocomplete="off"
      spellcheck="false" aria-label="Party code" /><button class="btn" type="submit">Join</button>`;
    join.onsubmit = (e) => { e.preventDefault(); joinParty($("#partyCode").value); };
    body.appendChild(join);
    return;
  }

  const shareUrl = location.origin + "/#party=" + party.code;
  body.appendChild(el("div", "party-code-big", escapeHtml(party.code)));
  body.appendChild(el("p", "party-note", party.role === "host"
    ? "You started this room. Share the code (or link) — everyone stays in sync."
    : "You're in the party. Playback follows the room."));
  const copy = el("button", "btn party-copy", "Copy invite link");
  copy.onclick = () => { try { navigator.clipboard.writeText(shareUrl); toast("Invite link copied", "ok"); } catch { toast(shareUrl, ""); } };
  body.appendChild(copy);
  body.appendChild(el("div", "party-members", `${party.members || 1} ${(party.members || 1) === 1 ? "person" : "people"} watching`));
  const leave = el("button", "btn ghost party-leave", "Leave party");
  leave.onclick = leaveParty;
  body.appendChild(leave);
}

function startParty() {
  api("/api/party/create", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: currentVideo ? currentVideo.path : null }),
  }).then(d => {
    if (!d || !d.code) { toast("Couldn't start the party.", "err"); return; }
    party.code = d.code; party.role = "host"; party.members = 1;
    connectParty();
    buildPartyPanel(); updatePartyButton();
    if (currentVideo) partyLocal("load");
    toast("Watch party started · code " + d.code, "ok");
  }).catch(e => toast(e.message || "Couldn't start the party.", "err"));
}

function joinParty(code) {
  code = (code || "").trim().toUpperCase();
  if (code.length < 4) { toast("Enter the 4-character code.", "err"); return; }
  api("/api/party/join", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  }).then(d => {
    if (!d || !d.ok) { toast((d && d.error) || "No room with that code.", "err"); return; }
    party.code = code; party.role = "guest"; party.members = (d.snapshot && d.snapshot.members) || 1;
    connectParty();
    buildPartyPanel(); updatePartyButton();
    if (d.snapshot && d.snapshot.state) applyPartyState(d.snapshot.state);
    toast("Joined watch party " + code, "ok");
  }).catch(e => toast(e.message || "Couldn't join.", "err"));
}

function leaveParty() {
  if (party.es) { try { party.es.close(); } catch {} party.es = null; }
  if (party.poll) { clearInterval(party.poll); party.poll = null; }
  party.code = null; party.role = null; party.members = 0;
  buildPartyPanel(); updatePartyButton();
  toast("Left the watch party", "");
}

function connectParty() {
  if (party.es) { try { party.es.close(); } catch {} }
  try {
    party.es = new EventSource("/api/party/events?code=" + enc(party.code));
  } catch { toast("Live sync isn't supported here.", "err"); return; }
  party.es.onmessage = (e) => {
    let msg; try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === "ping") { if (typeof msg.members === "number") setPartyMembers(msg.members); return; }
    if (msg.type === "load" || msg.type === "control") applyPartyState(msg);
    if (typeof msg.members === "number") setPartyMembers(msg.members);
  };
  party.es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ };
  // light member-count poll while connected (cheap; the panel shows it)
  if (party.poll) clearInterval(party.poll);
  party.poll = setInterval(() => {
    if (!party.code) return;
    api("/api/party/state?code=" + enc(party.code)).then(s => {
      if (s && typeof s.members === "number") setPartyMembers(s.members);
    }).catch(() => {});
  }, 5000);
}

function setPartyMembers(n) {
  party.members = n;
  const m = $(".party-members");
  if (m) m.textContent = `${n} ${n === 1 ? "person" : "people"} watching`;
}

// Apply a room state to the local player (guard against echoing it straight back).
function applyPartyState(st) {
  if (!st) return;
  party.applying = true;
  setTimeout(() => { party.applying = false; }, 500);     // suppress the echo of our own apply
  if (st.path && (!currentVideo || currentVideo.path !== st.path)) {
    openPlayerByPath(st.path);
    // give the new clip a moment to load before syncing position/state
    setTimeout(() => syncToState(st), 1200);
    return;
  }
  syncToState(st);
}
function syncToState(st) {
  if (!currentVideo) return;
  if (typeof st.position === "number" && Math.abs(currentPlayPos() - st.position) > 1.2) seekTo(st.position);
  if (typeof st.rate === "number" && st.rate && st.rate !== state.rate) setSpeed(st.rate);
  if (st.paused === true && !video.paused) video.pause();
  else if (st.paused === false && video.paused) video.play().catch(() => {});
}

// Open a clip from just its absolute path (used when the room loads something new).
function openPlayerByPath(path) {
  const name = String(path).split(/[\\/]/).pop() || path;
  const ext = (name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
  openPlayer({ path, name, display: prettyName(name), ext, playable: true, direct: true });
}

// Mirror a local playback change to the room (no-op unless we're in a party).
function partyLocal(kind) {
  if (!party.code || party.applying) return;
  const body = {
    code: party.code, kind: kind === "load" ? "load" : "control",
    path: currentVideo ? currentVideo.path : null,
    position: currentPlayPos(), paused: !!video.paused, rate: state.rate,
  };
  api("/api/party/update", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => {});
}
