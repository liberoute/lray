"""
Smart Router — automatically decides the best route for each host.

Routes:
  - direct: connect directly (fastest, but only works for unblocked sites)
  - relay: go through GAS relay (slower, but bypasses censorship)
  - forwarder: go through upstream forwarder (stable IP, fixes CAPTCHA)

Decision logic:
  1. If host is in bypass_hosts → always direct
  2. If host is in block_hosts → always blocked
  3. If host was recently tested direct and succeeded → direct
  4. If host was recently tested direct and failed → relay
  5. If unknown → try direct first (with short timeout), remember result

The router learns over time which hosts are blocked and which aren't,
so after a few minutes of use, routing is optimal.

Persistence:
  Routes are cached to `routing_cache.json` so restarts don't lose
  learned data. The cache is saved periodically and on shutdown.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("Router")


@dataclass
class _HostRecord:
    """Routing record for a single host."""
    route: str = "unknown"  # "direct", "relay", "forwarder", "unknown"
    direct_ok: int = 0
    direct_fail: int = 0
    relay_ok: int = 0
    last_direct_attempt: float = 0.0
    last_direct_success: float = 0.0
    last_direct_fail: float = 0.0
    avg_direct_latency_ms: float = 0.0
    avg_relay_latency_ms: float = 0.0
    _direct_latencies: list = field(default_factory=list)
    _relay_latencies: list = field(default_factory=list)


# How long to remember a direct failure before retrying
_DIRECT_FAIL_TTL = 300.0  # 5 minutes
# How long to trust a direct success before re-probing
_DIRECT_SUCCESS_TTL = 600.0  # 10 minutes
# Max latency samples to keep per host
_MAX_SAMPLES = 20
# Direct attempt timeout (short — if it doesn't connect fast, it's blocked)
DIRECT_PROBE_TIMEOUT = 3.0
# How often to save cache (seconds)
_SAVE_INTERVAL = 60.0
# Cache file name
_CACHE_FILE = "routing_cache.json"


class SmartRouter:
    """Learns which hosts are accessible directly and routes accordingly."""

    def __init__(self, config: dict, data_dir: str = "."):
        self._records: dict[str, _HostRecord] = {}
        self._enabled = config.get("smart_routing", False)
        self._data_dir = Path(data_dir)
        self._cache_path = self._data_dir / _CACHE_FILE
        self._dirty = False
        self._last_save: float = 0
        # Hosts that should always go through forwarder (CAPTCHA-protected)
        self._forwarder_hosts = self._load_rules(config.get("forwarder_hosts", []))
        self._bypass_hosts = self._load_rules(config.get("bypass_hosts", []))

        # Load cached routes on init
        self._load_cache()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _load_rules(raw) -> tuple[set[str], tuple[str, ...]]:
        exact: set[str] = set()
        suffixes: list[str] = []
        for item in raw or []:
            h = str(item).strip().lower().rstrip(".")
            if not h:
                continue
            if h.startswith("."):
                suffixes.append(h)
            else:
                exact.add(h)
        return exact, tuple(suffixes)

    @staticmethod
    def _matches(host: str, rules: tuple[set[str], tuple[str, ...]]) -> bool:
        exact, suffixes = rules
        h = host.lower().rstrip(".")
        if h in exact:
            return True
        return any(h.endswith(s) for s in suffixes)

    def get_route(self, host: str) -> str:
        """Get the recommended route for a host.

        Returns: "direct", "relay", "forwarder", or "probe"
          - "probe" means try direct first with short timeout
        """
        if not self._enabled:
            return "relay"  # default behavior when smart routing is off

        h = host.lower().rstrip(".")

        # Forwarder hosts always go through forwarder
        if self._matches(h, self._forwarder_hosts):
            return "forwarder"

        # Bypass hosts always direct
        if self._matches(h, self._bypass_hosts):
            return "direct"

        record = self._records.get(h)
        if not record:
            return "probe"  # unknown — try direct first

        now = time.time()

        # If direct recently failed, use relay
        if record.last_direct_fail > 0:
            if now - record.last_direct_fail < _DIRECT_FAIL_TTL:
                return "relay"

        # If direct recently succeeded, use direct
        if record.last_direct_success > 0:
            if now - record.last_direct_success < _DIRECT_SUCCESS_TTL:
                return "direct"

        # Stale data — re-probe
        return "probe"

    def record_direct_success(self, host: str, latency_ms: float = 0):
        """Record a successful direct connection."""
        h = host.lower().rstrip(".")
        record = self._records.setdefault(h, _HostRecord())
        record.route = "direct"
        record.direct_ok += 1
        record.last_direct_success = time.time()
        record.last_direct_attempt = time.time()
        if latency_ms > 0:
            record._direct_latencies.append(latency_ms)
            if len(record._direct_latencies) > _MAX_SAMPLES:
                record._direct_latencies = record._direct_latencies[-_MAX_SAMPLES:]
            record.avg_direct_latency_ms = sum(record._direct_latencies) / len(record._direct_latencies)
        self._mark_dirty()

    def record_direct_failure(self, host: str):
        """Record a failed direct connection."""
        h = host.lower().rstrip(".")
        record = self._records.setdefault(h, _HostRecord())
        record.route = "relay"
        record.direct_fail += 1
        record.last_direct_fail = time.time()
        record.last_direct_attempt = time.time()
        self._mark_dirty()

    def record_relay_success(self, host: str, latency_ms: float = 0):
        """Record a successful relay."""
        h = host.lower().rstrip(".")
        record = self._records.setdefault(h, _HostRecord())
        record.relay_ok += 1
        if latency_ms > 0:
            record._relay_latencies.append(latency_ms)
            if len(record._relay_latencies) > _MAX_SAMPLES:
                record._relay_latencies = record._relay_latencies[-_MAX_SAMPLES:]
            record.avg_relay_latency_ms = sum(record._relay_latencies) / len(record._relay_latencies)

    def get_stats(self) -> dict:
        """Return routing stats for dashboard."""
        direct_hosts = sum(1 for r in self._records.values() if r.route == "direct")
        relay_hosts = sum(1 for r in self._records.values() if r.route == "relay")
        return {
            "enabled": self._enabled,
            "total_hosts_learned": len(self._records),
            "direct_hosts": direct_hosts,
            "relay_hosts": relay_hosts,
            "top_direct": [
                {"host": h, "latency_ms": round(r.avg_direct_latency_ms)}
                for h, r in sorted(
                    self._records.items(),
                    key=lambda x: x[1].direct_ok, reverse=True
                )[:10]
                if r.route == "direct"
            ],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _mark_dirty(self):
        """Mark cache as needing save. Auto-saves if interval passed."""
        self._dirty = True
        now = time.time()
        if now - self._last_save > _SAVE_INTERVAL:
            self.save_cache()

    def _load_cache(self):
        """Load routing cache from disk."""
        try:
            if not self._cache_path.exists():
                return
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            now = time.time()
            loaded = 0
            for host, entry in data.items():
                record = _HostRecord(
                    route=entry.get("route", "unknown"),
                    direct_ok=entry.get("direct_ok", 0),
                    direct_fail=entry.get("direct_fail", 0),
                    relay_ok=entry.get("relay_ok", 0),
                    last_direct_success=entry.get("last_direct_success", 0),
                    last_direct_fail=entry.get("last_direct_fail", 0),
                    last_direct_attempt=entry.get("last_direct_attempt", 0),
                    avg_direct_latency_ms=entry.get("avg_direct_latency_ms", 0),
                    avg_relay_latency_ms=entry.get("avg_relay_latency_ms", 0),
                )
                # Skip entries older than 24 hours
                last_activity = max(record.last_direct_success, record.last_direct_fail)
                if last_activity > 0 and (now - last_activity) > 86400:
                    continue
                self._records[host] = record
                loaded += 1
            if loaded:
                log.info("Loaded %d cached routes from %s", loaded, _CACHE_FILE)
        except Exception as e:
            log.debug("Failed to load routing cache: %s", e)

    def save_cache(self):
        """Save routing cache to disk."""
        if not self._dirty and self._last_save > 0:
            return
        try:
            now = time.time()
            data = {}
            for host, record in self._records.items():
                # Only save hosts with meaningful data
                if record.direct_ok == 0 and record.direct_fail == 0:
                    continue
                # Skip stale entries (older than 24h)
                last_activity = max(record.last_direct_success, record.last_direct_fail)
                if last_activity > 0 and (now - last_activity) > 86400:
                    continue
                data[host] = {
                    "route": record.route,
                    "direct_ok": record.direct_ok,
                    "direct_fail": record.direct_fail,
                    "relay_ok": record.relay_ok,
                    "last_direct_success": record.last_direct_success,
                    "last_direct_fail": record.last_direct_fail,
                    "last_direct_attempt": record.last_direct_attempt,
                    "avg_direct_latency_ms": round(record.avg_direct_latency_ms, 1),
                    "avg_relay_latency_ms": round(record.avg_relay_latency_ms, 1),
                }

            # Cap at 5000 entries — keep most recently active
            if len(data) > 5000:
                sorted_hosts = sorted(
                    data.items(),
                    key=lambda x: max(x[1]["last_direct_success"], x[1]["last_direct_fail"]),
                    reverse=True,
                )
                data = dict(sorted_hosts[:5000])

            self._cache_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
            self._last_save = time.time()
            log.debug("Saved %d routes to %s", len(data), _CACHE_FILE)
        except Exception as e:
            log.debug("Failed to save routing cache: %s", e)
