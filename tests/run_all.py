#!/usr/bin/env python3
"""Run all tests. Use before pushing."""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run_test(name, cmd):
    print(f"\n{'═' * 50}")
    print(f"  {name}")
    print(f"{'═' * 50}\n")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode == 0


def main():
    print("\n" + "█" * 50)
    print("  lray — Test Suite")
    print("█" * 50)

    tests = [
        ("Import Check", [sys.executable, "tests/test_imports.py"]),
        ("Install Script", [sys.executable, "tests/test_install.py"]),
        ("Setup Wizard (all modes)", [sys.executable, "tests/test_setup_wizard.py"]),
    ]

    # Proxy test only if config.json exists
    config_path = os.path.join(ROOT, "config.json")
    if os.path.exists(config_path):
        tests.append(("Proxy Connectivity", [sys.executable, "tests/test_proxy.py"]))
    else:
        print("\n  ⚠️  config.json not found — skipping proxy test")
        print("     Run 'lray setup' first\n")

    passed = 0
    failed = 0

    for name, cmd in tests:
        if run_test(name, cmd):
            passed += 1
        else:
            failed += 1

    print(f"\n{'═' * 50}")
    print(f"  Total: {passed} passed, {failed} failed")
    print(f"{'═' * 50}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
