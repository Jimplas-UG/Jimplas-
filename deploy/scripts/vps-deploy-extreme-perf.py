#!/usr/bin/env python3
"""Deploy extreme-perf + persistent connection fixes to FRA."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/main.py",
    "frontend/App.js",
    "frontend/hooks/useDeskSession.js",
    "frontend/hooks/useBrokerLiveFeed.js",
    "frontend/hooks/useBinanceLiveFeed.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/contexts/BinanceBridgeContext.js",
    "frontend/components/BinanceStatusStrip.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/components/TradeHistoryPanel.js",
    "frontend/components/TradeResultsCalendar.js",
    "frontend/screens/ScannerScreen.js",
    "frontend/screens/TradeScreen.js",
]

CMD = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile /opt/bilshenz/binance_trading_system/python/main.py
echo COMPILE_OK
systemctl restart bilshenz-binance-api
sleep 6
python3 <<'PY'
import json, urllib.request, time
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
t0=time.perf_counter()
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
print('health_ms', round((time.perf_counter()-t0)*1000,1), 'ok', h.get('ok'), 'cool', h.get('rest_cool_s'), 'connected', h.get('connected'))
t1=time.perf_counter()
st=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'X-Bridge-Token':tok}), timeout=10).read().decode())
print('status_ms', round((time.perf_counter()-t1)*1000,1), 'connected', st.get('connected'), 'link_health', st.get('link_health'), 'cool', st.get('rest_cool_s'))
app=open('/opt/bilshenz/frontend/App.js').read()
print('pollTicks_always', 'pollTicks: true' in app and 'tab !== \'profile\'' not in app.split('useDeskSession')[1][:400])
print('has_TradeHistoryPanel', Path('/opt/bilshenz/frontend/components/TradeHistoryPanel.js').exists())
print('has_link_health_status', 'link_health' in open('/opt/bilshenz/binance_trading_system/python/main.py').read())
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
        with sftp.file(remote, "wb") as f:
            f.write(data)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
