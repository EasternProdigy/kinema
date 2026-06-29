# Kadmu — Monetization

How Kadmu makes money, what's free, and exactly where each lever is wired in code.

## The model (one sentence)

**Open-core: the player is free and MIT, and we monetize the hosted *connection* — not
the features.** Files never flow through our servers (model A / P2P), so company cost
scales with *tenants* (cheap), not *watch-hours* (expensive). See
[ROADMAP.md](ROADMAP.md) ("Business model") and [cloud/README.md](../cloud/README.md).

Two hard rules this doc keeps:

1. **Never cripple the free version.** Gating a *local* feature (accounts, parental
   controls, archive, DLNA, playback) just breeds a community fork. We only gate
   *cloud-delivered* conveniences (remote access, relay, off-site backup).
2. **MIT means you can't sell the software.** A fork can rebuild the binary for free.
   Durable revenue comes from things a fork can't copy: the hosted connection, the
   trademark, signed-and-updated builds, and convenience services.

---

## What's free, forever (self-host)

Everything in the player and on the box: browse/resume/autoplay, on-the-fly
remux/transcode + HLS, the Netflix-style home + discovery + recommendations,
accounts/profiles/roles, parental controls + library scoping, DLNA / Chromecast /
10-foot TV, LAN watch party, archive + remote-storage mounts, TLS, PWA. The free
install advertises Cloud and can carry affiliate links, but is never feature-locked.

---

## The levers

### 1. Subscription — Kadmu Cloud (primary, recurring)

The engine. A node run cloud-attached (`--cloud`/`--tenant` + `KADMU_CLOUD_SECRET`)
polls the control-plane for a signed license; the license `features` dict lights up
cloud conveniences. Inactive subscription → the node's gate returns **402** and the
app shows a "Manage billing" notice.

**Tiers** (catalog: [cloud/control-plane/cloud/const.py](../cloud/control-plane/cloud/const.py) `PLANS`):

| Tier | Price | Homes | Relay cap / quality | Notes |
|---|---|---|---|---|
| **Self-host** | Free (MIT) | — | — (LAN/P2P you run) | Everything local |
| **Plus** | $5/mo · $50/yr | 1 | 100 GB · 720p | Remote access, share-link, managed metadata/subtitles, backup |
| **Family** | $9/mo · $90/yr | 3 | 250 GB · 1080p | Most popular |
| **Pro** | $15/mo · $150/yr | 5 | 500 GB · 1080p | Priority support |
| **Lifetime** | $149 once | 1 | 50 GB · 720p | One-time; P2P-first (modest relay so it isn't a margin trap) |

Prices are display values; the real charge is the Stripe Price per plan
(`STRIPE_PRICE_*` env). With no Stripe key the control-plane runs in **MOCK mode** and
the full signup→pay→license→tier flow works locally.

**Code:** plan→features minting `const.features_for_plan` → `licensing.issue(features=…)`
→ node reads `cloud.entitlement_state()["features"]` and `cloud.feature("remote")`
([src/kadmu/cloud.py](../src/kadmu/cloud.py)). Pricing page: `pages.pricing`.
Checkout/webhooks: `stripe_client` + `webhooks.process_event` (lifetime = one-time
`mode=payment` → perpetual entitlement via `_complete_onetime_purchase`).

### 2. One-time purchases (survive MIT)

- **Lifetime Cloud** — wired above (relay deliberately modest).
- **Paid signed desktop build + auto-update** — sell the notarized, one-click,
  auto-updating app; source stays free. *Not code in this repo — a packaging/signing
  pipeline (`pyinstaller` builds already exist in the Release workflow).*
- **Commercial / white-label / OEM license** — businesses embedding Kadmu pay for the
  **trademark + branding removal + support/warranty** (MIT grants no trademark). *Legal
  + a price page; not code.*

### 3. Metered add-ons (recurring, margin-safe)

Charge for the one thing that actually costs money — relay egress. Already metered:
[cloud/metering/](../cloud/metering/) tracks per-tenant bytes and enforces per-plan caps
(`PLAN_RELAY_CAPS`). Overage / "relay-plus" / extra homes drop in here.

### 4. Managed conveniences (cheap Cloud perks — license `features`)

`metadata` (managed TMDB), `subtitles` (managed fetch), `backup` (off-site settings),
`share_link` (private per-title link). All flags already minted per tier; wire the
server side incrementally. None gate a local feature.

### 5. No-infra revenue ($0 cost — already surfaced in-app)

- **"Where to watch" affiliate** on discover + search-external info sheets
  ([src/web/js/billing.js](../src/web/js/billing.js) `whereToWatchUrl`, used by
  `openDiscover` in catalog.js). Default = a plain JustWatch search; set
  `KADMU_AFFILIATE_WATCH` (with `{q}`) to earn referral.
- **Storage-provider referrals** in the "Add cloud/remote storage" dialog
  ([src/web/js/manage.js](../src/web/js/manage.js) — `link`/`getLabel` per provider).
- **Donations** — one-time Stripe Checkout, OSS funding (`/donate`, presets in cloud
  `const.py`). Surfaced in the node's Settings → Kadmu Cloud card.

---

## In-app monetization surface (the "where")

`/api/session` always carries an `upsell` block (`site`, `pricing`, `donate`,
`affiliate`) — even on self-host — built in [src/kadmu/handler.py](../src/kadmu/handler.py)
`_session_state`. The UI uses it in:

- **Settings → "Kadmu Cloud"** ([src/web/js/billing.js](../src/web/js/billing.js)):
  current plan + "Manage billing" for a tenant, or a "watch from anywhere" upsell +
  Support/Donate for self-host.
- **Discover / search info sheet** — "Find where to watch →".
- **Cloud inactive overlay** ([src/web/js/cloud.js](../src/web/js/cloud.js)) — 402 path.

A host can blank the whole surface with `KADMU_SHOW_UPSELL=0`.

### Config (node)

| Env | Default | Purpose |
|---|---|---|
| `KADMU_CLOUD_SITE` | `https://kadmu.app` | Marketing/pricing base URL |
| `KADMU_DONATE_URL` | `<site>/donate` | Donate link |
| `KADMU_AFFILIATE_WATCH` | (empty → JustWatch) | "Where to watch" affiliate base (`{q}`) |
| `KADMU_SHOW_UPSELL` | `1` | Set `0` to hide all paid touchpoints |

### Config (cloud control-plane)

`STRIPE_PRICE_{MONTHLY,YEARLY,FAMILY_MONTHLY,FAMILY_YEARLY,PRO_MONTHLY,PRO_YEARLY,LIFETIME}`,
`KADMU_RELAY_CAP_{MONTHLY,YEARLY,FAMILY,PRO,LIFETIME}_GIB`, plus the existing
`STRIPE_*` keys. See [cloud/control-plane/.env.example](../cloud/control-plane/.env.example).

---

## Launch checklist (the non-code bits)

These are accounts/legal actions, not code — the code is wired to accept them:

1. Create the Stripe Products/Prices for all tiers + lifetime; set `STRIPE_PRICE_*`.
2. Confirm tier prices + relay caps (the placeholders above).
3. (Optional) Join affiliate programs (JustWatch/retailer, storage providers); set
   `KADMU_AFFILIATE_WATCH` + the provider links in `manage.js`.
4. Decide the licensing stance (keep MIT vs open-core the `cloud/` layer) — see
   [ROADMAP.md](ROADMAP.md) open decisions.
5. Trademark "Kadmu" before selling commercial/white-label rights.
