#!/usr/bin/env python3
"""Deploy cool-spam + instant close history fixes to FRA."""
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
    "binance_trading_system/python/calendar_pnl.py",
    "binance_trading_system/python/execution_engine.py",
    "binance_trading_system/python/momentum_scanner.py",
    "frontend/hooks/useBinanceLiveFeed.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/components/scanner/ScannerExecutionPanel.js",
    "frontend/lib/liveFloatingPnl.js",
    "frontend/components/TradeResultsCalendar.js",
    "frontend/components/TradeHistoryPanel.js",
    "frontend/lib/tradeCalendarModel.js",
    "frontend/screens/TradeScreen.js",
    "frontend/lib/dealPnl.js",
    "frontend/screens/TradeScreen.js",
]

CMD = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py \
  /opt/bilshenz/binance_trading_system/python/execution_engine.py \
  /opt/bilshenz/binance_trading_system/python/momentum_scanner.py
echo COMPILE_OK
grep -q 'rest_cooling' /opt/bilshenz/binance_trading_system/python/execution_engine.py && echo HAS_REST_COOLING_STAGE
grep -q 'remember_close_deals' /opt/bilshenz/binance_trading_system/python/binance_connector.py && echo HAS_REMEMBER_CLOSE
grep -q '_deal_symbol_history' /opt/bilshenz/binance_trading_system/python/binance_connector.py && echo HAS_SYM_HIST
grep -q 'deals_head' /opt/bilshenz/binance_trading_system/python/main.py && echo HAS_DEALS_HEAD
grep -q 'rest_cooling' /opt/bilshenz/frontend/components/scanner/ScannerExecutionPanel.js && echo HAS_UI_COOL_DEDUP
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
print('health', h.get('ok'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
st=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'X-Bridge-Token':tok}), timeout=12).read().decode())
print('can_execute', (st.get('scanner') or {}).get('can_execute') if isinstance(st.get('scanner'), dict) else st.get('can_execute'),
      'exec_block', (st.get('scanner') or {}).get('exec_block') if isinstance(st.get('scanner'), dict) else None)
# scanner status via health often embeds scanner
sc=h.get('scanner') or {}
print('scanner_can_exec', sc.get('can_execute'), 'block', sc.get('exec_block'))
ev=sc.get('execution_events') or []
print('events', len(ev))
for e in ev[:3]:
  print(' EVT', e.get('stage'), e.get('symbol'), (e.get('error') or '')[:80])
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
        parent = str(Path(remote).parent)
        try:
            sftp.stat(parent)
        except OSError:
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
