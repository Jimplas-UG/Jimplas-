#!/usr/bin/env python3
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""
python3 - <<'PY'
import glob, re
files = [
  '/var/log/bilshenz/app.log',
  '/var/log/bilshenz/binance-api.log',
  '/var/log/bilshenz/websocket.log',
  '/var/log/bilshenz/trades.log',
  '/var/log/tradingbot/forward-bot.log',
]
# also newest rotated
files += sorted(glob.glob('/var/log/bilshenz/app.log.*'))[:3]
files += sorted(glob.glob('/var/log/bilshenz/binance-api.log.*'))[:3]
files += sorted(glob.glob('/var/log/bilshenz/websocket.log.*'))[:3]
pat = re.compile(r'BANKUSDT|RIFUSDT|UNIUSDT|scanner SHORT|scanner LONG|LONG1|LONG2|Pending|entered|best pending|SMART_EXIT|SHORT_TP|PULLBACK|adopted|demote|qualify')
for f in files:
  try:
    with open(f, encoding='utf-8', errors='replace') as fh:
      lines = fh.readlines()[-8000:]
  except Exception as e:
    print('skip', f, e); continue
  hits=[ln.rstrip() for ln in lines if pat.search(ln)]
  if not hits:
    continue
  print('====', f, 'hits', len(hits), '====')
  for ln in hits[-60:]:
    print(ln[-450:])
PY
"""
def main():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
if __name__ == "__main__":
    raise SystemExit(main())
