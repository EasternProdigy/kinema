# Kadmu — Roadmap & future plans

The vision, the business model, and **what's next**. This is forward-looking on purpose:

- **What's already built** → [CHANGELOG.md](CHANGELOG.md) (the record of shipped work).
- **How to take the hosted edition live** → [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) (the
  step-by-step go-live punch list).
- **Where we're going** → this document.

> **Status in one line:** the whole roadmap (Phases 1–5) is **code-complete on `main`**.
> Self-host (the player, accounts, hardening) is shipped and production-ready. The hosted
> edition (billing, P2P remote, scale/cost-control) is built and runs in mock mode; what's left
> is *operational* (deploy + real-network testing), tracked in the launch checklist.

---

## Vision — why Kadmu beats Plex & Jellyfin

The **best browser-based player for your own video files** — VLC-grade per-file power,
Netflix-grade ease — shipped as **two editions from one codebase**: free self-host, and a paid
hosted "Kadmu Cloud" that sells *convenience and infrastructure, never features*.

Our competitors are **Plex** and **Jellyfin**; the gap between them is the lane we own:

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
   the screen you watch on; browse instantly, never wait on a scan.
2. **VLC-power meets Netflix-ease** — the only browser player with audio/sub sync offset, EQ +
   volume boost, video filters, frame-step, A-B loop, screenshot, a real home page, storyboard
   scrubbing — *and* a watch party. Nobody else combines both. (Our feature moat.)
3. **Yours, and private by architecture** — no account, no ads, no phone-home, one auditable
   file; files never leave your machine; remote is cheap because we never touch the bytes.

**What we deliberately DON'T do** (focus is a feature): no FAST channels / "discover" / content
platform, no Live TV/DVR for now, no chasing Plex's army of native TV/console apps. Browser-first
is the counter-bet — Kadmu plays *your* files beautifully and gets out of the way.

---

## Business model — open-core, monetize the hosting

The trap to avoid is crippling the free version so people are forced to pay; that breeds a
community fork. Instead the **product is fully open** and the **paid thing is the hosting**. A
few features only *make sense* in the cloud and naturally become Cloud perks:

| Capability | Self-host (free) | Cloud (paid) |
|---|---|---|
| Full VLC-grade player, metadata, library, accounts | ✅ | ✅ |
| Your libraries from your disks | ✅ | ✅ (served from YOUR machine — we never host the video) |
| HTTPS, uptime, backups, updates | you do it | we do it |
| Internet access without port-forward / DDNS | DIY | ✅ built-in (P2P-first) |
| Share a link to a friend across the internet | DIY | ✅ |
| Watch party / synced playback | ✅ (LAN) | ✅ (anywhere, P2P) |
| Cost | $0 | subscription, **pay first** |

**Donations** fund the open-source side (Ko-fi / GitHub Sponsors / Stripe one-time); **subscriptions**
fund the hosted side (Stripe). The core node runs identically whether it's your laptop or a Cloud
tenant — edition awareness is one entitlements check (`_session_state()` capability flags).

### Cost model — local files keep our egress near-zero (decided)

The single biggest lever: **the cloud never stores, hosts, or pipes users' video.** Files stay on
the user's machine and stream to their browser from there. Our cloud is **accounts + billing +
the connection handshake — not a video pipe.** This keeps egress ≈ $0 and removes DMCA-storage
liability (we never store or serve the content).

- **Same-device / LAN:** bytes go disk→browser or PC→TV. Cloud touches zero video.
- **Remote, P2P (WebRTC):** browser ↔ home node directly (~80–90% of networks); cloud brokers
  only the handshake. The existing byte-range streaming is tunneled over a data channel, so
  seeking survives.
- **Remote, relay fallback (~10–20% hostile NATs):** a TURN relay carries the session — the one
  place egress can reappear. It is **hard-capped** per plan (100 GB/mo, ≤720p), credentialed only
  for active+under-cap tenants, and alerted at the fleet level. **Never** default-tunnel-all-video.

