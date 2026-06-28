# Kadmu Roadmap — from LAN app to dual self-host + hosted product

> Status: **in progress.** Phase 1 "Tier 0" player polish (audio-track picker, subtitle
> styling + sync) has landed, and **Phase 2 (accounts & multi-user, opt-in `--accounts`) is
> shipped** — see the §2 marker and the changelog. This document remains the agreed direction;
> we keep implementing phase by phase, settling the open decisions in §6 as we go.

Goal: the **best browser-based player for your own video files** — VLC-grade per-file power,
Netflix-grade ease of use — shipped as **two editions from one codebase**:

- **Kadmu (self-host)** — open source, free, `git clone` / one-line install, runs on your box.
- **Kadmu Cloud (hosted)** — we run it; users pay before they get in. Same core + a thin
  cloud layer (accounts, billing, infra). People pay for *convenience and infrastructure*,
  not for features held hostage.

> **The pitch:** *Kadmu is the personal media player that's as private and free as Jellyfin,
> as easy as Plex, with the per-file power of VLC — and remote access that just works, without
> the Plex tax.* It's **our** app, and it gives the power back to the people who own their files.

### Decisions locked
- **Editions:** open-core — fully-open free self-host + paid hosted ("Kadmu Cloud"). Monetize
  the hosting, never cripple the free product.
- **Storage:** Cloud **never hosts or pipes the video** — files stay on the user's own machine.
  This keeps our egress ≈ $0 and removes DMCA-storage liability (see §5).
- **Remote scope:** **LAN-first, remote later.** Cloud v1 = same-device/LAN (accounts + billing
  + licensing wrapper, near-zero infra cost); P2P remote-from-anywhere is the headline v2 upgrade
  that makes the subscription clearly worth paying for.
- **Identity:** lead with the **player (VLC-power) + a great frontend**; market the three
  pillars — *effortless · VLC-meets-Netflix · yours & private*. See **Positioning** below.

### Already shipped (since the original TODO)
- ✅ Audio-track probing + selectable audio on the backend (`/api/stream?audio=N`, `meta.audios[]`)
- ✅ Embedded subtitle extraction (sidecar + in-container text subs → VTT)
- ✅ Background library index (instant/complete search), in-memory progress, trash auto-purge,
  concurrent-stream cap
- ✅ Sort & filter controls; Continue-watching and My-List rows
> Remaining from the old list — scrub-preview thumbnails, skip-intro, hero banner — are folded
> into the phases below. The audio-track UI and subtitle polish are now Phase 1 "Tier 0" because
> the backend is already done.

---

## Positioning — why Kadmu beats Plex & Jellyfin

Our competitors are **Plex** and **Jellyfin**. Each wins something and loses something; the gap
between them is the lane we own.

| | Plex | Jellyfin | **Kadmu** |
|---|---|---|---|
| License | closed | FOSS | **FOSS (open-core)** |
| Account required to watch | yes | no | **no** |
| Ads / upsells in *your* library | yes | no | **never** |
| Phones home | yes | no | **no (TMDB opt-in, default-off)** |
| Setup | easy | hard | **seconds — one file, no DB, no runtime** |
| Browse before scan finishes | no | no | **yes (background index + live walk)** |
| Per-file power (sync offset, EQ, filters…) | basic | basic | **VLC-grade, in the browser** |
| Native app required to view | yes | yes | **no — browser-first** |
| Remote access | **paywalled (2025)** | DIY reverse-proxy | **just works, cheap (P2P, ~$0 egress)** |

**The three things that ARE our identity** — build and market around these:

