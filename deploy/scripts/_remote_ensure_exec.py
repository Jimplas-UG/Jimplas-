#!/usr/bin/env python3
from pathlib import Path
import json
want = {'BINANCE_TESTNET': '1', 'BINANCE_FORCE_TESTNET': '1', 'BINANCE_FORCE_MAINNET': '0', 'BINANCE_PAPER': '0', 'FORWARD_DRY_RUN': '0', 'SCANNER_EXEC': '1', 'SCANNER_ENABLED': '1'}
p = Path('/etc/bilshenz.env')
lines = p.read_text().splitlines()
out, seen = [], set()
for line in lines:
    if not line or line.lstrip().startswith('#') or '=' not in line:
        out.append(line); continue
    k = line.split('=', 1)[0].strip()
    if k in want:
        out.append(f'{k}={want[k]}'); seen.add(k)
    else:
        out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f'{k}={v}')
DEFAULT_TOKEN = 'c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858'
fixed = False
for i, l in enumerate(out):
    if l.startswith('BRIDGE_TOKEN='):
        val = l.split('=',1)[1].strip().strip('"').strip("'")
        if len(val) < 8:
            out[i] = 'BRIDGE_TOKEN=' + DEFAULT_TOKEN
        fixed = True
        break
if not fixed:
    out.append('BRIDGE_TOKEN=' + DEFAULT_TOKEN)
p.write_text('\n'.join(out) + '\n')
print('env_updated', want)
pj = Path('/opt/bilshenz/frontend/app.json')
j = json.loads(pj.read_text())
expo = j.setdefault('expo', {})
android = expo.setdefault('android', {})
vc = int(android.get('versionCode') or 14) + 1
vn = str(expo.get('version') or '1.4.3')
parts = vn.split('.')
try:
    parts[-1] = str(int(parts[-1]) + 1)
except Exception:
    parts = ['1', '4', '4']
vn = '.'.join(parts)
expo['version'] = vn
android['versionCode'] = vc
pj.write_text(json.dumps(j, indent=2) + '\n')
print(f'version={vn} versionCode={vc}')
