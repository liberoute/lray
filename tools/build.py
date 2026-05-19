#!/usr/bin/env python3
"""
lray Build Script — builds binaries and release packages.

Usage:
    python build.py              Interactive menu
    python build.py --all        Build everything
    python build.py --client     Build client binary only
    python build.py --exit       Build self-hosted-exit package
    python build.py --forwarder  Build upstream-forwarder package
    python build.py --release    Build all + package for GitHub release
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # project root
DIST = HERE / "release"
SRC = HERE / "src"


# ─── Colors ───────────────────────────────────────────────────────────────────

def _c(code, text):
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t): return _c("1", t)
def green(t): return _c("32", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)
def dim(t): return _c("2", t)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def make_zip(folder: Path, output: Path):
    """Zip a folder into output.zip"""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(folder)
                # Ensure LF line endings for text files
                if file.suffix in (".sh", ".js", ".yml", ".json", ".md", ".html", ""):
                    content = file.read_bytes().replace(b"\r\n", b"\n")
                    zf.writestr(str(arcname), content)
                else:
                    zf.write(file, arcname)


# ─── Build Functions ──────────────────────────────────────────────────────────

def build_client():
    """Build client binary with PyInstaller."""
    import platform as plat

    # Import version
    sys.path.insert(0, str(SRC))
    from constants import __version__

    system = plat.system().lower()
    machine = plat.machine().lower()

    # Detect arch
    if "arm" in machine or "aarch" in machine:
        if "64" in machine or "aarch64" in machine:
            arch = "arm64"
        else:
            arch = "armv7"
    else:
        arch = "amd64"

    os_name = {"linux": "linux", "windows": "windows", "darwin": "macos"}.get(system, system)
    ext = ".exe" if system == "windows" else ""
    binary_name = f"lray-{os_name}-{arch}"
    release_name = f"lray-{os_name}-{arch}-v{__version__}"

    print(f"\n  {bold('Building client binary...')}")
    print(f"  Platform: {os_name}-{arch}")
    print()

    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(red("  ❌ PyInstaller not installed. Run: pip install pyinstaller"))
        return False

    # Clean previous build
    for d in (HERE / "build", HERE / "dist"):
        if d.exists():
            shutil.rmtree(d)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", binary_name,
        "--paths", str(SRC),
        "--hidden-import", "h2",
        "--hidden-import", "hpack",
        "--hidden-import", "hyperframe",
        "--hidden-import", "brotli",
        "--hidden-import", "zstandard",
        "--hidden-import", "certifi",
        str(HERE / "cli.py"),
    ]

    result = subprocess.run(cmd, cwd=str(HERE), capture_output=True)

    if result.returncode != 0:
        print(red("  ❌ PyInstaller failed"))
        print(dim(result.stderr.decode()[-500:]))
        return False

    binary = HERE / "dist" / f"{binary_name}{ext}"

    if not binary.exists():
        print(red("  ❌ Binary not found after build"))
        return False

    # Copy to release folder as versioned zip
    ensure_dir(DIST)
    zip_output = DIST / f"{release_name}.zip"
    with zipfile.ZipFile(zip_output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(binary, f"{binary_name}{ext}")

    size_mb = zip_output.stat().st_size / 1024 / 1024
    print(green(f"  ✅ Built: release/{release_name}.zip ({size_mb:.1f} MB)"))
    return True


def build_exit_node():
    """Package self-hosted-exit as update.zip + start.sh."""
    print(f"\n  {bold('Building self-hosted-exit package...')}")

    source = HERE / "deploy" / "self-hosted-exit"
    if not source.exists():
        print(red("  ❌ deploy/self-hosted-exit/ not found"))
        return False

    ensure_dir(DIST)
    out_dir = DIST / "self-hosted-exit"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    # Files to include
    files = ["exit_node.js", "dashboard.html", "Dockerfile",
             "docker-compose.yml", "start.sh", "README.md"]

    # Create update.zip
    zip_path = out_dir / "update.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            src = source / f
            if src.exists():
                content = src.read_bytes().replace(b"\r\n", b"\n")
                zf.writestr(f, content)

    # Copy start.sh separately
    start_sh = source / "start.sh"
    if start_sh.exists():
        content = start_sh.read_bytes().replace(b"\r\n", b"\n")
        (out_dir / "start.sh").write_bytes(content)

    # Create .env.example
    env_example = source / ".env.example"
    if env_example.exists():
        shutil.copy2(env_example, out_dir / ".env.example")

    size_kb = zip_path.stat().st_size / 1024
    print(green(f"  ✅ Self-hosted exit: release/self-hosted-exit/ ({size_kb:.0f} KB)"))
    print(dim(f"     ├── update.zip"))
    print(dim(f"     ├── start.sh"))
    print(dim(f"     └── .env.example"))
    return True


def build_upstream_forwarder():
    """Package upstream-forwarder as update.zip + start.sh."""
    print(f"\n  {bold('Building upstream-forwarder package...')}")

    source = HERE / "deploy" / "upstream_forwarder"
    if not source.exists():
        print(red("  ❌ deploy/upstream_forwarder/ not found"))
        return False

    ensure_dir(DIST)
    out_dir = DIST / "upstream-forwarder"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    # Files to include
    files = ["upstream_forwarder.js", "dashboard.html", "Dockerfile",
             "docker-compose.yml", "dynamic.yml", "start.sh", "README.md", ".gitignore"]

    # Create update.zip
    zip_path = out_dir / "update.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            src = source / f
            if src.exists():
                content = src.read_bytes().replace(b"\r\n", b"\n")
                zf.writestr(f, content)

    # Copy start.sh separately
    start_sh = source / "start.sh"
    if start_sh.exists():
        content = start_sh.read_bytes().replace(b"\r\n", b"\n")
        (out_dir / "start.sh").write_bytes(content)

    # Copy .env.example
    env_example = source / ".env.example"
    if env_example.exists():
        shutil.copy2(env_example, out_dir / ".env.example")

    size_kb = zip_path.stat().st_size / 1024
    print(green(f"  ✅ Upstream forwarder: release/upstream-forwarder/ ({size_kb:.0f} KB)"))
    print(dim(f"     ├── update.zip"))
    print(dim(f"     ├── start.sh"))
    print(dim(f"     └── .env.example"))
    return True


def _sync_readme_version():
    """Update README.md header to match constants.__version__."""
    import re as _re
    sys.path.insert(0, str(SRC))
    from constants import __version__

    readme = HERE / "README.md"
    if not readme.exists():
        return

    content = readme.read_text(encoding="utf-8")
    new_content = _re.sub(r"^# lray v[\d.]+", f"# lray v{__version__}", content, count=1)
    if new_content != content:
        readme.write_text(new_content, encoding="utf-8")
        print(f"  {green('✓')} README.md version synced to v{__version__}")


def build_release():
    """Build everything and create a release-ready folder."""
    print(f"\n  {bold('Building full release...')}")

    # Sync version in README
    _sync_readme_version()

    # Clean
    if DIST.exists():
        shutil.rmtree(DIST)
    ensure_dir(DIST)

    results = {
        "Client binary": build_client(),
        "Self-hosted exit": build_exit_node(),
        "Upstream forwarder": build_upstream_forwarder(),
    }

    # Copy docs
    docs_to_copy = ["README.md", "CHANGELOG.md", "LICENSE", "config.example.json"]
    for f in docs_to_copy:
        src = HERE / f
        if src.exists():
            shutil.copy2(src, DIST / f)

    # Summary
    print(f"\n  {'═' * 40}")
    print(f"  Release folder: {cyan(str(DIST))}")
    print()
    for name, ok in results.items():
        status = green("✅") if ok else red("❌")
        print(f"    {status} {name}")
    print(f"\n  {'═' * 40}")

    # Show tree
    print(f"\n  release/")
    for item in sorted(DIST.rglob("*")):
        if item.is_file():
            rel = item.relative_to(DIST)
            size = item.stat().st_size
            if size > 1024 * 1024:
                s = f"{size / 1024 / 1024:.1f} MB"
            elif size > 1024:
                s = f"{size / 1024:.0f} KB"
            else:
                s = f"{size} B"
            print(f"    {rel}  ({s})")

    return all(results.values())


# ─── Interactive Menu ─────────────────────────────────────────────────────────

def interactive_menu():
    """Show interactive build menu with arrow keys + space to select."""
    import platform as plat

    system = plat.system().lower()
    machine = plat.machine().lower()
    if "arm" in machine or "aarch" in machine:
        arch = "arm64" if ("64" in machine or "aarch64" in machine) else "armv7"
    else:
        arch = "amd64"
    os_name = {"linux": "linux", "windows": "windows", "darwin": "macos"}.get(system, system)
    current = f"{os_name}-{arch}"

    # All build targets
    items = [
        # Clients
        {"key": "linux-amd64", "type": "client", "checked": False},
        {"key": "linux-arm64", "type": "client", "checked": False},
        {"key": "linux-armv7", "type": "client", "checked": False},
        {"key": "windows-amd64", "type": "client", "checked": False},
        {"key": "windows-arm64", "type": "client", "checked": False},
        {"key": "macos-arm64", "type": "client", "checked": False},
        {"key": "macos-amd64", "type": "client", "checked": False},
        # Servers
        {"key": "self-hosted-exit", "type": "server", "checked": False},
        {"key": "upstream-forwarder", "type": "server", "checked": False},
    ]

    # Auto-check current platform
    for item in items:
        if item["key"] == current:
            item["checked"] = True

    cursor = 0

    # Platform-specific key reading
    if sys.platform == "win32":
        import msvcrt

        def read_key():
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H": return "up"
                if ch2 == b"P": return "down"
                return None
            if ch == b" ": return "space"
            if ch == b"\r": return "enter"
            if ch == b"a": return "a"
            if ch == b"q" or ch == b"\x1b": return "quit"
            return None
    else:
        import tty
        import termios

        def read_key():
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    ch2 = sys.stdin.read(1)
                    if ch2 == "[":
                        ch3 = sys.stdin.read(1)
                        if ch3 == "A": return "up"
                        if ch3 == "B": return "down"
                    return "quit"
                if ch == " ": return "space"
                if ch == "\r" or ch == "\n": return "enter"
                if ch == "a": return "a"
                if ch == "q": return "quit"
                return None
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def render():
        # Clear screen
        print("\033[2J\033[H", end="")
        print()
        print(bold("  ╔══════════════════════════════════════╗"))
        print(bold("  ║     lray Build Menu               ║"))
        print(bold("  ╚══════════════════════════════════════╝"))
        print()
        print(dim(f"  ↑↓ move | SPACE toggle | A select all | ENTER build | Q quit"))
        print()

        print(bold("  ── Client Binaries ──"))
        for i, item in enumerate(items):
            if item["type"] == "server" and (i == 0 or items[i-1]["type"] == "client"):
                print()
                print(bold("  ── Server Packages ──"))

            check = green("✓") if item["checked"] else " "
            pointer = cyan("❯") if i == cursor else " "
            label = item["key"]
            if item["key"] == current:
                label += dim(" ← current")

            print(f"  {pointer} [{check}] {label}")

        print()

    # Interactive loop
    while True:
        render()
        key = read_key()

        if key == "up":
            cursor = (cursor - 1) % len(items)
        elif key == "down":
            cursor = (cursor + 1) % len(items)
        elif key == "space":
            items[cursor]["checked"] = not items[cursor]["checked"]
        elif key == "a":
            all_checked = all(i["checked"] for i in items)
            for i in items:
                i["checked"] = not all_checked
        elif key == "enter":
            break
        elif key == "quit":
            print()
            return

    # Build selected
    selected = [i for i in items if i["checked"]]
    if not selected:
        print(red("\n  Nothing selected!"))
        return

    print(f"\n  Building {len(selected)} target(s)...\n")

    for item in selected:
        if item["type"] == "client":
            if item["key"] == current:
                build_client()
            else:
                print(dim(f"  ⚠️  {item['key']}: Can't cross-compile locally. Use GitHub Actions."))
        elif item["key"] == "self-hosted-exit":
            build_exit_node()
        elif item["key"] == "upstream-forwarder":
            build_upstream_forwarder()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        interactive_menu()
    elif "--all" in args or "--release" in args:
        ok = build_release()
        sys.exit(0 if ok else 1)
    elif "--client" in args:
        ok = build_client()
        sys.exit(0 if ok else 1)
    elif "--exit" in args:
        ok = build_exit_node()
        sys.exit(0 if ok else 1)
    elif "--forwarder" in args:
        ok = build_upstream_forwarder()
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
