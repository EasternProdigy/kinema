# Kadmu Cloud layer — Phase 4b: remote-from-anywhere (P2P)

This directory is **not shipped to self-hosters**. It's the thin cloud layer from the
[roadmap](../docs/ROADMAP.md) §1 — the part that *can't* be standard-library and *isn't part of
the open-source core*. Phase 4b is the headline Cloud upgrade: **watch your home library from
anywhere, with the video streaming peer-to-peer so our egress stays ≈ $0** (ROADMAP §5).

> **The core promise is untouched.** `src/kadmu/` is still stdlib-only, single-file-spirit, no
> `pip install`. Nothing in this directory is imported by the core, and the core needs **zero
> changes** to be reachable remotely (the connector talks to it as a localhost client). The one
> unavoidable dependency — `aiortc`, for real WebRTC — lives only in the connector, here in
> `cloud/`. See [requirements.txt](requirements.txt).

## The shape

```
   browser (anywhere)                  cloud (broker only)                home node (your box)
  ┌──────────────────┐   register+SDP  ┌───────────────────┐  register+SDP ┌───────────────────┐
  │  app shell        │ ──────────────▶│ signaling/server  │◀───────────── │ connector/        │
  │  + js/remote.js   │                │  (stdlib, no video)│               │  connector.py     │
  │                   │                └───────────────────┘               │  (aiortc)         │
  │  fetch proxy ─────┼───────────  WebRTC data channel  ───────────────────┼─▶ http://127.0.0.1│
  │  MSE  ◀───────────┼───────────  (wire.py framing)    ◀──────────────────┼── :8000 core node │
  └──────────────────┘            video never touches cloud                 └───────────────────┘
```

1. The **connector** runs on the user's machine next to the normal `python3 src/server.py`
   node. It registers with the **signaling broker** as the *host* for a stable node id.
2. The **browser** (hosted app shell + `js/remote.js`) registers as a *guest*, and the broker
   passes one WebRTC offer/answer + ICE between them. That's the broker's entire job.
3. A direct **data channel** opens browser↔node. From here the cloud is out of the loop:
   `remote.js` tunnels the node's HTTP (the `api()` JSON calls and the byte-range video) over
   the channel using the [`wire.py`](wire.py) framing. **The video bytes go peer-to-peer and
   never traverse our servers** — that's the whole cost model.

## Components

| path | runtime | dep? | what it is |
|---|---|---|---|
| [`wire.py`](wire.py) | both Python peers | **stdlib** | the HTTP-over-datachannel framing codec (the protocol heart) |
| [`tests/test_wire.py`](tests/test_wire.py) | dev | **stdlib** | unit tests for the codec — `python3 -m unittest discover -s cloud/tests` |
| [`signaling/server.py`](signaling/server.py) | cloud | **stdlib** | the handshake broker (HTTP long-poll relay + entitlement gate) |
| [`connector/connector.py`](connector/connector.py) | home node | **aiortc** | the P2P endpoint; proxies data-channel ⇄ `http://127.0.0.1:<port>` |
| [`../src/web/js/remote.js`](../src/web/js/remote.js) | browser | native | signaling + `RTCPeerConnection` + `fetch` proxy + MSE video tunnel |

## The wire protocol (`wire.py`)

A data channel is message-oriented, so HTTP is reframed. Every message is one frame:

```
byte 0     type   (REQ 0x01 · DATA 0x02 · END 0x03 · RES 0x04 · ABORT 0x05)
bytes 1-4  stream id (uint32 BE) — one HTTP exchange = one stream id
bytes 5..  REQ/RES/ABORT → UTF-8 JSON head;  DATA → raw body bytes;  END → empty
```

- A request is `REQ [DATA…] END`; a response is `RES [DATA…] END`. Bodies split into ≤64 KiB
  DATA frames so a 4 GiB movie range never becomes one giant message.
- `ABORT` tears a stream down early — `remote.js` sends it the moment the user seeks, so the
  now-stale range stops streaming instead of wasting the uplink. This is what keeps **seeking**
  responsive over P2P.

`remote.js` reimplements this exact byte layout in JS; the two are kept in lockstep, and the
Python side is unit-tested so drift surfaces immediately.

## Relay / TURN policy (ROADMAP §5 — the one place egress can leak)