1. **Effortless & zero-install** — one command (or double-click) to run; nothing to install on
   the screen you watch on; browse instantly, never wait on a scan. *(Beats Jellyfin's #1 pain.)*
2. **VLC-power meets Netflix-ease** — the only browser player with audio/sub **sync offset**,
   **EQ + volume boost**, video filters, frame-step, A-B loop, screenshot *and* posters, a real
   home page, storyboard scrubbing. Nobody else combines both. *(Our feature moat.)*
3. **Yours, and private by architecture** — no account, no ads, no phone-home, one auditable
   file; files never leave your machine; remote is cheap because we never touch the bytes.
   *(Beats Plex's account/ads/bloat and its 2025 remote paywall.)*

**Ethos — this app gives the power back to the people who own their files.** No account to
watch, no ads, no upsells, no features held hostage, no lock-in: your library stays your folders,
your data stays yours, and the power-user controls are all *there*, not paywalled.

**What we deliberately DON'T do** (focus is a feature): no FAST channels / "discover" / content
platform, no Live TV/DVR for now, no chasing Plex's army of native TV/console apps — browser-first
is the counter-bet. Kadmu plays *your* files beautifully and gets out of the way.

---

## 0. The model: open-core, monetize the hosting

The trap to avoid: crippling the free version so people are forced to pay. That breeds
resentment and a community fork. Instead, the **product is fully open**; the **paid thing is
the hosting**. A handful of features only *make sense* in the cloud (off-site access without
port-forwarding, share-a-link, managed transcode) and naturally become Cloud perks.

| Capability | Self-host (free) | Cloud (paid) |
|---|---|---|
| Full player (all VLC-grade features) | ✅ | ✅ |
| Metadata/posters, discovery, library | ✅ | ✅ |
| Multi-user accounts & profiles | ✅ (optional, self-managed) | ✅ (core) |
| Your own libraries from your disks | ✅ | ✅ (served from YOUR machine — we never host the video) |
| HTTPS, uptime, backups, updates | you do it | we do it |
| Internet access without port-forward / DDNS | DIY | ✅ built-in (P2P-first) |
| Share a link to a friend across the internet | DIY | ✅ |
| Watch party / synced playback | ✅ (LAN) | ✅ (anywhere, P2P) |
| Transcoding | local CPU | local CPU (stays on your machine — keeps our egress at $0) |
| Support / SLA | community | ✅ |
| Cost | $0 | subscription, **pay first** |

**Donations** fund the open-source side (Ko-fi / GitHub Sponsors / Open Collective — a button,
no dependency). **Subscriptions** fund the hosted side (Stripe).

---

## 1. Architecture north star — keep the soul, add the platform

The repo's identity is sacred: **`src/server.py` is single-file, Python-stdlib-only, no build,
no `pip install`.** That magic is *why people will self-host it*. The plan preserves it.

The lucky break: **most of the multi-user/platform foundation is stdlib-compatible.**

- **`sqlite3` is in the standard library.** Accounts, per-user progress/My-List, persistent
  sessions, quotas — all can move to a single embedded DB **without breaking the no-pip
  promise.** This de-risks the entire accounts pillar.
- **`ssl` is in the standard library.** Optional built-in HTTPS (`--tls cert key`) is possible
  for self-hosters, even though a reverse proxy (Caddy auto-HTTPS) stays the recommended prod path.
- **The dormant profiles code is the seam.** `PROFILES_ENABLED = False` at
  `src/server.py:227`, plus `list_profiles`/`create_profile`/`current_profile` and an unread
  `X-Kadmu-Profile` header — multi-user is already half-designed. We activate it, we don't
  bolt it on.

What canNOT be stdlib (Stripe, the marketing/signup site, a load balancer, object storage)
lives in a **separate Cloud control-plane layer** — its own directory/service, *not* part of
the open-source core. The core node runs identically whether it's your laptop or a Cloud tenant.

```
kadmu/                      ← open source (MIT/AGPL — see §4), stdlib-only core
  src/server.py             ← the node: serves video, library, player. Runs everywhere.
  src/web/                  ← the frontend (both editions)
cloud/                      ← NOT shipped to self-hosters; powers Kadmu Cloud only
  control-plane/            ← signup, Stripe billing, tenant provisioning, dashboard
  infra/                    ← reverse proxy, autoscale, storage, observability
```

**Edition awareness = one entitlements check.** A small capability/entitlement layer
(`_session_state()` already gates the UI by capability flags — extend it) tells the frontend
what this user/instance can do. Self-host: everything local is "on." Cloud: gated by the
user's plan. The frontend already trusts the backend as the authority on capabilities, so this
fits the existing design.

---

## 2. The phased plan

Each phase is shippable on its own. Self-host benefits from 1–3 immediately; Cloud needs
2–4 before it can launch.

### Phase 1 — The player & frontend *(edition: Both)* — lead with our differentiators
This is where we win. No DB, no accounts, no new deps. **Order matters: ship the power-user
player and a beautiful frontend first** (the moat), then the Netflix-style discovery layer.

**1.1 — VLC-grade player (the moat — do this first):**
- **Tier 0 (backend already done):** audio-track picker UI; subtitle styling + **sync offset**.
- audio **sync offset** (±ms); video filters (rotate/flip/aspect/zoom, brightness/contrast/
  saturation via CSS); **Web Audio EQ + volume boost >100%** + normalization; chapters;
  frame-step (`,`/`.`); A-B loop; screenshot; free-typed speed.
- per-file / per-show **memory** of chosen audio, subtitle, speed, and sync.

**1.2 — A genuinely good frontend (see "Frontend & design bar" below):**
- redesign the player overlay so all the new controls are discoverable but never cluttered
  (grouped menus, a "more" tray, full keyboard map, command palette).
- storyboard **hover-scrubbing** on the seek bar (`STORYBOARD_DIR` at `src/server.py:66`, unused).
- responsive/touch polish, **PWA install**, accessibility pass (landmarks, focus, captions).

**1.3 — Netflix-grade discovery:**
- metadata enrichment (TMDB/.nfo — first opt-in outbound call), show/season parsing.
- real home page (hero + rows incl. Recently Added, "Because you watched"), up-next +
  skip-intro (from chapters), preview-on-hover.

**1.4 — Signature delight (cheap "wow" neither competitor nails):**
- **watch party / synced playback** (LAN/self-host via a server-coordinated play state) — make
  it one click and free. Cross-internet watch-party + share-a-link land with P2P in Phase 4b.

### Phase 2 — Accounts & multi-user foundation *(edition: Both; required for Cloud)* — ✅ SHIPPED
- ✅ Introduced **SQLite** (`sqlite3`, stdlib) as the accounts/state store, with a one-time
  importer that pulls the shared single-password JSON state into the first (owner) account.
  The JSON files remain the store for the default single-password mode.
- ✅ **Real users:** registration, login, **admin/self password reset**, per-user identity.
  (Email-based reset isn't possible stdlib-only with no SMTP config — reset is admin-driven
  in the UI plus the `--reset-password` console hatch. Email reset waits for the Cloud layer.)
- ✅ **Per-user data isolation:** progress, My List, playlists and prefs keyed by `user_id`.
- ✅ **Persistent sessions** (SQLite rows, survive restart) + **roles** (admin vs viewer;
  management is admin-only, last-admin protected).
- ✅ Opt-in (`--accounts`); default stays single-password simple. Accounts subsume `--profiles`.
> Built stdlib-only (PBKDF2-HMAC-SHA256 password hashing). Frontend: first-run owner setup,
> sign-in/registration, an account menu, and Settings ▸ Your account / People (admin).
> **Still open for a later pass:** a JSON *export* path (we import but don't export yet), and
> moving the rest of frontend prefs server-side (cc/keyHud already sync; volume/last-folder don't).

### Phase 3 — Public-hardening & ops *(edition: Both; required for Cloud)*
- **TLS story:** optional built-in `ssl` + a documented Caddy reverse-proxy deploy (auto-HTTPS).
- **Abuse protection:** per-IP request rate limiting & timeouts (today only `/api/login` is
  throttled; everything else is open — re-indexing is cheap to weaponize).
- **Observability:** structured request logging (`log_message` is a no-op at
  `src/server.py:2036`), `/healthz`, basic metrics, error capture.
- **Quotas/accounting:** per-user concurrent streams + bandwidth meter (prereq for paid tiers).

### Phase 4a — Cloud v1: accounts, billing, licensing (LAN) *(edition: Hosted)* — 🚧 SCAFFOLDED
The node still runs on the user's machine and serves local files (LAN). The cloud adds the
paid wrapper — egress ≈ $0 (license checks + app shell only).
- Marketing/landing + **signup with pay-first gate** (Stripe Checkout → entitlement → access).
- **Stripe billing:** subscriptions, webhooks, plan→entitlement sync, dunning, cancellation.
- **Entitlement/license check:** the local node validates an active subscription against the
  cloud (offline grace period so playback survives brief outages).
- **Donations** wired for the OSS side (separate, simple).
> **Landed (stdlib-only, runs end-to-end in MOCK mode with no Stripe keys):** the
> `cloud/control-plane/` service — landing/pricing/donate pages, pay-first signup, Stripe
> Checkout + customer portal + **signature-verified webhooks** (subscription-state sync),
> the machine-to-machine **`/api/license`** endpoint issuing short-lived **HS256** license
> tokens, a subscriber **dashboard** (status + node connection details), and donations.
> Node side: **`src/kadmu/cloud.py`** cloud-attach client (`--cloud`/`--tenant` +
> `KADMU_CLOUD_SECRET`) that fetches + verifies a license, caches it for **offline grace**
> across restarts, and gates the instance (HTTP 402, app shell still loads) when the
> subscription is inactive. Self-host stays fully unlocked (the gate is a no-op). See
> [cloud/README.md](../cloud/README.md). **Still open:** a live Stripe key test, the
> trial-vs-none decision, multi-node-per-account UX, and (future) asymmetric license keys.
- ⚠️ Honest caveat: LAN-only paid value is thin vs. free self-host. Bundle real convenience
  (managed updates, hosted metadata service so users need no TMDB key, priority support, polish)
  and position remote access (4b) as the reason to subscribe.

### Phase 4b — Cloud v2: remote-from-anywhere (P2P) *(edition: Hosted)* — the headline upgrade
- **P2P remote access (WebRTC):** browser ↔ home node directly; cloud brokers only the handshake
  (signaling). Tunnel the existing byte-range streaming over a WebRTC data channel to keep seeking.
- **Relay fallback policy** for hostile-NAT minority: capped quality/usage, paid add-on, or BYO
  relay — never default-tunnel-all-video (see §5).
- Cloud-only perks: off-site access (no port-forward/DDNS), share-a-link to a friend.

### Phase 5 — Scale & cost control *(edition: Hosted)*
- Signaling/relay infra scaling; CDN for the static app shell.
- Horizontal scale of the control plane: stateless API + shared DB; ThreadingHTTPServer limits
  (~100–200 concurrent/node) inform the self-host node, not the (now thin) cloud.
- Relay-cost monitoring + per-plan caps so the ~10–20% relay minority can't blow the budget.

---

## Frontend & design bar

"A good frontend" is a first-class goal here, not a coat of paint. The bar:

- **Stay vanilla** — no framework, no bundler, no transpile (project constraint). Prove a
  world-class UI is possible in hand-written HTML/CSS/JS; keep it fast and dependency-free.
- **Brand-true** — every color, gradient, font, radius, shadow from [BRAND.md](BRAND.md) /
  `style.css`. Calm, cinematic, uncluttered — the anti-Plex.
- **Player UX** — surface the new power-user controls without clutter: grouped control menus, a
  "more" tray, a settings sheet, a full keyboard map + command palette, on-screen gesture
  feedback. Power is *available*, never *in your face*.
- **Library UX** — Netflix-feel home (hero + rows), poster grid, storyboard scrub, instant
  search (done), smooth lazy media, tasteful motion (respect `prefers-reduced-motion`).
- **Responsive & touch** — great on phone/tablet/TV-browser; 44px targets; gestures; PWA
  installable; a real "living-room" view.
- **Accessible** — landmark regions, focus management, library keyboard nav, caption defaults,
  high-contrast-safe, `:focus-visible` everywhere.
- **Fast & robust** — instant first paint, optimistic UI, graceful offline/empty/error states,
  no layout shift. Feel like a native app that happens to live in a tab.

> Frontend work runs through all of Phase 1 and continues as features land — it's the difference
> between "a script that plays files" and "the app people choose over Plex."

---

## 3. Feature backlog by pillar (prioritized)

Effort: **S** ≈ hours/1 day · **M** ≈ days · **L** ≈ week+. Most-impactful items **bolded**.

### Pillar A — VLC-grade per-file power
1. **Audio-track picker UI** — backend ready (`/api/stream?audio=N`, `meta.audios[]`), no UI. **S**
2. **Subtitle styling + delay/sync offset** — signature VLC features, mostly frontend. **S–M**
3. Audio sync offset (±ms). **S**
4. Video filters: rotate/flip, aspect override, zoom/crop, brightness/contrast/saturation (CSS). **S–M**
5. Web Audio: equalizer, gain >100%, normalization, mono downmix. **M**
6. **Chapters** (ffprobe already exposes them) → menu + seek-bar markers → basis for skip-intro. **M**
7. Frame-step (`,`/`.`), A-B loop, screenshot, free-typed playback speed. **S**
8. Per-file / per-show memory of chosen audio, subtitle, speed, sync. **S**
9. Deinterlace + custom transcode resolution. **M**
10. Cast / DLNA out ("play on TV"). **L**

### Pillar B — Netflix-grade ease (biggest overall lever)
1. **Metadata enrichment (TMDB / local .nfo)** — posters, backdrops, synopsis, cast, ratings,
   episode titles. Turns "folder of mp4s" into a catalog. First opt-in outbound call. **L**
2. **Storyboard hover-scrubbing** (`STORYBOARD_DIR` scaffolded, unused). **M**
3. Smart organization: `S01E02` parsing, show/season grouping, Movies vs TV split. **M**
4. Real home page: hero/billboard + rows (Continue ✅, My List ✅, Recently Added,
   Because-you-watched, genre rows). **M**
5. Up-next autoplay countdown (next-card exists) + skip-intro from chapters. **S–M**
6. Preview-on-hover (animated thumb / short autoplay); filters by genre/year/resolution. **M**
7. **PWA** (installable, offline shell). **S**

### Pillar C — Platform / public / monetization
1. **SQLite state store** + JSON→DB migration. **L**
2. **Real accounts** (activate profiles): register, login, reset, identity. **L**
3. **Per-user data isolation** (progress/lists/prefs by user). **L** (with #2)
4. Persistent sessions + roles (admin/viewer). **M**
5. TLS (built-in `ssl` opt-in + Caddy deploy doc). **M**
6. Per-IP rate limiting + request timeouts + body/abuse limits. **M**
7. Observability: logging, `/healthz`, metrics, error capture. **M**
8. Quotas/accounting (streams, bandwidth) per user. **M**
9. Stripe billing + pay-first signup + entitlement gating. **M** (after accounts)
10. Donations (Ko-fi/Sponsors/Stripe link). **S**
11. Cloud control plane: provisioning, dashboard, tenant routing. **L**
12. Scale: transcode workers, egress/CDN, storage model. **L**

### Pillar D — Signature features (what Plex/Jellyfin don't nail)
1. **Watch party / synced playback** — one-click, free for self-host (server-coordinated play
   state over SSE/WebSocket on LAN; over the P2P channel for remote). Plex paywalls it,
   Jellyfin's SyncPlay is clunky. **M**
2. **Share-a-link to one video** — time-limited, no account; over P2P so ~$0 egress (Phase 4b). **M**
3. **Command palette + full keyboard control** — power-user navigation neither web player has. **S**

---

## 4. Open source & licensing — decide deliberately

Currently **MIT**. MIT lets *anyone* — including a competitor — take the code and launch a
rival hosted Kadmu, using your work to undercut your paid tier. For a project that *also* runs
a hosted business, the common defenses:

- **Keep MIT** — maximally friendly, best for adoption/community; accept that others may host it.
- **AGPL-3.0 for the core** — copyleft; anyone who hosts a *modified* version must publish their
  changes. Standard "we want a community *and* a hosting business" choice (Jellyfin-adjacent).
- **Open-core split** — core under MIT/AGPL, the `cloud/` control-plane stays **proprietary**
  (it's our infra, never needed to self-host). This is compatible with either core license and
  is likely the right combo: **AGPL (or MIT) core + proprietary cloud layer.**

Also to decide: monorepo (core public + `cloud/` private submodule) vs. two repos;
CLA for contributions; trademark on the "Kadmu" name so forks can't trade on the brand.

---

## 5. Cost model — local files keep our egress near-zero (DECIDED)

**Decision:** Cloud never stores, hosts, or pipes users' video. Files stay on the user's own
machine and are served from there to their browser. Our cloud is **accounts + billing + the
connection handshake — not a video pipe.** This is the single biggest cost lever, and it also
removes our DMCA-storage liability (we never store or serve the content).

Where our cloud actually spends bytes:

| Flows through our cloud | Size | Cost |
|---|---|---|
| App shell (HTML/JS/CSS) | hundreds of KB, CDN-cached | ~cents, once |
| Auth + library listings (API JSON) | KB / session | negligible |
| Connection signaling | KB, once / session | negligible |
| **The video itself** | **0 — never touches our servers** | **$0** |

vs. the "we host the files" model where *every byte of every stream* is our egress — a 95%+ cut.

**The one place egress can sneak back: remote playback that can't go peer-to-peer.**
- **Same-device / same-LAN:** bytes go disk→browser or PC→TV over the LAN. Cloud touches zero video.
- **Remote, P2P (WebRTC):** browser ↔ home node directly; cloud brokers only the handshake.
  ~Zero egress; works on ~80–90% of networks. The existing byte-range streaming can be tunneled
  over a WebRTC data channel, so seeking and the current pipeline mostly survive.
- **Remote, relay fallback (~10–20% hostile NATs):** traffic bounces through a relay. If that
  relay is ours, we pay full video egress — the only leak. Mitigate: cap relay quality/usage,
  charge for it, or have users bring their own. **Never** default to "tunnel all video through
  us" (the naive reverse-tunnel) — that reintroduces full egress. P2P-first is how Tailscale
  keeps costs down.

**Tradeoffs of local files** (same as Plex/Jellyfin): the user's computer must be **on** to
watch; remote quality is capped by their **home upload speed**, not our infra.

**Legal (much lighter now):** still want **ToS + Privacy Policy** for the account service, but
no content hosting ⇒ no DMCA-storage liability and no file-takedown duty.

**"Pay first" mechanics:** Stripe Checkout before account activation; decide trial vs. none,
refund window, and cancellation behavior.

This is *why* the recommended sequence front-loads the free product (Phases 1–3) and treats the
hosted business (Phases 4–5) as a deliberate, separately-funded step.

---

## 6. Open decisions needed (before building Phase 2+)

1. **Licensing:** MIT core, AGPL core, or open-core (AGPL/MIT core + proprietary `cloud/`)?
2. ~~**Self-host multi-user default:**~~ **DECIDED** — single-password stays the default;
   accounts are **opt-in** via `--accounts` (shipped in Phase 2). Cloud will require them.
3. **Metadata enrichment:** OK to add the first **opt-in outbound network call** (TMDB)? (The
   app currently never phones home — this is a deliberate philosophy change, default-off.)
4. **Remote-access scope** (now the key Cloud fork — storage is decided: files stay local):
   same-device/LAN only (cheapest; cloud = accounts wrapper, egress ≈ $0), or
   remote-from-anywhere too (P2P-first WebRTC, relay only as a capped fallback)?
5. **Pricing shape:** flat monthly? tiers by streams/storage/bandwidth? (affects quota design.)
6. **stdlib purity for self-host:** confirm we hold the **stdlib-only, single-file, no-pip**
   line for the core (the plan assumes yes — `sqlite3`/`ssl` keep it intact).

## 7. Recommended first move

Build **Phase 1 in order** now — pure product value, ships to self-host immediately, zero
architecture risk, and *is* the eventual Cloud product. Lead with **1.1 the VLC-grade player**
(the moat — Tier 0's backend is already done) and **1.2 a genuinely good frontend**, then layer
on discovery (1.3) and the signature watch-party delight (1.4). Settle the §6 decisions in
parallel; none of them block Phase 1.
