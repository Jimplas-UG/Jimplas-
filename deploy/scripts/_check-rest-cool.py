#!/usr/bin/env python3
from pathlib import Path
import paramiko

pkey = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
cmd = r"""
grep -n "max_wait_s\|_wait_or_clear_cool\|_engage_rest_cool\|CLOSE_REST\|rest_cooling_left\|clear_rest_cool" \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py \
  /opt/bilshenz/binance_trading_system/python/frozen_strategy.py | head -50
echo '---'
python3 - <<'PY'
import urllib.request, json
h=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=3))
print('rest_cool_s', h.get('rest_cool_s'))
print('ok', h.get('ok'))
PY
"""
_, o, e = c.exec_command(cmd, timeout=25)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR:", err)
c.close()
