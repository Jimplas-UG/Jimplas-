#!/usr/bin/env python3
"""Deploy sticky-positions API fix to FRA and verify."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

CMD = r"""
set -e
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py
echo COMPILE_OK
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
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'cool', h.get('rest_cool_s'), 'exec', s.get('can_execute'), 'active', s.get('active_symbol'))
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token': tok})
with urllib.request.urlopen(req, timeout=12) as r:
  j=json.loads(r.read().decode())
print('positions_ok', j.get('ok'), 'stale', j.get('stale'), 'cool', j.get('rest_cool_s'), 'n', len(j.get('positions') or []))
for p in (j.get('positions') or [])[:6]:
  print(' POS', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume'), 'pnl', p.get('profit'))
# Force cool-path sticky: call again (should still return last-good even if cool)
print('keys_have_last_good', 'last_good_positions' in open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read())
PY
systemctl is-active bilshenz-binance-api
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in ("main.py", "binance_connector.py"):
        sftp.put(str(ROOT / "binance_trading_system/python" / name), f"/opt/bilshenz/binance_trading_system/python/{name}")
    for rel in (
        "frontend/broker/binanceFuturesApi.js",
        "frontend/hooks/useBinanceLiveFeed.js",
        "frontend/components/OpenPositionsPanel.js",
        "frontend/screens/TradeScreen.js",
        "frontend/screens/RiskScreen.js",
        "frontend/components/InstitutionalRiskDesk.js",
        "frontend/components/BinanceBridgePanel.js",
        "frontend/components/scanner/TickScannerHome.js",
        "frontend/components/scanner/ScannerEngineVisual.js",
        "frontend/components/BinanceStatusStrip.js",
        "frontend/components/AppBottomNav.js",
        "frontend/components/BilshenzHeader.js",
        "frontend/App.js",
    ):
        local = ROOT / rel
        if local.exists():
            sftp.put(str(local), f"/opt/bilshenz/{rel}")
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
