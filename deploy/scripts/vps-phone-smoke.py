#!/usr/bin/env python3
"""Phone-path smoke: health + login attach against FRA (no secret echo)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("VPS_HOST", "159.223.29.223")
TOKEN = os.environ.get("BRIDGE_TOKEN", "c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858")
DESK = os.environ.get("DESK_API_KEY", "f44a0e6b7ea7b76418e484d6041e52da")
KEY = os.environ.get("BINANCE_API_KEY", "").strip()
SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()


def req(url: str, method="GET", data=None, headers=None, timeout=20):
    h = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return res.status, json.loads(res.read().decode())


def main() -> int:
    base = f"http://{HOST}:8766"
    desk = f"http://{HOST}:8791"
    print("1) bridge /health")
    st, h = req(f"{base}/health", headers={"X-Bridge-Token": TOKEN})
    print(" ", st, "connected=", h.get("connected"), "mode=", h.get("mode"),
          "exec=", (h.get("scanner") or {}).get("can_execute"))
    print("2) desk /health")
    st, d = req(f"{desk}/health")
    print(" ", st, d)
    print("3) desk proxy /v1/binance/health")
    st, p = req(f"{desk}/v1/binance/health", headers={"Authorization": f"Bearer {DESK}"})
    print(" ", st, "ok=", p.get("ok"), "connected=", p.get("connected"), "mode=", p.get("mode"))
    if KEY and SECRET:
        print("4) POST /api/login mainnet")
        try:
            st, j = req(
                f"{base}/api/login",
                method="POST",
                headers={"X-Bridge-Token": TOKEN},
                data={"api_key": KEY, "api_secret": SECRET, "testnet": False, "auto_detect_env": True},
                timeout=45,
            )
            print(" ", st, "ok=", j.get("ok"), "connected=", j.get("connected"), "testnet=", j.get("testnet"),
                  "error=", j.get("error") or j.get("detail"))
        except urllib.error.HTTPError as e:
            print(" ", "HTTP", e.code, e.read()[:300])
    else:
        print("4) skip login (set BINANCE_API_KEY/SECRET to smoke login)")
    print("SMOKE_OK" if h.get("connected") else "SMOKE_PARTIAL")
    return 0 if h.get("connected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
