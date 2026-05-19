#!/usr/bin/env python3
"""Test setup wizard in all modes without user interaction."""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from setup import generate, load_base_config, DIST_DIR, CONFIG_PATH


def _clean():
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    # Don't delete config.json — other tests need it
    # Only delete if we created a test one
    if CONFIG_PATH.exists():
        content = CONFIG_PATH.read_text(encoding="utf-8")
        if "test_key" in content:
            os.remove(CONFIG_PATH)


def test_mode_gas():
    """Mode: gas — only GAS, no Worker, no VPS."""
    _clean()
    answers = {
        "auth_key": "test_key_1234567890_abcdefghijklmn",
        "key_gas": "test_key_1234567890_abcdefghijklmn",
        "key_worker": "test_key_1234567890_abcdefghijklmn",
        "key_vps": "test_key_1234567890_abcdefghijklmn",
        "has_server": False,
        "exit_mode": "gas",
        "worker_name": "unused",
        "lan_sharing": False,
        "listen_port": "8085",
        "socks5_enabled": True,
        "socks5_port": "1080",
        "dashboard_enabled": True,
        "dashboard_port": "8087",
        "dashboard_auth": False,
        "dashboard_user": "",
        "dashboard_pass": "",
        "want_tunnels": False,
        "tcp_tunnels": [],
        "step_by_step": False,
    }

    generate(answers)

    # Check outputs
    assert (DIST_DIR / "gas" / "Code.gs").exists(), "Code.gs not generated"
    assert not (DIST_DIR / "cloudflare-worker").exists(), "Worker should not exist for gas mode"
    assert not (DIST_DIR / "self-hosted-exit").exists(), "Exit node should not exist for gas mode"
    assert not (DIST_DIR / "upstream_forwarder").exists(), "Forwarder should not exist for gas mode"
    assert CONFIG_PATH.exists(), "config.json not generated"

    # Check config
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    assert cfg["auth_key"] == "test_key_1234567890_abcdefghijklmn"
    assert cfg["listen_port"] == 8085

    # Check Code.gs has correct mode
    code = (DIST_DIR / "gas" / "Code.gs").read_text(encoding="utf-8")
    assert 'const MODE = "gas"' in code

    print("  ✅ Mode: gas")


def test_mode_cfw():
    """Mode: cfw — GAS + Worker."""
    _clean()
    answers = {
        "auth_key": "test_key_cfw_1234567890_abcdefghijk",
        "key_gas": "test_key_cfw_1234567890_abcdefghijk",
        "key_worker": "test_key_cfw_1234567890_abcdefghijk",
        "key_vps": "test_key_cfw_1234567890_abcdefghijk",
        "has_server": False,
        "exit_mode": "cfw",
        "worker_name": "test-worker",
        "lan_sharing": False,
        "listen_port": "9000",
        "socks5_enabled": False,
        "socks5_port": "1080",
        "dashboard_enabled": True,
        "dashboard_port": "9001",
        "dashboard_auth": False,
        "dashboard_user": "",
        "dashboard_pass": "",
        "want_tunnels": False,
        "tcp_tunnels": [],
        "step_by_step": False,
    }

    generate(answers)

    assert (DIST_DIR / "gas" / "Code.gs").exists()
    assert (DIST_DIR / "cloudflare-worker" / "worker.js").exists(), "Worker not generated for cfw mode"
    assert not (DIST_DIR / "self-hosted-exit").exists()

    # Check worker has correct URL
    worker = (DIST_DIR / "cloudflare-worker" / "worker.js").read_text(encoding="utf-8")
    assert 'const WORKER_URL = "test-worker.workers.dev"' in worker

    code = (DIST_DIR / "gas" / "Code.gs").read_text(encoding="utf-8")
    assert 'const MODE = "cfw"' in code

    print("  ✅ Mode: cfw")


def test_mode_vps():
    """Mode: vps — GAS + self-hosted exit."""
    _clean()
    answers = {
        "auth_key": "test_key_vps_1234567890_abcdefghijk",
        "key_gas": "test_key_vps_1234567890_abcdefghijk",
        "key_worker": "test_key_vps_1234567890_abcdefghijk",
        "key_vps": "vps_specific_key_1234567890_abcdefg",
        "has_server": True,
        "server_domain": "test.example.com",
        "server_ssl": True,
        "server_port": "8443",
        "http_port": "80",
        "ssl_mode": "own",
        "letsencrypt_email": "",
        "ssl_cert_file": "/etc/ssl/cert.pem",
        "ssl_key_file": "/etc/ssl/key.pem",
        "also_http": False,
        "exit_mode": "vps",
        "worker_name": "unused",
        "lan_sharing": True,
        "listen_port": "8085",
        "socks5_enabled": True,
        "socks5_port": "1080",
        "dashboard_enabled": True,
        "dashboard_port": "8087",
        "dashboard_auth": False,
        "dashboard_user": "",
        "dashboard_pass": "",
        "want_tunnels": False,
        "tcp_tunnels": [],
        "step_by_step": False,
    }

    generate(answers)

    assert (DIST_DIR / "gas" / "Code.gs").exists()
    assert (DIST_DIR / "self-hosted-exit" / "start.sh").exists(), "Exit node not generated for vps mode"
    assert (DIST_DIR / "self-hosted-exit" / ".env").exists(), ".env not generated"
    assert not (DIST_DIR / "cloudflare-worker").exists(), "Worker should not exist for vps mode"
    assert not (DIST_DIR / "upstream_forwarder").exists()

    # Check .env has correct values
    env = (DIST_DIR / "self-hosted-exit" / ".env").read_text(encoding="utf-8")
    assert "AUTH_KEY=vps_specific_key_1234567890_abcdefg" in env
    assert "PORT=8443" in env
    assert "SSL_CERT_FILE=/etc/ssl/cert.pem" in env

    code = (DIST_DIR / "gas" / "Code.gs").read_text(encoding="utf-8")
    assert 'const MODE = "vps"' in code
    assert "test.example.com" in code

    print("  ✅ Mode: vps")


