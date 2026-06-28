# Kadmu Cloud — infra (`cloud/infra/`)

Deployment + operations for the hosted layer — **Phase 5** (scale & cost control),
config-as-code only. The whole hosted control plane runs on **Docker Compose + Caddy**,
self-hosted Prometheus/Grafana, and **Cloudflare Free** — explicitly **not**
Kubernetes/Terraform yet (premature for this scale; see [PHASE_5_DESIGN.md §1](../../docs/PHASE_5_DESIGN.md)).

> No third-party runtime deps in our own code: the control-plane and signaling broker are
> stdlib-only. The only binaries we *run* (not author) are Caddy, coturn, Prometheus, and
> Grafana — all $0 tooling.

## What's here

| file / dir | what it is |
|---|---|
| [`Caddyfile`](Caddyfile) | **production** reverse proxy + sticky LB: `cloud.` (control-plane), `signal.` (signaling, sticky by node id across `sig1`/`sig2`…), `app.` (static shell origin behind the CDN). Auto-HTTPS. |
| [`Caddyfile.example`](Caddyfile.example) | the minimal single-vhost Phase-4a starting point (kept for reference; `Caddyfile` supersedes it). |
| [`docker-compose.scale.yml`](docker-compose.scale.yml) | the multi-service stack: `caddy`, `control-plane`, `sig1` + `sig2`, `prometheus`, `grafana`. |
| [`.env.example`](.env.example) | env/secrets for the stack (copy to `.env`; nothing hard-coded). |
| [`observability/`](observability/) | Prometheus scrape config + alert rules + Grafana provisioning/dashboard, and the **autoscale runbook**. |
| [`cdn/`](cdn/) | Cloudflare Free setup + the build-free `?v=APP_VERSION` cache-busting. |

The TURN relay is **not** in this stack — it runs from
[`cloud/relay/docker-compose.yml`](../relay/) on its **own VPS** so its (capped, metered)
egress stays isolated. Prometheus here scrapes it across the network.

## Run the stack

```bash
cp cloud/infra/.env.example cloud/infra/.env       # fill in secrets (signal secret, Stripe, Grafana pw…)
docker compose -f cloud/infra/docker-compose.scale.yml --env-file cloud/infra/.env up -d
```

Point the three DNS records (`cloud.`, `signal.`, `app.kadmu.app`) at the box first; Caddy
provisions Let's Encrypt certs on boot. Set the control-plane's `KADMU_CLOUD_BASE_URL` to
the public `https://cloud.kadmu.app` so Stripe redirects + dashboard links are correct.

## The cost model (~$10–11/mo fixed)

The architecture keeps **video off our servers** (P2P, ROADMAP §5), so the only spend is a
thin control plane plus a hard-capped relay:

| Concern | Choice | ~Cost |
|---|---|---|
| Control-plane + signaling + ops (this stack) | one small VPS (e.g. Hetzner CX22 / Fly shared-cpu-1x) | **~$5–6/mo** |
| TURN relay (coturn, separate VPS, off-by-default per tenant, byte-capped) | one small VPS | **~$5/mo + capped egress** |
| CDN for the app shell | **Cloudflare Free** | **$0** |
| Backups / static origin | **Cloudflare R2** (zero egress) — Litestream replicates `cloud.db` | **~$0** |
| Observability | self-hosted Prometheus + Grafana on the ops box | **$0** |
| TLS / LB | Caddy auto-HTTPS | **$0** |

**Total fixed ≈ $10–11/mo** until thousands of tenants, plus *variable, hard-capped* relay
egress (per-plan caps + the fleet budget alert). This preserves the 95%+ structural cut vs.
a host-the-video model.

## Stripe webhook

Point a Stripe webhook at `https://cloud.kadmu.app/api/webhook/stripe` and copy its signing
secret into `STRIPE_WEBHOOK_SECRET`. Subscribe to: `checkout.session.completed`,
`customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`.
Caddy proxies the raw body verbatim, so signature verification works through the proxy.

## What you set up yourself (out of scope for config-as-code)

This directory is **config**; provisioning the things the config points at is operational:

- **VPS provisioning** — two small boxes: this ops/control stack, and a separate one for
  coturn (`cloud/relay/`).
- **DNS records** — `cloud.`, `signal.`, `app.kadmu.app` → the ops box (proxy `app.` through
  Cloudflare; keep `cloud.`/`signal.` DNS-only); `relay.kadmu.app` → the relay box.
- **Env / secrets** — copy `.env.example` → `.env` and fill in `KADMU_SIGNAL_SECRET`,
  `KADMU_TURN_SECRET`, Stripe keys, the Grafana admin password (generate with
  `openssl rand -hex 32`).
- **Cloudflare account** — add the zone, set the cache rule, SSL mode Full (strict) — see
  [`cdn/README.md`](cdn/README.md).
- **R2 + Litestream** — an R2 bucket + a Litestream sidecar/cron replicating `cloud.db` for
  durability (restore in seconds on box loss).
- **Later, optional** — the **managed-Postgres + N-instance control-plane cutover** when a
  concrete trigger fires (p95 latency / tenant count — see the
  [observability runbook](observability/README.md#autoscale-runbook)). Not needed at launch.

## Scaling at a glance (full runbook in `observability/README.md`)

- **Signaling** scales **OUT** — add `sigN` behind the sticky LB (or
  `docker compose up -d --scale sig1=N`); the `X-Kadmu-Node` hash keeps guest+host pinned
  with zero shared state.
- **Relay (coturn)** scales **VERTICALLY first** — each is independently capped; grow the
  NIC before adding a second box.
- **Control-plane** stays **one box** until the documented Postgres cutover trigger.
