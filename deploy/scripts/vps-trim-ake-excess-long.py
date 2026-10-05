#!/usr/bin/env python3
"""Trim AKEUSDT excess LONG back to Short + Long1 + Long2 (2 recovery partitions)."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
python3 <<'PY'
import json, urllib.request

def get(path):
    req = urllib.request.Request(
        f"http://127.0.0.1:8766{path}",
        headers={"X-Bridge-Token": open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")},
    )
    return json.load(urllib.request.urlopen(req, timeout=20))

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8766{path}",
        data=data,
        headers={
            "X-Bridge-Token": open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'"),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=30))

pos = get("/api/positions")
snap = get("/api/scanner/snapshot")
long_qty = 0.0
short_qty = 0.0
for p in pos.get("positions") or []:
    if p.get("symbol") != "AKEUSDT":
        continue
    vol = float(p.get("volume") or 0)
    side = str(p.get("positionSide") or "").upper()
    print("pos", side, vol, p.get("price_open"))
    if side == "LONG":
        long_qty = vol
    if side == "SHORT":
        short_qty = vol
# Expected recovery = ~2 * one long partition. One long fill was ~86k.
# Keep two partitions; trim anything above ~1.15 * (2 * 86500).
one = 86500.0
target = one * 2
excess = max(0.0, long_qty - target)
print("long_qty", long_qty, "target", target, "excess", excess, "short", short_qty)
if excess > 1000:
    # Round down a bit for step safety
    close_vol = float(int(excess))
    print("closing excess LONG", close_vol)
    try:
        r = post("/api/close", {"symbol": "AKEUSDT", "position_side": "LONG", "volume": close_vol})
        print("close", r)
    except Exception as e:
        print("close failed", e)
        import traceback; traceback.print_exc()
else:
    print("no excess trim needed")
pos2 = get("/api/positions")
for p in pos2.get("positions") or []:
    if p.get("symbol") == "AKEUSDT" and float(p.get("volume") or 0) > 0:
        print("after", p.get("positionSide"), p.get("volume"), p.get("price_open"))
snap2 = get("/api/scanner/snapshot")
print("logic", snap2.get("position_logic"))
for b in snap2.get("blocks") or []:
    if b.get("symbol") == "AKEUSDT":
        print("block", b.get("status"), b.get("legs"))
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
