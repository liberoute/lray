#!/usr/bin/env python3
"""Interactive setup wizard.

Asks all questions first, then generates everything into output/.

Run:
    python setup.py
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # project root (tools/ → root)
CONFIG_PATH = HERE / "config.json"
EXAMPLE_PATH = HERE / "config.example.json"
DIST_DIR = HERE / "output"
WORKER_TEMPLATE = HERE / "deploy" / "cloudflare-worker" / "worker.js"
GAS_TEMPLATE = HERE / "deploy" / "gas" / "Code.gs"


# ─── Terminal colors ──────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t: str) -> str: return _c("1", t)
def cyan(t: str) -> str: return _c("36", t)
def green(t: str) -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str) -> str: return _c("31", t)
def dim(t: str) -> str: return _c("2", t)
def blue(t: str) -> str: return _c("34", t)


def prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{dim(default)}]" if default else ""
    while True:
        try:
            raw = input(f"{cyan('?')} {question}{suffix}: ").strip()
        except EOFError:
            print()
            sys.exit(1)
        if not raw and default is not None:
            return default
        if raw:
            return raw
        print(red("  value required"))


def prompt_yes_no(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"{cyan('?')} {question} [{hint}]: ").strip().lower()
        except EOFError:
            return default
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def random_auth_key(length: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def print_step(num: int, title: str):
    print()
    print(f"  {bold(blue(f'[{num}]'))} {bold(title)}")
    print()


# ─── Config loader ────────────────────────────────────────────────────────────

def load_base_config() -> dict:
    if EXAMPLE_PATH.exists():
        try:
            with EXAMPLE_PATH.open() as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "mode": "apps_script",
        "google_ip": "216.239.38.120",
        "front_domain": "www.google.com",
        "listen_host": "127.0.0.1",
        "listen_port": 8085,
        "socks5_enabled": True,
        "socks5_port": 1080,
        "log_level": "INFO",
        "verify_ssl": True,
        "lan_sharing": False,
        "relay_timeout": 25,
        "bypass_hosts": ["localhost", ".local", ".lan", ".home.arpa"],
        "block_hosts": [],
        "forwarder_hosts": [],
        "hosts": {},
    }


# ─── Ask all questions ────────────────────────────────────────────────────────

def ask_all() -> dict:
    """Ask all questions upfront, return answers dict."""
    answers = {}

    print()
    print(bold("  ╔══════════════════════════════════════════╗"))
    print(bold("  ║     lray — Setup Wizard              ║"))
    print(bold("  ╚══════════════════════════════════════════╝"))
    print()
    print(dim("  Answer a few questions. Then everything will be generated for you."))

    if CONFIG_PATH.exists():
        if not prompt_yes_no("config.json exists. Overwrite?", default=False):
            print(dim("  Cancelled."))
            sys.exit(0)

    # ── Step 1: Exit Mode (ask first so we know what keys are needed) ─────────
    print_step(1, "Exit Mode")
    print(dim("  How should traffic exit to the internet?"))
    print()
    print(dim("  1. gas        — GAS fetches directly (simplest)"))
    print(dim("  2. cfw        — GAS → Cloudflare Worker"))
    print(dim("  3. vps        — GAS → VPS (self-hosted exit)"))
    print(dim("  4. cfw_vps    — GAS → Worker → VPS"))
    print()
    mode_choice = prompt("Choose 1-4", default="1")
    mode_map = {"1": "gas", "2": "cfw", "3": "vps", "4": "cfw_vps"}
    answers["exit_mode"] = mode_map.get(mode_choice, "gas")
    print(f"  → Exit mode: {green(answers['exit_mode'])}")

    # ── GAS ownership ─────────────────────────────────────────────────────────
    print()
    gas_own = prompt_yes_no("  Is the GAS (Google Apps Script) yours to deploy?", default=True)
    answers["gas_own"] = gas_own

    if not gas_own:
        print(dim("  Someone already set up GAS. Enter their deployment info:"))
        answers["preset_script_id"] = prompt("  Script Deployment ID")

    # ── CFW config ────────────────────────────────────────────────────────────
    if answers["exit_mode"] in ("cfw", "cfw_vps"):
        print()
        print(bold("  Cloudflare Worker:"))
        cfw_own = prompt_yes_no("  Is the Worker yours?", default=True)
        answers["cfw_own"] = cfw_own

        if cfw_own:
            random_name = "relay-" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
            answers["worker_name"] = prompt("  Worker name", default=random_name)
        else:
            answers["worker_name"] = "unused"
            answers["shared_worker_url"] = prompt("  Worker URL (e.g. https://relay-xyz.workers.dev)")
    else:
        answers["cfw_own"] = False
        answers["worker_name"] = "unused"

    # ── VPS config ────────────────────────────────────────────────────────────
    if answers["exit_mode"] in ("vps", "cfw_vps"):
        print()
        print(bold("  VPS / Exit Node:"))
        vps_own = prompt_yes_no("  Is the VPS yours?", default=True)

        if vps_own:
            answers["has_server"] = True
            answers["vps_own"] = True
            answers["server_domain"] = prompt("  Server domain or IP")
            answers["server_ssl"] = prompt_yes_no("  HTTPS/SSL?", default=True)

            if answers["server_ssl"]:
                print()
                print(dim("    SSL: 1=Let's Encrypt  2=Own certificate"))
                answers["ssl_choice"] = prompt("    Choose 1 or 2", default="1")
                if answers["ssl_choice"] == "1":
                    answers["ssl_mode"] = "letsencrypt"
                    answers["letsencrypt_email"] = prompt("    Email for Let's Encrypt")
                    answers["ssl_cert_file"] = "./certs/fullchain.pem"
                    answers["ssl_key_file"] = "./certs/privkey.pem"
                    answers["http_port"] = "80"
                else:
                    answers["ssl_mode"] = "own"
                    answers["letsencrypt_email"] = ""
                    answers["ssl_cert_file"] = prompt("    Cert file path", default="./certs/fullchain.pem")
                    answers["ssl_key_file"] = prompt("    Key file path", default="./certs/privkey.pem")
                    answers["http_port"] = prompt("    HTTP port", default="80")

                answers["server_port"] = prompt("    HTTPS port", default="443")
                answers["also_http"] = prompt_yes_no("    Also listen on HTTP?", default=True)
            else:
                answers["ssl_mode"] = "none"
                answers["letsencrypt_email"] = ""
                answers["ssl_cert_file"] = ""
                answers["ssl_key_file"] = ""
                answers["server_port"] = prompt("    HTTP port", default="8080")
                answers["http_port"] = answers["server_port"]
                answers["also_http"] = True
        else:
            answers["has_server"] = False
            answers["vps_own"] = False
            answers["shared_vps_url"] = prompt("  VPS URL (e.g. https://their-server.com)")
            answers["shared_vps_key"] = prompt("  Auth key for that VPS")
    else:
        answers["has_server"] = False
        answers["vps_own"] = False

    # ── Step 2: Auth Keys ─────────────────────────────────────────────────────
    print_step(2, "Authentication Keys")

    if not gas_own and not answers.get("cfw_own") and not answers.get("vps_own"):
        # Everything is someone else's — just need the GAS auth key
        auth_key = prompt("Auth key (from whoever set up GAS)")
        while len(auth_key) < 32:
            print(red("  Must be at least 32 characters!"))
            auth_key = prompt("Auth key")
        answers["auth_key"] = auth_key
        answers["key_gas"] = auth_key
        answers["key_worker"] = auth_key
        answers["key_vps"] = answers.get("shared_vps_key", auth_key)
    else:
        auth_key = random_auth_key()
        print(f"  Generated: {green(auth_key)}")
        print()
        if not prompt_yes_no("Use this key?", default=True):
            auth_key = prompt("Enter your own key (min 32 chars)")
            while len(auth_key) < 32:
                print(red("  Must be at least 32 characters!"))
                auth_key = prompt("Enter your own key (min 32 chars)")
        answers["auth_key"] = auth_key

        # Separate keys?
        print()
        separate_keys = prompt_yes_no("Separate keys per segment?", default=False)
        if separate_keys:
            answers["key_gas"] = prompt("Key: Client → GAS", default=auth_key)
            answers["key_worker"] = prompt("Key: GAS → Worker", default=random_auth_key())
            answers["key_vps"] = prompt("Key: GAS/Worker → VPS", default=random_auth_key())
        else:
            answers["key_gas"] = auth_key
            answers["key_worker"] = auth_key
            answers["key_vps"] = auth_key

    # ── Network ───────────────────────────────────────────────────────────────
    print_step(3, "Local Proxy")
    answers["lan_sharing"] = prompt_yes_no("Share with other devices on network (LAN)?", default=False)
    answers["listen_host"] = "0.0.0.0" if answers["lan_sharing"] else "127.0.0.1"
    answers["listen_port"] = prompt("HTTP proxy port", default="8085")
    answers["socks5_enabled"] = prompt_yes_no("Enable SOCKS5?", default=True)
    if answers["socks5_enabled"]:
        answers["socks5_port"] = prompt("SOCKS5 port", default="1080")
    else:
        answers["socks5_port"] = "1080"

    # ── Dashboard ─────────────────────────────────────────────────────────────
    print()
    answers["dashboard_enabled"] = prompt_yes_no("Enable local dashboard?", default=True)
    if answers["dashboard_enabled"]:
        answers["dashboard_port"] = prompt("Dashboard port", default="8087")
        answers["dashboard_auth"] = prompt_yes_no("Protect dashboard with password?", default=False)
        if answers["dashboard_auth"]:
            answers["dashboard_user"] = prompt("Dashboard username", default="admin")
            answers["dashboard_pass"] = prompt("Dashboard password", default=answers.get("key_gas", auth_key))
        else:
            answers["dashboard_user"] = ""
            answers["dashboard_pass"] = ""
    else:
        answers["dashboard_port"] = "8087"
        answers["dashboard_user"] = ""
        answers["dashboard_pass"] = ""

    # ── Instructions mode ────────────────────────────────────────────────────
    print()
    print_step(4, "How do you want the instructions?")
    print(dim("  step-by-step = I'll wait for you to do each step before continuing"))
    print(dim("  all-at-once  = Generate everything, show all instructions at the end"))
    print()
    answers["step_by_step"] = prompt_yes_no("Step by step? (no = all at once)", default=True)

    return answers


# ─── Generate everything ──────────────────────────────────────────────────────

def generate(answers: dict):
    """Generate all files into output/ based on answers."""

    step_by_step = answers.get("step_by_step", False)

    print()
    print(bold("  Generating files..."))
    print()

    # Clean dist
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    auth_key = answers["auth_key"]
    key_gas = answers.get("key_gas", auth_key)
    key_worker = answers.get("key_worker", auth_key)
    key_vps = answers.get("key_vps", auth_key)
    worker_url = f"{answers['worker_name']}.workers.dev"
    exit_mode = answers.get("exit_mode", "cfw")

    # ── 1. Upstream Forwarder ─────────────────────────────────────────────────
    forwarder_url = None
    if answers.get("has_server"):
        domain = answers["server_domain"]
        port = answers["server_port"]
        ssl_mode = answers["ssl_mode"]
        use_ssl = answers["server_ssl"]
        protocol = "https" if use_ssl else "http"

        forwarder_url = f"{protocol}://{domain}:{port}/fwd"
        if (use_ssl and port == "443") or (not use_ssl and port == "80"):
            forwarder_url = f"{protocol}://{domain}/fwd"

        # Choose server component based on exit mode
        exit_mode = answers.get("exit_mode", "cfw")
        if exit_mode == "vps":
            # VPS mode: GAS → VPS directly, use self-hosted-exit
            dist_fwd = DIST_DIR / "self-hosted-exit"
            dist_fwd.mkdir()
            source_dir = HERE / "deploy" / "self-hosted-exit"
            server_files = ("exit_node.js", "dashboard.html", "Dockerfile",
                            "docker-compose.yml", "start.sh", "README.md")
            # For VPS mode, forwarder_url is the root (not /fwd)
            forwarder_url = f"{protocol}://{domain}:{port}"
            if (use_ssl and port == "443") or (not use_ssl and port == "80"):
                forwarder_url = f"{protocol}://{domain}"
        else:
            # CFW_VPS mode: Worker → VPS, use upstream_forwarder
            dist_fwd = DIST_DIR / "upstream_forwarder"
            dist_fwd.mkdir()
            source_dir = HERE / "deploy" / "upstream_forwarder"
            server_files = ("upstream_forwarder.js", "dashboard.html", "Dockerfile",
                            "docker-compose.yml", "dynamic.yml", "start.sh",
                            "README.md", ".gitignore")

        # Collect all files for the zip
        zip_files = {}
        for filename in server_files:
            src = source_dir / filename
            if src.exists():
                content = src.read_bytes().replace(b"\r\n", b"\n")
                zip_files[filename] = content

        # Generate .env
        # If we have a merged env from update mode, use that (preserves user values + adds new keys)
        if "_merged_env" in answers:
            merged = answers["_merged_env"]
            env_lines = []
            for key, value in merged.items():
                env_lines.append(f"{key}={value}")
            env_content = "\n".join(env_lines) + "\n"
        else:
            http_port = answers.get("http_port", "80")
            also_http = answers.get("also_http", True)
            protocol_mode = "both" if (use_ssl and also_http) else ("https" if use_ssl else "http")

            if exit_mode == "vps":
                # Self-hosted exit .env
                ssl_cert = answers.get("ssl_cert_file", "")
                ssl_key = answers.get("ssl_key_file", "")
                also_http = answers.get("also_http", False)
                http_port = answers.get("http_port", "80")

                if ssl_cert and ssl_key:
                    if also_http:
                        protocol_mode = "both"
                    else:
                        protocol_mode = "https"
                else:
                    protocol_mode = "http"

                env_content = f"""DOMAIN={domain}
