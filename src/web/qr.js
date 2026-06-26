"use strict";
/* Tiny dependency-free QR encoder — byte mode, error-correction level M,
   versions 1–6 (enough for any LAN URL). Renders a crisp SVG. No CDN, no build
   step; bundled like everything else in Kinema. The module placement mirrors the
   ISO/IEC 18004 layout (verified module-for-module against a reference encoder
   and round-tripped through a decoder). Public API:
       KinemaQR.svg(text, {quiet, dark, light})  -> SVG string
       KinemaQR.matrix(text, forcedMask?)         -> boolean[][]  (used by tests) */
(function () {
  const EXP = new Array(256), LOG = new Array(256);
  (function () { let x = 1; for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } })();
  const gmul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[(LOG[a] + LOG[b]) % 255];

  function rsGen(n) {
    let g = [1];
    for (let i = 0; i < n; i++) {
      const r = new Array(g.length + 1).fill(0);
      for (let j = 0; j < g.length; j++) { r[j] ^= g[j]; r[j + 1] ^= gmul(g[j], EXP[i]); }
      g = r;
    }
    return g;
  }
  function rsEncode(data, n) {
    const gen = rsGen(n), ec = new Array(n).fill(0);
    for (const b of data) {
      const f = b ^ ec[0];
      ec.shift(); ec.push(0);
      if (f) for (let j = 0; j < n; j++) ec[j] ^= gmul(gen[j + 1], f);
    }
    return ec;
  }

  const EC = {
    1: { ecc: 10, blocks: [16] },
    2: { ecc: 16, blocks: [28] },
    3: { ecc: 26, blocks: [44] },
    4: { ecc: 18, blocks: [32, 32] },
    5: { ecc: 24, blocks: [43, 43] },
    6: { ecc: 16, blocks: [27, 27, 27, 27] },
  };
  const CAP = { 1: 14, 2: 26, 3: 42, 4: 62, 5: 84, 6: 106 };
  const ALIGN = { 1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34] };

  function toBytes(text) {
    if (typeof TextEncoder !== "undefined") return Array.from(new TextEncoder().encode(text));
    const out = []; const s = unescape(encodeURIComponent(text));
    for (let i = 0; i < s.length; i++) out.push(s.charCodeAt(i));
    return out;
  }

  function codewords(text) {
    const bytes = toBytes(text);
    let version = 0;
    for (let v = 1; v <= 6; v++) if (bytes.length <= CAP[v]) { version = v; break; }
    if (!version) throw new Error("QR: data too long for this encoder");
    const ec = EC[version], totalData = ec.blocks.reduce((a, b) => a + b, 0);

    const bits = [];
    const put = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    put(0b0100, 4);
    put(bytes.length, 8);
    for (const b of bytes) put(b, 8);
    const cap = totalData * 8;
    for (let i = 0; i < 4 && bits.length < cap; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const pad = [0xEC, 0x11];
    for (let i = 0; bits.length < cap; i++) put(pad[i & 1], 8);

    const data = [];
    for (let i = 0; i < bits.length; i += 8) { let b = 0; for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j]; data.push(b); }

    const dBlocks = [], eBlocks = [];
    let off = 0;
    for (const n of ec.blocks) { const blk = data.slice(off, off + n); off += n; dBlocks.push(blk); eBlocks.push(rsEncode(blk, ec.ecc)); }
    const out = [];
    const maxD = Math.max(...ec.blocks);
    for (let i = 0; i < maxD; i++) for (const blk of dBlocks) if (i < blk.length) out.push(blk[i]);
    for (let i = 0; i < ec.ecc; i++) for (const blk of eBlocks) out.push(blk[i]);
    return { version, words: out };
  }

  function maskFn(p) {
    return [
      (r, c) => (r + c) % 2 === 0,
      (r, c) => r % 2 === 0,
      (r, c) => c % 3 === 0,
      (r, c) => (r + c) % 3 === 0,
      (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
      (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
      (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
      (r, c) => (((r * c) % 3) + ((r + c) % 2)) % 2 === 0,
    ][p];
  }

  function formatBits(mask) {
    let rem = mask;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ (((rem >> 9) & 1) * 0x537);
    return ((mask << 10) | rem) ^ 0x5412;
  }

  function probe(m, n, row, col) {
    for (let r = -1; r < 8; r++) {
      if (row + r <= -1 || n <= row + r) continue;
      for (let c = -1; c < 8; c++) {
        if (col + c <= -1 || n <= col + c) continue;
        m[row + r][col + c] =
          (r >= 0 && r <= 6 && (c === 0 || c === 6)) ||
          (c >= 0 && c <= 6 && (r === 0 || r === 6)) ||
          (r >= 2 && r <= 4 && c >= 2 && c <= 4);
      }
    }
  }
  function alignment(m, n, version) {
    const pos = ALIGN[version];
    for (let i = 0; i < pos.length; i++) for (let j = 0; j < pos.length; j++) {
      const row = pos[i], col = pos[j];
      if (m[row][col] !== null) continue;
      for (let r = -2; r < 3; r++) for (let c = -2; c < 3; c++)
        m[row + r][col + c] = (r === -2 || r === 2 || c === -2 || c === 2 || (r === 0 && c === 0));
    }
  }
  function timing(m, n) {
    for (let r = 8; r < n - 8; r++) if (m[r][6] === null) m[r][6] = r % 2 === 0;
    for (let c = 8; c < n - 8; c++) if (m[6][c] === null) m[6][c] = c % 2 === 0;
  }
  function typeInfo(m, n, mask) {
    const bits = formatBits(mask);
    for (let i = 0; i < 15; i++) {
      const v = ((bits >> i) & 1) === 1;
      if (i < 6) m[i][8] = v;
      else if (i < 8) m[i + 1][8] = v;
      else m[n - 15 + i][8] = v;
    }
    for (let i = 0; i < 15; i++) {
      const v = ((bits >> i) & 1) === 1;
      if (i < 8) m[8][n - i - 1] = v;
      else if (i < 9) m[8][15 - i - 1 + 1] = v;
      else m[8][15 - i - 1] = v;
    }
    m[n - 8][8] = true;
  }
  function mapData(m, n, words, mask) {
    const mf = maskFn(mask), dlen = words.length;
    let inc = -1, row = n - 1, bitIndex = 7, byteIndex = 0;
    for (let col = n - 1; col > 0; col -= 2) {
      if (col <= 6) col -= 1;
      const cols = [col, col - 1];
      for (;;) {
        for (const c of cols) {
          if (m[row][c] !== null) continue;
          let dark = byteIndex < dlen && ((words[byteIndex] >> bitIndex) & 1) === 1;
          if (mf(row, c)) dark = !dark;
          m[row][c] = dark;
          if (--bitIndex === -1) { byteIndex++; bitIndex = 7; }
        }
        row += inc;
        if (row < 0 || n <= row) { row -= inc; inc = -inc; break; }
      }
    }
  }
  function build(version, words, mask) {
    const n = version * 4 + 17;
    const m = Array.from({ length: n }, () => new Array(n).fill(null));
    probe(m, n, 0, 0); probe(m, n, 0, n - 7); probe(m, n, n - 7, 0);
    alignment(m, n, version);
    timing(m, n);
    typeInfo(m, n, mask);
    mapData(m, n, words, mask);
    return m;
  }

  function penalty(m) {
    const n = m.length;
    let p = 0;
    const d = (r, c) => m[r][c] === true;
    for (let r = 0; r < n; r++) for (const vert of [0, 1]) {
      let run = 1, prev = vert ? m[0][r] : m[r][0];
      for (let i = 1; i < n; i++) {
        const v = vert ? m[i][r] : m[r][i];
        if (v === prev) { run++; if (run === 5) p += 3; else if (run > 5) p += 1; }
        else { run = 1; prev = v; }
      }
    }
    for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) {
      const v = d(r, c);
      if (v === d(r, c + 1) && v === d(r + 1, c) && v === d(r + 1, c + 1)) p += 3;
    }
    const p1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], p2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    const b = (r, c) => d(r, c) ? 1 : 0;
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
      if (c + 11 <= n) { let a = true, e = true; for (let k = 0; k < 11; k++) { const v = b(r, c + k); if (v !== p1[k]) a = false; if (v !== p2[k]) e = false; } if (a) p += 40; if (e) p += 40; }
      if (r + 11 <= n) { let a = true, e = true; for (let k = 0; k < 11; k++) { const v = b(r + k, c); if (v !== p1[k]) a = false; if (v !== p2[k]) e = false; } if (a) p += 40; if (e) p += 40; }
    }
    let dc = 0;
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (d(r, c)) dc++;
    p += Math.floor(Math.abs((dc * 100) / (n * n) - 50) / 5) * 10;
    return p;
  }

  function matrix(text, forced) {
    const { version, words } = codewords(text);
    if (forced != null) return build(version, words, forced);
    let best = null, bestP = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const m = build(version, words, mask);
      const pen = penalty(m);
      if (pen < bestP) { bestP = pen; best = m; }
    }
    return best;
  }

  function svg(text, opts) {
    opts = opts || {};
    const quiet = opts.quiet == null ? 4 : opts.quiet;
    const dark = opts.dark || "#211915", light = opts.light || "#ffffff";
    const m = matrix(text);
    const size = m.length, dim = size + quiet * 2;
    let path = "";
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++)
      if (m[r][c] === true) path += `M${c + quiet} ${r + quiet}h1v1h-1z`;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}" ` +
      `shape-rendering="crispEdges" role="img" aria-label="QR code for ${text}">` +
      `<rect width="${dim}" height="${dim}" fill="${light}"/>` +
      `<path d="${path}" fill="${dark}"/></svg>`;
  }

  const api = { svg, matrix };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  globalThis.KinemaQR = api;
})();
