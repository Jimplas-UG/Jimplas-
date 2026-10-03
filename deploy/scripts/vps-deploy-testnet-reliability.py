#!/usr/bin/env python3
"""Deploy testnet reliability ops fixes (no strategy knob changes)."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/execution_engine.py",
    "binance_trading_system/python/main.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py execution_engine.py main.py
{PY} - <<'PY'
import binance_connector as bc
from frozen_strategy import assert_frozen_contract
d = bc.BinanceConnector.__new__(bc.BinanceConnector)
d._api_auth_blocked = False
d._signed_ready = True
parsed = bc.BinanceConnector._parse_order_error(d, RuntimeError('Remote end closed connection without response'))
assert parsed['retryable'] is True, parsed
parsed2 = bc.BinanceConnector._parse_order_error(d, RuntimeError('Connection reset by peer'))
assert parsed2['retryable'] is True, parsed2
snap = assert_frozen_contract()
print('CONTRACT_OK', snap['strategy_id'], 'partition', snap['ops']['partition_usd'])
print('RETRY_REMOTE_OK')
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, time, urllib.request
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    print(i, 'mode', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'),
          'block', sc.get('exec_block'), 'part', sc.get('partition_usd'),
          'signed', (sc.get('api_auth') or {{}}).get('signed_ready'),
          'user_ws', (h.get('user_data_stream') or {{}}).get('ws_connected'))
    if h.get('connected') and sc.get('can_execute') and (sc.get('api_auth') or {{}}).get('signed_ready'):
        break
    time.sleep(1)
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/status', headers={{'Authorization':'Bearer '+tok}})
st=json.loads(urllib.request.urlopen(req, timeout=10).read())
acc=st.get('account') or {{}}
print('BALANCE', acc.get('balance'), 'equity', acc.get('equity'), 'margin_free', acc.get('margin_free'), 'server', acc.get('server'))
print('TESTNET_OK' if st.get('testnet') and float(acc.get('balance') or 0) > 1000 else 'CHECK_ACCOUNT')
PY
"""

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        remote = f"/opt/bilshenz/{rel.replace(chr(92), '/')}"
        sftp.put(str(local), remote)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()


if __name__ == "__main__":
    main()
