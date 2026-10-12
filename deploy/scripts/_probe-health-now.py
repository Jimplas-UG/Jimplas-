#!/usr/bin/env python3
"""Live /health + 418/weight log tail after deploy."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, urllib.request
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('LIVE', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'),
      'block', sc.get('exec_block') or sc.get('exec_block_reason'), 'cool', h.get('rest_cool_s'))
PY
echo '--- last 418/weight lines'
grep -hE "418 IP ban|used weight|Binance 429" /var/log/bilshenz/*.log | tail -n 8
echo '--- 418/429 lines last 10 min'
since=$(date -u -d '-10 min' +%Y-%m-%dT%H:%M)
cat /var/log/bilshenz/*.log | awk -v s="$since" '$1 >= s' | grep -cE "418|429"
echo '--- positions log lines last 10 min'
cat /var/log/bilshenz/*.log | awk -v s="$since" '$1 >= s' | grep -c "\[binance_connector\] positions"
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-600:])
    c.close()


if __name__ == "__main__":
    main()
