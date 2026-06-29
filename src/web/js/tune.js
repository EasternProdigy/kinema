"use strict";
/* tune.js — the player "tune" sheet: a slide-in tray that gathers the power-user
   controls (video adjustments, audio EQ/boost/normalize/mono/delay, and the
   frame-step / A-B loop / screenshot tools) so they're discoverable without
   cluttering the control bar. Built fresh each time it opens so every control
   reflects the live audioState / filtersState.
   Part of the Kadmu frontend; classic script sharing the global scope. */

/* ---- small builders ---- */
function _tuneSlider(label, min, max, step, value, fmt, onInput) {
  const row = el("div", "tune-row");
  row.appendChild(el("span", "tune-label", label));
  const wrap = el("div", "tune-ctl");
  const input = document.createElement("input");
  input.type = "range"; input.min = min; input.max = max; input.step = step; input.value = value;
  input.className = "tune-range seek";
  const out = el("span", "tune-val", fmt(+value));
  input.addEventListener("input", () => { out.textContent = fmt(+input.value); paintRange(input); onInput(+input.value); });
  paintRange(input);
  wrap.appendChild(input); wrap.appendChild(out);
  row.appendChild(wrap);
  return row;
}
function _tuneBtns(label, btns) {
  const row = el("div", "tune-row");
  row.appendChild(el("span", "tune-label", label));
  const wrap = el("div", "tune-btns");
  for (const b of btns) {
    const x = el("button", "tune-btn" + (b.active ? " active" : ""), b.html || escapeHtml(b.label || ""));
    x.type = "button";
    if (b.id) x.id = b.id;
    if (b.title) x.title = b.title;
    x.onclick = () => b.onClick(x);
    wrap.appendChild(x);
  }
  row.appendChild(wrap);
  return row;
}
function _tuneToggle(label, checked, onChange) {
  const row = el("div", "tune-row");
  const lab = el("label", "tune-switch");
  const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!checked;
  cb.addEventListener("change", () => onChange(cb.checked));
  lab.appendChild(cb);
  lab.appendChild(el("span", "tune-switch-track", "<i></i>"));
  lab.appendChild(el("span", "tune-switch-label", escapeHtml(label)));
  row.appendChild(lab);
  return row;
}
function _tuneSection(title, resetFn) {
  const sec = el("div", "tune-section");
  const head = el("div", "tune-sec-head");
  head.appendChild(el("h4", null, escapeHtml(title)));
  if (resetFn) {
    const r = el("button", "tune-reset", "Reset"); r.type = "button";
    r.onclick = () => { resetFn(); buildTuneSheet(); };
    head.appendChild(r);
  }
  sec.appendChild(head);
  return sec;
}

