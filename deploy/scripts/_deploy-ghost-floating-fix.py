#!/usr/bin/env python3
"""Deploy ghost-floating / sticky-close UI+API fixes to FRA."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
REMOTE_FE = "/opt/bilshenz/frontend"
PY = f"{REMOTE_PY}/.venv/bin/python"

FILES = [
    ("binance_trading_system/python/main.py", f"{REMOTE_PY}/main.py"),
    ("binance_trading_system/python/binance_connector.py", f"{REMOTE_PY}/binance_connector.py"),
    ("binance_trading_system/python/momentum_scanner.py", f"{REMOTE_PY}/momentum_scanner.py"),
    ("binance_trading_system/python/frozen_strategy.py", f"{REMOTE_PY}/frozen_strategy.py"),
    ("binance_trading_system/python/test_close_orders.py", f"{REMOTE_PY}/test_close_orders.py"),
    ("frontend/lib/liveFloatingPnl.js", f"{REMOTE_FE}/lib/liveFloatingPnl.js"),
    ("frontend/lib/liveFloatingPnl.test.js", f"{REMOTE_FE}/lib/liveFloatingPnl.test.js"),
    ("frontend/hooks/useBinanceLiveFeed.js", f"{REMOTE_FE}/hooks/useBinanceLiveFeed.js"),
    ("frontend/screens/TradeScreen.js", f"{REMOTE_FE}/screens/TradeScreen.js"),
    ("frontend/screens/ScannerScreen.js", f"{REMOTE_FE}/screens/ScannerScreen.js"),
    ("frontend/App.js", f"{REMOTE_FE}/App.js"),
    ("frontend/components/OpenPositionsPanel.js", f"{REMOTE_FE}/components/OpenPositionsPanel.js"),
    ("frontend/components/BinanceBridgePanel.js", f"{REMOTE_FE}/components/BinanceBridgePanel.js"),
    ("frontend/broker/binanceFuturesApi.js", f"{REMOTE_FE}/broker/binanceFuturesApi.js"),
]

CMD = rf"""
set -e
cd {REMOTE_PY}
{PY} -m py_compile main.py binance_connector.py momentum_scanner.py frozen_strategy.py
{PY} test_close_orders.py
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract
assert_frozen_contract()
from binance_connector import BinanceConnector, BinanceConfig
c = BinanceConnector(BinanceConfig())
c._last_good_positions = [{{"symbol": "ORCAUSDT", "volume": 1}}]
c._last_good_account = {{"balance": 100.0, "profit": -9.6, "equity": 90.4}}
c.apply_symbol_positions_snapshot("ORCAUSDT", [])
assert c._last_good_positions == []
assert float(c._last_good_account["profit"]) == 0.0
assert "apply_symbol_positions_snapshot" in open("main.py", encoding="utf-8").read()
assert "positions_cleared" in open("main.py", encoding="utf-8").read()
assert "apply_symbol_positions_snapshot" in open("momentum_scanner.py", encoding="utf-8").read()
print("PY_STICKY_FLAT_OK")
PY
cd {REMOTE_FE}
node lib/liveFloatingPnl.test.js
grep -q heroFloatingPnl screens/TradeScreen.js
grep -q heroFloatingPnl screens/ScannerScreen.js
grep -q 'prev.positions !== next.positions' screens/ScannerScreen.js
grep -q CLOSE_TOMBSTONE_MS hooks/useBinanceLiveFeed.js
grep -q positions_snapshot broker/binanceFuturesApi.js
grep -q heroFloatingPnl components/BinanceBridgePanel.js
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={{'Authorization':'Bearer '+tok}}
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers=H)
pos=json.loads(urllib.request.urlopen(req, timeout=12).read())
items=[p for p in (pos.get('positions') or []) if float(p.get('volume') or 0)>1e-12]
req2=urllib.request.Request('http://127.0.0.1:8766/api/status', headers=H)
st=json.loads(urllib.request.urlopen(req2, timeout=12).read())
acct=st.get('account') or {{}}
print('can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'pos', len(items), 'acct_profit', acct.get('profit'), 'sticky_stale', pos.get('stale'))
assert len(items)==0, items
assert float(acct.get('profit') or 0) == 0.0, acct.get('profit')
print('GHOST_FLOATING_DEPLOY_OK')
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel, remote in FILES:
        sftp.put(str(ROOT / rel), remote)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()


if __name__ == "__main__":
    main()
