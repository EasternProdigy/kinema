# Kadmu Cloud — Launch Checklist (what's left to go live)

> **Status:** all roadmap phases are **code-complete on `main`**. Self-host (Phases 1–3) is
> shipped and production-ready. The hosted layer (Phases 4a/4b/5, under `cloud/`) is built and
> runs end-to-end in **mock mode**; what remains is **operational** — provision infrastructure,
> wire real secrets, and do the real-network testing that can't be unit-tested. This document is
> the punch list to take it from "works on my laptop in mock mode" to "a stranger can pay and
> watch their own library from anywhere."
>
> Companion docs: [ROADMAP.md](ROADMAP.md) (vision & future plans), each `cloud/*/README.md`
> (per-service runbooks), [ROADMAP.md](ROADMAP.md) (the big picture). Self-host deployment is a
> different, already-done path — see [../deploy/](../deploy/) and [SECURITY.md](SECURITY.md).

Legend: ☐ = to do · ⚠ = decision/risk · 💻 = still requires code · 🌐 = external account/spend

---

## 0. Decisions to lock before spending money

These drive everything downstream; settle them first (see [ROADMAP.md](ROADMAP.md) — Open decisions).

- ☐ ⚠ **Licensing** — MIT (today) vs AGPL core vs open-core (AGPL/MIT core + proprietary `cloud/`).
  This affects whether the `cloud/` dir stays in this repo or moves to a private one. (see ROADMAP.md — Open decisions)
- ☐ ⚠ **Pricing shape** — confirm the $5/mo, $50/yr placeholders in
  `cloud/control-plane/cloud/const.py` (`PLANS`), and the **100 GB/mo relay cap + 720p ceiling**
  (`PLAN_RELAY_CAPS`, `relay_max_height`). Decide on a paid "relay-plus" add-on vs BYO-relay only.
- ☐ ⚠ **License token TTL / grace** — currently 24 h TTL, 7-day offline grace
  (`KADMU_CLOUD_LICENSE_TTL` / `KADMU_CLOUD_OFFLINE_GRACE`). Confirm against how fast a
  cancellation should cut off access.
- ☐ ⚠ **Trial vs none**, refund window, and cancellation behavior for the pay-first gate.
- ☐ ⚠ **TURN provider** — self-hosted coturn (what we built, cheapest) vs a managed TURN
  (Twilio/metered — simpler, per-GB). Recommend coturn.
- ☐ ⚠ **Metadata enrichment (TMDB)** — still deliberately deferred (see ROADMAP.md). Decide if
  the hosted edition ships the first opt-in outbound call as a managed convenience.
- ☐ 🌐 **Trademark + domain** — register `kadmu.app` (or chosen domain); consider a "Kadmu"
  wordmark trademark so forks can't trade on the brand (see ROADMAP.md — Open decisions).

---

## 1. Code follow-ups still required (the non-deploy gaps)

Most of the system is done; these are the genuine remaining **code** items.

- ☐ 💻 **Phase 4b P2P real-network testing.** The aiortc transport (ICE/DTLS/SCTP, backpressure,
  ABORT) in `cloud/connector/connector.py` and the `RTCPeerConnection` handshake in
  `src/web/js/remote.js` are structured and reviewed but **never run against two real networked
  peers + a browser**. This needs a manual integration pass (two machines on different networks,
  or a hostile-NAT simulator). The `cloud/wire.py` framing it depends on *is* unit-tested.
- ☐ 💻 **MSE fragmented-MP4 for remote video.** MSE needs fMP4; the node's `build_remux` emits
  plain MP4, so remote *video* (not the JSON API) won't play past the progressive-blob fallback.
  Add an fMP4 profile (`-movflags +frag_keyframe+empty_moov+default_base_moof`) to the remux path
  for the remote case (gate it so self-host streaming is unchanged). This is the main 4b follow-up.
