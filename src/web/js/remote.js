/* Kadmu Phase 4b — browser P2P client (remote-from-anywhere).
 *
 * In the hosted edition the app shell is served by the cloud, but the user's video and library
 * live on their home node, which has NO public HTTP route. This module opens a direct WebRTC
 * connection to that node's `connector` (the cloud only brokers the handshake) and tunnels the
 * node's HTTP over a data channel using the exact byte layout of cloud/wire.py.
 *
 * Two integration surfaces, both designed to need ZERO changes elsewhere:
 *   1. `fetch` proxy — once the channel is up, relative `/api/...` (and `/sub`, `/thumb`, …)
 *      requests are transparently routed P2P. Every existing `api()` call in util.js Just Works;
 *      the rest of the frontend is none the wiser.
 *   2. `window.kadmuRemote.attachVideo(videoEl, path)` — video can't go through `fetch` (a
 *      `<video src>` does its own range requests the browser owns), so the player calls this in
 *      remote mode to drive the element from Media Source Extensions fed over the tunnel, which
 *      is what keeps seeking working end-to-end.
 *
 * Inert unless remote config is present (window.KADMU_REMOTE or ?kadmu_remote=… in the URL), so
 * shipping it in the self-host index.html costs nothing.  No framework, no build — vanilla, to
 * match the rest of src/web/js/. */
