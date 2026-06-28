# Kadmu Cloud — relay (`cloud/relay/`)

The **capped TURN relay**: the last-resort fallback for the Phase 4b P2P remote
feature, on the ~**10-20%** of networks where a direct WebRTC connection can't be
made. **P2P stays the default** — relay only carries a session when ICE has no
other working candidate, and only if the tenant's plan and remaining budget allow
it. This is the single place where the cloud's egress can leak, so it ships with
metering and per-plan byte caps from day one (never the relay without the caps).

Full design: [docs/PHASE_5_DESIGN.md](../../docs/PHASE_5_DESIGN.md) §2 (2.1-2.5).
Background on the relay policy: [cloud/README.md](../README.md) "Relay / TURN policy".

This directory is **config-as-code only** — a coturn config, a Compose stack, and
this runbook. No Python lives here; the metering logic it works with is authored
in [`cloud/metering/`](../metering/).

```
cloud/relay/
├─ turnserver.conf       coturn config (REST-API creds, caps, SSRF deny, exporter)
├─ docker-compose.yml    coturn + the metering collector
├─ .env.example          documented placeholders (copy to .env)
└─ README.md             this runbook
```

---

## What runs here

| service | image | what it does |
|---|---|---|
| `coturn` | `coturn/coturn:latest` | the TURN relay; validates ephemeral creds locally, enforces the quality/abuse caps, exposes Prometheus metrics on `:9641` |
| `meter-collector` | runs [`cloud/metering/collector.py`](../metering/collector.py) | scrapes coturn's `/metrics`, diffs byte counters, attributes them to the tenant in each TURN username, writes per-tenant usage to the shared `cloud.db` |

---

## The credential scheme (no open relay, ever)

coturn runs in **TURN REST API** mode (`use-auth-secret`): it validates each
credential's HMAC **locally** against a shared secret, with **no callback** to us
— so the relay stays dumb and cheap, but credentials are unforgeable and expire
fast.

```
username = "<expiry-unix-timestamp>:<tenant-id>"
password = base64( HMAC-SHA1( static-auth-secret, username ) )
```

The flow (design §2.2):

1. Right before connecting, the browser asks the control-plane (4a):
   `GET /api/relay-credentials` (authed, tenant-bound).
2. The control-plane checks: active subscription? plan allows relay? tenant under
   its monthly relay-byte cap (via `metering.caps.relay_allowed(tenant, plan)`)?
3. **Yes** → it mints a **short-TTL** (e.g. 120 s) credential as above and returns
   `{ relay: true, iceServers: [...], ttl }`.
   **No** → `{ relay: false, reason }`, and the browser stays P2P-only (showing
   "remote unavailable on this network / upgrade for relay").
4. coturn recomputes the HMAC with `static-auth-secret`; match + future expiry ⇒
   allocation allowed.

**Over budget / no subscription ⇒ no credential ⇒ no relay allocation.** The cap
is enforced *before* bytes flow, not cleaned up after. The same `static-auth-secret`
(`TURN_SECRET`) must be configured on **both** this relay and the control-plane.

---

## The per-plan cap model (design §2.4)

Relay carries **video**, so the caps are set against a real egress budget:

- Relay quality is **capped at ~720p ≈ 2.5 Mbps** — never original/4K over relay.
  That's ~**1.1 GB/hour**. Enforced two ways (defense in depth): `max-bps` in
  `turnserver.conf`, and the connector clamping to `RELAY_MAX_HEIGHT=720` when its
  selected ICE pair is `relay`.
- A generous personal cap of **100 GB / tenant / month** ≈ ~90 hours of relayed
  viewing. Most tenants use **0** (P2P works); only the hostile-NAT minority touch
  relay at all. At ~$0.01/GB that's ~$1/tenant worst case, only for that minority
  — blended cost per subscriber is cents.

The cap numbers live in the control-plane's plan catalog (`PLAN_RELAY_CAP_BYTES`),
not here; this relay just enforces the per-session **quality** ceiling and reports
bytes for the cap accounting.

---

## How it ties together

```
browser ──GET /api/relay-credentials──▶ control-plane (4a) ──relay_allowed()?──▶ cloud/metering
   │                                          │ mint short-TTL HMAC cred
   │ ◀────── { iceServers, ttl } ─────────────┘
   ▼
coturn (this relay) ── validates HMAC locally, allocates, caps quality ──▶ relayed media
   │ Prometheus :9641 (turn_traffic_*)
   ▼
meter-collector (cloud/metering/collector.py) ── diff bytes, attribute per tenant ──▶ cloud.db
                                                                                        ▲
                                              control-plane reads usage for the next ───┘
                                              relay_allowed() cap decision
```

