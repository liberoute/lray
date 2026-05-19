#!/usr/bin/env python3
"""
lray CLI — unified command-line interface.

Usage:
    lray                       Start proxy (default)
    lray start                 Start proxy
    lray --config path.json    Start with custom config
    lray setup                 Run setup wizard (from scratch)
    lray setup --rebuild       Re-generate dist/ without questions
    lray update                Check for updates & self-update
    lray test                  Run proxy tests
    lray check                 Validate config.json
    lray status                Show running status
    lray scan                  Find fastest Google IP
    lray install               Install service + CA cert
    lray install --service     Install systemd service only
    lray install --ca          Install CA certificate only
    lray uninstall             Remove everything (service + CA + instructions)
    lray uninstall --service   Remove systemd service only
    lray uninstall --ca        Remove CA certificate only
    lray version               Show version
    lray help                  Show this help
"""

import sys
import os

# Ensure src/ and tools/ are on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
_TOOLS = os.path.join(_HERE, "tools")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)


def main():
    args = sys.argv[1:]

    # No args or starts with -- → run proxy (pass all flags through)
    if not args or args[0].startswith("-"):
        # Auto-setup if first run
        config_path = os.environ.get("DFT_CONFIG", os.path.join(_HERE, "config.json"))
        if not os.path.exists(config_path) and not any(a.startswith("--config") for a in args):
            print()
            print("  Welcome! No config.json found — running setup wizard...")
            print()
            from setup import main as run_setup
            rc = run_setup()
            if rc != 0:
                sys.exit(rc)
            if not os.path.exists(config_path):
                sys.exit(1)

        sys.argv = [sys.argv[0]] + args
        from main import main as run_main
        run_main()
        return

    command = args[0]

    # Handle --config anywhere
    if "--config" in args and command not in ("setup", "update"):
        # Pass through to main.py as -c flag
        sys.argv = [sys.argv[0]] + args[1:]
        idx = args.index("--config")
        if idx + 1 < len(args):
            sys.argv = [sys.argv[0], "-c", args[idx + 1]] + [
                a for i, a in enumerate(args[1:]) if i != idx - 1 and i != idx
            ]
        from main import main as run_main
        run_main()
        return

    if command == "start":
        # Auto-setup if no config exists
        config_path = os.environ.get("DFT_CONFIG", os.path.join(_HERE, "config.json"))
        if not os.path.exists(config_path):
            print()
            print("  No config.json found — running setup wizard first...")
            print()
            from setup import main as run_setup
            rc = run_setup()
            if rc != 0:
                sys.exit(rc)
            if not os.path.exists(config_path):
                print("  Setup cancelled or failed.")
                sys.exit(1)

        sys.argv = [sys.argv[0]] + args[1:]
        from main import main as run_main
        run_main()

    elif command == "setup":
        # Check for --rebuild flag
        if "--rebuild" in args:
            sys.argv = [sys.argv[0], "--update"]
            from setup import main as run_setup
            sys.exit(run_setup())
        else:
            sys.argv = [sys.argv[0]] + args[1:]
            from setup import main as run_setup
            sys.exit(run_setup())

    elif command == "build":
        # Legacy alias for setup --rebuild
        sys.argv = [sys.argv[0], "--update"]
        from setup import main as run_setup
        sys.exit(run_setup())

    elif command == "update":
        _self_update()

    elif command == "scan":
        sys.argv = [sys.argv[0], "--scan"] + args[1:]
        from main import main as run_main
        run_main()

    elif command in ("install-cert", "install_cert"):
        sys.argv = [sys.argv[0], "--install-cert"]
        from main import main as run_main
        run_main()

    elif command in ("uninstall-cert", "uninstall_cert"):
        sys.argv = [sys.argv[0], "--uninstall-cert"]
        from main import main as run_main
        run_main()

    elif command == "install":
        _install(args[1:])

    elif command == "uninstall":
        _uninstall(args[1:])

    elif command == "build":
        _build_binary()

    elif command == "version":
        from constants import __version__
        print(f"lray v{__version__}")

    elif command == "status":
        _show_status()

    elif command == "test":
        sys.argv = [sys.argv[0]] + args[1:]
        from test_proxy import main as run_test
        sys.exit(run_test())

    elif command == "check":
        _check_config()

    elif command == "help" or command == "--help":
        print(__doc__)

    else:
        print(f"Unknown command: {command}")
        print("Run 'lray help' for usage.")
        sys.exit(1)


