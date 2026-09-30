#!/usr/bin/env python3
"""Deploy restored Sep23 exit-ops lock to FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/frozen_strategy.py",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/components/OpenPositionsPanel.js",
]

CMD = r"""
set -euo pipefail
cd /opt/bilshenz/binance_trading_system/python
python3 test_frozen_strategy.py
systemctl restart bilshenz-binance-api
sleep 8
systemctl is-active bilshenz-binance-api
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c "import sys,json;d=json.load(sys.stdin);s=d.get('scanner') or {};print('mode',d.get('mode'),'exec',s.get('can_execute'),'strategy',s.get('strategy_id'),'partition',s.get('partition_usd'))"
python3 - <<'PY'
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('CONTRACT_OK', snap['ops'])
import inspect, binance_connector as bc
src=inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
assert 'max_wait_s: float = 12.0' in src
print('CLOSE_COOL_OK 12s')
import momentum_scanner as ms
src=open(ms.__file__,encoding='utf-8').read()
assert 'short_ok_for_smart' in src
print('SMART_EXIT_GUARD_OK')
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp=c.open_sftp()
    for rel in FILES:
        local=ROOT/rel.replace('/','\\')
        print('upload', rel)
        sftp.put(str(local), f'/opt/bilshenz/{rel}')
    sftp.close()
    _,o,e=c.exec_command(CMD, timeout=120)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-1500:])
    code=o.channel.recv_exit_status()
    c.close()
    return code

if __name__=='__main__':
    raise SystemExit(main())