- **Control-plane** ↔ relay: shares `TURN_SECRET`; mints creds at
  `GET /api/relay-credentials`. (See [docs/PHASE_5_DESIGN.md](../../docs/PHASE_5_DESIGN.md) §6.1.)
- **Metering** ↔ relay: the collector reads coturn's `:9641/metrics`. Usage lands
  in the shared `cloud.db` so the control-plane's `relay_allowed()` sees it next
  time (design §2.3, §10.2 — one store, one Litestream backup).

---

## The SSRF / abuse-deny rationale (CRITICAL)

A TURN relay forwards traffic to whatever peer the client names. Without
restrictions it becomes an open **SSRF proxy** into anything routable from the
VPS — cloud metadata endpoints, the LAN behind the box, localhost services. So
`turnserver.conf` **denies every non-public range**, IPv4 and IPv6 (RFC1918,
loopback, link-local, CGNAT/RFC6598, ULA, TEST-NETs), plus `no-multicast-peers`.
Combined with `use-auth-secret` (no anonymous allocations), `no-cli`, modern-TLS
only, and `fingerprint`/`stale-nonce`/`secure-stun`, the relay can only shuttle
media between two public-internet peers it was given a valid credential for.
**If you add an `allowed-peer-ip` exception, you are widening this surface — don't.**

---

## BYO-relay escape valve

A tenant can point at **their own** coturn instead of ours (design §2.4, third
escape valve). In that case the control-plane's credential endpoint returns the
tenant's server in `iceServers`, and **none of their relayed bytes are our egress**
— so a heavy relay user can self-host the cost. This relay is for the default,
capped, hosted path; BYO is the pressure valve for anyone who outgrows it.

---

## Running it

```bash
cd cloud/relay
cp .env.example .env          # then fill in the blanks (see below)
docker compose up -d
docker compose logs -f coturn
```

Quick sanity check (from another host, replace the realm + a minted cred — the
control-plane mints these; there is no static login):

```bash
# install the coturn client tools, then exercise an allocation with a real cred:
turnutils_uclient -v -u "<exp>:<tenant>" -w "<base64 hmac>" turn.kadmu.app
```

Do **not** run the relay open to validate it — there is intentionally no static
user; a valid ephemeral credential from the control-plane is the only way in.

---

## WHAT YOU STILL NEED TO SET UP YOURSELF

This is config-as-code; the relay needs a home and some one-time wiring:

1. **A separate small VPS** for the relay (design §1 keeps it isolated from the
   control-plane so the only egress source is contained — ~$5/mo). Install Docker.
2. **DNS** — point an **A record** for `turn.kadmu.app` (your `TURN_REALM`) at the
   VPS's public IP.
3. **`TURN_EXTERNAL_IP`** — set it in `.env` to the VPS's public IPv4 (most cloud
   VPSes are 1:1 NAT, so coturn must advertise the public address, not the private
   one). For 1:1 NAT you may use `<public>/<private>`.
4. **Generate & share `TURN_SECRET`** — `openssl rand -hex 32`. Put it in this
   `.env` **and** configure the **same value** on the control-plane host (it signs
   the credentials this relay validates). Keep it out of source control.
5. **Open the firewall** on the VPS (and any cloud security group):
   - `3478/udp` and `3478/tcp` — STUN/TURN
   - `5349/tcp` — TURN over TLS
   - the relay UDP range `49160-49200/udp` (`RELAY_MIN_PORT`-`RELAY_MAX_PORT`;
     widen for more concurrent sessions, keeping `.env`, `turnserver.conf`, and
     the firewall in sync)
   - keep `9641` (metrics) **internal only** — never expose it publicly.
6. **(TLS on `:5349`)** — provide certs for `TURN_REALM` (e.g. via the
   `cert`/`pkey` coturn options or a fronting proxy). Plain `3478` works without
   them; TLS is recommended for clients on restrictive networks.
7. **Point the collector at the real `cloud.db`** — in production, bind-mount the
   control-plane's data directory into the `meter-collector` service (replacing the
   `meter-data` named volume) so metering and cap decisions share one store.

That's it — once DNS, the IP, the secret, and the firewall are set, the relay
serves only credential-bearing, capped, public-peer-only sessions, and the
collector keeps the per-tenant byte counts flowing into the control-plane.
