#!/usr/bin/env python3
"""Probe FRA trade calendar + income for today (Nairobi)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

REMOTE_PROBE = r"""python3 <<'PY'
import json, urllib.request, sys, os
from pathlib import Path
sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
os.chdir("/opt/bilshenz/binance_trading_system/python")
d = {}
for l in Path("/etc/bilshenz.env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1)
        d[k.strip()] = v.strip().strip('"').strip("'")
tok = d.get("BRIDGE_TOKEN", "")
print("TRADE_HISTORY_SINCE", d.get("TRADE_HISTORY_SINCE", ""))
print("TRADE_CALENDAR_TZ", d.get("TRADE_CALENDAR_TZ", ""))
for path in ("/api/trade-calendar?days=120", "/api/logs?limit=40"):
    req = urllib.request.Request(
        f"http://127.0.0.1:8766{path}",
        headers={"X-Bridge-Token": tok},
    )
    j = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    if "days" in j:
        days = j.get("days") or []
        tail = [x for x in days if str(x.get("date", "")) >= "2026-09-20"]
        print(
            "CAL",
            "ok",
            j.get("ok"),
            "stale",
            j.get("stale"),
            "tz",
            j.get("tz"),
            "since",
            j.get("since"),
            "source",
            j.get("source"),
            "ndays",
            len(days),
            "total",
            j.get("total_pnl"),
        )
        print("TAIL", json.dumps(tail))
    else:
        deals = j.get("deals") or []
        print("LOGS", "ok", j.get("ok"), "stale", j.get("stale"), "n", len(deals))
        for dd in deals[:5]:
            print(
                " deal",
                dd.get("time"),
                dd.get("symbol"),
                dd.get("profit"),
                dd.get("realized_pnl"),
            )

try:
    from binance_connector import BinanceConnector, config_from_env
    from calendar_pnl import aggregate_income_days, day_key_from_ms
    from trade_history import include_trade_time

    c = BinanceConnector(config_from_env())
    income = c._request(
        "GET",
        "/fapi/v1/income",
        {"incomeType": "REALIZED_PNL", "limit": 1000},
        signed=True,
    )
    by = aggregate_income_days(income or [], include_trade_time=include_trade_time)
    print("income_rows", len(income or []))
    print("income_days_keys_tail", sorted(by.keys())[-10:])
    today_rows = [
        r
        for r in (income or [])
        if day_key_from_ms(int(r.get("time") or 0)) == "2026-09-25"
    ]
    print("today_2026-09-25_rows", len(today_rows), "sum", round(sum(float(r.get("income") or 0) for r in today_rows), 4))
    print("cool_s", c.rest_cooling_left())
    sticky = getattr(c, "_last_good_calendar", None) or {}
    print("sticky_cal_days", len(sticky.get("days") or []))
    sticky_tail = [x for x in (sticky.get("days") or []) if str(x.get("date", "")) >= "2026-09-20"]
    print("sticky_tail", json.dumps(sticky_tail))
except Exception as e:
    print("connector_probe_error", e)
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    probe_local = ROOT / "deploy" / "scripts" / "_probe-income.py"
    sftp.put(str(probe_local), "/tmp/_probe-income.py")
    sftp.close()
    _, stdout, stderr = client.exec_command(REMOTE_PROBE, timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err[-3000:])
    # grep deployed connector for persist
    _, stdout2, _ = client.exec_command(
        "grep -n 'history_cache\\|calendar_cache\\|persist.*calendar' "
        "/opt/bilshenz/binance_trading_system/python/binance_connector.py | head -5; "
        "ls -la /var/lib/bilshenz/ 2>/dev/null | head -20",
        timeout=30,
    )
    sys.stdout.write("\n=== DEPLOY CHECK ===\n")
    sys.stdout.write(stdout2.read().decode("utf-8", "replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
