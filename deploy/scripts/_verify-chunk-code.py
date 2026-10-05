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
import inspect
src=inspect.getsource(BinanceConnector.close_position)
print('has_chunk', 'max_cell' in src, 'has_rank', '_close_rank' in src)
# parse filters offline from public
import json, urllib.request
data=json.loads(urllib.request.urlopen('https://testnet.binancefuture.com/fapi/v1/exchangeInfo', timeout=30).read())
for s in data['symbols']:
    if s['symbol']=='PORTALUSDT':
        parsed=BinanceConnector._parse_symbol_filters(BinanceConnector.__new__(BinanceConnector), s)
        print('PORTAL marketMaxQty', parsed.get('marketMaxQty'), 'maxQty', parsed.get('maxQty'))
        break
# recent successful chunk close?
from pathlib import Path
text=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
for ln in text.splitlines():
    if 'closed in' in ln and 'chunk' in ln.lower():
        print(ln)
    if 'PORTAL' in ln and ('04:2' in ln or '04:3' in ln) and ('EXEC' in ln or 'closed' in ln or 'chunk' in ln or 'FILLED' in ln):
        pass
# last 30 PORTAL lines
hits=[ln for ln in text.splitlines() if 'PORTAL' in ln]
for ln in hits[-12:]:
    print(ln[:200])
PY
'''
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
print(e.read().decode('utf-8','replace')[-800:])
c.close()
