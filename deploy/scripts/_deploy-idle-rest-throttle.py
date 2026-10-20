#!/usr/bin/env python3
"""Deploy idle REST throttle — stop flat positionRisk/userTrades stampede → 418."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py momentum_scanner.py main.py
{PY} test_permanent_leak_locks.py 2>&1 | tail -n 20
{PY} - <<'PY'
from binance_connector import (
    POSITIONS_SHARE_S, POSITIONS_SHARE_FLAT_S, RECENT_DEALS_MAX_SYMBOLS, RECENT_DEALS_TTL_S,
    BinanceConnector, BinanceConfig,
)
from momentum_scanner import RECONCILE_IDLE_MS, RECONCILE_INTERVAL_MS
assert POSITIONS_SHARE_S >= 20
assert POSITIONS_SHARE_FLAT_S >= 40
assert RECENT_DEALS_MAX_SYMBOLS <= 5
assert RECONCILE_IDLE_MS >= 60_000
c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
c._note_rest_success("2300", signed=True)
assert c.rest_cooling_left() == 0.0, "hard weight must not engage rest cool"
assert c._weight_pause_left() > 0.0, "hot minute must keep weight pause"
print("THROTTLE_OK share", POSITIONS_SHARE_S, "flat", POSITIONS_SHARE_FLAT_S,
      "deals_max", RECENT_DEALS_MAX_SYMBOLS, "idle_ms", RECONCILE_IDLE_MS,
      "active_ms", RECONCILE_INTERVAL_MS, "pause", round(c._weight_pause_left(),1))
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, time, urllib.request, pathlib
for i in range(15):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    ban=0.0
    p=pathlib.Path('/var/lib/bilshenz/rest-ban.json')
    if p.exists():
        b=json.loads(p.read_text())
        ban=max(0.0, float(b.get('until_epoch') or 0)-time.time())
    print(i, 'cool', h.get('rest_cool_s'), 'can', sc.get('can_execute'),
          'block', sc.get('exec_block'), 'tracked', sc.get('symbols_tracked'),
          'idle_ms', sc.get('reconcile_idle_ms'), 'ban_left', round(ban,1))
    if h.get('connected') and sc.get('symbols_tracked', 0) > 10:
        break
    time.sleep(1)
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        remote = f"/opt/bilshenz/{rel.replace(chr(92), '/')}"
        sftp.put(str(local), remote)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()


if __name__ == "__main__":
    main()
