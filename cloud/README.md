# Kadmu Cloud (`cloud/`) — the hosted layer

This directory is the **paid, hosted side of Kadmu** (Phase 4 of [docs/ROADMAP.md](../docs/ROADMAP.md)).
It is **NOT shipped to self-hosters** and is never required to run the open-source node.

The whole product stays open and unlocked; Cloud monetizes **convenience and
infrastructure**, never features. Critically, **the cloud never stores or pipes your
video** — files stay on your machine. Our servers only host the *account, billing,
and the connection handshake*, which keeps egress ≈ $0 (see docs/ROADMAP.md — Cost model).

```
cloud/
├─ control-plane/   ← Phase 4a: signup, Stripe billing, entitlement/license API, dashboard, donations
├─ signaling/       ← Phase 4b: P2P (WebRTC) handshake broker for remote-from-anywhere
├─ connector/       ← Phase 4b: the home-node P2P endpoint (aiortc) — bridges the data channel ⇄ localhost node
├─ wire.py          ← Phase 4b: the HTTP-over-datachannel framing codec (+ tests/)
└─ infra/           ← Phase 5: reverse proxy, scaling, observability (deploy notes / design)
```

> **The core promise is untouched.** `src/kadmu/` is still stdlib-only, single-file-spirit, no
> `pip install`. Nothing in this directory is imported by the core. The control-plane and the
> signaling broker are themselves **stdlib-only**; the one unavoidable third-party dependency —
> `aiortc`, for real WebRTC — is quarantined to the connector (see [requirements.txt](requirements.txt)),
> exactly the "what can't be stdlib lives in `cloud/`" split from docs/ROADMAP.md.

---

## control-plane — Phase 4a (accounts, billing, licensing)

A standalone **stdlib-only** Python service (same soul as the core: no build, no pip —
Stripe is reached over its REST API with `urllib`). It runs in **MOCK mode by default**,
so the entire signup → pay → license flow works end-to-end with **zero Stripe setup**.

**Run it (mock mode):**

```bash
python3 cloud/control-plane/server.py
# → http://127.0.0.1:8787  (landing, /pricing, /donate, /dashboard)
```

**The funnel it implements**

1. **Landing / pricing / donate** — brand-true marketing pages (server-rendered, no JS).
2. **Pay-first signup** (`/signup` → `/api/signup`) — creates a cloud account, then sends
   the visitor to Stripe Checkout. Access activates only once payment succeeds.
3. **Stripe billing** — Checkout (subscription), the customer portal ("Manage billing"),
   and **webhooks** (`/api/webhook/stripe`, HMAC-SHA256 signature verified) keep
   subscription state in sync: `checkout.session.completed`,
   `customer.subscription.updated|deleted`, `invoice.payment_failed`.
4. **Entitlement / license API** (`/api/license`) — a tenant's node proves it holds the
   per-tenant secret (HMAC over `<tenant>.<ts>`; the secret never crosses the wire), and
   if the owning account is subscribed, gets back a **short-lived, signed (HS256) license
   token** carrying an **offline-grace** window.
5. **Dashboard** (`/dashboard`) — subscription status, **node connection details**
   (tenant id + secret + a ready-to-paste run command), and Manage-billing.
6. **Donations** (`/donate`) — one-time Stripe Checkout for the OSS side, no account needed.

**Going live:** copy [`control-plane/.env.example`](control-plane/.env.example) → `.env`,
set `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PRICE_*`, put it behind a
reverse proxy for HTTPS, and point a Stripe webhook at `<BASE_URL>/api/webhook/stripe`.

### How the open-source node attaches

The node (`src/kadmu/`) runs **cloud-attached** when given a cloud URL, a tenant id, and
the tenant secret (from the dashboard) — see [`src/kadmu/cloud.py`](../src/kadmu/cloud.py):

```bash
KADMU_CLOUD_URL=https://cloud.kadmu.app \
KADMU_CLOUD_TENANT=ten_xxx \
KADMU_CLOUD_SECRET=••••• \
python3 src/server.py --accounts ~/Videos
```

It polls `/api/license`, verifies the token locally, and caches it (on disk) so brief
cloud outages — even a restart during one — ride the offline-grace window. When the
subscription is inactive the node still serves its app shell and `/api/session` (so the
UI can show a "Manage billing" notice and you can still sign in) but **gates every other
route with HTTP 402**. Default self-host (no cloud config) is never gated.

> **Security note:** the per-tenant secret is symmetric (HS256). It's provisioned at
> runtime and never in source, so the open-source-ness of the node doesn't leak it. A
> future hardening pass could move license signing to asymmetric keys.

---

## Remote-from-anywhere — Phase 4b (P2P / WebRTC)

The headline Cloud upgrade: **watch your home library from anywhere, with the video
streaming peer-to-peer so our egress stays ≈ $0** (docs/ROADMAP.md — Cost model). The core needs **zero
changes** to be reachable remotely — the connector talks to it as a localhost client.

### The shape

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

### Components

| path | runtime | dep? | what it is |
|---|---|---|---|
| [`wire.py`](wire.py) | both Python peers | **stdlib** | the HTTP-over-datachannel framing codec (the protocol heart) |
| [`tests/test_wire.py`](tests/test_wire.py) | dev | **stdlib** | unit tests for the codec — `python3 -m unittest discover -s cloud/tests` |
| [`signaling/server.py`](signaling/server.py) | cloud | **stdlib** | the handshake broker (HTTP long-poll relay + entitlement gate) |
| [`connector/connector.py`](connector/connector.py) | home node | **aiortc** | the P2P endpoint; proxies data-channel ⇄ `http://127.0.0.1:<port>` |
| [`../src/web/js/remote.js`](../src/web/js/remote.js) | browser | native | signaling + `RTCPeerConnection` + `fetch` proxy + MSE video tunnel |

