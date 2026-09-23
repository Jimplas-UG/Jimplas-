#!/usr/bin/env python3
"""Deploy ultra-fast tabs + close reliability fixes to FRA and verify."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

BRIDGE_FILES = (
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/test_close_orders.py",
)

FRONTEND_FILES = (
    "frontend/App.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/hooks/useBinanceLiveFeed.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/screens/TradeScreen.js",
    "frontend/screens/RiskScreen.js",
    "frontend/screens/ScannerScreen.js",
    "frontend/components/InstitutionalRiskDesk.js",
    "frontend/components/scanner/TickScannerHome.js",
    "frontend/components/scanner/ScannerEngineVisual.js",
)

CMD = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py
echo COMPILE_OK
cd /opt/bilshenz/binance_trading_system/python && $VENV test_close_orders.py
echo TESTS_OK
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
print('health_ok', h.get('ok'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
r=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health/ready', timeout=8).read().decode())
print('ready_ok', r.get('ok'), 'ready', r.get('ready'), 'checks', r.get('checks'))
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token': tok})
with urllib.request.urlopen(req, timeout=12) as resp:
  j=json.loads(resp.read().decode())
print('positions_ok', j.get('ok'), 'stale', j.get('stale'), 'n', len(j.get('positions') or []))
src=open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read()
print('has_apply_snapshot', 'apply_symbol_positions_snapshot' in src)
msrc=open('/opt/bilshenz/binance_trading_system/python/main.py').read()
print('has_close_ops', '_close_ops' in msrc and 'close_operation_id' in msrc)
print('has_health_ready', '/health/ready' in msrc)
app=open('/opt/bilshenz/frontend/App.js').read()
print('lazy_tabs', 'risk: false' in app and 'InteractionManager' not in app)
PY
systemctl is-active bilshenz-binance-api
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in BRIDGE_FILES + FRONTEND_FILES:
        local = ROOT / rel
        if not local.exists():
            print(f"MISSING {rel}", file=sys.stderr)
            continue
        remote = f"/opt/bilshenz/{rel}"
        sftp.put(str(local), remote)
        print(f"uploaded {rel}")
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