- **Direct P2P (STUN):** ~80–90% of networks. Cloud egress = the KB of handshake. This is the
  default; the connector ships only a public STUN server.
- **TURN relay:** the hostile-NAT minority. Relayed video **is** real egress if the relay is
  ours, so it's **never the default**. TURN is added only when explicitly configured
  (`KADMU_TURN_URL`), and the plan is to treat it as a **capped, paid add-on / BYO-relay** —
  *never* "tunnel all video through us." The connector's `_ice_servers()` encodes this: STUN
  always, TURN only on opt-in.

## Entitlement — the Phase 4a seam

Remote access is a **paid** Cloud perk, so the broker won't broker for free. Every `register`
carries a `token`; `verify_entitlement()` must pass before any SDP is relayed.

- **Today:** an HMAC token signed with `KADMU_SIGNAL_SECRET`, bound to a node id + expiry.
  Mint one with `python3 signaling/server.py --mint <node>`. With no secret set the broker runs
  in **dev mode** and accepts any token (local testing only).
- **Production (Phase 4a):** the control-plane mints this token after Stripe confirms an active
  subscription, encoding the user + plan; `verify_entitlement()` becomes the billing check.
  This is the single, clean integration point between 4a (billing) and 4b (access).

## Share-a-link (designed, not yet built)

A time-limited link that lets a friend watch **one** video with no account — also P2P, so still
≈ $0 egress. The mechanism reuses everything above: a share token is a scoped entitlement
(`{node, path, exp, one-video}`) the broker accepts for a guest, and `remote.js`'s fetch proxy
is constrained to that single path. Tracked as the next Phase 4b increment.

## Running it (local end-to-end)

```bash
# 1. the core node (unchanged) — serves your library on localhost
python3 src/server.py ~/Videos                     # → http://127.0.0.1:8000

# 2. the signaling broker (stdlib, dev mode = any token)
python3 cloud/signaling/server.py                  # → :8443

# 3. the connector, on the same machine (needs aiortc)
pip install -r cloud/requirements.txt
KADMU_SIGNAL_URL=http://127.0.0.1:8443 KADMU_NODE_ID=demo \
KADMU_LOCAL_PORT=8000 python3 cloud/connector/connector.py

# 4. a browser, pointed at any app shell, with remote params:
#    file/host the app shell, then open with:
#      ?kadmu_remote=demo&kadmu_signal=http://127.0.0.1:8443&kadmu_token=dev
```

(Real cross-internet use puts the broker on a public host and runs steps 1+3 on the home box;
the browser is anywhere.)

## What's verified vs. what's stubbed

Honesty about test coverage, since most of P2P can't be exercised without two real networked
peers + a browser + a TURN server:

**Verified here (CI-able, no network):**
- ✅ `wire.py` framing codec — 8 unit tests green (round-trips, binary-clean bodies, chunking,
  garbage rejection). This is the correctness-critical part.
- ✅ `signaling/server.py` — boots; `/healthz`, `register`/`send`/`poll` mailbox relay and the
  HMAC entitlement gate exercised by a stdlib smoke test.
- ✅ `py_compile` on the connector; `node --check` on `remote.js`.

**Structured & reviewed, but needs real-network integration testing:**
- ⚠ `connector.py` aiortc transport (ICE/DTLS/SCTP, backpressure via `bufferedAmount`,
  ABORT handling). Logic is in place; not yet run against a live browser peer.
- ⚠ `remote.js` `RTCPeerConnection` handshake and the `fetch` proxy under a real channel.
- ⚠ **MSE video tunnel** — the biggest open item. MSE requires **fragmented MP4**; the node's
  remux path currently emits plain MP4. To make remote *video* (not just the JSON API) play,
  the core's `build_remux` needs an fMP4 profile (`-movflags +frag_keyframe+empty_moov+default_base_moof`)
  for the remote case. `remote.js` falls back to a progressive blob download when MSE can't
  accept the mime, so small clips work regardless. **This is the main follow-up.**

## Why this respects the project's soul

- Core stays **stdlib-only / no-pip** — the dependency and all WebRTC weight is quarantined in
  `cloud/`, and the core doesn't import or even know about it.
- The cloud is a **handshake broker, not a video pipe** — egress ≈ $0, no DMCA-storage liability.
- Even the broker is **stdlib, zero-install** — the no-install ethos extends into the cloud
  layer where it can.
