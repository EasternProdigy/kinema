# Kadmu Cloud — observability & autoscale (`cloud/infra/observability/`)

Self-hosted Prometheus + Grafana on the ops box (Phase 5, [PHASE_5_DESIGN.md §8](../../../docs/PHASE_5_DESIGN.md)).
No managed-APM per-host bill — we scrape the `/metrics` every Kadmu service already
exposes (Phase 3 added them to the core node) and alert on the one thing that costs real
money: **relay egress**.

```
observability/
├─ prometheus.yml          scrape config (15s) for control-plane, signaling, coturn, core node
├─ alerts.yml              alerting rules (the money alert + operational backstops)
├─ grafana/
│  ├─ provisioning/
│  │  ├─ datasources/datasource.yml    Prometheus @ http://prometheus:9090
│  │  └─ dashboards/dashboards.yml     loads dashboards from the path below
│  └─ dashboards/kadmu-cloud.json      the cost/scale dashboard
└─ README.md              ← you are here
```

## Run it

The whole stack comes up from the scale Compose file (Prometheus + Grafana are services
in it):

```bash
cp cloud/infra/.env.example cloud/infra/.env     # then fill in secrets
docker compose -f cloud/infra/docker-compose.scale.yml --env-file cloud/infra/.env up -d
```

- **Grafana** → `http://localhost:3000` (bound to loopback; front with Caddy or an SSH
  tunnel). Login `admin` / `GRAFANA_ADMIN_PASSWORD` from `.env`. The Prometheus
  datasource and the **Kadmu Cloud — Scale & Cost Control** dashboard are
  auto-provisioned on boot.
- **Prometheus** is internal-only (no published port). Reach it through Grafana's
  Explore, or `docker compose exec prometheus ...`, or an SSH tunnel to `:9090`.

> The **coturn relay runs on its own VPS** (`cloud/relay/`), so its target is a routable
> host (`RELAY_HOST` in `.env`, exporter on `:9641`). Prometheus has no env interpolation
> — edit the `coturn` job target in `prometheus.yml` to match your relay host, or template
> it at deploy time.

## The dashboard

`kadmu-cloud.json` (schemaVersion 39) visualizes, top to bottom:

- **Relay egress vs. budget** (the money panel) — `sum(increase(kadmu_relay_bytes_total[30d]))`
  against the 2 TiB fleet budget line, plus a stat showing % of budget used.
- **Relay sessions active**, **tenants over cap**, **relay fallback ratio**, **relay
  tenants total**, and **relay egress by plan**.
- **Signaling** — peers/hosts and registrations/messages rate across brokers.
- **Control-plane** — request & 5xx rate; accounts/subscriptions/tenants gauges.
- **coturn** — bytes/s, packets/s, total allocations.

## What each alert means (`alerts.yml`)

| Alert | Fires when | What to do |
|---|---|---|
| **RelayEgressOverBudget** (critical — *the money alert*) | `sum(increase(kadmu_relay_bytes_total[30d]))` crosses the **2 TiB/mo fleet budget** (a backstop ABOVE per-tenant caps) | Find the leak: `kadmu_relay_tenants_over_cap`, per-plan `kadmu_relay_bytes_total{plan}`, fallback ratio. A pricing/abuse signal — don't just raise the budget. |
| **RelayEgressApproachingBudget** (warning) | egress > 80% of budget | Early warning; review usage + NAT before it hits the hard line. |
| **RelayFallbackRatioHigh** (warning) | relay sessions / active hosts > **20%** | P2P/STUN is failing more than expected. Investigate STUN reachability + the connector ICE config **before** scaling/paying for relay. |
| **TenantsOverRelayCap** (info) | `kadmu_relay_tenants_over_cap` > 5 | Confirm plan caps are right; consider a paid relay-plus add-on. |
| **ControlPlaneErrors** (critical) | control-plane 5xx > 0.5/s | Check Stripe webhooks, the SQLite DB, license mint. Blocks signups/billing/license refresh. |
| **WebhookBacklog** (warning) | 5xx on `/api/webhook/stripe` over 15m | Subscription state drifting. Check signature verification, DB, Stripe retry queue. |
| **ControlPlaneDown** / **SignalingBrokerDown** / **CoturnRelayDown** | `up == 0` for 5m | Service unscrapeable. Caddy drops a dead broker from the sticky LB automatically; restart/scale. |
| **TenantLicenseRefreshFailures** (warning) | 5xx on `/api/license` > 0.1/s | Nodes ride offline-grace for now; sustained failures gate playback (402) once grace lapses. Check signing keys + entitlements DB. |
| **SubscriptionTenantMismatch** (info) | active subs > tenants | Metering/labeling bug — reconcile control-plane accounting. |