def test_mode_cfw_vps():
    """Mode: cfw_vps — GAS + Worker + upstream forwarder."""
    _clean()
    answers = {
        "auth_key": "test_key_cfwvps_1234567890_abcdefgh",
        "key_gas": "test_key_cfwvps_1234567890_abcdefgh",
        "key_worker": "test_key_cfwvps_1234567890_abcdefgh",
        "key_vps": "vps_key_cfwvps_1234567890_abcdefghij",
        "has_server": True,
        "server_domain": "forwarder.example.com",
        "server_ssl": True,
        "server_port": "443",
        "http_port": "80",
        "ssl_mode": "letsencrypt",
        "letsencrypt_email": "test@test.com",
        "ssl_cert_file": "./certs/fullchain.pem",
        "ssl_key_file": "./certs/privkey.pem",
        "also_http": True,
        "exit_mode": "cfw_vps",
        "worker_name": "my-relay",
        "lan_sharing": False,
        "listen_port": "8085",
        "socks5_enabled": True,
        "socks5_port": "1080",
        "dashboard_enabled": True,
        "dashboard_port": "8087",
        "dashboard_auth": False,
        "dashboard_user": "",
        "dashboard_pass": "",
        "want_tunnels": False,
        "tcp_tunnels": [],
        "step_by_step": False,
    }

    generate(answers)

    assert (DIST_DIR / "gas" / "Code.gs").exists()
    assert (DIST_DIR / "cloudflare-worker" / "worker.js").exists()
    assert (DIST_DIR / "upstream_forwarder" / "start.sh").exists()
    assert (DIST_DIR / "upstream_forwarder" / ".env").exists()

    # Check worker has forwarder embedded
    worker = (DIST_DIR / "cloudflare-worker" / "worker.js").read_text(encoding="utf-8")
    assert "_FORWARDER_URL" in worker
    assert "_FORWARDER_KEY" in worker

    code = (DIST_DIR / "gas" / "Code.gs").read_text(encoding="utf-8")
    assert 'const MODE = "cfw_vps"' in code

    print("  ✅ Mode: cfw_vps")


def test_separate_keys():
    """Separate keys per segment."""
    _clean()
    answers = {
        "auth_key": "master_key_1234567890_abcdefghijklm",
        "key_gas": "gas_key_11111111111111111111111111111",
        "key_worker": "worker_key_222222222222222222222222222",
        "key_vps": "vps_key_33333333333333333333333333333",
        "has_server": True,
        "server_domain": "vps.test.com",
        "server_ssl": False,
        "server_port": "3000",
        "http_port": "3000",
        "ssl_mode": "none",
        "letsencrypt_email": "",
        "ssl_cert_file": "",
        "ssl_key_file": "",
        "also_http": True,
        "exit_mode": "vps",
        "worker_name": "unused",
        "lan_sharing": False,
        "listen_port": "8085",
        "socks5_enabled": True,
        "socks5_port": "1080",
        "dashboard_enabled": True,
        "dashboard_port": "8087",
        "dashboard_auth": False,
        "dashboard_user": "",
        "dashboard_pass": "",
        "want_tunnels": False,
        "tcp_tunnels": [],
        "step_by_step": False,
    }

    generate(answers)

    # config.json should have key_gas
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    assert cfg["auth_key"] == "gas_key_11111111111111111111111111111"

    # Code.gs should have key_gas
    code = (DIST_DIR / "gas" / "Code.gs").read_text(encoding="utf-8")
    assert "gas_key_11111111111111111111111111111" in code

    # VPS .env should have key_vps
    env = (DIST_DIR / "self-hosted-exit" / ".env").read_text(encoding="utf-8")
    assert "vps_key_33333333333333333333333333333" in env

    print("  ✅ Separate keys")


def main():
    print()
    print("  Setup Wizard Tests")
    print()

    tests = [
        test_mode_gas,
        test_mode_cfw,
        test_mode_vps,
        test_mode_cfw_vps,
        test_separate_keys,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    _clean()  # cleanup

    print()
    print(f"  Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
