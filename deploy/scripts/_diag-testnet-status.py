#!/usr/bin/env python3
"""Pull status/balance/positions/events + margin gate path on FRA testnet."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
for path in /health /api/status /api/positions /api/scanner/snapshot; do
  curl -sS -m 8 -H "Authorization: Bearer $TOK" "http://127.0.0.1:8766$path" -o "/tmp$(echo $path | tr / _).json" -w "$path http=%{http_code}\n"
done
python3 <<'PY'
import json
from pathlib import Path

def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception as e:
        return {'_err': str(e)}

h=load('/tmp_health.json')
st=load('/tmp_api_status.json')
pos=load('/tmp_api_positions.json')
snap=load('/tmp_api_scanner_snapshot.json')

sc=h.get('scanner') or {}
print('HEALTH mode', h.get('mode'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'halted', sc.get('user_exec_halted'))
print('part', sc.get('partition_usd'), 'active', sc.get('active_symbol'), 'last_err', sc.get('last_exec_error'))
print('auth', sc.get('api_auth'))
print('streams tick', (h.get('tick_stream') or {}).get('ws_connected'),
      'scan', (h.get('scanner_stream') or {}).get('ws_connected'),
      'user', (h.get('user_data_stream') or {}).get('ws_connected'))

print('STATUS mode', st.get('mode'), 'testnet', st.get('testnet'), 'connected', st.get('connected'), 'error', st.get('error'))
acc=st.get('account') or {}
print('ACCOUNT', {k:acc.get(k) for k in acc if 'key' not in k.lower() and 'secret' not in k.lower()})
# common balance fields on status
for k in ('balance','available','available_balance','wallet_balance','equity','free_margin','margin_free','usdt'):
    if k in st: print('ST', k, st.get(k))

# walk for USDT numbers
def find_nums(obj, prefix=''):
    if isinstance(obj, dict):
        for k,v in obj.items():
            lk=k.lower()
            if any(x in lk for x in ('bal','avail','margin','equity','wallet','free','unreal')):
                if not isinstance(v,(dict,list)):
                    print('NUM', prefix+k, v)
            if isinstance(v,(dict,list)) and k in ('account','balances','assets','wallet'):
                find_nums(v, prefix+k+'.')
    elif isinstance(obj, list):
        for i,row in enumerate(obj[:10]):
            if isinstance(row, dict) and str(row.get('asset','')).upper() in ('USDT','BUSD',''):
                if 'wallet' in json.dumps(row).lower() or row.get('asset'):
                    print('ROW', row)
find_nums(st)

plist = pos.get('positions') if isinstance(pos, dict) else pos
if not isinstance(plist, list):
    plist = []
openp=[]
for p in plist:
    amt=float(p.get('positionAmt') or p.get('volume') or p.get('qty') or 0)
    if abs(amt)>1e-12:
        openp.append(p)
print('OPEN_POS', len(openp), 'raw', len(plist) if isinstance(plist,list) else type(plist))
for p in openp[:12]:
    print('POS', {k:p.get(k) for k in ('symbol','positionAmt','positionSide','entryPrice','markPrice','leverage','marginType','isolatedWallet','unRealizedProfit','notional')})

print('EVENTS')
for e in (sc.get('execution_events') or [])[:15]:
    print(json.dumps({k:e.get(k) for k in ('ts','symbol','leg','stage','error','quantity','fill_price')}, default=str)[:300])

rows=snap.get('rows') or []
active=[r for r in rows if str(r.get('status')) not in ('Scanning','Closed','') ]
print('ACTIVE_ROWS', len(active))
for r in active[:15]:
    print('ROW', r.get('symbol'), r.get('status'), 'pnl', r.get('unrealizedPnl'), '15m', r.get('pct15m'))
PY

echo '=== recent scanner/exec today ==='
grep -E '2026-10-03.*(scanner SHORT|scanner LONG|EXEC_|insufficient|INVALIDATION|SMART_EXIT|PULLBACK|Remote end|429|418|Invalid symbol|margin)' /var/log/bilshenz/binance-api.log | tail -n 60
'''
_, o, e = c.exec_command(CMD, timeout=50)
out = o.read().decode("utf-8", "replace")
Path(__file__).with_name("_tn-diag2.txt").write_text(out, encoding="utf-8")
print(out.encode("ascii", "replace").decode("ascii")[:15000])
c.close()
