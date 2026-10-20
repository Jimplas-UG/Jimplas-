#!/usr/bin/env python3
from pathlib import Path
import hashlib
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
local = ROOT / "binance_trading_system/python/momentum_scanner.py"
local_hash = hashlib.sha256(local.read_bytes()).hexdigest()
local_size = local.stat().st_size
print("LOCAL", local_size, local_hash)
print("LOCAL has prep", b"leverage_5x_prepare_failed" in local.read_bytes())

CMD = r"""
python3 - <<'PY'
import hashlib, pathlib, inspect, sys
sys.path.insert(0, '/opt/bilshenz/binance_trading_system/python')
p = pathlib.Path('/opt/bilshenz/binance_trading_system/python/momentum_scanner.py')
data = p.read_bytes()
print('REMOTE_FILE', len(data), hashlib.sha256(data).hexdigest())
print('REMOTE_FILE has prep', b'leverage_5x_prepare_failed' in data)
print('REMOTE_FILE has snapshot call', b'self._snapshot_symbol_legs_to_sticky(coin)' in data)
# show surrounding lines
text = data.decode('utf-8', 'replace')
idx = text.find('leverage_5x_prepare_failed')
print('idx', idx)
if idx > 0:
    print(repr(text[idx-120:idx+80]))
import momentum_scanner as ms
print('module_file', ms.__file__)
s = inspect.getsource(ms.MomentumScanner._execute_pending_short)
print('inspect_len', len(s))
print('inspect has prep', 'leverage_5x_prepare_failed' in s)
print('inspect has snapshot', '_snapshot_symbol_legs_to_sticky' in s)
# print last 800 chars of inspect source
print('TAIL')
print(s[-800:])
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    # force put again binary
    sftp = c.open_sftp()
    sftp.put(str(local), "/opt/bilshenz/binance_trading_system/python/momentum_scanner.py")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    print(e.read().decode("utf-8", "replace")[-1000:])
    c.close()

if __name__ == "__main__":
    main()
