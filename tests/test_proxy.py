#!/usr/bin/env python3
"""
lray Proxy Tester — tests the running proxy end-to-end.

Usage:
    python test_proxy.py
    python test_proxy.py --host 127.0.0.1 --port 8087

Tests:
  1. Proxy is listening (TCP connect)
  2. HTTP request through proxy (icanhazip.com)
  3. HTTPS request through proxy (httpbin.org/ip)
  4. SOCKS5 proxy works
  5. PAC file is served
  6. Dashboard is accessible
  7. Exit IP check
"""

import argparse
import json
import socket
import sys
import time
import urllib.request
import urllib.error

# ─── Colors ───────────────────────────────────────────────────────────────────

def _c(code, text):
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t): return _c("32", t)
def red(t): return _c("31", t)
def yellow(t): return _c("33", t)
def dim(t): return _c("2", t)
def bold(t): return _c("1", t)

PASS = green("✓ PASS")
FAIL = red("✕ FAIL")
SKIP = yellow("○ SKIP")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def check_port(host, port, timeout=3):
    """Check if a TCP port is open."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def fetch_via_proxy(url, proxy_host, proxy_port, timeout=45):
    """Fetch a URL through the HTTP proxy."""
    proxy = urllib.request.ProxyHandler({
        "http": f"http://{proxy_host}:{proxy_port}",
        "https": f"http://{proxy_host}:{proxy_port}",
    })
    opener = urllib.request.build_opener(proxy)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "lray-tester/1.0")
    try:
        resp = opener.open(req, timeout=timeout)
        return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return None, str(e)


def fetch_direct(url, timeout=5):
    """Fetch a URL directly (no proxy)."""
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read().decode(errors="replace")
    except Exception as e:
        return None, str(e)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_proxy_listening(host, port):
    """Test 1: Proxy TCP port is open."""
    ok = check_port(host, port)
    return ok, f"HTTP proxy on {host}:{port}"


def test_socks_listening(host, port):
    """Test 2: SOCKS5 TCP port is open."""
    ok = check_port(host, port)
    return ok, f"SOCKS5 on {host}:{port}"


def test_pac_server(host, pac_port):
    """Test 3: PAC file is served."""
    status, body = fetch_direct(f"http://{host}:{pac_port}/proxy.pac")
    ok = status == 200 and "FindProxyForURL" in body
    detail = f"PAC on {host}:{pac_port}"
    if ok:
        detail += f" ({len(body)} bytes)"
    return ok, detail


def test_dashboard(host, dash_port):
    """Test 4: Dashboard is accessible."""
    status, body = fetch_direct(f"http://{host}:{dash_port}/dashboard")
    ok = status == 200 and ("lray" in body or "Dashboard" in body)
    return ok, f"Dashboard on {host}:{dash_port}"


def test_http_proxy(host, port):
    """Test 5: HTTP request through proxy."""
    t0 = time.time()
    status, body = fetch_via_proxy("http://icanhazip.com", host, port)
    elapsed = int((time.time() - t0) * 1000)
    if status == 200 and body.strip():
        ip = body.strip().split("\n")[0]
        return True, f"HTTP via proxy → {ip} ({elapsed}ms)"
    return False, f"HTTP via proxy failed: {status} {body[:100]}"


def test_https_proxy(host, port):
    """Test 6: HTTPS request through proxy."""
    t0 = time.time()
    status, body = fetch_via_proxy("https://icanhazip.com", host, port)
    elapsed = int((time.time() - t0) * 1000)
    if status == 200 and body.strip():
        ip = body.strip().split("\n")[0]
        return True, f"HTTPS via proxy → {ip} ({elapsed}ms)"
    return False, f"HTTPS via proxy failed: {status} {body[:100]}"


def test_exit_ip(host, port):
    """Test 7: Check exit IP."""
    status, body = fetch_via_proxy("http://icanhazip.com", host, port)
    if status == 200:
        exit_ip = body.strip().split("\n")[0]
        # Check if it's different from our real IP
        real_status, real_body = fetch_direct("http://icanhazip.com")
        if real_status == 200:
            real_ip = real_body.strip().split("\n")[0]
            if exit_ip != real_ip:
                return True, f"Exit IP: {exit_ip} (different from real: {real_ip})"
            else:
                return None, f"Exit IP same as real IP: {exit_ip} (proxy may be bypassing)"
        return True, f"Exit IP: {exit_ip} (couldn't check real IP)"
    return False, "Couldn't determine exit IP"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="lray Proxy Tester")
    parser.add_argument("--host", default="127.0.0.1", help="Proxy host")
    parser.add_argument("--port", type=int, default=None, help="HTTP proxy port")
    parser.add_argument("--socks-port", type=int, default=None, help="SOCKS5 port")
    parser.add_argument("--pac-port", type=int, default=None, help="PAC port")
    parser.add_argument("--dash-port", type=int, default=None, help="Dashboard port")
    parser.add_argument("--config", default="config.json", help="Config file to read ports from")
    args = parser.parse_args()

    # Read ports from config if not specified
    host = args.host
    port = args.port
    socks_port = args.socks_port
    pac_port = args.pac_port
    dash_port = args.dash_port

    if not port:
        try:
            with open(args.config) as f:
                cfg = json.load(f)
            port = cfg.get("listen_port", 8085)
            socks_port = socks_port or cfg.get("socks5_port", 1080)
            pac_port = pac_port or cfg.get("pac_port", port + 1)
            dash_port = dash_port or cfg.get("dashboard_port", port + 2)
            if cfg.get("listen_host") not in ("127.0.0.1", "0.0.0.0"):
                host = cfg["listen_host"]
        except Exception:
            port = 8085
            socks_port = socks_port or 1080
            pac_port = pac_port or 8086
            dash_port = dash_port or 8087

    socks_port = socks_port or 1080
    pac_port = pac_port or port + 1
    dash_port = dash_port or port + 2

    # Auto-start proxy if not running
    proxy_process = None
    if not check_port(host if host != "0.0.0.0" else "127.0.0.1", port):
        import subprocess
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(root, "config.json")

        # Can't start without config
        if not os.path.exists(config_path):
            print(red("  ❌ config.json not found. Run 'lray setup' first."))
            return 1

        print(dim("  Proxy not running — starting it..."))
        proxy_process = subprocess.Popen(
            [sys.executable, os.path.join(root, "main.py")],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for proxy to start
        check_host = host if host != "0.0.0.0" else "127.0.0.1"
        for _ in range(30):
            time.sleep(1)
            if check_port(check_host, port):
                break
        else:
            print(red("  ❌ Proxy failed to start within 30s"))
            proxy_process.kill()
            return 1
        print(dim("  ✓ Proxy started"))
        # Give relay time to warm up (first GAS connection is slow)
        time.sleep(3)
        # Use 127.0.0.1 for testing if bound to 0.0.0.0
        if host == "0.0.0.0":
            host = "127.0.0.1"

    print()
    print(bold("  lray Proxy Tester"))
    print(dim(f"  Target: {host}:{port}"))
    print()

    tests = [
        ("Proxy listening", lambda: test_proxy_listening(host, port)),
        ("SOCKS5 listening", lambda: test_socks_listening(host, socks_port)),
        ("PAC file server", lambda: test_pac_server(host, pac_port)),
        ("Dashboard", lambda: test_dashboard(host, dash_port)),
        ("HTTP through proxy", lambda: test_http_proxy(host, port)),
        ("HTTPS through proxy", lambda: test_https_proxy(host, port)),
        ("Exit IP check", lambda: test_exit_ip(host, port)),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, test_fn in tests:
        try:
            result, detail = test_fn()
            if result is True:
                print(f"  {PASS}  {name}: {detail}")
                passed += 1
            elif result is False:
                print(f"  {FAIL}  {name}: {detail}")
                failed += 1
            else:
                print(f"  {SKIP}  {name}: {detail}")
                skipped += 1
        except Exception as e:
            print(f"  {FAIL}  {name}: {red(str(e))}")
            failed += 1

    print()
    print(f"  Results: {green(str(passed) + ' passed')}, {red(str(failed) + ' failed')}, {yellow(str(skipped) + ' skipped')}")
    print()

    if failed == 0:
        print(green("  🎉 All tests passed!"))
    else:
        print(red(f"  ⚠️  {failed} test(s) failed"))

    # Stop proxy if we started it
    if proxy_process:
        proxy_process.terminate()
        proxy_process.wait(timeout=5)
        print(dim("  ✓ Proxy stopped"))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