AUTH_KEY={key_vps}
PORT={port}
HTTP_PORT={http_port}
HOST=0.0.0.0
PROTOCOL_MODE={protocol_mode}
MAX_BODY_MB=100
FETCH_TIMEOUT_MS=30000
RATE_LIMIT_RPM=300
EXIT_PROXY_URL=
LOG_REQUESTS=true
DASHBOARD_USER=
DASHBOARD_PASS=
SSL_CERT_FILE={ssl_cert}
SSL_KEY_FILE={ssl_key}
"""
            else:
                # Upstream forwarder .env (full)
                env_content = f"""DOMAIN={domain}

# Authentication
AUTH_KEY={key_vps}

# Forwarder
FORWARDER_PORT=8787
FORWARDER_REPLICAS=2
MAX_BODY_MB=50
FETCH_TIMEOUT_MS=30000
RATE_LIMIT_RPM=300
LOG_REQUESTS=true

# Protocol
PROTOCOL_MODE={protocol_mode}
HTTP_PORT={http_port}
HTTPS_PORT={port}

# SSL
SSL_MODE={ssl_mode}
LETSENCRYPT_EMAIL={answers.get('letsencrypt_email', '')}
SSL_CERT_FILE={answers.get('ssl_cert_file', './certs/fullchain.pem')}
SSL_KEY_FILE={answers.get('ssl_key_file', './certs/privkey.pem')}

