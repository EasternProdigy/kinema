"""Per-plan relay caps and the allow/deny decision — the cost guardrail.

This is the rule the control-plane consults inside ``GET /api/relay-credentials`` before
minting a TURN credential. No credential ⇒ no relay allocation, so denying here is what keeps
relay egress from ever blowing the budget (docs/PHASE_5_DESIGN.md §2).

The caps below are the design's starting points (§2.4); the control-plane can override them
from its plan catalog (``PLANS[plan]["relay_cap_bytes"]``) so pricing changes don't need a
metering deploy. Quality is capped *separately* by the connector (``RELAY_MAX_HEIGHT``) so a
relayed stream is ≤720p — together they bound worst-case egress per tenant.
"""
from __future__ import annotations

GiB = 1024 ** 3

# Starting-point caps (overridable per-plan by the control-plane). 0 ⇒ the plan has no relay.
PLAN_RELAY_CAP_BYTES = {
    "monthly": 100 * GiB,        # ~90 hours of ≤720p relayed viewing / month
    "yearly":  100 * GiB,
    # a future "relay-plus" add-on or BYO-relay would add a higher / unlimited entry
}

RELAY_MAX_HEIGHT = 720           # quality ceiling the connector enforces on a relay candidate pair


def period_for(now):
    """The 'YYYY-MM' billing month for a unix timestamp. Passed-in time keeps callers pure
    and testable; uses UTC so a tenant's month boundary doesn't depend on server locale."""
    import time
    return time.strftime("%Y-%m", time.gmtime(now))


def cap_for(plan, plan_caps=None):
    """The monthly relay-byte cap for ``plan``. ``plan_caps`` (optional) is the control-plane's
    override map (plan id → cap bytes); falls back to ``PLAN_RELAY_CAP_BYTES``."""
    if plan_caps and plan in plan_caps:
        return int(plan_caps[plan] or 0)
    return int(PLAN_RELAY_CAP_BYTES.get(plan, 0))


def relay_allowed(tenant, plan, store, now, plan_caps=None):
    """``(allowed: bool, reason: str|None)``.

    Denies when: the plan grants no relay, or the tenant is already at/over its monthly cap.
    ``store`` is a ``MeterStore``; ``now`` a unix timestamp (the billing period is derived
    from it). The control-plane has already confirmed an *active subscription* before calling
    this — caps are the second gate, not the first.
    """
    cap = cap_for(plan, plan_caps)
    if cap <= 0:
        return False, "plan-no-relay"
    used = store.bytes_this_period(tenant, period_for(now))
    if used >= cap:
        return False, "cap-reached"
    return True, None


def over_cap_tenants(store, now, plan_of, plan_caps=None):
    """Count tenants at/over their cap this period — feeds ``kadmu_relay_tenants_over_cap``.
    ``plan_of`` maps a tenant id → its plan id (the control-plane supplies it); a tenant with
    no known plan is treated as cap 0 (no relay) and only counts as over-cap if it has usage."""
    period = period_for(now)
    n = 0
    for row in store.rows_for_period(period):
        cap = cap_for(plan_of(row["tenant"]) if plan_of else None, plan_caps)
        if cap <= 0:
            if int(row["bytes"]) > 0:
                n += 1
        elif int(row["bytes"]) >= cap:
            n += 1
    return n
