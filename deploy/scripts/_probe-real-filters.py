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
import json, urllib.request

# Use the bot's own public base the connector uses
from binance_connector import BinanceConnector, BinanceConfig
cfg = BinanceConfig(api_key='x', api_secret='y', testnet=True)
print('base', getattr(cfg, 'base_url', None), getattr(cfg, 'futures_base', None))
# inspect defaults
import dataclasses
print(cfg)

# Direct fetch full exchangeInfo for BEAMX from same host bot uses
for base in [
    'https://testnet.binancefuture.com',
    'https://fstream.binancefuture.com',
]:
    try:
        url = base + '/fapi/v1/exchangeInfo'
        data = json.loads(urllib.request.urlopen(url, timeout=30).read())
        syms = {s['symbol']: s for s in data.get('symbols', [])}
        for want in ['BEAMXUSDT','AINUSDT','BTCUSDT']:
            s = syms.get(want)
            if not s:
                print(base, want, 'MISSING'); continue
            filters = {f['filterType']: f for f in s.get('filters', [])}
            print(base, want, 'qtyPrec', s.get('quantityPrecision'),
                  'LOT', filters.get('LOT_SIZE'),
                  'MARKET', filters.get('MARKET_LOT_SIZE'))
        break
    except Exception as e:
        print(base, 'ERR', e)

# Also ask running API via bridge to symbol endpoint
tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
for sym in ['BEAMXUSDT','AINUSDT']:
    req = urllib.request.Request(
        f'http://127.0.0.1:8766/api/symbol/{sym}?pip_size=0.01',
        headers={'Authorization': 'Bearer ' + tok},
    )
    try:
        st = json.loads(urllib.request.urlopen(req, timeout=10).read())
        print('API_SYMBOL', sym, {k: st.get(k) for k in ('stepSize','minQty','maxQty','max_qty','volume_max','quantityPrecision','tickSize') if k in st or True})
        print('API_KEYS', sorted(st.keys())[:40])
    except Exception as e:
        print('API_ERR', sym, e)
PY
'''

_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err[-2000:])
c.close()
