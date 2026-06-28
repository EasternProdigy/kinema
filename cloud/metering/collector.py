"""The usage collector — turns coturn's Prometheus counters into per-tenant relay bytes.

coturn exposes cumulative traffic counters on its Prometheus endpoint (default ``:9641``).
This polls that endpoint, diffs the byte counters since the last scrape, recovers the tenant
from the TURN username label (``<exp>:<tenant>`` — see turncreds), and feeds the delta to the
``Meter``. Cheapest usage source per the design (§2.3): no Redis, no per-session callbacks.

Run it next to coturn (see cloud/relay/docker-compose.yml):
    COTURN_METRICS_URL=http://127.0.0.1:9641/metrics \
    KADMU_METER_DB=/data/cloud.db \
    python3 cloud/metering/collector.py

stdlib only. The Prometheus text parser and the diff/attribution logic are unit-tested
(cloud/metering/tests/test_collector.py); the live coturn label shape is the one thing that
varies by coturn build/config, so the label key is env-tunable (``KADMU_TURN_LABEL``).
"""
from __future__ import annotations
import os
import re
import sys
import time
import urllib.request

# Allow `import metering...` whether run as a module or a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from metering.meter import Meter          # noqa: E402
from metering import turncreds            # noqa: E402

# coturn byte counters we sum for the egress budget (both directions traverse our relay).
BYTE_METRICS = ("turn_traffic_sentb", "turn_traffic_rcvb",
                "turn_traffic_peer_sentb", "turn_traffic_peer_rcvb")
# Which label carries the TURN username (varies by coturn build/config).
LABEL_CANDIDATES = ("user", "username")

_LINE = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?P<labels>\{[^}]*\})?\s+(?P<val>[-+0-9.eE]+)\s*$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse_prometheus(text):
    """Parse a Prometheus text exposition into ``[(name, {labels}, value), …]``, skipping
    comments and unparseable lines. Tolerant by design — coturn's output is the input."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        labels = {}
        if m.group("labels"):
            for k, v in _LABEL.findall(m.group("labels")):
                labels[k] = v.replace('\\"', '"').replace("\\\\", "\\")
        try:
            val = float(m.group("val"))
        except ValueError:
            continue
        out.append((m.group("name"), labels, val))
    return out


class Collector:
    def __init__(self, meter, label_candidates=LABEL_CANDIDATES, byte_metrics=BYTE_METRICS):
        self.meter = meter
        self.label_candidates = tuple(label_candidates)
        self.byte_metrics = set(byte_metrics)
        self._last = {}                    # (metric, username) -> last cumulative value
        self._seen_sessions = set()        # usernames counted as a session this run

    def _username(self, labels):
        for key in self.label_candidates:
            if labels.get(key):
                return labels[key]
        return None

    def ingest(self, text, now):
        """Diff one scrape against the previous one and record per-tenant byte deltas.
        Returns the total bytes recorded this round (handy for logs/tests)."""
        recorded = 0
        for name, labels, val in parse_prometheus(text):
            if name not in self.byte_metrics:
                continue
            username = self._username(labels)
            tenant = turncreds.parse_tenant(username) if username else None
            if not tenant:
                continue                   # can't attribute — skip rather than mis-bill
            key = (name, username)
            prev = self._last.get(key)
            self._last[key] = val
            if prev is None:
                continue                   # first sight of this series — establish a baseline only
            delta = val - prev
            if delta < 0:                  # counter reset (coturn restart) — count from zero
                delta = val
            if delta <= 0:
                continue
            new_session = 1 if username not in self._seen_sessions else 0
            self._seen_sessions.add(username)
            self.meter.record(tenant, int(delta), now, delta_sessions=new_session)
            recorded += int(delta)
        return recorded


def scrape(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def main():
    url = os.environ.get("COTURN_METRICS_URL", "http://127.0.0.1:9641/metrics")
    db = os.environ.get("KADMU_METER_DB", "/data/cloud.db")
    interval = max(5, int(os.environ.get("KADMU_METER_INTERVAL", "30")))
    meter = Meter(db)
    collector = Collector(meter)
    print(f"metering collector: scraping {url} every {interval}s → {db}", flush=True)
    while True:
        now = time.time()
        try:
            recorded = collector.ingest(scrape(url), now)
            if recorded:
                print(f"recorded {recorded} relay bytes", flush=True)
        except Exception as e:             # a relay blip shouldn't kill the collector
            print(f"scrape error: {e}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
