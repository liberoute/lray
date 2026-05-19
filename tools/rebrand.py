#!/usr/bin/env python3
"""
Rebrand tool — rename the project everywhere.

Usage:
    python tools/rebrand.py
    python tools/rebrand.py --name my-proxy --repo myuser/my-proxy

Changes:
  - src/branding.py (source of truth)
  - install.sh
  - deploy/systemd/*.service
  - README.md
  - CHANGELOG.md
  - cli.py help text
  - docker-compose.yml
  - Dockerfile
  - run.bat / run.sh
"""

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # project root

sys.path.insert(0, str(HERE / "src"))


def _c(code, text):
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t): return _c("32", t)
def cyan(t): return _c("36", t)
def dim(t): return _c("2", t)
def bold(t): return _c("1", t)


def prompt(question, default=None):
    suffix = f" [{dim(default)}]" if default else ""
    raw = input(f"  {cyan('?')} {question}{suffix}: ").strip()
    return raw or default


def rebrand(new_name: str, new_repo: str):
    """Replace all references to old name with new name."""

    # Read current branding
    from branding import APP_NAME, GITHUB_REPO

    old_name = APP_NAME
    old_repo = GITHUB_REPO

    if new_name == old_name and new_repo == old_repo:
        print("  Nothing to change — same name.")
        return

    print()
    print(f"  Rebranding: {old_name} → {bold(new_name)}")
    print(f"  Repo: {old_repo} → {bold(new_repo)}")
    print()

    # Files to search and replace
    files_to_update = [
        "src/branding.py",
        "install.sh",
        "cli.py",
        "run.bat",
        "run.sh",
        "docker-compose.yml",
        "README.md",
        "CHANGELOG.md",
        "deploy/systemd/lray.service",
        "deploy/systemd/lray@.service",
        "deploy/systemd/env.example",
        "deploy/systemd/README.md",
        ".env.example",
        "docs/getting-started.md",
        "docs/exit-modes.md",
        "docs/server-deploy.md",
        "docs/ssh-tunnel.md",
        "docs/configuration.md",
        "docs/dashboard.md",
        "docs/troubleshooting.md",
        "docs/architecture.md",
        "docs/building.md",
    ]

    count = 0
    for rel_path in files_to_update:
        path = HERE / rel_path
        if not path.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        original = content

        # Replace name variations
        content = content.replace(old_name, new_name)
        content = content.replace(old_name.upper().replace("-", "_"), new_name.upper().replace("-", "_"))
        content = content.replace(old_repo, new_repo)

        if content != original:
            path.write_text(content, encoding="utf-8")
            print(f"  ✓ {rel_path}")
            count += 1

    # Rename service files
    old_service = HERE / "deploy" / "systemd" / f"{old_name}.service"
    new_service = HERE / "deploy" / "systemd" / f"{new_name}.service"
    if old_service.exists() and old_name != new_name:
        old_service.rename(new_service)
        print(f"  ✓ Renamed: {old_name}.service → {new_name}.service")
        count += 1

    old_template = HERE / "deploy" / "systemd" / f"{old_name}@.service"
    new_template = HERE / "deploy" / "systemd" / f"{new_name}@.service"
    if old_template.exists() and old_name != new_name:
        old_template.rename(new_template)
        print(f"  ✓ Renamed: {old_name}@.service → {new_name}@.service")
        count += 1

    print()
    print(green(f"  ✅ Done! {count} files updated."))
    print()
    print(dim(f"  Don't forget to:"))
    print(dim(f"    - Rename the folder if needed"))
    print(dim(f"    - Update GitHub repo settings"))
    print(dim(f"    - Rebuild: python tools/build.py --all"))
    print()


def main():
    print()
    print(bold("  ╔══════════════════════════════════════╗"))
    print(bold("  ║     Rebrand Tool                      ║"))
    print(bold("  ╚══════════════════════════════════════╝"))
    print()

    from branding import APP_NAME, GITHUB_REPO

    print(f"  Current name: {cyan(APP_NAME)}")
    print(f"  Current repo: {cyan(GITHUB_REPO)}")
    print()

    # CLI args
    args = sys.argv[1:]
    new_name = None
    new_repo = None

    for i, arg in enumerate(args):
        if arg == "--name" and i + 1 < len(args):
            new_name = args[i + 1]
        if arg == "--repo" and i + 1 < len(args):
            new_repo = args[i + 1]

    if not new_name:
        new_name = prompt("New project name", default=APP_NAME)
    if not new_repo:
        new_repo = prompt("New GitHub repo (user/name)", default=GITHUB_REPO)

    rebrand(new_name, new_repo)


if __name__ == "__main__":
    main()
