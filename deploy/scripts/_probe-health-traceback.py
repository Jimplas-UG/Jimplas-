#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
# Full traceback around last health 500
python3 - <<'PY'
from pathlib import Path
p=Path('/var/log/bilshenz/binance-api.log')
text=p.read_text(errors='replace')
idx=text.rfind('File "/opt/bilshenz/binance_trading_system/python/main.py", line 708')
print('idx', idx)
if idx<0:
    idx=text.rfind('GET /health')
chunk=text[max(0,idx-500):idx+2500]
print(chunk)
PY
echo '=== ban left ==='
python3 - <<'PY'
import json,time
b=json.load(open('/var/lib/bilshenz/rest-ban.json'))
print('until', b, 'left_s', round(b['until_epoch']-time.time(),1))
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-400:])
    c.close()

if __name__ == "__main__":
    main()
