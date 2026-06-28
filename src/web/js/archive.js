"use strict";
/* archive.js — the Archive (reclaim disk) UI. On a finished title's detail page it
   offers a one-click background re-encode to a smaller, still-watchable copy, with
   live progress and a Cancel, then shows "Archived · saved N". It also paints a
   "ready to archive" flag on watched posters (the auto-suggest half of the feature).
   Talks to /api/archive (GET status · POST enqueue) and /api/archive/cancel.
   Classic script sharing the global scope; loads right after catalog.js, whose
   renderTitleDetail() calls renderArchiveControls(). */

let archivePollTimer = null;

function stopArchivePoll() {
  if (archivePollTimer) { clearInterval(archivePollTimer); archivePollTimer = null; }
}

// Corner flag on a poster: this watched title is ready to compress. Guarded callers
// (catalog.js) only invoke it when it.suggestArchive is set.
function archiveSuggestFlag() {
  return `<span class="archive-flag" title="Watched — ready to archive and save space">${ICON.archive}</span>`;
}

// Injected into a title's .title-actions by catalog.js renderTitleDetail(d).
function renderArchiveControls(view, d) {
  const a = d && d.archive;
  const actions = $(".title-actions", view);
  if (!actions || !a || !a.available) return;      // no encoder on the server → don't offer it
  let box = $(".title-archive", view);
  if (!box) { box = el("div", "title-archive"); actions.appendChild(box); }
  paintArchive(box, view, d, a);
}

function fullyWatched(d) {
  return d.kind === "show"
    ? (d.episodeCount > 0 && d.watched >= d.episodeCount)
    : !!(d.video && d.video.watched);
}

function paintArchive(box, view, d, a) {
  stopArchivePoll();
  if (a.running) {
    box.className = "title-archive running";
    box.innerHTML =
      `<span class="arch-ic" data-icon="archive"></span>
       <span class="arch-body">
         <span class="arch-label">Starting…</span>
         <span class="arch-prog"><i style="width:0%"></i></span>
       </span>
       <button class="btn ghost mini arch-cancel" type="button">Cancel</button>`;
    applyIcons(box);
    $(".arch-cancel", box).onclick = () => cancelArchive(d, view);
    startArchivePoll(box, view, d);
    return;
  }
  if (a.fullyArchived) {
    box.className = "title-archive done";
    const saved = a.saved ? ` · saved ${fmtSize(a.saved)}` : "";
    box.innerHTML = `<span class="arch-ic" data-icon="check"></span><span class="arch-static">Archived${escapeHtml(saved)}</span>`;
    applyIcons(box);
    return;
  }
  if (a.candidate) {
    const suggest = fullyWatched(d);
    const partial = a.archived > 0 ? ` (${a.archived}/${a.total})` : "";
    box.className = "title-archive" + (suggest ? " suggest" : "");
    box.innerHTML =
      `<button class="btn ghost arch-go" type="button">
         <span class="arch-ic" data-icon="archive"></span>
         <span>Archive to save space${escapeHtml(partial)}</span>
       </button>
       ${suggest ? `<span class="arch-note">You've finished this — reclaim disk, keep it watchable.</span>` : ""}`;
    applyIcons(box);
    $(".arch-go", box).onclick = () => startArchive(d, view);
    return;
  }
  box.className = "title-archive";
  box.innerHTML = "";
}

async function startArchive(d, view) {
  let r;
  try {
    r = await api("/api/archive", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: d.id }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  if (!r.ok) { toast(r.error || "Couldn't start archiving.", "err"); return; }
  toast(`Compressing ${r.queued} file${r.queued === 1 ? "" : "s"} in the background…`, "ok");
  const box = $(".title-archive", view);
  if (box) paintArchive(box, view, d, Object.assign({}, d.archive, { running: true }));
}

async function cancelArchive(d, view) {
  try {
    await api("/api/archive/cancel", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: d.id }),
    });
  } catch (e) { toast(e.message, "err"); return; }
  toast("Archiving cancelled", "ok");
  stopArchivePoll();
  reloadArchiveState(view, d);
}

function startArchivePoll(box, view, d) {
  stopArchivePoll();
  let misses = 0;
  archivePollTimer = setInterval(async () => {
    let s;
    try { s = await api("/api/archive"); } catch { return; }
    const isActive = s.active && s.active.id === d.id;
    const job = isActive ? s.active : (s.queue || []).find(j => j.id === d.id);
    const bar = $(".arch-prog i", box), label = $(".arch-label", box);
    if (!job) {                              // no longer queued or running → it finished
      if (++misses >= 2) { stopArchivePoll(); reloadArchiveState(view, d); }
      return;
    }
    misses = 0;
    if (isActive) {
      const overall = Math.min(100, Math.round(
        ((job.doneCount + (job.percent || 0) / 100) / Math.max(1, job.total)) * 100));
      if (bar) bar.style.width = overall + "%";
      if (label) label.textContent = job.total > 1
        ? `Compressing ${Math.min(job.doneCount + 1, job.total)} of ${job.total} · ${overall}%`
        : `Compressing · ${overall}%`;
    } else if (label) {
      label.textContent = "Queued…";
    }
  }, 2000);
}

// Re-fetch the title so the control reflects the finished state (and report savings).
async function reloadArchiveState(view, d) {
  if (typeof titleNow !== "undefined" && titleNow && titleNow.id !== d.id) return;  // navigated away
  let nd;
  try { nd = await api(`/api/title?id=${enc(d.id)}`); } catch { return; }
  if (!nd || !nd.archive) return;
  const before = (d.archive && d.archive.saved) || 0;
  d.archive = nd.archive; d.watched = nd.watched; d.episodeCount = nd.episodeCount;
  if (typeof titleNow !== "undefined" && titleNow && titleNow.id === d.id) titleNow.archive = nd.archive;
  const box = $(".title-archive", view);
  if (box) paintArchive(box, view, d, nd.archive);
  const gained = (nd.archive.saved || 0) - before;
  if (gained > 0) toast(`Done — saved ${fmtSize(gained)}`, "ok");
}
