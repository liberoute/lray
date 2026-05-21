"""
Smart Router — rule-based routing for each host.

Routes:
  - direct: connect directly (fastest, for unblocked sites)
  - relay: go through GAS relay (bypasses censorship)
  - forwarder: go through upstream forwarder (stable IP, fixes CAPTCHA)

Decision logic (config-driven, no probing):
  1. If host is in forwarder_hosts → forwarder
  2. If host is in force_relay (youtube_via_relay + google domains) → relay
  3. If host is in bypass_hosts → direct
  4. Default → relay
"""

import logging

log = logging.getLogger("Router")


class SmartRouter:
    """Config-driven router — decides direct/relay/forwarder per host."""

    def __init__(self, config: dict, data_dir: str = "."):
        self._enabled = config.get("smart_routing", False)

        # Hosts that should always go through forwarder (CAPTCHA-protected)
        self._forwarder_hosts = self._load_rules(config.get("forwarder_hosts", []))
        self._bypass_hosts = self._load_rules(config.get("bypass_hosts", []))

        # Hosts that should always relay — e.g. YouTube video servers
        force_relay = config.get("force_relay_hosts", [])
        if config.get("youtube_via_relay", False):
            force_relay = list(force_relay) + [
                ".youtube.com", ".youtu.be", ".ytimg.com",
                ".ggpht.com", ".googlevideo.com",
                ".google.com", ".googleapis.com", ".gstatic.com",
                ".googleusercontent.com",
            ]
        # Always relay githubusercontent (patterniha needs it on first start)
        force_relay = list(force_relay) + [".githubusercontent.com"]
        self._force_relay_hosts = self._load_rules(force_relay)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _load_rules(raw) -> tuple[set[str], tuple[str, ...]]:
        """Parse host rules into (exact_set, suffix_tuple) for fast matching."""
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
        """Check if host matches any exact or suffix rule."""
        exact, suffixes = rules
        h = host.lower().rstrip(".")
        if h in exact:
            return True
        return any(h.endswith(s) for s in suffixes)

    def get_route(self, host: str) -> str:
        """Get the route for a host: "direct", "relay", or "forwarder"."""
        if not self._enabled:
            return "relay"

        h = host.lower().rstrip(".")

        # Forwarder hosts
        if self._matches(h, self._forwarder_hosts):
            return "forwarder"

        # Force relay hosts (youtube, google, etc.)
        if self._matches(h, self._force_relay_hosts):
            return "relay"

        # Bypass hosts → direct
        if self._matches(h, self._bypass_hosts):
            return "direct"

        # Default → relay
        return "relay"

    def get_stats(self) -> dict:
        """Return routing stats for dashboard."""
        return {
            "enabled": self._enabled,
            "mode": "rule-based",
        }

    def save_cache(self):
        """No-op — kept for backward compatibility with proxy_server.stop()."""
        pass