> Alert **thresholds are baked into PromQL** (no env interpolation). When you tune the
> fleet budget, change it in **both** `alerts.yml` (the `2199023255552` constants) **and**
> `.env`'s `RELAY_FLEET_BUDGET_BYTES`. There is no Alertmanager wired here yet — add one as
> a Compose service and a `alerting:` block in `prometheus.yml` when you want paging.

---

## Autoscale runbook

Per [PHASE_5_DESIGN.md §7–§8](../../../docs/PHASE_5_DESIGN.md) each tier scales differently.
The cheap correct moves, in order of when you'll need them:

### Signaling — scale **OUT** (cheap, do this first)

Handshakes are brief (KB once per session; the broker is out of the loop after the data
channel opens), so a single stdlib broker holds thousands of concurrent handshakes — the
binding constraint is file descriptors / thread count, not CPU. Watch `kadmu_signal_peers`
per instance and FD headroom. When one box is tight, **add brokers behind the sticky LB**:

**Option A — add a named instance (preferred for a stable upstream list):**
1. Copy the `sig2` service block in `docker-compose.scale.yml` to `sig3` (same env).
2. Add `sig3:8443` to the `reverse_proxy` upstreams in `Caddyfile` (`signal.kadmu.app`).
3. Add `sig3:8443` to the `signaling` job in `prometheus.yml`.
4. `docker compose -f docker-compose.scale.yml up -d` (Caddy reloads the upstream).

**Option B — scale the same service (fastest):**
```bash
docker compose -f cloud/infra/docker-compose.scale.yml up -d --scale sig1=3
```

Either way the sticky key holds: Caddy pins each session's **guest + host** to one broker
by hashing `X-Kadmu-Node` (`lb_policy header X-Kadmu-Node`), so **no shared state** is
needed — adding a broker only reshuffles a fraction of node→instance mappings (consistent
hash). A shared bus (Redis pub/sub / Postgres `LISTEN/NOTIFY`) is the *later* path only if
one box genuinely can't hold the long-poll fan-out — documented in §3, not built.

### Relay (coturn) — scale **VERTICALLY first**

Relay is the only tier that costs real egress, and each relay is **independently capped**
(per-tenant caps + the fleet budget alert). So grow the **existing** box (bigger NIC /
egress allowance) before adding a second relay — vertical keeps the cap accounting simple
and avoids spreading byte attribution across instances. Only shard horizontally (a second
coturn, region-split) when one VPS's NIC is the bottleneck *and* the budget alert says the
spend is justified. It lives on its own VPS (`cloud/relay/docker-compose.yml`), separate
from this stack, precisely so its egress stays isolated and visible.

### Control-plane — stay **ONE box** until a concrete cutover trigger

Its traffic is tiny and bursty (login, Stripe Checkout/webhooks, periodic license mint),
and **offline license tokens** (24 h TTL / 7-day grace) keep nodes off the control-plane
per request — so brief downtime is invisible to playback. Keep it a single SQLite instance
made durable by **Litestream → R2**, not distributed.

**Cutover trigger (pick a concrete signal, not vibes — §4/§10):** move to **managed
Postgres + N identical instances behind Caddy round-robin** when *either*:
- **p95 control-plane request latency** (derived from `kadmu_requests_total` + a latency
  histogram once added) stays above **~250 ms** for a sustained period, **or**
- **`kadmu_cloud_tenants_total`** crosses a chosen scale line (e.g. **~5,000 tenants**),
  whichever comes first.

Because sessions + entitlements already live in the DB and webhooks are idempotent
(`webhook_events` dedupe), the cutover is a config change (`db.py` → Postgres) + running N
instances, not a rewrite. The Kubernetes/Terraform version is the *later* step gated on
real load — not now.
