"""
Config Parser — normalizes nested config to flat format for backward compatibility.

Supports both old flat format:
  { "listen_host": "127.0.0.1", "listen_port": 8085, "socks5_port": 1080 }

And new nested format:
  { "proxies": { "host": "127.0.0.1", "http": { "port": 8085 }, "socks5": { "port": 1080 } } }

Always returns a flat dict that proxy_server.py can use.
"""


def normalize_config(raw: dict) -> dict:
    """Convert nested config to flat format. Passes flat config through unchanged."""

    # If already flat (has listen_port), return as-is
    if "listen_port" in raw:
        return raw

    cfg = dict(raw)

    # ── Proxies ───────────────────────────────────────────────────────────────
    proxies = raw.get("proxies", {})
    if proxies:
        lan_sharing = proxies.get("lan_sharing", False)
        cfg["lan_sharing"] = lan_sharing
        cfg["listen_host"] = "0.0.0.0" if lan_sharing else "127.0.0.1"

        # New format: listeners array
        listeners = proxies.get("listeners")
        if listeners and isinstance(listeners, list):
            cfg["listeners"] = listeners
            # Set legacy values from first http/mixed listener
            for l in listeners:
                if l.get("type") in ("http", "mixed"):
                    cfg["listen_port"] = l.get("port", 8085)
                    break
            else:
                cfg["listen_port"] = 8085
            for l in listeners:
                if l.get("type") == "socks5":
                    cfg["socks5_enabled"] = True
                    cfg["socks5_port"] = l.get("port", 1080)
                    break
            else:
                cfg["socks5_enabled"] = False
                cfg["socks5_port"] = 1080
            for l in listeners:
                if l.get("type") == "mtproto":
                    cfg["mtproto_enabled"] = True
                    cfg["mtproto_port"] = l.get("port", 8443)
                    cfg["mtproto_secret"] = l.get("secret", "")
                    break
            else:
                cfg["mtproto_enabled"] = False
        else:
            # Old format: separate http/socks5/mtproto sections
            http = proxies.get("http", {})
            cfg["listen_port"] = http.get("port", 8085)

            socks5 = proxies.get("socks5", {})
            cfg["socks5_enabled"] = socks5.get("enabled", True)
            cfg["socks5_port"] = socks5.get("port", 1080)

            mtproto = proxies.get("mtproto", {})
            cfg["mtproto_enabled"] = mtproto.get("enabled", False)
            cfg["mtproto_port"] = mtproto.get("port", 8443)
            cfg["mtproto_secret"] = mtproto.get("secret", "")

            # Build listeners from old format for unified handling
            _listeners = []
            if http.get("enabled", True):
                _mode = "smart" if raw.get("routing", {}).get("smart_routing", True) else "relay"
                _listeners.append({"port": cfg["listen_port"], "type": "mixed", "mode": _mode})
            if cfg["socks5_enabled"]:
                _listeners.append({"port": cfg["socks5_port"], "type": "socks5", "mode": _mode})
            if cfg["mtproto_enabled"]:
                _listeners.append({
                    "port": cfg["mtproto_port"], "type": "mtproto",
                    "mode": "relay", "secret": cfg["mtproto_secret"],
                })
            cfg["listeners"] = _listeners

    # ── Relay ─────────────────────────────────────────────────────────────────
    relay = raw.get("relay", {})
    if relay:
        cfg["google_ip"] = relay.get("google_ip", cfg.get("google_ip", "216.239.38.120"))
        cfg["front_domain"] = relay.get("front_domain", cfg.get("front_domain", "www.google.com"))
        cfg["relay_timeout"] = relay.get("timeout", cfg.get("relay_timeout", 25))
        cfg["tls_connect_timeout"] = relay.get("tls_connect_timeout", cfg.get("tls_connect_timeout", 15))
        cfg["tcp_connect_timeout"] = relay.get("tcp_connect_timeout", cfg.get("tcp_connect_timeout", 10))
        cfg["parallel_relay"] = relay.get("parallel_relay", cfg.get("parallel_relay", 1))
        cfg["verify_ssl"] = relay.get("verify_ssl", cfg.get("verify_ssl", True))

    # ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard = raw.get("dashboard", {})
    if dashboard:
        cfg["dashboard_enabled"] = dashboard.get("enabled", True)
        cfg["dashboard_port"] = dashboard.get("port", 8087)
        cfg["dashboard_user"] = dashboard.get("user", "")
        cfg["dashboard_pass"] = dashboard.get("pass", "")

    # ── PAC ───────────────────────────────────────────────────────────────────
    pac = raw.get("pac", {})
    if pac:
        cfg["pac_enabled"] = pac.get("enabled", True)
        cfg["pac_port"] = pac.get("port", 8086)

    # ── DNS Relay ─────────────────────────────────────────────────────────────
    dns = raw.get("dns_relay", {})
    if dns:
        cfg["dns_relay_enabled"] = dns.get("enabled", False)
        cfg["dns_relay_port"] = dns.get("port", 5353)
        cfg["dns_relay_server"] = dns.get("server", "8.8.8.8")

    # ── Tunnels ───────────────────────────────────────────────────────────────
    tunnels = raw.get("tunnels", {})
    if tunnels:
        cfg["tcp_tunnels"] = tunnels.get("tcp", [])
        cfg["udp_tunnels"] = tunnels.get("udp", [])

    # ── Routing ───────────────────────────────────────────────────────────────
    routing = raw.get("routing", {})
    if routing:
        cfg["smart_routing"] = routing.get("smart_routing", True)
        cfg["bypass_hosts"] = routing.get("bypass_hosts", ["localhost", ".local", ".lan", ".home.arpa"])
        cfg["block_hosts"] = routing.get("block_hosts", [])
        cfg["forwarder_hosts"] = routing.get("forwarder_hosts", [])
        cfg["youtube_via_relay"] = routing.get("youtube_via_relay", False)

    # ── Advanced ──────────────────────────────────────────────────────────────
    advanced = raw.get("advanced", {})
    if advanced:
        cfg["doh_enabled"] = advanced.get("doh_enabled", True)
        cfg["hot_reload"] = advanced.get("hot_reload", True)
        cfg["log_level"] = advanced.get("log_level", "INFO")
        cfg["patterniha_sync"] = advanced.get("patterniha_sync", True)
        cfg["hosts"] = advanced.get("hosts", {})

    return cfg
