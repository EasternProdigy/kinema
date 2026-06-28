"""Unit tests for the Phase 5 metering core — the cost guardrail.

stdlib unittest, no network, no coturn. Run:
    python3 -m unittest discover -s cloud/metering/tests
or:
    python3 cloud/metering/tests/test_metering.py
"""
import os
import sys
import tempfile
import unittest

# Make `import metering...` work however this file is invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from metering import caps, turncreds          # noqa: E402
from metering.meter import Meter               # noqa: E402
from metering.store import MeterStore          # noqa: E402
from metering.collector import Collector, parse_prometheus  # noqa: E402

GiB = 1024 ** 3
T0 = 1_750_000_000          # a fixed unix time inside one month, for determinism


def _tmpdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


class TurnCredsTests(unittest.TestCase):
    def test_roundtrip_and_format(self):
        user, pw, exp = turncreds.make_credential("ten_abc", "s3cr3t", T0, ttl=120)
        self.assertEqual(exp, T0 + 120)
        self.assertEqual(user, f"{T0 + 120}:ten_abc")
        self.assertEqual(turncreds.parse_tenant(user), "ten_abc")
        self.assertTrue(turncreds.verify(user, pw, "s3cr3t", T0))

    def test_wrong_secret_and_expiry(self):
        user, pw, _ = turncreds.make_credential("ten_abc", "s3cr3t", T0, ttl=120)
        self.assertFalse(turncreds.verify(user, pw, "other", T0))          # bad secret
        self.assertFalse(turncreds.verify(user, pw, "s3cr3t", T0 + 999))   # expired
        self.assertIsNone(turncreds.parse_tenant("garbage"))
        self.assertIsNone(turncreds.parse_tenant("notanum:ten"))

    def test_requires_secret(self):
        with self.assertRaises(ValueError):
            turncreds.make_credential("ten_abc", "", T0)

    def test_ice_servers_has_stun_and_turn(self):
        servers, exp = turncreds.ice_servers("ten_x", "sec", ["turn:turn.example:3478"], T0, ttl=60)
        self.assertEqual(exp, T0 + 60)
        self.assertTrue(any("stun:" in s["urls"] for s in servers if isinstance(s["urls"], str)))
        turn = [s for s in servers if isinstance(s.get("urls"), list)]
        self.assertEqual(len(turn), 1)
        self.assertIn("username", turn[0])
        self.assertIn("credential", turn[0])

    def test_ice_servers_stun_only_without_turn(self):
        servers, _ = turncreds.ice_servers("ten_x", "", [], T0)
        self.assertTrue(all("username" not in s for s in servers))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmpdb()
        self.store = MeterStore(self.path).init()

    def tearDown(self):
        os.unlink(self.path)

    def test_add_accumulates(self):
        p = caps.period_for(T0)
        self.store.add("ten_a", p, 1000, T0, delta_sessions=1)
        self.store.add("ten_a", p, 500, T0 + 1)
        self.assertEqual(self.store.bytes_this_period("ten_a", p), 1500)

    def test_periods_isolated(self):
        self.store.add("ten_a", "2026-01", 10, T0)
        self.store.add("ten_a", "2026-02", 20, T0)
        self.assertEqual(self.store.bytes_this_period("ten_a", "2026-01"), 10)
        self.assertEqual(self.store.bytes_this_period("ten_a", "2026-02"), 20)

    def test_totals(self):
        p = caps.period_for(T0)
        self.store.add("ten_a", p, 100, T0, delta_sessions=1)
        self.store.add("ten_b", p, 200, T0, delta_sessions=2)
        b, s, n = self.store.totals_for_period(p)
        self.assertEqual((b, s, n), (300, 3, 2))

    def test_init_idempotent_and_shared_db_safe(self):
        # Calling init twice, and on a fresh handle to the same file, must not error.
        self.store.init()
        MeterStore(self.path).init()
        self.assertEqual(self.store.bytes_this_period("nobody", caps.period_for(T0)), 0)


class CapsTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmpdb()
        self.store = MeterStore(self.path).init()

    def tearDown(self):
        os.unlink(self.path)

    def test_under_cap_allowed(self):
        ok, reason = caps.relay_allowed("ten_a", "monthly", self.store, T0)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_plan_without_relay_denied(self):
        ok, reason = caps.relay_allowed("ten_a", "free", self.store, T0)
        self.assertFalse(ok)
        self.assertEqual(reason, "plan-no-relay")

    def test_at_cap_denied(self):
        p = caps.period_for(T0)
        self.store.add("ten_a", p, 100 * GiB, T0)        # exactly at the monthly cap
        ok, reason = caps.relay_allowed("ten_a", "monthly", self.store, T0)
        self.assertFalse(ok)
        self.assertEqual(reason, "cap-reached")

    def test_just_under_cap_allowed(self):
        p = caps.period_for(T0)
        self.store.add("ten_a", p, 100 * GiB - 1, T0)
        ok, _ = caps.relay_allowed("ten_a", "monthly", self.store, T0)
        self.assertTrue(ok)

    def test_plan_caps_override(self):
        p = caps.period_for(T0)
        self.store.add("ten_a", p, 5 * GiB, T0)
        # control-plane override: monthly cap lowered to 1 GiB → now over cap
        ok, reason = caps.relay_allowed("ten_a", "monthly", self.store, T0,
                                        plan_caps={"monthly": 1 * GiB})
        self.assertFalse(ok)
        self.assertEqual(reason, "cap-reached")

    def test_over_cap_tenants_count(self):
        p = caps.period_for(T0)
        self.store.add("rich", p, 200 * GiB, T0)         # over
        self.store.add("light", p, 1 * GiB, T0)          # under
        plan_of = lambda t: "monthly"                    # noqa: E731
        self.assertEqual(caps.over_cap_tenants(self.store, T0, plan_of), 1)


class MeterAndMetricsTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmpdb()

    def tearDown(self):
        os.unlink(self.path)

    def test_render_metrics_groups_by_plan(self):
        meter = Meter(self.path, plan_of=lambda t: {"a": "monthly", "b": "yearly"}.get(t, "unknown"))
        meter.record("a", 10 * GiB, T0, delta_sessions=1)
        meter.record("b", 20 * GiB, T0, delta_sessions=1)
        text = meter.render_metrics(T0)
        self.assertIn('kadmu_relay_bytes_total{plan="monthly"} %d' % (10 * GiB), text)
        self.assertIn('kadmu_relay_bytes_total{plan="yearly"} %d' % (20 * GiB), text)
        self.assertIn("kadmu_relay_sessions_active 2", text)
        self.assertIn("kadmu_relay_tenants_total 2", text)

    def test_allowed_via_meter(self):
        meter = Meter(self.path)
        ok, _ = meter.allowed("ten_a", "monthly", T0)
        self.assertTrue(ok)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.path = _tmpdb()
        self.meter = Meter(self.path)
        self.collector = Collector(self.meter)

    def tearDown(self):
        os.unlink(self.path)

    def _expo(self, sentb, rcvb, user):
        return (f'turn_traffic_sentb{{realm="kadmu",user="{user}"}} {sentb}\n'
                f'turn_traffic_rcvb{{realm="kadmu",user="{user}"}} {rcvb}\n'
                '# a comment\n'
                'turn_total_allocations 3\n')

    def test_parse_prometheus(self):
        rows = parse_prometheus(self._expo(100, 50, "1750000120:ten_a"))
        names = {r[0] for r in rows}
        self.assertIn("turn_traffic_sentb", names)
        self.assertIn("turn_total_allocations", names)

    def test_diff_attribution(self):
        user = f"{T0 + 120}:ten_a"
        # First scrape establishes a baseline (no recording).
        self.assertEqual(self.collector.ingest(self._expo(1000, 500, user), T0), 0)
        # Second scrape: deltas 200 + 100 = 300 attributed to ten_a.
        rec = self.collector.ingest(self._expo(1200, 600, user), T0 + 30)
        self.assertEqual(rec, 300)
        self.assertEqual(self.meter.store.bytes_this_period("ten_a", caps.period_for(T0)), 300)

    def test_counter_reset_counts_from_zero(self):
        user = f"{T0 + 120}:ten_a"
        self.collector.ingest(self._expo(1000, 0, user), T0)
        # coturn restarted → counter dropped; the new value is the delta.
        rec = self.collector.ingest(self._expo(40, 0, user), T0 + 30)
        self.assertEqual(rec, 40)

    def test_unattributable_skipped(self):
        # No parseable tenant in the username → not billed to anyone.
        rec = self.collector.ingest(
            'turn_traffic_sentb{realm="kadmu",user="garbage"} 999\n', T0)
        self.assertEqual(rec, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
