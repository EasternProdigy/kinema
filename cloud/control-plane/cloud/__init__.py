"""Kadmu Cloud control-plane — the *hosted* layer (NOT shipped to self-hosters).

This package powers Kadmu Cloud only: marketing/landing, pay-first signup, Stripe
billing, the entitlement/license service the local node validates against, and
donations for the open-source side. The open-source node (``src/kadmu/``) never
imports this; it only talks to it over HTTP as a Cloud tenant.

Like the core, it is **Python standard library only** — Stripe is reached over its
REST API with ``urllib`` (no SDK), and it ships with a **mock mode** so the whole
signup → checkout → webhook → license flow runs end-to-end with no Stripe keys.
See ``cloud/README.md``.

Module layout (dependencies point downward, no cycles):

| module        | responsibility |
|---------------|----------------|
| ``const``     | config from env, paths, plan/pricing catalog, mock-mode flag |
| ``db``        | the SQLite store: accounts, sessions, subscriptions, tenants, donations, webhook log |
| ``accounts``  | cloud-customer accounts + persistent sessions (PBKDF2-HMAC-SHA256) |
| ``stripe_client`` | Stripe REST over urllib + webhook signature verify + the mock simulator |
| ``licensing`` | sign the HS256 license tokens a tenant's node fetches and verifies |
| ``entitlements`` | subscription state → entitlement, and tenant provisioning |
| ``handler``   | the one BaseHTTPRequestHandler subclass and its routes |
| ``app``       | the threaded server + ``main()`` |
"""