- ☐ 💻 **Share-a-link** (designed, not built — `cloud/README.md`). A scoped, time-limited
  entitlement the signaling broker accepts for an account-less guest, with `remote.js`'s fetch
  proxy constrained to one path.
- ☐ 💻 **Complete `cloud/control-plane/.env.example`.** It currently lists only host/port/base-URL.
  Add the Stripe + TURN + mode vars that `const.py` actually reads (see §4 below) so going live is
  copy-paste, not archaeology.
- ☐ 💻 *(optional hardening)* **Asymmetric license keys.** License + tenant proof use a symmetric
  HS256/HMAC secret today. Fine for launch; a later pass could move license signing to asymmetric
  keys so a compromised node can't forge licenses for others.
- ☐ 💻 *(optional)* **Soft connection cap on the core node** surfaced via `/metrics`
  ([ROADMAP.md](ROADMAP.md)) so a self-hoster sees the ~100–200 concurrent ceiling.

---

## 2. Accounts & infrastructure to provision

- ☐ 🌐 **Domain + DNS** at a registrar (Cloudflare DNS is convenient since we use their CDN).
- ☐ 🌐 **Stripe account** (live mode) — for subscriptions + donations.
- ☐ 🌐 **Cloudflare** account (Free tier) — CDN for the app shell + DNS.
- ☐ 🌐 **Cloudflare R2** bucket — for Litestream DB backups (zero egress fees).
- ☐ 🌐 **VPS #1 — "ops box"** (e.g. Hetzner CX22 / Fly shared-cpu-1x, ~$5–6/mo): runs
  control-plane + 2× signaling + Caddy + Prometheus + Grafana via
  `cloud/infra/docker-compose.scale.yml`.
- ☐ 🌐 **VPS #2 — "relay box"** (separate small VPS, ~$5/mo + capped egress): runs coturn +
  the metering collector via `cloud/relay/docker-compose.yml`. Kept separate so the only
  egress source is isolated. **Open the firewall**: 3478/udp+tcp, 5349/tcp, and the relay UDP
  range `49160–49200` (or whatever you set), plus 9641 only on the private network.
- ☐ Install Docker + Docker Compose on both boxes.

---

## 3. DNS records

| Record | Points at | Purpose |
|---|---|---|
| ☐ `cloud.kadmu.app` | ops box (via Caddy) | control-plane: signup, billing, dashboard, `/api/license`, `/api/relay-credentials` |
| ☐ `signal.kadmu.app` | ops box (via Caddy) | signaling broker (sticky LB across sig1/sig2) |
| ☐ `app.kadmu.app` | Cloudflare → app origin | the static app shell (CDN-fronted) |
| ☐ `turn.kadmu.app` | **relay box public IP** (A record) | coturn TURN/STUN |
| ☐ `grafana.kadmu.app` *(optional)* | ops box | Grafana UI |

Set Cloudflare to **proxied (orange cloud)** for `app.` (so the CDN caches the shell); leave
`turn.` **DNS-only (grey cloud)** — TURN must reach the box directly, not through Cloudflare.

---

## 4. Secrets & per-service `.env`

Generate shared secrets once: `openssl rand -hex 32` for `TURN_SECRET`, again for
`KADMU_SIGNAL_SECRET`. **The same `TURN_SECRET` must be set on both the relay box and the
control-plane** (the control-plane mints credentials the relay validates).

### `cloud/control-plane/.env`  (copy from `.env.example`, then add)
- ☐ `KADMU_CLOUD_MODE=live`
- ☐ `KADMU_CLOUD_BASE_URL=https://cloud.kadmu.app`
- ☐ `STRIPE_SECRET_KEY=sk_live_…`, `STRIPE_PUBLISHABLE_KEY=pk_live_…`
- ☐ `STRIPE_WEBHOOK_SECRET=whsec_…` (from the webhook you create in §6)
- ☐ `STRIPE_PRICE_MONTHLY=price_…`, `STRIPE_PRICE_YEARLY=price_…`
- ☐ `KADMU_TURN_SECRET=<the shared secret>`
- ☐ `KADMU_TURN_URLS=turn:turn.kadmu.app:3478,turns:turn.kadmu.app:5349`
- ☐ *(optional)* `KADMU_RELAY_CRED_TTL=120`, `KADMU_RELAY_CAP_MONTHLY_GIB=100`,
  `KADMU_CLOUD_LICENSE_TTL`, `KADMU_CLOUD_OFFLINE_GRACE`

