"""The metering façade — ties the store + caps together and renders Prometheus metrics.

A control-plane creates one ``Meter`` (pointed at the shared ``cloud.db``) and uses it for
both the relay decision (``allowed``) and recording (``record``); the collector uses the same
``record`` to attribute coturn bytes. The Prometheus output (``render_metrics``) is what
``cloud/infra/observability`` scrapes and what the §2.5 budget alert fires on.
"""
from __future__ import annotations

from . import caps
from .store import MeterStore


class Meter:
    def __init__(self, db_path, plan_caps=None, plan_of=None):
        self.store = MeterStore(db_path).init()
        self.plan_caps = plan_caps          # {plan_id: cap_bytes} override from the control-plane catalog
        self._plan_of = plan_of             # callable: tenant_id -> plan_id (for over-cap accounting)

    # ----- decision + recording ------------------------------------------ #
    def allowed(self, tenant, plan, now):
        return caps.relay_allowed(tenant, plan, self.store, now, self.plan_caps)

    def record(self, tenant, delta_bytes, now, delta_sessions=0):
        """Attribute relayed bytes (and optionally a new session) to a tenant's current period."""
        self.store.add(tenant, caps.period_for(now), delta_bytes, now, delta_sessions)

    # ----- metrics (Prometheus text exposition) -------------------------- #
    def render_metrics(self, now):
        period = caps.period_for(now)
        rows = self.store.rows_for_period(period)
        bytes_by_plan = {}
        sessions = 0
        for r in rows:
            plan = (self._plan_of(r["tenant"]) if self._plan_of else None) or "unknown"
            bytes_by_plan[plan] = bytes_by_plan.get(plan, 0) + int(r["bytes"])
            sessions += int(r["sessions"])
        over = caps.over_cap_tenants(self.store, now, self._plan_of, self.plan_caps)

        out = []
        out.append("# HELP kadmu_relay_bytes_total Relayed bytes attributed this billing period.")
        out.append("# TYPE kadmu_relay_bytes_total counter")
        if bytes_by_plan:
            for plan, b in sorted(bytes_by_plan.items()):
                out.append(f'kadmu_relay_bytes_total{{plan="{plan}"}} {b}')
        else:
            out.append('kadmu_relay_bytes_total{plan="none"} 0')
        out.append("# HELP kadmu_relay_tenants_over_cap Tenants at or over their relay cap this period.")
        out.append("# TYPE kadmu_relay_tenants_over_cap gauge")
        out.append(f"kadmu_relay_tenants_over_cap {over}")
        out.append("# HELP kadmu_relay_sessions_active Relay sessions recorded this period.")
        out.append("# TYPE kadmu_relay_sessions_active gauge")
        out.append(f"kadmu_relay_sessions_active {sessions}")
        out.append("# HELP kadmu_relay_tenants_total Tenants with any relay usage this period.")
        out.append("# TYPE kadmu_relay_tenants_total gauge")
        out.append(f"kadmu_relay_tenants_total {len(rows)}")
        return "\n".join(out) + "\n"
