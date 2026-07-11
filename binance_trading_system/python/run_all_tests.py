#!/usr/bin/env python3
"""Run all Python trading tests before APK release."""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(__file__)
TESTS = [
    "test_execution_engine.py",
    "test_exec_session.py",
    "test_scanner_15m.py",
    "test_exec_integration.py",
    "test_one_pair_isolation.py",
    "test_close_orders.py",
    "test_leverage_policy.py",
    "test_deal_pnl.py",
]


def main() -> int:
    failed = 0
    for name in TESTS:
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            print("SKIP missing", name)
            continue
        print("==>", name)
        r = subprocess.run([sys.executable, path], cwd=ROOT)
        if r.returncode != 0:
            failed += 1
            print("FAILED", name)
        else:
            print("PASSED", name)
    if failed:
        print(f"\n{failed} test suite(s) failed")
        return 1
    print("\nALL_TESTS_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
