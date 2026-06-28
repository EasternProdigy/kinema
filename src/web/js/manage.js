"use strict";
/* manage.js — multi-select, context menu, file ops, add/remove folders, dialogs
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html. */

/* ===================== multi-select (Shift+click) ===================== */
// Shift+click (or a card's checkbox) selects items; right-click acts on the whole
// selection via the context menu. No mode toggle — selecting starts the moment you
// Shift+click something and ends when you plain-click, press Esc, or clear it.
function toggleSelect(card, path, name, isFolder) {
  if (!state.session.canManage) return;          // read-only can't select/manage
  if (state.selection.has(path)) { state.selection.delete(path); card.classList.remove("selected"); }
  else { state.selection.set(path, { name, isFolder }); card.classList.add("selected"); }
  updateSelectionUI();
}
function clearSelection() {
  state.selection.clear();
  $$(".video-card.selected, .folder-card.selected").forEach(c => c.classList.remove("selected"));
  updateSelectionUI();
}
// Replace the whole selection with a single item (standard right-click behavior).
function selectOnly(card, path, name, isFolder) {
  state.selection.clear();
  $$(".video-card.selected, .folder-card.selected").forEach(c => c.classList.remove("selected"));
  state.selection.set(path, { name, isFolder });
  if (card) card.classList.add("selected");
  updateSelectionUI();
}
function updateSelectionUI() {
  // Checkboxes + selected styling show whenever at least one item is selected.
  document.body.classList.toggle("selecting", state.selection.size > 0);
}

/* ===================== right-click context menu ===================== */
function closeContextMenu() { $("#ctxMenu")?.classList.add("hidden"); }

function openContextMenu(ev, target) {
  ev.preventDefault();
  ev.stopPropagation();
  closeContextMenu();
  const canManage = state.session.canManage;
  const isRoot = !!(state.data && state.data.isRoot);

  // figure out what the actions operate on
  let multi = false;
  if (target) {
    if (state.selection.has(target.path) && state.selection.size > 1) multi = true;   // act on the whole selection
    else selectOnly(target.card, target.path, target.name, target.isFolder);
  }
  const n = state.selection.size;

  const items = [];
  if (target && !multi) {
    if (target.isFolder) items.push({ icon: "folderOpen", label: "Open", fn: () => loadLibrary(target.path) });
    else items.push({ icon: "play", label: "Play", fn: () => openPlayer(target.item) });
  }
  // Mark watched / unwatched — personal state, allowed even in read-only.
  if (target && !multi && !target.isFolder) {
    const w = isWatched(target.item);
    items.push({ icon: w ? "eyeOff" : "eye", label: w ? "Mark as unwatched" : "Mark as watched",
      fn: () => w ? markUnwatched(target.path) : markWatched(target.path, target.item && target.item.duration) });
  }
  if (canManage) {
    if (isRoot) {
      if (target) {
        if (items.length) items.push({ sep: true });
        items.push({ icon: "remove", danger: true, fn: doRemoveRoots,
          label: n > 1 ? `Remove ${n} from library` : "Remove from library" });
      }
    } else {
      if (target) {
        if (items.length) items.push({ sep: true });
        if (n === 1) items.push({ icon: "rename", label: "Rename", fn: doRename });
        items.push({ icon: "move", label: n > 1 ? `Move ${n}…` : "Move…", fn: doMove });
        items.push({ icon: "trash", danger: true, fn: doDelete, label: n > 1 ? `Delete ${n}` : "Delete" });
      }
      items.push({ sep: true });
      items.push({ icon: "folderPlus", label: "New folder", fn: doNewFolder });
    }
  }
  // drop a leading/trailing separator if it has nothing useful around it
  while (items.length && items[0].sep) items.shift();
  while (items.length && items[items.length - 1].sep) items.pop();
  if (!items.length) return;

  const menu = $("#ctxMenu");
  menu.innerHTML = "";
  for (const it of items) {
    if (it.sep) { menu.appendChild(el("div", "ctx-sep")); continue; }
    const b = el("button", it.danger ? "danger" : "", `${ICON[it.icon] || ""}<span>${escapeHtml(it.label)}</span>`);
    b.onclick = () => { closeContextMenu(); it.fn(); };
    menu.appendChild(b);
  }
  menu.style.left = ev.clientX + "px";
  menu.style.top = ev.clientY + "px";
  menu.classList.remove("hidden");
  // keep it on-screen
  const r = menu.getBoundingClientRect();
  if (r.right > window.innerWidth - 8) menu.style.left = Math.max(8, window.innerWidth - r.width - 8) + "px";
  if (r.bottom > window.innerHeight - 8) menu.style.top = Math.max(8, window.innerHeight - r.height - 8) + "px";
}

