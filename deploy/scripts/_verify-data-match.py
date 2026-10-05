#!/usr/bin/env python3
"""Verify positions fields match Binance after deploy; re-login if needed."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, json, time, hmac, hashlib, urllib.request, urllib.parse
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session, save_binance_session
s=load_binance_session() or {}
key=(s.get('api_key') or os.environ.get('BINANCE_API_KEY','')).strip()
sec=(s.get('api_secret') or os.environ.get('BINANCE_API_SECRET','')).strip()
tok=os.environ.get('BRIDGE_TOKEN','').strip()

# ensure connected
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
print('connected0', h.get('connected'))
if not h.get('connected') and key and sec:
    body=json.dumps({'api_key':key,'api_secret':sec,'testnet':False}).encode()
    req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST',
        headers={'Content-Type':'application/json','Authorization':f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=40) as r:
        print('relogin', json.loads(r.read()).get('ok'))
    time.sleep(2)

params={'timestamp': int(time.time()*1000)}
qs=urllib.parse.urlencode(params)
sig=hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
req=urllib.request.Request(f'https://fapi.binance.com/fapi/v2/positionRisk?{qs}&signature={sig}', headers={'X-MBX-APIKEY': key})
with urllib.request.urlopen(req, timeout=12) as r:
    risk=json.loads(r.read())
bin_pos=[p for p in risk if abs(float(p.get('positionAmt') or 0))>0]

reqp=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':f'Bearer {tok}'})
bot=json.loads(urllib.request.urlopen(reqp, timeout=10).read())
reqs=urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization':f'Bearer {tok}'})
st=json.loads(urllib.request.urlopen(reqs, timeout=10).read())
acct=st.get('account') or {}
print('connected', st.get('connected'), 'bal', acct.get('balance'), 'profit', acct.get('profit'))
print('bot_n', len(bot.get('positions') or []), 'bin_n', len(bin_pos))
ok_all=True
for bp in bin_pos:
    sym=bp.get('symbol')
    match=next((x for x in (bot.get('positions') or []) if x.get('symbol')==sym), None)
    be=float(bp.get('entryPrice') or 0); bm=float(bp.get('markPrice') or 0); bpnl=float(bp.get('unRealizedProfit') or 0); blev=int(float(bp.get('leverage') or 0))
    print('BIN', sym, 'entry', be, 'mark', bm, 'pnl', bpnl, 'lev', blev)
    if not match:
        print('MISSING_BOT'); ok_all=False; continue
    oe=float(match.get('price_open') or 0); om=float(match.get('markPrice') or 0); opnl=float(match.get('profit') or 0); olev=int(match.get('leverage') or 0)
    print('BOT', sym, 'entry', oe, 'mark', om, 'pnl', opnl, 'lev', olev)
    print('diffs entry', abs(be-oe), 'mark', abs(bm-om), 'pnl', abs(bpnl-opnl), 'lev_ok', olev==blev, 'has_mark', om>0)
    if abs(be-oe)>1e-8 or abs(bpnl-opnl)>1e-6 or olev!=blev or not (om>0):
        ok_all=False
print('MATCH_OK' if ok_all else 'MATCH_DRIFT')
sc=(json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read()).get('scanner') or {})
print('can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
PY
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err=e.read().decode("utf-8", "replace")
if err.strip():
    print(err.encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
