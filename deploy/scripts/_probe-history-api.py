#!/usr/bin/env python3
"""One-shot probe of /api/logs and /api/trade-calendar on FRA (run on VPS)."""
import json
import urllib.request
from pathlib import Path

d = {}
for line in Path("/etc/bilshenz.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        d[k] = v.strip()
tok = d.get("BRIDGE_TOKEN", "")
H = {"X-Bridge-Token": tok}
base = "http://127.0.0.1:8766"

for path in ("/health", "/api/logs?limit=20", "/api/trade-calendar?days=120"):
    req = urllib.request.Request(base + path, headers=H)
    j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    if path == "/health":
        print("=== health", {k: j.get(k) for k in ("ok", "connected", "rest_cool_s", "warning")})
        continue
    if "deals" in j:
        deals = j.get("deals") or []
        print("===", path, "count", len(deals), "stale", j.get("stale"), "ok", j.get("ok"))
        for x in deals[:10]:
            print(
                " ",
                x.get("time"),
                x.get("symbol"),
                "pnl",
                x.get("profit"),
                "oid",
                x.get("order_id"),
            )
    else:
        days = j.get("days") or []
        print(
            "===",
            path,
            "days",
            len(days),
            "source",
            j.get("source"),
            "since",
            j.get("since"),
            "tz",
            j.get("tz"),
            "total",
            j.get("total_pnl"),
            "stale",
            j.get("stale"),
        )
        for x in days[-15:]:
            print(" ", x)
