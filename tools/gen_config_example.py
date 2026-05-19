#!/usr/bin/env python3
"""Generate config.example.json from constants.py defaults."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from constants import (
    RELAY_TIMEOUT, TLS_CONNECT_TIMEOUT, TCP_CONNECT_TIMEOUT,
)


def generate():
    config = {
        "mode": "apps_script",
        "auth_key": "CHANGE_ME_TO_A_STRONG_SECRET",
        "script_id": "YOUR_APPS_SCRIPT_DEPLOYMENT_ID",

        "relay": {
            "google_ip": "216.239.38.120",
            "front_domain": "www.google.com",
            "timeout": RELAY_TIMEOUT,
            "tls_connect_timeout": TLS_CONNECT_TIMEOUT,
            "tcp_connect_timeout": TCP_CONNECT_TIMEOUT,
            "parallel_relay": 1,
            "verify_ssl": True,
        },

        "proxies": {
            "http": {
                "host": "127.0.0.1",
                "port": 8085,
            },
            "socks5": {
                "enabled": True,
                "port": 1080,
            },
        },

        "dashboard": {
            "enabled": True,
            "port": 8087,
            "user": "",
            "pass": "",
        },

        "pac": {
            "enabled": True,
            "port": 8086,
        },

        "dns_relay": {
            "enabled": False,
            "port": 5353,
            "server": "8.8.8.8",
        },

        "tunnels": {
            "tcp": [],
            "udp": [],
        },

        "routing": {
            "smart_routing": True,
            "bypass_hosts": ["localhost", ".local", ".lan", ".home.arpa"],
            "block_hosts": [],
            "forwarder_hosts": [],
            "youtube_via_relay": False,
        },

        "advanced": {
            "doh_enabled": True,
            "hot_reload": True,
            "lan_sharing": False,
            "log_level": "INFO",
            "hosts": {},
        },
    }

    return config


if __name__ == "__main__":
    config = generate()
    output = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
    with open(output, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print(f"✓ Generated: config.example.json")
