#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
journalctl -u bilshenz-binance-api --since '5 min ago' --no-pager 2>/dev/null | tr -cd '\11\12\15\40-\176\n' | grep -Ei 'session|login|testnet|mainnet|restored|auto-switch|Invalid API|FORCE|configure' | tail -n 50
echo === SESSION_FILES ===
python3 - <<'PY'
import json, os, glob
paths = glob.glob('/var/lib/bilshenz/*session*') + glob.glob('/opt/bilshenz/**/*session*.json', recursive=True)
for p in paths[:10]:
  try:
    j=json.load(open(p))
    print(p, {k: ('***' if 'key' in k.lower() or 'secret' in k.lower() else j.get(k)) for k in j})
  except Exception as e:
    print(p, e)
PY
echo === HEALTH ===
curl -sS http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print({ "mode":h.get("mode"), "connected":h.get("connected"), "can_execute":s.get("can_execute"), "exec_block":s.get("exec_block") })'
"""


def main() -> int:
    if not PASSWORD:
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