(function () {
  "use strict";

  // ── config: injected by the hosted app shell, or via URL for local testing ──────────────
  const q = new URLSearchParams(location.search);
  const CFG = window.KADMU_REMOTE || (q.get("kadmu_remote") ? {
    node: q.get("kadmu_remote"),
    signal: q.get("kadmu_signal") || location.origin,
    token: q.get("kadmu_token") || "dev",
  } : null);
  if (!CFG) return;                                   // not a remote session — stay dormant

  // ICE servers: start from whatever the shell injected, then (Phase 5) refresh from the
  // control-plane's entitlement-bound relay-credentials endpoint right before connecting, so an
  // over-budget / inactive tenant transparently falls back to STUN-only (P2P) instead of relay.
  let ICE = CFG.iceServers || [{ urls: "stun:stun.l.google.com:19302" }];
  const CREDS_URL = CFG.credsUrl ||
    (window.KADMU_CLOUD_URL ? window.KADMU_CLOUD_URL.replace(/\/$/, "") + "/api/relay-credentials" : null);

  async function refreshIce() {
    if (!CREDS_URL) return;
    try {
      const r = await realFetch(CREDS_URL, { credentials: "include" });
      const info = await r.json();
      if (info && Array.isArray(info.iceServers) && info.iceServers.length) ICE = info.iceServers;
    } catch (_) { /* keep the existing ICE — relay is a bonus, never a hard dependency */ }
  }

  // ── wire codec — must match cloud/wire.py byte-for-byte ─────────────────────────────────
  const REQ = 0x01, DATA = 0x02, END = 0x03, RES = 0x04, ABORT = 0x05;
  const MAX_CHUNK = 64 * 1024;
  const enc = new TextEncoder(), dec = new TextDecoder();

  function frame(type, stream, payload) {
    const body = payload || new Uint8Array(0);
    const buf = new Uint8Array(5 + body.length);
    buf[0] = type;
    new DataView(buf.buffer).setUint32(1, stream >>> 0);
    buf.set(body, 5);
    return buf.buffer;
  }
  const encReq = (s, method, path, headers) =>
    frame(REQ, s, enc.encode(JSON.stringify({ method, path, headers })));
  const encAbort = (s, reason) => frame(ABORT, s, enc.encode(JSON.stringify({ reason })));

  function decode(ab) {
    const buf = new Uint8Array(ab);
    const type = buf[0];
    const stream = new DataView(buf.buffer, buf.byteOffset).getUint32(1);
    const rest = buf.subarray(5);
    if (type === DATA) return { type, stream, payload: rest };
    if (type === END) return { type, stream };
    return { type, stream, meta: rest.length ? JSON.parse(dec.decode(rest)) : {} };
  }

  // ── signaling (plain fetch to the cloud broker — opaque SDP only) ────────────────────────
  // X-Kadmu-Node pins guest+host to one broker instance behind a sticky LB (cloud/infra,
  // §3). Uses the original fetch (realFetch) so signaling never loops through the P2P proxy.
  const sig = (path, body) =>
    realFetch(CFG.signal.replace(/\/$/, "") + path, {
      method: body ? "POST" : "GET",
      headers: Object.assign({ "X-Kadmu-Node": CFG.node },
        body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => r.json());

  // ── connection state ────────────────────────────────────────────────────────────────────
  let pc = null, channel = null, nextStream = 1;
  const streams = new Map();             // stream id -> { onHead, controller, done }
  let ready = null;                      // Promise resolved when the data channel opens

  function connect() {
    if (ready) return ready;
    ready = (async () => {
      await refreshIce();                                // Phase 5: entitlement-bound TURN (or STUN-only)
      const me = await sig("/signal/register", { role: "guest", node: CFG.node, token: CFG.token });
      if (me.error) throw new Error("remote: " + me.error);
      pc = new RTCPeerConnection({ iceServers: ICE });
      channel = pc.createDataChannel("kadmu", { ordered: true });
      channel.binaryType = "arraybuffer";
      channel.onmessage = (e) => dispatch(decode(e.data));

      const opened = new Promise((res, rej) => {
        channel.onopen = res;
        channel.onerror = () => rej(new Error("remote: data channel error"));
        pc.onconnectionstatechange = () => {
          if (["failed", "closed"].includes(pc.connectionState)) rej(new Error("remote: connection " + pc.connectionState));
        };
      });

      await pc.setLocalDescription(await pc.createOffer());
      await waitIceComplete(pc);                       // non-trickle: ship one complete offer
      await sig("/signal/send", { peer: me.peer, to: me.host, type: "offer", data: { sdp: pc.localDescription.sdp } });
      await pumpSignaling(me.peer);                     // wait for the host's answer
      await opened;
      return channel;
    })();
    return ready;
  }

  function waitIceComplete(pc) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((res) => {
      const check = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", check); res(); } };
      pc.addEventListener("icegatheringstatechange", check);
    });
  }

  async function pumpSignaling(peer) {
    for (let i = 0; i < 4 && pc.remoteDescription == null; i++) {
      const { messages } = await sig("/signal/poll?peer=" + peer);
      for (const m of messages || []) {
        if (m.type === "answer") await pc.setRemoteDescription({ type: "answer", sdp: m.data.sdp });
      }
    }
    if (pc.remoteDescription == null) throw new Error("remote: no answer from home node");
  }

  // ── demux incoming frames into per-stream ReadableStreams ───────────────────────────────
  function dispatch(f) {
    const st = streams.get(f.stream);
    if (f.type === RES) { if (st) st.onHead(f.meta); }
    else if (f.type === DATA) { if (st && st.controller) st.controller.enqueue(f.payload); }
    else if (f.type === END) { if (st) { try { st.controller && st.controller.close(); } catch (_) {} st.done(); streams.delete(f.stream); } }
  }

  // ── remoteFetch: a drop-in `fetch` over the data channel ────────────────────────────────
  async function remoteFetch(path, opts) {
    opts = opts || {};
    await connect();
    const id = (nextStream = (nextStream + 1) & 0x7fffffff) || 1;
    const headers = Object.assign({ "X-Kadmu": "1" }, opts.headers || {});

    let onHead, body;
    const head = new Promise((res) => { onHead = res; });
    body = new ReadableStream({
      start(controller) { streams.set(id, { onHead, controller, done() {} }); },
      cancel() { try { channel.send(encAbort(id, "cancel")); } catch (_) {} streams.delete(id); },
    });
    // The ReadableStream `start` runs synchronously above, registering the stream before we send.
    if (opts.signal) opts.signal.addEventListener("abort", () => { try { channel.send(encAbort(id, "abort")); } catch (_) {} });

    channel.send(encReq(id, opts.method || "GET", path, headers));
    const meta = await head;
    return new Response(body, {
      status: meta.status, statusText: meta.reason || "",
      headers: meta.headers || {},
    });
  }

  // ── install the transparent fetch proxy ─────────────────────────────────────────────────
  // Anything pointing at the home node (relative API/media paths) goes P2P; app-shell assets
  // served by the cloud (absolute URLs, /js, /fonts, /style.css) pass through to the network.
  const NODE_PREFIXES = ["/api/", "/sub", "/thumb", "/stream", "/transcode"];
  const realFetch = window.fetch.bind(window);
  function isNodePath(url) {
    if (/^https?:\/\//i.test(url)) return false;
    return NODE_PREFIXES.some((p) => url.startsWith(p));
  }
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (isNodePath(url)) return remoteFetch(url, Object.assign({}, init, { headers: init && init.headers }));
    return realFetch(input, init);
  };

  // ── MSE video tunnel: drive a <video> from byte ranges pulled over the channel ──────────
  // `<video src>` can't ride the fetch proxy, so the player calls this in remote mode. We pull
  // the stream in windows over the tunnel and append to a SourceBuffer, re-requesting on seek
  // so scrubbing still works. NOTE: MSE requires fragmented MP4; the node's remux path must emit
  // fMP4 (+frag_keyframe+empty_moov) for this to play — see cloud/README.md "What's stubbed".
  async function attachVideo(video, path, opts) {
    opts = opts || {};
    const mime = opts.mime || 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"';
    if (!("MediaSource" in window) || !MediaSource.isTypeSupported(mime)) {
      return attachBlob(video, path);                  // fallback: progressive download (no MSE)
    }
    const ms = new MediaSource();
    video.src = URL.createObjectURL(ms);
    await new Promise((res) => ms.addEventListener("sourceopen", res, { once: true }));
    const sb = ms.addSourceBuffer(mime);
    let offset = 0, total = Infinity, inflight = null;

    async function pump(from) {
      if (inflight) { inflight.abort(); }
      const ctl = new AbortController(); inflight = ctl;
      offset = from;
      while (offset < total && !ctl.signal.aborted) {
        const end = offset + 4 * 1024 * 1024 - 1;
        const r = await remoteFetch(path, { headers: { Range: `bytes=${offset}-${end}` }, signal: ctl.signal });
        const cr = r.headers.get("Content-Range");
        if (cr) total = parseInt(cr.split("/")[1], 10) || total;
        const data = new Uint8Array(await r.arrayBuffer());
        if (!data.length) break;
        await appendBuffer(sb, data);
        offset += data.length;
      }
      if (offset >= total && ms.readyState === "open") { try { ms.endOfStream(); } catch (_) {} }
    }
    function appendBuffer(sb, data) {
      return new Promise((res) => { sb.addEventListener("updateend", res, { once: true }); sb.appendBuffer(data); });
    }
    video.addEventListener("seeking", () => {
      // map seek time → byte offset (approximate via average bitrate); MSE corrects on append.
      const frac = video.duration ? video.currentTime / video.duration : 0;
      pump(Math.floor(frac * (total === Infinity ? 0 : total)));
    });
    pump(0);
  }

  async function attachBlob(video, path) {
    const r = await remoteFetch(path, {});
    video.src = URL.createObjectURL(await r.blob());
  }

  // ── public surface + autoboot ───────────────────────────────────────────────────────────
  window.kadmuRemote = { connect, remoteFetch, attachVideo, get peerState() { return pc && pc.connectionState; } };
  connect().catch((e) => console.error(e));            // start the handshake during boot
})();
