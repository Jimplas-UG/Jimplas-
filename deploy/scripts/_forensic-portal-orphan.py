#!/usr/bin/env python3
"""Emergency forensic: PORTAL orphan long + live rule state on FRA."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request, re, time
from pathlib import Path

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
print('=== HEALTH ===')
print('mode', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('part', sc.get('partition_usd'), 'active', sc.get('active_symbol'), 'halt', sc.get('user_exec_halted'))
print('rule_kernel', sc.get('rule_kernel'))
print('strategy', sc.get('strategy_id'), 'last_err', sc.get('last_exec_error'))

req = urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization': 'Bearer ' + tok})
st = json.loads(urllib.request.urlopen(req, timeout=15).read())
print('testnet', st.get('testnet'), 'bal', (st.get('account') or {}).get('balance'))
pos = st.get('positions') or []
if isinstance(pos, dict):
    pos = pos.get('items') or pos.get('positions') or []
print('=== POSITIONS count', len(pos) if isinstance(pos, list) else type(pos))
for p in (pos if isinstance(pos, list) else [])[:20]:
    if not isinstance(p, dict):
        continue
    print(' POS', {k: p.get(k) for k in ('symbol','side','positionSide','qty','quantity','positionAmt','entry','entryPrice','leverage','marginType','unRealizedProfit','profit')})

# Scanner open strategies
req2 = urllib.request.Request('http://127.0.0.1:8766/api/scanner/snapshot', headers={'Authorization': 'Bearer ' + tok})
try:
    snap = json.loads(urllib.request.urlopen(req2, timeout=12).read())
    print('=== SCANNER SNAP keys', list(snap.keys())[:20])
    for k in ('active','strategies','open','coins','positions'):
        if k in snap:
            v = snap[k]
            print(k, type(v).__name__, (len(v) if hasattr(v,'__len__') else v) )
except Exception as e:
    print('snapshot_err', e)

# Code presence
import inspect
import momentum_scanner as ms
from frozen_strategy import assert_frozen_contract
from rule_kernel import preflight_open, OpenIntent
snapc = assert_frozen_contract()
print('CONTRACT', snapc['strategy_id'])
print('has_rule_intent', 'rule_intent=self._build_rule_intent' in inspect.getsource(ms.MomentumScanner.__init__))
print('has_watchdog', hasattr(ms.MomentumScanner, '_rule_watchdog'))

# Log scrape PORTAL
text = ''
for p in (Path('/var/log/bilshenz/binance-api.log'), Path('/var/log/bilshenz/binance-api.log.1')):
    if p.exists():
        text += p.read_text(errors='replace') + '\n'
# last 6 hours-ish: keep lines with PORTAL
lines = [ln for ln in text.splitlines() if 'PORTAL' in ln]
print('=== PORTAL LOG LINES', len(lines))
for ln in lines[-80:]:
    print(ln[:240])

# Also RULE_KERNEL / orphan / LONG1 / adopt
print('=== RULE/ORPHAN recent ===')
for pat in ('RULE_KERNEL', 'RULE_WATCHDOG', 'orphan', 'PORTALUSDT', 'adopted exchange LONG', 'scanner LONG1 PORTAL', 'scanner SHORT PORTAL', 'EXEC_OK coin=PORTAL', 'EXEC_FAIL coin=PORTAL', 'SIBLING', 'manual'):
    hits = [ln for ln in text.splitlines() if pat in ln]
    print(pat, 'hits', len(hits))
    for ln in hits[-5:]:
        print(' ', ln[:220])
PY
'''

_, o, e = c.exec_command(CMD, timeout=120)
out = o.read().decode('utf-8', 'replace')
err = e.read().decode('utf-8', 'replace')
print(out.encode('ascii', 'replace').decode('ascii'))
if err.strip():
    print('STDERR', err.encode('ascii', 'replace').decode('ascii')[-2000:])
Path(__file__).with_name('_portal-forensic.txt').write_text(out, encoding='utf-8')
c.close()
