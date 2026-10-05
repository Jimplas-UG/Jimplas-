#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS --max-time 15 http://127.0.0.1:8766/api/scanner/snapshot > /tmp/snap.json 2>/dev/null || echo '{}' > /tmp/snap.json
python3 <<'PY'
import json, subprocess
h=json.load(open('/tmp/h.json')); s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('active', s.get('active_symbol'))
print('last_exec_error', s.get('last_exec_error'))
print('partition_usd', s.get('partition_usd'))
print('can_execute', s.get('can_execute'), 'auth', s.get('api_auth'))
print('--- events ---')
for e in (s.get('execution_events') or [])[-20:]:
    print(json.dumps(e)[:400])
print('--- rows ---')
try:
    rows=json.load(open('/tmp/snap.json')).get('rows') or []
except Exception:
    rows=[]
for r in rows:
    st=str(r.get('status') or '')
    sym=r.get('symbol')
    if sym == 'CTUSDT' or st not in ('Scanning','') and 'CT' in str(sym or ''):
        print(json.dumps({k:r.get(k) for k in (
            'symbol','status','pct15m','adverse_pct','short_adverse','price','detail','note',
            'legs','short','long1','long2','pnl','entry'
        )}, default=str)[:600])
    elif st not in ('Scanning',''):
        print('ROW', sym, st, json.dumps(r)[:350])
PY
echo '--- CTUSDT log ---'
grep -E 'CTUSDT|LONG2|insufficient_margin|Long 2|long2' /var/log/bilshenz/binance-api.log | tail -n 40
echo '--- balance/pos via python ---'
cd /opt/bilshenz/binance_trading_system/python && python3 <<'PY'
import os, json
# try to read session
p='/var/lib/bilshenz/binance-session.json'
print('session keys', list(json.load(open(p)).keys()) if os.path.exists(p) else 'missing')
try:
    sess=json.load(open(p))
    # redact secrets
    safe={k:v for k,v in sess.items() if 'key' not in k.lower() and 'secret' not in k.lower() and 'token' not in k.lower()}
    print(json.dumps(safe, default=str)[:1500])
except Exception as e:
    print(e)
PY
"""
_, o, e = c.exec_command(CMD, timeout=60)
out = o.read().decode("utf-8", "replace")
err = e.read().decode("utf-8", "replace")
out_path = Path(__file__).with_name("_ctusdt-out.txt")
out_path.write_text(out + (("\nSTDERR:\n" + err[-800:]) if err.strip() else ""), encoding="utf-8")
print(out_path.read_text(encoding="utf-8").encode("ascii", "replace").decode("ascii"))
c.close()