# Limits
MEM_LIMIT=512m
CPU_LIMIT=1.0
CF_IP_WHITELIST=false
EXIT_PROXY_URL=

# Dashboard
DASHBOARD_USER=admin
DASHBOARD_PASS=
"""
        (dist_fwd / ".env").write_text(env_content, newline="\n")

        # Write start.sh separately (for first-time deploy)
        if "start.sh" in zip_files:
            (dist_fwd / "start.sh").write_bytes(zip_files["start.sh"])

        # Create update.zip with all files (including start.sh and .env)
        import zipfile
        zip_path = dist_fwd / "update.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in zip_files.items():
                zf.writestr(name, content)
            # .env also in zip
            zf.writestr(".env", env_content)

        print(f"  ✓ output/{'self-hosted-exit' if exit_mode == 'vps' else 'upstream_forwarder'}/")
        print(f"    ├── start.sh      (entry point — run this)")
        print(f"    ├── update.zip    (all files, auto-extracted on first run)")
        print(f"    └── .env          (your config — never overwritten by updates)")

    # ── 2. Cloudflare Worker (only for cfw/cfw_vps) ─────────────────────────────
    if exit_mode in ("cfw", "cfw_vps"):
        dist_worker = DIST_DIR / "cloudflare-worker"
        dist_worker.mkdir()

        if WORKER_TEMPLATE.exists():
            code = WORKER_TEMPLATE.read_text(encoding="utf-8")
            code = code.replace(
                'const WORKER_URL = "myworker.workers.dev";',
                f'const WORKER_URL = "{worker_url}";',
            )

            # Hardcode forwarder URL + auth key into the worker code
            if forwarder_url and exit_mode == "cfw_vps":
                code = code.replace(
                    f'const WORKER_URL = "{worker_url}";\nconst DEFAULT_UPSTREAM_TIMEOUT_MS = 25000;',
                    f'const WORKER_URL = "{worker_url}";\n'
                    f'const DEFAULT_UPSTREAM_TIMEOUT_MS = 25000;\n'
                    f'\n'
                    f'// Hardcoded by setup wizard\n'
                    f'const _FORWARDER_URL = "{forwarder_url}";\n'
                    f'const _FORWARDER_KEY = "{key_vps}";',
                )
                code = code.replace(
                    '    const single = env.UPSTREAM_FORWARDER_URL || "";',
                    '    const single = env.UPSTREAM_FORWARDER_URL || _FORWARDER_URL || "";',
                )
                code = code.replace(
                    '    const authKey = env.UPSTREAM_AUTH_KEY || "";',
                    '    const authKey = env.UPSTREAM_AUTH_KEY || _FORWARDER_KEY || "";',
                )
        else:
            code = f'const WORKER_URL = "{worker_url}";\n// Template not found'

        # Obfuscate
        from code_obfuscator import obfuscate_worker
        code = obfuscate_worker(code)

        (dist_worker / "worker.js").write_text(code, encoding="utf-8")
        print(f"  ✓ output/cloudflare-worker/worker.js (obfuscated)")

    # ── 3. Google Apps Script ─────────────────────────────────────────────────
    if answers.get("gas_own", True):
        dist_gas = DIST_DIR / "gas"
        dist_gas.mkdir()

        exit_mode = answers.get("exit_mode", "cfw")

        if GAS_TEMPLATE.exists():
            gas_code = GAS_TEMPLATE.read_text(encoding="utf-8")
            gas_code = gas_code.replace(
                'const AUTH_KEY = "STRONG_SECRET_KEY";',
                f'const AUTH_KEY = "{key_gas}";',
            )
            gas_code = gas_code.replace(
                'const MODE = "cfw";',
                f'const MODE = "{exit_mode}";',
            )
            if exit_mode in ("cfw", "cfw_vps"):
                gas_code = gas_code.replace(
                    '"https://worker1.workers.dev"',
                    f'"https://{worker_url}"',
                )
            else:
                gas_code = gas_code.replace(
                    '"https://worker1.workers.dev"',
                    '// "https://worker.workers.dev"  // not used in this mode',
                )
            if exit_mode in ("vps", "cfw_vps") and forwarder_url:
                vps_base = forwarder_url.replace("/fwd", "")
                gas_code = gas_code.replace(
                    '// "https://your-vps.com",',
                    f'"{vps_base}",',
                )
        else:
            gas_code = f'const AUTH_KEY = "{key_gas}";\nconst MODE = "{exit_mode}";\n// Template not found'

        # Obfuscate
        from code_obfuscator import obfuscate_gas
        gas_code = obfuscate_gas(gas_code)

        (dist_gas / "Code.gs").write_text(gas_code, encoding="utf-8")
        print(f"  ✓ output/gas/Code.gs (mode: {exit_mode}, obfuscated)")
    else:
        print(f"  ⏭ Skipping GAS (using existing deployment)")

    # ── 4. config.json ────────────────────────────────────────────────────────
    # ── Build nested config ─────────────────────────────────────────────────────
    lan_sharing = answers.get("lan_sharing", False)
    listen_host = "0.0.0.0" if lan_sharing else "127.0.0.1"

    try:
        http_port = int(answers["listen_port"])
    except (ValueError, KeyError):
        http_port = 8085

    socks5_enabled = answers.get("socks5_enabled", True)
    try:
        socks5_port = int(answers.get("socks5_port", 1080))
    except ValueError:
        socks5_port = 1080

    dashboard_enabled = answers.get("dashboard_enabled", True)
    try:
        dashboard_port = int(answers.get("dashboard_port", 8087))
    except ValueError:
        dashboard_port = 8087
    dashboard_user = answers.get("dashboard_user", "")
    dashboard_pass = answers.get("dashboard_pass", "")

    cfg = {
        "mode": "apps_script",
        "exit_mode": answers.get("exit_mode", "gas"),
        "auth_key": key_gas,
        "script_id": answers.get("preset_script_id", "PASTE_YOUR_DEPLOYMENT_ID_HERE"),

        "relay": {
            "google_ip": "216.239.38.120",
            "front_domain": "www.google.com",
            "timeout": 25,
            "parallel_relay": 1,
        },

        "proxies": {
            "lan_sharing": lan_sharing,
            "listeners": [
                {"port": http_port, "type": "mixed", "mode": "smart"},
            ] + ([{"port": socks5_port, "type": "socks5", "mode": "smart"}] if socks5_enabled else []),
        },

        "dashboard": {
            "enabled": dashboard_enabled,
            "port": dashboard_port,
            "user": dashboard_user,
            "pass": dashboard_pass,
        },

        "pac": {
            "enabled": True,
            "port": 8086,
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
            "log_level": "INFO",
            "patterniha_sync": True,
            "hosts": {},
        },
    }

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_suffix(".json.bak"))

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"  ✓ config.json")

    print()
    print(green("  ══════════════════════════════════════════"))
    print(green("  ✓  All files generated!"))
    print(green("  ══════════════════════════════════════════"))

    # ── Instructions ──────────────────────────────────────────────────────────

    if step_by_step:
        _instructions_step_by_step(answers, cfg, auth_key, worker_url, forwarder_url)
    else:
        _instructions_all_at_once(answers, cfg, auth_key, worker_url, forwarder_url)


def _wait(msg: str = "Done? Press Enter to continue..."):
    """Wait for user in step-by-step mode."""
    try:
        input(f"\n  {dim(msg)}")
    except EOFError:
        pass
    print()


def _instructions_step_by_step(answers, cfg, auth_key, worker_url, forwarder_url):
    """Guide user through each step, waiting between them."""

    step = 1

    # ── Deploy forwarder ──────────────────────────────────────────────────────
    if answers.get("has_server"):
        exit_mode = answers.get("exit_mode", "cfw")
        folder_name = "self-hosted-exit" if exit_mode == "vps" else "upstream_forwarder"
        print()
        print(bold(f"  ━━━ Step {step}: Deploy exit node on your server ━━━"))
        print()
        print(f"  Copy the folder {cyan(f'output/{folder_name}/')} to your server.")
        print(f"  Then on the server run:")
        print()
        print(f"    {cyan('chmod +x start.sh')}")
        print(f"    {cyan('./start.sh')}")
        print()
        print(dim("  It will build and start Docker containers automatically."))
        _wait("Did you deploy it? Press Enter...")
        step += 1

    # ── Deploy Worker (only for cfw/cfw_vps modes) ──────────────────────────────
    exit_mode = answers.get("exit_mode", "cfw")
    if exit_mode in ("cfw", "cfw_vps"):
        print()
        print(bold(f"  ━━━ Step {step}: Deploy Cloudflare Worker ━━━"))
        print()
        print(f"  1. Open {cyan('https://dash.cloudflare.com/')}")
        print(f"  2. Go to: {bold('Compute (Workers & Pages)')} → Create")
        print(f"  3. Click {bold('Start with Hello World')} → Deploy")
        print(f"  4. Click {bold('Edit code')}")
        print(f"  5. Delete all code, paste contents of:")
        print(f"     {cyan('output/cloudflare-worker/worker.js')}")
        print(f"  6. Click {bold('Deploy')}")
        if forwarder_url:
            print()
            print(green("  ✓ Forwarder URL and auth key are already embedded in the code."))
            print(dim("    No need to set environment variables manually."))
        _wait("Did you deploy the Worker? Press Enter...")
        step += 1

    # ── Deploy GAS ────────────────────────────────────────────────────────────
    print()
    print(bold(f"  ━━━ Step {step}: Deploy Google Apps Script ━━━"))
    print()
    print(f"  1. Open {cyan('https://script.google.com/')}")
    print(f"  2. Click {bold('New project')}")
    print(f"  3. Delete all code, paste contents of:")
    print(f"     {cyan('output/gas/Code.gs')}")
    print(f"  4. Click {bold('Deploy')} → {bold('New deployment')}")
    print(f"  5. Type: {bold('Web app')}")
    print(f"     Execute as: {bold('Me')}")
    print(f"     Who has access: {bold('Anyone')}")
    print(f"  6. Click Deploy")
    print(f"  7. Copy the {bold('Deployment ID')}")
    print()

    script_id = prompt("Paste the Deployment ID here")
    cfg["script_id"] = script_id

    # Re-write config with actual script_id
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(green(f"  ✓ config.json updated with script_id"))
    step += 1

    # ── Start proxy ───────────────────────────────────────────────────────────
    print()
    print(bold(f"  ━━━ Step {step}: Start the proxy ━━━"))
    print()
    print(f"  Run: {cyan('python main.py')}")
    print()

    _host = "0.0.0.0" if cfg["proxies"]["lan_sharing"] else "127.0.0.1"
    _listeners = cfg["proxies"].get("listeners", [])
    _dash_port = cfg["dashboard"]["port"]
    _pac_port = cfg["pac"]["port"]

    for l in _listeners:
        ltype = l.get("type", "mixed").upper()
        if ltype == "MIXED":
            ltype = "HTTP/SOCKS5"
        print(f"  {ltype}:  {_host}:{l['port']} (mode={l.get('mode','smart')})")
    print(f"  PAC URL:     http://{_host}:{_pac_port}/proxy.pac")
    print(f"  Dashboard:   http://{_host}:{_dash_port}/dashboard")
    print()
    print(green("  🎉 Setup complete! Enjoy your freedom."))
    print()
    print(bold("  ─── Dashboard Access ───"))
    print(f"  Local:      http://{_host}:{_dash_port}/dashboard")
    if answers.get("has_server"):
        domain = answers["server_domain"]
        port = answers["server_port"]
        protocol = "https" if answers["server_ssl"] else "http"
        print(f"  Server:     {protocol}://{domain}:{port}/dashboard")
        print(f"              password: AUTH_KEY (or set DASHBOARD_USER/PASS in .env)")
    exit_mode = answers.get("exit_mode", "cfw")
    if exit_mode in ("cfw", "cfw_vps"):
        print(f"  Worker:     https://{worker_url}/dashboard")
        print(f"              password: AUTH_KEY")
    print()


def _instructions_all_at_once(answers, cfg, auth_key, worker_url, forwarder_url):
    """Show all instructions at once without waiting."""

    print()
    step = 1

    if answers.get("has_server"):
        exit_mode = answers.get("exit_mode", "cfw")
        folder_name = "self-hosted-exit" if exit_mode == "vps" else "upstream_forwarder"
        print(bold(f"  Step {step}: Deploy exit node"))
        print(f"    scp -r output/{folder_name}/ user@server:/opt/exit/")
        print(f"    ssh server 'cd /opt/exit && chmod +x start.sh && ./start.sh'")
        print()
        step += 1

    exit_mode = answers.get("exit_mode", "cfw")
    if exit_mode in ("cfw", "cfw_vps"):
        print(bold(f"  Step {step}: Deploy Cloudflare Worker"))
        print(f"    → {cyan('https://dash.cloudflare.com/')} → Workers → Create → Edit code")
        print(f"    → Paste: output/cloudflare-worker/worker.js → Deploy")
        if forwarder_url:
            print(f"    → Forwarder URL + auth key are already in the code ✓")
        print()
        step += 1

    print(bold(f"  Step {step}: Deploy Google Apps Script"))
    print(f"    → {cyan('https://script.google.com/')} → New project")
    print(f"    → Paste: output/gas/Code.gs → Deploy as Web app")
    print(f"    → Copy Deployment ID → edit config.json → replace script_id")
    print()
    step += 1

    print(bold(f"  Step {step}: Start"))
    print(f"    {cyan('python main.py')}")
    print()

    _host = "0.0.0.0" if cfg["proxies"]["lan_sharing"] else "127.0.0.1"
    _listeners = cfg["proxies"].get("listeners", [])
    _dash_port = cfg["dashboard"]["port"]
    _pac_port = cfg["pac"]["port"]

    for l in _listeners:
        ltype = l.get("type", "mixed").upper()
        if ltype == "MIXED":
            ltype = "HTTP/SOCKS5"
        print(f"    {ltype}:    {_host}:{l['port']} (mode={l.get('mode','smart')})")
    print(f"    PAC:       http://{_host}:{_pac_port}/proxy.pac")
    print(f"    Dashboard: http://{_host}:{_dash_port}/dashboard")
    print()


# ─── Update mode ──────────────────────────────────────────────────────────────

# All .env keys that should exist — if missing, they'll be added with defaults
_ENV_DEFAULTS = {
    "DOMAIN": "example.com",
    "AUTH_KEY": "",
    "FORWARDER_PORT": "8787",
    "FORWARDER_REPLICAS": "2",
    "MAX_BODY_MB": "50",
    "FETCH_TIMEOUT_MS": "30000",
    "RATE_LIMIT_RPM": "300",
    "LOG_REQUESTS": "true",
    "PROTOCOL_MODE": "auto",
    "HTTP_PORT": "80",
    "HTTPS_PORT": "443",
    "SSL_MODE": "letsencrypt",
    "LETSENCRYPT_EMAIL": "",
    "SSL_CERT_FILE": "./certs/fullchain.pem",
    "SSL_KEY_FILE": "./certs/privkey.pem",
    "MEM_LIMIT": "512m",
    "CPU_LIMIT": "1.0",
    "CF_IP_WHITELIST": "false",
    "EXIT_PROXY_URL": "",
    "DASHBOARD_USER": "admin",
    "DASHBOARD_PASS": "",
}


def update_dist():
    """Re-generate output/ using existing .env (preserving user values, adding new keys)."""

    print()
    print(bold("  🔄 Update mode"))
    print()

    # ── Find existing .env ────────────────────────────────────────────────────
    dist_env_path = DIST_DIR / "upstream_forwarder" / ".env"
    deploy_env_path = HERE / "deploy" / "upstream_forwarder" / ".env"

    env_path = None
    if dist_env_path.exists():
        env_path = dist_env_path
        print(f"  Found: output/upstream_forwarder/.env")
    elif deploy_env_path.exists():
        env_path = deploy_env_path
        print(f"  Found: deploy/upstream_forwarder/.env")

    # ── Find config.json ──────────────────────────────────────────────────────
    if CONFIG_PATH.exists():
        print(f"  Found: config.json")
        with CONFIG_PATH.open() as f:
            cfg = json.load(f)
    else:
        cfg = {}

    auth_key = cfg.get("auth_key", "")

    # ── Read existing .env values ─────────────────────────────────────────────
    existing_env = {}
    if env_path:
        existing_env = _parse_env_file(env_path)
        if not auth_key:
            auth_key = existing_env.get("AUTH_KEY", "")

    if not auth_key:
        print(red("  ❌ No AUTH_KEY found in config.json or .env"))
        print(red("     Run 'python setup.py' for full setup first."))
        return 1

    # ── Merge: keep existing values, add new keys with defaults ───────────────
    merged_env = dict(existing_env)
    new_keys = []
    for key, default in _ENV_DEFAULTS.items():
        if key not in merged_env:
            if key == "AUTH_KEY":
                merged_env[key] = auth_key
            else:
                merged_env[key] = default
            new_keys.append(key)

    if new_keys:
        print(f"  Added {len(new_keys)} new config keys: {', '.join(new_keys)}")
    else:
        print(f"  .env is up to date (no new keys)")

    # ── Build answers from merged env ─────────────────────────────────────────
    domain = merged_env.get("DOMAIN", "example.com")
    has_server = domain and domain != "example.com"

    # Support both nested and flat config formats
    proxies = cfg.get("proxies", {})
    if isinstance(proxies, dict) and "http" in proxies:
        # Nested format
        _lan = proxies.get("lan_sharing", False)
        _http_port = proxies.get("http", {}).get("port", 8085)
        _socks_enabled = proxies.get("socks5", {}).get("enabled", True)
        _socks_port = proxies.get("socks5", {}).get("port", 1080)
    else:
        # Flat format (legacy)
        _lan = cfg.get("lan_sharing", False)
        _http_port = cfg.get("listen_port", 8085)
        _socks_enabled = cfg.get("socks5_enabled", True)
        _socks_port = cfg.get("socks5_port", 1080)

    answers = {
        "auth_key": auth_key,
        "has_server": has_server,
        "worker_name": "my-relay",
        "lan_sharing": _lan,
        "listen_port": str(_http_port),
        "socks5_enabled": _socks_enabled,
        "socks5_port": str(_socks_port),
        "step_by_step": False,
    }

    if has_server:
        answers["server_domain"] = domain
        answers["server_ssl"] = merged_env.get("SSL_MODE", "none") != "none"
        answers["server_port"] = merged_env.get("HTTPS_PORT", "443")
        answers["http_port"] = merged_env.get("HTTP_PORT", "80")
        answers["ssl_mode"] = merged_env.get("SSL_MODE", "none")
        answers["letsencrypt_email"] = merged_env.get("LETSENCRYPT_EMAIL", "")
        answers["ssl_cert_file"] = merged_env.get("SSL_CERT_FILE", "./certs/fullchain.pem")
        answers["ssl_key_file"] = merged_env.get("SSL_KEY_FILE", "./certs/privkey.pem")
        answers["also_http"] = merged_env.get("PROTOCOL_MODE", "both") in ("both", "http")

    # Detect worker name from existing dist
    dist_worker_path = DIST_DIR / "cloudflare-worker" / "worker.js"
    if dist_worker_path.exists():
        import re
        content = dist_worker_path.read_text(encoding="utf-8")
        m = re.search(r'const WORKER_URL = "([^"]+)"', content)
        if m:
            answers["worker_name"] = m.group(1).replace(".workers.dev", "")
            print(f"  Worker name: {answers['worker_name']}")

    # Detect exit mode from existing dist structure OR deploy folder OR config
    _cfg_exit_mode = cfg.get("exit_mode", "")
    if _cfg_exit_mode:
        answers["exit_mode"] = _cfg_exit_mode
    elif (DIST_DIR / "self-hosted-exit").exists():
        answers["exit_mode"] = "vps"
    elif (DIST_DIR / "upstream_forwarder").exists() and (DIST_DIR / "cloudflare-worker").exists():
        answers["exit_mode"] = "cfw_vps"
    elif (DIST_DIR / "cloudflare-worker").exists():
        answers["exit_mode"] = "cfw"
    elif (HERE / "deploy" / "self-hosted-exit" / ".env").exists():
        answers["exit_mode"] = "vps"
        answers["has_server"] = True
        # Read domain from self-hosted-exit .env
        exit_env = _parse_env_file(HERE / "deploy" / "self-hosted-exit" / ".env")
        if exit_env.get("DOMAIN") and exit_env["DOMAIN"] != "example.com":
            answers["server_domain"] = exit_env["DOMAIN"]
            merged_env.update(exit_env)
            has_server = True
    elif (HERE / "deploy" / "upstream_forwarder" / ".env").exists() and env_path:
        answers["exit_mode"] = "cfw_vps"
    elif has_server:
        answers["exit_mode"] = "vps"
    else:
        answers["exit_mode"] = "gas"
    print(f"  Exit mode: {answers['exit_mode']}")

    # If exit mode requires a server, ensure has_server is set
    if answers["exit_mode"] in ("vps", "cfw_vps") and not answers.get("has_server"):
        answers["has_server"] = True
        # Use defaults if no server info available
        if "server_domain" not in answers:
            answers["server_domain"] = merged_env.get("DOMAIN", "example.com")
        if "server_port" not in answers:
            answers["server_port"] = merged_env.get("HTTPS_PORT", merged_env.get("PORT", "8443"))
        if "server_ssl" not in answers:
            answers["server_ssl"] = merged_env.get("SSL_MODE", "none") != "none"
        if "ssl_mode" not in answers:
            answers["ssl_mode"] = merged_env.get("SSL_MODE", "none")

    # ── Override .env content with merged values ──────────────────────────────
    # We'll write the merged .env in generate() by passing it through answers
    answers["_merged_env"] = merged_env

    print()
    generate(answers)
    print(green("  ✓ Update complete. Upload update.zip to your server and run ./start.sh"))
    return 0


def _parse_env_file(path: Path) -> dict:
    """Parse a .env file into a dict."""
    result = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    except Exception:
        pass
    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # Check for --update flag
    if "--update" in sys.argv or "update" in sys.argv:
        return update_dist()

    answers = ask_all()
    generate(answers)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print(dim("  Cancelled."))
        sys.exit(130)
