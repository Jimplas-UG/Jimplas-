#!/usr/bin/env python3
"""E2E smoke: desk + bridge health, positions, close path, scanner, APK manifest."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
DESK = int(os.environ.get("DESK_PORT", "8791"))
BRIDGE = int(os.environ.get("BRIDGE_PORT", "8766"))
TOKEN = os.environ.get("BRIDGE_TOKEN", "")


def get(url: str, headers: dict | None = None, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "BilshenzE2E/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(url: str, body: bytes, headers: dict | None = None, timeout: int = 60) -> tuple[int, bytes]:
    h = {"User-Agent": "BilshenzE2E/1.0", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    failed = 0
    bridge_h = {"X-Bridge-Token": TOKEN} if TOKEN else {}

    # Load token from VPS env file when run locally with VPS_PASSWORD script
    if not TOKEN and os.path.isfile("/etc/bilshenz.env"):
        for line in open("/etc/bilshenz.env", encoding="utf-8"):
            if line.startswith("BRIDGE_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
                bridge_h = {"X-Bridge-Token": TOKEN}
                break

    print("==> desk /health")
    code, data = get(f"http://{HOST}:{DESK}/health")
    if code != 200:
        print("FAIL desk health", code)
        failed += 1
    else:
        print("OK", data.decode()[:120])

    print("==> bridge /health")
    code, data = get(f"http://127.0.0.1:{BRIDGE}/health" if HOST == "127.0.0.1" else f"http://{HOST}:{BRIDGE}/health", bridge_h)
    if code != 200:
        code, data = get(f"http://{HOST}:{DESK}/v1/binance/health", bridge_h)
    if code != 200:
        print("FAIL bridge health", code)
        failed += 1
    else:
        j = json.loads(data)
        print("OK connected=", j.get("connected"), "scanner=", j.get("scanner_stream", {}).get("ws_connected"))

    print("==> positions")
    code, data = get(
        f"http://{HOST}:{BRIDGE}/api/positions" if HOST != "157.245.33.42" else f"http://127.0.0.1:{BRIDGE}/api/positions",
        bridge_h,
    )
    if code != 200 and HOST == "157.245.33.42":
        # remote check via direct bridge port
        code, data = get(f"http://{HOST}:{BRIDGE}/api/positions", bridge_h)
    if code != 200:
        print("FAIL positions", code, data[:200])
        failed += 1
    else:
        j = json.loads(data)
        pos = j.get("positions") or []
        print("OK positions", len(pos))
        for p in pos:
            print(
                " ",
                p.get("symbol"),
                p.get("type"),
                p.get("volume"),
                p.get("margin_type"),
            )

    print("==> close rate-limit burst (20x)")
    close_url = f"http://127.0.0.1:{BRIDGE}/api/close" if os.path.isfile("/etc/bilshenz.env") else f"http://{HOST}:{BRIDGE}/api/close"
    if HOST == "157.245.33.42" and not os.path.isfile("/etc/bilshenz.env"):
        close_url = f"http://{HOST}:{BRIDGE}/api/close"
    hits_429 = 0
    for i in range(20):
        code, body = post(close_url, b'{"symbol":"BTCUSDT"}', bridge_h, timeout=15)
        if code == 429:
            hits_429 += 1
    if hits_429 > 0:
        print("FAIL close rate limited", hits_429, "/20")
        failed += 1
    else:
        print("OK no 429 on close burst (may return 400 no position)")

    print("==> manifest")
    code, data = get(f"http://{HOST}:{DESK}/download/manifest.json")
    if code != 200:
        print("FAIL manifest", code)
        failed += 1
    else:
        j = json.loads(data)
        print("OK apk", j.get("versionName"), "present=", j.get("apkPresent"))

    print("==> python tests")
    if os.path.isfile("binance_trading_system/python/run_all_tests.py"):
        import subprocess

        r = subprocess.run([sys.executable, "run_all_tests.py"], cwd="binance_trading_system/python")
        if r.returncode != 0:
            failed += 1
            print("FAIL python tests")
        else:
            print("OK python tests")

    if failed:
        print(f"\nE2E_FAILED ({failed})")
        return 1
    print("\nE2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
