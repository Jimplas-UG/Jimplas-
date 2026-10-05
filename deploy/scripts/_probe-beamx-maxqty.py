#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
from binance_connector import BinanceConnector, BinanceConfig

env = {}
for line in open('/etc/bilshenz.env'):
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k] = v.strip().strip('"').strip("'")

cfg = BinanceConfig(
    api_key=env.get('BINANCE_API_KEY', ''),
    api_secret=env.get('BINANCE_API_SECRET', ''),
    testnet=True,
)
conn = BinanceConnector(cfg)
for sym in ['BEAMXUSDT', 'AINUSDT', 'GTCUSDT', 'AAVEUSDT']:
    try:
        sp = conn.symbol_spec(sym, pip_size=0.01)
        marks = conn._request('GET', '/fapi/v1/ticker/price', {'symbol': sym}, signed=False)
        px = float(marks.get('price') or 0)
        maxq = float(sp.get('maxQty') or 0)
        step = float(sp.get('stepSize') or 0)
        for label, lev, pct in [('short5', 5, 50), ('long10', 10, 40)]:
            notional = 100 * pct / 100 * lev
            qty = notional / max(px, 1e-12)
            print(f'{sym} {label} px={px} need={qty:.3f} maxQty={maxq} OVER={qty > maxq}')
        print(sym, 'lev', conn.symbol_leverage(sym))
    except Exception as e:
        print(sym, 'ERR', e)
PY
'''

_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err[-2000:])
c.close()
