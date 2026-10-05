#!/usr/bin/env python3
"""Read-only: what free/wallet balance FRA bridge sees on testnet vs $100 partition need."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 10 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 12 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status > /tmp/st.json || true
curl -sS -m 12 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/account > /tmp/ac.json || true
curl -sS -m 12 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json || true

python3 <<'PY'
import json
h=json.load(open('/tmp/h.json'))
sc=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('partition_usd', sc.get('partition_usd'), 'locked', sc.get('partition_usd_locked'))
print('auth', sc.get('api_auth'))

def dump(path):
    try:
        d=json.load(open(path))
    except Exception as e:
        print(path, 'ERR', e); return
    # redact
    if isinstance(d, dict):
        keys=list(d.keys())
        print(path, 'keys', keys[:30])
        for k in ('balance','wallet_balance','available','availableBalance','available_balance','free','margin',
                  'equity','unrealized','account','balances','totalWalletBalance','availableBalance',
                  'totalMarginBalance','maxWithdrawAmount','mode','testnet','error','connected'):
            if k in d:
                print(' ', k, '=', d.get(k) if not isinstance(d.get(k),(dict,list)) else json.dumps(d.get(k))[:400])
        # nested account
        acc=d.get('account') or {}
        if isinstance(acc, dict):
            for k,v in acc.items():
                if 'key' in k.lower() or 'secret' in k.lower(): continue
                print('  account.'+k, '=', v if not isinstance(v,(dict,list)) else json.dumps(v)[:300])
        # positions summary
        pos=d.get('positions') or d.get('open_positions')
        if isinstance(pos, list):
            openp=[p for p in pos if abs(float(p.get('positionAmt') or p.get('volume') or p.get('qty') or 0))>1e-12]
            print('  open_pos', len(openp))
            for p in openp[:8]:
                print('   ', {k:p.get(k) for k in ('symbol','positionAmt','positionSide','entryPrice','leverage','isolated','marginType','isolatedWallet','unRealizedProfit')})
    else:
        print(path, type(d), str(d)[:200])

for p in ('/tmp/st.json','/tmp/ac.json','/tmp/p.json'):
    dump(p)

# Direct signed balance via connector in-process if possible
import sys
sys.path.insert(0,'/opt/bilshenz/binance_trading_system/python')
print('=== CONNECTOR BALANCE ===')
try:
    # call bridge internal if exposed
    import urllib.request
    # try common endpoints
    for path in ('/api/balance','/api/wallet','/status','/api/status'):
        try:
            req=urllib.request.Request('http://127.0.0.1:8766'+path, headers={'Authorization':'Bearer '+open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")})
            d=json.loads(urllib.request.urlopen(req, timeout=8).read())
            # print numeric-looking fields
            def walk(obj, prefix=''):
                if isinstance(obj, dict):
                    for k,v in obj.items():
                        lk=k.lower()
                        if any(x in lk for x in ('bal','margin','avail','equity','wallet','free','unreal')):
                            print(path, prefix+k, '=', v if not isinstance(v,(dict,list)) else json.dumps(v)[:200])
                        elif k in ('account','balances','assets'):
                            walk(v, prefix+k+'.')
                elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
                    for i,row in enumerate(obj[:5]):
                        if str(row.get('asset','')).upper()=='USDT' or 'wallet' in json.dumps(row).lower():
                            print(path, 'row', row)
            walk(d)
        except Exception as e:
            pass
except Exception as e:
    print('connector err', e)

# Margin need math for locked partition
part=100.0
short_m = part*0.50  # ~$50 at 5x means notional $250
long_m = part*0.40   # ~$40 at 10x means notional $400
print('=== SIZING MATH (locked $100) ===')
print('short_margin_budget', short_m, 'long1', long_m, 'long2', long_m, 'full_stack_margin', short_m+long_m+long_m)
print('NOTE: undercapital claim earlier was MAINNET free~$20-37, not testnet $5000')
PY

echo '=== recent insufficient_margin on testnet day ==='
grep -E 'insufficient_margin|free=' /var/log/bilshenz/binance-api.log | tail -n 30
'''
_, o, e = c.exec_command(CMD, timeout=60)
out = o.read().decode("utf-8", "replace")
Path(__file__).with_name("_testnet-bal-out.txt").write_text(out, encoding="utf-8")
print(out.encode("ascii", "replace").decode("ascii")[:14000])
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR:", err.encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