def _show_status():
    """Show proxy status by checking if ports are listening."""
    import json
    import socket

    config_path = os.environ.get("DFT_CONFIG", os.path.join(_HERE, "config.json"))

    if not os.path.exists(config_path):
        print("❌ config.json not found")
        return

    with open(config_path) as f:
        cfg = json.load(f)

    host = cfg.get("listen_host", "127.0.0.1")
    port = cfg.get("listen_port", 8085)
    socks_port = cfg.get("socks5_port", 1080)

    def check_port(h, p):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((h if h != "0.0.0.0" else "127.0.0.1", p))
            s.close()
            return True
        except Exception:
            return False

    from constants import __version__
    print(f"lray v{__version__}")
    print()

    http_ok = check_port(host, port)
    socks_ok = check_port(host, socks_port) if cfg.get("socks5_enabled") else None

    print(f"  HTTP Proxy  ({host}:{port}):  {'✅ running' if http_ok else '❌ not running'}")
    if socks_ok is not None:
        print(f"  SOCKS5      ({host}:{socks_port}): {'✅ running' if socks_ok else '❌ not running'}")

    pac_port = cfg.get("pac_port", port + 1)
    dash_port = cfg.get("dashboard_port", port + 2)
    pac_ok = check_port(host, pac_port)
    dash_ok = check_port(host, dash_port)

    print(f"  PAC Server  ({host}:{pac_port}): {'✅ running' if pac_ok else '❌ not running'}")
    print(f"  Dashboard   ({host}:{dash_port}): {'✅ running' if dash_ok else '❌ not running'}")
    print()

    if http_ok:
        print("  Status: 🟢 Online")
    else:
        print("  Status: 🔴 Offline")
        print("  Run: lray start")


def _install(flags):
    """Install components: --service, --ca, or both."""
    import subprocess
    import shutil

    if not flags:
        flags = ["--service", "--ca"]

    print()

    if "--service" in flags:
        print("  Installing systemd service...")
        service_src = os.path.join(_HERE, "deploy", "systemd")
        if not os.path.isdir(service_src):
            print("  ❌ deploy/systemd/ not found")
        elif sys.platform != "linux":
            print("  ❌ Systemd only works on Linux")
        elif os.geteuid() != 0:
            print("  ❌ Run as root: sudo lray install --service")
        else:
            # Copy service files
            shutil.copy2(
                os.path.join(service_src, "lray.service"),
                "/etc/systemd/system/lray.service",
            )
            shutil.copy2(
                os.path.join(service_src, "lray@.service"),
                "/etc/systemd/system/lray@.service",
            )
            # Create dirs
            os.makedirs("/etc/lray", exist_ok=True)
            os.makedirs("/var/log/lray", exist_ok=True)
            # Create env file
            env_path = "/etc/lray/env"
            if not os.path.exists(env_path):
                with open(env_path, "w") as f:
                    f.write(f"LRAY_INSTALL_DIR={_HERE}\n")
                    f.write("LRAY_CONFIG=/etc/lray/config.json\n")
                    f.write("LRAY_CA_DIR=/etc/lray/ca\n")
                    f.write("LRAY_LOG_DIR=/var/log/lray\n")
            # Reload
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            print("  ✅ Service installed!")
            print("     Start: systemctl start lray")
            print("     Enable: systemctl enable lray")

    if "--ca" in flags:
        print("  Installing CA certificate...")
        sys.argv = [sys.argv[0], "--install-cert"]
        from main import main as run_main
        try:
            run_main()
        except SystemExit:
            pass

    print()


