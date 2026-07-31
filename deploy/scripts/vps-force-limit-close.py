#!/usr/bin/env python3
"""Force MUSDT LONG close via limit IOC when MARKET hits PERCENT_PRICE."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -euo pipefail
set -a; . /etc/bilshenz.env; set +a
cd /opt/bilshenz/binance_trading_system/python
python3 - <<'PY'
import time, sys
sys.path.insert(0, '.')
from binance_connector import BinanceConnector, config_from_env, round_to_step

c = BinanceConnector(config_from_env())
sym = 'MUSDT'
print('positions_before', c.positions(sym, force=True))
tick = c.book_ticker(sym) or {}
print('tick', tick)
info = c.get_symbol_spec(sym) if hasattr(c, 'get_symbol_spec') else c.symbol_spec(sym)
pos = [p for p in c.positions(sym, force=True) if str(p.get('positionSide') or '').upper()=='LONG' or str(p.get('type') or '').upper()=='BUY']
if not pos:
    print('already_flat')
    raise SystemExit
p = pos[0]
qty = round_to_step(float(p.get('volume') or 0), float(info.get('stepSize') or 1))
bid = float(tick.get('bid') or 0)
ask = float(tick.get('ask') or 0)
mark = bid or ask
tick_sz = float(info.get('tickSize') or 0.0001)
# Walk prices from near-market down until IOC accepts (PERCENT_PRICE band).
prices = []
for mult in (0.995, 0.99, 0.98, 0.97, 0.95, 0.93, 0.90):
    raw = mark * mult
    # round down to tick
    px = int(raw / tick_sz) * tick_sz
    prices.append(float(f'{px:.8f}'))
for px in prices:
    params = {
      'symbol': sym,
      'side': 'SELL',
      'type': 'LIMIT',
      'timeInForce': 'IOC',
      'quantity': qty,
      'price': px,
      'positionSide': 'LONG',
      'newClientOrderId': f'BSV32_FORCE_{int(time.time()*1000)}'[:36],
    }
    print('try', params)
    try:
        resp = c._request_keepalive('POST', '/fapi/v1/order', params, signed=True, timeout=10.0)
        print('resp', resp)
        filled = float(resp.get('executedQty') or 0)
        if filled > 0 or str(resp.get('status') or '').upper() in ('FILLED', 'PARTIALLY_FILLED'):
            break
    except Exception as e:
        print('fail', e)
else:
    for i in range(8):
        time.sleep(2)
        r = c.close_by_position_side(sym, 'LONG', None)
        print('market_retry', i, r)
        if r.get('ok'):
            break
print('positions_after', c.positions(sym, force=True))
# Reset scanner state for MUSDT
try:
    from main import momentum_scanner
except Exception:
    momentum_scanner = None
print('scanner_import_skip' if momentum_scanner is None else 'have_scanner')
PY
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/close-all -d '{}' || true
echo
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print(err, file=sys.stderr)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
