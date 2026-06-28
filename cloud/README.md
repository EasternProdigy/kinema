# Kadmu Cloud (`cloud/`) — the hosted layer

This directory is the **paid, hosted side of Kadmu** (Phase 4 of [docs/ROADMAP.md](../docs/ROADMAP.md)).
It is **NOT shipped to self-hosters** and is never required to run the open-source node.

The whole product stays open and unlocked; Cloud monetizes **convenience and
infrastructure**, never features. Critically, **the cloud never stores or pipes your
video** — files stay on your machine. Our servers only host the *account, billing,
and the connection handshake*, which keeps egress ≈ $0 (see ROADMAP §5).

```
cloud/
├─ control-plane/   ← Phase 4a (this PR): signup, Stripe billing, entitlement/license API, dashboard, donations
├─ signaling/       ← Phase 4b: P2P (WebRTC) handshake broker for remote-from-anywhere   [separate work]
└─ infra/           ← Phase 5: reverse proxy, scaling, observability (deploy notes)
```

## control-plane — what landed in Phase 4a

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

## How the open-source node attaches

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
