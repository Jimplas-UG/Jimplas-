#!/usr/bin/env python3
"""Pull realized PnL / commission breakdown from VPS Binance keys."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

REMOTE = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(python3 - <<'PY'
import os
print(os.environ.get('BRIDGE_TOKEN') or os.environ.get('DESK_API_KEY') or '')
PY
)
echo ===CAL===
curl -s -H "X-Bridge-Token: $TOKEN" "http://127.0.0.1:8766/api/trade-calendar?days=60"
echo
echo ===LOGS===
curl -s -H "X-Bridge-Token: $TOKEN" "http://127.0.0.1:8766/api/logs?limit=30"
echo
python3 - <<'PY'
import os, time, hmac, hashlib, urllib.request, urllib.parse, json
from collections import defaultdict
key = os.environ.get("BINANCE_API_KEY", "")
secret = os.environ.get("BINANCE_API_SECRET") or os.environ.get("BINANCE_SECRET") or ""
base = os.environ.get("BINANCE_FAPI", "https://fapi.binance.com")
if not key or not secret:
    print("INCOME no_keys")
    raise SystemExit(0)

def get(path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    q = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        base + path + "?" + q + "&signature=" + sig,
        headers={"X-MBX-APIKEY": key},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

start = int((time.time() - 21 * 86400) * 1000)
rows = []
cursor = start
while True:
    chunk = get("/fapi/v1/income", {"startTime": cursor, "limit": 1000})
    if not chunk:
        break
    rows.extend(chunk)
    if len(chunk) < 1000:
        break
    cursor = int(chunk[-1]["time"]) + 1
    if cursor > int(time.time() * 1000):
        break

by = defaultdict(float)
sym = defaultdict(float)
day = defaultdict(float)
for x in rows:
    t = x.get("incomeType") or "?"
    v = float(x.get("income") or 0)
    by[t] += v
    if t in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
        d = time.strftime("%Y-%m-%d", time.gmtime(int(x["time"]) / 1000))
        day[d] += v
    if t == "REALIZED_PNL":
        sym[x.get("symbol") or "?"] += v

print("INCOME_TYPES", dict(sorted(by.items(), key=lambda kv: -abs(kv[1]))))
print("NET_21D", round(sum(by.values()), 4))
print("REALIZED", round(by.get("REALIZED_PNL", 0), 4), "COMMISSION", round(by.get("COMMISSION", 0), 4), "FUNDING", round(by.get("FUNDING_FEE", 0), 4))
print("DAILY", dict(sorted(day.items())))
print("TOP_SYM", sorted(sym.items(), key=lambda kv: abs(kv[1]), reverse=True)[:20])
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(REMOTE, timeout=120)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
