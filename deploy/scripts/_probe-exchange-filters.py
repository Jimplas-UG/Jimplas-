#!/usr/bin/env python3
"""Read LOT_SIZE / MARKET_LOT_SIZE for BEAMX via live API process (session keys)."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")

# Use in-process connector from a tiny import that attaches to nothing — instead hit exchangeInfo public
import urllib.request
for sym in ['BEAMXUSDT','AINUSDT','GTCUSDT']:
    url = f'https://testnet.binancefuture.com/fapi/v1/exchangeInfo?symbol={sym}'
    data = json.loads(urllib.request.urlopen(url, timeout=15).read())
    s = data['symbols'][0]
    filters = {f['filterType']: f for f in s.get('filters', [])}
    lot = filters.get('LOT_SIZE', {})
    mlot = filters.get('MARKET_LOT_SIZE', {})
    print(sym, 'LOT', {k: lot.get(k) for k in ('minQty','maxQty','stepSize')}, 'MARKET', {k: mlot.get(k) for k in ('minQty','maxQty','stepSize')})

# Ask running bot connector symbol_spec via a remote helper using the API service? 
# Inspect live module path for maxQty parsing
from binance_connector import BinanceConnector
import inspect
src = inspect.getsource(BinanceConnector.symbol_spec)
print('symbol_spec has maxQty', 'maxQty' in src)
print('symbol_spec has MARKET', 'MARKET_LOT' in src)
PY
'''

_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err[-1500:])
c.close()
