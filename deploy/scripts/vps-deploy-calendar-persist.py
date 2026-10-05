#!/usr/bin/env python3
"""Deploy trade calendar persist + REST-cool income refresh to FRA."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/calendar_pnl.py",
    "binance_trading_system/python/history_cache.py",
    "binance_trading_system/python/trade_history.py",
    "binance_trading_system/python/main.py",
    "frontend/components/TradeResultsCalendar.js",
    "frontend/components/TradeHistoryPanel.js",
    "frontend/lib/tradeCalendarModel.js",
]

VERIFY = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py \
  /opt/bilshenz/binance_trading_system/python/history_cache.py \
  /opt/bilshenz/binance_trading_system/python/trade_history.py \
  /opt/bilshenz/binance_trading_system/python/main.py
grep -q '_fetch_realized_income_rows' /opt/bilshenz/binance_trading_system/python/binance_connector.py && echo HAS_INCOME_PAGINATE
grep -q '_persist_history_cache' /opt/bilshenz/binance_trading_system/python/binance_connector.py && echo HAS_DISK_CACHE
mkdir -p /var/lib/bilshenz
systemctl restart bilshenz-binance-api
sleep 8
systemctl is-active bilshenz-binance-api
python3 <<'PY'
import json, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); d[k.strip()]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
req=urllib.request.Request('http://127.0.0.1:8766/api/trade-calendar?days=120', headers={'X-Bridge-Token':tok})
j=json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
tail=[x for x in (j.get('days') or []) if str(x.get('date',''))>='2026-09-20']
print('CAL_OK', j.get('ok'), 'stale', j.get('stale'), 'source', j.get('source'), 'tz', j.get('tz'))
print('TAIL', json.dumps(tail))
print('CACHE_FILE', __import__('os').path.exists('/var/lib/bilshenz/trade-history-cache.json'))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        if not local.exists():
            print("MISSING", rel, file=sys.stderr)
            continue
        data = local.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        remote = f"/opt/bilshenz/{rel}"
        parent = str(Path(remote).parent)
        try:
            sftp.stat(parent)
        except OSError:
            client.exec_command(f"mkdir -p {parent}")
        with sftp.file(remote, "wb") as f:
            f.write(data)
        print("uploaded", rel)
    sftp.close()
    _, stdout, stderr = client.exec_command(VERIFY, timeout=120)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2500:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
