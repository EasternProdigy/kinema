"""Phase 5 seam in the control-plane: mint entitlement-bound TURN credentials and expose
relay metering metrics.

This is the adapter the design's §6.1 contract names. It imports the standalone
``cloud/metering/`` package (by putting the repo's ``cloud/`` dir on the path — the same trick
the connector uses to import ``wire``) so the cap logic lives in one tested place. The metering
store is the **same** ``cloud.db`` the control-plane already backs up (PHASE_5_DESIGN §10.2),
so there's a single DB and a single Litestream→R2 backup.

Flow (``GET /api/relay-credentials``): caller is identified (dashboard session *or* tenant
proof) → resolve its active subscription → ``meter.allowed(tenant, plan)`` → if yes, mint a
short-TTL coturn credential and return an ``iceServers`` list; if no, return ``{relay: false,
reason}`` and the browser stays P2P-only.
"""
from __future__ import annotations
import os
import sys

from . import const, entitlements

# Make `import metering` resolve to cloud/metering/ (this file is cloud/control-plane/cloud/…).
_CLOUD_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _CLOUD_DIR not in sys.path:
    sys.path.insert(0, _CLOUD_DIR)
from metering import turncreds          # noqa: E402
from metering.meter import Meter         # noqa: E402

_meter = None


def plan_of(tenant_id):
    """tenant id → its plan id (or None) via the owning account's active subscription —
    used by the metering metrics/over-cap accounting."""
    row = entitlements.get_tenant(tenant_id)
    if row is None:
        return None
    sub = entitlements.active_subscription(row["account_id"])
    return sub["plan"] if sub else None


def meter():
    """The process-wide Meter, bound to the shared control-plane DB."""
    global _meter
    if _meter is None:
        _meter = Meter(str(const.DB_PATH), plan_caps=const.PLAN_RELAY_CAPS, plan_of=plan_of)
    return _meter


def relay_credentials(tenant_id, plan, now):
    """Decide + (maybe) mint. Returns a JSON-able dict for the endpoint.

    ``{relay: true, iceServers: [...], ttl}`` when the plan grants relay and the tenant is
    under its monthly cap; otherwise ``{relay: false, reason, iceServers: [STUN only]}`` so the
    browser can still attempt direct P2P (relay is the fallback, not the default).
    """
    stun_only, _ = turncreds.ice_servers(tenant_id, "", [], now, stun_urls=const.STUN_URLS)
    if not const.TURN_URLS or not const.TURN_SECRET:
        # No relay configured on this deployment → STUN-only, honestly reported.
        return {"relay": False, "reason": "relay-not-configured", "iceServers": stun_only,
                "ttl": const.RELAY_CRED_TTL}
    ok, reason = meter().allowed(tenant_id, plan, now)
    if not ok:
        return {"relay": False, "reason": reason, "iceServers": stun_only,
                "ttl": const.RELAY_CRED_TTL}
    servers, expiry = turncreds.ice_servers(
        tenant_id, const.TURN_SECRET, const.TURN_URLS, now,
        ttl=const.RELAY_CRED_TTL, stun_urls=const.STUN_URLS)
    return {"relay": True, "iceServers": servers, "ttl": const.RELAY_CRED_TTL,
            "expires": expiry,
            "maxHeight": (const.PLANS.get(plan) or {}).get("relay_max_height", 720)}


def metrics_text(now):
    """Prometheus exposition for the control-plane: relay metering (from the Meter) plus a few
    control-plane gauges. Scraped by cloud/infra/observability."""
    from .db import db
    parts = [meter().render_metrics(now)]
    try:
        c = db()
        accounts_n = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
        tenants_n = c.execute("SELECT COUNT(*) n FROM tenants").fetchone()["n"]
        subs_active = c.execute(
            "SELECT COUNT(*) n FROM subscriptions WHERE status IN ('active','trialing')"
        ).fetchone()["n"]
        parts.append(
            "# HELP kadmu_cloud_accounts_total Cloud accounts.\n"
            "# TYPE kadmu_cloud_accounts_total gauge\n"
            f"kadmu_cloud_accounts_total {accounts_n}\n"
            "# HELP kadmu_cloud_tenants_total Provisioned tenants (self-host nodes).\n"
            "# TYPE kadmu_cloud_tenants_total gauge\n"
            f"kadmu_cloud_tenants_total {tenants_n}\n"
            "# HELP kadmu_cloud_subscriptions_active Active/trialing subscriptions.\n"
            "# TYPE kadmu_cloud_subscriptions_active gauge\n"
            f"kadmu_cloud_subscriptions_active {subs_active}\n")
    except Exception:
        pass
    return "".join(parts)
