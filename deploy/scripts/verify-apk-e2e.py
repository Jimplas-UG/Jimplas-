#!/usr/bin/env python3
"""E2E verify: manifest + APK download + backend health."""
import hashlib
import json
import os
import sys
import urllib.request

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PORT = int(os.environ.get("DESK_PORT", "8791"))
BASE = f"http://{HOST}:{PORT}"


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "BilshenzVerify/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def head(url: str, timeout: int = 30) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "BilshenzVerify/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def main() -> int:
    failed = 0

    try:
        manifest = json.loads(get(f"{BASE}/download/manifest.json", 30).decode())
    except Exception as e:
        print("FAIL manifest:", e)
        return 1

    if not manifest.get("ok"):
        print("FAIL manifest not ok")
        return 1
    print("OK manifest", manifest.get("versionName"), "b", manifest.get("versionCode"))

    expected_sha = manifest.get("sha256", "")
    expected_size = int(manifest.get("sizeBytes") or 0)
    apk_url = f"{BASE}/download/bilshenz.apk"

    try:
        code = head(apk_url)
        if code != 200:
            print(f"FAIL HEAD {apk_url} -> {code}")
            failed += 1
        else:
            print("OK HEAD apk 200")
    except Exception as e:
        print("FAIL HEAD apk:", e)
        failed += 1

    try:
        data = get(apk_url, 180)
    except Exception as e:
        print("FAIL download apk:", e)
        return 1

    if len(data) != expected_size:
        print(f"FAIL size {len(data)} != expected {expected_size}")
        failed += 1
    else:
        print("OK size", len(data))

    sha = hashlib.sha256(data).hexdigest()
    if expected_sha and sha != expected_sha:
        print(f"FAIL sha256 {sha} != {expected_sha}")
        failed += 1
    else:
        print("OK sha256", sha[:16] + "...")

    if data[:2] != b"PK":
        print("FAIL not a zip/apk")
        failed += 1
    else:
        print("OK zip signature")

    try:
        health = json.loads(get(f"{BASE}/health", 15).decode())
        if not health.get("ok"):
            print("FAIL desk health")
            failed += 1
        else:
            print("OK desk health")
    except Exception as e:
        print("WARN desk health:", e)

    if failed:
        print(f"\nVERIFY_FAILED ({failed})")
        return 1
    print("\nVERIFY_OK — install:", apk_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
