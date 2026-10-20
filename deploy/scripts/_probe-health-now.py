#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, time, pathlib, urllib.request, glob, re
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
uds=h.get('user_data_stream') or {}
print('NOW', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
print('connected', h.get('connected'), 'mode', h.get('mode'), 'testnet', h.get('testnet'))
print('cool', h.get('rest_cool_s'), 'can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('tracked', sc.get('symbols_tracked'), 'active', sc.get('active_symbol'),
      'idle_ms', sc.get('reconcile_idle_ms'), 'partition', sc.get('partition_usd'))
print('user_ws', uds.get('ws_connected'), 'open_positions', h.get('open_positions'))
p=pathlib.Path('/var/lib/bilshenz/rest-ban.json')
if p.exists():
    b=json.loads(p.read_text())
    left=round(float(b.get('until_epoch') or 0)-time.time(),1)
    print('ban_left', left, 'host', b.get('host'))
else:
    print('ban_left', 0, 'none')
# last 5 min: 418 / weight / EXEC
since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-300))
lines=[]
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if l.startswith('2026-') and l[:16] >= since[:16]:
            lines.append(l)
n418=sum(1 for l in lines if '418 IP ban' in l)
nweight=sum(1 for l in lines if 'used weight' in l)
nexec=sum(1 for l in lines if 'EXEC_OK' in l or 'EXEC ' in l)
print('last5m lines', len(lines), '418', n418, 'weight_warn', nweight)
weights=[]
for l in lines:
    m=re.search(r'used weight (\d+(?:\.\d+)?)/2400', l)
    if m: weights.append(float(m.group(1)))
if weights:
    print('weight_max_5m', max(weights), 'last', weights[-1])
else:
    print('weight_max_5m', 'quiet')
# services
import subprocess
print('services', subprocess.getoutput('systemctl is-active bilshenz-binance-api bilshenz-forward-bot'))
print('THROTTLE', 'share' in open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read() and 'POSITIONS_SHARE_FLAT_S' in open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read())
print('IDLE_CONST', 'RECONCILE_IDLE_MS' in open('/opt/bilshenz/binance_trading_system/python/momentum_scanner.py').read())
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-500:])
    c.close()

if __name__ == "__main__":
    main()
