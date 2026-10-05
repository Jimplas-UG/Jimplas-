#!/usr/bin/env python3
"""Fix BRIDGE_TOKEN if empty; verify session restore + halt; no secret printing."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
python3 <<'PY'
from pathlib import Path
import re

def parse_env(text: str) -> dict:
    text = text.replace('\\n', '\n')
    kv = {}
    for ln in text.splitlines():
        if not ln.strip() or ln.strip().startswith('#') or '=' not in ln:
            continue
        k, v = ln.split('=', 1)
        k = k.strip()
        if k and k not in kv:
            kv[k] = v
    return kv

sources = []
for p in [
    Path('/etc/bilshenz.env.smashed.bak'),
    Path('/etc/bilshenz.env.pre-repair'),
    Path('/etc/bilshenz.env'),
]:
    if p.exists():
        sources.append((p, parse_env(p.read_text(encoding='utf-8', errors='replace'))))

# find best BRIDGE_TOKEN
best_tok = ''
best_src = None
for p, kv in sources:
    tok = (kv.get('BRIDGE_TOKEN') or '').strip().strip('"').strip("'")
    print(f'{p.name}: BRIDGE_TOKEN_len={len(tok)} SESSION_ENC_len={len((kv.get("SESSION_ENC_KEY") or "").strip())} APIKEY_len={len((kv.get("BINANCE_API_KEY") or "").strip())}')
    if len(tok) > len(best_tok):
        best_tok = tok
        best_src = p

cur = parse_env(Path('/etc/bilshenz.env').read_text(encoding='utf-8', errors='replace'))
# Prefer tokens from backup if current empty
if len((cur.get('BRIDGE_TOKEN') or '').strip()) < 8 and best_tok:
    cur['BRIDGE_TOKEN'] = best_tok
    print('RESTORED_BRIDGE_TOKEN_FROM', best_src, 'len', len(best_tok))

# Mainnet live prefs (do not touch strategy knobs beyond halt)
cur['SCANNER_EXEC'] = '0'
cur['FORWARD_DRY_RUN'] = '1'
cur['BINANCE_FORCE_MAINNET'] = '1'
cur['BINANCE_FORCE_TESTNET'] = '0'
cur['BINANCE_TESTNET'] = '0'  # avoid conflicting with FORCE_MAINNET
cur['BINANCE_PAPER'] = '0'

# keep TRADE_HISTORY_SINCE if present
order = list(cur.keys())
# stable preferred order head
head = [
 'HOST','PORT','BILSHENZ_ENV','PRODUCTION_MODE','LOG_DIR',
 'BRIDGE_TOKEN','DESK_API_KEY','DESK_API_PORT','AUTH_JWT_SECRET','SESSION_ENC_KEY',
 'BINANCE_API_KEY','BINANCE_API_SECRET','BINANCE_TESTNET','BINANCE_FORCE_TESTNET','BINANCE_FORCE_MAINNET',
 'BINANCE_PAPER','BINANCE_SYMBOL','BINANCE_LEVERAGE','BINANCE_MARGIN_TYPE',
 'SCANNER_ENABLED','SCANNER_EXEC','FORWARD_DRY_RUN','FORWARD_SYMBOLS','FORWARD_MAX_SYMBOLS','FORWARD_POLL_SEC',
 'TRADE_HISTORY_SINCE','STRATEGY_FREEZE'
]
seen=set(); lines=[]
for k in head + order:
    if k in seen or k not in cur: continue
    seen.add(k)
    lines.append(f'{k}={cur[k]}')
Path('/etc/bilshenz.env').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print('WRITTEN lines', len(lines))
for k in ('BRIDGE_TOKEN','SESSION_ENC_KEY','DESK_API_KEY','BINANCE_API_KEY','BINANCE_API_SECRET'):
    v=(cur.get(k) or '').strip().strip('"').strip("'")
    print(f'{k} len={len(v)}')
for k in ('SCANNER_EXEC','FORWARD_DRY_RUN','BINANCE_FORCE_MAINNET','BINANCE_TESTNET','TRADE_HISTORY_SINCE'):
    print(f'{k}={cur.get(k)}')
PY

systemctl restart bilshenz-binance-api bilshenz-forward-bot bilshenz-desk-api
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot bilshenz-desk-api

cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, json, urllib.request, time
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session
s=load_binance_session()
print('session_file_ok', bool(s))

for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'connected', h.get('connected'), 'block', sc.get('exec_block'), 'can', sc.get('can_execute'),
          'user', (h.get('user_data_stream') or {}).get('ws_connected'),
          'tick', (h.get('tick_stream') or {}).get('ws_connected'))
    if h.get('connected'):
        break
    time.sleep(1)

# diagnostics should be fast
tok=os.environ.get('BRIDGE_TOKEN','')
req=urllib.request.Request('http://127.0.0.1:8766/api/diagnostics', headers={'Authorization': f'Bearer {tok}'})
t0=time.perf_counter()
d=json.loads(urllib.request.urlopen(req, timeout=8).read())
print('diag_ms', round((time.perf_counter()-t0)*1000,1), 'ok', d.get('ok'),
      'user_ws', (d.get('user_data_stream') or {}).get('ws_connected'),
      'scanner_ws', (d.get('scanner_stream') or {}).get('ws_connected'),
      'binance_ms', d.get('binance_latency_ms'))
pos=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization': f'Bearer {tok}'}), timeout=8).read())
print('open_n', len(pos.get('positions') or []))
PY
journalctl -u bilshenz-binance-api --since '25 seconds ago' --no-pager | grep -iE 'session|persisted|restore|mismatch|connected|mainnet|SCANNER_EXEC' | tail -30
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=120)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print('STDERR', err.encode("ascii", "replace").decode("ascii")[-2000:])
c.close()