function buildTuneSheet() {
  const sheet = $("#tuneSheet");
  if (!sheet) return;
  sheet.innerHTML = "";
  const head = el("div", "tune-head");
  head.appendChild(el("span", "tune-title", "Tune"));
  const x = el("button", "icon-round", ICON.close);
  x.title = "Close (T)"; x.setAttribute("aria-label", "Close tune"); x.onclick = closeTune;
  head.appendChild(x);
  sheet.appendChild(head);
  const body = el("div", "tune-body");
  sheet.appendChild(body);

  /* ---- Video ---- */
  const vid = _tuneSection("Video", resetFilters);
  vid.appendChild(_tuneSlider("Brightness", 0.4, 1.6, 0.01, filtersState.brightness, v => Math.round(v * 100) + "%", v => setAdjust("brightness", v)));
  vid.appendChild(_tuneSlider("Contrast", 0.4, 1.6, 0.01, filtersState.contrast, v => Math.round(v * 100) + "%", v => setAdjust("contrast", v)));
  vid.appendChild(_tuneSlider("Saturation", 0, 2, 0.01, filtersState.saturation, v => Math.round(v * 100) + "%", v => setAdjust("saturation", v)));
  vid.appendChild(_tuneSlider("Zoom", 1, 2, 0.01, filtersState.zoom, v => v.toFixed(2) + "×", v => setZoom(v)));
  vid.appendChild(_tuneBtns("Rotate / flip", [
    { html: ICON.rotate, title: "Rotate 90°", active: filtersState.rotate !== 0, onClick: () => { rotateBy(90); buildTuneSheet(); } },
    { html: ICON.flipH, title: "Flip horizontally", active: filtersState.flipH, onClick: () => { toggleFlip("h"); buildTuneSheet(); } },
    { html: ICON.flipV, title: "Flip vertically", active: filtersState.flipV, onClick: () => { toggleFlip("v"); buildTuneSheet(); } },
  ]));
  vid.appendChild(ccSeg("Aspect", FIT_MODES.map(m => ({ key: m.id, label: m.label })), filtersState.fit, setFit));
  // Deinterlace (yadif) — needs a server-side ffmpeg pass, so only offer it when there's an encoder.
  if (state.session && state.session.ffmpeg && typeof setDeinterlace === "function") {
    vid.appendChild(_tuneToggle("Deinterlace — smooth interlaced DVD / TV video", state.deinterlace, setDeinterlace));
  }
  body.appendChild(vid);

  /* ---- Audio ---- */
  const aud = _tuneSection("Audio", resetAudio);
  if (audioState.available === false) {
    aud.appendChild(el("p", "tune-note", "Audio effects aren't available in this browser."));
  } else {
    aud.appendChild(ccSeg("Equalizer",
      Object.keys(EQ_PRESETS).map(k => ({ key: k, label: EQ_PRESETS[k].label })),
      (audioState.preset in EQ_PRESETS) ? audioState.preset : "flat",
      k => { setEqPreset(k); buildTuneSheet(); }));
    const eqRow = el("div", "tune-eq");
    EQ_BANDS.forEach((b, i) => {
      const col = el("div", "tune-eq-band");
      const dbLab = el("span", "tune-eq-db", (audioState.eq[i] > 0 ? "+" : "") + (audioState.eq[i] || 0));
      const input = document.createElement("input");
      input.type = "range"; input.min = -12; input.max = 12; input.step = 1; input.value = audioState.eq[i] || 0;
      input.className = "tune-eq-slider";
      input.title = (b.f >= 1000 ? (b.f / 1000) + "k" : b.f) + " Hz";
      input.addEventListener("input", () => {
        setEqBand(i, +input.value);
        dbLab.textContent = (+input.value > 0 ? "+" : "") + input.value;
      });
      col.appendChild(dbLab);
      col.appendChild(input);
      col.appendChild(el("span", "tune-eq-hz", b.f >= 1000 ? (b.f / 1000) + "k" : b.f));
      eqRow.appendChild(col);
    });
    aud.appendChild(eqRow);
    aud.appendChild(_tuneSlider("Volume boost", 0.5, 3, 0.05, audioState.boost, v => Math.round(v * 100) + "%", setBoost));
    aud.appendChild(_tuneSlider("Audio delay", 0, 1000, 10, audioState.delayMs, v => Math.round(v) + " ms", setAudioDelay));
    aud.appendChild(_tuneToggle("Normalize — level loud & quiet parts", audioState.normalize, setNormalize));
    aud.appendChild(_tuneToggle("Mono — downmix to one channel", audioState.mono, setMono));
  }
  body.appendChild(aud);

  /* ---- Tools ---- */
  const tools = _tuneSection("Tools", null);
  tools.appendChild(_tuneBtns("Frame step", [
    { html: "◀︎", title: "Previous frame (,) — paused", onClick: () => frameStep(-1) },
    { html: "︎▶", title: "Next frame (.) — paused", onClick: () => frameStep(1) },
  ]));
  tools.appendChild(_tuneBtns("A-B loop", [
    { label: state.abA == null ? "Set A" : (state.abB == null ? "Set B" : "On"), id: "abLoopBtn", active: state.abA != null, title: "A-B loop (B)", onClick: () => { cycleAbLoop(); buildTuneSheet(); } },
    { label: "Clear", onClick: () => { clearAbLoop(); buildTuneSheet(); } },
  ]));
  tools.appendChild(_tuneBtns("Screenshot", [
    { html: ICON.camera + "<span>Save frame</span>", title: "Save the current frame (I)", onClick: screenshot },
  ]));
  body.appendChild(tools);

  updateTuneButton();
}

function updateTuneButton() {
  const b = $("#tuneBtn");
  if (b) b.classList.toggle("on", audioActive() || filtersActive());
}

let _tuneOpen = false;
function openTune() {
  ensureAudioGraph();           // learn availability + ready the EQ before we draw it
  buildTuneSheet();
  $("#tuneSheet")?.classList.remove("hidden");
  $("#playerOverlay")?.classList.add("tune-open");
  _tuneOpen = true;
  showUi();
}
function closeTune() {
  $("#tuneSheet")?.classList.add("hidden");
  $("#playerOverlay")?.classList.remove("tune-open");
  _tuneOpen = false;
}
function toggleTune() { _tuneOpen ? closeTune() : openTune(); }