Tradeoffs (same as Plex/Jellyfin): the user's machine must be **on** to watch, and remote
quality is capped by their **home upload speed**, not our infra. Fixed hosted cost ≈ **$10–11/mo**
until thousands of tenants — scales with *tenants* (cheap), not *watch-hours* (expensive).

---

## Future plans

### Near-term engineering (the real remaining code)

These are the only items that are still *code* (everything else is deploy — see the launch
checklist). Detail + verification steps live in [LAUNCH_CHECKLIST.md §1](LAUNCH_CHECKLIST.md).

- **Phase 4b real-network testing** — the aiortc transport + browser `RTCPeerConnection`
  handshake are reviewed but never run against two real networked peers. (`cloud/wire.py` framing
  *is* unit-tested.)
- **Fragmented-MP4 for remote video** — MSE needs fMP4; `build_remux` emits plain MP4, so remote
  *video* (vs the JSON API) only plays via the progressive-blob fallback. Add an fMP4 profile for
  the remote case, gated so self-host streaming is unchanged. The headline 4b follow-up.
- **Share-a-link** — a scoped, time-limited entitlement the broker accepts for an account-less
  guest, with `remote.js`'s fetch proxy constrained to one path. Also P2P, so ≈ $0 egress.
- *(hardening)* **Asymmetric license keys** — license + tenant proof use a symmetric secret today;
  a later pass could move signing to asymmetric keys.

### Bigger bets / later

- **Metadata enrichment (TMDB / local `.nfo`)** — posters, backdrops, synopsis, cast, episode
  titles. The first opt-in *outbound* call (default-off — the app still never phones home). The
  hosted edition could run this as a managed service so users need no TMDB key.
- **Cast / DLNA out** ("play on TV"), deinterlace, smart `S01E02` show/season grouping,
  because-you-watched rows — depth on the player & discovery moat.

### Scale & cost-control (when load demands it — not before)

Today's hosted stack is **one small box + SQLite + Litestream→R2** for the control-plane, cheap
brokers behind a sticky LB for signaling, and a separately-capped coturn relay (built — see
[cloud/README.md](../cloud/README.md) "Scale & cost control"). Premature Kubernetes/Terraform is
the expensive mistake here; the documented cutovers, each gated on a concrete signal:

- **Signaling:** scale *out* — more cheap brokers behind sticky-by-node-id routing (zero shared
  state). A Redis/Postgres `LISTEN/NOTIFY` bus only if one box can't hold the long-poll fan-out.
- **Control-plane:** stay one instance until a real signal (e.g. p95 latency, or ~5,000 tenants),
  then SQLite → managed Postgres behind the same `db.py` interface + N round-robin instances.
  Sessions are already in-DB and webhooks idempotent, so it's config, not a rewrite.
- **Relay:** scale *vertically* (bigger NIC) before horizontally — each relay is independently
  capped, and per-plan caps + a fleet budget alert keep the only real egress cost bounded.

---

## Open decisions (settle before scaling spend)

1. **Licensing** — keep **MIT**, move the core to **AGPL-3.0**, or **open-core** (AGPL/MIT core +
   the `cloud/` control-plane proprietary). MIT lets a competitor host a rival; AGPL or open-core
   defends the hosting business. Also: monorepo vs two repos, a CLA, and a "Kadmu" trademark.
2. **Pricing shape** — confirm the $5/mo · $50/yr placeholders and the 100 GB/mo · 720p relay
   caps; decide on a paid "relay-plus" add-on vs BYO-relay only.
3. **Metadata (TMDB)** — ship the first opt-in outbound call? (Default-off philosophy change.)
4. **TURN provider** — self-hosted coturn (cheapest, what we built) vs managed TURN.
5. **License token TTL / grace** — currently 24 h / 7-day; balance revocation speed vs load.
6. **Control-plane cutover trigger** — pick the concrete signal (p95 latency or tenant count) so
   the Postgres + multi-instance move isn't decided on vibes.
