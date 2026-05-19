#!/usr/bin/env python3
"""Test install.sh script validity (syntax, vars, structure)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def test_install_sh_exists():
    path = os.path.join(ROOT, "install.sh")
    assert os.path.exists(path), "install.sh not found"
    return True


def test_install_sh_has_shebang():
    path = os.path.join(ROOT, "install.sh")
    with open(path, "rb") as f:
        first_line = f.readline()
    assert first_line.startswith(b"#!/bin/bash"), f"Bad shebang: {first_line}"
    return True


def test_install_sh_has_required_vars():
    path = os.path.join(ROOT, "install.sh")
    content = open(path, encoding="utf-8", errors="replace").read()
    required = ["INSTALL_DIR", "BIN_LINK", "CONFIG_DIR", "LOG_DIR", "REPO"]
    missing = [v for v in required if v + "=" not in content]
    assert not missing, f"Missing vars: {missing}"
    return True


def test_install_sh_no_crlf():
    path = os.path.join(ROOT, "install.sh")
    content = open(path, "rb").read()
    assert b"\r\n" not in content, "install.sh has CRLF line endings (must be LF)"
    return True


def test_install_sh_references_branding():
    """Check install.sh vars match branding.py."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from branding import APP_NAME, INSTALL_DIR, CONFIG_DIR, LOG_DIR, BIN_PATH

    path = os.path.join(ROOT, "install.sh")
    content = open(path, encoding="utf-8", errors="replace").read()

    assert APP_NAME in content, f"APP_NAME '{APP_NAME}' not in install.sh"
    assert INSTALL_DIR in content, f"INSTALL_DIR not in install.sh"
    assert CONFIG_DIR in content, f"CONFIG_DIR not in install.sh"
    assert LOG_DIR in content, f"LOG_DIR not in install.sh"
    return True


def test_branding_consistency():
    """Check branding.py values are consistent."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from branding import APP_NAME, GITHUB_REPO, INSTALL_DIR

    assert len(APP_NAME) > 0
    assert APP_NAME in INSTALL_DIR
    assert APP_NAME in GITHUB_REPO
    return True


def main():
    print()
    print("  Install Script Tests")
    print()

    tests = [
        test_install_sh_exists,
        test_install_sh_has_shebang,
        test_install_sh_has_required_vars,
        test_install_sh_no_crlf,
        test_install_sh_references_branding,
        test_branding_consistency,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1

    print(f"\n  Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
