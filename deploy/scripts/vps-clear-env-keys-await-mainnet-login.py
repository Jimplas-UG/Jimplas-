#!/usr/bin/env python3
"""Clear testnet env keys after mainnet force — wait for app mainnet login. Keeps $100 lock."""
from pathlib import Path
import sys
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
set -e
python3 - <<'PY'
from pathlib import Path
import json
p=Path('/etc/bilshenz.env')
lines=[]
for line in p.read_text().splitlines():
    if line.startswith('BINANCE_API_KEY='):
        lines.append('BINANCE_API_KEY=')
    elif line.startswith('BINANCE_API_SECRET='):
        lines.append('BINANCE_API_SECRET=')
    else:
        lines.append(line)
p.write_text('\n'.join(lines)+'\n')
p.chmod(0o600)
d={}
for line in p.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); d[k]=v.strip().strip('"').strip("'")
print('cleared_env_keys key_len', len(d.get('BINANCE_API_KEY','')), 'secret_len', len(d.get('BINANCE_API_SECRET','')))
print('FORCE_MAIN', d.get('BINANCE_FORCE_MAINNET'), 'TESTNET', d.get('BINANCE_TESTNET'), 'SINCE', d.get('TRADE_HISTORY_SINCE'))
risk_p=Path('/var/lib/bilshenz/scanner-risk.json')
raw=json.loads(risk_p.read_text())
raw.update({'partition_usd':100.0,'short_pct':50.0,'long1_pct':40.0,'long2_pct':40.0,'locked':True,'partition_usd_locked':True})
risk_p.write_text(json.dumps(raw, indent=2)+'\n')
print('risk_ok', raw.get('partition_usd'), raw.get('partition_usd_locked'))
PY
rm -f /var/lib/bilshenz/binance-session.json /opt/bilshenz/binance_trading_system/python/.binance_session.json
systemctl restart bilshenz-binance-api
sleep 10
systemctl is-active bilshenz-binance-api
python3 - <<'PY'
import json, urllib.request
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=10).read().decode())
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('partition', s.get('partition_usd'), 'locked', s.get('partition_usd_locked'), 'risk_locked', s.get('risk_locked'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'strategy', s.get('strategy_id'))
assert float(s.get('partition_usd') or 0)==100.0
assert s.get('partition_usd_locked') is True
print('READY_FOR_MAINNET_APP_LOGIN')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.buffer.write(o.read())
    err = e.read()
    if err.strip():
        sys.stderr.buffer.write(b"STDERR " + err[-1000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
