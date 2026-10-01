#!/usr/bin/env python3
"""Compare Binance REST truth vs bridge bot state for mismatch forensics."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"
OUT = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "_mismatch_out.txt"

CMD = r'''
set +e
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 8 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/bot_pos.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status > /tmp/bot_st.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/bot_d.json
cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, json, time, hmac, hashlib, urllib.request, urllib.parse
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session
s=load_binance_session() or {}
key=(s.get('api_key') or os.environ.get('BINANCE_API_KEY','')).strip()
sec=(s.get('api_secret') or os.environ.get('BINANCE_API_SECRET','')).strip()

def signed(path, params=None):
    params=dict(params or {})
    params['timestamp']=int(time.time()*1000)
    qs=urllib.parse.urlencode(params)
    sig=hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url=f'https://fapi.binance.com{path}?{qs}&signature={sig}'
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY': key})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())

acct=signed('/fapi/v2/account')
risk=signed('/fapi/v2/positionRisk')
open_orders=signed('/fapi/v1/openOrders')

usdt=None
for a in acct.get('assets') or []:
    if a.get('asset')=='USDT':
        usdt=a; break

bin_pos=[]
for r in risk:
    try:
        amt=float(r.get('positionAmt') or 0)
    except Exception:
        amt=0
    if abs(amt)>0:
        bin_pos.append({
            'symbol': r.get('symbol'),
            'positionAmt': r.get('positionAmt'),
            'entryPrice': r.get('entryPrice'),
            'markPrice': r.get('markPrice'),
            'unRealizedProfit': r.get('unRealizedProfit'),
            'leverage': r.get('leverage'),
            'positionSide': r.get('positionSide'),
            'notional': r.get('notional'),
            'isolatedMargin': r.get('isolatedMargin'),
            'updateTime': r.get('updateTime'),
        })

h=json.load(open('/tmp/h.json'))
bot_pos=json.load(open('/tmp/bot_pos.json'))
bot_st=json.load(open('/tmp/bot_st.json'))
bot_d=json.load(open('/tmp/bot_d.json'))
sc=h.get('scanner') or {}

print('=== BINANCE TRUTH ===')
print('wallet', usdt.get('walletBalance') if usdt else None,
      'avail', usdt.get('availableBalance') if usdt else None,
      'crossUnPnl', acct.get('totalUnrealizedProfit'),
      'canTrade', acct.get('canTrade'))
print('bin_open_n', len(bin_pos))
for r in bin_pos:
    print('BIN', r)
print('open_orders_n', len(open_orders) if isinstance(open_orders, list) else open_orders)

print('=== BOT ===')
print('connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
print('partition', sc.get('partition_usd'), 'strategy', sc.get('strategy_id'))
print('bot_status_bal', bot_st.get('balance') or bot_st.get('account') or {k:bot_st.get(k) for k in list(bot_st.keys())[:20]})
print('bot_pos_ok', bot_pos.get('ok'), 'stale', bot_pos.get('stale'), 'cool', bot_pos.get('rest_cool_s'), 'n', len(bot_pos.get('positions') or []))
for r in (bot_pos.get('positions') or []):
    if isinstance(r, dict):
        print('BOT', {k:r.get(k) for k in ('symbol','side','positionSide','volume','positionAmt','entry_price','entryPrice','price','mark','markPrice','profit','unRealizedProfit','leverage','ticket')})

# mismatch summary
bot_syms=set()
for r in (bot_pos.get('positions') or []):
    if isinstance(r, dict) and r.get('symbol'):
        bot_syms.add(str(r['symbol']).upper())
bin_syms=set(r['symbol'] for r in bin_pos)
print('=== DIFF ===')
print('only_binance', sorted(bin_syms-bot_syms))
print('only_bot', sorted(bot_syms-bin_syms))
print('both', sorted(bin_syms & bot_syms))

# streams
print('streams tick', (h.get('tick_stream') or {}).get('ws_connected'),
      'scanner', (h.get('scanner_stream') or {}).get('ws_connected'), 'rest', (h.get('scanner_stream') or {}).get('rest_active'),
      'user', (h.get('user_data_stream') or {}).get('ws_connected'),
      'user_last_err', (h.get('user_data_stream') or {}).get('last_error'),
      'events', (h.get('user_data_stream') or {}).get('events_received'))
print('diag_binance_ms', bot_d.get('binance_latency_ms'))

# recent closes / adopts
import subprocess
print('=== recent scanner/pos logs ===')
print(subprocess.check_output(['bash','-lc',"grep -iE 'adopt|mismatch|MOVR|SHORT|LONG|close|position|EXEC_|USER_WS|stale|mark' /var/log/bilshenz/binance-api.log | tail -50"], text=True, errors='replace'))
PY
'''

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    OUT.write_text(out + ("\n---stderr---\n" + err if err.strip() else ""), encoding="utf-8")
    print(out.encode("ascii", "replace").decode("ascii"))
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    print("WROTE", OUT)
    c.close()

if __name__ == "__main__":
    main()
