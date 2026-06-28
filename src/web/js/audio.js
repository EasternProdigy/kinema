"use strict";
/* audio.js — Web Audio processing graph: equalizer, volume boost (>100%),
   normalization (compressor), mono downmix, and audio delay (A/V sync).
   Part of the Kadmu frontend, split from one app.js into ordered classic scripts
   that share the global scope; load order is fixed in index.html.

   The graph is built lazily the first time playback starts (an AudioContext can
   only start after a user gesture). It taps the single, persistent <video> element
   once via createMediaElementSource — so it lives for the whole page and survives
   every clip swap. When the browser has no Web Audio API, every control below is a
   safe no-op and the player still plays normally (just without these extras). */

/* 5-band graphic EQ — low shelf, three peaking mids, high shelf. */
const EQ_BANDS = [
  { f: 60,    type: "lowshelf"  },
  { f: 250,   type: "peaking", q: 1.0 },
  { f: 1000,  type: "peaking", q: 1.0 },
  { f: 4000,  type: "peaking", q: 1.0 },
  { f: 12000, type: "highshelf" },
];
const EQ_PRESETS = {
  flat:    { label: "Flat",        gains: [0, 0, 0, 0, 0] },
  bass:    { label: "Bass boost",  gains: [7, 4, 0, 0, 0] },
  treble:  { label: "Treble boost",gains: [0, 0, 0, 4, 7] },
  vocal:   { label: "Voice",       gains: [-3, 0, 4, 3, 0] },
  loud:    { label: "Loudness",    gains: [6, 2, 0, 2, 6] },
  night:   { label: "Late night",  gains: [-2, 0, 3, 1, -3] },
};

const audioState = {
  available: null,        // null = not yet probed; true/false after first build attempt
  preset: "flat",
  eq: [0, 0, 0, 0, 0],    // per-band gain in dB
  boost: 1.0,             // output gain multiplier (1 = 100%; up to 3 = 300%)
  normalize: false,       // dynamics compression + makeup (volume leveling)
  mono: false,            // downmix to a single channel
  delayMs: 0,             // delay the audio relative to the video (0..1000ms)
};

let _actx = null, _src = null;
let _eqNodes = [], _delayNode = null, _compNode = null, _makeupNode = null, _boostNode = null, _monoNode = null;
let _audioBuilt = false;

// True once the user has nudged anything off its default (drives the "on" dot).
function audioActive() {
  return audioState.preset !== "flat" || audioState.eq.some(g => g !== 0) ||
    audioState.boost !== 1.0 || audioState.normalize || audioState.mono || audioState.delayMs !== 0;
}

// Build the processing graph once, lazily, after playback has started.
function ensureAudioGraph() {
  if (_audioBuilt) return audioState.available;
  _audioBuilt = true;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) { audioState.available = false; return false; }
  try {
    _actx = new Ctx();
    _src = _actx.createMediaElementSource(video);
    _eqNodes = EQ_BANDS.map(b => {
      const n = _actx.createBiquadFilter();
      n.type = b.type;
      n.frequency.value = b.f;
      if (b.q) n.Q.value = b.q;
      n.gain.value = 0;
      return n;
    });
    _delayNode = _actx.createDelay(2.0);
    _compNode = _actx.createDynamicsCompressor();
    _makeupNode = _actx.createGain();
    _boostNode = _actx.createGain();
    _monoNode = _actx.createGain();
    _monoNode.channelCount = 1;
    _monoNode.channelCountMode = "explicit";
    _monoNode.channelInterpretation = "speakers";

    // source -> delay -> eq(5) -> compressor -> makeup -> boost -> [mono?] -> dest
    let node = _src;
    node.connect(_delayNode); node = _delayNode;
    for (const eq of _eqNodes) { node.connect(eq); node = eq; }
    node.connect(_compNode); node = _compNode;
    node.connect(_makeupNode); node = _makeupNode;
    node.connect(_boostNode); node = _boostNode;
    // boost -> dest (or boost -> mono -> dest) wired by applyAudio()
    audioState.available = true;
    applyAudio();
    return true;
  } catch (e) {
    audioState.available = false;
    return false;
  }
}

// Push the whole audioState onto the live nodes (cheap; called on any change).
function applyAudio() {
  if (!_actx || !_boostNode) return;
  const t = _actx.currentTime;
  _eqNodes.forEach((n, i) => { try { n.gain.setTargetAtTime(audioState.eq[i] || 0, t, 0.02); } catch {} });
  try { _delayNode.delayTime.setTargetAtTime(Math.max(0, audioState.delayMs / 1000), t, 0.02); } catch {}
  if (audioState.normalize) {
    try {
      _compNode.threshold.value = -28; _compNode.knee.value = 28;
      _compNode.ratio.value = 8; _compNode.attack.value = 0.003; _compNode.release.value = 0.25;
    } catch {}
    _makeupNode.gain.setTargetAtTime(1.7, t, 0.02);
  } else {
    try {
      _compNode.threshold.value = 0; _compNode.knee.value = 0;
      _compNode.ratio.value = 1; _compNode.attack.value = 0.003; _compNode.release.value = 0.25;
    } catch {}
    _makeupNode.gain.setTargetAtTime(1.0, t, 0.02);
  }
  _boostNode.gain.setTargetAtTime(audioState.boost, t, 0.02);
  // (re)wire the mono tap
  try { _boostNode.disconnect(); } catch {}
  try { _monoNode.disconnect(); } catch {}
  if (audioState.mono) { _boostNode.connect(_monoNode); _monoNode.connect(_actx.destination); }
  else { _boostNode.connect(_actx.destination); }
}

// Web Audio contexts start suspended; resume on every play so processing is live.
function resumeAudio() {
  if (_actx && _actx.state === "suspended") { _actx.resume().catch(() => {}); }
}

/* ---- setters used by the tune sheet ---- */
function setEqPreset(name) {
  const p = EQ_PRESETS[name] || EQ_PRESETS.flat;
  audioState.preset = name in EQ_PRESETS ? name : "flat";
  audioState.eq = p.gains.slice();
  ensureAudioGraph(); applyAudio();
}
function setEqBand(i, db) {
  audioState.eq[i] = Math.max(-12, Math.min(12, +db || 0));
  audioState.preset = "custom";
  ensureAudioGraph(); applyAudio();
}
function setBoost(mult) {
  audioState.boost = Math.max(0, Math.min(3, +mult || 1));
  ensureAudioGraph(); applyAudio();
}
function setNormalize(on) { audioState.normalize = !!on; ensureAudioGraph(); applyAudio(); }
function setMono(on) { audioState.mono = !!on; ensureAudioGraph(); applyAudio(); }
function setAudioDelay(ms) {
  audioState.delayMs = Math.max(0, Math.min(1000, Math.round(+ms || 0)));
  ensureAudioGraph(); applyAudio();
}
function resetAudio() {
  audioState.preset = "flat";
  audioState.eq = [0, 0, 0, 0, 0];
  audioState.boost = 1.0;
  audioState.normalize = false;
  audioState.mono = false;
  audioState.delayMs = 0;
  applyAudio();
}