async function runOp(payload) {
  return api("/api/op", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function openRenameDialog(path, name) {
  openDialog("Rename", `<label>New name</label><input type="text" id="dlgInput" value="${escapeHtml(name)}" />`,
    async () => {
      const nn = $("#dlgInput").value.trim();
      if (!nn) return false;
      const r = await runOp({ action: "rename", path, name: nn });
      if (r.ok) { toast("Renamed", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => { const i = $("#dlgInput"); if (i) { i.focus(); i.setSelectionRange(0, prettyName(name).length); } }, 50);
}
function doRename() {
  const [path, info] = [...state.selection.entries()][0];
  openRenameDialog(path, info.name);
}

function openDeleteDialog(items) {
  const names = items.slice(0, 6).map(i => i.name).join(", ") + (items.length > 6 ? `, +${items.length - 6} more` : "");
  openDialog("Delete to trash",
    `<p>Move <b>${items.length}</b> item(s) to the library's <code>.kadmu-trash</code> folder?</p>
     <p class="muted small">${escapeHtml(names)}</p>
     <p class="muted small">Nothing is permanently erased — you can restore from the trash folder on disk.</p>`,
    async () => {
      let ok = 0, fail = 0;
      for (const it of items) {
        const r = await runOp({ action: "delete", path: it.path });
        r.ok ? ok++ : fail++;
      }
      toast(`Moved ${ok} to trash${fail ? `, ${fail} failed` : ""}`, fail ? "err" : "ok");
      loadLibrary(state.path); return true;
    });
}
function doDelete() {
  openDeleteDialog([...state.selection.entries()].map(([path, info]) => ({ path, name: info.name })));
}

function openNewFolderDialog(parentPath) {
  if (!parentPath) { toast("Open a library folder first, then create folders inside it.", "err"); return; }
  openDialog("New folder", `<label>Folder name</label><input type="text" id="dlgInput" placeholder="Season 1" />`,
    async () => {
      const name = $("#dlgInput").value.trim();
      if (!name) return false;
      const r = await runOp({ action: "mkdir", path: parentPath, name });
      if (r.ok) { toast("Folder created", "ok"); loadLibrary(state.path); return true; }
      toast(r.message, "err"); return false;
    });
  setTimeout(() => $("#dlgInput")?.focus(), 50);
}
function doNewFolder() { openNewFolderDialog(state.path); }

function openMoveDialog(paths) {
  let pickerPath = state.path;
  openDialog("Move to…", `<div id="pickerWrap"></div>`, async () => {
    if (!pickerPath) { toast("Pick a destination folder.", "err"); return false; }
    let ok = 0, fail = 0;
    for (const path of paths) {
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
      const up = el("div", "p-row up", `${ICON.up}<span>Up one level</span>`);
      up.onclick = () => drawPicker(parent);
      picker.appendChild(up);
    }
    for (const f of data.folders) {
      const row = el("div", "p-row", `${ICON.folder}<span>${escapeHtml(f.name)}</span>`);
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
function doMove() { openMoveDialog([...state.selection.keys()]); }

/* ===================== remove library roots ===================== */
async function doRemoveRoots() {
  const paths = [...state.selection.keys()];
  if (!paths.length) return;
  try {
    const cfg = await api("/api/config");
    const next = (cfg.roots || []).filter(r => !paths.includes(r));
    await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
    await refreshSession();
    toast(`Removed ${paths.length} folder${paths.length > 1 ? "s" : ""} from library`, "ok");
    state.selection.clear();
    loadLibrary(null);
  } catch (e) { toast(e.message, "err"); }
}

/* ===================== add a folder (native OS chooser, with fallback) ===================== */
async function addFolder() {
  if (state.session.nativePicker) {
    try {
      const r = await api("/api/pick-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (r.cancelled) return;
      if (!r.ok) { toast(r.error || "Could not open the folder chooser.", "err"); return; }
      await addRootPath(r.path);
    } catch (e) { toast(e.message, "err"); }
  } else {
    openFolderPicker();   // fallback in-browser picker (e.g. when accessed remotely)
  }
}
async function addRootPath(path) {
  const cfg = await api("/api/config");
  const next = [...new Set([...(cfg.roots || []), path])];
  await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ roots: next }) });
  await refreshSession();
  await renderRoots();
  toast("Folder added", "ok");
  loadLibrary(null);
}

/* ===================== drag-and-drop folders ===================== */
async function addPaths(paths) {
  try {
    const r = await api("/api/add-paths", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths }) });
    if (r.added && r.added.length) {
      toast(`Added ${r.added.length} folder${r.added.length > 1 ? "s" : ""} to your library`, "ok");
      await refreshSession();
      loadLibrary(null);
    } else {
      toast("Couldn't read a folder from that drop. Drag a folder from your file manager.", "err");
    }
  } catch (e) { toast(e.message, "err"); }
}
function wireDragDrop() {
  const hint = $("#dropHint");
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || [])
    .some(t => t === "Files" || t === "text/uri-list");
  window.addEventListener("dragenter", (e) => {
    if (!state.session.canManage || !hasFiles(e)) return;
    depth++; hint.classList.remove("hidden");
  });
  window.addEventListener("dragover", (e) => {
    if (state.session.canManage && hasFiles(e)) e.preventDefault();
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    depth--; if (depth <= 0) { depth = 0; hint.classList.add("hidden"); }
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();                 // stop Firefox from opening the dropped file
    depth = 0; hint.classList.add("hidden");
    if (!state.session.canManage) return;
    const dt = e.dataTransfer;
    const raw = (dt.getData("text/uri-list") || dt.getData("text/plain") || "");
    const paths = raw.split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith("#"));
    if (!paths.length) { toast("Couldn't read a folder path from that drop.", "err"); return; }
    addPaths(paths);
  });
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
      const up = el("div", "p-row up", `${ICON.up}<span>Up</span>`);
      up.onclick = () => draw(data.parent);
      picker.appendChild(up);
    }
    for (const d of data.dirs) {
      const row = el("div", "p-row",
        `${ICON.folder}<span>${escapeHtml(d.name)}${d.videos ? ` <span class="muted small">· ${d.videos} videos</span>` : ""}</span>`);
      row.onclick = () => draw(d.path);
      picker.appendChild(row);
    }
    if (!data.dirs.length) picker.appendChild(el("div", "p-row up", "(no subfolders here)"));
    wrap.appendChild(picker);
    wrap.appendChild(el("div", "picker-cur", `Add: <b>${escapeHtml(data.path)}</b>`));
  }
  draw(null);
}