def _uninstall(flags):
    """Uninstall components: --service, --ca, or everything."""
    import subprocess
    import shutil

    # No flags = uninstall everything
    all_mode = not flags

    print()

    if all_mode or "--service" in flags:
        print("  Removing systemd service...")
        if sys.platform != "linux":
            print("  ❌ Systemd only on Linux")
        elif os.geteuid() != 0:
            print("  ❌ Run as root: sudo lray uninstall")
        else:
            subprocess.run(["systemctl", "stop", "lray"], check=False, capture_output=True)
            subprocess.run(["systemctl", "disable", "lray"], check=False, capture_output=True)
            for f in ("/etc/systemd/system/lray.service", "/etc/systemd/system/lray@.service"):
                if os.path.exists(f):
                    os.remove(f)
            subprocess.run(["systemctl", "daemon-reload"], check=False)
            print("  ✅ Service removed")

    if all_mode or "--ca" in flags:
        print("  Removing CA certificate...")
        sys.argv = [sys.argv[0], "--uninstall-cert"]
        from main import main as run_main
        try:
            run_main()
        except SystemExit:
            pass

    if all_mode:
        print()
        print("  To fully remove lray:")
        print(f"    rm -rf {_HERE}")
        print("    rm -f /usr/local/bin/lray")
        print("    rm -rf /etc/lray")
        print("    rm -rf /var/log/lray")

    print()


def _build_binary():
    """Build standalone binary with PyInstaller."""
    import subprocess

    print()
    print("  Building lray binary...")
    print()

    # Check PyInstaller
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  ❌ PyInstaller not installed.")
        print("     Install: pip install pyinstaller")
        return

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "lray",
        "--paths", "src",
        "--hidden-import", "h2",
        "--hidden-import", "hpack",
        "--hidden-import", "hyperframe",
        "--hidden-import", "brotli",
        "--hidden-import", "zstandard",
        "--hidden-import", "certifi",
        os.path.join(_HERE, "cli.py"),
    ]

    result = subprocess.run(cmd, cwd=_HERE)

    if result.returncode == 0:
        ext = ".exe" if sys.platform == "win32" else ""
        print()
        print(f"  ✅ Built: dist/lray{ext}")
        print(f"     Size: {os.path.getsize(os.path.join(_HERE, 'dist', f'lray{ext}')) / 1024 / 1024:.1f} MB")
    else:
        print("  ❌ Build failed")


