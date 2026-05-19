"""
Patterniha Config Sync — fetches and parses MITM-DomainFronting config.

Periodically checks https://github.com/patterniha/MITM-DomainFronting
for the latest xray config and extracts domain→SNI mappings that can be
used for direct domain fronting without needing a relay (GAS/Worker/VPS).

This saves relay quota for sites that can be reached directly via CDN
domain fronting (Google, GitHub, Vercel, Fastly, Netlify, etc.).

Usage:
    syncer = PatternihaSync(config)
    await syncer.start()  # background periodic check

    # In routing logic:
    mapping = syncer.get_sni_mapping("reddit.com")
    if mapping:
        # Connect to mapping.connect_ip with SNI=mapping.sni
        ...
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("Patterniha")

# GitHub raw URL for the config
_CONFIG_URL = (
    "https://raw.githubusercontent.com/patterniha/"
    "MITM-DomainFronting/main/Xray-config/MITM-DomainFronting.json"
)

# GitHub API for latest release (to check version)
_RELEASES_URL = (
    "https://api.github.com/repos/patterniha/"
    "MITM-DomainFronting/releases/latest"
)

# How often to check for updates (seconds)
_CHECK_INTERVAL = 3600  # 1 hour

# Cache file name
_CACHE_FILE = "patterniha_config.json"
_STATE_FILE = "patterniha_state.json"


@dataclass
class SNIMapping:
    """A domain fronting mapping: connect to connect_host with sni as ServerName."""
    sni: str                    # SNI to use in outgoing TLS (e.g. "www.google.com")
    connect_host: str           # IP or hostname to connect to
    alpn: list[str] = field(default_factory=lambda: ["h2", "http/1.1"])
    verify_names: list[str] = field(default_factory=list)


class PatternihaSync:
    """Syncs patterniha's MITM-DomainFronting config and provides routing info."""

    def __init__(self, config: dict, data_dir: str = "."):
        self._enabled = config.get("patterniha_sync", True)
        self._data_dir = Path(data_dir)
        self._cache_path = self._data_dir / _CACHE_FILE
        self._state_path = self._data_dir / _STATE_FILE

        # Domain → SNIMapping
        self._mappings: dict[str, SNIMapping] = {}
        # Suffix rules: ".youtube.com" → SNIMapping
        self._suffix_mappings: list[tuple[str, SNIMapping]] = []
        # All supported domains (for dashboard/stats)
        self._supported_domains: list[str] = []

        self._version: str = ""
        self._last_check: float = 0
        self._task: Optional[asyncio.Task] = None

        # Load cached config on init
        self._load_cache()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def version(self) -> str:
        return self._version

    @property
    def supported_domains(self) -> list[str]:
        return self._supported_domains

    def get_sni_mapping(self, host: str) -> Optional[SNIMapping]:
        """Get SNI mapping for a host, or None if not supported.

        Checks exact match first, then suffix rules.
        """
        if not self._enabled:
            return None
        if not self._mappings and not self._suffix_mappings:
            return None

        h = host.lower().rstrip(".")

        # Exact match
        if h in self._mappings:
            return self._mappings[h]

        # Suffix match
        for suffix, mapping in self._suffix_mappings:
            if h.endswith(suffix) or h == suffix.lstrip("."):
                return mapping

        return None

    def get_stats(self) -> dict:
        """Return stats for dashboard."""
        return {
            "enabled": self._enabled,
            "version": self._version,
            "last_check": self._last_check,
            "total_mappings": len(self._mappings),
            "suffix_rules": len(self._suffix_mappings),
            "supported_domains": self._supported_domains[:20],
        }

    async def start(self):
        """Start background update loop."""
        if not self._enabled:
            return

        # Initial fetch if no cache
        if not self._mappings:
            await self._fetch_and_parse()

        # Start periodic check
        self._task = asyncio.create_task(self._update_loop())

    async def stop(self):
        """Stop background updates."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _update_loop(self):
        """Periodically check for config updates."""
        while True:
            try:
                await asyncio.sleep(_CHECK_INTERVAL)
                await self._fetch_and_parse()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Patterniha update check failed: %s", e)
                await asyncio.sleep(60)  # retry sooner on error

    async def _fetch_and_parse(self):
        """Fetch latest config from GitHub and parse it."""
        import urllib.request
        import urllib.error

        log.info("Checking patterniha config for updates...")

        try:
            # Check latest release version first
            new_version = await self._check_version()
            if new_version and new_version == self._version:
                log.info("Patterniha config up to date (v%s)", self._version)
                self._last_check = time.time()
                return

            # Fetch the config
            loop = asyncio.get_running_loop()
            config_data = await loop.run_in_executor(None, self._download_config)

            if not config_data:
                log.warning("Failed to download patterniha config")
                return

            # Parse it
            config = json.loads(config_data)
            self._parse_xray_config(config)

            # Update version
            remarks = config.get("remarks", "")
            if remarks:
                # Extract version from "MITM-DomainFronting_v20"
                if "_v" in remarks:
                    self._version = remarks.split("_v")[-1]
                else:
                    self._version = remarks

            self._last_check = time.time()

            # Save cache
            self._save_cache(config_data)
            self._save_state()

            log.info(
                "Patterniha config updated to v%s (%d mappings, %d suffix rules)",
                self._version, len(self._mappings), len(self._suffix_mappings)
            )

        except Exception as e:
            log.warning("Patterniha sync error: %s", e)

    async def _check_version(self) -> Optional[str]:
        """Check latest release version from GitHub API."""
        import urllib.request
        import urllib.error

        try:
            loop = asyncio.get_running_loop()

            def _fetch():
                req = urllib.request.Request(
                    _RELEASES_URL,
                    headers={"User-Agent": "lray-patterniha-sync"}
                )
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read())
                tag = data.get("tag_name", "")
                return tag.lstrip("v")

            return await loop.run_in_executor(None, _fetch)
        except Exception:
            return None

    def _download_config(self) -> Optional[str]:
        """Download the config file (blocking, run in executor)."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                _CONFIG_URL,
                headers={"User-Agent": "lray-patterniha-sync"}
            )
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.read().decode("utf-8")
        except Exception as e:
            log.debug("Download failed: %s", e)
            return None

    def _parse_xray_config(self, config: dict):
        """Parse xray config and extract domain→SNI mappings.

        The config has:
        - outbounds with tag "tls-repack-*" that define SNI + connect targets
        - routing rules that map domains to those outbounds
        """
        mappings: dict[str, SNIMapping] = {}
        suffix_mappings: list[tuple[str, SNIMapping]] = []
        supported: list[str] = []

        # Step 1: Parse outbounds to get tag → SNIMapping
        outbound_map: dict[str, SNIMapping] = {}

        for outbound in config.get("outbounds", []):
            tag = outbound.get("tag", "")
            if not tag.startswith("tls-repack-"):
                continue

            stream = outbound.get("streamSettings", {})
            security = stream.get("security", "")
            if security != "tls":
                continue

            tls_settings = stream.get("tlsSettings", {})
            sni = tls_settings.get("serverName", "")
            alpn = tls_settings.get("alpn", ["h2", "http/1.1"])
            verify_names = []

            # Parse verifyPeerCertByName for allowed cert names
            verify_raw = tls_settings.get("verifyPeerCertByName", "")
            if verify_raw:
                verify_names = [
                    n.strip() for n in verify_raw.split(",")
                    if n.strip() and n.strip() != "fromMitM"
                ]

            # Get connect target from redirect setting
            settings = outbound.get("settings", {})
            redirect = settings.get("redirect", "")
            connect_host = ""
            if redirect:
                # Format: "hostname:port" or "ip:port"
                connect_host = redirect.rsplit(":", 1)[0] if ":" in redirect else redirect

            if not sni or sni == "fromMitM":
                continue

            # Clean up alpn (remove "fromMitM")
            clean_alpn = [a for a in alpn if a != "fromMitM"]
            if not clean_alpn:
                clean_alpn = ["h2", "http/1.1"]

            outbound_map[tag] = SNIMapping(
                sni=sni,
                connect_host=connect_host or sni,
                alpn=clean_alpn,
                verify_names=verify_names,
            )

        # Step 2: Parse routing rules to map domains → outbound tags
        routing = config.get("routing", {})
        rules = routing.get("rules", [])

        for rule in rules:
            outbound_tag = rule.get("outboundTag", "")
            if outbound_tag not in outbound_map:
                continue

            # Only process rules from MITM inbounds (tls-decrypt-*)
            inbound_tags = rule.get("inboundTag", [])
            if inbound_tags and not any("tls-decrypt" in t for t in inbound_tags):
                continue

            mapping = outbound_map[outbound_tag]
            domains = rule.get("domain", [])

            for domain_rule in domains:
                # Parse xray domain format
                if domain_rule.startswith("domain:"):
                    # Suffix match
                    d = domain_rule[7:]  # strip "domain:"
                    suffix_mappings.append(("." + d, mapping))
                    supported.append("*." + d)
                elif domain_rule.startswith("full:"):
                    # Exact match
                    d = domain_rule[5:]  # strip "full:"
                    mappings[d] = mapping
                    supported.append(d)
                elif domain_rule.startswith("geosite:"):
                    # Geosite rule — we expand known ones
                    geo = domain_rule[8:]
                    expanded = self._expand_geosite(geo)
                    for d in expanded:
                        if d.startswith("."):
                            suffix_mappings.append((d, mapping))
                            supported.append("*" + d)
                        else:
                            mappings[d] = mapping
                            supported.append(d)
                else:
                    # Plain domain (treat as exact)
                    mappings[domain_rule] = mapping
                    supported.append(domain_rule)

        self._mappings = mappings
        self._suffix_mappings = suffix_mappings
        self._supported_domains = sorted(set(supported))

    @staticmethod
    def _expand_geosite(name: str) -> list[str]:
        """Expand known geosite categories to domain lists.

        We only expand categories that patterniha actually uses.
        This is a best-effort mapping — xray uses dat files for full lists.
        """
        known = {
            "google": [
                ".google.com", ".google.co", ".googleapis.com",
                ".gstatic.com", ".googleusercontent.com",
                ".googlevideo.com", ".youtube.com", ".ytimg.com",
                ".ggpht.com", ".google-analytics.com",
                ".googletagmanager.com", ".doubleclick.net",
                ".googlesyndication.com", ".googleadservices.com",
            ],
            "vercel": [
                ".vercel.com", ".vercel.app", ".vercel.sh",
                ".nextjs.org", ".now.sh",
            ],
            "fastly": [
                ".fastly.com", ".fastly.net",
                ".fastlylb.net", ".global.ssl.fastly.net",
            ],
            "reddit": [
                ".reddit.com", ".redd.it", ".redditstatic.com",
                ".redditmedia.com",
            ],
            "github": [
                ".github.com", ".github.io", ".githubusercontent.com",
                ".githubassets.com", ".github.dev",
            ],
            "netlify": [
                ".netlify.com", ".netlify.app", ".netlifyglobalcdn.com",
            ],
            "cnn": [
                ".cnn.com", ".cnn.io",
            ],
        }
        return known.get(name, [])

    def _load_cache(self):
        """Load cached config from disk."""
        try:
            if self._cache_path.exists():
                data = self._cache_path.read_text(encoding="utf-8")
                config = json.loads(data)
                self._parse_xray_config(config)

                # Load state
                if self._state_path.exists():
                    state = json.loads(self._state_path.read_text(encoding="utf-8"))
                    self._version = state.get("version", "")
                    self._last_check = state.get("last_check", 0)

                log.info(
                    "Loaded cached patterniha config v%s (%d mappings)",
                    self._version, len(self._mappings)
                )
        except Exception as e:
            log.debug("Failed to load patterniha cache: %s", e)

    def _save_cache(self, raw_json: str):
        """Save config to disk cache."""
        try:
            self._cache_path.write_text(raw_json, encoding="utf-8")
        except Exception as e:
            log.debug("Failed to save patterniha cache: %s", e)

    def _save_state(self):
        """Save sync state to disk."""
        try:
            state = {
                "version": self._version,
                "last_check": self._last_check,
            }
            self._state_path.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except Exception as e:
            log.debug("Failed to save patterniha state: %s", e)
