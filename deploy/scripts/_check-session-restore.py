#!/usr/bin/env python3
"""Inspect session restore state after halt restart."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
ls -la /var/lib/bilshenz/binance-session.json 2>/dev/null
python3 -c "import json; p='/var/lib/bilshenz/binance-session.json';
import os
print('exists', os.path.exists(p))
if os.path.exists(p):
  d=json.load(open(p))
  print('keys', list(d.keys()) if isinstance(d,dict) else type(d))
  if isinstance(d,dict):
    for k,v in d.items():
      if isinstance(v,str):
        print(k, 'len', len(v), 'preview', v[:6]+'...' if len(v)>6 else v)
      else:
        print(k, type(v).__name__, v if not isinstance(v,(dict,list)) else '...')
"
echo '=== grep restore logs ==='
journalctl -u bilshenz-binance-api --since '3 min ago' --no-pager | grep -iE 'session|restore|login|connected|api_key|SCANNER_EXEC|HALT' | tail -40
curl -sS -m 4 http://127.0.0.1:8766/health | python3 -c 'import sys,json;h=json.load(sys.stdin);print({k:h.get(k) for k in ("connected","ok")});print("scanner",h.get("scanner"));print("user",h.get("user_data_stream"))'
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_API)' /etc/bilshenz.env | sed -E 's/(BINANCE_API_KEY|BINANCE_API_SECRET)=.*/\1=***/'
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=40)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-1000:])
c.close()