def _self_update():
    """Check for updates and self-update."""
    import subprocess
    import urllib.request
    import urllib.error
    import platform

    from constants import __version__

    print()
    print(f"  Current version: v{__version__}")
    print(f"  Checking for updates...")
    print()

    # Detect if running as binary or from source
    is_binary = getattr(sys, 'frozen', False)
    git_dir = os.path.join(_HERE, ".git")
    is_git = os.path.isdir(git_dir)

    # Check latest version from GitHub
    latest = None
    download_url = None
    release_url = None

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/liberoute/lray/releases/latest",
            headers={"User-Agent": "lray-updater"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        import json
        data = json.loads(resp.read())
        latest = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", "")

        # Find matching binary for this platform
        if is_binary:
            system = platform.system().lower()  # linux, windows, darwin
            machine = platform.machine().lower()  # x86_64, amd64, aarch64, arm64
            arch = "arm64" if "arm" in machine or "aarch" in machine else "amd64"
            os_name = {"linux": "linux", "windows": "windows", "darwin": "macos"}.get(system, system)
            target_name = f"lray-{os_name}-{arch}"

            for asset in data.get("assets", []):
                if target_name in asset.get("name", ""):
                    download_url = asset.get("browser_download_url")
                    break

    except Exception as e:
        print(f"  ❌ Couldn't check for updates: {e}")
        return

    if not latest:
        print("  ❌ Couldn't determine latest version")
        return

    if latest == __version__:
        print("  ✅ Already up to date!")
        print()
        return

    print(f"  🆕 New version available: v{latest}")
    print()

    if is_binary:
        # Binary mode: download new binary
        if download_url:
            print(f"  Downloading update...")
            try:
                resp = urllib.request.urlopen(download_url, timeout=60)
                data = resp.read()

                # Save to temp, then replace
                import tempfile
                import tarfile
                import io

                tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")

                # Find the binary in the tar
                exe_name = "lray.exe" if sys.platform == "win32" else "lray"
                for member in tar.getmembers():
                    if member.name.endswith(exe_name):
                        # Extract to temp
                        tmp_path = sys.executable + ".new"
                        with open(tmp_path, "wb") as f:
                            f.write(tar.extractfile(member).read())

                        # Replace current binary
                        old_path = sys.executable + ".old"
                        try:
                            os.replace(sys.executable, old_path)
                            os.replace(tmp_path, sys.executable)
                            os.remove(old_path)
                            print(f"  ✅ Updated to v{latest}!")
                            print(f"     Restart lray to use new version.")
                        except PermissionError:
                            print(f"  ⚠️  Can't replace running binary.")
                            print(f"     New version saved to: {tmp_path}")
                            print(f"     Replace manually and restart.")
                        break
                else:
                    print(f"  ❌ Binary not found in archive")
                    print(f"     Download manually: {release_url}")

            except Exception as e:
                print(f"  ❌ Download failed: {e}")
                print(f"     Download manually: {release_url}")
        else:
            print(f"  No binary found for your platform.")
            print(f"  Download manually: {release_url}")

    elif is_git:
        # Git mode: pull
        try:
            result = subprocess.run(
                ["git", "pull", "--quiet"],
                cwd=_HERE, capture_output=True, timeout=60,
            )
            if result.returncode == 0:
                print(f"  ✅ Updated to v{latest}!")
                print(f"     Run 'lray build' to regenerate dist/")
            else:
                print(f"  ❌ git pull failed. Try manually: git pull")
        except FileNotFoundError:
            print(f"  ❌ git not found.")
            print(f"     Download: {release_url}")

    else:
        # Neither binary nor git — just show link
        print(f"  Download: {release_url}")

    print()


def _check_config():
    """Validate config.json and show issues."""
    import json

    config_path = os.environ.get("DFT_CONFIG", os.path.join(_HERE, "config.json"))

    print()
    print("  Config Check")
    print()

    # Check file exists
    if not os.path.exists(config_path):
        print("  ❌ config.json not found")
        print(f"     Expected at: {config_path}")
        print("     Run: lray setup")
        return

    print(f"  ✓ Found: {config_path}")

    # Parse JSON
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ❌ Invalid JSON: {e}")
        return

    print(f"  ✓ Valid JSON ({len(cfg)} keys)")

    # Check required keys
    errors = 0

    auth_key = cfg.get("auth_key", "")
    if not auth_key or len(auth_key) < 32:
        print("  ❌ auth_key missing or too short (min 32 chars)")
        errors += 1
    elif auth_key in ("CHANGE_ME_TO_A_STRONG_SECRET", "PASTE_YOUR_DEPLOYMENT_ID_HERE"):
        print("  ❌ auth_key is still a placeholder — change it!")
        errors += 1
    else:
        print(f"  ✓ auth_key: {auth_key[:8]}... ({len(auth_key)} chars)")

    script_id = cfg.get("script_id") or cfg.get("script_ids")
    if not script_id:
        print("  ❌ script_id missing")
        errors += 1
    elif script_id == "PASTE_YOUR_DEPLOYMENT_ID_HERE":
        print("  ❌ script_id is placeholder — deploy GAS and paste the ID")
        errors += 1
    else:
        if isinstance(script_id, list):
            print(f"  ✓ script_ids: {len(script_id)} scripts configured")
        else:
            print(f"  ✓ script_id: ...{script_id[-12:]}")

    # Check ports
    port = cfg.get("listen_port", 8085)
    socks = cfg.get("socks5_port", 1080)
    if port == socks:
        print(f"  ❌ listen_port and socks5_port are the same ({port})")
        errors += 1
    else:
        print(f"  ✓ Ports: HTTP={port}, SOCKS5={socks}")

    # Check front_domain
    fd = cfg.get("front_domain", "")
    if fd:
        print(f"  ✓ front_domain: {fd}")
    else:
        print("  ⚠️  front_domain not set (using default www.google.com)")

    # Check google_ip
    gip = cfg.get("google_ip", "")
    if gip:
        print(f"  ✓ google_ip: {gip}")

    # Summary
    print()
    if errors == 0:
        print("  ✅ Config looks good!")
    else:
        print(f"  ❌ {errors} issue(s) found — fix them before starting")
    print()


if __name__ == "__main__":
    main()
