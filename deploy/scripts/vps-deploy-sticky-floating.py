#!/usr/bin/env python3
"""Deploy sticky floating PnL + permanent history (no on/off wipe during REST cool)."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/binance_connector.py",
    "frontend/lib/liveFloatingPnl.js",
    "frontend/hooks/useBinanceLiveFeed.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/components/TradeResultsCalendar.js",
    "frontend/screens/TradeScreen.js",
]

CMD = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py
echo COMPILE_OK
grep -q '_last_good_account' /opt/bilshenz/binance_trading_system/python/binance_connector.py && echo HAS_STICKY_ACCOUNT
grep -q 'liveFloatingPnl' /opt/bilshenz/frontend/hooks/useBinanceLiveFeed.js && echo HAS_LIVE_FLOAT
grep -q 'keep last-known calendar' /opt/bilshenz/frontend/components/TradeResultsCalendar.js && echo HAS_STICKY_CAL
systemctl restart bilshenz-binance-api
sleep 7
python3 <<'PY'
import json, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
print('health', 'ok', h.get('ok'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
req=urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'X-Bridge-Token': tok})
st=json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
acct=st.get('account') or {}
print('status', 'connected', st.get('connected'), 'stale', st.get('stale'), 'cool', st.get('rest_cool_s'),
      'bal', acct.get('balance'), 'float', acct.get('profit'))
req2=urllib.request.Request('http://127.0.0.1:8766/api/logs?limit=20', headers={'X-Bridge-Token': tok})
lg=json.loads(urllib.request.urlopen(req2, timeout=15).read().decode())
print('logs', 'ok', lg.get('ok'), 'stale', lg.get('stale'), 'n', len(lg.get('deals') or []))
req3=urllib.request.Request('http://127.0.0.1:8766/api/trade-calendar?days=60', headers={'X-Bridge-Token': tok})
cal=json.loads(urllib.request.urlopen(req3, timeout=20).read().decode())
print('calendar', 'ok', cal.get('ok'), 'stale', cal.get('stale'), 'days', len(cal.get('days') or []), 'total', cal.get('total_pnl'))
PY
systemctl is-active bilshenz-binance-api
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        if not local.exists():
            print("MISSING", rel, file=sys.stderr)
            continue
        data = local.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        remote = f"/opt/bilshenz/{rel}"
        # ensure parent dir for new files
        parent = str(Path(remote).parent)
        try:
            sftp.stat(parent)
        except OSError:
            # mkdir -p via remote
            c.exec_command(f"mkdir -p {parent}")
        with sftp.file(remote, "wb") as f:
            f.write(data)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
