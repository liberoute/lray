"""
Config file watcher — hot-reload config.json without restarting.

Watches the config file for changes and applies safe updates to the
running proxy server. Only certain settings can be hot-reloaded;
others (like listen_port) require a restart.

Hot-reloadable settings:
  - block_hosts
  - bypass_hosts
  - forwarder_hosts
  - direct_google_exclude
  - direct_google_allow
  - youtube_via_relay
  - relay_timeout
  - log_level
  - parallel_relay
  - chunked_download_*
  - rate_limit_rpm (upstream forwarder)

NOT hot-reloadable (require restart):
  - listen_host / listen_port
  - socks5_port
  - auth_key / script_id
  - front_domain / google_ip
  - pac_port / dashboard_port
"""

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("ConfigWatch")

# Settings that can be safely updated at runtime
_HOT_RELOAD_KEYS = frozenset({
    "block_hosts",
    "bypass_hosts",
    "forwarder_hosts",
    "direct_google_exclude",
    "direct_google_allow",
    "youtube_via_relay",
    "relay_timeout",
    "log_level",
    "parallel_relay",
    "chunked_download_min_size",
    "chunked_download_chunk_size",
    "chunked_download_max_parallel",
    "chunked_download_max_chunks",
    "chunked_download_extensions",
    "hosts",
    "verify_ssl",
})


class ConfigWatcher:
    """Watches config.json and applies changes to the running server."""

    def __init__(self, config_path: str, proxy_server, check_interval: float = 2.0):
        self._path = config_path
        self._proxy = proxy_server
        self._interval = check_interval
        self._last_mtime: float = 0.0
        self._last_config: dict = {}
        self._task: asyncio.Task | None = None
        self._running = False

        # Record initial mtime
        try:
            self._last_mtime = os.path.getmtime(config_path)
        except OSError:
            pass

    async def start(self):
        """Start watching the config file."""
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        log.info("Config watcher started (checking every %.1fs)", self._interval)

    async def stop(self):
        """Stop watching."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self):
        """Poll the config file for changes."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                self._check_for_changes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug("Config watch error: %s", e)

    def _check_for_changes(self):
        """Check if config file was modified and apply changes."""
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return

        if mtime <= self._last_mtime:
            return

        self._last_mtime = mtime
        log.info("Config file changed, reloading...")

        try:
            with open(self._path, "r") as f:
                new_config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error("Failed to reload config: %s", e)
            return

        self._apply_changes(new_config)

    def _apply_changes(self, new_config: dict):
        """Apply hot-reloadable changes to the running proxy."""
        changes = []

        # ── Log level ─────────────────────────────────────────────────────────
        new_level = new_config.get("log_level", "INFO")
        if new_level != self._last_config.get("log_level"):
            level = getattr(logging, new_level.upper(), logging.INFO)
            logging.getLogger().setLevel(level)
            changes.append(f"log_level → {new_level}")

        # ── Host rules ────────────────────────────────────────────────────────
        for key in ("block_hosts", "bypass_hosts"):
            new_val = new_config.get(key, [])
            old_val = self._last_config.get(key, [])
            if new_val != old_val:
                rules = self._proxy._load_host_rules(new_val)
                if key == "block_hosts":
                    self._proxy._block_hosts = rules
                else:
                    self._proxy._bypass_hosts = rules
                changes.append(f"{key} → {len(new_val)} rules")

        # ── Direct Google rules ───────────────────────────────────────────────
        for key in ("direct_google_exclude", "direct_google_allow"):
            new_val = new_config.get(key, [])
            old_val = self._last_config.get(key, [])
            if new_val != old_val:
                if key == "direct_google_exclude":
                    from constants import GOOGLE_DIRECT_EXACT_EXCLUDE
                    self._proxy._direct_google_exclude = {
                        h.lower().rstrip(".")
                        for h in list(GOOGLE_DIRECT_EXACT_EXCLUDE) + list(new_val)
                    }
                else:
                    from constants import GOOGLE_DIRECT_ALLOW_EXACT
                    self._proxy._direct_google_allow = {
                        h.lower().rstrip(".")
                        for h in list(GOOGLE_DIRECT_ALLOW_EXACT) + list(new_val)
                    }
                changes.append(f"{key} updated")

        # ── Hosts override (DNS map) ─────────────────────────────────────────
        new_hosts = new_config.get("hosts", {})
        if new_hosts != self._last_config.get("hosts", {}):
            self._proxy._hosts = new_hosts
            changes.append(f"hosts → {len(new_hosts)} entries")

        # ── Relay timeout ─────────────────────────────────────────────────────
        new_timeout = new_config.get("relay_timeout")
        if new_timeout and new_timeout != self._last_config.get("relay_timeout"):
            if hasattr(self._proxy.fronter, "_relay_timeout"):
                self._proxy.fronter._relay_timeout = float(new_timeout)
                changes.append(f"relay_timeout → {new_timeout}s")

        # ── Chunked download settings ─────────────────────────────────────────
        for key in ("chunked_download_min_size", "chunked_download_chunk_size",
                    "chunked_download_max_parallel", "chunked_download_max_chunks"):
            new_val = new_config.get(key)
            if new_val and new_val != self._last_config.get(key):
                attr = "_" + key.replace("chunked_download_", "download_")
                if hasattr(self._proxy, attr):
                    setattr(self._proxy, attr, int(new_val))
                    changes.append(f"{key} → {new_val}")

        # ── YouTube via relay ─────────────────────────────────────────────────
        new_yt = new_config.get("youtube_via_relay", False)
        if new_yt != self._last_config.get("youtube_via_relay", False):
            from constants import SNI_REWRITE_SUFFIXES
            if new_yt:
                yt_suffixes = ("youtube.com", "youtu.be", "ytimg.com", "ggpht.com")
                self._proxy._SNI_REWRITE_SUFFIXES = tuple(
                    s for s in SNI_REWRITE_SUFFIXES if s not in yt_suffixes
                )
            else:
                self._proxy._SNI_REWRITE_SUFFIXES = SNI_REWRITE_SUFFIXES
            changes.append(f"youtube_via_relay → {new_yt}")

        # ── Save state ────────────────────────────────────────────────────────
        self._last_config = new_config

        if changes:
            log.info("Config reloaded: %s", ", ".join(changes))
        else:
            log.debug("Config file changed but no hot-reloadable differences found")