### `cloud/relay/.env`
- ☐ `TURN_SECRET=<the same shared secret>`
- ☐ `TURN_REALM=turn.kadmu.app`
- ☐ `TURN_EXTERNAL_IP=<relay box public IP>`
- ☐ `KADMU_METER_DB=/data/cloud.db` — **bind-mount the control-plane's real `cloud.db`** here
  (see the compose comment) so caps and metering share one store. If the relay box can't share the
  control-plane's disk, run the collector on the ops box against `https://turn…:9641` instead.

### `cloud/infra/.env`
- ☐ `KADMU_SIGNAL_SECRET=<signal secret>`
- ☐ `KADMU_SIGNAL_ORIGIN=https://app.kadmu.app`
- ☐ `KADMU_CLOUD_BASE_URL=https://cloud.kadmu.app`
- ☐ `KADMU_TURN_SECRET=<shared TURN secret>` (if the ops box also runs the collector)
- ☐ `CORE_NODE_HOST=…` (a representative core node `/metrics` target, if you scrape one)
- ☐ `RELAY_HOST=turn.kadmu.app:9641`, `GRAFANA_ADMIN_PASSWORD=…`,
  `RELAY_FLEET_BUDGET_BYTES=…` (the global budget the egress alert fires on)

> Keep every `.env` out of git (already covered by `.gitignore`). Never put `TURN_SECRET` or
> Stripe keys in a committed file.

---

## 5. Stand up the services (ordered)

1. ☐ **Control-plane first** (it owns the DB and mints everything). On the ops box, with its
   `.env` set: it comes up as part of `docker-compose.scale.yml`. Confirm `https://cloud.kadmu.app/healthz`
   shows `"mock": false`.
2. ☐ **Signaling + Caddy** — `docker compose -f cloud/infra/docker-compose.scale.yml up -d`.
   Caddy auto-issues HTTPS for `cloud.` / `signal.` / `grafana.`. Confirm
   `https://signal.kadmu.app/healthz` and that `/metrics` is **not** publicly reachable.
3. ☐ **Relay** — on the relay box: `docker compose -f cloud/relay/docker-compose.yml up -d`.
   Confirm coturn is listening and the collector is scraping (`docker logs`).
4. ☐ **App shell behind the CDN** — serve `src/web` from a core node started with **`--cdn`**
   (or `KADMU_CDN=1`) so it emits immutable cache headers + `?v=APP_VERSION`; put Cloudflare in
   front of `app.kadmu.app` with the cache rule from `cloud/infra/cdn/README.md` (cache everything
   except `/`, `/index.html`, `/api/*`).
5. ☐ **Observability** — Prometheus + Grafana are in the infra compose; import the dashboard at
   `cloud/infra/observability/grafana/dashboards/kadmu-cloud.json` (auto-provisioned) and set the
   Grafana admin password.

---

## 6. Stripe wiring

- ☐ Create two **Products/Prices** (monthly, yearly); copy the price ids into the control-plane `.env`.
- ☐ Create a **webhook endpoint** → `https://cloud.kadmu.app/api/webhook/stripe`, subscribe to
  `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`,
  `invoice.payment_failed`; copy its signing secret into `STRIPE_WEBHOOK_SECRET`.
- ☐ Enable the **customer billing portal** in Stripe (powers the dashboard "Manage billing").
- ☐ Do **one real test purchase** (Stripe test card in a test-mode dry run, then a real card):
  signup → checkout → webhook → subscription active → dashboard shows the tenant id + secret.

---

## 7. Backups & durability

