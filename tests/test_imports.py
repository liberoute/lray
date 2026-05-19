#!/usr/bin/env python3
"""Test that all modules import correctly."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_all_imports():
    """All src modules should import without error."""
    modules = [
        "proxy_server",
        "domain_fronter",
        "h2_transport",
        "mitm",
        "codec",
        "constants",
        "cert_installer",
        "google_ip_scanner",
        "lan_utils",
        "logging_utils",
        "pac_server",
        "doh_resolver",
        "dashboard_server",
        "config_watcher",
        "smart_router",
        "quota_tracker",
        "config_parser",
        "branding",
        "patterniha_sync",
    ]

    failed = []
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            failed.append((mod, str(e)))

    if failed:
        print("FAILED imports:")
        for mod, err in failed:
            print(f"  ❌ {mod}: {err}")
        return 1

    print(f"✅ All {len(modules)} modules imported successfully")
    return 0


if __name__ == "__main__":
    sys.exit(test_all_imports())