### The wire protocol (`wire.py`)

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

### Relay / TURN policy (the one place egress can leak)

- **Direct P2P (STUN):** ~80–90% of networks. Cloud egress = the KB of handshake. This is the
  default; the connector ships only a public STUN server.
- **TURN relay:** the hostile-NAT minority. Relayed video **is** real egress if the relay is
  ours, so it's **never the default**. TURN is added only when explicitly configured
  (`KADMU_TURN_URL`), and the plan is to treat it as a **capped, paid add-on / BYO-relay** —
  *never* "tunnel all video through us." The connector's `_ice_servers()` encodes this: STUN
  always, TURN only on opt-in. Phase 5 ([docs/ROADMAP.md](../docs/ROADMAP.md))
  specifies the capped coturn relay + per-plan byte caps that back this policy.

### Entitlement — the Phase 4a seam

Remote access is a **paid** Cloud perk, so the broker won't broker for free. Every `register`
carries a `token`; `verify_entitlement()` must pass before any SDP is relayed.

- **Today:** an HMAC token signed with `KADMU_SIGNAL_SECRET`, bound to a node id + expiry.
  Mint one with `python3 signaling/server.py --mint <node>`. With no secret set the broker runs
  in **dev mode** and accepts any token (local testing only).
- **Production (Phase 4a):** the control-plane mints this token after Stripe confirms an active
  subscription, encoding the user + plan; `verify_entitlement()` becomes the billing check.
  This is the single, clean integration point between 4a (billing) and 4b (access).

### Share-a-link (designed, not yet built)

A time-limited link that lets a friend watch **one** video with no account — also P2P, so still
≈ $0 egress. The mechanism reuses everything above: a share token is a scoped entitlement
(`{node, path, exp, one-video}`) the broker accepts for a guest, and `remote.js`'s fetch proxy
is constrained to that single path. Tracked as the next Phase 4b increment.

### Running it (local end-to-end)

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

### What's verified vs. what's stubbed

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

---

## Scale & cost control — Phase 5 (built)

Phase 5 keeps the cost model (`video never touches our servers`) holding as tenants are
added, and **caps the one place egress can leak** — the TURN relay. The cost model + cap rationale
live in [docs/ROADMAP.md](../docs/ROADMAP.md); this is what shipped.

| Piece | Where | What it does |
|---|---|---|
| **Metering + caps** (stdlib, 21 tests) | [`metering/`](metering/) | meters relay bytes per tenant × month, enforces a per-plan cap, and mints coturn ephemeral TURN credentials. **No credential ⇒ no relay**, so the cap is enforced *before* bytes flow. `python3 -m unittest discover -s cloud/metering/tests` |
| **Relay-credential gate** | `control-plane` | `GET /api/relay-credentials` (entitlement- + cap-gated) → short-TTL ICE servers, or STUN-only when over cap / inactive / unconfigured. Plus a Prometheus `GET /metrics`. |
| **The capped relay** | [`relay/`](relay/) | coturn (`use-auth-secret`, ≤720p/≈3 Mbps ceilings, private-range SSRF denial, Prometheus) + the metering collector. P2P stays default; relay is the rare fallback. |
| **Sticky signaling scale** | [`signaling/`](signaling/) | `X-Kadmu-Node` routing key (both peers send it → a sticky LB pins them to one broker, zero shared state), env-tunable TTLs, `/metrics`. |
| **CDN cache-busting** | core (`--cdn`) | immutable long-cache + `?v=APP_VERSION` on the app shell behind Cloudflare Free. **Off by default — self-host is byte-identical.** |
| **Deploy stack** | [`infra/`](infra/) | Caddy sticky LB, `docker-compose.scale.yml`, Cloudflare-Free CDN notes, Prometheus + Grafana (dashboards + the fleet relay-egress budget alert). |

**The credential scheme** (control-plane mints, coturn validates locally, no per-call lookup):
`username = "<expiry>:<tenant>"`, `password = base64(HMAC-SHA1(turn_secret, username))`.

**What you still set up yourself** (it's deploy, not code): a small VPS for
control-plane+signaling+ops and a separate one for coturn; DNS (`cloud.` `signal.` `turn.`
`app.kadmu.app`); a Cloudflare Free account for the CDN; real Stripe keys; one shared
`TURN_SECRET` (give it to both the relay and the control-plane); Litestream→R2 for DB backups.
Then `docker compose -f cloud/infra/docker-compose.scale.yml up -d` and the relay's compose on
its box. Fixed cost ≈ **$10–11/mo**; relay egress is hard-capped per plan. See each subdir's
`README.md` and `.env.example`.

---

## Why this respects the project's soul

- Core stays **stdlib-only / no-pip** — the dependency and all WebRTC weight is quarantined in
  `cloud/`, and the core doesn't import or even know about it.
- The cloud is a **handshake broker, not a video pipe** — egress ≈ $0, no DMCA-storage liability.
- Even the broker and the control-plane are **stdlib, zero-install** — the no-install ethos
  extends into the cloud layer wherever it can.
