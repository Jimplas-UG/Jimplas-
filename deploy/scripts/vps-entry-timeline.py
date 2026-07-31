#!/usr/bin/env python3
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""
python3 - <<'PY'
import re
path='/var/log/bilshenz/app.log'
with open(path, encoding='utf-8', errors='replace') as fh:
    lines=fh.readlines()
# focus today short-first window
want=re.compile(r'BANKUSDT|RIFUSDT|UNIUSDT')
key=re.compile(r'scanner SHORT |Pending|entered|executing|best pending|demote|LONG1|LONG2|SHORT_TP|SMART_EXIT|adopted|qualify|cooldown|EXEC_OK|status=')
for ln in lines:
    if '2026-07-31T13:' not in ln and '2026-07-31T12:5' not in ln and '2026-07-31T12:4' not in ln:
        # also 13:08 deploy window through now - actually include all Jul 31 afternoon for BANK open ~13:09
        if '2026-07-31T1' not in ln:
            continue
    if want.search(ln) and (key.search(ln) or 'SELL' in ln or 'BUY' in ln):
        print(ln.rstrip()[-480:])
PY
"""
def main():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    c.close()
if __name__ == "__main__":
    raise SystemExit(main())
