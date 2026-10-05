#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r'''
systemctl is-active bilshenz-binance-api
# quick health with short timeout
curl -sS -m 3 http://127.0.0.1:8766/health | head -c 800 || echo HEALTH_TIMEOUT
echo
# find margin fails + which day/mode context
echo '=== margin fails chronologically ==='
grep -n 'insufficient_margin' /var/log/bilshenz/binance-api.log | tail -n 20
echo '=== mode lines around last margin fail ==='
# show testnet/mainnet markers near oct1 vs oct2/3
grep -E 'mode=|testnet|FORCE_MAINNET|login ok|account_ok|insufficient_margin' /var/log/bilshenz/binance-api.log | tail -n 40
# try balance via python connector with hard timeout
timeout 15 /opt/bilshenz/binance_trading_system/python/.venv/bin/python - <<'PY' || echo BAL_TIMEOUT
import os, json
# load env
for ln in open('/etc/bilshenz.env'):
    if '=' in ln and not ln.startswith('#'):
        k,v=ln.split('=',1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
print('ENV testnet', os.environ.get('BINANCE_TESTNET'), 'force_tn', os.environ.get('BINANCE_FORCE_TESTNET'), 'force_mn', os.environ.get('BINANCE_FORCE_MAINNET'))
print('key_len', len(os.environ.get('BINANCE_API_KEY') or ''))
# hit health via unix? skip if hung
import urllib.request
try:
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=2).read())
    print('health mode', h.get('mode'), 'connected', h.get('connected'), 'part', (h.get('scanner') or {}).get('partition_usd'))
except Exception as e:
    print('health', e)
PY
'''
_,o,e=c.exec_command(CMD, timeout=40)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-800:])
c.close()
