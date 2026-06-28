# Kadmu Cloud — infra (`cloud/infra/`)

Deployment + operations for the hosted control-plane. Fleshing this out is **Phase 5**
(scale & cost control); for now it holds the minimum to run the Phase 4a control-plane
behind HTTPS, since the control-plane itself is plain HTTP (no TLS, like the core node).

## Reverse proxy (HTTPS)

The control-plane speaks HTTP on `KADMU_CLOUD_PORT`. Terminate TLS in front of it.
[`Caddyfile.example`](Caddyfile.example) is a complete, auto-HTTPS starting point:

```bash
caddy run --config cloud/infra/Caddyfile.example --adapter caddyfile
```

Set the control-plane's `KADMU_CLOUD_BASE_URL` to the public `https://` origin so Stripe
redirects and dashboard links are correct.

## Stripe webhook

Point a Stripe webhook endpoint at `https://<your-domain>/api/webhook/stripe` and copy
its signing secret into `STRIPE_WEBHOOK_SECRET`. Subscribe to: `checkout.session.completed`,
`customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`.

## Still to come (Phase 5)

Horizontal scale of the (stateless) control-plane behind a shared DB, a CDN for the
static app shell, structured logging/metrics, and — once Phase 4b lands — signaling/relay
capacity planning with per-plan caps so the hostile-NAT relay minority can't blow the budget.