- ☐ Install **Litestream** on the ops box, replicating `cloud/control-plane/data/cloud.db` → R2.
- ☐ Test a **restore**: kill the box, restore `cloud.db` from R2, confirm sessions/subscriptions
  survive (they're DB rows; webhooks are idempotent, so replays are safe).

---

## 8. Pre-launch verification (before opening signups)

- ☐ **License path:** a provisioned tenant's node (`--cloud https://cloud.kadmu.app --tenant ten_… `,
  `KADMU_CLOUD_SECRET=…`) fetches a license, and the node gates with **402** when the subscription
  is canceled, while still serving the app shell + `/api/session`.
- ☐ **Relay-credential path:** `GET /api/relay-credentials` returns real `iceServers` (a `turn:` entry
  with username/credential) for an active tenant; returns `{relay:false, reason:"cap-reached"}`
  once that tenant's `relay_usage` crosses the cap; returns STUN-only for an inactive sub.
- ☐ **A real remote session** (the 4b code item §1): from a phone on cellular, load
  `app.kadmu.app`, sign in, and play a file off a home node — first over P2P, then force-relay
  (block STUN) and confirm it relays, stays ≤720p, and increments `kadmu_relay_bytes_total`.
- ☐ **Metrics + the money alert:** Prometheus is scraping control-plane/signaling/coturn; the
  Grafana **relay-egress-vs-budget** alert is armed and routes somewhere you'll see it.
- ☐ **Security spot-check:** `/metrics` endpoints aren't world-readable; coturn refuses to relay to
  private ranges; the app-shell CSP still passes; no secret is reachable from the client.

---

## 9. Launch & post-launch

- ☐ 🌐 Publish **ToS + Privacy Policy** for the account service (no content hosting ⇒ no
  DMCA-storage duty, but you still need these — see ROADMAP.md, Cost model).
- ☐ Wire **donations** for the OSS side (the control-plane `/donate` flow → a real Stripe one-time
  price) and add the donate button to the project README/site.
- ☐ Open signups. Watch: relay-fallback ratio (if >~20%, investigate STUN/NAT before paying for
  relay), webhook error rate, license-refresh failures, aggregate relay egress vs budget.

---

## 10. Scale triggers (don't pre-build)

Stay on **one** control-plane box + SQLite + Litestream until a concrete signal
([ROADMAP.md](ROADMAP.md) — Scale & cost-control): e.g. control-plane p95 latency degrades, or ~5,000 tenants. Then cut over
to managed Postgres behind the same `db.py` interface + N round-robin instances (sessions are
already in-DB and webhooks idempotent, so it's config, not a rewrite). Scale **signaling** out
first (more cheap brokers behind the sticky LB); scale **relay** vertically (bigger NIC) before
horizontally. K8s/Terraform only if/when Compose genuinely can't keep up.

---

## Cost at a glance

| Item | ~Cost |
|---|---|
| Ops box (control-plane + signaling + Prometheus/Grafana) | ~$5–6/mo |
| Relay box (coturn) | ~$5/mo + **hard-capped** relay egress |
| Cloudflare CDN (Free) + R2 backups (free tier early) | ~$0 |
| Stripe | per-transaction fees only |
| **Fixed total** | **~$10–11/mo** until thousands of tenants |

The video never flows through our servers (P2P), and relay egress is capped per plan + alerted at
the fleet level — so cost scales with *tenants* (cheap), not with *watch-hours* (expensive). That's
the whole bet.

---

## TL;DR — minimum path to the first paying user

1. Settle pricing + licensing (§0). 2. Buy a domain + 2 small VPSes; create Stripe + Cloudflare + R2 (§2).
3. Point DNS (§3). 4. Fill the three `.env` files with real secrets (§4). 5. `docker compose up` the
ops stack, then the relay stack (§5). 6. Wire the Stripe webhook + do a test purchase (§6).
7. Run the §8 verification (incl. one real remote playback — the last untested code path).
8. Publish ToS/Privacy, open signups (§9).
