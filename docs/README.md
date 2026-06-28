# Kadmu docs

The map of the project's documentation. Start here.

## Using & self-hosting Kadmu
- **[../README.md](../README.md)** — what Kadmu is, quick start, features, CLI options.
- **[SECURITY.md](SECURITY.md)** — the threat model and the localhost/LAN security posture.
- **[../deploy/README.md](../deploy/README.md)** — run it in Docker (the public read-only demo, or your own library).
- **[BRAND.md](BRAND.md)** — the brand source of truth (colors, type, voice). Visual deck: [brand/kadmu-brand-guidelines.html](brand/kadmu-brand-guidelines.html).

## Project history & direction
- **[CHANGELOG.md](CHANGELOG.md)** — what has shipped (the record of done work).
- **[ROADMAP.md](ROADMAP.md)** — the vision, the open-core business/cost model, and **what's next** (future plans + open decisions).

## Contributing
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to build, check, and submit changes.
- **[../CLAUDE.md](../CLAUDE.md)** — the architecture guide: how the backend package and the frontend scripts fit together (for humans and agents working in the code).
- **[NOTICE.md](NOTICE.md)** — third-party attributions.

## The hosted edition — "Kadmu Cloud" (optional; NOT needed to self-host)
- **[../cloud/README.md](../cloud/README.md)** — the hosted layer: control-plane (billing/accounts/licensing), P2P remote, and scale & cost control.
- **[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)** — the step-by-step punch list to take Kadmu Cloud live (accounts, DNS, secrets, deploy).
- Per-service runbooks: **[../cloud/relay/README.md](../cloud/relay/README.md)** (coturn relay) ·
  **[../cloud/infra/README.md](../cloud/infra/README.md)** (Caddy/Compose/scale) ·
  **[../cloud/infra/cdn/README.md](../cloud/infra/cdn/README.md)** (CDN) ·
  **[../cloud/infra/observability/README.md](../cloud/infra/observability/README.md)** (Prometheus/Grafana).

---

*Tip: "what's done" → CHANGELOG · "where it's going" → ROADMAP · "how to ship the cloud" → LAUNCH_CHECKLIST.*
