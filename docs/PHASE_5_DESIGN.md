# Phase 5 — Scale & cost control (design + implementation)

> **Status: BUILT (code + config-as-code); live infra is a deploy step.** 4a and 4b have
> landed, and this design is now implemented under `cloud/`: the metering core
> (`cloud/metering/`, stdlib, 21 tests), the entitlement-bound relay-credential + `/metrics`
> routes in the control-plane, the capped coturn config + collector (`cloud/relay/`), the
> sticky-scale signaling extensions + connector/`remote.js` ICE wiring, the flag-gated CDN
> cache-busting in the core (`--cdn`), and the Caddy/Compose/Prometheus/Grafana stack
> (`cloud/infra/`). What remains is **operational, not code**: provision the VPS(es), DNS, a
> Cloudflare account, real Stripe + TURN secrets, then `docker compose up`. The deltas vs. this
> plan are noted inline as **[built]**. Nothing here touches the open-source core's promises;
> the one core change (the CDN flag, §5) is off by default so self-host is byte-identical.

> **The north star:** *keep our cloud cost ≈ $0.* Per [ROADMAP §5](ROADMAP.md#5-cost-model--local-files-keep-our-egress-near-zero-decided),
> the cloud never stores or pipes video — it's accounts + billing + the connection handshake.
> Phase 5's job is to **keep it that way as we add tenants**, and to **cap the one place egress
> can leak**: the TURN relay used by the ~10-20% of networks where P2P can't connect.

---

## 0. TL;DR — what Phase 5 ships

| # | Deliverable | Where | Cheap-to-run choice |
|---|---|---|---|
| 1 | **Relay-cost monitoring + per-plan caps** | `cloud/metering/` (new, stdlib) | the cost-control core — meter TURN bytes per tenant, enforce per-plan monthly caps, deny relay entitlement when over budget |
| 2 | **TURN relay (the fallback that 4b lacks)** | `cloud/relay/` (coturn config + ops) | coturn on one small VPS, **capped quality + per-plan byte caps**, P2P-first so it's rarely used |
| 3 | **Signaling horizontal scale** | `cloud/signaling/` (extend 4b) | **sticky-by-node-id** LB routing — no shared bus, no Redis bill; document a shared-store path for later |
| 4 | **Control-plane horizontal scale** | `cloud/control-plane/` (extend 4a) | stay **1 small instance + SQLite + Litestream→R2** until traffic demands it; document the stateless-API + Postgres cutover |
| 5 | **CDN for the static app shell** | `cloud/infra/cdn/` + tiny core tweak | Cloudflare **free tier**, build-free cache-busting via `?v=APP_VERSION` |
| 6 | **Observability + autoscale policy** | `cloud/infra/` | scrape existing `/metrics` (Phase 3) + signaling/relay; self-hosted Prometheus+Grafana on the ops box, no managed-APM bill |

Everything is **standard-library Python + config-as-code** (Docker Compose + Caddy), cloud-agnostic,
deployable on the cheapest VPS tier. The only non-stdlib pieces are operational binaries we *run*
but don't *write* (coturn; optionally Prometheus/Grafana).

---

## 1. Recommended stack (and why it's cheap)

The user constraint is explicit: **best for this app, and cheap to run.** Those align, because
the architecture already keeps video off our servers. The spend we must avoid is (a) managed
services with per-seat/per-GB pricing, and (b) relay egress. The recommended stack:

| Concern | Choice | ~Cost | Why |
|---|---|---|---|
| Compute | One small VPS for control-plane+signaling+ops (e.g. Hetzner CX22 / Fly shared-cpu-1x) | **~$5–6/mo** | stdlib services idle near-zero CPU/RAM; one box covers early scale |
| TURN relay | coturn on a separate small VPS, **off by default per tenant** | **~$5/mo + capped egress** | isolate the only egress source; size egress with hard caps (§2) |
| CDN | Cloudflare Free | **$0** | global edge cache for the app shell; unlimited cached static egress |
| Static/backup storage | Cloudflare R2 | **$0 egress** (free tier covers early) | **zero egress fees** — Litestream backups + any static origin |
| Database | SQLite + Litestream (→R2) now; managed Postgres only at real scale | **$0 → ~$0** | control-plane traffic is tiny (auth + license mint + webhooks) |
| Observability | Prometheus + Grafana on the ops box (or just structured logs) | **$0** | scrapes Phase 3 `/metrics`; avoid managed-APM per-host billing |
| TLS / LB | Caddy (auto-HTTPS) | **$0** | already the Phase 3 reverse-proxy choice |

**Total fixed:** ~**$10–11/mo** for the whole hosted control plane until thousands of tenants —
plus *variable, hard-capped* relay egress. Compare to the "we host video" model where every
stream is our egress. This is a 95%+ structural cut, preserved.

> **Why not Kubernetes/Terraform now?** Both add cost and operational weight for scale we don't
> have. The design keeps everything as **Docker Compose + Caddy** (portable, $0 tooling) and
> documents the K8s/Postgres cutover as a *later* step gated on real load. Premature IaC is the
> expensive mistake here.

---

## 2. Deliverable 1 + 2 — relay cost control (the heart of Phase 5)

This is the single most important part: the §5 cost model only holds if relay egress can never
"blow the budget." 4b is **P2P + signaling only**; it has no TURN fallback yet, so Phase 5 both
**adds the relay** and **wraps it in metering + caps** from day one (never ship the relay without
the caps — that's the whole point).

### 2.1 How relay fits the connection flow

```
guest browser ──register/SDP──▶ signaling broker ◀──register/SDP── connector (home box)
       │                                                                   │
       ├───────────────── try direct P2P (host/srflx candidates) ─────────┤   ~80–90%: $0
       │                                                                   │
       └──── if ICE fails ────▶  TURN relay (coturn)  ◀──── relay candidate ┘   ~10–20%: metered
                                  ▲ allocations gated by a short-lived,
                                  │ entitlement-bound TURN credential
                                  │ minted by the control-plane (4a)
```

P2P stays the default (ICE prefers host/server-reflexive candidates; relay is last resort). The
relay only carries a session when the network is hostile — and only if that tenant's plan and
remaining budget allow it.

### 2.2 Entitlement-bound TURN credentials (no open relay, ever)

coturn supports **REST-API ephemeral credentials** (the standard `use-auth-secret` /
time-limited-username scheme). We reuse it as the cap enforcement point:

- The browser asks the control-plane for ICE servers right before connecting:
  `GET /api/relay-credentials` (4a route, see contract §6.1).
- The control-plane checks: active subscription? plan allows relay? tenant under its monthly
  relay-byte cap? If yes, it returns a **short-TTL** (e.g. 120 s) coturn credential
  (`username = exp:tenant`, `password = HMAC(turn_secret, username)`). If no, it returns
  `{ relay: false, reason }` and the browser stays P2P-only (and shows "remote unavailable on
  this network / upgrade for relay").
- coturn validates the HMAC locally (shared `turn_secret`) — **no per-call lookup to us**, so
  the relay stays dumb and cheap, but credentials are unforgeable and expire fast.

This means: **no valid subscription / over budget ⇒ no credential ⇒ no relay allocation.** The
cap is enforced *before* bytes flow, not cleaned up after.

### 2.3 Metering — `cloud/metering/` (new, stdlib)

A tiny standard-library package; the discrete, fully-testable core of Phase 5.

```
cloud/metering/
  __init__.py
  meter.py        # ingest usage samples; roll up per tenant × billing-period
  caps.py         # plan → monthly relay-byte cap; over_budget(tenant) decision
  store.py        # SQLite (relay_usage table) + Litestream backup; or write to 4a's db
  collector.py    # pulls coturn usage and feeds meter.record()
  tests/
```

**Usage source.** coturn can emit per-allocation byte counts two ways: (a) the `--prometheus`
exporter (`turn_traffic_*` series), or (b) writing session stats to Redis. Cheapest is the
**Prometheus exporter** — the `collector.py` scrapes coturn's `/metrics`, diffs byte counters,
and attributes them to the tenant encoded in the TURN username (`exp:tenant`). No Redis bill.

**Data model** (one row per tenant per period, plus a rolling sample log for graphs):

```sql
CREATE TABLE relay_usage (
  tenant      TEXT NOT NULL,
  period      TEXT NOT NULL,            -- 'YYYY-MM' billing month
  bytes       INTEGER NOT NULL DEFAULT 0,
  sessions    INTEGER NOT NULL DEFAULT 0,
  updated     REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant, period)
);
```

**Cap decision** (`caps.over_budget`):

```python
def relay_allowed(tenant, plan):
    cap = PLAN_RELAY_CAP_BYTES.get(plan, 0)      # see §2.4
    if cap == 0:                                  # plan has no relay
        return False, "plan-no-relay"
    used = store.bytes_this_period(tenant)
    if used >= cap:
        return False, "cap-reached"
    return True, None
```

The control-plane calls `relay_allowed()` inside `GET /api/relay-credentials`. The metering
store can live in the **4a `cloud.db`** (add the table to its schema) so there's one DB to back
up — or stand alone; the contract (§6) is the same either way.

### 2.4 The cap math (concrete, tunable)

Relay carries *video* when used, so caps must be set against a real egress budget. Worked example
(numbers are starting points, tune from data):

- Relay quality is **capped** (e.g. ≤720p ≈ 2.5 Mbps) — never original/4K over relay. That's
  ~**1.1 GB/hour**.
- A generous personal cap: **100 GB / tenant / month** of relay ≈ ~90 hours of relayed viewing.
  Most tenants use **0** (P2P works); only the hostile-NAT minority touch relay at all.
- At, say, $0.01/GB egress (cheap VPS/Cloudflare-fronted), 100 GB = **$1/tenant/mo worst case**,
  and only for the minority who hit relay — blended cost per subscriber is cents.

```python
PLAN_RELAY_CAP_BYTES = {
    "monthly": 100 * 1024**3,    # 100 GB/mo
    "yearly":  100 * 1024**3,
    # future "relay-plus" add-on or BYO-relay → higher/unlimited
}
RELAY_MAX_HEIGHT = 720           # quality ceiling enforced by the connector when on relay
```

**Three escape valves** (ROADMAP §5, all supported by this design): cap quality/usage (above),
charge for more (a paid relay add-on = another `PLAN_RELAY_CAP_BYTES` entry), or **BYO relay**
(a tenant points at their own coturn — the credential endpoint returns their server). Never
default to tunnel-all-video.

### 2.5 Alerting

`metering` exposes its own `/metrics` (Prometheus): `kadmu_relay_bytes_total{plan}`,
`kadmu_relay_tenants_over_cap`, `kadmu_relay_sessions_active`. Grafana alert when **aggregate**
monthly relay egress crosses a global budget line (a backstop above the per-tenant caps), so a
pricing mistake or abuse is caught at the fleet level, not just per tenant.

---

## 3. Deliverable 3 — signaling horizontal scale

4b's broker (`cloud/signaling/server.py`) keeps **one in-memory mailbox (queue) per peer**. That
is correct and cheap for one instance, but it means a guest and its host **must be handled by the
same instance** — otherwise `register`/`poll` land on different boxes and never rendezvous.

**Cheapest correct scale: sticky routing by node id.** Both peers of a session share the stable
**host node id** (the guest registers *to* a node; the host registers *as* that node). Route on it:

```caddyfile
# cloud/infra/Caddyfile (signaling upstream)
signal.kadmu.app {
    reverse_proxy /signal/* {
        to sig1:8443 sig2:8443
        lb_policy           cookie            # or hash on the node id (see below)
        # Prefer hashing the node id so both peers pin to one instance with no shared state:
        # lb_policy header X-Kadmu-Node   (clients send it; broker already keys on `node`)
    }
}
```

Two viable pinning keys, both **zero-shared-state**:
1. **Hash the node id** (`X-Kadmu-Node` header or a path/query param both peers send) → consistent
   instance per node. Add the header in `remote.js` + connector; trivial 4b extension.
2. **Cookie affinity** for the guest + have the connector send the same routing key.

Only if/when one box can't hold the long-poll fan-out do we add a **shared bus** (Redis pub/sub,
or a tiny Postgres `LISTEN/NOTIFY`) so any instance can serve any peer. Documented, not built —
sticky routing carries us a long way because signaling is KB-once-per-session and the broker is
out of the loop after the data channel opens.

**Capacity:** each session is two long-poll clients for a few seconds during handshake, then idle.
A single stdlib `ThreadingHTTPServer` broker handles thousands of concurrent handshakes; the
binding constraint is file descriptors / thread count, not CPU. We'll load-document the ceiling
(see §5) and scale **out** (more cheap brokers behind sticky routing) before **up**.

### 3.1 Make the broker scale-ready (small 4b extensions Phase 5 owns)

- Add `X-Kadmu-Node` (or query key) so the LB can pin without parsing the body.
- Make `PEER_TTL`/`POLL_TIMEOUT` env-tunable (they're constants today).
- Expose `/metrics` (active peers, sessions/sec, relay-fallback count) alongside the existing
  `/healthz`, for the autoscale signal.

---

## 4. Deliverable 4 — control-plane horizontal scale

4a (`cloud/control-plane/`) is a stdlib `ThreadingHTTPServer` over **SQLite** (`cloud.db`:
accounts, sessions, subscriptions, tenants, donations, webhook_events). Its traffic is **tiny and
bursty**: login, Stripe Checkout/redirect, webhook delivery, periodic license-token mint/refresh.

**Cheapest correct path: don't scale it yet.** One small instance with SQLite easily serves
thousands of tenants for this workload. Make it *durable* and *ready*, not distributed:

1. **Durability now:** **Litestream** replicates `cloud.db` continuously to **R2** (zero egress
   fees). Survives box loss; restore in seconds. ~$0.
2. **Statelessness now:** the only server-side state is the DB and the session cookie (already a
   DB row, not memory) — so the API is *already* effectively stateless apart from SQLite. Keep it
   that way (no in-process caches that would diverge across instances).
3. **Idempotent webhooks:** the `webhook_events` table already dedupes by event id — required for
   safe retries and for >1 instance later. Confirm every state-changing webhook path is
   idempotent.

**The cutover (documented, gated on real load):** when one instance is genuinely insufficient,
swap SQLite → **managed Postgres** (cheapest tier; or Neon/Supabase free tier early) behind the
*same* `db.py` interface, then run **N identical control-plane instances** behind Caddy
round-robin. Because sessions and entitlements are already in the DB and webhooks are idempotent,
this is a config change, not a rewrite. Litestream/R2 backup applies to Postgres too (or use the
provider's PITR).

> **License tokens are the scale relief valve.** Nodes validate an **HS256 license** (4a
> `licensing`) *offline* with an expiry + grace period (ROADMAP §4a). So a node doesn't hit the
> control-plane per request — only to refresh its token periodically. This keeps control-plane
> QPS low and makes brief control-plane downtime invisible to playback. Phase 5 should pick the
> token TTL + grace to balance revocation speed vs. control-plane load (recommend **24 h TTL,
> 7-day grace**).

---

## 5. Deliverable 5 — CDN for the static app shell

The hosted app shell is the same static `src/web/` (HTML/CSS/`js/*.js`/fonts). In Cloud, serve it
from **Cloudflare Free** in front of the origin so the app-shell bytes (the only KB the cloud
serves on the hot path) are edge-cached globally at **$0**.

**Build-free cache-busting (preserve the no-build promise).** We can't fingerprint filenames
without a build step, so version by query string:

- The app shell references scripts/styles as `…/js/main.js?v=<APP_VERSION>` (and bump
  `APP_VERSION` on release, which already happens — [const.py](../src/kadmu/const.py)).
- Long-cache the static assets at the edge (`Cache-Control: public, max-age=31536000, immutable`)
  **except** `index.html` (short cache / revalidate), so a new release's `index.html` pulls the
  new `?v=` and busts the rest. One tiny core tweak: have the static handler emit long-cache
  headers for `/js/*`, `/fonts/*`, `/style.css` and version the references — gated behind a
  `KADMU_CLOUD`/CDN flag so the self-host default (no-cache for easy edits) is unchanged.
- Cloudflare cache rule: cache everything except `/`, `/index.html`, `/api/*`.

This keeps **all** app-shell egress on Cloudflare's free cache and our origin nearly silent. No
asset pipeline, no bundler — consistent with the project ethos.

> Coordination note: the cache-busting tweak is the *one* Phase 5 item that touches a shared file
> (the core static handler). It's small and flag-gated; do it as an isolated, reviewable change so
> it doesn't collide with frontend work on `kadmu-player-upgrades`.

---

## 6. Service contracts with 4a / 4b (so Phase 5 builds with minimal reconciliation)

These are the seams Phase 5 depends on. Defined here as the contract; when 4a/4b commit, confirm
names and adjust only the adapter, not the logic.

### 6.1 From 4a (control-plane)

| Contract | Shape | Notes |
|---|---|---|
| **Relay credential endpoint** | `GET /api/relay-credentials` (authed, tenant-bound) → `{relay:true, iceServers:[{urls,username,credential}], ttl}` or `{relay:false, reason}` | calls `metering.caps.relay_allowed(tenant, plan)`; mints short-TTL coturn HMAC creds |
| **Plan catalog gains relay caps** | add `relay_cap_bytes` (+ optional `relay_max_height`) to each entry in `const.PLANS` | drives `PLAN_RELAY_CAP_BYTES` |
| **Metering store** | either expose `cloud.db` for a `relay_usage` table, or accept `POST /internal/usage` from the collector | prefer shared DB → one Litestream backup |
| **Entitlement check** (already in 4a/4b seam) | `verify_entitlement(token) → {tenant, plan, active}` | already used by signaling `register`; relay reuses the same identity |

### 6.2 From 4b (remote)

| Contract | Shape | Notes |
|---|---|---|
| **Routing key for sticky LB** | both peers send `X-Kadmu-Node: <node id>` (or `?node=`) on signaling calls | enables zero-state horizontal scale (§3) |
| **ICE config injection** | `remote.js` fetches `iceServers` from `/api/relay-credentials` before `RTCPeerConnection` | connector already accepts `RTCConfiguration` |
| **Relay quality ceiling** | connector clamps to `RELAY_MAX_HEIGHT` when the selected ICE candidate pair is `relay` | enforces the cap quality (§2.4) |
| **Signaling `/metrics`** | extend the broker (it has `/healthz`) with peer/session/relay counters | autoscale + dashboards |

---

## 7. Capacity planning (what informs what)

Per ROADMAP §5 the cloud is *thin*, so node limits inform **the node**, not the cloud:

- **Node:** a single `ThreadingHTTPServer` core node handles ~**100–200 concurrent connections**
  before thread/FD pressure. Phase 3 already added the per-IP rate limiter, `MAX_STREAMS`, and
  `/metrics` — so the node is the right place to *surface* and *cap* concurrency. Phase 5 adds a
  short capacity note to docs (and optionally a soft connection cap on `KadmuServer` surfaced via
  `/metrics`), so a self-hoster on a Pi knows the ceiling. This does **not** require cloud scale.
- **Signaling:** scale **out** with cheap brokers behind sticky routing (§3) — handshakes are
  brief; thousands concurrent per box.
- **Control-plane:** one box for a long time (§4); QPS kept low by offline license tokens.
- **Relay:** the only capacity that costs real money → governed by per-plan caps + a fleet
  budget alert (§2), and sized to the hostile-NAT minority, not the whole user base.

---

## 8. Observability & autoscale

Cheap, self-hosted, built on what already exists:

- **Scrape targets:** core node `/metrics` (Phase 3), signaling `/metrics` (§3.1), control-plane
  `/metrics` (add), relay/coturn `/metrics`, metering `/metrics` (§2.5).
- **Stack:** Prometheus + Grafana on the ops box (or Grafana Cloud free tier). No per-host APM
  billing.
- **Key dashboards/alerts:** aggregate relay egress vs. budget (the money alert); signaling
  sessions/sec + relay-fallback ratio (if it climbs above ~20%, investigate STUN/NAT before
  paying for relay); control-plane error rate + webhook backlog; tenant license-refresh failures.
- **Autoscale policy (documented):** signaling scales out on sustained sessions/sec or FD
  headroom; control-plane manual until the Postgres cutover; relay vertical (bigger NIC) before
  horizontal, since each is independently capped. With Compose this is a documented runbook +
  `docker compose up --scale sigN`; the K8s HPA version is the later cutover.

---

## 9. Implementation plan (when 4a/4b land)

Ordered so the **cost guardrail ships before the cost source**, and each step is independently
verifiable:

1. **`cloud/metering/`** (stdlib + tests) — `meter`, `caps`, `store`. *Verify:* unit tests for
   roll-up math and `relay_allowed` boundary cases; no infra needed. **Do this first.**
2. **`/api/relay-credentials` in 4a** — wire `relay_allowed` + coturn HMAC cred minting; add
   `relay_cap_bytes` to `PLANS`. *Verify:* mock-mode request returns creds under cap, refusal at
   cap / inactive sub.
3. **`cloud/relay/`** — coturn config (use-auth-secret, quotas, Prometheus exporter) + Compose
   service; `collector.py` attributing bytes to tenants. *Verify:* a forced-relay loopback
   session increments `relay_usage`; over-cap tenant is refused a credential.
4. **4b sticky-scale extensions** — `X-Kadmu-Node` routing key, env-tunable TTLs, broker
   `/metrics`; Caddy sticky config. *Verify:* two broker instances + LB; a guest/host pair
   rendezvous; metrics scrape.
5. **CDN cache-busting** — flag-gated long-cache headers + `?v=APP_VERSION` references; Cloudflare
   cache rules doc. *Verify:* asset responses carry immutable cache headers under the flag; core
   default unchanged.
6. **Control-plane durability + scale-readiness** — Litestream→R2; confirm webhook idempotency;
   document the Postgres + N-instance cutover. *Verify:* kill/restore the box from R2; replay a
   duplicate webhook is a no-op.
7. **Observability** — Prometheus scrape config + Grafana dashboards/alerts; autoscale runbook.

Each step lands under `cloud/` in distinct subpaths (`metering/`, `relay/`, `infra/`), so it
composes with 4a's `control-plane/` and 4b's `signaling/`,`connector/` with minimal conflict.

---

## 10. Open decisions (settle before building)

1. **Relay caps & pricing:** confirm `100 GB/mo` per-plan cap, `720p` relay ceiling, and whether
   to offer a paid "relay-plus" add-on vs. BYO-relay only. (Drives §2.4.)
2. **Metering store location:** shared 4a `cloud.db` (one backup, tighter coupling) **vs.**
   standalone `cloud/metering` DB (looser coupling, two backups). Recommend **shared**.
3. **License token TTL/grace:** recommend **24 h / 7-day grace** — confirm against how fast you
   want cancellations to cut off access.
4. **TURN provider:** self-hosted **coturn** (recommended, cheapest, full control) vs. a managed
   TURN (e.g. metered/Twilio — simpler, per-GB priced, less control). Recommend coturn.
5. **CDN provider:** Cloudflare Free (recommended) vs. Bunny/Fastly. Affects only `cloud/infra/cdn/`.
6. **When to trigger the Postgres + multi-instance control-plane cutover** — pick a concrete
   signal (e.g. p95 control-plane latency, or tenant count) so it's not vibes.

---

## Appendix — proposed `cloud/` layout after Phase 5

```
cloud/
├─ control-plane/      # 4a — billing, accounts, entitlements, licensing  (+ relay-credentials, relay caps)
├─ signaling/          # 4b — the broker  (+ sticky routing key, /metrics, env-tunable TTLs)
├─ connector/          # 4b — home-node aiortc sidecar  (+ relay quality clamp)
├─ wire.py             # 4b — HTTP-over-datachannel framing (stdlib)
├─ metering/           # 5  — relay usage metering + per-plan caps (stdlib + tests)   ◀ NEW
├─ relay/              # 5  — coturn config, ephemeral-cred scheme, usage collector    ◀ NEW
├─ infra/              # 5  — Caddy LB, Compose stacks, CDN config, Prometheus/Grafana ◀ NEW
│  ├─ Caddyfile
│  ├─ docker-compose.scale.yml
│  ├─ cdn/
│  └─ observability/
└─ README.md           # 5  — extend with the scale & cost-control runbook
```

All standard-library Python + config-as-code; the only runtime binaries we operate (not author)
are coturn and (optionally) Prometheus/Grafana. Fixed cost ~$10–11/mo; relay egress hard-capped.
